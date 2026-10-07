"""Synthetic Shipwise array validation and structured-error regressions."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import repo_seo_baseline as repo


class ShipwiseValueTests(unittest.TestCase):
    def evaluate(self, keywords):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project.yaml"
            project.write_text("discoverability:\n  keywords:\n" +
                               "".join("    - " + value + "\n" for value in keywords))
            return repo.evaluate_shipwise_project(root, project)

    def test_keyword_members_must_be_nonblank_strings(self):
        for values in [('""',), ("'   '",), ("null",), ("false",), ("[]",), ("valid", "null")]:
            with self.subTest(values=values):
                result = self.evaluate(values)
                self.assertEqual(result["checks"]["keywords"]["status"], "error")
                self.assertIn("invalid", result["checks"]["keywords"]["reason"])

    def test_valid_keywords_keep_submitted_evidence(self):
        result = self.evaluate(["'  synthetic term  '", "second"])
        self.assertEqual(result["checks"]["keywords"]["status"], "ok")
        self.assertEqual(result["checks"]["keywords"]["evidence"], ["  synthetic term  ", "second"])

    def test_repetition_is_an_observation_with_explicit_unicode_matching_basis(self):
        cases = [("Go", "Django and Google", 2), ("Straße", "STRASSE, Straße!", 2),
                 ("repo seo", "repo seo; (repo seo)", 2), ("中文", "中文工具，中文文档", 2)]
        for keyword, description, count in cases:
            with self.subTest(keyword=keyword), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                project = root / "project.yaml"
                project.write_text("discoverability:\n  primary_keyword: " + json.dumps(keyword, ensure_ascii=False) +
                                   "\n  description: " + json.dumps(description, ensure_ascii=False) + "\n")
                result = repo.evaluate_shipwise_project(root, project)
                self.assertNotIn("keyword_stuffing", result["checks"])
                self.assertEqual(result["keyword_observations"]["primary_keyword_occurrences"], count)
                self.assertEqual(result["keyword_observations"]["matching_basis"], "casefolded_substring")
                self.assertEqual(result["checks"]["primary_keyword_in_description"]["status"], "ok")
                # Existing missing-input gates still produce structured errors.
                self.assertEqual(result["checks"]["keywords"]["status"], "error")

    def test_missing_keyword_has_zero_observations_and_keeps_required_gate(self):
        result = self.evaluate(["valid"])
        self.assertEqual(result["keyword_observations"]["primary_keyword_occurrences"], 0)
        self.assertEqual(result["checks"]["primary_keyword"]["status"], "error")

    def test_duplicate_unhashable_topics_emit_json_errors_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project.yaml"
            project.write_text("discoverability:\n  topics:\n    - []\n    - []\n")
            stream = io.StringIO()
            with patch.object(sys, "argv", ["repo", "--root", str(root), "--project-yaml", str(project), "--json"]), \
                    patch.object(repo, "run_cmd", return_value={"status": "skipped", "reason": "synthetic"}), \
                    patch.object(repo, "site_resource_checks") as site, contextlib.redirect_stdout(stream):
                code = repo.main()
            self.assertEqual(code, 1)
            site.assert_not_called()
            result = json.loads(stream.getvalue())
            checks = result["shipwise"]["checks"]
            self.assertEqual(checks["topics_format"]["status"], "error")
            self.assertEqual(checks["topics_unique"]["status"], "error")
            self.assertEqual(checks["topics_unique"]["evidence"], [[]])


if __name__ == "__main__":
    unittest.main()
