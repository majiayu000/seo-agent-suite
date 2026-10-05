"""Offline regressions for metadata evidence and crawl-resource discovery."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import site_meta_audit as site


class SiteRegressionTests(unittest.TestCase):
    def response(self, url, body="", code=200, **extra):
        return {"status": "ok" if code == 200 else "error", "url": url,
                "http_status": code, "body": body, "body_truncated": False,
                "content_type": "text/plain", **extra}

    def audit_html(self, body, **extra):
        url = "https://example.com/docs/page"
        page = self.response(url, body, content_type="text/html", **extra)
        with patch.object(site, "fetch", side_effect=lambda target: page if target == url else self.response(target, code=404)):
            return site.audit(url)

    def test_all_directives_canonicals_and_hreflang_survive(self):
        result = self.audit_html('''<head><base href="/localized/">
            <meta name="robots" content="index"><meta name="robots" content="noindex">
            <meta name="Googlebot" content="nosnippet">
            <link rel="canonical" href="first"><link rel="alternate" hreflang="zh" href="zh/">
            </head><body><link rel="canonical" href="second"></body>''',
            x_robots_tag=["noindex", "googlebot: nosnippet"], link_headers=['<https://example.com>; rel="canonical"'], redirects=[{"http_status": 302}])
        self.assertEqual([item["content"] for item in result["robots_meta_declarations"]], ["index", "noindex", "nosnippet"])
        self.assertEqual([item["location"] for item in result["canonicals"]], ["head", "body"])
        self.assertEqual([item["resolved_url"] for item in result["canonicals"]], ["https://example.com/localized/first", "https://example.com/localized/second"])
        self.assertEqual(result["hreflang"][0]["hreflang"], "zh")
        self.assertEqual(result["page"]["x_robots_tag"], ["noindex", "googlebot: nosnippet"])
        self.assertEqual(result["capture"]["scope"], "raw_html")
        self.assertTrue(result["collected_at"].endswith("Z"))

    def test_json_ld_presence_is_separate_from_parsing(self):
        result = self.audit_html('''<script type="application/ld+json"></script>
            <script type="application/ld+json">{bad}</script>
            <script type="application/ld+json">[{"@graph":[{"@type":["Article","Thing"],"@id":"#a"}]}]</script>''')
        self.assertTrue(result["checks"]["has_json_ld"])
        self.assertEqual(result["json_ld_count"], 3)
        self.assertEqual([item["status"] for item in result["json_ld"]], ["empty", "invalid_json", "parsed"])
        self.assertEqual(result["json_ld"][2]["types"], ["Article", "Thing"])
        self.assertEqual(result["json_ld"][2]["ids"], ["#a"])

    def test_robots_sitemaps_are_discovered_and_deduplicated(self):
        origin = "https://example.com"
        robots = "User-agent: *\nSitemap: https://example.com/custom.xml\nsitemap: https://example.com/custom.xml\nSitemap: https://example.com/sitemap.xml\n"
        calls = []
        def fetch(url):
            calls.append(url)
            return self.response(url, robots if url.endswith("robots.txt") else '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>/relative</loc></url></urlset>')
        with patch.object(site, "fetch", side_effect=fetch):
            result = site.crawl_resource_checks(origin)
        self.assertEqual(calls, [origin + "/robots.txt", origin + "/custom.xml", origin + "/sitemap.xml"])
        custom = result["sitemap_xml"][0]
        self.assertTrue(custom["present"])
        self.assertTrue(custom["sitemap_evidence"]["expected_namespace"])
        self.assertEqual(custom["sitemap_evidence"]["non_absolute_loc_count"], 1)

    def test_robots_missing_is_an_observation(self):
        with patch.object(site, "fetch", side_effect=lambda url: self.response(url, code=404)):
            result = site.crawl_resource_checks("https://example.com/")
        self.assertFalse(result["robots_txt"][0]["present"])
        self.assertEqual(result["robots_txt"][0]["observation"], "not_configured")

    def test_truncated_sitemap_does_not_claim_complete_validation(self):
        evidence = site.sitemap_evidence(self.response("https://example.com/sitemap.xml", '<urlset><url><loc>https://example.com/</loc></url>', body_truncated=True))
        self.assertEqual(evidence["scope"], "sample")
        self.assertIsNone(evidence["well_formed"])
        self.assertFalse(evidence["expected_namespace"])

    def test_malformed_html_base_is_reported_without_crashing(self):
        result = self.audit_html('<head><base href="http://[bad/"><link rel="canonical" href="article"></head>')
        self.assertIsNone(result["canonicals"][0]["resolved_url"])
        self.assertIn("resolution_error", result["canonicals"][0])

    def test_canonical_credentials_are_redacted_in_both_outputs(self):
        result = self.audit_html('<head><link rel="canonical" href="https://user:secret@example.com/article"></head>')
        self.assertNotIn("secret", str(result))
        self.assertEqual(result["canonical"], "https://example.com/article")

    def test_unfinished_json_ld_is_not_claimed_as_parsed(self):
        result = self.audit_html('<script type="application/ld+json">{"@type":"Article"}', body_truncated=True)
        self.assertEqual(result["json_ld"][0]["status"], "incomplete_script")
        self.assertTrue(result["capture"]["body_truncated"])

    def test_custom_sitemap_uses_the_public_fetch_boundary(self):
        import public_http
        page = self.response("https://example.com/robots.txt", "Sitemap: http://127.0.0.1/private.xml\nSitemap: file:///etc/passwd\n")
        actual_fetch = site.fetch
        def fetch(url):
            return actual_fetch(url) if url.startswith(("http://127.0.0.1", "file:")) else page if url.endswith("robots.txt") else self.response(url, code=404)
        with patch.object(site, "fetch", side_effect=fetch), patch.object(public_http, "connect_endpoint") as connect:
            result = site.crawl_resource_checks("https://example.com/")
        self.assertEqual([item["status"] for item in result["sitemap_xml"][:2]], ["error", "error"])
        connect.assert_not_called()

    def test_sitemap_discovery_is_bounded_and_reports_omitted_candidates(self):
        robots = "\n".join(f"Sitemap: https://example.com/map-{number}.xml" for number in range(2000))
        calls = []
        def fetch(url):
            calls.append(url)
            return self.response(url, robots if url.endswith("robots.txt") else "<urlset/>")
        with patch.object(site, "fetch", side_effect=fetch):
            result = site.crawl_resource_checks("https://example.com/docs/")
        self.assertEqual(len(calls), 11)
        self.assertEqual(result["sitemap_discovery"], {
            "declaration_count": 2000, "unique_candidate_count": 2002,
            "checked_count": 10, "omitted_count": 1992, "complete": False,
            "robots_body_truncated": False,
        })

    def test_page_exposes_sitemap_discovery_coverage(self):
        result = self.audit_html("<title>Page</title>")
        self.assertEqual(result["checks"]["sitemap_discovery"]["checked_count"], 3)
        self.assertTrue(result["checks"]["sitemap_discovery"]["complete"])

    def test_sitemap_resource_check_parses_xml_once(self):
        with patch.object(site.ElementTree, "XMLPullParser", wraps=site.ElementTree.XMLPullParser) as parse:
            result = site.resource_check(self.response("https://example.com/map.xml", "<urlset/>"), "sitemap.xml")
        self.assertTrue(result["present"])
        self.assertEqual(parse.call_count, 1)

    def test_truncated_robots_cannot_claim_complete_discovery(self):
        with patch.object(site, "fetch", side_effect=lambda url: self.response(url, "Sitemap: https://example.com/one.xml" if url.endswith("robots.txt") else "<urlset/>", body_truncated=url.endswith("robots.txt"))):
            result = site.crawl_resource_checks("https://example.com/")
        self.assertFalse(result["sitemap_discovery"]["complete"])
        self.assertTrue(result["sitemap_discovery"]["robots_body_truncated"])


if __name__ == "__main__":
    unittest.main()
