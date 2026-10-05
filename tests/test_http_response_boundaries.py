"""HTTP framing/status regressions using memory streams, without sockets."""

from http.client import HTTPResponse
import io
import sys
import unittest
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import public_http as http


class MemorySocket:
    def __init__(self, data):
        self.data = data

    def makefile(self, mode):
        return io.BytesIO(self.data)


def framed_response(body, length=None):
    length_header = b"" if length is None else f"Content-Length: {length}\r\n".encode()
    response = HTTPResponse(MemorySocket(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n" + length_header + b"\r\n" + body
    ))
    response.begin()
    return response


class HttpResponseBoundaryTests(unittest.TestCase):
    @contextmanager
    def connection(self, response, proxied):
        parsed = urllib.parse.urlparse("http://example.invalid/")
        endpoint = (http.socket.AF_INET, http.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))
        connection = Mock()
        connection.getresponse.return_value = response
        proxy = urllib.parse.urlparse("http://proxy.example.invalid:8080") if proxied else None
        with patch.object(http, "validate_public_http_url", return_value=(parsed, [endpoint])), \
                patch.object(http, "select_proxy", return_value=proxy), \
                patch.object(http, "PinnedHTTPConnection", return_value=connection), \
                patch.object(http, "ProxyPinnedHTTPConnection", return_value=connection):
            yield connection
        connection.close.assert_called_once()

    def test_short_content_length_is_a_structured_fetch_error(self):
        for proxied in (False, True):
            with self.subTest(proxied=proxied), self.connection(framed_response(b"abc", 10), proxied):
                result = http.fetch_public_url("http://example.invalid/", max_body_bytes=64)
                self.assertEqual(result["status"], "error")
                self.assertIn("IncompleteRead", result["reason"])
                self.assertNotIn("body", result)

    def test_complete_and_intentionally_sampled_bodies_remain_distinct(self):
        for proxied in (False, True):
            for body, length, limit, truncated in [
                (b"abcdefghij", 10, 10, False),
                (b"abcdefghij", 10, 9, True),
                (b"abc", 10, 2, True),  # Enough bytes for the requested sample.
                (b"abc", None, 64, False),  # No declared length to verify.
                (b"", 0, 64, False),
            ]:
                with self.subTest(proxied=proxied, length=length, limit=limit), \
                        self.connection(framed_response(body, length), proxied):
                    result = http.fetch_public_url("http://example.invalid/", max_body_bytes=limit)
                    self.assertEqual(result["status"], "ok")
                    self.assertEqual(result["body_truncated"], truncated)

    def test_redirect_and_error_status_do_not_wait_for_irrelevant_body(self):
        for proxied in (False, True):
            for status in (302, 404, 500):
                response = Mock(status=status)
                headers = {"location": "/next", "content-type": "text/plain"}
                response.getheader.side_effect = headers.get
                response.getheaders.return_value = list(headers.items())
                response.read.side_effect = OSError("synthetic stalled body")
                with self.subTest(proxied=proxied, status=status), self.connection(response, proxied):
                    result = http.request_public_url_once("http://example.invalid/", 1)
                    self.assertEqual(result["http_status"], status)
                    self.assertEqual(result["location"], "/next")
                    self.assertEqual(result["body"], b"")
                    self.assertEqual(result["sample_bytes"], 0)
                    response.read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
