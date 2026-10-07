"""Offline Open Graph evidence regressions; no media or page requests."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import site_meta_audit as site


class OpenGraphRegressionTests(unittest.TestCase):
    def audit_html(self, body):
        url = "https://example.invalid/page"
        page = {"status": "ok", "url": url, "body": body,
                "content_type": "text/html", "body_truncated": False}
        resources = {"robots_txt": [], "sitemap_xml": [], "sitemap_discovery": {},
                     "robots_access": site.robots_access({"http_status": 404}, url)}
        with patch.object(site, "fetch", return_value=page) as fetch, \
                patch.object(site, "crawl_resource_checks", return_value=resources):
            result = site.audit(url)
        fetch.assert_called_once_with(url)
        return result

    def test_first_image_keeps_its_width_and_order(self):
        result = self.audit_html('''<head>
            <meta property="og:image" content="https://example.invalid/first.png">
            <meta property="og:image:width" content="100">
            <meta property="og:image" content="https://example.invalid/second.png">
            </head>''')
        self.assertEqual(result["open_graph"], {
            "og:image": "https://example.invalid/first.png", "og:image:width": "100"})
        self.assertEqual(result["open_graph_declarations"], [
            {"property": "og:image", "content": "https://example.invalid/first.png", "location": "head"},
            {"property": "og:image:width", "content": "100", "location": "head"},
            {"property": "og:image", "content": "https://example.invalid/second.png", "location": "head"},
        ])

    def test_later_dimensions_are_not_attached_to_first_image(self):
        for first, second in [("first.png", "second.png"), ("second.png", "first.png")]:
            with self.subTest(first=first):
                result = self.audit_html(f'''<meta property="og:image" content="{first}">
                    <meta property="og:image" content="{second}">
                    <meta property="og:image:width" content="100">
                    <meta property="og:image:height" content="200">''')
                self.assertEqual(result["open_graph"], {"og:image": first})
                self.assertEqual(len(result["open_graph_declarations"]), 4)

    def test_equal_image_urls_still_start_separate_roots(self):
        result = self.audit_html('''<meta property="og:image" content="same.png">
            <meta property="og:image:width" content="100">
            <meta property="og:image" content="same.png">
            <meta property="og:image:height" content="200">''')
        self.assertEqual(result["open_graph"], {"og:image": "same.png", "og:image:width": "100"})
        self.assertEqual([x["content"] for x in result["open_graph_declarations"]],
                         ["same.png", "100", "same.png", "200"])

    def test_image_url_alias_is_a_root_without_inventing_a_key(self):
        for first, second in [("og:image:url", "og:image"), ("og:image", "og:image:url")]:
            with self.subTest(first=first):
                result = self.audit_html(f'''<meta property="{first}" content="first.png">
                    <meta property="og:image:alt" content="First image">
                    <meta property="{second}" content="second.png">
                    <meta property="og:image:width" content="200">''')
                self.assertEqual(result["open_graph"], {first: "first.png", "og:image:alt": "First image"})
                self.assertEqual([x["property"] for x in result["open_graph_declarations"]],
                                 [first, "og:image:alt", second, "og:image:width"])

    def test_duplicate_image_attributes_use_first_and_preserve_all_evidence(self):
        result = self.audit_html('''<meta property="og:image" content="first.png">
            <meta property="og:image:width" content="100">
            <meta property="og:image:width" content="200">''')
        self.assertEqual(result["open_graph"]["og:image:width"], "100")
        self.assertEqual([x["content"] for x in result["open_graph_declarations"]],
                         ["first.png", "100", "200"])

    def test_orphan_properties_are_only_raw_evidence(self):
        result = self.audit_html('''<meta property="og:image:width" content="100">
            <meta property="og:image" content="first.png">
            <meta property="og:image:height" content="200">''')
        self.assertEqual(result["open_graph"], {"og:image": "first.png", "og:image:height": "200"})
        self.assertEqual(result["open_graph_declarations"][0]["content"], "100")

    def test_another_open_graph_root_ends_image_properties(self):
        for root in ["og:title", "og:video", "og:audio", "og:video:url", "og:audio:url"]:
            with self.subTest(root=root):
                result = self.audit_html(f'''<meta property="og:image" content="first.png">
                    <meta property="og:image:width" content="100">
                    <meta property="{root}" content="other">
                    <meta property="og:image:height" content="200">''')
                self.assertEqual(result["open_graph"], {
                    "og:image": "first.png", "og:image:width": "100", root: "other"})
                self.assertEqual(result["open_graph_declarations"][-1]["property"], "og:image:height")

    def test_blank_first_root_and_attributes_are_not_skipped(self):
        result = self.audit_html('''<meta property="og:image">
            <meta property="og:image:width" content="">
            <meta property="og:image:width" content="100">
            <meta property="og:image" content="second.png">''')
        self.assertEqual(result["open_graph"], {"og:image": "", "og:image:width": ""})
        self.assertEqual([x["content"] for x in result["open_graph_declarations"]],
                         ["", "", "100", "second.png"])

    def test_single_image_keeps_all_its_supplied_fields(self):
        fields = {"og:image": "image.png", "og:image:secure_url": "https://example.invalid/image.png",
                  "og:image:type": "image/png", "og:image:width": "100", "og:image:height": "200",
                  "og:image:alt": "An image"}
        result = self.audit_html("".join(f'<meta property="{key}" content="{value}">' for key, value in fields.items()))
        self.assertEqual(result["open_graph"], fields)
        self.assertTrue(all(x["location"] == "head" for x in result["open_graph_declarations"]))

    def test_non_image_and_twitter_duplicate_semantics_are_unchanged(self):
        result = self.audit_html('''<head><meta property="og:title" content="First">
            <meta property="og:locale:alternate" content="en_GB">
            <meta name="twitter:image" content="first.png"></head><body>
            <meta property="og:title" content="Last"><meta property="og:locale:alternate" content="fr_FR">
            <meta name="twitter:image" content="second.png"></body>''')
        self.assertEqual(result["open_graph"], {"og:title": "Last", "og:locale:alternate": "fr_FR"})
        self.assertEqual(result["twitter"], {"twitter:image": "second.png"})
        self.assertTrue(result["checks"]["has_og_title"])
        self.assertEqual([x["location"] for x in result["open_graph_declarations"]], ["head", "head", "body", "body"])

    def test_no_open_graph_and_properties_without_a_root(self):
        result = self.audit_html('<title>No metadata</title>')
        self.assertEqual(result["open_graph"], {})
        self.assertEqual(result["open_graph_declarations"], [])
        self.assertFalse(result["checks"]["has_og_title"])
        result = self.audit_html('<meta property="og:image:width" content="100">')
        self.assertEqual(result["open_graph"], {})
        self.assertEqual(result["open_graph_declarations"][0]["content"], "100")

    def test_new_evidence_and_summary_redact_url_userinfo(self):
        result = self.audit_html('''<meta property="og:image" content="https://user:secret@example.invalid/first.png" data-debug="private">
            <meta property="og:image:secure_url" content="https://user:secret@example.invalid/secure.png">
            <meta property="og:image" content="https://user:secret@[bad/">
            <meta property="og:description" content="See https://user:secret@example.invalid/doc">
            <meta property="og:url" content="https://user:secret@example.invalid:notaport/">''')
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(result["open_graph"]["og:image"], "https://example.invalid/first.png")
        self.assertEqual(result["open_graph_declarations"][2]["content"], "https://[bad/")
        self.assertEqual(result["open_graph_declarations"][3]["content"], "See https://example.invalid/doc")


if __name__ == "__main__":
    unittest.main()
