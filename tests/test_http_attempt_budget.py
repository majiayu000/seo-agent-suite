"""Opt-in logical target-attempt limits, using offline fake transports only."""

import io
import json
import urllib.parse
from contextlib import contextmanager, ExitStack, redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import public_http as http
import site_meta_audit as site


class HTTPAttemptBudgetStateTests(unittest.TestCase):
    def test_rejects_non_integer_or_negative_limits(self):
        for value in (-1, True, False, 1.0, float("nan"), float("inf"), "1", None):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                http.HTTPAttemptBudget(value)

    def test_zero_blocks_without_charging(self):
        budget = http.HTTPAttemptBudget(0)
        with self.assertRaises(http.HTTPAttemptBudgetExhausted):
            budget.charge()
        self.assertEqual(budget.attempts_used, 0)

    def test_exact_limit_and_independent_instances(self):
        budget = http.HTTPAttemptBudget(2)
        other = http.HTTPAttemptBudget(2)
        budget.charge()
        budget.charge()
        self.assertEqual(budget.attempts_used, 2)
        self.assertEqual(other.attempts_used, 0)
        with self.assertRaises(http.HTTPAttemptBudgetExhausted):
            budget.charge()
        self.assertEqual(budget.attempts_used, 2)

class _TransportHarness:
    @contextmanager
    def transport(self, outcomes, *, proxied=False, endpoints=1):
        connections = []
        def create(*args, **kwargs):
            outcome = outcomes[len(connections)]
            connection = Mock()
            if isinstance(outcome, Exception):
                connection.request.side_effect = outcome
            else:
                status, body, headers = outcome
                response = Mock(status=status, length=len(body))
                response.getheader.side_effect = headers.get
                response.getheaders.return_value = list(headers.items())
                response.read.return_value = body
                connection.getresponse.return_value = response
            connections.append(connection)
            return connection
        def validate(url):
            parsed = urllib.parse.urlparse(url)
            port = 443 if parsed.scheme == "https" else 80
            return parsed, [(http.socket.AF_INET, http.socket.SOCK_STREAM, 6, "", ("8.8.8." + str(index + 1), port)) for index in range(endpoints)]
        with ExitStack() as stack:
            stack.enter_context(patch.object(http, "validate_public_http_url", side_effect=validate))
            stack.enter_context(patch.object(http, "select_proxy", return_value=urllib.parse.urlparse("http://proxy.invalid:8080") if proxied else None))
            for name in ("PinnedHTTPConnection", "PinnedHTTPSConnection", "ProxyPinnedHTTPConnection", "ProxyPinnedHTTPSConnection"):
                stack.enter_context(patch.object(http, name, side_effect=create))
            # Any accidental real network operation is a test failure.
            stack.enter_context(patch.object(http.socket, "socket", side_effect=AssertionError("unexpected socket")))
            stack.enter_context(patch.object(http.socket, "getaddrinfo", side_effect=AssertionError("unexpected DNS")))
            yield connections
        for connection in connections:
            connection.close.assert_called_once()

    def ok(self, body=b"ok", media="text/plain"):
        return 200, body, {"content-type": media}


class HTTPAttemptTransportTests(_TransportHarness, unittest.TestCase):
    def test_zero_no_transport_or_dns(self):
        with patch.object(http, "validate_public_http_url", side_effect=AssertionError("DNS must not start")):
            result = http.fetch_public_url("https://example.invalid/", budget=http.HTTPAttemptBudget(0))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason_code"], "http_attempt_budget_exhausted")
        self.assertNotIn("http_status", result)

    def test_direct_and_proxy_failed_endpoints_are_charged_and_terminal(self):
        for proxied in (False, True):
            for scheme in ("http", "https"):
                with self.subTest(proxied=proxied, scheme=scheme), self.transport([OSError("synthetic connect failure"), self.ok()], proxied=proxied, endpoints=2) as connections:
                    budget = http.HTTPAttemptBudget(1)
                    result = http.fetch_public_url(scheme + "://example.invalid/", budget=budget)
                    self.assertEqual(len(connections), 1)
                    self.assertEqual(budget.attempts_used, 1)
                    self.assertEqual(result["status"], "unavailable")
                    self.assertEqual(result["endpoint_errors"], ["synthetic connect failure"])

    def test_successful_fallback_and_last_real_failure_are_not_relabelled(self):
        for proxied in (False, True):
            with self.subTest(proxied=proxied), self.transport([OSError("first failed"), self.ok()], proxied=proxied, endpoints=2):
                budget = http.HTTPAttemptBudget(2)
                result = http.fetch_public_url("http://example.invalid/", budget=budget)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(budget.attempts_used, 2)
            with self.subTest(proxied=proxied), self.transport([OSError("first failed")], proxied=proxied):
                result = http.fetch_public_url("http://example.invalid/", budget=http.HTTPAttemptBudget(1))
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["reason"], "first failed")
                self.assertNotIn("reason_code", result)

    def test_redirect_shares_allowance_and_preserves_observed_headers(self):
        for proxied in (False, True):
            for cap in (1, 2):
                with self.subTest(proxied=proxied, cap=cap), self.transport([(302, b"", {"location": "/next", "x-robots-tag": "noindex"}), self.ok()], proxied=proxied) as connections:
                    budget = http.HTTPAttemptBudget(cap)
                    result = http.fetch_public_url("http://example.invalid/", budget=budget)
                    self.assertEqual(len(connections), cap)
                    self.assertEqual(len(result["redirects"]), 1)
                    self.assertEqual(result["status"], "unavailable" if cap == 1 else "ok")
                    if cap == 1:
                        self.assertEqual(result["x_robots_tag"], ["noindex"])

    def test_invalid_target_costs_no_attempt_and_retains_real_error(self):
        budget = http.HTTPAttemptBudget(1)
        with patch.object(http, "validate_public_http_url", side_effect=ValueError("blocked target")):
            result = http.fetch_public_url("https://example.invalid/", budget=budget)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "blocked target")
        self.assertEqual(budget.attempts_used, 0)

    def test_new_endpoint_error_evidence_redacts_url_userinfo(self):
        with self.transport([OSError("failed https://user:secret@example.invalid/path")], endpoints=2):
            result = http.fetch_public_url("http://example.invalid/", budget=http.HTTPAttemptBudget(1))
        self.assertEqual(result["endpoint_errors"], ["failed https://example.invalid/path"])


class HTTPAttemptAuditTests(_TransportHarness, unittest.TestCase):
    html = b'<head><title>Example</title><meta name="description" content="Description"><link rel="canonical" href="https://example.invalid/"></head><body><h1>Example</h1></body>'

    def cli(self, *args):
        with patch.object(sys, "argv", ["site_meta_audit.py", "https://example.invalid/", *args]), redirect_stdout(io.StringIO()) as output:
            code = site.main()
        return code, output.getvalue()

    def test_zero_audit_and_cli_are_blocked_with_explanatory_output(self):
        with patch.object(http, "validate_public_http_url", side_effect=AssertionError("no network")):
            result = site.audit("https://example.invalid/", max_http_attempts=0)
            code, output = self.cli("--max-http-attempts", "0")
        self.assertEqual(result["execution"]["completion"], "blocked")
        self.assertEqual(result["execution"]["usage"]["http_attempts"], 0)
        self.assertNotIn("checks", result)
        self.assertEqual(code, 1)
        self.assertIn("allowance exhausted", output)
        self.assertEqual(result["findings"][0]["code"], "page_fetch_error")

    def test_shared_page_and_resource_allowance_unknown_not_missing(self):
        with self.transport([self.ok(self.html, "text/html")]) as connections:
            result = site.audit("https://example.invalid/", max_http_attempts=1)
        self.assertEqual(len(connections), 1)
        self.assertEqual(result["title"], "Example")
        self.assertEqual(result["execution"]["completion"], "partial")
        self.assertTrue(result["checks"]["has_title"])
        self.assertIsNone(result["checks"]["has_robots_txt"])
        self.assertIsNone(result["checks"]["has_sitemap_xml"])
        self.assertEqual(result["checks"]["sitemap_discovery"]["checked_count"], 0)
        self.assertFalse(result["checks"]["sitemap_discovery"]["complete"])
        self.assertIn("http_attempt_budget_exhausted", [finding["code"] for finding in result["findings"]])
        for fail_on, expected in ((None, 0), ("warning", 1), ("error", 0)):
            with self.transport([self.ok(self.html, "text/html")]):
                code, output = self.cli("--max-http-attempts", "1", "--json", *(["--fail-on", fail_on] if fail_on else []))
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(output)["execution"]["completion"], "partial")

    def test_exact_n_complete_and_fresh_audits(self):
        outcomes = [self.ok(self.html, "text/html"), self.ok(b"User-agent: *\nAllow: /"), self.ok(b"<urlset/>", "application/xml")]
        for _ in range(2):
            with self.transport(outcomes) as connections:
                result = site.audit("https://example.invalid/", max_http_attempts=3)
            self.assertEqual(len(connections), 3)
            self.assertEqual(result["execution"]["completion"], "complete")
            self.assertEqual(result["execution"]["limit_events"], [])
            self.assertTrue(result["checks"]["has_sitemap_xml"])

    def test_known_failures_and_redirects_make_partial_not_blocked(self):
        for outcomes, endpoints in (([(302, b"", {"location": "/next"})], 1), ([OSError("real failed endpoint")], 2)):
            with self.subTest(outcomes=outcomes), self.transport(outcomes, endpoints=endpoints):
                result = site.audit("https://example.invalid/", max_http_attempts=1)
            self.assertEqual(result["execution"]["completion"], "partial")
            self.assertEqual(result["page"]["status"], "unavailable")
        with self.transport([(503, b"", {})]):
            result = site.audit("https://example.invalid/", max_http_attempts=1)
        self.assertEqual(result["page"]["http_status"], 503)
        self.assertEqual(result["execution"]["completion"], "complete")
        self.assertEqual(result["execution"]["limit_events"], [])

    def test_observed_resource_true_dominates_later_unknown(self):
        with self.transport([self.ok(self.html, "text/html"), self.ok(b"Sitemap: https://example.invalid/map.xml"), self.ok(b"<urlset/>", "application/xml")]):
            result = site.audit("https://example.invalid/", max_http_attempts=3)
        self.assertTrue(result["checks"]["has_sitemap_xml"])
        self.assertEqual(result["checks"]["sitemap_discovery"]["checked_count"], 1)
        self.assertEqual(result["execution"]["completion"], "partial")

    def test_no_option_outputs_remain_identical_and_non_html_exact_cap_complete(self):
        for cap in (None, 1):
            with self.transport([self.ok(b"plain text")]):
                result = site.audit("https://example.invalid/", **({"max_http_attempts": cap} if cap is not None else {}))
            if cap is None:
                self.assertNotIn("execution", result)
            else:
                self.assertEqual(result["execution"]["completion"], "complete")
            self.assertNotIn("checks", result)

    def test_unset_and_nonlimiting_budget_preserve_evidence_and_fetch_order(self):
        outcomes = [self.ok(self.html, "text/html"), self.ok(b"User-agent: *\nAllow: /"), self.ok(b"<urlset/>", "application/xml")]
        results = []
        requests = []
        def normalized(value):
            if isinstance(value, dict):
                return {key: normalized(child) for key, child in value.items() if key not in {"collected_at", "execution"}}
            if isinstance(value, list):
                return [normalized(child) for child in value]
            return value
        for options in ({}, {"max_http_attempts": 50}):
            with self.transport(outcomes) as connections:
                results.append(normalized(site.audit("https://example.invalid/", **options)))
                requests.append([connection.request.call_args for connection in connections])
        self.assertEqual(results[0], results[1])
        self.assertEqual(requests[0], requests[1])

    def test_argument_validation_precedes_collection(self):
        with patch.object(site, "fetch", side_effect=AssertionError("collection must not start")):
            for cap in (-1, True, 1.5, "2"):
                with self.subTest(cap=cap), self.assertRaises(ValueError):
                    site.audit("https://example.invalid/", max_http_attempts=cap)
            for cap in ("-1", "1.5", "nan", "true"):
                with self.subTest(cap=cap), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                    self.cli("--max-http-attempts", cap)
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
