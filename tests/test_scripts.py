#!/usr/bin/env python3
"""Behavior checks for local audit scripts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepoSeoBaselineTests(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "repo_seo_baseline.py"), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_invalid_homepage_scheme_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_script("--root", tmp, "--homepage", "file:///tmp/site", "--json")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be an http(s) URL", result.stderr)

    def test_toml_unavailable_is_marked_as_error(self) -> None:
        module = load_script("repo_seo_baseline.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Cargo.toml").write_text('[package]\nname = "demo"\n', encoding="utf-8")
            original = module.tomllib
            module.tomllib = None
            try:
                manifests = module.collect_manifests(root)
            finally:
                module.tomllib = original

        self.assertEqual(manifests["cargo"]["status"], "error")
        self.assertEqual(manifests["errors"][0]["reason"], "tomllib unavailable on Python <3.11")

    def test_invalid_package_json_is_marked_as_error(self) -> None:
        module = load_script("repo_seo_baseline.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":', encoding="utf-8")

            manifests = module.collect_manifests(root)

        self.assertEqual(manifests["npm"], [])
        self.assertEqual(manifests["errors"][0]["path"], "package.json")
        self.assertIn("invalid JSON", manifests["errors"][0]["reason"])

    def test_unreadable_package_json_returns_explicit_error(self) -> None:
        module = load_script("repo_seo_baseline.py")
        with mock.patch.object(Path, "read_text", side_effect=OSError("denied")):
            data, error = module.read_json(Path("package.json"))

        self.assertIsNone(data)
        self.assertEqual(error["status"], "error")
        self.assertIn("denied", error["reason"])

    def test_shipwise_project_yaml_gate_returns_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            issue_dir = root / ".github" / "ISSUE_TEMPLATE"
            issue_dir.mkdir(parents=True)
            (issue_dir / "bug.md").write_text("# Bug\n", encoding="utf-8")
            project_yaml = root / "project.yaml"
            project_yaml.write_text(
                """name: "demo"
discoverability:
  description: "Demo repo SEO helper"
  primary_keyword: "repo seo"
  keywords:
    - "repo seo"
  topics:
    - "seo"
    - "github"
    - "developer-tools"
    - "metadata"
    - "open-source"
  homepage_url: "https://example.com"
  social_image_set: false
""",
                encoding="utf-8",
            )

            result = self.run_script("--root", str(root), "--project-yaml", str(project_yaml), "--json")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["shipwise"]["checks"]["social_image_set"]["status"], "error")

    def test_shipwise_gate_checks_keyword_topics_and_complete_community_files(self) -> None:
        module = load_script("repo_seo_baseline.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"]:
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            issue_dir = root / ".github" / "ISSUE_TEMPLATE"
            issue_dir.mkdir(parents=True)
            (issue_dir / "bug.md").write_text("# Bug\n", encoding="utf-8")
            project_yaml = root / "project.yaml"
            project_yaml.write_text(
                """discoverability:
  description: "A repo seo helper"
  primary_keyword: "repo seo"
  keywords:
    - "repo seo"
  topics:
    - "seo"
    - "github"
    - "developer-tools"
    - "metadata"
    - "open-source"
  homepage_url: "https://example.com"
  social_image_set: true
""",
                encoding="utf-8",
            )

            evidence = module.evaluate_shipwise_project(root, project_yaml)

            self.assertTrue(all(item["status"] == "ok" for item in evidence["checks"].values()))

            bad_text = project_yaml.read_text(encoding="utf-8").replace(
                'description: "A repo seo helper"', 'description: "A metadata helper"'
            ).replace('    - "open-source"', '    - "bad_topic!"')
            project_yaml.write_text(bad_text, encoding="utf-8")
            failed = module.evaluate_shipwise_project(root, project_yaml)

        self.assertEqual(failed["checks"]["primary_keyword_in_description"]["status"], "error")
        self.assertEqual(failed["checks"]["topics_format"]["status"], "error")

    def test_shipwise_gate_rejects_duplicate_topics_and_each_missing_community_file(self) -> None:
        module = load_script("repo_seo_baseline.py")
        required_files = [
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "SECURITY.md",
            ".github/ISSUE_TEMPLATE/bug.md",
        ]
        for missing in required_files:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in ["README.md", "LICENSE", *required_files[:-1]]:
                    if name != missing:
                        (root / name).write_text("ok\n", encoding="utf-8")
                issue_dir = root / ".github" / "ISSUE_TEMPLATE"
                issue_dir.mkdir(parents=True)
                if missing != required_files[-1]:
                    (issue_dir / "bug.md").write_text("# Bug\n", encoding="utf-8")
                project_yaml = root / "project.yaml"
                project_yaml.write_text(
                    """discoverability:
  description: "A repo seo helper"
  primary_keyword: "repo seo"
  keywords:
    - "repo seo"
  topics:
    - "seo"
    - "seo"
    - "developer-tools"
    - "metadata"
    - "open-source"
  homepage_url: "https://example.com"
  social_image_set: true
""",
                    encoding="utf-8",
                )

                evidence = module.evaluate_shipwise_project(root, project_yaml)

            self.assertEqual(evidence["checks"]["topics_unique"]["status"], "error")
            check_name = {
                "CONTRIBUTING.md": "contributing",
                "CODE_OF_CONDUCT.md": "code_of_conduct",
                "SECURITY.md": "security",
                ".github/ISSUE_TEMPLATE/bug.md": "issue_templates",
            }[missing]
            self.assertEqual(evidence["checks"][check_name]["status"], "error")

    def test_http_check_blocks_private_dns_and_private_redirect_targets(self) -> None:
        module = load_script("repo_seo_baseline.py")
        private_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]
        with (
            mock.patch.object(module.socket, "getaddrinfo", return_value=private_answer),
            mock.patch.object(module.urllib.request, "build_opener") as build_opener,
        ):
            result = module.http_check("http://audit-target.example")

        self.assertEqual(result["status"], "error")
        self.assertIn("non-public", result["reason"])
        build_opener.assert_not_called()

        handler = module.PublicOnlyRedirectHandler()
        request = module.urllib.request.Request("https://public.example")
        with (
            mock.patch.object(module.socket, "getaddrinfo", return_value=private_answer),
            self.assertRaises(module.urllib.error.URLError),
        ):
            handler.redirect_request(
                request, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data"
            )

    def test_public_url_validation_covers_credentials_ports_dns_and_redirects(self) -> None:
        module = load_script("repo_seo_baseline.py")
        public_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        with mock.patch.object(module.socket, "getaddrinfo", return_value=public_answer):
            module.validate_public_http_url("https://example.com")
            handler = module.PublicOnlyRedirectHandler()
            request = module.urllib.request.Request("https://example.com/start")
            redirected = handler.redirect_request(
                request, None, 302, "Found", {}, "https://example.com/final"
            )
        self.assertEqual(redirected.full_url, "https://example.com/final")

        invalid_urls = [
            "file:///tmp/local",
            "https://user:pass@example.com/",
            "https://example.com:not-a-port/",
        ]
        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                module.validate_public_http_url(url)

        with mock.patch.object(
            module.socket, "getaddrinfo", side_effect=module.socket.gaierror("dns down")
        ), self.assertRaisesRegex(ValueError, "resolution failed"):
            module.validate_public_http_url("https://unresolved.example")
        with mock.patch.object(module.socket, "getaddrinfo", return_value=[]), self.assertRaisesRegex(
            ValueError, "no addresses"
        ):
            module.validate_public_http_url("https://empty.example")

    def test_http_check_uses_public_only_opener_and_surfaces_transport_errors(self) -> None:
        module = load_script("repo_seo_baseline.py")

        class Response:
            status = 200
            headers = {"content-type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return b"ok"

            def geturl(self):
                return "https://example.com/final"

        class Opener:
            def __init__(self, result):
                self.result = result

            def open(self, _request, timeout):
                if isinstance(self.result, Exception):
                    raise self.result
                self.timeout = timeout
                return self.result

        public_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        with (
            mock.patch.object(module.socket, "getaddrinfo", return_value=public_answer),
            mock.patch.object(module.urllib.request, "build_opener", return_value=Opener(Response())),
        ):
            success = module.http_check("https://example.com")
        self.assertEqual(success["status"], "ok")
        self.assertEqual(success["sample_bytes"], 2)

        failures = [module.urllib.error.URLError("offline"), TimeoutError()]
        for failure in failures:
            with (
                self.subTest(failure=type(failure).__name__),
                mock.patch.object(module.socket, "getaddrinfo", return_value=public_answer),
                mock.patch.object(module.urllib.request, "build_opener", return_value=Opener(failure)),
            ):
                result = module.http_check("https://example.com")
            self.assertEqual(result["status"], "error")

    def test_package_json_root_must_be_an_object(self) -> None:
        module = load_script("repo_seo_baseline.py")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package.json"
            path.write_text("[]", encoding="utf-8")

            data, error = module.read_json(path)

        self.assertIsNone(data)
        self.assertIn("must be an object", error["reason"])

    def test_valid_package_json_preserves_manifest_data(self) -> None:
        module = load_script("repo_seo_baseline.py")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "package.json"
            path.write_text('{"name":"demo"}', encoding="utf-8")

            data, error = module.read_json(path)

        self.assertEqual(data["name"], "demo")
        self.assertIsNone(error)

    def test_site_resource_errors_all_fail_the_top_level_gate(self) -> None:
        module = load_script("repo_seo_baseline.py")
        evidence = {
            "manifests": {"errors": []},
            "site": {
                "https://example.com": {
                    "homepage": {"status": "ok", "url": "https://example.com"},
                    "robots": {"status": "error", "url": "https://example.com/robots.txt", "reason": "redirect blocked"},
                    "sitemap": {"status": "ok", "url": "https://example.com/sitemap.xml"},
                }
            },
            "shipwise": {"checks": {}},
        }

        errors = module.collect_errors(evidence)

        self.assertEqual(errors[0]["resource"], "robots")
        self.assertEqual(errors[0]["reason"], "redirect blocked")


class SiteMetaAuditTests(unittest.TestCase):
    def test_invalid_url_scheme_fails(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "site_meta_audit.py"), "file:///tmp/index.html", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("url must be an http(s) URL", result.stderr)

    def test_html_soft_404_is_not_resource_present(self) -> None:
        module = load_script("site_meta_audit.py")
        present, reason = module.resource_present(
            {
                "status": "ok",
                "http_status": 200,
                "content_type": "text/html",
                "body": "<html><title>Not found</title></html>",
            },
            "sitemap.xml",
        )

        self.assertFalse(present)
        self.assertIn("HTML", reason)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
