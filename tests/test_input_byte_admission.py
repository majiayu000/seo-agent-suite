#!/usr/bin/env python3
"""Opt-in per-file admission, not aggregate execution or parser resource limits."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/repo_seo_baseline.py'
spec = importlib.util.spec_from_file_location('input_byte_admission', SCRIPT)
repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo)


class InputByteAdmission(unittest.TestCase):
    def cli(self, root, *args):
        return subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--json', *args],
                              env={**os.environ, 'PATH': ''}, capture_output=True, text=True, timeout=10)

    def test_raw_bytes_zero_exact_eof_lookahead_and_unicode(self):
        for raw in (b'', b'a', '中文🙂'.encode(), b'a\r\nb\rc', b'\xef\xbb\xbfabc'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'input'; path.write_bytes(raw)
                expected = path.read_text(encoding='utf-8')
                self.assertEqual(repo.read_input_text(path, len(raw)), expected)
                self.assertEqual(repo.read_input_text(path, len(raw) + 1), expected)
                if raw:
                    with self.assertRaises(repo.InputTooLargeError):
                        repo.read_input_text(path, len(raw) - 1)
                    with self.assertRaises(repo.InputTooLargeError):
                        repo.read_input_text(path, 0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input'; path.write_bytes(b'\xff')
            with self.assertRaises(repo.InputTooLargeError): repo.read_input_text(path, 0)
            with self.assertRaises(UnicodeDecodeError): repo.read_input_text(path, 1)
            self.assertEqual(repo.read_input_text(path, 1, errors='replace'), '\ufffd')

    def test_reads_are_bounded_unbuffered_and_support_short_reads(self):
        class ShortStream(io.BytesIO):
            requests = []
            def read(self, size=-1):
                self.requests.append(size)
                return super().read(min(size, 2))
        stream = ShortStream(b'abcdefghijk')
        with patch.object(Path, 'open', return_value=stream) as opened:
            with self.assertRaises(repo.InputTooLargeError): repo.read_input_text(Path('input'), 4)
        opened.assert_called_once_with('rb', buffering=0)
        self.assertEqual(stream.requests, [5, 3, 1])
        stream = ShortStream(b'abcd'); stream.requests = []
        with patch.object(Path, 'open', return_value=stream):
            self.assertEqual(repo.read_input_text(Path('input'), 10**100), 'abcd')
        self.assertTrue(all(0 < request <= 65536 for request in stream.requests))

    def test_structured_parsers_never_receive_an_oversized_valid_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            for filename, raw, reader, module, method in (
                ('package.json', b'{} ', repo.read_json, repo.json, 'loads'),
                ('Cargo.toml', b'a=1\n ', repo.read_toml, repo.tomllib, 'loads'),
            ):
                with self.subTest(filename=filename):
                    path = Path(tmp) / filename; path.write_bytes(raw)
                    with patch.object(module, method) as parse:
                        data, error = reader(path, len(raw) - 1)
                    parse.assert_not_called(); self.assertIsNone(data)
                    self.assertEqual(error['status'], 'error')
                    self.assertIn('max-input-bytes', error['reason'])
                    self.assertEqual(reader(path, len(raw))[1], None)

    def test_mixed_manifests_keep_valid_siblings_and_skip_cargo_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'child').mkdir()
            (root / 'package.json').write_text('{"private":true}')
            (root / 'child/package.json').write_text('{"description":"' + 'x'*100 + '"}')
            (root / 'Cargo.toml').write_text('[workspace]\nmembers=["child"]\n' + '#'*100)
            (root / 'pyproject.toml').write_text('[project]\n')
            with patch.object(repo, 'run_cmd') as run:
                result = repo.collect_manifests(root, 30)
            run.assert_not_called()
            self.assertEqual([x['path'] for x in result['npm']], ['package.json'])
            self.assertEqual({x['path'] for x in result['errors']}, {'child/package.json', 'Cargo.toml'})
            self.assertEqual(result['cargo']['status'], 'error')
            self.assertEqual(result['python']['path'], 'pyproject.toml')

    def test_readme_oversize_has_no_content_claims_and_preserves_valid_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'docs').mkdir()
            (root / 'README.md').write_bytes(b'# Heading\n' + b'x'*40)
            (root / 'docs/readme.txt').write_bytes(b'# yes\n\xff')
            result = repo.collect_readmes(root, 12)
            error = next(x for x in result if x['path'] == 'README.md')
            self.assertEqual(set(error), {'path', 'status', 'reason_code', 'reason'})
            valid = next(x for x in result if x['path'] != 'README.md')
            self.assertEqual(valid['line_count'], 2)
            self.assertTrue(repo.collect_community_files(root)['readme'])
            errors = repo.collect_errors({'readmes': result})
            self.assertEqual(errors, [{'surface': 'readme', **error}])
            self.assertNotIn('missing', error['reason'])

    def test_cli_and_shipwise_never_reread_rejected_readme_without_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text('# ' + 'x' * 4096)
            project = root / 'project.yaml'
            project.write_text('discoverability:\n  description: "keep"\n')
            original_read = repo.read_input_text
            for shipwise in (False, True):
                with self.subTest(shipwise=shipwise):
                    def bounded_read(path, limit=None, **kwargs):
                        if path.name == 'README.md':
                            self.assertEqual(limit, 128, 'README reread bypasses byte admission')
                        return original_read(path, limit, **kwargs)
                    argv = [str(SCRIPT), '--root', str(root), '--json', '--max-input-bytes', '128']
                    if shipwise:
                        argv.extend(['--project-yaml', str(project)])
                    output = io.StringIO()
                    with patch.object(repo, 'read_input_text', side_effect=bounded_read), patch.object(sys, 'argv', argv), contextlib.redirect_stdout(output):
                        self.assertEqual(repo.main(), 1)
                    payload = json.loads(output.getvalue())
                    self.assertEqual(payload['readmes'][0]['reason_code'], 'input_too_large')
                    self.assertTrue(payload['community_files']['readme'])
                    self.assertEqual(payload['community_files']['community_file_paths']['readme'], ['README.md'])

    def test_yaml_oversize_is_not_parsed_or_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'project.yaml'; path.write_text('discoverability:\n  description: "keep"\n')
            with patch.object(repo, 'parse_scalar') as parse:
                with self.assertRaises(repo.InputTooLargeError): repo.parse_shipwise_discoverability(path, 16)
            parse.assert_not_called()
            self.assertEqual(repo.parse_shipwise_discoverability(path, path.stat().st_size)['description'], 'keep')

    def test_cli_json_collection_errors_and_valid_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package.json').write_text('{"private":true}')
            (root / 'README.md').write_text('# ' + 'x'*100)
            (root / 'Cargo.toml').write_text('[package]\n' + '#'*100)
            yaml = root / 'project.yaml'; yaml.write_text('discoverability:\n' + '#'*100)
            result = self.cli(root, '--max-input-bytes', '20', '--project-yaml', str(yaml))
            self.assertEqual(result.returncode, 1, result.stderr); self.assertEqual(result.stderr, '')
            payload = json.loads(result.stdout)
            self.assertEqual(payload['status'], 'error')
            self.assertTrue(payload['manifests']['npm'][0]['private'])
            self.assertEqual({x['surface'] for x in payload['errors']}, {'manifest', 'readme', 'shipwise'})
            self.assertEqual(set(payload['shipwise']), {'project_yaml', 'status', 'reason_code', 'reason'})
            self.assertNotIn('missing', payload['shipwise']['reason'])

    def test_cli_invalid_flag_and_existing_yaml_syntax_exit_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in ('-1', '1.5', 'no'):
                result = self.cli(tmp, '--max-input-bytes', value)
                self.assertEqual(result.returncode, 2); self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)
            yaml = Path(tmp) / 'project.yaml'; yaml.write_text('discoverability:\n    - orphan-list-item\n')
            for args in ((), ('--max-input-bytes', '1000')):
                result = self.cli(tmp, '--project-yaml', str(yaml), *args)
                self.assertEqual(result.returncode, 2); self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)

    def test_cli_zero_allows_empty_readme_but_rejects_nonempty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'README.md').write_bytes(b'')
            result = self.cli(tmp, '--max-input-bytes', '0')
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['readmes'][0]['line_count'], 0)
            (root / 'README.md').write_bytes(b'\n')
            result = self.cli(tmp, '--max-input-bytes', '0')
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)['readmes'][0]['status'], 'error')

    def test_admitted_content_matches_unset_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_bytes(b'# Test\r\n\xff\rtext')
            (root / 'package.json').write_text('{"private":true,"description":"中文"}')
            (root / 'Cargo.toml').write_text('[package]\nname="demo"\npublish=false\n')
            (root / 'pyproject.toml').write_text('[project]\nname="demo"\n')
            for helper in (repo.collect_readmes, repo.collect_manifests):
                self.assertEqual(helper(root), helper(root, 1000))


if __name__ == '__main__': unittest.main()
