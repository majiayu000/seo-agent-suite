#!/usr/bin/env python3
"""Bounded lexical ATX/fence evidence, not a Markdown rendering contract."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('readme_contract', ROOT / 'scripts/repo_seo_baseline.py')
repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo)


class ReadmeHeadingContract(unittest.TestCase):
    def collect(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text(text, encoding='utf-8')
            return repo.collect_readmes(root)[0]

    def test_atx_levels_and_raw_unicode_evidence(self):
        for level in range(1, 7):
            for indent in range(4):
                heading = '#' * level + '\t 中文 café 👩🏽\u200d💻 **title** ###'
                with self.subTest(level=level, indent=indent):
                    self.assertEqual(self.collect(' ' * indent + heading + '  \n')['first_heading'], heading)

    def test_empty_atx_heading_is_still_evidence(self):
        for heading in ('#', '######', '## \t'):
            with self.subTest(heading=heading):
                self.assertEqual(self.collect(heading)['first_heading'], heading.strip())

    def test_non_heading_prefixes_do_not_win(self):
        for prefix in ('#hashtag', '####### invalid', '\\# escaped', '    # code', '\t# code', ' \t# code', '\u00a0# no', '#\u00a0no', '> # quote', '- # list'):
            with self.subTest(prefix=prefix):
                self.assertEqual(self.collect(prefix + '\n# Actual 标题\n')['first_heading'], '# Actual 标题')

    def test_backtick_and_tilde_fences(self):
        for fence in ('```', '~~~~'):
            for indent in range(4):
                prefix = ' ' * indent
                with self.subTest(fence=fence, indent=indent):
                    text = prefix + fence + 'sh\n# shell comment\n' + prefix + fence + '\t \n## Actual\n'
                    self.assertEqual(self.collect(text)['first_heading'], '## Actual')

    def test_close_requires_matching_character_length_and_no_info(self):
        for false_close in ('```', '~~~~', '`````sh', '````` # trailing', '    `````', '\t`````'):
            with self.subTest(false_close=false_close):
                text = '````sh\n' + false_close + '\n# Still code\n`````\n## Actual\n'
                self.assertEqual(self.collect(text)['first_heading'], '## Actual')

    def test_unclosed_fence_suppresses_until_eof(self):
        for opener in ('```sh', '~~~', '````'):
            with self.subTest(opener=opener):
                self.assertIsNone(self.collect(opener + '\n# Code only\n')['first_heading'])

    def test_invalid_openers_and_backtick_info(self):
        for opener in ('``', '~~', '    ```', '\t~~~', '```bad`info'):
            with self.subTest(opener=opener):
                self.assertEqual(self.collect(opener + '\n# Actual\n')['first_heading'], '# Actual')
        self.assertIsNone(self.collect('~~~info`allowed\n# Still code\n')['first_heading'])

    def test_multiple_fences_and_first_heading_selection(self):
        text = '```sh\n# one\n```\n~~~md\n## two\n~~~~\n### First\n# Later\n'
        self.assertEqual(self.collect(text)['first_heading'], '### First')

    def test_missing_heading_and_unsupported_setext(self):
        for text in ('', '\n \n', 'Title\n=====\n', 'plain text\n#hashtag\n'):
            with self.subTest(text=text):
                self.assertIsNone(self.collect(text)['first_heading'])

    def test_other_readme_evidence_is_unchanged(self):
        text = '\n  ```sh  \n# ignored\n```\n  ## Title ###  \n\n'
        self.assertEqual(self.collect(text), {'path': 'README.md', 'line_count': 6, 'first_heading': '## Title ###', 'first_non_empty': '```sh'})

    def test_discovery_order_and_fence_state_per_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.github').mkdir()
            (root / 'docs').mkdir()
            (root / 'README.md').write_text('```\n# Unclosed\n')
            (root / '.github/readme.MD').write_text('## GitHub\n')
            (root / 'docs/ReadMe.txt').write_text('### Docs\n')
            (root / 'README-directory').mkdir()
            actual = repo.collect_readmes(root)
            self.assertEqual([item['path'] for item in actual], ['.github/readme.MD', 'README.md', 'docs/ReadMe.txt'])
            self.assertEqual([item['first_heading'] for item in actual], ['## GitHub', None, '### Docs'])

    def test_real_cli_json_contract_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text('```sh\n# comment\n```\n# 标题 ###\n', encoding='utf-8')
            env = dict(os.environ, PATH='')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/repo_seo_baseline.py'), '--root', str(root), '--json'], env=env, capture_output=True, text=True, encoding='utf-8', timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data['readmes'][0]['first_heading'], '# 标题 ###')
            self.assertEqual(data['status'], 'ok')
            self.assertEqual(data['errors'], [])
            self.assertTrue(data['community_files']['readme'])


if __name__ == '__main__':
    unittest.main()
