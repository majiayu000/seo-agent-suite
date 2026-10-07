"""Bounded YAML double-quoted escapes preserve semantic string evidence."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import repo_seo_baseline as repo


class YamlEscapeTests(unittest.TestCase):
    def test_named_escapes(self):
        pairs = {'0': '\0', 'a': '\a', 'b': '\b', 't': '\t', '\t': '\t',
                 'n': '\n', 'v': '\v', 'f': '\f', 'r': '\r', 'e': '\x1b',
                 ' ': ' ', '"': '"', '/': '/', '\\': '\\', 'N': '\x85',
                 '_': '\xa0', 'L': '\u2028', 'P': '\u2029'}
        for escape, expected in pairs.items():
            with self.subTest(escape=repr(escape)):
                self.assertEqual(repo.parse_scalar('"before\\' + escape + 'after"'),
                                 'before' + expected + 'after')

    def test_fixed_width_unicode_and_literal_unicode_are_equivalent(self):
        for encoded, literal in [(r'\x41', 'A'), (r'\u4e2d\u6587', '中文'),
                                 (r'\U0001F680', '🚀'), (r'\U0010FFFF', '\U0010ffff')]:
            with self.subTest(encoded=encoded):
                self.assertEqual(repo.parse_scalar('"' + encoded + '"'), literal)
        self.assertEqual(repo.parse_scalar(r'"中文\t🚀\u0021"'), '中文\t🚀!')

    def test_yaml_next_line_is_not_python_named_unicode(self):
        self.assertEqual(repo.parse_scalar(r'"\N{SPACE}"'), '\x85{SPACE}')

    def test_decoding_is_single_pass(self):
        self.assertEqual(repo.parse_scalar(r'"\\u4e2d\\n"'), r'\u4e2d\n')

    def test_quote_properties_and_comments_remain_supported(self):
        for prefix in ('', '!!str ', '!<tag:yaml.org,2002:str> ', '&label '):
            with self.subTest(prefix=prefix):
                self.assertEqual(repo.parse_scalar(prefix + r'"a\" # b\t" # outside'), 'a" # b\t')
        self.assertEqual(repo.parse_scalar('""'), '')

    def test_single_quoted_and_plain_backslashes_remain_literal(self):
        self.assertEqual(repo.parse_scalar(r"'中文\n\u0041\q it''s'"), r"中文\n\u0041\q it's")
        self.assertEqual(repo.parse_scalar(r'中文\n\u0041\q'), r'中文\n\u0041\q')

    def test_invalid_escapes_are_controlled_errors_without_input_disclosure(self):
        for value in (r'"private\q"', r'"private\x1"', r'"private\xGG"',
                      r'"private\u123"', r'"private\uZZZZ"', r'"private\U00110000"',
                      r'"private\uD800"', r'"private\U0000DFFF"',
                      r'"private\uD83D\uDE80"', r'"private\c"',
                      r'"private\"', '"private', '"private" trailing'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as error:
                    repo.parse_scalar(value)
                self.assertNotIn('private', str(error.exception))

    def run_cli(self, scalar):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / 'project.yaml'
            project.write_text('discoverability:\n  description: ' + scalar +
                               '\n  primary_keyword: 中文\n  keywords:\n    - "中文"\n  topics: []\n', encoding='utf-8')
            env = os.environ.copy()
            env['PATH'] = ''  # No git/gh/npm/network commands in this synthetic CLI fixture.
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/repo_seo_baseline.py'),
                                     '--root', tmp, '--project-yaml', str(project), '--json'],
                                    capture_output=True, text=True, env=env, timeout=15)
            return result

    def test_real_cli_json_contains_decoded_evidence(self):
        result = self.run_cli(r'"中文\t\u4e2d\u6587\n\U0001F680 \\\"quote\""')
        self.assertIn(result.returncode, (0, 1), result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['shipwise']['discoverability']['description'], '中文\t中文\n🚀 \\"quote"')
        self.assertNotIn('Traceback', result.stderr)

    def test_real_cli_invalid_escape_preserves_argparse_error_contract(self):
        result = self.run_cli(r'"private\q"')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertIn('error:', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('private', result.stderr)


if __name__ == '__main__':
    unittest.main()
