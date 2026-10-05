"""Offline regressions for the supported Shipwise block grammar."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import repo_seo_baseline as repo


class DiscoverabilityStructureTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.yaml"
            path.write_text(text, encoding="utf-8")
            return repo.parse_shipwise_discoverability(path)

    def test_nested_fields_are_not_promoted_to_direct_fields(self):
        for indentation in ("   ", "    ", "      ", "  \t"):
            with self.subTest(indentation=repr(indentation)):
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    self.parse("discoverability:\n  nested:\n" + indentation +
                               "primary_keyword: nested-only\n")

    def test_comments_do_not_change_the_direct_record(self):
        expected = {"primary_keyword": "synthetic keyword", "topics": ["synthetic topic"]}
        variants = [
            "discoverability:\n  primary_keyword: synthetic keyword\n  topics:\n    - synthetic topic\n",
            "discoverability: # record\n  primary_keyword: synthetic keyword\n  topics: # list\n    - synthetic topic\n",
            "discoverability:\n  primary_keyword: synthetic keyword\n# comment\n  topics:\n    - synthetic topic\n",
            "discoverability:\n  primary_keyword: synthetic keyword\n  # comment\n  topics:\n    # comment\n    - synthetic topic\n",
        ]
        for text in variants:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), expected)

    def test_following_top_level_block_is_not_absorbed(self):
        self.assertEqual(self.parse(
            "discoverability:\n  primary_keyword: direct\nother:\n  primary_keyword: elsewhere\n"
        ), {"primary_keyword": "direct"})


if __name__ == "__main__":
    unittest.main()
