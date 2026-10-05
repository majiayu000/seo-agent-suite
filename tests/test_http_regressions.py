#!/usr/bin/env python3
"""Offline regressions for public HTTP transport and audit evidence."""
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime
from email.message import Message
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("http_regression_module", Path(__file__).resolve().parents[1] / "scripts/public_http.py")
http = importlib.util.module_from_spec(spec)
spec.loader.exec_module(http)


def response(body=b"ok", status=200, location=None, content_type="text/html", **headers):
    return dict(http_status=status, location=location, content_type=content_type,
                sample_bytes=len(body), body=body, **headers)


class HttpRegressionTests(unittest.TestCase):
    def fetch(self, body, content_type="text/html"):
        with mock.patch.object(http, "request_public_url_once", return_value=response(body, content_type=content_type)):
            return http.fetch_public_url("https://public.example/")

    def test_unicode_request_target_direct_and_proxy_preserves_existing_escapes(self):
        url = "http://public.example/中文/%E4%B8%AD;版本=1?q=中文&next=/中文%20页#片段"
        expected = "/%E4%B8%AD%E6%96%87/%E4%B8%AD;%E7%89%88%E6%9C%AC=1?q=%E4%B8%AD%E6%96%87&next=/%E4%B8%AD%E6%96%87%20%E9%A1%B5"
        endpoints = [(http.socket.AF_INET, http.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))]
        headers = Message()
        headers["Content-Type"] = "text/html"
        headers["X-Robots-Tag"] = "noindex"
        headers["X-Robots-Tag"] = "googlebot: nofollow"
        headers["Link"] = '<https://public.example/a>; rel="canonical"'
        headers["Link"] = '<https://public.example/b>; rel="alternate"'
        network_response = mock.Mock(status=200)
        network_response.read.return_value = b"ok"
        network_response.getheader.side_effect = headers.get
        network_response.getheaders.return_value = list(headers.items())
        connection = mock.Mock()
        connection.getresponse.return_value = network_response
        for proxy in (None, http.urllib.parse.urlparse("http://proxy.example:8080")):
            with self.subTest(proxy=proxy), mock.patch.object(http.socket, "getaddrinfo", return_value=endpoints), mock.patch.object(http, "select_proxy", return_value=proxy), mock.patch.object(http, "PinnedHTTPConnection", return_value=connection), mock.patch.object(http, "ProxyPinnedHTTPConnection", return_value=connection):
                connection.reset_mock()
                result = http.request_public_url_once(url, 5)
                self.assertEqual(connection.request.call_args.args[:2], ("GET", expected))
                self.assertEqual(result["x_robots_tag"], ["noindex", "googlebot: nofollow"])
                self.assertEqual(result["link_headers"], headers.get_all("Link"))
                connection.close.assert_called_once()

    def test_html_meta_charset_decodes_gbk(self):
        for declaration in ('<meta charset="gbk">', '<meta http-equiv="Content-Type" content="text/html; charset=gbk">', '<meta content="text/html; charset=GBK" http-equiv="content-type">'):
            with self.subTest(declaration=declaration):
                text = declaration + "<title>中文页面</title>"
                self.assertEqual(self.fetch(text.encode("gbk"))["body"], text)

    def test_link_uri_redacts_userinfo_and_preserves_header_semantics(self):
        header = '<https://sample:example-pass@public.example/a?q=1>; rel="canonical", <//sample:example-pass@public.example/b>; rel="alternate"; hreflang="en"'
        headers = Message()
        headers["Link"] = header
        network_response = mock.Mock()
        network_response.getheader.side_effect = headers.get
        network_response.getheaders.return_value = list(headers.items())
        self.assertEqual(http._response_header_values(network_response, "link"), ['<https://public.example/a?q=1>; rel="canonical", <//public.example/b>; rel="alternate"; hreflang="en"'])

    def test_meta_charset_ignores_comments_and_script_text(self):
        text = '<!-- <meta charset="gbk"> --><script>"<meta charset=gbk>"</script><title>中文</title>'
        self.assertEqual(self.fetch(text.encode())["body"], text)

    def test_http_charset_takes_precedence(self):
        text = '<meta charset="gbk"><title>中文</title>'
        self.assertEqual(self.fetch(text.encode(), "text/html; charset=utf-8")["body"], text)

    def test_invalid_and_nontext_charsets_do_not_crash(self):
        for charset in ("base64_codec", "hex_codec", "rot_13", "not-a-codec", "\x00"):
            with self.subTest(charset=charset):
                self.assertIsNone(http.charset_from_content_type("text/html; charset=" + charset))
                self.assertEqual(self.fetch(b"hello", "text/html; charset=" + charset)["body"], "hello")

    def test_invalid_meta_charset_falls_back_without_crash(self):
        text = '<meta charset="base64_codec"><title>中文</title>'
        self.assertEqual(self.fetch(text.encode())["body"], text)

    def test_redirect_chain_and_final_headers_survive_fetch(self):
        replies = [response(status=301, location="/moved"), response(status=302, location="/final"), response(x_robots_tag=["noindex", "googlebot: nofollow"], link_headers=['<https://public.example/a>; rel="canonical"'])]
        with mock.patch.object(http, "request_public_url_once", side_effect=replies):
            result = http.fetch_public_url("https://public.example/")
        self.assertEqual(result["redirects"], [dict(url="https://public.example/", status=301, location="/moved"), dict(url="https://public.example/moved", status=302, location="/final")])
        self.assertEqual(result["url"], "https://public.example/final")
        self.assertEqual(result["x_robots_tag"], replies[-1]["x_robots_tag"])
        self.assertEqual(result["link_headers"], replies[-1]["link_headers"])
        self.assertIsNotNone(datetime.fromisoformat(result["collected_at"].replace("Z", "+00:00")).tzinfo)

    def test_blocked_redirect_preserves_redacted_evidence(self):
        for location in ("https://sample:example-pass@public.example/final", "//sample:example-pass@public.example/final"):
            with self.subTest(location=location), mock.patch.object(http, "request_public_url_once", side_effect=[response(status=302, location=location), ValueError("URL credentials are not allowed")]):
                result = http.fetch_public_url("https://public.example/")
                self.assertEqual(result["status"], "error")
                self.assertIn("redirect blocked", result["reason"])
                self.assertEqual(result["redirects"][0]["status"], 302)
                self.assertNotIn("example-pass", repr(result))
                self.assertNotIn("sample:", repr(result))

    def test_transport_error_and_status_error_keep_prior_redirects(self):
        for final in (OSError("offline"), response(status=404, x_robots_tag=["noindex"])):
            with self.subTest(final=final), mock.patch.object(http, "request_public_url_once", side_effect=[response(status=301, location="/final"), final]):
                result = http.http_check("https://public.example/")
                self.assertEqual(result["status"], "error")
                self.assertEqual(len(result["redirects"]), 1)
                self.assertIn("collected_at", result)
                self.assertNotIn("body", result)

    def test_redirect_limit_and_missing_location_have_evidence(self):
        for location, reason in (("/again", "too many redirects"), (None, "redirect missing Location header")):
            with self.subTest(location=location), mock.patch.object(http, "request_public_url_once", return_value=response(status=302, location=location)):
                result = http.follow_public_http("https://public.example/", max_redirects=0)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["redirects"], [dict(url="https://public.example/", status=302, location=location)])

    def test_malformed_redirect_authority_is_a_structured_error(self):
        with mock.patch.object(http, "request_public_url_once", return_value=response(status=302, location="https://sample:example-pass@[bad/")):
            result = http.fetch_public_url("https://public.example/")
        self.assertEqual(result["status"], "error")
        self.assertIn("redirect blocked", result["reason"])
        self.assertEqual(len(result["redirects"]), 1)
        self.assertNotIn("example-pass", repr(result))

    def test_body_bound_is_preserved_for_meta_charset(self):
        text = '<meta charset="gbk">中文'
        body = text.encode("gbk")
        with mock.patch.object(http, "request_public_url_once", return_value=response(body)):
            result = http.fetch_public_url("https://public.example/", max_body_bytes=len(body) - 1)
        self.assertTrue(result["body_truncated"])
        self.assertIn("<meta charset=", result["body"])


if __name__ == "__main__":
    unittest.main()
