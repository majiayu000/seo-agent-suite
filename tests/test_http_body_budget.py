"""Invocation-wide exposed payload bytes, using amount-respecting offline readers."""
import contextlib
import http.client as client
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.parse
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import public_http as http
import site_meta_audit as site


class MemorySocket:
    def __init__(self, data): self.data = data
    def makefile(self, mode): return io.BytesIO(self.data)


def response(body=b'abc', length='auto', status=200, media='text/plain', extra=b''):
    if length == 'auto': length = len(body)
    header = b'' if length is None else f'Content-Length: {length}\r\n'.encode()
    r = client.HTTPResponse(MemorySocket(
        f'HTTP/1.1 {status} Test\r\nContent-Type: {media}\r\n'.encode() + header + extra + b'\r\n' + body))
    r.begin()
    original = r.read
    r.calls = []
    r.exposed = 0
    def read(amount):
        r.calls.append(amount)
        try:
            data = original(amount)
        except client.IncompleteRead as exc:
            r.exposed += len(exc.partial)
            raise
        r.exposed += len(data)
        return data
    r.read = read
    return r


class Harness:
    @contextlib.contextmanager
    def transport(self, responses, *, proxied=False, endpoints=1):
        connections = []
        def create(*args, **kwargs):
            r = responses[len(connections)]
            c = Mock()
            if isinstance(r, Exception): c.request.side_effect = r
            else: c.getresponse.return_value = r
            connections.append(c)
            return c
        def validate(url):
            parsed = urllib.parse.urlparse(url)
            return parsed, [(http.socket.AF_INET, http.socket.SOCK_STREAM, 6, '', ('8.8.8.'+str(i+1), 80)) for i in range(endpoints)]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(http, 'validate_public_http_url', side_effect=validate))
            stack.enter_context(patch.object(http, 'select_proxy', return_value=urllib.parse.urlparse('http://proxy.invalid:8080') if proxied else None))
            for name in ('PinnedHTTPConnection', 'PinnedHTTPSConnection', 'ProxyPinnedHTTPConnection', 'ProxyPinnedHTTPSConnection'):
                stack.enter_context(patch.object(http, name, side_effect=create))
            stack.enter_context(patch.object(http.socket, 'socket', side_effect=AssertionError('unexpected socket')))
            stack.enter_context(patch.object(http.socket, 'getaddrinfo', side_effect=AssertionError('unexpected DNS')))
            yield connections
        for c in connections: c.close.assert_called_once()

    def fetch(self, r, limit, proxied=False, **kwargs):
        b = http.HTTPBodyBudget(limit)
        with self.transport([r], proxied=proxied):
            result = http.fetch_public_url('http://example.invalid/', body_budget=b, **kwargs)
        self.assertEqual(b.bytes_used, r.exposed)
        self.assertLessEqual(b.bytes_used, limit)
        self.assertTrue(all(0 < n <= limit for n in r.calls))
        return result, b


class BodyTransportTests(Harness, unittest.TestCase):
    def test_strict_state_validation(self):
        for value in (-1, True, False, 1.0, '1', None):
            with self.subTest(value=value), self.assertRaises(ValueError): http.HTTPBodyBudget(value)
        self.assertEqual(http.HTTPBodyBudget(0).bytes_used, 0)

    def test_known_length_less_equal_greater(self):
        for proxy in (False, True):
            for limit, incomplete in ((2, True), (3, False), (4, False)):
                with self.subTest(proxy=proxy, limit=limit):
                    result, budget = self.fetch(response(), limit, proxy)
                    self.assertEqual(result['body'], 'abc'[:limit])
                    self.assertEqual(result['body_truncated'], incomplete)
                    self.assertEqual(result.get('reason_code'), 'http_body_budget_exhausted' if incomplete else None)

    def test_unknown_eof_exact_boundary_never_probes_n_plus_one(self):
        for proxy in (False, True):
            for limit, incomplete in ((2, True), (3, True), (4, False)):
                with self.subTest(proxy=proxy, limit=limit):
                    r = response(length=None)
                    result, budget = self.fetch(r, limit, proxy)
                    self.assertEqual(result['body_truncated'], incomplete)
                    self.assertEqual(r.calls, [limit])

    def test_chunked_boundary_and_partial_failure(self):
        for proxy in (False, True):
            for limit, incomplete in ((3, True), (4, False)):
                r = response(b'3\r\nabc\r\n0\r\n\r\n', length=None, extra=b'Transfer-Encoding: chunked\r\n')
                result, budget = self.fetch(r, limit, proxy)
                self.assertEqual(result['body'], 'abc')
                self.assertEqual(result['body_truncated'], incomplete)
            r = response(b'2\r\nab\r\n3\r\nc', length=None, extra=b'Transfer-Encoding: chunked\r\n')
            result, budget = self.fetch(r, 10, proxy)
            self.assertEqual(result['status'], 'error')
            self.assertEqual(budget.bytes_used, r.exposed)
            self.assertGreater(budget.bytes_used, 0)

    def test_lookahead_is_charged_even_when_discarded(self):
        for proxy in (False, True):
            r = response(b'abcdef')
            result, budget = self.fetch(r, 4, proxy, max_body_bytes=2)
            self.assertEqual(result['body'], 'ab')
            self.assertTrue(result['body_truncated'])
            self.assertEqual(budget.bytes_used, 3)
            self.assertEqual(r.calls, [3])

    def test_short_declared_body_and_empty_body(self):
        for proxy in (False, True):
            result, budget = self.fetch(response(b'ab', length=5), 10, proxy)
            self.assertEqual(result['status'], 'error')
            self.assertIn('IncompleteRead', result['reason'])
            self.assertEqual(budget.bytes_used, 2)
            result, budget = self.fetch(response(b''), 1, proxy)
            self.assertEqual(budget.bytes_used, 0)
            self.assertFalse(result['body_truncated'])

    def test_error_redirect_bodies_unread_and_headers_preserved(self):
        for proxy in (False, True):
            for status in (404, 500):
                r = response(b'ignored', status=status)
                result, b = self.fetch(r, 1, proxy)
                self.assertEqual(r.calls, [])
                self.assertEqual(b.bytes_used, 0)
            r = response(b'ignored', status=302, extra=b'Location: /next\r\nX-Robots-Tag: noindex\r\n')
            b = http.HTTPBodyBudget(1)
            with self.transport([r, response(b'abc')], proxied=proxy):
                result = http.fetch_public_url('http://example.invalid/', body_budget=b)
            self.assertEqual(r.calls, [])
            self.assertEqual(len(result['redirects']), 1)
            self.assertEqual(b.bytes_used, 1)

    def test_failed_read_partial_is_charged_before_fallback(self):
        for proxy in (False, True):
            for limit, count in ((2, 1), (4, 2)):
                first = response(b'ab', length=5)
                second = response(b'xyz')
                b = http.HTTPBodyBudget(limit)
                # Force a surfaced partial exception within the bounded read.
                first.read = Mock(side_effect=client.IncompleteRead(b'ab', 1))
                with self.transport([first, second], proxied=proxy, endpoints=2) as connections:
                    result = http.fetch_public_url('http://example.invalid/', body_budget=b)
                self.assertEqual(len(connections), count)
                self.assertEqual(b.bytes_used, limit)
                if limit == 2:
                    self.assertEqual(result['status'], 'unavailable')
                    self.assertIn('IncompleteRead', result['endpoint_errors'][0])
                else:
                    self.assertEqual(second.calls, [2])
                    self.assertEqual(result['body'], 'xy')
                    self.assertTrue(result['body_truncated'])

    def test_zero_refuses_before_dns_and_no_reused_state(self):
        with patch.object(http, 'validate_public_http_url', side_effect=AssertionError('DNS')):
            b = http.HTTPBodyBudget(0)
            result = http.fetch_public_url('http://example.invalid/', body_budget=b)
        self.assertEqual(result['reason_code'], 'http_body_budget_exhausted')
        self.assertEqual(b.bytes_used, 0)
        self.assertEqual(http.HTTPBodyBudget(3).bytes_used, 0)


class BodyAuditTests(Harness, unittest.TestCase):
    html = b'<head><title>Observed</title></head><body><h1>Observed</h1></body>'

    def cli(self, *args):
        with patch.object(sys, 'argv', ['site_meta_audit.py', 'http://example.invalid/', *args]), contextlib.redirect_stdout(io.StringIO()) as out:
            code = site.main()
        return code, out.getvalue()

    def test_shared_page_resource_unknown_preserves_page_and_exits(self):
        for threshold, expected in ((None, 0), ('warning', 1), ('error', 0)):
            with self.transport([response(self.html, media='text/html')]) as conns:
                code, raw = self.cli('--json', '--max-http-body-bytes', str(len(self.html)), *(['--fail-on', threshold] if threshold else []))
            result = json.loads(raw)
            self.assertEqual(code, expected)
            self.assertEqual(len(conns), 1)
            self.assertEqual(result['title'], 'Observed')
            self.assertIsNone(result['checks']['has_robots_txt'])
            self.assertIsNone(result['checks']['has_sitemap_xml'])
            self.assertFalse(result['checks']['sitemap_discovery']['complete'])
            self.assertEqual(result['checks']['sitemap_discovery']['checked_count'], 0)
            self.assertEqual(result['execution']['usage']['http_body_bytes'], len(self.html))
            self.assertEqual(result['execution']['completion'], 'partial')

    def test_truncated_page_absence_is_unknown_and_positive_kept(self):
        prefix = b'<head><title>Observed</title>'
        with self.transport([response(prefix+b' more</head>', media='text/html')]):
            result = site.audit('http://example.invalid/', max_http_body_bytes=len(prefix))
        self.assertEqual(result['page']['status'], 'ok')
        self.assertEqual(result['title'], 'Observed')
        self.assertTrue(result['capture']['body_truncated'])
        self.assertIsNone(result['assessment']['indexing']['noindex'])
        self.assertEqual(result['assessment']['canonical']['status'], 'unknown')
        self.assertNotIn('meta_description_missing', [x['code'] for x in result['findings']])

    def test_partial_robots_and_sitemap_never_false_missing(self):
        for resource in ('robots', 'sitemap'):
            items = [response(self.html, media='text/html')]
            cap = len(self.html)
            if resource == 'sitemap':
                items.append(response(b'User-agent: *\nAllow: /'))
                cap += len(b'User-agent: *\nAllow: /')
            items.append(response(b'<urlset><url></url></urlset>', media='application/xml'))
            with self.transport(items): result = site.audit('http://example.invalid/', max_http_body_bytes=cap+2)
            self.assertFalse(result['checks']['sitemap_discovery']['complete'])
            self.assertIsNone(result['checks']['has_sitemap_xml'])
            if resource == 'robots': self.assertIsNone(result['assessment']['crawl_access']['Googlebot']['allowed'])

    def test_exact_final_known_body_complete_and_positive_dominates_later_unknown(self):
        robots = b'User-agent: *\nAllow: /'
        sitemap = b'<urlset/>'
        for _ in range(2):
            with self.transport([response(self.html, media='text/html'), response(robots), response(sitemap, media='application/xml')]):
                result = site.audit('http://example.invalid/', max_http_body_bytes=len(self.html)+len(robots)+len(sitemap))
            self.assertEqual(result['execution']['completion'], 'complete')
            self.assertEqual(result['execution']['limit_events'], [])
            self.assertTrue(result['checks']['has_sitemap_xml'])
        robots = b'Sitemap: http://example.invalid/map.xml'
        with self.transport([response(self.html, media='text/html'), response(robots), response(sitemap, media='application/xml')]):
            result = site.audit('http://example.invalid/', max_http_body_bytes=len(self.html)+len(robots)+len(sitemap))
        self.assertTrue(result['checks']['has_sitemap_xml'])
        self.assertEqual(result['execution']['completion'], 'partial')

    def test_composed_attempt_and_byte_limits(self):
        for attempts, byte_limit, reason in ((0, 100, 'http_attempt_budget_exhausted'), (2, 0, 'http_body_budget_exhausted')):
            with patch.object(http, 'validate_public_http_url', side_effect=AssertionError('DNS')):
                result = site.audit('http://example.invalid/', max_http_attempts=attempts, max_http_body_bytes=byte_limit)
            self.assertEqual(result['page']['reason_code'], reason)
            self.assertEqual(result['execution']['completion'], 'blocked')
            self.assertEqual(result['execution']['usage']['http_attempts'], 0)
            self.assertEqual(result['execution']['usage']['http_body_bytes'], 0)

    def test_validation_cli_help_and_zero_exit(self):
        with patch.object(site, 'fetch', side_effect=AssertionError('collection')):
            for value in (-1, True, False, 1.0, '2'):
                with self.subTest(value=value), self.assertRaises(ValueError): site.audit('http://example.invalid/', max_http_body_bytes=value)
            for value in ('-1', '1.5', 'true', 'nan'):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught: self.cli('--max-http-body-bytes', value)
                self.assertEqual(caught.exception.code, 2)
        with patch.object(http, 'validate_public_http_url', side_effect=AssertionError('DNS')):
            code, raw = self.cli('--max-http-body-bytes', '0', '--json')
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(raw)['execution']['completion'], 'blocked')


if __name__ == '__main__': unittest.main()
