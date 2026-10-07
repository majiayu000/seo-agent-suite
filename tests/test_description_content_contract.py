"""Offline contracts for usable description content, preserving raw evidence."""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import site_meta_audit as site


class DescriptionContentContractTests(unittest.TestCase):
    url = "https://example.com/page"

    def audit_description(self, declaration, *, truncated=False):
        body = ('<head><title>Example</title>' + declaration
                + '<link rel="canonical" href="https://example.com/page">'
                + '</head><body><h1>Example</h1></body>')
        page = {"status": "ok", "url": self.url, "http_status": 200,
                "body": body, "body_truncated": truncated, "content_type": "text/html"}
        def fetch(target):
            return page if target == self.url else {
                "status": "error", "url": target, "http_status": 404,
                "body": "", "body_truncated": False, "content_type": "text/plain"}
        with patch.object(site, "fetch", side_effect=fetch):
            return site.audit(self.url)

    def assert_presence(self, declaration, raw, present, *, truncated=False):
        result = self.audit_description(declaration, truncated=truncated)
        self.assertEqual(result["meta_description"], raw)
        self.assertIs(result["checks"]["has_meta_description"], present)
        self.assertEqual(result["assessment"]["observations"]["description_length"], len(raw or ""))
        missing = [f for f in result["findings"] if f["code"] == "meta_description_missing"]
        self.assertEqual(bool(missing), not present and not truncated)
        if missing:
            self.assertEqual(missing[0]["severity"], "warning")
            self.assertEqual(missing[0]["confidence"], "Confirmed")
            self.assertEqual(missing[0]["evidence"], "meta_description")
        if truncated:
            self.assertIn("capture_incomplete", {f["code"] for f in result["findings"]})
        return result

    def test_missing_and_empty_content(self):
        for declaration in ('', '<meta name="description">', '<meta name="description" content="">'):
            with self.subTest(declaration=declaration):
                self.assert_presence(declaration, None, False)

    def test_whitespace_only_content(self):
        for raw in (' ', '\t\n\r ', '\u00a0\u2003\u202f'):
            with self.subTest(raw=raw):
                self.assert_presence(f'<meta name="description" content="{raw}">', raw, False)

    def test_entity_whitespace_content(self):
        self.assert_presence('<meta name="description" content="&nbsp;&#32;&#9;&#10;&#x2003;">',
                             '\u00a0 \t\n\u2003', False)

    def test_nonblank_content_preserves_padding(self):
        for raw in ('x', '  Useful description\t', '\u00a0中文描述\u2003'):
            with self.subTest(raw=raw):
                self.assert_presence(f'<meta name="description" content="{raw}">', raw, True)

    def test_no_ideal_length_threshold(self):
        self.assert_presence('<meta name="description" content="x">', 'x', True)
        raw = 'x' * 1000
        self.assert_presence(f'<meta name="description" content="{raw}">', raw, True)

    def test_truncated_absence_stays_unknown(self):
        for declaration, raw in (('', None), ('<meta name="description" content="">', None),
                                 ('<meta name="description" content="  ">', '  ')):
            with self.subTest(declaration=declaration):
                self.assert_presence(declaration, raw, False, truncated=True)

    def test_truncated_observed_content_stays_present(self):
        self.assert_presence('<meta name="description" content=" x ">', ' x ', True, truncated=True)

    def test_first_declaration_selection_is_unchanged(self):
        self.assert_presence('<meta name="description" content="  ">'
                             '<meta name="description" content="later">', '  ', False)

    def test_unrelated_checks_and_assessments_are_unchanged(self):
        blank = self.audit_description('<meta name="description" content="   ">')
        full = self.audit_description('<meta name="description" content="abc">')
        self.assertEqual({k: v for k, v in blank["checks"].items() if k != "has_meta_description"},
                         {k: v for k, v in full["checks"].items() if k != "has_meta_description"})
        self.assertEqual(blank["assessment"], full["assessment"])
        self.assertEqual([f for f in blank["findings"] if f["code"] != "meta_description_missing"],
                         full["findings"])

    def test_cli_keeps_default_fetch_exit_and_opt_in_warning_gate(self):
        result = self.audit_description('<meta name="description" content="  ">')
        for args, expected in (([], 0), (["--fail-on", "warning"], 1), (["--fail-on", "error"], 0)):
            with self.subTest(args=args), patch.object(site, "audit", return_value=result), \
                    patch.object(sys, "argv", ["site_meta_audit.py", self.url, "--json", *args]), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(site.main(), expected)
                self.assertEqual(json.loads(output.getvalue())["meta_description"], '  ')


if __name__ == "__main__":
    unittest.main()
