"""Offline tests for main-document metadata context boundaries."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import site_meta_audit as site


class MetadataContextTests(unittest.TestCase):
    def parse(self, body):
        parser = site.MetaParser()
        parser.feed(body)
        parser.finish()
        return parser

    def test_template_descendants_are_not_document_metadata(self):
        fragment = ('<title>Dormant</title><meta name="description" content="Dormant">'
                    '<link rel="canonical" href="/dormant">'
                    '<script type="application/ld+json">{}</script><h1>Dormant</h1>')
        for attributes in ("", ' shadowrootmode="open"'):
            with self.subTest(attributes=attributes):
                parser = self.parse(f"<template{attributes}>{fragment}</template>")
                self.assertEqual((parser.title, parser.h1, parser.meta, parser.links, parser.json_ld_count),
                                 ("", [], [], [], 0))

    def test_nested_template_resumes_real_metadata_and_surrounding_heading(self):
        parser = self.parse(
            '<head><template><template><title>Dormant</title></template>'
            '<meta name="description" content="Dormant"></template>'
            '<title>Actual</title><meta name="description" content="Actual"></head>'
            '<body><h1>Main <template><h1>Dormant</h1></template>heading</h1></body>'
        )
        self.assertEqual(parser.title, "Actual")
        self.assertEqual(site.first_meta(parser, "name", "description"), "Actual")
        self.assertEqual(parser.meta[0]["location"], "head")
        self.assertEqual(parser.h1, ["Main heading"])

    def test_svg_titles_do_not_change_document_title(self):
        parser = self.parse('<head><title>Actual</title></head>'
                            '<svg><title>Icon</title><svg><title>Nested icon</title></svg>'
                            '<foreignObject><h1>Embedded heading</h1></foreignObject></svg>'
                            '<h1>Normal heading</h1>')
        self.assertEqual(parser.title, "Actual")
        self.assertEqual(parser.h1, ["Embedded heading", "Normal heading"])

    def test_heading_omits_code_but_retains_json_ld_evidence(self):
        parser = self.parse(
            '<h1>Main<script>syntheticCode()</script><style>.synthetic{color:red}</style>'
            '<script type="application/ld+json">{"@type":"Thing"}</script> heading</h1>'
        )
        self.assertEqual(parser.h1, ["Main heading"])
        self.assertEqual(parser.json_ld_count, 1)
        self.assertEqual(parser.json_ld[0]["types"], ["Thing"])

    def test_inert_fragment_does_not_make_audit_presence_checks_true(self):
        url = "https://example.invalid/"
        page = {"status": "ok", "url": url, "http_status": 200,
                "content_type": "text/html", "body_truncated": False,
                "body": '<template><title>Dormant</title><meta name="description" content="Dormant">'
                        '<link rel="canonical" href="/dormant"><script type="application/ld+json">'
                        '{}</script></template>'}
        with patch.object(site, "fetch", side_effect=lambda target: page if target == url else
                          {"status": "error", "url": target, "http_status": 404, "body": ""}):
            result = site.audit(url)
        for name in ("has_title", "has_meta_description", "has_canonical", "has_json_ld"):
            self.assertFalse(result["checks"][name], name)


if __name__ == "__main__":
    unittest.main()
