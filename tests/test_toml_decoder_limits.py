#!/usr/bin/env python3
"""Expected stdlib TOML limits retain the structured evidence handoff."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/repo_seo_baseline.py'
spec = importlib.util.spec_from_file_location('toml_decoder_limits', SCRIPT)
repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo)
REASON = 'TOML value exceeds supported numeric or nesting limits'


class TomlDecoderLimits(unittest.TestCase):
    def test_real_decoder_limits_preserve_cli_json_and_valid_siblings(self):
        # These exercise the real decoder in isolated interpreters with default
        # recursion settings and a deterministic integer-conversion limit.
        values = ('9' * 5000, '[' * 2000 + '0' + ']' * 2000)
        for filename, section, key in (('Cargo.toml', 'package', 'cargo'),
                                       ('pyproject.toml', 'project', 'python')):
            for value in values:
                with self.subTest(filename=filename, size=len(value)), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / filename).write_text(f'[{section}]\nname="demo"\nvalue={value}\n')
                    (root / 'package.json').write_text('{"private":true,"description":"valid sibling"}')
                    sibling = 'pyproject.toml' if filename == 'Cargo.toml' else 'Cargo.toml'
                    sibling_section = 'project' if sibling == 'pyproject.toml' else 'package'
                    sibling_key = 'python' if sibling == 'pyproject.toml' else 'cargo'
                    sibling_publish = "publish=false\n" if sibling == "Cargo.toml" else ""
                    (root / sibling).write_text(f'[{sibling_section}]\nname="kept"\ndescription="valid TOML sibling"\n{sibling_publish}')
                    result = subprocess.run(
                        [sys.executable, '-X', 'int_max_str_digits=4300', str(SCRIPT),
                         '--root', str(root), '--json'],
                        env={**os.environ, 'PATH': ''}, capture_output=True,
                        text=True, timeout=10)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stderr, '')
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload['status'], 'error')
                    self.assertEqual(payload['manifests'][key]['status'], 'error')
                    self.assertEqual(payload['manifests'][sibling_key]['description'], 'valid TOML sibling')
                    self.assertEqual(payload['manifests']['npm'][0]['description'], 'valid sibling')
                    self.assertTrue(any(e['path'] == filename and e['reason'] == REASON
                                        for e in payload['errors']))
                    json.dumps(payload, allow_nan=False)

    def test_expected_decoder_exceptions_use_fixed_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'Cargo.toml'
            path.write_text('[package]\nname="valid"\n')
            for error in (ValueError('input-specific detail'), RecursionError('input-specific detail')):
                with self.subTest(error=type(error).__name__), mock.patch.object(repo.tomllib, 'loads', side_effect=error):
                    data, diagnostic = repo.read_toml(path)
                    self.assertIsNone(data)
                    self.assertEqual(diagnostic, {'status': 'error', 'path': str(path), 'reason': REASON})

    def test_existing_valid_syntax_utf8_file_and_size_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'Cargo.toml'
            path.write_text('[package]\nname="valid"\n')
            self.assertEqual(repo.read_toml(path), ({'package': {'name': 'valid'}}, None))
            self.assertEqual(repo.read_toml(path, 0)[1]['reason_code'], 'input_too_large')
            path.write_text('[package\n')
            self.assertTrue(repo.read_toml(path)[1]['reason'].startswith('invalid TOML:'))
            path.write_bytes(b'\xff')
            self.assertTrue(repo.read_toml(path)[1]['reason'].startswith('invalid UTF-8:'))
            path.unlink()
            self.assertEqual(repo.read_toml(path)[1]['status'], 'error')


if __name__ == '__main__':
    unittest.main()
