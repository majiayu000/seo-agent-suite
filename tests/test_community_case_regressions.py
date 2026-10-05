"""Case-insensitive candidate filenames retain their original evidence paths."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import repo_seo_baseline as repo


class CommunityCaseTests(unittest.TestCase):
    def test_case_variants_are_discovered_in_existing_supported_locations(self):
        for directory in ("", ".github", "docs"):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                folder = root / directory
                folder.mkdir(exist_ok=True)
                for name in ("readme.md", "Contributing.md", "code_of_conduct.md", "security"):
                    (folder / name).write_text("# Synthetic document\n")
                result = repo.collect_community_files(root)
                for key in ("readme", "contributing", "code_of_conduct", "security"):
                    self.assertTrue(result[key], key)
                    self.assertEqual(len(result["community_file_paths"][key]), 1)
                self.assertEqual(result["community_file_paths"]["readme"],
                                 [(folder / "readme.md").relative_to(root).as_posix()])
                self.assertEqual(repo.collect_readmes(root)[0]["first_heading"], "# Synthetic document")

    def test_directories_and_similar_unrecognized_filenames_remain_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "readme.md").mkdir()
            (root / "contributing.md.backup").write_text("Synthetic backup")
            result = repo.collect_community_files(root)
            self.assertFalse(result["readme"])
            self.assertFalse(result["contributing"])


if __name__ == "__main__":
    unittest.main()
