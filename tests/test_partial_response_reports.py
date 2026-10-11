"""Offline HTTP 206 evidence contracts through the collector, CLI, and MCP.

Only connection establishment and DNS are replaced. Real HTTPResponse objects
read framed in-memory bytes through the direct and proxy transport functions.
"""
from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from http.client import HTTPResponse
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.parse
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from seo_agent_suite import cli, mcp_server  # noqa: E402
from seo_agent_suite.comparison_metadata import validate_site_comparison_metadata  # noqa: E402

URL = "https://example.invalid/"
METADATA = {
    "title": "has_title",
    "description": "has_meta_description",
    "canonical": "has_canonical",
    "og_title": "has_og_title",
    "json_ld": "has_json_ld",
}
EMPTY_HTML = b"<html><head></head><body></body></html>"
ALL_HTML = (
    '<head><title>Observed title</title>'
    '<meta name="description" content="Observed description">'
    f'<link rel="canonical" href="{URL}">'
    '<meta property="og:title" content="Observed social title">'
    '<script type="application/ld+json">{"@type":"WebPage"}</script></head>'
    '<body><h1>Observed heading</h1></body>'
).encode()


class MemorySocket:
    def __init__(self, wire):
        self.wire = wire

    def makefile(self, mode):
        return io.BytesIO(self.wire)


def framed_response(body, *, status, media, headers=(), declared_length=None):
    length = len(body) if declared_length is None else declared_length
    lines = [f"HTTP/1.1 {status} Test", f"Content-Type: {media}",
             f"Content-Length: {length}", *headers]
    if status == 206 and body:
        lines.append(f"Content-Range: bytes 0-{len(body) - 1}/{len(body) + 100}")
    wire = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    response = HTTPResponse(MemorySocket(wire))
    response.begin()
    return response


class FakeMCP:
    """Register the actual wrapper without installing optional MCP transport."""

    def __init__(self, *args, **kwargs):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function
        return register


def without_timestamps(value):
    if isinstance(value, dict):
        return {key: without_timestamps(item) for key, item in value.items()
                if key != "collected_at"}
    if isinstance(value, list):
        return [without_timestamps(item) for item in value]
    return value


class PartialResponseReportTests(unittest.TestCase):
    def setUp(self):
        self.site = cli.load_script("site_meta_audit.py")
        self.http = self.site.public_http

    @contextmanager
    def transport(self, body, *, proxied, status=206, media="text/html",
                  headers=(), declared_length=None, resource_status=200):
        connections = []
        requests = []

        def connection(*args, **kwargs):
            conn = Mock()
            connections.append(conn)

            def request(method, path, headers):
                self.assertEqual(method, "GET")
                requests.append(path)
                if path == "/":
                    response = framed_response(
                        body, status=status, media=media, headers=page_headers,
                        declared_length=declared_length,
                    )
                else:
                    self.assertIn(path, ("/robots.txt", "/sitemap.xml"))
                    if resource_status is None:
                        raise TimeoutError("synthetic resource timeout")
                    resource_body, resource_media = (
                        (b"User-agent: *\nAllow: /\n", "text/plain")
                        if path == "/robots.txt" else
                        (b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>',
                         "application/xml")
                    )
                    response = framed_response(
                        resource_body, status=resource_status, media=resource_media,
                    )
                conn.getresponse.return_value = response

            conn.request.side_effect = request
            return conn

        page_headers = headers
        endpoint = (self.http.socket.AF_INET, self.http.socket.SOCK_STREAM,
                    6, "", ("8.8.8.8", 443))
        proxy = urllib.parse.urlparse("http://proxy.invalid:8080") if proxied else None
        with patch.object(self.http.socket, "getaddrinfo", return_value=[endpoint]), \
                patch.object(self.http.socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(self.http, "select_proxy", return_value=proxy), \
                patch.object(self.http, "PinnedHTTPSConnection", side_effect=connection) as direct, \
                patch.object(self.http, "ProxyPinnedHTTPSConnection", side_effect=connection) as proxy_connection:
            yield requests
        self.assertTrue(connections)
        self.assertEqual(direct.call_count, 0 if proxied else len(connections))
        self.assertEqual(proxy_connection.call_count, len(connections) if proxied else 0)
        for conn in connections:
            conn.close.assert_called_once()

    def collect(self, body=EMPTY_HTML, *, proxied, expected_exit=0, **options):
        with self.transport(body, proxied=proxied, **options):
            raw = self.site.audit(URL)
            with redirect_stdout(io.StringIO()) as output:
                exit_code = cli.main(["site-meta", URL, "--json"])
            package = json.loads(output.getvalue())
            with patch.object(mcp_server, "_require_mcp", return_value=FakeMCP):
                server = mcp_server.build_server()
            mcp = json.loads(server.tools["site_meta"](URL))
        self.assertEqual(exit_code, expected_exit)
        self.assertEqual(mcp["exit_code"], expected_exit)
        self.assertEqual(without_timestamps(package), without_timestamps(
            {key: value for key, value in mcp.items() if key != "exit_code"}))
        for result in (package, mcp):
            for key, value in raw.items():
                if key not in {"findings", "collected_at"}:
                    self.assertEqual(without_timestamps(result[key]), without_timestamps(value), key)
            self.assertEqual([f["code"] for f in result["findings"] if "code" in f],
                             [f["code"] for f in raw["findings"]])
            self.assertEqual(validate_site_comparison_metadata(result), [])
        return raw, (package, mcp)

    def assert_metadata(self, results, expected):
        for result in results:
            findings = {f["id"]: f for f in result["findings"]
                        if f["id"].startswith("site.meta.")}
            self.assertEqual(set(findings), {f"site.meta.{name}.{state}"
                                             for name, state in expected.items()})
            for name, state in expected.items():
                finding = findings[f"site.meta.{name}.{state}"]
                self.assertEqual(finding["status"],
                                 {"unknown": "unknown", "present": "pass", "missing": "fail"}[state])
                self.assertEqual(finding["confidence"],
                                 "hypothesis" if state == "unknown" else "confirmed")
                if state == "missing":
                    self.assertIn("action", finding)
                else:
                    self.assertNotIn("action", finding)
                if state == "unknown":
                    self.assertEqual(finding["severity"], "info")
                    self.assertIn({"kind": "json_pointer", "path": f"/checks/{METADATA[name]}"},
                                  finding["evidence"])
                    self.assertIn({"kind": "json_pointer", "path": "/capture/body_truncated"},
                                  finding["evidence"])
                    self.assertIn({"kind": "json_pointer", "path": "/page/http_status"},
                                  finding["evidence"])

    def assert_partial_capture(self, raw, results, *, truncated=False):
        for result in (raw, *results):
            self.assertEqual(result["page"]["http_status"], 206)
            self.assertIs(result["page"]["body_truncated"], truncated)
            self.assertIs(result["capture"]["body_truncated"], truncated)
            self.assertIsNone(result["assessment"]["json_ld_parse_valid"])
            codes = {f["code"] for f in result["findings"] if "code" in f}
            self.assertIn("capture_incomplete", codes)
            self.assertNotIn("title_missing", codes)
            self.assertNotIn("meta_description_missing", codes)
        for result in results:
            comparison = result["comparison"]
            self.assertEqual(comparison["collection"]["completion"], "unknown")
            self.assertIn("missing_capture_evidence", comparison["collection"]["reasons"])
            self.assertEqual(comparison["target"]["identity_state"], "unknown")
            self.assertEqual(comparison["scope"]["resources"], "excluded")
            for row in comparison["evaluations"]:
                self.assertEqual(row["outcome"], "unknown")
                self.assertEqual(row["completion"], "incomplete")
                self.assertEqual(row["reason"], "missing_capture_evidence")

    def test_untruncated_206_absence_is_unknown_in_primary_findings(self):
        for proxied in (False, True):
            with self.subTest(proxied=proxied):
                raw, results = self.collect(proxied=proxied)
                self.assert_partial_capture(raw, results)
                self.assert_metadata(results, dict.fromkeys(METADATA, "unknown"))
                for result in (raw, *results):
                    self.assertIsNone(result["assessment"]["indexing"]["noindex"])
                    self.assertEqual(result["assessment"]["canonical"]["status"], "unknown")
                    self.assertTrue(all(result["checks"][key] is False for key in METADATA.values()))
                for result in results:
                    self.assertEqual(result["status"], "ok")
                    for row in result["comparison"]["evaluations"]:
                        self.assertEqual(row["legacy_finding_ids"], [row["rule_id"] + ".unknown"])

    def test_observed_title_is_present_while_other_206_metadata_is_unknown(self):
        for proxied in (False, True):
            with self.subTest(proxied=proxied):
                raw, results = self.collect(b"<head><title>Observed title</title></head>", proxied=proxied)
                self.assert_partial_capture(raw, results)
                self.assert_metadata(results, {**dict.fromkeys(METADATA, "unknown"), "title": "present"})
                self.assertEqual(raw["title"], "Observed title")

    def test_observed_206_metadata_survives_but_canonical_validation_stays_unknown(self):
        for proxied in (False, True):
            with self.subTest(proxied=proxied):
                raw, results = self.collect(ALL_HTML, proxied=proxied)
                self.assert_partial_capture(raw, results)
                self.assert_metadata(results, dict.fromkeys(METADATA, "present"))
                for result in (raw, *results):
                    canonical = result["assessment"]["canonical"]
                    self.assertEqual(canonical["status"], "unknown")
                    self.assertEqual(canonical["targets"], [URL])
                    self.assertEqual(canonical["declaration_count"], 1)
                    self.assertIsNone(result["assessment"]["indexing"]["noindex"])
                    self.assertEqual(result["json_ld"][0]["status"], "parsed")
                    self.assertIn("canonical_unknown", {f["code"] for f in result["findings"] if "code" in f})

    def test_observed_noindex_remains_confirmed_on_a_206(self):
        cases = (
            (b'<head><meta name="robots" content="noindex,follow"></head>', (), "meta"),
            (b'<head><meta name="googlebot" content="none"></head>', (), "meta"),
            (EMPTY_HTML, ("X-Robots-Tag: googlebot: noindex",), "x_robots_tag"),
        )
        for proxied in (False, True):
            for body, headers, source in cases:
                with self.subTest(proxied=proxied, source=source, body=body):
                    raw, results = self.collect(body, proxied=proxied, headers=headers)
                    self.assert_partial_capture(raw, results)
                    self.assert_metadata(results, dict.fromkeys(METADATA, "unknown"))
                    for result in (raw, *results):
                        indexing = result["assessment"]["indexing"]
                        self.assertIs(indexing["noindex"], True)
                        self.assertEqual(indexing["indexed"], "unknown")
                        self.assertIn(source, {item["source"] for item in indexing["evidence"]})
                    for result in results:
                        finding = next(f for f in result["findings"] if f["id"] == "site.assessment.noindex_declared")
                        self.assertEqual(finding["status"], "fail")
                        self.assertEqual(finding["confidence"], "confirmed")

    def test_observed_canonical_errors_are_not_erased_by_partial_capture(self):
        cases = (
            (b'<head><link rel="canonical" href="javascript:invalid"></head>', "invalid"),
            ((f'<head><link rel="canonical" href="{URL}">'
              f'<link rel="canonical" href="{URL}other"></head>').encode(), "conflicting"),
        )
        for proxied in (False, True):
            for body, expected in cases:
                with self.subTest(proxied=proxied, expected=expected):
                    raw, results = self.collect(body, proxied=proxied)
                    self.assert_partial_capture(raw, results)
                    self.assert_metadata(results, {**dict.fromkeys(METADATA, "unknown"), "canonical": "present"})
                    for result in (raw, *results):
                        self.assertEqual(result["assessment"]["canonical"]["status"], expected)

    def test_actual_byte_truncation_remains_separate_from_http_partial_status(self):
        prefix = b"<head><title>Observed title</title></head>"
        body = prefix + b" " * (self.http.DEFAULT_MAX_BODY_BYTES + 1 - len(prefix))
        for proxied in (False, True):
            for status in (200, 206):
                with self.subTest(proxied=proxied, status=status):
                    raw, results = self.collect(body, proxied=proxied, status=status)
                    self.assert_metadata(results, {**dict.fromkeys(METADATA, "unknown"), "title": "present"})
                    for result in (raw, *results):
                        self.assertIs(result["page"]["body_truncated"], True)
                        self.assertIs(result["capture"]["body_truncated"], True)
                        self.assertIsNone(result["assessment"]["indexing"]["noindex"])
                        self.assertEqual(result["assessment"]["canonical"]["status"], "unknown")
                    if status == 206:
                        self.assert_partial_capture(raw, results, truncated=True)
                    else:
                        for result in results:
                            for row in result["comparison"]["evaluations"]:
                                self.assertEqual(row["outcome"], "pass" if row["rule_id"] == "site.meta.title" else "unknown")

    def test_complete_200_still_confirms_absence_and_no_noindex(self):
        for proxied in (False, True):
            with self.subTest(proxied=proxied):
                raw, results = self.collect(proxied=proxied, status=200)
                self.assert_metadata(results, dict.fromkeys(METADATA, "missing"))
                for result in (raw, *results):
                    self.assertIs(result["page"]["body_truncated"], False)
                    self.assertIs(result["capture"]["body_truncated"], False)
                    self.assertIs(result["assessment"]["indexing"]["noindex"], False)
                    self.assertEqual(result["assessment"]["canonical"]["status"], "missing")
                    self.assertNotIn("capture_incomplete", {f["code"] for f in result["findings"] if "code" in f})
                for result in results:
                    self.assertEqual(result["status"], "partial")
                    self.assertTrue(all(row["outcome"] == "fail" for row in result["comparison"]["evaluations"]))

    def test_complete_200_still_validates_observed_metadata(self):
        for proxied in (False, True):
            with self.subTest(proxied=proxied):
                raw, results = self.collect(ALL_HTML, proxied=proxied, status=200)
                self.assert_metadata(results, dict.fromkeys(METADATA, "present"))
                for result in (raw, *results):
                    self.assertIs(result["capture"]["body_truncated"], False)
                    self.assertIs(result["assessment"]["indexing"]["noindex"], False)
                    self.assertEqual(result["assessment"]["canonical"]["status"], "self")
                    self.assertIs(result["assessment"]["json_ld_parse_valid"], True)
                for result in results:
                    self.assertEqual(result["status"], "ok")
                    self.assertTrue(all(row["outcome"] == "pass" for row in result["comparison"]["evaluations"]))

    def test_http_errors_and_short_framed_bodies_keep_fetch_error_exits(self):
        cases = (
            {"status": 404},
            {"status": 200, "declared_length": len(EMPTY_HTML) + 10},
            {"status": 206, "declared_length": len(EMPTY_HTML) + 10},
        )
        for proxied in (False, True):
            for options in cases:
                with self.subTest(proxied=proxied, **options):
                    raw, results = self.collect(proxied=proxied, expected_exit=1, **options)
                    self.assertEqual(raw["page"]["status"], "error")
                    if "declared_length" in options:
                        self.assertIn("IncompleteRead", raw["page"]["reason"])
                    self.assert_metadata(results, {})
                    for result in results:
                        self.assertEqual(result["status"], "error")
                        self.assertIn("site.fetch.failed", {f["id"] for f in result["findings"]})
                        self.assertNotIn("checks", result)
                        self.assertTrue(all(row["outcome"] == "unknown" and row["reason"] == "page_fetch_error"
                                            for row in result["comparison"]["evaluations"]))

    def test_partial_page_does_not_change_auxiliary_resource_semantics(self):
        for proxied in (False, True):
            for resource_status in (200, 206, 403, 404, 410, None):
                with self.subTest(proxied=proxied, resource_status=resource_status):
                    raw, results = self.collect(proxied=proxied, resource_status=resource_status)
                    self.assert_partial_capture(raw, results)
                    self.assert_metadata(results, dict.fromkeys(METADATA, "unknown"))
                    expected = ("present" if resource_status == 200 else
                                "missing" if resource_status in (404, 410) else "unknown")
                    for result in results:
                        for resource in ("robots_txt", "sitemap"):
                            finding = next(f for f in result["findings"]
                                           if f["id"].startswith(f"site.crawl.{resource}."))
                            self.assertEqual(finding["id"], f"site.crawl.{resource}.{expected}")
                            self.assertEqual(finding["status"],
                                             {"present": "pass", "missing": "fail", "unknown": "unknown"}[expected])
                            if expected == "unknown":
                                self.assertNotIn("action", finding)

    def test_non_html_206_stays_skipped_instead_of_missing_metadata(self):
        for proxied in (False, True):
            with self.subTest(proxied=proxied):
                raw, results = self.collect(b"%PDF partial bytes", proxied=proxied, media="application/pdf")
                self.assert_metadata(results, {})
                for result in (raw, *results):
                    self.assertEqual(result["capture"]["scope"], "raw_response")
                    self.assertIs(result["capture"]["body_truncated"], False)
                    self.assertIsNone(result["assessment"]["indexing"]["noindex"])
                for result in results:
                    self.assertEqual([f["id"] for f in result["findings"]],
                                     ["site.assessment.html_metadata_unavailable"])


if __name__ == "__main__":
    unittest.main()
