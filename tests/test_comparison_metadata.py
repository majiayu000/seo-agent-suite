#!/usr/bin/env python3
"""Offline tests for the reviewed P05 five-rule comparison metadata contract.

Numbered cases correspond to the contract's 43 acceptance scenarios. Case 43
checks the metadata prerequisites and outcome inputs only; no P06 comparator is
implemented, exercised, or implied by this suite. All HTTP is fixture-driven.
"""
from __future__ import annotations

import builtins
import copy
import hashlib
import inspect
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import zipfile
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from seo_agent_suite import SCHEMA_VERSION, __version__  # noqa: E402
from seo_agent_suite import cli, mcp_server  # noqa: E402
from seo_agent_suite.comparison_metadata import (  # noqa: E402
    build_site_comparison_metadata,
    validate_site_comparison_metadata,
)
from seo_agent_suite.comparison_runtime import resolve_site_runtime_policy  # noqa: E402
from seo_agent_suite.report import enrich_repo_evidence, enrich_site_result  # noqa: E402

URL = "https://example.com/docs/"
RULE_CHECKS = {
    "site.meta.canonical": "has_canonical",
    "site.meta.description": "has_meta_description",
    "site.meta.json_ld": "has_json_ld",
    "site.meta.og_title": "has_og_title",
    "site.meta.title": "has_title",
}
RULES = sorted(RULE_CHECKS)
POLICY = {
    "timeout_seconds": 20,
    "max_body_bytes": 1_000_000,
    "max_redirects": 5,
    "request_headers": {
        "User-Agent": "seo-agent-suite/0.2.0 (+https://github.com/majiayu000/seo-agent-suite)",
        "Accept": "*/*",
    },
}
ALL_HTML = ('<head><title>Observed</title><meta name="description" content="Observed">'
            '<link rel="canonical" href="https://example.com/docs/">'
            '<meta property="og:title" content="Observed">'
            '<script type="application/ld+json">{"@type":"WebPage"}</script></head>')


def report_fixture(*, present=True, truncated=False, url=URL, effective=None):
    """Containing envelope with intentionally small, explicit evidence."""
    raw = {
        "url": url,
        "collected_at": "2026-01-01T00:00:00Z",
        "page": {"status": "ok", "url": effective or url, "http_status": 200,
                 "content_type": "text/html", "content_encoding": None,
                 "body_truncated": truncated},
        "capture": {"scope": "raw_html", "rendered": False, "body_truncated": truncated},
        "checks": {**dict.fromkeys(RULE_CHECKS.values(), present),
                   "robots_txt": [], "sitemap_xml": [],
                   "sitemap_discovery": {"complete": True}},
        "findings": [],
    }
    return enrich_site_result(raw)


def attach(report, requested_url=URL, runtime_policy=None):
    report["comparison"] = build_site_comparison_metadata(
        report, requested_url, copy.deepcopy(POLICY if runtime_policy is None else runtime_policy)
    )
    return report


def ledger(report):
    return {row["rule_id"]: row for row in report["comparison"]["evaluations"]}


def pointer_value(report, pointer):
    """Independent RFC6901 resolver used by tests, never by production."""
    value = report
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


class FakeMCP:
    def __init__(self, *args, **kwargs):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function
        return register


class ComparisonContractTests(unittest.TestCase):
    def assert_valid(self, report, *, requested_url=URL, runtime_policy=None):
        self.assertEqual(validate_site_comparison_metadata(report), [])
        self.assertEqual(validate_site_comparison_metadata(
            report, requested_url=requested_url,
            runtime_policy=POLICY if runtime_policy is None else runtime_policy), [])
        block = report["comparison"]
        self.assertEqual([row["rule_id"] for row in block["evaluations"]], RULES)
        self.assertEqual({row["subject_id"] for row in block["evaluations"]}, {"page"})
        self.assertEqual(len(block["evaluations"]), 5)
        for group in [block["collection"], block["provenance"]["resources"], *block["evaluations"]]:
            for ref in group["evidence_refs"]:
                pointer_value(report, ref)
        for key in ("requested_url_ref", "effective_url_ref"):
            if block["provenance"][key] is not None:
                pointer_value(report, block["provenance"][key])
        ids = [finding.get("id") for finding in report.get("findings", [])]
        for row in block["evaluations"]:
            for fid in row["legacy_finding_ids"]:
                self.assertEqual(ids.count(fid), 1)

    def assert_rows(self, report, outcome, completion, reason=None):
        for row in report["comparison"]["evaluations"]:
            self.assertEqual(row["outcome"], outcome)
            self.assertEqual(row["completion"], completion)
            if reason is not None:
                self.assertEqual(row["reason"], reason)

    def collect_html(self, body=ALL_HTML, *, truncated=False, content_type="text/html",
                     content_encoding=None, resource_code=404):
        site = cli.load_script("site_meta_audit.py")
        def fetch(target):
            if target == URL:
                return {"url": target, "status": "ok", "http_status": 200,
                        "body": body, "content_type": content_type,
                        "content_encoding": content_encoding, "body_truncated": truncated}
            return {"url": target, "status": "error", "http_status": resource_code,
                    "reason": "timeout" if resource_code is None else f"HTTP {resource_code}",
                    "body": "", "body_truncated": False}
        with patch.object(site, "fetch", side_effect=fetch):
            return enrich_site_result(site.audit(URL))

    def test_01_complete_all_pass(self):
        report = attach(report_fixture())
        self.assert_valid(report)
        self.assert_rows(report, "pass", "complete", "observed_present")
        self.assertEqual(report["comparison"]["collection"]["completion"], "complete")
        self.assertEqual(report["comparison"]["collection"]["reasons"], [])
        self.assertEqual(report["comparison"]["producer"]["tool_version"], __version__)
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)

    def test_complete_exact_identity_rejects_conflicting_containing_target(self):
        report = attach(report_fixture())
        self.assert_valid(report)
        self.assertEqual(report["comparison"]["collection"]["completion"], "complete")
        self.assertEqual(report["comparison"]["target"]["identity_state"], "exact")
        before = copy.deepcopy(report)
        report["target"]["id"] = "https://another.example/"
        self.assertTrue(validate_site_comparison_metadata(report))
        self.assertTrue(validate_site_comparison_metadata(
            report, requested_url=URL, runtime_policy=POLICY))
        self.assertEqual(report["comparison"], before["comparison"])

    def test_02_complete_title_absent_is_complete_despite_legacy_partial(self):
        report = attach(self.collect_html(ALL_HTML.replace("<title>Observed</title>", "")))
        self.assert_valid(report)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["comparison"]["collection"]["completion"], "complete")
        self.assertEqual(ledger(report)["site.meta.title"]["outcome"], "fail")
        self.assertEqual(ledger(report)["site.meta.title"]["reason"], "confirmed_absent")

    def test_03_complete_whitespace_description(self):
        report = attach(self.collect_html('<meta name="description" content=" \n\t ">'))
        self.assertFalse(report["checks"]["has_meta_description"])
        self.assertEqual(ledger(report)["site.meta.description"]["outcome"], "fail")
        self.assert_valid(report)

    def test_04_canonical_presence_does_not_assert_valid_target(self):
        report = attach(self.collect_html('<link rel="canonical" href="javascript:invalid">'))
        self.assertEqual(report["assessment"]["canonical"]["status"], "invalid")
        self.assertEqual(ledger(report)["site.meta.canonical"]["outcome"], "pass")
        self.assert_valid(report)

    def test_05_jsonld_start_does_not_assert_parse_validity(self):
        for body in ('<script type="application/ld+json">{broken}</script>',
                     '<script type="APPLICATION/LD+JSON">'):
            with self.subTest(body=body):
                report = attach(self.collect_html(body))
                self.assertNotEqual(report["assessment"]["json_ld_parse_valid"], True)
                self.assertEqual(ledger(report)["site.meta.json_ld"]["outcome"], "pass")
                self.assert_valid(report)

    def test_06_truncated_empty_has_no_confirmed_absence(self):
        report = attach(report_fixture(present=False, truncated=True))
        self.assert_valid(report)
        self.assert_rows(report, "unknown", "incomplete", "body_truncated")
        self.assertEqual(report["comparison"]["collection"]["completion"], "incomplete")
        self.assertIn("body_truncated", report["comparison"]["collection"]["reasons"])

    def test_07_truncated_observed_title_keeps_limited_positive(self):
        report = attach(self.collect_html("<title>Seen</title>", truncated=True))
        self.assert_valid(report)
        for rule, row in ledger(report).items():
            self.assertEqual(row["outcome"], "pass" if rule == "site.meta.title" else "unknown")
        self.assertEqual(report["comparison"]["collection"]["completion"], "incomplete")

    def test_08_truncated_all_observed_does_not_claim_complete_collection(self):
        report = attach(report_fixture(truncated=True))
        self.assert_valid(report)
        self.assert_rows(report, "pass", "complete", "observed_present")
        self.assertEqual(report["comparison"]["collection"]["completion"], "incomplete")

    def test_09_missing_or_contradictory_truncation_flag(self):
        for location in ("page", "capture"):
            for value in (None, 0, 1, "false", "missing", True):
                with self.subTest(location=location, value=value):
                    report = report_fixture(present=False)
                    if value == "missing":
                        del report[location]["body_truncated"]
                    else:
                        report[location]["body_truncated"] = value
                    attach(report)
                    self.assertNotEqual(report["comparison"]["collection"]["completion"], "complete")
                    self.assertFalse(any(row["outcome"] == "fail" for row in ledger(report).values()))
                    self.assert_valid(report)

    def test_10_missing_or_nonboolean_check_evidence(self):
        for key in RULE_CHECKS.values():
            for value in (None, 0, 1, "false", "true", [], {}, "missing"):
                with self.subTest(key=key, value=value):
                    report = report_fixture()
                    if value == "missing":
                        del report["checks"][key]
                    else:
                        report["checks"][key] = value
                    attach(report)
                    rule = next(rule for rule, check in RULE_CHECKS.items() if check == key)
                    self.assertEqual(ledger(report)[rule]["outcome"], "unknown")
                    self.assertEqual(ledger(report)[rule]["reason"], "missing_check_evidence")
                    self.assertEqual(report["comparison"]["collection"]["completion"], "unknown")
                    self.assert_valid(report)

    def test_11_failed_fetches_never_establish_effective_identity(self):
        for status, reason in ((None, "DNS failure"), (None, "timeout"), (403, "HTTP 403"),
                               (404, "HTTP 404"), (None, "redirect blocked")):
            with self.subTest(reason=reason):
                report = enrich_site_result({"url": URL,
                    "page": {"status": "error", "url": "http://127.0.0.1/blocked",
                             "http_status": status, "reason": reason}})
                attach(report)
                self.assert_rows(report, "unknown", "incomplete", "page_fetch_error")
                self.assertEqual(report["comparison"]["collection"]["completion"], "incomplete")
                self.assertIsNone(report["comparison"]["target"]["effective_url"])
                self.assertEqual(report["comparison"]["target"]["identity_state"], "unknown")
                self.assertTrue(all(row["legacy_finding_ids"] == [] for row in ledger(report).values()))
                self.assert_valid(report)

    def test_12_non_html_is_not_applicable_without_missing_findings(self):
        for media in ("application/pdf", "text/plain", "application/json"):
            report = attach(self.collect_html("{}", content_type=media))
            self.assert_rows(report, "skip", "not_applicable", "non_html")
            self.assertEqual(report["comparison"]["collection"]["completion"], "not_applicable")
            self.assertFalse(any(f["id"].startswith("site.meta.") for f in report["findings"]))
            self.assert_valid(report)

    def test_13_unknown_media_and_unsupported_encoding_are_unknown(self):
        for media, encoding, reason in ((None, None, "unknown_media_type"),
                                        ("", None, "unknown_media_type"),
                                        ("text/html", "gzip", "unsupported_encoding"),
                                        ("application/pdf", "br", "unsupported_encoding")):
            with self.subTest(media=media, encoding=encoding):
                report = attach(self.collect_html(content_type=media, content_encoding=encoding))
                self.assert_rows(report, "unknown", "incomplete", reason)
                self.assertEqual(report["comparison"]["collection"]["completion"], "unknown")
                self.assert_valid(report)

    def test_14_same_requested_new_effective_url_changes_target_tuple(self):
        before = attach(report_fixture())
        after = attach(report_fixture(effective="https://example.com/new/"))
        self.assertNotEqual(before["comparison"]["target"], after["comparison"]["target"])
        self.assert_valid(after)

    def test_15_same_effective_different_requested_url_changes_target_tuple(self):
        first = attach(report_fixture())
        other = "https://example.com/alias"
        second = attach(report_fixture(url=other, effective=URL), requested_url=other)
        self.assertNotEqual(first["comparison"]["target"], second["comparison"]["target"])
        self.assert_valid(second, requested_url=other)

    def test_16_redacted_userinfo_is_neither_retained_nor_hashed(self):
        secret = "uniquely-private-test-password"
        requested = f"https://test-user:{secret}@example.com/docs/"
        report = attach(report_fixture(), requested_url=requested)
        block = report["comparison"]
        self.assertIsNone(block["target"]["requested_url"])
        self.assertEqual(block["target"]["identity_state"], "unknown")
        self.assertEqual(block["provenance"]["url_redaction"], "applied")
        encoded = json.dumps(block)
        for sensitive in (secret, "test-user", requested, hashlib.sha256(requested.encode()).hexdigest(),
                          hashlib.sha256(secret.encode()).hexdigest()):
            self.assertNotIn(sensitive, encoded)
        self.assert_valid(report, requested_url=requested)

    def test_17_unavailable_original_input_cannot_retrofit_identity(self):
        report = attach(report_fixture(), requested_url=None)
        self.assertEqual(report["comparison"]["target"]["identity_state"], "unknown")
        self.assertIsNone(report["comparison"]["target"]["requested_url"])
        self.assertEqual(report["comparison"]["collection"]["completion"], "unknown")
        self.assertNotIn("comparison", enrich_site_result(report_fixture()))
        self.assert_valid(report, requested_url=None)

    def test_18_exact_url_spelling_is_preserved_without_normalization(self):
        urls = ["https://EXAMPLE.com:443/a;b?x=1&y=2#Fragment",
                "https://example.com/a;b?y=2&x=1#Fragment", "https://example.com/a%2Fb",
                "https://example.com/a%2fb", "https://example.com/a/b", "https://example.com/a/",
                "https://example.com/a", "HTTP://example.com:80/?q=%41#one",
                "https://例子.example/路径?查询=值#片段"]
        targets = []
        for url in urls:
            report = attach(report_fixture(url=url), requested_url=url)
            target = report["comparison"]["target"]
            self.assertEqual((target["requested_url"], target["effective_url"]), (url, url))
            self.assertEqual(target["identity_state"], "exact")
            self.assert_valid(report, requested_url=url)
            targets.append((target["requested_url"], target["effective_url"]))
        self.assertEqual(len(set(targets)), len(urls))

    def test_19_robots_failure_does_not_expand_or_block_page_scope(self):
        report = attach(self.collect_html(resource_code=None))
        self.assertTrue(report["checks"]["sitemap_discovery"]["complete"])
        self.assertEqual(report["comparison"]["collection"]["completion"], "complete")
        resources = report["comparison"]["provenance"]["resources"]
        self.assertEqual(resources["coverage"], "unknown")
        self.assertEqual(resources["comparison_scope"], "excluded")
        self.assertEqual(resources["reason"], "not_assessed_by_this_contract")
        self.assert_valid(report)

    def test_20_resource_caps_truncation_and_final_collisions_remain_legacy_evidence(self):
        report = report_fixture()
        report["checks"]["robots_txt"] = [{"url": "https://example.com/robots.txt",
                                                 "status": "ok", "body_truncated": True}]
        report["checks"]["sitemap_xml"] = [
            {"url": "https://cdn.example/sitemap.xml", "body_truncated": False},
            {"url": "https://cdn.example/sitemap.xml", "body_truncated": True}]
        report["checks"]["sitemap_discovery"] = {"complete": False, "candidate_count": 11,
                                                          "max_candidates": 10}
        before = copy.deepcopy(report)
        attach(report)
        self.assertEqual({k: v for k, v in report.items() if k != "comparison"}, before)
        self.assertEqual(report["comparison"]["scope"]["subject_ids"], ["page"])
        self.assertEqual(report["comparison"]["provenance"]["resources"]["coverage"], "unknown")
        self.assertEqual(report["comparison"]["collection"]["completion"], "complete")
        self.assert_valid(report)

    def test_21_addition_preserves_legacy_findings_status_and_actions(self):
        report = self.collect_html("<title>Title only</title>")
        before = json.dumps(report, sort_keys=True)
        attach(report)
        comparison = report.pop("comparison")
        self.assertEqual(json.dumps(report, sort_keys=True), before)
        report["comparison"] = comparison
        self.assert_valid(report)

    def test_22_raw_script_json_text_default_and_fail_on_are_unchanged(self):
        site = cli.load_script("site_meta_audit.py")
        raw = {"url": URL, "page": {"status": "ok", "http_status": 200},
               "title": "Observed", "findings": [{"severity": "warning", "confidence": "Confirmed",
                     "code": "title_missing", "message": "Fixture warning"}]}
        for options, expected_code in ((["--json"], 0), ([], 0),
                                        (["--json", "--fail-on", "warning"], 1),
                                        (["--fail-on", "error"], 0)):
            with self.subTest(options=options), patch.object(site, "audit", return_value=raw), \
                    patch.object(sys, "argv", ["site_meta_audit.py", URL, *options]), \
                    redirect_stdout(io.StringIO()) as output:
                code = site.main()
            self.assertEqual(code, expected_code)
            self.assertNotIn("comparison", output.getvalue())
            if "--json" in options:
                self.assertEqual(json.loads(output.getvalue()), raw)
            else:
                self.assertIn("title: Observed", output.getvalue())
        self.assertNotIn("comparison_metadata", (ROOT / "scripts/site_meta_audit.py").read_text())
        self.assertNotIn("comparison_metadata", (ROOT / "scripts/public_http.py").read_text())

    def test_23_repository_reports_and_old_envelopes_are_unsupported(self):
        for root in ("/same/root", "/moved/root"):
            report = enrich_repo_evidence({"root": root, "status": "ok", "errors": []})
            self.assertNotIn("comparison", report)
            self.assertTrue(validate_site_comparison_metadata(report))
        self.assertTrue(validate_site_comparison_metadata(report_fixture()))
        report = attach(report_fixture())
        report["target"] = {"kind": "repo", "id": "/same/root"}
        self.assertTrue(validate_site_comparison_metadata(report))

    def test_24_actual_cli_and_registered_mcp_wrapper_have_identical_blocks(self):
        site = cli.load_script("site_meta_audit.py")
        http = cli.load_script("public_http.py")
        # Exercise the complete collector call chain with memory-only connections.
        # The public URL guard still runs; DNS and actual sockets are stubbed below it.
        requests_seen = []
        def connection(*args, **kwargs):
            conn = Mock()
            def request(method, path, headers):
                requests_seen.append((args[3], copy.deepcopy(headers)))
                body = ALL_HTML.encode() if path == "/docs/" else b""
                response = Mock(status=200 if body else 404, length=len(body), chunked=False)
                response.read.return_value = body
                headers = {"content-type": "text/html" if body else "text/plain"}
                response.getheader.side_effect = headers.get
                response.getheaders.return_value = list(headers.items())
                conn.getresponse.return_value = response
            conn.request.side_effect = request
            return conn
        endpoints = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        with patch.object(socket, "getaddrinfo", return_value=endpoints), \
                patch.object(http, "select_proxy", return_value=None), \
                patch.object(http, "PinnedHTTPSConnection", side_effect=connection), \
                patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            with redirect_stdout(io.StringIO()) as output:
                code = cli.main(["site-meta", URL, "--json"])
            package = json.loads(output.getvalue())
            with patch.object(mcp_server, "_require_mcp", return_value=FakeMCP):
                server = mcp_server.build_server()
            mcp = json.loads(server.tools["site_meta"](URL))
        self.assertEqual(set(server.tools), {"doctor", "repo_baseline", "site_meta"})
        self.assertEqual(list(inspect.signature(server.tools["site_meta"]).parameters), ["url"])
        self.assertEqual(code, 0)
        self.assertEqual(mcp["exit_code"], code)
        self.assertEqual(package["comparison"], mcp["comparison"])
        self.assertEqual(package["comparison"]["scope"]["configuration_status"], "verified")
        self.assert_valid(package, runtime_policy=resolve_site_runtime_policy(site, audit_options={}))
        self.assert_valid(mcp, runtime_policy=resolve_site_runtime_policy(site, audit_options={}))
        self.assertTrue(requests_seen)
        for timeout, headers in requests_seen:
            self.assertEqual(timeout, package["comparison"]["scope"]["limits"]["timeout_seconds"])
            self.assertEqual(headers, package["comparison"]["scope"]["request_headers"])

    def test_25_built_wheel_contains_importable_helper_and_collectors(self):
        # Build/extract in temporary paths only; never install into shared Python.
        with tempfile.TemporaryDirectory(prefix="seo-p05-wheel-") as tmp:
            tmp = Path(tmp)
            checkout = tmp / "source"
            shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "*.pyc", "build", "dist", "*.egg-info"))
            wheels = tmp / "wheels"
            wheels.mkdir()
            build = subprocess.run([sys.executable, "-c",
                "import setuptools.build_meta as b; b.build_wheel(" + repr(str(wheels)) + ")"],
                cwd=checkout, capture_output=True, text=True, check=False)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            wheel_files = list(wheels.glob("*.whl"))
            self.assertEqual(len(wheel_files), 1)
            installed = tmp / "installed"
            with zipfile.ZipFile(wheel_files[0]) as archive:
                self.assertIn("seo_agent_suite/comparison_metadata.py", archive.namelist())
                archive.extractall(installed)
            smoke_script = "\n".join([
                "import sys, runpy, unittest",
                "sys.path.insert(0, " + repr(str(installed)) + ")",
                # Preload the installed package before loading this test definition.
                # Its __path__ then guarantees every production submodule is wheel-owned.
                "import seo_agent_suite",
                "from seo_agent_suite import cli, mcp_server, comparison_metadata, comparison_runtime",
                "from seo_agent_suite.paths import load_script",
                "site = load_script('site_meta_audit.py')",
                "for module in (seo_agent_suite, cli, mcp_server, comparison_metadata, comparison_runtime, site):",
                "    assert module.__file__.startswith(" + repr(str(installed)) + "), module.__file__",
                "p = comparison_runtime.resolve_site_runtime_policy(site, audit_options={})",
                "assert p['max_body_bytes'] == 1000000, p",
                "assert p['timeout_seconds'] == 20, p",
                "namespace = runpy.run_path(" + repr(str(Path(__file__).resolve())) + ")",
                "case = namespace['ComparisonContractTests']('test_24_actual_cli_and_registered_mcp_wrapper_have_identical_blocks')",
                "result = unittest.TextTestRunner().run(unittest.TestSuite([case]))",
                "assert result.wasSuccessful(), 'installed wheel CLI/MCP regression'",
                "print('wheel helper and actual CLI/MCP OK')",
            ])
            smoke = subprocess.run([sys.executable, "-I", "-c", smoke_script],
                cwd=tmp, capture_output=True, text=True, check=False)
            self.assertEqual(smoke.returncode, 0, smoke.stdout + smoke.stderr)
            self.assertIn("wheel helper and actual CLI/MCP OK", smoke.stdout)

    def test_26_runtime_policy_is_actual_bound_call_chain_configuration(self):
        site = cli.load_script("site_meta_audit.py")
        http = cli.load_script("public_http.py")
        policy = resolve_site_runtime_policy(site, audit_options={})
        self.assertEqual(policy["timeout_seconds"], inspect.signature(site.fetch).parameters["timeout"].default)
        self.assertEqual(policy["max_body_bytes"], site.fetch_public_url.__kwdefaults__["max_body_bytes"])
        follow = site.fetch_public_url.__globals__["follow_public_http"]
        self.assertEqual(policy["max_redirects"], inspect.signature(follow).parameters["max_redirects"].default)
        self.assertEqual(policy["request_headers"], http.default_request_headers())
        observed = []
        def request(url, timeout, *, max_body_bytes):
            observed.append((timeout, max_body_bytes))
            return {"http_status": 200, "content_type": "text/html", "location": None,
                    "sample_bytes": 0, "body": b""}
        with patch.object(http, "request_public_url_once", side_effect=request):
            site.fetch(URL)
        self.assertEqual(observed, [(policy["timeout_seconds"], policy["max_body_bytes"] + 1)])
        for defaults in ({"timeout_seconds": 7}, {"max_body_bytes": 17}, {"max_redirects": 2}):
            with self.subTest(defaults=defaults), ExitStack() as stack:
                if "timeout_seconds" in defaults:
                    stack.enter_context(patch.object(site.fetch, "__defaults__", (7,)))
                if "max_body_bytes" in defaults:
                    stack.enter_context(patch.object(site.fetch_public_url, "__kwdefaults__", {**site.fetch_public_url.__kwdefaults__, "max_body_bytes": 17}))
                if "max_redirects" in defaults:
                    stack.enter_context(patch.object(follow, "__kwdefaults__", {**follow.__kwdefaults__, "max_redirects": 2}))
                changed = resolve_site_runtime_policy(site, audit_options={})
                for key, value in defaults.items():
                    self.assertEqual(changed[key], value)
                changed_report = attach(report_fixture(), runtime_policy=changed)
                self.assertNotEqual(changed_report["comparison"]["scope"], attach(report_fixture())["comparison"]["scope"])
                self.assert_valid(changed_report, runtime_policy=changed)
        with patch.object(http, "USER_AGENT", "changed-public-agent/1"):
            self.assertEqual(resolve_site_runtime_policy(site, audit_options={})["request_headers"]["User-Agent"], "changed-public-agent/1")

    def test_27_versions_scope_and_inventory_tampering_are_rejected(self):
        mutations = [
            (("contract_version",), "2.0"), (("producer", "id"), "other/site-meta"),
            (("producer", "tool_version"), "unrelated-version"),
            (("producer", "report_schema_version"), "2.0"),
            (("producer", "ruleset_id"), "all.seo"), (("producer", "ruleset_version"), "2"),
            (("scope", "method"), "rendered"), (("scope", "rendered"), True),
            (("scope", "rule_ids"), RULES[:-1]), (("scope", "subject_ids"), ["page", "resource"]),
            (("scope", "resources"), "complete"), (("scope", "adapters"), ["provider"]),
        ]
        for path, value in mutations:
            with self.subTest(path=path):
                report = attach(report_fixture())
                node = report["comparison"]
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                self.assertTrue(validate_site_comparison_metadata(report))
        report = attach(report_fixture())
        report["comparison"]["scope"]["limits"]["timeout_seconds"] = 21
        self.assertTrue(validate_site_comparison_metadata(report, runtime_policy=POLICY))

    def test_28_complete_unique_supported_ledger_is_required(self):
        def duplicate(rows): rows[1] = copy.deepcopy(rows[0])
        def missing(rows): rows.pop()
        def extra(rows): rows.append(copy.deepcopy(rows[0]))
        def unknown_rule(rows): rows[0]["rule_id"] = "site.unknown"
        def unknown_subject(rows): rows[0]["subject_id"] = "robots"
        for mutate in (duplicate, missing, extra, unknown_rule, unknown_subject):
            with self.subTest(mutation=mutate.__name__):
                report = attach(report_fixture())
                mutate(report["comparison"]["evaluations"])
                self.assertTrue(validate_site_comparison_metadata(report))

    def test_29_invalid_pointers_links_and_contradictory_rows_are_rejected(self):
        def bad_pointer(r): r["comparison"]["evaluations"][0]["evidence_refs"].append("/absent")
        def malformed_pointer(r): r["comparison"]["evaluations"][0]["evidence_refs"].append("/checks/~2invalid")
        def bad_link(r): r["comparison"]["evaluations"][0]["legacy_finding_ids"].append("does.not.exist")
        def repeated_id(r): r["findings"].append(copy.deepcopy(r["findings"][0]))
        def wrong_reason(r): r["comparison"]["evaluations"][0]["reason"] = "confirmed_absent"
        def wrong_completion(r): r["comparison"]["evaluations"][0]["completion"] = "incomplete"
        def wrong_outcome(r): r["comparison"]["evaluations"][0]["outcome"] = "fail"
        def changed_evidence(r): r["checks"]["has_canonical"] = False
        def changed_capture(r): r["capture"]["body_truncated"] = True
        def wrong_effective(r): r["comparison"]["target"]["effective_url"] += "different"
        def wrong_redaction(r): r["comparison"]["provenance"]["url_redaction"] = "applied"
        def wrong_schema(r): r["schema_version"] = "2.0"
        for mutate in (bad_pointer, malformed_pointer, bad_link, repeated_id, wrong_reason,
                       wrong_completion, wrong_outcome, changed_evidence, changed_capture,
                       wrong_effective, wrong_redaction, wrong_schema):
            with self.subTest(mutation=mutate.__name__):
                report = attach(report_fixture())
                mutate(report)
                errors = validate_site_comparison_metadata(report, requested_url=URL, runtime_policy=POLICY)
                self.assertTrue(errors)
                self.assertTrue(all(isinstance(error, str) for error in errors))
                self.assertEqual(errors, validate_site_comparison_metadata(
                    report, requested_url=URL, runtime_policy=POLICY))

    def test_30_timestamps_details_and_legacy_source_revision_do_not_change_metadata(self):
        first = report_fixture()
        second = copy.deepcopy(first)
        second["collected_at"] = "2030-12-31T23:59:59Z"
        second["source_revision"] = "unverified-legacy-value"
        for finding in second["findings"]:
            finding["detail"] = "Reworded observations"
            finding["severity"] = "high"
            finding["title"] = "Cosmetic title"
        self.assertEqual(attach(first)["comparison"], attach(second)["comparison"])

    def test_31_builder_and_validator_are_pure_offline_and_do_not_mutate_inputs(self):
        raw = report_fixture()
        policy = copy.deepcopy(POLICY)
        before = json.dumps(raw, sort_keys=True)
        policy_before = json.dumps(policy, sort_keys=True)
        def forbidden(*args, **kwargs):
            raise AssertionError("P05 builder/validator attempted I/O")
        targets = [(socket, "socket"), (socket, "getaddrinfo"), (socket, "create_connection"),
                   (subprocess, "Popen"), (os, "system"), (os, "open"), (builtins, "open"),
                   (Path, "open"), (Path, "write_text"), (Path, "write_bytes"),
                   (urllib.request, "urlopen")]
        with ExitStack() as stack:
            for owner, name in targets:
                stack.enter_context(patch.object(owner, name, side_effect=forbidden))
            block = build_site_comparison_metadata(raw, URL, policy)
            self.assertEqual(validate_site_comparison_metadata(
                {**raw, "comparison": block}, requested_url=URL, runtime_policy=policy), [])
            self.assertEqual(block, build_site_comparison_metadata(raw, URL, policy))
        self.assertEqual(json.dumps(raw, sort_keys=True), before)
        self.assertEqual(json.dumps(policy, sort_keys=True), policy_before)
        block["scope"]["request_headers"]["User-Agent"] = "mutated-output"
        self.assertEqual(json.dumps(policy, sort_keys=True), policy_before)

    def test_32_body_description_canonical_and_og_title_stay_lexical(self):
        report = attach(self.collect_html('<body><meta name="description" content="Body">'
                    '<link rel="canonical" href="https://example.com/">'
                    '<meta property="og:title" content="Body"></body>'))
        for rule in ("site.meta.description", "site.meta.canonical", "site.meta.og_title"):
            self.assertEqual(ledger(report)[rule]["outcome"], "pass")
        self.assert_valid(report)

    def test_33_first_empty_duplicate_description_is_not_rescued(self):
        report = attach(self.collect_html('<meta name="description" content="">'
                                         '<meta name="description" content="Later">'))
        self.assertFalse(report["checks"]["has_meta_description"])
        self.assertEqual(ledger(report)["site.meta.description"]["outcome"], "fail")
        self.assert_valid(report)

    def test_34_first_empty_duplicate_canonical_is_not_rescued(self):
        report = attach(self.collect_html('<link rel="canonical" href="">'
                                         '<link rel="canonical" href="https://example.com/">'))
        self.assertFalse(report["checks"]["has_canonical"])
        self.assertEqual(ledger(report)["site.meta.canonical"]["outcome"], "fail")
        self.assert_valid(report)

    def test_35_canonical_and_og_whitespace_are_truthy_but_description_is_not(self):
        report = attach(self.collect_html('<meta name="description" content="  ">'
                    '<link rel="canonical" href="  "><meta property="og:title" content="  ">'))
        self.assertEqual(ledger(report)["site.meta.description"]["outcome"], "fail")
        self.assertEqual(ledger(report)["site.meta.canonical"]["outcome"], "pass")
        self.assertEqual(ledger(report)["site.meta.og_title"]["outcome"], "pass")
        self.assert_valid(report)

    def test_36_last_empty_og_title_overrides_earlier_nonempty(self):
        report = attach(self.collect_html('<meta property="og:title" content="First">'
                                         '<meta property="og:title" content="">'))
        self.assertEqual(ledger(report)["site.meta.og_title"]["outcome"], "fail")
        self.assert_valid(report)

    def test_37_last_whitespace_og_title_remains_present(self):
        report = attach(self.collect_html('<meta property="og:title" content="First">'
                                         '<meta property="og:title" content="  ">'))
        self.assertEqual(ledger(report)["site.meta.og_title"]["outcome"], "pass")
        self.assert_valid(report)

    def test_38_body_and_multiple_titles_preserve_collector_lexical_concatenation(self):
        report = attach(self.collect_html('<head><title>Head</title></head>'
                    '<body><title>Body</title><svg><title>Ignored</title></svg>'
                    '<template><title>Ignored too</title></template></body>'))
        self.assertEqual(report["title"], "HeadBody")
        self.assertEqual(ledger(report)["site.meta.title"]["outcome"], "pass")
        self.assert_valid(report)
        report = attach(self.collect_html('<body><title>Body only</title></body>'))
        self.assertEqual(ledger(report)["site.meta.title"]["outcome"], "pass")

    def test_39_partial_unknown_runtime_policy_preserves_known_settings(self):
        policy = copy.deepcopy(POLICY)
        policy["max_body_bytes"] = None
        policy["request_headers"]["User-Agent"] = None
        report = attach(report_fixture(), runtime_policy=policy)
        block = report["comparison"]
        self.assertEqual(block["scope"]["limits"], {"max_body_bytes": None,
                         "timeout_seconds": 20, "max_redirects": 5})
        self.assertEqual(block["scope"]["request_headers"], {"User-Agent": None, "Accept": "*/*"})
        self.assertEqual(block["scope"]["configuration_status"], "unknown")
        self.assertEqual(block["collection"]["completion"], "unknown")
        self.assertIn("configuration_unverified", block["collection"]["reasons"])
        self.assert_rows(report, "pass", "complete")
        self.assert_valid(report, runtime_policy=policy)
        block["scope"]["configuration_status"] = "verified"
        self.assertTrue(validate_site_comparison_metadata(report))

    def test_40_missing_url_fields_have_null_provenance_references(self):
        for location, key, ref in ((None, "url", "requested_url_ref"),
                                   ("page", "url", "effective_url_ref")):
            report = report_fixture()
            del (report[location] if location else report)[key]
            attach(report)
            self.assertIsNone(report["comparison"]["provenance"][ref])
            self.assertEqual(report["comparison"]["target"]["identity_state"], "unknown")
            self.assertEqual(report["comparison"]["collection"]["completion"], "unknown")
            self.assert_valid(report)

    def test_41_syntactic_identity_rejects_bad_inputs_without_network(self):
        invalid = ["", "https:///missing", "ftp://example.com/", "https://example.com:0/",
                   "https://example.com:65536/", "https://example.com:notaport/", "https://[broken/",
                   "https://@example.com/", "https://user:pass@example.com/", "https://:443/",
                   "https://example.com/a b", "https://example.com/a\x00b", "https://example.com/a\x7fb",
                   "\thttps://example.com/", "https://example.com/\n", None, 7, True, []]
        for url in invalid:
            for field in ("requested", "effective"):
                with self.subTest(url=url, field=field):
                    report = report_fixture()
                    requested = URL
                    if field == "requested":
                        report["url"] = url
                        requested = url
                    else:
                        report["page"]["url"] = url
                    attach(report, requested_url=requested)
                    self.assertEqual(report["comparison"]["target"]["identity_state"], "unknown")
                    self.assertNotEqual(report["comparison"]["collection"]["completion"], "complete")
                    self.assert_valid(report, requested_url=requested)
        for code in (True, False, "200", 199, 300, 404, None):
            report = report_fixture()
            report["page"]["http_status"] = code
            attach(report)
            self.assertEqual(report["comparison"]["target"]["identity_state"], "unknown")
            self.assertNotEqual(report["comparison"]["collection"]["completion"], "complete")
        for url in ("https://example.com:65535/", "https://[2001:db8::1]/a?x=%2f#F", "https://example.com:/"):
            report = attach(report_fixture(url=url), requested_url=url)
            self.assertEqual(report["comparison"]["target"]["identity_state"], "exact")
            self.assert_valid(report, requested_url=url)

    def test_42_mutated_module_constant_does_not_override_bound_body_default(self):
        site = cli.load_script("site_meta_audit.py")
        http = cli.load_script("public_http.py")
        actual_bound = site.fetch_public_url.__kwdefaults__["max_body_bytes"]
        with patch.object(http, "DEFAULT_MAX_BODY_BYTES", actual_bound + 123):
            policy = resolve_site_runtime_policy(site, audit_options={})
        self.assertEqual(policy["max_body_bytes"], actual_bound)

    def test_43_lifecycle_inputs_exist_only_under_complete_metadata_prerequisites(self):
        # P05 supplies all four valid outcome pairs without computing lifecycle labels.
        # Future P06 must apply its global gates before interpreting these transitions.
        for before_value, after_value in ((True, False), (False, False), (False, True), (True, True)):
            before = attach(report_fixture(present=before_value))
            after = attach(report_fixture(present=after_value))
            self.assert_valid(before)
            self.assert_valid(after)
            for block in (before["comparison"], after["comparison"]):
                self.assertEqual(block["collection"]["completion"], "complete")
                self.assertEqual(block["target"]["identity_state"], "exact")
                self.assertEqual(block["scope"]["configuration_status"], "verified")
            self.assertEqual(before["comparison"]["target"], after["comparison"]["target"])
            self.assertEqual(before["comparison"]["scope"], after["comparison"]["scope"])
            self.assertEqual(ledger(before)["site.meta.title"]["outcome"], "pass" if before_value else "fail")
            self.assertEqual(ledger(after)["site.meta.title"]["outcome"], "pass" if after_value else "fail")
        unavailable = [attach(report_fixture(truncated=True)),
                       attach(self.collect_html(content_type="application/pdf")),
                       attach(report_fixture(), requested_url=None)]
        for report in unavailable:
            self.assertNotEqual(report["comparison"]["collection"]["completion"], "complete")
        old = report_fixture()
        self.assertTrue(validate_site_comparison_metadata(old))
        incomplete_inventory = attach(report_fixture())
        incomplete_inventory["comparison"]["evaluations"].pop()
        self.assertTrue(validate_site_comparison_metadata(incomplete_inventory))

    def assert_extraction_unknown(self, site):
        policy = resolve_site_runtime_policy(site, audit_options={})
        report = attach(report_fixture(), runtime_policy=policy)
        self.assertEqual(report["comparison"]["scope"]["configuration_status"], "unknown")
        self.assertEqual(report["comparison"]["collection"]["completion"], "unknown")
        self.assert_valid(report, runtime_policy=policy)

    def test_stock_compiler_annotation_helpers_preserve_known_runtime(self):
        site = cli.load_script("site_meta_audit.py")
        self.assertEqual(resolve_site_runtime_policy(site, audit_options={}), POLICY)

    def test_open_graph_actual_redaction_binding_cannot_change_presence_unverified(self):
        site = cli.load_script("site_meta_audit.py")
        parser = site.MetaParser()
        parser.feed('<meta property="og:title" content="Observed">')
        original = site.redact_url
        self.assertTrue(site.open_graph_evidence(parser)[0]["og:title"])
        with patch.object(site, "redact_url", lambda value: "" if value == "Observed" else original(value)):
            self.assertEqual(site.redact_url(URL), URL)
            self.assertFalse(site.open_graph_evidence(parser)[0]["og:title"])
            self.assert_extraction_unknown(site)

    def test_open_graph_redaction_code_and_local_helper_fail_closed(self):
        site = cli.load_script("site_meta_audit.py")
        redact = site.open_graph_evidence.__globals__["redact_url"]
        with patch.dict(redact.__globals__, {"_strip_userinfo_heuristic": lambda value: ""}):
            parser = site.MetaParser()
            parser.feed('<meta property="og:title" content="https://[broken/">')
            self.assertFalse(site.open_graph_evidence(parser)[0]["og:title"])
            self.assert_extraction_unknown(site)
        for function in (redact, redact.__globals__["_strip_userinfo_heuristic"]):
            with self.subTest(helper=function.__name__):
                code = function.__code__
                try:
                    function.__code__ = (lambda value: "").__code__.replace(
                        co_filename=code.co_filename, co_firstlineno=code.co_firstlineno)
                    self.assert_extraction_unknown(site)
                finally:
                    function.__code__ = code

    def test_partial_http_response_never_confirms_page_absence(self):
        for present in (False, True):
            with self.subTest(present=present):
                report = report_fixture(present=present)
                report["page"]["http_status"] = 206
                attach(report)
                self.assertNotEqual(report["comparison"]["collection"]["completion"], "complete")
                self.assert_rows(report, "unknown", "incomplete", "missing_capture_evidence")
                self.assert_valid(report)

    def test_replaced_extraction_bindings_do_not_claim_comparable_collection(self):
        site = cli.load_script("site_meta_audit.py")
        audit = site.audit
        self.assertEqual(resolve_site_runtime_policy(site, audit_options={}), POLICY)
        for name in ("MetaParser", "first_meta", "first_link", "open_graph_evidence", "encoded_resource"):
            with self.subTest(helper=name), patch.object(site, name, lambda *args: None):
                self.assertIs(site.audit, audit)
                self.assert_extraction_unknown(site)

    def test_changed_parser_extraction_methods_fail_closed_with_unchanged_class_source(self):
        site = cli.load_script("site_meta_audit.py")
        parser = site.MetaParser
        for name in ("__init__", "handle_starttag", "handle_endtag", "handle_data", "_finish_h1", "finish", "feed"):
            with self.subTest(method=name), patch.object(parser, name, lambda *args: None):
                self.assertIs(site.MetaParser, parser)
                self.assert_extraction_unknown(site)

    def test_inherited_parser_descriptor_overrides_fail_closed(self):
        site = cli.load_script("site_meta_audit.py")
        for name in ("feed", "close", "reset"):
            for value in (property(lambda self: lambda *args: None), None):
                with self.subTest(method=name, descriptor=type(value).__name__), patch.object(site.MetaParser, name, value):
                    self.assert_extraction_unknown(site)

    def test_changed_extraction_code_is_not_hidden_by_reviewed_source_location(self):
        site = cli.load_script("site_meta_audit.py")
        for name in ("first_meta", "first_link", "open_graph_evidence", "encoded_resource"):
            function = getattr(site, name)
            code = function.__code__
            changed = (lambda *args: None).__code__.replace(
                co_filename=code.co_filename, co_firstlineno=code.co_firstlineno)
            with self.subTest(helper=name):
                try:
                    function.__code__ = changed
                    self.assert_extraction_unknown(site)
                finally:
                    function.__code__ = code

    def test_unrecognized_runtime_callables_never_infer_stock_settings_from_name(self):
        site = cli.load_script("site_meta_audit.py")
        def fetch(url, timeout=20):
            return {}
        fetch.__name__ = "fetch"
        with patch.object(site, "fetch", fetch):
            policy = resolve_site_runtime_policy(site, audit_options={})
        self.assertIsNone(policy["timeout_seconds"])
        report = attach(report_fixture(), runtime_policy=policy)
        self.assertEqual(report["comparison"]["scope"]["configuration_status"], "unknown")
        self.assertEqual(report["comparison"]["collection"]["completion"], "unknown")
        with patch.object(site, "fetch_public_url", lambda url, timeout=20: {}):
            policy = resolve_site_runtime_policy(site, audit_options={})
        self.assertIsNone(policy["max_body_bytes"])
        self.assertEqual(policy["timeout_seconds"], 20)
        unknown = resolve_site_runtime_policy(SimpleNamespace())
        self.assertTrue(all(unknown.get(name) is None for name in ("max_body_bytes", "timeout_seconds", "max_redirects")))
        self.assertEqual(unknown["request_headers"], {"User-Agent": None, "Accept": None})

    def test_advertised_signature_cannot_replace_actual_bound_defaults(self):
        site = cli.load_script("site_meta_audit.py")
        follow = site.fetch_public_url.__globals__["follow_public_http"]
        cases = [(site.fetch, "timeout", "timeout_seconds"),
                 (site.fetch_public_url, "max_body_bytes", "max_body_bytes"),
                 (follow, "max_redirects", "max_redirects")]
        for function, parameter, policy_key in cases:
            with self.subTest(parameter=parameter):
                signature = inspect.signature(function)
                actual = signature.parameters[parameter].default
                deceptive = signature.replace(parameters=[
                    item.replace(default=actual + 123) if item.name == parameter else item
                    for item in signature.parameters.values()])
                with patch.object(function, "__signature__", deceptive, create=True):
                    policy = resolve_site_runtime_policy(site, audit_options={})
                self.assertEqual(policy[policy_key], actual)

    def test_changed_redirect_default_is_the_bound_limit_actually_consumed(self):
        site = cli.load_script("site_meta_audit.py")
        http = cli.load_script("public_http.py")
        follow = site.fetch_public_url.__globals__["follow_public_http"]
        with patch.object(follow, "__kwdefaults__", {**follow.__kwdefaults__, "max_redirects": 2}):
            policy = resolve_site_runtime_policy(site, audit_options={})
            with patch.object(http, "request_public_url_once", return_value={
                    "http_status": 302, "content_type": "text/html", "location": "/again",
                    "sample_bytes": 0, "body": b""}) as request:
                result = site.fetch(URL)
        self.assertEqual(policy["max_redirects"], 2)
        self.assertEqual(request.call_count, policy["max_redirects"] + 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "too many redirects")

    def test_registered_cli_mcp_early_returns_and_mocked_configuration_fail_closed(self):
        site = cli.load_script("site_meta_audit.py")
        cases = [
            {"status": "error", "url": URL, "reason": "DNS fixture", "http_status": None},
            {"status": "ok", "url": URL, "http_status": 200, "content_type": "application/pdf",
             "content_encoding": None, "body_truncated": False, "body": "%PDF"},
            {"status": "ok", "url": URL, "http_status": 200, "content_type": "text/html",
             "content_encoding": None, "body_truncated": True, "body": "<title>Seen</title>"},
        ]
        with patch.object(mcp_server, "_require_mcp", return_value=FakeMCP):
            server = mcp_server.build_server()
        for page in cases:
            with self.subTest(page=page), patch.object(site, "fetch", return_value=page):
                policy = resolve_site_runtime_policy(site, audit_options={})
                with redirect_stdout(io.StringIO()) as output:
                    code = cli.main(["site-meta", URL, "--json"])
                report = json.loads(output.getvalue())
                wrapped = json.loads(server.tools["site_meta"](URL))
            self.assertEqual(code, 1 if page["status"] == "error" else 0)
            self.assertEqual(wrapped["exit_code"], code)
            self.assertEqual(report["comparison"], wrapped["comparison"])
            self.assertEqual(len(report["comparison"]["evaluations"]), 5)
            self.assertEqual(report["comparison"]["scope"]["configuration_status"], "unknown")
            self.assertEqual(report["comparison"]["collection"]["completion"], "unknown")
            self.assertIn("configuration_unverified", report["comparison"]["collection"]["reasons"])
            self.assert_valid(report, runtime_policy=policy)

    def test_all_reviewed_examples_validate_against_corresponding_containing_evidence(self):
        for name in ("complete", "truncated", "unknown-policy", "non-html", "fetch-error"):
            with self.subTest(example=name):
                if name == "fetch-error":
                    report = enrich_site_result({"url": URL,
                        "page": {"url": URL, "status": "error", "reason": "timeout"},
                        "capture": {"scope": "raw_html", "rendered": False, "body_truncated": None}})
                elif name == "non-html":
                    report = self.collect_html("%PDF", content_type="application/pdf")
                else:
                    report = self.collect_html(ALL_HTML.replace("<title>Observed</title>", ""),
                                               truncated=name == "truncated")
                report["comparison"] = json.loads((ROOT / "tests/fixtures/comparison_metadata" /
                                            f"example-{name}.comparison.json").read_text())
                report["tool_version"] = report["comparison"]["producer"]["tool_version"]
                policy = copy.deepcopy(POLICY)
                if name == "unknown-policy":
                    policy["max_body_bytes"] = None
                    policy["request_headers"]["User-Agent"] = None
                self.assert_valid(report, runtime_policy=policy)

    def test_malformed_capture_is_unknown_and_never_turns_false_into_absence(self):
        for capture in (None, {}, [], {"scope": "rendered", "rendered": False, "body_truncated": False},
                        {"scope": "raw_html", "rendered": 0, "body_truncated": False},
                        {"scope": "raw_html", "rendered": True, "body_truncated": False}):
            with self.subTest(capture=capture):
                report = report_fixture(present=False)
                report["capture"] = capture
                attach(report)
                self.assertEqual(report["comparison"]["collection"]["completion"], "unknown")
                self.assert_rows(report, "unknown", "incomplete")
                self.assert_valid(report)

    def test_unknown_policy_primitive_values_are_not_silently_coerced(self):
        for key in ("max_body_bytes", "timeout_seconds", "max_redirects"):
            for value in (True, "20", -1, [], {}):
                with self.subTest(key=key, value=value):
                    policy = copy.deepcopy(POLICY)
                    policy[key] = value
                    report = attach(report_fixture(), runtime_policy=policy)
                    self.assertIsNone(report["comparison"]["scope"]["limits"][key])
                    self.assertEqual(report["comparison"]["scope"]["configuration_status"], "unknown")

    def test_missing_or_malformed_encoding_is_not_assumed_unencoded(self):
        for encoding in ("missing", [], {}, 0, True):
            with self.subTest(encoding=encoding):
                report = report_fixture()
                if encoding == "missing":
                    del report["page"]["content_encoding"]
                else:
                    report["page"]["content_encoding"] = encoding
                attach(report)
                self.assert_rows(report, "unknown", "incomplete", "missing_capture_evidence")
                self.assertEqual(report["comparison"]["collection"]["completion"], "unknown")
                self.assert_valid(report)
        for encoding in (None, "", "identity", "IDENTITY"):
            report = report_fixture()
            report["page"]["content_encoding"] = encoding
            attach(report)
            self.assertEqual(report["comparison"]["collection"]["completion"], "complete")

    def test_runtime_policy_does_not_copy_secret_or_unrelated_configuration(self):
        policy = copy.deepcopy(POLICY)
        marker = "private-fixture-value-do-not-copy"
        policy.update(proxy=marker, environment={"TOKEN": marker}, credentials=marker)
        policy["request_headers"].update(Authorization=marker, Cookie=marker)
        report = attach(report_fixture(), runtime_policy=policy)
        self.assertNotIn(marker, json.dumps(report["comparison"]))
        self.assertEqual(report["comparison"]["scope"]["request_headers"], POLICY["request_headers"])
        self.assert_valid(report, runtime_policy=policy)

    def test_extra_block_fields_and_malformed_shapes_are_rejected_deterministically(self):
        for key in (None, "producer", "target", "scope", "collection", "provenance"):
            report = attach(report_fixture())
            block = report["comparison"] if key is None else report["comparison"][key]
            block["not_in_v1"] = "extra"
            self.assertTrue(validate_site_comparison_metadata(report))
        for value in (None, [], "invalid", 1, True, {}):
            report = report_fixture()
            report["comparison"] = value
            errors = validate_site_comparison_metadata(report)
            self.assertIsInstance(errors, list)
            self.assertTrue(errors)

    def test_approved_example_and_schema_bytes_are_unchanged(self):
        expected = {
            "example-complete.comparison.json": "75fe8e8a5b4709e32160aebb13ff3039de992ce993ea1e5f97327a77461bef0a",
            "example-fetch-error.comparison.json": "1531620acd14b0aeea653d1d9869503bc95dfc7f5b8b86e970226ab55f903030",
            "example-non-html.comparison.json": "9b107a48798cc53e47af67c408714e7881c2532a2af204d3ae155db3100aa937",
            "example-truncated.comparison.json": "3828807b34ed56200274b2e7a69a98c5130b793fbf58b827fa1e045f0eb96c0a",
            "example-unknown-policy.comparison.json": "4038465d786f1fed15e7199406a9f98c402a2221f5531fcb72b051d9dd3ebabc",
        }
        for filename, digest in expected.items():
            data = (ROOT / "tests/fixtures/comparison_metadata" / filename).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
            self.assertEqual(json.loads(data)["producer"]["tool_version"], "0.2.0")
        schema = ROOT / "references/comparison-metadata.schema.json"
        self.assertEqual(hashlib.sha256(schema.read_bytes()).hexdigest(),
                         "90e0d243ea748cf2df5df656c42c613614543cee8fae9ad1fa17d9aef1b80b58")

    def test_approved_complete_example_matches_builder_output(self):
        report = report_fixture()
        report["checks"]["has_title"] = False
        # Regenerate legacy links for the precise reviewed example.
        report = enrich_site_result({k: v for k, v in report.items()
                                     if k not in {"schema_version", "tool_version", "target", "status", "findings"}})
        block = build_site_comparison_metadata(report, URL, POLICY)
        expected = json.loads((ROOT / "tests/fixtures/comparison_metadata/example-complete.comparison.json").read_text())
        expected["producer"]["tool_version"] = __version__
        self.assertEqual(block, expected)


if __name__ == "__main__":
    unittest.main()
