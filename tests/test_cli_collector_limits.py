"""Installed CLI forwarding for opt-in collector limits; no live HTTP/provider calls."""
from __future__ import annotations

import io
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from seo_agent_suite import cli
from seo_agent_suite.compare import compare_reports
from seo_agent_suite.report import enrich_site_result

URL = 'https://example.com/docs/'
HTML = b'<head><title>Observed</title></head>'


def invoke(args):
    with redirect_stdout(io.StringIO()) as out:
        code = cli.main(args)
    return code, json.loads(out.getvalue())


@contextmanager
def offline_site():
    site = cli.load_script('site_meta_audit.py')
    http = cli.load_script('public_http.py')
    def connection(*args, **kwargs):
        conn = Mock()
        def request(method, path, headers):
            body = HTML if path == '/docs/' else b''
            response = Mock(status=200 if body else 404, length=len(body), chunked=False)
            response.read.side_effect = lambda size=-1: body if size < 0 else body[:size]
            hs = {'content-type': 'text/html' if body else 'text/plain'}
            response.getheader.side_effect = hs.get
            response.getheaders.return_value = list(hs.items())
            conn.getresponse.return_value = response
        conn.request.side_effect = request
        return conn
    with patch.object(socket, 'getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]), \
            patch.object(http, 'select_proxy', return_value=None), \
            patch.object(http, 'PinnedHTTPSConnection', side_effect=connection), \
            patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
        yield site


def without_time(value):
    if isinstance(value, dict):
        return {k: without_time(v) for k, v in value.items() if k != 'collected_at'}
    if isinstance(value, list):
        return [without_time(v) for v in value]
    return value


class CollectorLimitTests(unittest.TestCase):
    def test_usage_validation_and_help(self):
        for command, flag in [('site-meta', '--max-http-attempts'), ('site', '--max-http-body-bytes'),
                              ('repo-baseline', '--max-input-bytes'), ('repo', '--max-input-bytes')]:
            base = [command] + ([URL] if command.startswith('site') else [])
            for value in ('-1', '1.5', 'true', 'None'):
                with self.subTest(command=command, flag=flag, value=value), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        cli.main(base + [flag, value])
                    self.assertEqual(caught.exception.code, 2)
            with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as caught:
                cli.main([command, '--help'])
            self.assertEqual(caught.exception.code, 0)
            self.assertIn(flag, out.getvalue())

    def test_site_direct_parity_actual_policy_and_exits(self):
        cases = ({}, {'max_http_attempts': 0}, {'max_http_attempts': 1},
                 {'max_http_body_bytes': 0}, {'max_http_body_bytes': 10},
                 {'max_http_body_bytes': 1000000},
                 {'max_http_attempts': 100, 'max_http_body_bytes': 1000000})
        for command in ('site-meta', 'site'):
            for options in cases:
                with self.subTest(command=command, options=options), offline_site() as site:
                    argv = [command, URL, '--json']
                    for key, value in options.items():
                        argv.extend(['--' + key.replace('_', '-'), str(value)])
                    with patch.object(cli, 'resolve_site_runtime_policy', wraps=cli.resolve_site_runtime_policy) as resolve:
                        code, report = invoke(argv)
                    resolve.assert_called_once_with(site, audit_options=options)
                    direct = enrich_site_result(site.audit(URL, **options))
                comparison = report.pop('comparison')
                self.assertEqual(without_time(report), without_time(direct))
                self.assertEqual(code, 0 if direct['page']['status'] == 'ok' else 1)
                self.assertEqual(comparison['scope']['configuration_status'], 'unknown' if options else 'verified')
                self.assertEqual(comparison['collection']['completion'], 'unknown' if options else 'complete')
                report['comparison'] = comparison
                result = compare_reports(json.dumps(report).encode(), json.dumps(report).encode())
                self.assertEqual(result['status'], 'incomparable' if options else 'comparable')
                if options.get('max_http_body_bytes') == 10:
                    self.assertTrue(report['capture']['body_truncated'])
                    absent = [f for f in report['findings'] if f.get('id', '').startswith('site.meta.description')]
                    self.assertTrue(absent)
                    self.assertTrue(all(f['status'] == 'unknown' for f in absent))
                if not options:
                    self.assertNotIn('execution', report)

    def test_repo_omitted_forwarding_and_mcp_default(self):
        from seo_agent_suite import mcp_server
        module = cli.load_script('repo_seo_baseline.py')
        seen = []
        def main():
            seen.append(list(sys.argv))
            print(json.dumps({'root': '.', 'errors': []}))
            return 0
        class FakeMCP:
            def __init__(self, *args, **kwargs):
                self.tools = {}
            def tool(self):
                def register(function):
                    self.tools[function.__name__] = function
                    return function
                return register
        with patch.object(module, 'main', side_effect=main):
            for limit in (None, 0, 32):
                args = ['repo', '--root', '.', '--json']
                if limit is not None:
                    args += ['--max-input-bytes', str(limit)]
                invoke(args)
                self.assertEqual(seen[-1], ['repo_seo_baseline.py', '--root', '.', '--json'] +
                                 ([] if limit is None else ['--max-input-bytes', str(limit)]))
            with patch.object(mcp_server, '_require_mcp', return_value=FakeMCP):
                server = mcp_server.build_server()
            report = json.loads(server.tools['repo_baseline'](root='.'))
            self.assertEqual(report['exit_code'], 0)
            self.assertNotIn('--max-input-bytes', seen[-1])

    def test_repo_direct_parity_siblings_and_aliases(self):
        module = cli.load_script('repo_seo_baseline.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text('# ' + 'x' * 100)
            (root / 'package.json').write_text('{"private": true}')
            (root / 'pyproject.toml').write_text('[project]\nname="tiny"\n')
            (root / 'project.yaml').write_text('discoverability:\n  name: tiny\n')
            for command in ('repo-baseline', 'repo'):
                for limit in (None, 0, 32):
                    with self.subTest(command=command, limit=limit):
                        args = ['--root', tmp, '--project-yaml', str(root / 'project.yaml'), '--json']
                        if limit is not None:
                            args += ['--max-input-bytes', str(limit)]
                        with patch.object(module, 'run_cmd', return_value={'status': 'unavailable', 'reason': 'offline fixture'}), \
                                patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
                            code, report = invoke([command] + args)
                            with patch.object(sys, 'argv', ['repo_seo_baseline.py'] + args), redirect_stdout(io.StringIO()) as out:
                                direct_code = module.main()
                            direct = json.loads(out.getvalue())
                        self.assertEqual(code, direct_code)
                        self.assertEqual(without_time(report), without_time(direct))
                        if limit == 32:
                            self.assertTrue(any('max-input-bytes' in e['reason'] for e in report['errors']))
                            self.assertEqual(report['manifests']['python']['name'], 'tiny')
                        if limit == 0:
                            self.assertEqual(code, 1)


class InstalledWheelLimitTests(unittest.TestCase):
    def test_installed_wheel_outside_checkout(self):
        # Build in disposable source and install only into a disposable venv.
        with tempfile.TemporaryDirectory(prefix='seo-cli-limits-') as tmp:
            tmp = Path(tmp)
            source = tmp / 'source'
            shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc', 'build', 'dist', '*.egg-info'))
            wheels = tmp / 'wheels'
            wheels.mkdir()
            def run(args, **kwargs):
                result = subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result
            run([sys.executable, '-c', 'import setuptools.build_meta as b; b.build_wheel(' + repr(str(wheels)) + ')'], cwd=source)
            run([sys.executable, '-m', 'venv', str(tmp / 'venv')])
            python = tmp / 'venv/bin/python'
            run([str(python), '-m', 'pip', 'install', '--no-deps', '--no-index', str(next(wheels.glob('*.whl')))], cwd=tmp)
            console = tmp / 'venv/bin/seo-agent'
            run([str(console), 'doctor'], cwd=tmp)
            probe = '\n'.join([
                'import runpy, unittest',
                'from seo_agent_suite import cli, mcp_server',
                'from seo_agent_suite.paths import load_script',
                'for module in (cli, mcp_server, load_script("site_meta_audit.py"), load_script("repo_seo_baseline.py")):',
                '    assert ' + repr(str(tmp / 'venv')) + ' in module.__file__, module.__file__',
                'ns = runpy.run_path(' + repr(str(Path(__file__).resolve())) + ')',
                'suite = unittest.defaultTestLoader.loadTestsFromTestCase(ns["CollectorLimitTests"])',
                'ns = runpy.run_path(' + repr(str(ROOT / 'tests/test_comparison_metadata.py')) + ')',
                'suite.addTest(ns["ComparisonContractTests"]("test_24_actual_cli_and_registered_mcp_wrapper_have_identical_blocks"))',
                'assert unittest.TextTestRunner().run(suite).wasSuccessful()',
            ])
            run([str(python), '-I', '-c', probe], cwd=tmp)
            for command, flag in [('site-meta', '--max-http-attempts'), ('site', '--max-http-body-bytes')]:
                result = subprocess.run([str(console), command, URL, flag, '0', '--json'], cwd=tmp, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(json.loads(result.stdout)['comparison']['scope']['configuration_status'], 'unknown')
            target = tmp / 'target'
            target.mkdir()
            (target / 'README.md').write_text('# demo\n')
            # Real console entrypoint, with optional command-line providers disabled.
            import os
            env = {**os.environ, 'PATH': '', 'PYTHONPATH': ''}
            for command in ('repo-baseline', 'repo'):
                result = subprocess.run([str(console), command, '--root', str(target),
                                         '--max-input-bytes', '0', '--json'],
                                        cwd=tmp, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertTrue(any('max-input-bytes' in e['reason']
                                    for e in json.loads(result.stdout)['errors']))
            for command, flag in [('repo', '--max-input-bytes'), ('site-meta', '--max-http-body-bytes')]:
                args = [str(console), command] + ([URL] if command == 'site-meta' else []) + [flag, '-1']
                result = subprocess.run(args, cwd=tmp, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
