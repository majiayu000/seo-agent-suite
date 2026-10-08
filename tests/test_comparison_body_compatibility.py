"""Exact Q5 no-option producer compatibility; active limits remain unknown."""
from __future__ import annotations

import json
import shutil
import unittest
from contextlib import contextmanager

import test_comparison_attempt_compatibility as fixtures

ROOT = fixtures.ROOT

BODY_TARGETS = {entry["path"]: entry["after_sha256"] for entry in json.loads(
    (ROOT / "tests/fixtures/comparison_metadata/q5-no-option.json").read_text())}


@contextmanager
def body_checkout():
    with fixtures.composed_checkout() as root:
        fixtures.apply_body_fixture(root)
        # Keep the concrete disposable collector package synchronized; inherited
        # editable mappings must never supply the original checkout's collector.
        shutil.copytree(root / "scripts", root / "src/seo_agent_suite/collectors", dirs_exist_ok=True)
        yield root


class BodyCompatibilityTests(unittest.TestCase):
    def run_probe(self, root, script):
        return fixtures.AttemptCompatibilityTests.run_probe(self, root, script, collector_targets=BODY_TARGETS)

    def test_q5_full_metadata_and_historical_attempt_fixture_with_wheel(self):
        with body_checkout() as root:
            self.run_probe(root, """
import runpy, unittest
metadata = runpy.run_path('tests/test_comparison_metadata.py')['ComparisonContractTests']
attempt = runpy.run_path('tests/test_comparison_attempt_compatibility.py')['AttemptCompatibilityTests']
suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(metadata),
                           unittest.defaultTestLoader.loadTestsFromTestCase(attempt)])
result = unittest.TextTestRunner().run(suite)
assert result.wasSuccessful()
""")

    def test_q5_requires_empty_context_and_both_explicit_none_binding_families(self):
        with body_checkout() as root:
            self.run_probe(root, """
import inspect, runpy
from unittest.mock import patch
ns = runpy.run_path('tests/test_comparison_metadata.py')
from seo_agent_suite.comparison_runtime import resolve_site_runtime_policy as resolve
from seo_agent_suite.comparison_metadata import build_site_comparison_metadata as build
expected = ns['POLICY']
assert resolve(site, audit_options={}) == expected

def unknown(policy):
    block = build(ns['report_fixture'](), ns['URL'], policy)
    assert block['scope']['configuration_status'] == 'unknown', policy
    assert block['collection']['completion'] == 'unknown', block
    assert 'configuration_unverified' in block['collection']['reasons']

unknown(resolve(site))
for context in (None, [], False, {'max_http_body_bytes': None},
                {'max_http_body_bytes': 0}, {'max_http_body_bytes': 1000000},
                {'max_http_attempts': 100}, {'max_http_attempts': None},
                {'max_http_attempts': None, 'max_http_body_bytes': None},
                {'max_http_attempts': 100, 'max_http_body_bytes': 1000000}):
    unknown(resolve(site, audit_options=context))
slots = [(site.audit, 'max_http_attempts'), (site.audit, 'max_http_body_bytes')]
for function in (site.fetch, site.fetch_public_url, http.follow_public_http,
                 http.request_public_url_once, http.request_via_proxy):
    slots.extend((function, parameter) for parameter in ('budget', 'body_budget'))
for function, parameter in slots:
    saved = function.__kwdefaults__
    try:
        for value in (0, False, http.HTTPAttemptBudget(100), http.HTTPBodyBudget(1000000)):
            function.__kwdefaults__ = {**saved, parameter: value}
            unknown(resolve(site, audit_options={}))
        function.__kwdefaults__ = {k: v for k, v in saved.items() if k != parameter}
        unknown(resolve(site, audit_options={}))
        advertised = inspect.signature(function).replace(parameters=[
            p.replace(default=None) if p.name == parameter else p
            for p in inspect.signature(function).parameters.values()])
        with patch.object(function, '__signature__', advertised, create=True):
            unknown(resolve(site, audit_options={}))
    finally:
        function.__kwdefaults__ = saved
    assert resolve(site, audit_options={}) == expected
with patch.object(http, 'DEFAULT_MAX_BODY_BYTES', 9):
    assert resolve(site, audit_options={})['max_body_bytes'] == 1000000
with patch.object(site, 'audit', lambda url, **kwargs: {}):
    unknown(resolve(site, audit_options={}))
""")

    def test_actual_active_allowance_captures_never_gain_comparison_eligibility(self):
        with body_checkout() as root:
            self.run_probe(root, """
import copy, runpy, socket
from unittest.mock import Mock, patch
ns = runpy.run_path('tests/test_comparison_metadata.py')
from seo_agent_suite.comparison_runtime import resolve_site_runtime_policy as resolve
from seo_agent_suite.comparison_metadata import build_site_comparison_metadata as build, validate_site_comparison_metadata as validate
from seo_agent_suite.report import enrich_site_result

def connection(*args, **kwargs):
    conn = Mock()
    def request(method, path, headers):
        body = ns['ALL_HTML'].encode() if path == '/docs/' else b''
        response = Mock(status=200 if body else 404, length=len(body), chunked=False)
        response.read.return_value = body
        hs = {'content-type': 'text/html' if body else 'text/plain'}
        response.getheader.side_effect = hs.get
        response.getheaders.return_value = list(hs.items())
        conn.getresponse.return_value = response
    conn.request.side_effect = request
    return conn

contexts = ({}, {'max_http_body_bytes': 1000000}, {'max_http_attempts': 100},
            {'max_http_attempts': 100, 'max_http_body_bytes': 1000000})
for options in contexts:
    with patch.object(socket, 'getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]), \\
            patch.object(http, 'select_proxy', return_value=None), \\
            patch.object(http, 'PinnedHTTPSConnection', side_effect=connection), \\
            patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
        report = enrich_site_result(site.audit(ns['URL'], **options))
    assert report['capture']['body_truncated'] is False
    policy = resolve(site, audit_options=options)
    report['comparison'] = build(report, ns['URL'], policy)
    assert [r['outcome'] for r in report['comparison']['evaluations']] == ['pass'] * 5
    assert validate(report, requested_url=ns['URL'], runtime_policy=policy) == []
    assert report['comparison']['collection']['completion'] == ('unknown' if options else 'complete')
    assert report['comparison']['scope']['configuration_status'] == ('unknown' if options else 'verified')
""")


if __name__ == "__main__":
    unittest.main()
