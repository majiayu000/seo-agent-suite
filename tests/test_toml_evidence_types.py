#!/usr/bin/env python3
"""TOML native values must not break the JSON evidence handoff."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/repo_seo_baseline.py'
spec = importlib.util.spec_from_file_location('toml_evidence_types', SCRIPT)
repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo)


class TomlEvidenceTypes(unittest.TestCase):
    def cli(self, root):
        # Missing external tools are a supported state; fixtures need no network.
        return subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--json'],
                              env={**os.environ, 'PATH': ''}, capture_output=True,
                              text=True, timeout=10)

    def test_cli_rejects_native_date_time_values_and_preserves_siblings(self):
        values = ('2026-10-07', '12:34:56', '2026-10-07T12:34:56',
                  '2026-10-07T12:34:56Z', '["valid", 2026-10-07]',
                  '{nested = {date = 2026-10-07}}')
        for filename, section, key in (('Cargo.toml', 'package', 'cargo'),
                                       ('pyproject.toml', 'project', 'python')):
            for value in values:
                with self.subTest(filename=filename, value=value), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / filename).write_text(f'[{section}]\nname = "demo"\ndescription = "keep me"\nkeywords = {value}\n')
                    (root / 'package.json').write_text('{"private":true,"description":"valid sibling"}')
                    result = self.cli(root)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stderr, '')
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload['status'], 'error')
                    manifest = payload['manifests'][key]
                    self.assertIsNone(manifest['keywords'])
                    self.assertEqual(manifest['description'], 'keep me')
                    self.assertEqual(manifest['name'], 'demo')
                    self.assertEqual(manifest['status'], 'error')
                    self.assertEqual(payload['manifests']['npm'][0]['description'], 'valid sibling')
                    self.assertTrue(any(item['path'] == filename and 'keywords' in item['reason']
                                        for item in payload['errors']))
                    json.dumps(payload, allow_nan=False)

    def test_all_exported_fields_reject_unsupported_values(self):
        fields = {'Cargo.toml': ('package', 'cargo', ('name', 'version', 'publish', 'description',
                  'homepage', 'repository', 'readme', 'keywords', 'categories')),
                  'pyproject.toml': ('project', 'python', ('name', 'description', 'urls', 'keywords'))}
        for filename, (section, key, names) in fields.items():
            for name in names:
                with self.subTest(filename=filename, field=name), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / filename).write_text(f'[{section}]\n{name} = 2026-10-07\n')
                    manifests = repo.collect_manifests(root)
                    self.assertIsNone(manifests[key][name])
                    self.assertTrue(manifests['errors'])
                    json.dumps(manifests, allow_nan=False)

    def test_nonfinite_toml_values_are_rejected(self):
        for value in ('inf', '-inf', 'nan', '[inf]', '{nested = nan}'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'pyproject.toml').write_text(f'[project]\ndescription = "kept"\nkeywords = {value}\n')
                result = self.cli(root)
                self.assertEqual(result.returncode, 1)
                payload = json.loads(result.stdout)
                self.assertIsNone(payload['manifests']['python']['keywords'])
                json.dumps(payload, allow_nan=False)

    def test_valid_values_and_ignored_metadata_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Cargo.toml').write_text('[package]\nname="demo"\npublish=false\nversion={workspace=true}\nkeywords=["a","b"]\n[package.metadata]\ndate=2026-10-07\n')
            (root / 'pyproject.toml').write_text('[project]\nname="python-demo"\nkeywords=["x"]\n[project.urls]\nHomepage="https://example.com/"\n[tool.sample]\ndate=2026-10-07\n')
            result = self.cli(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload['manifests']['cargo']['version'], {'workspace': True})
            self.assertEqual(payload['manifests']['cargo']['publish'], False)
            self.assertEqual(payload['manifests']['python']['urls'], {'Homepage': 'https://example.com/'})
            self.assertEqual(payload['errors'], [])


if __name__ == '__main__':
    unittest.main()
