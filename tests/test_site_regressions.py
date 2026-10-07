"""Offline regressions for metadata evidence and crawl-resource discovery."""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import site_meta_audit as site


class SiteRegressionTests(unittest.TestCase):
    clean_html = '''<head><title>Example</title><meta name="description" content="Example description">
        <link rel="canonical" href="https://example.com/docs/page"></head><body><h1>Example</h1></body>'''

    def response(self, url, body="", code=200, **extra):
        return {"status": "ok" if code == 200 else "error", "url": url,
                "http_status": code, "body": body, "body_truncated": False,
                "content_type": "text/plain", **extra}

    def audit_html(self, body, **extra):
        url = "https://example.com/docs/page"
        page = self.response(url, body, content_type="text/html", **extra)
        with patch.object(site, "fetch", side_effect=lambda target: page if target == url else self.response(target, code=404)):
            return site.audit(url)

    def run_cli(self, result, *args):
        with patch.object(site, "audit", return_value=result), patch.object(sys, "argv", ["site_meta_audit.py", result["url"], *args]), contextlib.redirect_stdout(io.StringIO()) as output:
            code = site.main()
        return code, output.getvalue()

    def test_problem_page_produces_findings_and_opt_in_failure(self):
        url = "https://example.com/docs/page"
        html = self.clean_html.replace('href="https://example.com/docs/page"', 'href="https://other.example/article"').replace('</head>', '<meta property="og:title" content="Example"><meta name="robots" content="noindex"><script type="application/ld+json">{bad}</script></head>').replace('</body>', '<h1>Second</h1></body>')
        def fetch(target):
            if target == url:
                return self.response(url, html, content_type="text/html", x_robots_tag=["noindex"])
            if target.endswith("robots.txt"):
                return self.response(target, "User-agent: *\nDisallow: /\n")
            return self.response(target, "<urlset/>", content_type="application/xml")
        with patch.object(site, "fetch", side_effect=fetch):
            result = site.audit(url)
        self.assertTrue(all(value for key, value in result["checks"].items() if key.startswith("has_")))
        self.assertTrue(result["assessment"]["indexing"]["noindex"])
        self.assertEqual(result["assessment"]["indexing"]["indexed"], "unknown")
        self.assertEqual(result["assessment"]["canonical"]["status"], "other")
        self.assertFalse(result["assessment"]["json_ld_parse_valid"])
        self.assertEqual(result["assessment"]["observations"]["nonempty_h1_count"], 2)
        findings = {item["code"]: item for item in result["findings"]}
        for code in ("noindex_declared", "robots_disallow_googlebot", "json_ld_parse_error"):
            self.assertEqual(findings[code]["severity"], "error")
            self.assertEqual(findings[code]["confidence"], "Confirmed")
        self.assertIn("noindex_hidden_by_robots", findings)
        self.assertEqual(findings["robots_disallow_gptbot"]["severity"], "info")
        self.assertEqual(self.run_cli(result)[0], 0)
        code, output = self.run_cli(result, "--json", "--fail-on", "error")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["findings"], result["findings"])
        self.assertIn("error [Confirmed] noindex_declared", self.run_cli(result)[1])

    def test_clean_page_and_severity_thresholds(self):
        clean = self.audit_html(self.clean_html)
        self.assertEqual(clean["findings"], [])
        self.assertIsNone(clean["assessment"]["json_ld_parse_valid"])
        for level in ("error", "warning", "info"):
            self.assertEqual(self.run_cli(clean, "--fail-on", level)[0], 0)
        warning = self.audit_html(self.clean_html.replace('href="https://example.com/docs/page"', 'href="https://other.example/"'))
        self.assertEqual(self.run_cli(warning, "--fail-on", "error")[0], 0)
        self.assertEqual(self.run_cli(warning, "--fail-on", "warning")[0], 1)
        info = self.audit_html(self.clean_html.replace('</body>', '<h1>Other heading</h1></body>'))
        self.assertEqual(self.run_cli(info, "--fail-on", "warning")[0], 0)
        self.assertEqual(self.run_cli(info, "--fail-on", "info")[0], 1)
        with patch.object(sys, "argv", ["site_meta_audit.py", clean["url"], "--fail-on", "invalid"]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            site.main()
        self.assertEqual(error.exception.code, 2)

    def test_fetch_failure_preserves_json_and_exit_contract(self):
        with patch.object(site, "fetch", return_value=self.response("https://example.com/", code=503)):
            result = site.audit("https://example.com/")
        for args in ((), ("--fail-on", "info"), ("--fail-on", "error")):
            code, output = self.run_cli(result, "--json", *args)
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output)["page"]["http_status"], 503)
            self.assertEqual(json.loads(output)["findings"][0]["code"], "page_fetch_error")
        self.assertNotIn("assessment", result)

    def test_noindex_scope_conflicts_and_header_parameters(self):
        cases = [
            ('<meta name="robots" content="index"><meta name="Googlebot" content="NoIndex">', [], True),
            ('<meta name="robots" content="NONE">', [], True),
            ('<meta name="googlebot-news" content="noindex">', [], False),
            ('<meta name="robots" content="noindex-example">', [], False),
            ('', ["otherbot: noindex"], False),
            ('', ["otherbot: index, noindex"], False),
            ('', ["otherbot: index, GOOGLEBOT: noindex, nofollow"], True),
            ('', ["otherbot: noindex", "index", "noindex"], True),
            ('', ["max-snippet: 0, noindex"], True),
            ('', ["unavailable_after: Wed, 25 Jun 2010 15:00:00 GMT, noindex"], True),
        ]
        for tags, headers, expected in cases:
            with self.subTest(tags=tags, headers=headers):
                result = self.audit_html('<head>' + tags + '</head>', x_robots_tag=headers)
                self.assertIs(result["assessment"]["indexing"]["noindex"], expected)
        body = self.audit_html('<head></head><body><meta name="robots" content="noindex"></body>')
        self.assertFalse(body["assessment"]["indexing"]["noindex"])

    def test_robots_specific_groups_merge_and_preserve_matching_evidence(self):
        text = '''\ufeffUser-agent: *
Disallow: /
User-agent: OAI-SearchBot
Sitemap: https://example.com/map.xml
User-agent: Googlebot
Disallow: /docs

User-agent: oai-searchbot
Allow: /docs/page
User-agent: GPTBot
Disallow:
'''
        result = site.robots_access(self.response("https://example.com/robots.txt", text), "https://example.com/docs/page")
        self.assertFalse(result["Googlebot"]["allowed"])
        self.assertTrue(result["OAI-SearchBot"]["allowed"])
        self.assertTrue(result["GPTBot"]["allowed"])
        self.assertEqual(result["OAI-SearchBot"]["matched_rule"], {"directive": "allow", "pattern": "/docs/page", "line": 9})
        self.assertEqual(result["GPTBot"]["matched_agents"], ["gptbot"])

    def test_robots_matching_precedence_encoding_and_query(self):
        cases = [
            ("Disallow: /\nAllow: /docs", "/docs/page", True),
            ("Allow: /docs\nDisallow: /docs", "/docs/page", True),
            ("Disallow: /*.php$", "/page.php?x=1", True),
            ("Disallow: /*.php$", "/page.php", False),
            ("Disallow: /docs/*?private=", "/docs/page?private=1#fragment", False),
            ("Disallow: /Docs", "/docs", True),
            ("Disallow: /中文", "/%E4%B8%AD%E6%96%87", False),
            ("Disallow: /%e4%b8%ad", "/中", False),
            ("Disallow: /%70age", "/page", False),
            ("Disallow: /a%2Fb", "/a/b", True),
            ("Disallow: /a%2Fb", "/a%2fb", False),
            ("Allow: /page\nDisallow: /*.htm", "/page.htm", False),
            ("Allow: /page\nDisallow: /*.ph", "/page.php5", True),
            ("Disallow: / # comment", "/robots.txt", True),
        ]
        for rules, path, allowed in cases:
            with self.subTest(rules=rules, path=path):
                result = site.robots_access(self.response("https://example.com/robots.txt", "User-agent: *\n" + rules), "https://example.com" + path)
                self.assertIs(result["Googlebot"]["allowed"], allowed)

    def test_robots_missing_and_unavailable_are_distinct(self):
        for code, extra, expected in ((404, {}, True), (410, {}, True), (403, {}, None), (429, {}, None), (503, {}, None), (200, {"body_truncated": True}, None), (200, {"content_type": "text/html"}, None)):
            with self.subTest(code=code, extra=extra):
                result = site.robots_access(self.response("https://example.com/robots.txt", "User-agent: *\nDisallow: /", code, **extra), "https://example.com/docs/page")
                self.assertIs(result["Googlebot"]["allowed"], expected)

    def test_canonical_syntax_duplicates_and_equivalent_urls(self):
        for href, expected in (("https://EXAMPLE.com:443/docs/page", "self"), ("/docs/%70age", "self"), ("https://other.example/docs/page", "other"), ("javascript:bad", "invalid"), ("https://example.com:bad/", "invalid"), ("https://bad host/", "invalid"), ("/docs/page#part", "invalid"), ("", "invalid")):
            with self.subTest(href=href):
                result = self.audit_html(self.clean_html.replace("https://example.com/docs/page", href))
                self.assertEqual(result["assessment"]["canonical"]["status"], expected)
        conflict = self.audit_html(self.clean_html.replace('</head>', '<link rel="canonical" href="/other"></head>'))
        self.assertEqual(conflict["assessment"]["canonical"]["status"], "conflicting")
        duplicate = self.audit_html(self.clean_html.replace('</head>', '<link rel="canonical" href="https://EXAMPLE.com:443/docs/page"></head>'))
        self.assertEqual(duplicate["assessment"]["canonical"]["status"], "self")
        self.assertIn("canonical_multiple", {item["code"] for item in duplicate["findings"]})
        body = self.audit_html('<head></head><body><link rel="canonical" href="/docs/page"></body>')
        self.assertEqual(body["assessment"]["canonical"]["status"], "invalid")
        preload = self.audit_html(self.clean_html, link_headers=['</style.css>; rel="preload"'])
        self.assertEqual(preload["assessment"]["canonical"]["status"], "self")
        header = self.audit_html(self.clean_html, link_headers=['<https://other.example/>; rel="canonical"'])
        self.assertEqual(header["assessment"]["canonical"]["status"], "unknown")
        self.assertTrue(header["assessment"]["canonical"]["http_link_headers_need_review"])

    def test_truncated_page_reports_unknown_without_inventing_absence(self):
        result = self.audit_html('<head>', body_truncated=True)
        self.assertIsNone(result["assessment"]["indexing"]["noindex"])
        self.assertIsNone(result["assessment"]["json_ld_parse_valid"])
        self.assertEqual(result["assessment"]["canonical"]["status"], "unknown")
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("capture_incomplete", codes)
        self.assertNotIn("title_missing", codes)
        self.assertNotIn("meta_description_missing", codes)
        noindex = self.audit_html('<head><meta name="robots" content="noindex">', body_truncated=True)
        self.assertTrue(noindex["assessment"]["indexing"]["noindex"])

    def test_lengths_are_observations_and_json_parse_is_not_schema_validation(self):
        result = self.audit_html(self.clean_html.replace('Example</title>', 'X' * 500 + '</title>').replace('Example description', 'Y' * 500).replace('</head>', '<script type="application/ld+json">42</script></head>'))
        self.assertTrue(result["assessment"]["json_ld_parse_valid"])
        self.assertEqual(result["assessment"]["observations"]["title_length"], 500)
        self.assertEqual(result["assessment"]["observations"]["description_length"], 500)
        self.assertEqual(result["findings"], [])

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
