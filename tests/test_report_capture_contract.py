#!/usr/bin/env python3
"""Offline package CLI and registered MCP wrapper capture contracts."""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from seo_agent_suite import cli, mcp_server  # noqa: E402


class FakeMCP:
    """Exercise registered tools without the optional MCP transport."""
    def __init__(self, *args, **kwargs):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function
        return register


class ReportCaptureContractTests(unittest.TestCase):
    url = "https://example.com/"
    metadata = ("title", "description", "canonical", "og_title", "json_ld")

    def run_audits(self, body, *, truncated, content_type="text/html", resource_code=404):
        site = cli.load_script("site_meta_audit.py")

        def fetch(target):
            if target == self.url:
                return {"url": target, "status": "ok", "http_status": 200,
                        "body": body, "content_type": content_type,
                        "body_truncated": truncated}
            return {"url": target, "status": "error", "http_status": resource_code,
                    "reason": "timeout" if resource_code is None else f"HTTP {resource_code}",
                    "body": "", "body_truncated": False}

        with patch.object(site, "fetch", side_effect=fetch):
            raw = site.audit(self.url)
            with redirect_stdout(io.StringIO()) as output:
                code = cli.main(["site-meta", self.url, "--json"])
            package = json.loads(output.getvalue())
            with patch.object(mcp_server, "_require_mcp", return_value=FakeMCP):
                server = mcp_server.build_server()
            mcp = json.loads(server.tools["site_meta"](self.url))
        self.assertEqual(code, 0)
        self.assertEqual(mcp["exit_code"], code)
        self.assertEqual(package["findings"], mcp["findings"])
        for result in (package, mcp):
            self.assertEqual(result["capture"], raw["capture"])
            self.assertEqual(result.get("checks"), raw.get("checks"))
            self.assertEqual(result.get("assessment"), raw.get("assessment"))
            self.assertEqual([f["code"] for f in result["findings"] if "code" in f],
                             [f["code"] for f in raw["findings"]])
        return package, mcp

    def assert_metadata(self, results, expected):
        for result in results:
            actual = {f["id"]: f for f in result["findings"] if f["id"].startswith("site.meta.")}
            self.assertEqual(set(actual), {f"site.meta.{name}.{state}" for name, state in expected.items()})
            for name, state in expected.items():
                finding = actual[f"site.meta.{name}.{state}"]
                self.assertEqual(finding["status"], {"unknown": "unknown", "missing": "fail", "present": "pass"}[state])
                self.assertEqual(finding["confidence"], "hypothesis" if state == "unknown" else "confirmed")
                if state == "unknown":
                    self.assertEqual(finding["severity"], "info")
                    self.assertNotIn("action", finding)
                    self.assertIn({"kind": "json_pointer", "path": "/capture/body_truncated"}, finding["evidence"])

    def test_truncated_absence_is_unknown(self):
        results = self.run_audits("<head>", truncated=True)
        self.assert_metadata(results, dict.fromkeys(self.metadata, "unknown"))
        for result in results:
            ids = {f["id"] for f in result["findings"]}
            self.assertIn("site.assessment.capture_incomplete", ids)
            self.assertIn("site.assessment.canonical_unknown", ids)

    def test_truncated_observed_title_stays_present(self):
        results = self.run_audits("<head><title>Observed</title>", truncated=True)
        self.assert_metadata(results, {**dict.fromkeys(self.metadata, "unknown"), "title": "present"})

    def test_all_observed_metadata_stays_present(self):
        body = ('<head><title>Observed</title><meta name="description" content="Observed">'
                '<link rel="canonical" href="https://example.com/">'
                '<meta property="og:title" content="Observed">'
                '<script type="application/ld+json">{"@type":"WebPage"}</script>')
        self.assert_metadata(self.run_audits(body, truncated=True), dict.fromkeys(self.metadata, "present"))

    def test_complete_absence_stays_confirmed_missing(self):
        results = self.run_audits("<html><head></head><body></body></html>", truncated=False)
        self.assert_metadata(results, dict.fromkeys(self.metadata, "missing"))

    def test_truncation_does_not_change_resource_response_semantics(self):
        for code in (404, 410, 403, None):
            with self.subTest(code=code):
                results = self.run_audits("<head>", truncated=True, resource_code=code)
                for result in results:
                    for name in ("robots_txt", "sitemap"):
                        state = "missing" if code in (404, 410) else "unknown"
                        finding = next(f for f in result["findings"] if f["id"] == f"site.crawl.{name}.{state}")
                        self.assertEqual(finding["status"], "fail" if state == "missing" else "unknown")

    def test_non_html_remains_skipped(self):
        for truncated in (False, True):
            with self.subTest(truncated=truncated):
                results = self.run_audits("%PDF", truncated=truncated, content_type="application/pdf")
                self.assert_metadata(results, {})
                for result in results:
                    self.assertEqual([f["id"] for f in result["findings"]],
                                     ["site.assessment.html_metadata_unavailable"])


if __name__ == "__main__":
    unittest.main()
