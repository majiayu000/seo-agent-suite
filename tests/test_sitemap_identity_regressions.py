"""Offline XML identity checks shared by page and repository audits."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import repo_seo_baseline as repo
import site_meta_audit as site

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


class SitemapIdentityTests(unittest.TestCase):
    def response(self, body, **extra):
        return {"status": "ok", "http_status": 200, "url": "https://example.invalid/sitemap.xml",
                "content_type": "application/xml", "body": body, "body_truncated": False, **extra}

    def test_comments_and_equivalent_child_prefixes_do_not_change_identity(self):
        bodies = [
            f'<urlset xmlns="{NS}"><!-- <html> is comment text --></urlset>',
            *[f'<urlset xmlns="{NS}" xmlns:{prefix}="http://www.w3.org/1999/xhtml">'
              f'<url><{prefix}:link rel="alternate" href="https://example.invalid/"/></url></urlset>'
              for prefix in ("html", "xhtml")],
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertTrue(site.resource_present(self.response(body), "sitemap.xml")[0])

    def test_root_namespace_is_checked_without_removing_legacy_no_namespace_support(self):
        for root in ("urlset", "sitemapindex"):
            for body, present in [
                (f'<{root} xmlns="{NS}"/>', True),
                (f'<s:{root} xmlns:s="{NS}"/>', True),
                (f'<{root}/>', True),
                (f'<{root} xmlns="urn:synthetic:other"/>', False),
                (f'<s:{root} xmlns:s="urn:synthetic:other"/>', False),
            ]:
                with self.subTest(body=body):
                    item = self.response(body)
                    self.assertEqual(site.resource_present(item, "sitemap.xml")[0], present)
                    self.assertEqual(site.resource_check(item, "sitemap.xml")["present"], present)

    def test_html_and_malformed_xml_still_fail(self):
        for item in [
            self.response("<html><body>Missing</body></html>"),
            self.response("<urlset><broken></urlset>"),
            self.response(f'<urlset xmlns="{NS}"/>', content_type="text/html; charset=utf-8"),
        ]:
            with self.subTest(item=item):
                self.assertFalse(site.resource_present(item, "sitemap.xml")[0])

    def test_page_and_repository_resource_consumers_share_the_result(self):
        for body, expected in [
            (f'<urlset xmlns="{NS}"><!-- <html> --></urlset>', True),
            ('<urlset xmlns="urn:synthetic:other"/>', False),
        ]:
            def fetch(url):
                if url.endswith("/sitemap.xml"):
                    return self.response(body, url=url)
                return {"status": "error", "http_status": 404, "url": url, "body": ""}

            with self.subTest(body=body), patch.object(site, "fetch", side_effect=fetch), \
                    patch.object(repo, "http_check", return_value={"status": "ok"}):
                self.assertEqual(repo.site_resource_checks("https://example.invalid")["sitemap"]["status"] == "ok", expected)
                self.assertEqual(site.crawl_resource_checks("https://example.invalid")["sitemap_xml"][0]["present"], expected)


if __name__ == "__main__":
    unittest.main()
