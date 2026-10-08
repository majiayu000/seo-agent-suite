"""Offline P06 comparisons: whole-pair gates, bounded input and CLI behavior."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from seo_agent_suite import cli
from seo_agent_suite.compare import compare_reports, MAX_INPUT_BYTES, MAX_CONTAINER_DEPTH
from seo_agent_suite.comparison_metadata import build_site_comparison_metadata
from test_comparison_metadata import report_fixture, attach, URL, POLICY, RULE_CHECKS


def report(present=True, **kwargs):
    return attach(report_fixture(present=present, **kwargs))


def encoded(value):
    return json.dumps(value).encode("utf-8")


def compare(before, after):
    return compare_reports(encoded(before), encoded(after))


class CompareTests(unittest.TestCase):
    def assert_incomparable(self, before, after):
        result = compare(before, after)
        self.assertEqual(result["status"], "incomparable", result)
        self.assertEqual(result["changes"], [])
        self.assertIsNone(result["counts"])
        self.assertTrue(result["reasons"])
        return result

    def test_new(self):
        result = compare(report(True), report(False))
        self.assertEqual(result["counts"], dict(new=5, persistent=0, resolved=0, unchanged_passing=0))
        self.assertEqual([r["outcome"] for r in result["changes"]], ["new"] * 5)

    def test_persistent(self):
        self.assertEqual(compare(report(False), report(False))["counts"]["persistent"], 5)

    def test_resolved(self):
        self.assertEqual(compare(report(False), report(True))["counts"]["resolved"], 5)

    def test_unchanged(self):
        result = compare(report(), report())
        self.assertEqual(result["counts"]["unchanged_passing"], 5)
        self.assertEqual(result["changes"], [])

    def test_mixed_deterministic_order_and_evidence(self):
        before, after = report(False), report(False)
        for value, rule in ((before, "site.meta.canonical"), (after, "site.meta.description")):
            value["checks"][RULE_CHECKS[rule]] = True
            value["findings"] = []
            attach(value)
        result = compare(before, after)
        self.assertEqual(result["counts"], dict(new=1, resolved=1, persistent=3, unchanged_passing=0))
        self.assertEqual([r["rule_id"] for r in result["changes"]], sorted(RULE_CHECKS))
        for i, row in enumerate(result["changes"]):
            for side, source in (("before", before), ("after", after)):
                self.assertEqual(row[side]["evaluation_ref"], f"/comparison/evaluations/{i}")
                for pointer in row[side]["evidence_refs"]:
                    current = source
                    for key in pointer[1:].split("/"):
                        current = current[key]
        self.assertEqual(compare(before, after), result)

    def test_legacy_never_upgraded(self):
        before = report()
        del before["comparison"]
        self.assert_incomparable(before, report())
        self.assertNotIn("comparison", before)

    def test_repository_unsupported(self):
        self.assert_incomparable({"schema_version": "1.0", "target": {"kind": "repo", "id": "/root"}}, report())

    def test_version_contract_and_schema(self):
        for key in ("contract_version",):
            with self.subTest(key=key):
                after = report(); after["comparison"][key] = "99"
                self.assert_incomparable(report(), after)
        after = report(); after["schema_version"] = "99"
        self.assert_incomparable(report(), after)

    def test_producer_ruleset_and_tool(self):
        for key in ("id", "ruleset_id", "ruleset_version", "report_schema_version", "tool_version"):
            with self.subTest(key=key):
                after = report(); after["comparison"]["producer"][key] = "99"
                self.assert_incomparable(report(), after)
        before, after = report(), report()
        for value in (before, after):
            value["tool_version"] = value["comparison"]["producer"]["tool_version"] = "99"
        result = self.assert_incomparable(before, after)
        self.assertEqual(result["reasons"][0]["code"], "unsupported_tool_version")

    def test_exact_requested_target(self):
        for url in (URL + "?a=1", URL + "#fragment", URL.upper(), URL.rstrip("/"), "https://example.com:443/docs/"):
            with self.subTest(url=url):
                after = report_fixture(url=url, effective=URL)
                attach(after, requested_url=url)
                self.assert_incomparable(report(), after)

    def test_redirect_target(self):
        self.assert_incomparable(report(), report(effective="https://example.com/other/"))

    def test_scope_changed(self):
        for key in ("max_body_bytes", "timeout_seconds", "max_redirects"):
            after = report(); policy = copy.deepcopy(POLICY); policy[key] += 1
            attach(after, runtime_policy=policy)
            self.assert_incomparable(report(), after)
        after = report(); policy = copy.deepcopy(POLICY); policy["request_headers"]["User-Agent"] += " changed"
        attach(after, runtime_policy=policy)
        self.assert_incomparable(report(), after)

    def test_unknown_policy_even_when_equal(self):
        before = report(); policy = copy.deepcopy(POLICY); policy["max_body_bytes"] = None
        attach(before, runtime_policy=policy)
        self.assert_incomparable(before, before)

    def test_truncated_positive_cannot_resolve(self):
        self.assert_incomparable(report(False), report(True, truncated=True))

    def test_unknown_before_cannot_be_new(self):
        self.assert_incomparable(report(False, truncated=True), report(False))

    def test_failed_fetch(self):
        after = report(); after["page"]["status"] = "error"; attach(after)
        self.assert_incomparable(report(False), after)

    def test_skip_nonhtml(self):
        after = report(); after["page"]["content_type"] = "application/json"; attach(after)
        self.assert_incomparable(report(False), after)

    def test_missing_check_and_capture(self):
        for section, key in (("checks", "has_title"), ("capture", "body_truncated")):
            after = report(); del after[section][key]; attach(after)
            self.assert_incomparable(report(False), after)

    def test_missing_duplicate_extra_and_unknown_ledger(self):
        for mode in ("missing", "duplicate", "extra", "unknown", "subject", "order"):
            with self.subTest(mode=mode):
                after = report(); rows = after["comparison"]["evaluations"]
                if mode == "missing": rows.pop()
                if mode == "duplicate": rows[1] = copy.deepcopy(rows[0])
                if mode == "extra": rows.append(copy.deepcopy(rows[0]))
                if mode == "unknown": rows[0]["outcome"] = "unknown"
                if mode == "subject": rows[0]["subject_id"] = "other"
                if mode == "order": rows.reverse()
                self.assert_incomparable(report(), after)

    def test_broken_evidence_and_legacy_links(self):
        for key, value in (("evidence_refs", ["/not-present"]), ("legacy_finding_ids", ["nonexistent"])):
            after = report(); after["comparison"]["evaluations"][0][key] = value
            self.assert_incomparable(report(), after)
        after = report(); after["findings"].append(copy.deepcopy(after["findings"][0]))
        self.assert_incomparable(report(), after)

    def test_resources_failure_does_not_claim_resolution(self):
        after = report(); after["checks"]["robots_txt"] = [{"status": "error"}]
        after["checks"]["sitemap_discovery"] = {"complete": False}; attach(after)
        result = compare(report(False), after)
        self.assertEqual(result["status"], "comparable")
        self.assertEqual(result["resources"], "excluded")
        self.assertTrue(all(r["subject_id"] == "page" for r in result["changes"]))

    def test_observation_only_changes_do_not_gate(self):
        after = report(); after["collected_at"] = "different"
        after["status"] = "partial"
        for finding in after["findings"]:
            finding.update(severity="error", detail="changed")
        self.assertEqual(compare(report(), after)["status"], "comparable")

    def test_digests_exact_bytes_and_whitespace(self):
        before = encoded(report()); after = b"\n " + before
        result = compare_reports(before, after)
        self.assertEqual(result["status"], "comparable")
        self.assertEqual(result["inputs"]["before"]["sha256"], hashlib.sha256(before).hexdigest())
        self.assertNotEqual(result["inputs"]["before"], result["inputs"]["after"])

    def test_pure_no_io_or_mutation(self):
        before, after = encoded(report(False)), encoded(report())
        originals = before[:], after[:]
        with ExitStack() as stack:
            for target in ("builtins.open", "pathlib.Path.open", "socket.socket", "socket.getaddrinfo", "subprocess.Popen", "os.system", "seo_agent_suite.cli.load_script", "seo_agent_suite.cli.resolve_site_runtime_policy"):
                stack.enter_context(patch(target, side_effect=AssertionError("I/O forbidden")))
            self.assertEqual(compare_reports(before, after)["status"], "comparable")
        self.assertEqual((before, after), originals)

    def test_malformed_root_and_type(self):
        for data in (b"{", b"[]", b"null", b"42", b'"text"', b"\xff", b"\xef\xbb\xbf{}", "{}", {}):
            with self.subTest(data=data):
                result = compare_reports(data, encoded(report()))
                self.assertEqual(result["status"], "invalid_input", result)
                self.assertEqual(result["changes"], [])
                self.assertIsNone(result["counts"])

    def test_duplicate_any_depth(self):
        for data in (b'{"x":1,"x":2}', b'{"extra":{"x":1,"x":2}}', b'{"a":1,"\\u0061":2}'):
            result = compare_reports(data, encoded(report()))
            self.assertEqual(result["reasons"][0]["code"], "duplicate_object_key")

    def test_nonfinite(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"):
            result = compare_reports(('{"x":' + value + '}').encode(), encoded(report()))
            self.assertEqual(result["reasons"][0]["code"], "nonfinite_number")

    def test_depth_exact_boundary(self):
        value = report(); value["extra"] = "end"
        for _ in range(MAX_CONTAINER_DEPTH - 1): value["extra"] = [value["extra"]]
        self.assertEqual(compare(value, value)["status"], "comparable")
        value["extra"] = [value["extra"]]
        result = compare(value, value)
        self.assertEqual(result["status"], "invalid_input")
        self.assertEqual(result["reasons"][0]["code"], "depth_limit_exceeded")

    def test_depth_strings_escapes_and_prevalidation(self):
        value = report(); value["extra"] = '[{"escaped":"\\\\\\\""}]' * 200
        self.assertEqual(compare(value, value)["status"], "comparable")
        with patch("seo_agent_suite.compare.validate_site_comparison_metadata", side_effect=AssertionError("too early")):
            self.assertEqual(compare_reports(b'{"x":' + b'[' * 65 + b'0' + b']' * 65 + b'}', b'{}')["status"], "invalid_input")

    def test_parser_recursion_is_deterministic(self):
        with patch("seo_agent_suite.compare.json.loads", side_effect=RecursionError):
            result = compare_reports(b'{}', b'{}')
        self.assertEqual(result["reasons"][0]["code"], "parser_recursion_limit")

    def test_size_exact_boundary(self):
        raw = encoded(report()); at_limit = raw + b' ' * (MAX_INPUT_BYTES - len(raw))
        self.assertEqual(compare_reports(at_limit, raw)["status"], "comparable")
        result = compare_reports(at_limit + b' ', raw)
        self.assertEqual(result["reasons"][0]["code"], "size_limit_exceeded")
        self.assertIsNone(result["inputs"]["before"]["sha256"])


class CompareCliTests(unittest.TestCase):
    def invoke(self, *args):
        output = io.StringIO()
        with redirect_stdout(output): code = cli.main(["compare", *map(str, args), "--json"])
        return code, json.loads(output.getvalue())

    def test_cli_exits_and_unchanged_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            before, after = Path(root) / "before.json", Path(root) / "after.json"
            before.write_bytes(encoded(report())); after.write_bytes(encoded(report(False)))
            original = before.read_bytes(), after.read_bytes()
            with patch.object(cli, "load_script", side_effect=AssertionError("no collectors")), patch("socket.getaddrinfo", side_effect=AssertionError("no DNS")), patch("subprocess.Popen", side_effect=AssertionError("no subprocess")):
                code, result = self.invoke(before, after)
            self.assertEqual(code, 0)  # New failures are not an implicit severity CI gate.
            self.assertEqual(result["counts"]["new"], 5)
            self.assertEqual((before.read_bytes(), after.read_bytes()), original)
            after.write_bytes(b'{}'); self.assertEqual(self.invoke(before, after)[0], 1)
            after.write_bytes(b'{'); self.assertEqual(self.invoke(before, after)[0], 2)
            self.assertEqual(self.invoke(before, Path(root) / "missing")[0], 2)
            self.assertEqual(self.invoke(root, before)[0], 2)
            self.assertEqual(self.invoke("-", before)[0], 2)

    def test_cli_bounded_read_size(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "a.json"
            path.write_bytes(encoded(report()))
            real_fdopen = os.fdopen
            lengths = []
            class Reader:
                def __init__(self, fd): self.stream = real_fdopen(fd, "rb")
                def __enter__(self): return self
                def __exit__(self, *args): self.stream.close()
                def read(self, size):
                    lengths.append(size)
                    return self.stream.read(size)
            with patch("os.fdopen", side_effect=lambda fd, mode: Reader(fd)):
                self.assertEqual(self.invoke(path, path)[0], 0)
            self.assertEqual(lengths, [MAX_INPUT_BYTES + 1, MAX_INPUT_BYTES + 1])
            path.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
            self.assertEqual(self.invoke(path, path)[0], 2)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO")
    def test_fifo_rejected_without_waiting(self):
        with tempfile.TemporaryDirectory() as root:
            fifo = Path(root) / "fifo"; os.mkfifo(fifo)
            code, result = self.invoke(fifo, fifo)
            self.assertEqual(code, 2)
            self.assertEqual(result["reasons"][0]["code"], "expected_regular_file")

    def test_text_output_and_argument_shape(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "a.json"; path.write_bytes(encoded(report()))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli.main(["compare", str(path), str(path)]), 0)
            self.assertIn("unchanged_passing: 5", output.getvalue())
        with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            for args in (["compare"], ["compare", "a", "b", "c"], ["compare", "a", "b", "--output", "x"]):
                with self.assertRaises(SystemExit) as caught: cli.main(args)
                self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
