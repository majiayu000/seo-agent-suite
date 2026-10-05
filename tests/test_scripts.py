#!/usr/bin/env python3
"""Behavior checks for local audit scripts."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def public_http_mod(module):
    """Return the shared public_http module used by audit scripts."""
    return module.public_http


class PublicHttpURLTests(unittest.TestCase):
    def test_request_blocks_non_public_endpoints_before_connect(self) -> None:
        module = load_script("public_http.py")
        addresses = [
            "64:ff9b::a9fe:a9fe",  # NAT64 link-local IPv4
            "64:ff9b::7f00:1",  # NAT64 loopback IPv4
            "64:ff9b::a00:1",  # NAT64 private IPv4
            "64:ff9b::e000:1",  # NAT64 multicast IPv4
            "64:ff9b::",  # NAT64 unspecified IPv4
            "64:ff9b:1::1",  # Local-use NAT64 prefix
            "fec0::1",
            "feff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",  # Site-local upper bound
            "224.0.0.1",
            "239.255.255.250",
            "ff02::1",
            "::ffff:224.0.0.1",  # IPv4-mapped multicast
            "10.0.0.1",
            "127.0.0.1",
            "169.254.169.254",
            "::ffff:127.0.0.1",
            "::",
            "::1",
            "fe80::1",
            "100::1",  # Reserved IPv6
        ]
        public_endpoint = (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))
        for address in addresses:
            ipv6 = ":" in address
            family = module.socket.AF_INET6 if ipv6 else module.socket.AF_INET
            sockaddr = (address, 80, 0, 0) if ipv6 else (address, 80)
            endpoint = (family, module.socket.SOCK_STREAM, 6, "", sockaddr)
            literal_url = f"http://[{address}]/" if ipv6 else f"http://{address}/"
            for url in (literal_url, "http://audit-target.example/"):
                for endpoints in ([endpoint], [public_endpoint, endpoint]):
                    with (
                        self.subTest(address=address, url=url, mixed=len(endpoints) > 1),
                        mock.patch.object(module.socket, "getaddrinfo", return_value=endpoints),
                        mock.patch.object(module, "select_proxy", return_value=None),
                        mock.patch.object(
                            module, "connect_endpoint", side_effect=AssertionError("blocked connect")
                        ) as connect_endpoint,
                    ):
                        with self.assertRaisesRegex(
                            ValueError, "^URL resolves to a non-public address$"
                        ):
                            module.request_public_url_once(url, 1)
                        connect_endpoint.assert_not_called()

    def test_public_unicast_endpoints_remain_allowed(self) -> None:
        module = load_script("public_http.py")
        for address in ("8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8", "64:ff9b::808:808"):
            ipv6 = ":" in address
            family = module.socket.AF_INET6 if ipv6 else module.socket.AF_INET
            sockaddr = (address, 80, 0, 0) if ipv6 else (address, 80)
            endpoints = [(family, module.socket.SOCK_STREAM, 6, "", sockaddr)]
            with self.subTest(address=address), mock.patch.object(
                module.socket, "getaddrinfo", return_value=endpoints
            ):
                parsed, validated = module.validate_public_http_url("http://public.example/")
            self.assertEqual(parsed.hostname, "public.example")
            self.assertEqual(validated, endpoints)

    def test_audit_entrypoints_report_non_public_address_error(self) -> None:
        for script, entrypoint in (("repo_seo_baseline.py", "http_check"), ("site_meta_audit.py", "fetch")):
            module = load_script(script)
            shared = public_http_mod(module)
            for address in ("64:ff9b::a9fe:a9fe", "fec0::1", "ff02::1"):
                endpoint = (shared.socket.AF_INET6, shared.socket.SOCK_STREAM, 6, "", (address, 80, 0, 0))
                with (
                    self.subTest(script=script, address=address),
                    mock.patch.object(shared.socket, "getaddrinfo", return_value=[endpoint]),
                    mock.patch.object(shared, "select_proxy", return_value=None),
                    mock.patch.object(
                        shared, "connect_endpoint", side_effect=AssertionError("blocked connect")
                    ) as connect_endpoint,
                ):
                    result = getattr(module, entrypoint)("http://audit-target.example/")
                    self.assertEqual(result["status"], "error")
                    self.assertEqual(result["reason"], "URL resolves to a non-public address")
                    connect_endpoint.assert_not_called()


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

    def test_cli_homepage_credentials_are_redacted_and_still_fail(self) -> None:
        for authority in ("example.invalid:8443", "[2001:db8::1]:8443"):
            for output_args in ((), ("--json",)):
                with self.subTest(authority=authority, output_args=output_args), tempfile.TemporaryDirectory() as tmp:
                    result = self.run_script(
                        "--root", tmp, "--homepage",
                        f"https://dummy-user:dummy-password@{authority}/docs/?view=full#section",
                        *output_args,
                    )

                self.assertEqual(result.returncode, 1)
                self.assertNotIn("dummy-user", result.stdout + result.stderr)
                self.assertNotIn("dummy-password", result.stdout + result.stderr)
                self.assertIn("URL credentials are not allowed", result.stdout)
                if output_args:
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload["status"], "error")
                    self.assertEqual(list(payload["site"]), [f"https://{authority}/docs?view=full"])

    def test_manifest_homepage_credentials_are_redacted_before_output(self) -> None:
        module = load_script("repo_seo_baseline.py")
        for manifest in ("package.json", "Cargo.toml"):
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                homepage = "https://dummy-user:dummy-password@example.invalid/docs"
                content = (
                    json.dumps({"homepage": homepage}) if manifest == "package.json"
                    else f'[package]\nhomepage = "{homepage}"\n'
                )
                (root / manifest).write_text(content, encoding="utf-8")
                stdout = io.StringIO()
                with (
                    mock.patch.object(sys, "argv", ["repo_seo_baseline.py", "--root", tmp, "--json"]),
                    mock.patch.object(sys, "stdout", stdout),
                    mock.patch.object(module, "run_cmd", return_value={"status": "skipped"}),
                    mock.patch.object(module.public_http.socket, "getaddrinfo") as resolve,
                    mock.patch.object(module.public_http, "connect_endpoint") as connect,
                ):
                    code = module.main()

            self.assertEqual(code, 1)
            self.assertNotIn("dummy-user", stdout.getvalue())
            self.assertNotIn("dummy-password", stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            item = payload["manifests"]["npm"][0] if manifest == "package.json" else payload["manifests"]["cargo"]
            self.assertEqual(item["homepage"], "https://example.invalid/docs")
            self.assertEqual(payload["site"]["https://example.invalid/docs"]["homepage"]["status"], "error")
            resolve.assert_not_called()
            connect.assert_not_called()

    def test_shipwise_homepage_credentials_fail_without_leaking_evidence(self) -> None:
        module = load_script("repo_seo_baseline.py")
        for userinfo in ("dummy-user:dummy-password", "dummy-user", ":dummy-password", ""):
            with self.subTest(userinfo=userinfo), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in ("README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"):
                    (root / name).write_text("ok\n", encoding="utf-8")
                issue_dir = root / ".github" / "ISSUE_TEMPLATE"
                issue_dir.mkdir(parents=True)
                (issue_dir / "bug.md").write_text("ok\n", encoding="utf-8")
                project_yaml = root / "project.yaml"
                project_yaml.write_text(
                    'discoverability:\n'
                    '  description: "A repo seo helper"\n'
                    '  primary_keyword: "repo seo"\n'
                    '  keywords:\n    - "repo seo"\n'
                    '  topics:\n    - "seo"\n    - "github"\n    - "developer-tools"\n    - "metadata"\n    - "open-source"\n'
                    f'  homepage_url: "https://{userinfo}@example.invalid/docs"\n'
                    '  social_image_set: true\n',
                    encoding="utf-8",
                )
                evidence = module.evaluate_shipwise_project(root, project_yaml)
                serialized = json.dumps(evidence)
                result = self.run_script("--root", tmp, "--project-yaml", str(project_yaml), "--json")

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(evidence["checks"]["homepage_url"]["status"], "error")
            self.assertIn("credentials", evidence["checks"]["homepage_url"]["reason"])
            self.assertEqual(evidence["checks"]["homepage_url"]["evidence"], "https://example.invalid/docs")
            self.assertEqual(evidence["discoverability"]["homepage_url"], "https://example.invalid/docs")
            self.assertEqual([key for key, value in evidence["checks"].items() if value["status"] == "error"], ["homepage_url"])
            self.assertEqual(payload["errors"][0]["check"], "homepage_url")
            self.assertNotIn("dummy-user", serialized + result.stdout + result.stderr)
            self.assertNotIn("dummy-password", serialized + result.stdout + result.stderr)

    def test_redacted_homepage_collision_preserves_credential_error(self) -> None:
        module = load_script("repo_seo_baseline.py")

        def request_once(url, *_args, **_kwargs):
            module.validate_public_http_url(url)
            return {"http_status": 200, "location": None, "content_type": "text/plain", "sample_bytes": 0, "body": b""}

        for homepages in (
            ["https://dummy-user:dummy-password@example.invalid/docs", "https://example.invalid/docs"],
            ["https://example.invalid/docs", "https://dummy-user:dummy-password@example.invalid/docs"],
        ):
            with self.subTest(homepages=homepages), tempfile.TemporaryDirectory() as tmp:
                stdout = io.StringIO()
                argv = ["repo_seo_baseline.py", "--root", tmp, "--json"]
                for homepage in homepages:
                    argv.extend(["--homepage", homepage])
                with (
                    mock.patch.object(sys, "argv", argv),
                    mock.patch.object(sys, "stdout", stdout),
                    mock.patch.object(module, "run_cmd", return_value={"status": "skipped"}),
                    mock.patch.object(module.public_http.socket, "getaddrinfo", return_value=[
                        (module.public_http.socket.AF_INET, module.public_http.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
                    ]),
                    mock.patch.object(module.public_http, "request_public_url_once", side_effect=request_once) as request,
                ):
                    code = module.main()

            self.assertEqual(code, 1)
            self.assertNotIn("dummy-password", stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["site"]["https://example.invalid/docs"]["homepage"]["status"], "error")
            self.assertEqual(request.call_count, 8)
            expected_urls = []
            for homepage in homepages:
                origin = homepage.removesuffix("/docs")
                expected_urls.extend([
                    homepage,
                    origin + "/robots.txt",
                    origin + "/sitemap.xml",
                    homepage + "/sitemap.xml",
                ])
            self.assertEqual([call.args[0] for call in request.call_args_list], expected_urls)

    def test_invalid_homepage_scheme_diagnostic_redacts_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_script("--root", tmp, "--homepage", "ftp://dummy-user:dummy-password@example.invalid/docs")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be an http(s) URL", result.stderr)
        self.assertNotIn("dummy-user", result.stderr)
        self.assertNotIn("dummy-password", result.stderr)

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

    def test_invalid_manifest_encoding_keeps_error_handoff(self) -> None:
        module = load_script("repo_seo_baseline.py")
        for filename in ["package.json", "Cargo.toml", "pyproject.toml"]:
            for output_args in [("--json",), ()]:
                with self.subTest(filename=filename, output_args=output_args), tempfile.TemporaryDirectory() as tmp:
                    (Path(tmp) / filename).write_bytes(b"\xff")
                    result = self.run_script("--root", tmp, *output_args)

                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertNotIn("Traceback", result.stdout)
                    reason = (
                        "invalid UTF-8" if filename == "package.json" or module.tomllib
                        else "tomllib unavailable on Python <3.11"
                    )
                    if output_args:
                        payload = json.loads(result.stdout)
                        self.assertEqual(payload["status"], "error")
                        self.assertEqual(len(payload["errors"]), 1)
                        self.assertEqual(payload["errors"][0]["surface"], "manifest")
                        self.assertEqual(payload["errors"][0]["path"], filename)
                        self.assertIn(reason, payload["errors"][0]["reason"])
                    else:
                        self.assertIn("status: error", result.stdout)
                        self.assertIn(reason, result.stdout)

    def test_non_table_toml_sections_emit_json_errors(self) -> None:
        module = load_script("repo_seo_baseline.py")
        for filename, section, manifest in [
            ("Cargo.toml", "package", "cargo"),
            ("pyproject.toml", "project", "python"),
        ]:
            for value in ['"nope"', "true", "123", "1.5", "[]", '["demo"]', "1979-05-27"]:
                with self.subTest(filename=filename, value=value), tempfile.TemporaryDirectory() as tmp:
                    (Path(tmp) / filename).write_text(f"{section} = {value}\n", encoding="utf-8")
                    result = self.run_script("--root", tmp, "--json")

                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    payload = json.loads(result.stdout)
                    reason = (
                        f"{section} must be a TOML table"
                        if module.tomllib else "tomllib unavailable on Python <3.11"
                    )
                    error = {"path": filename, "status": "error", "reason": reason}
                    self.assertEqual(payload["status"], "error")
                    self.assertEqual(payload["manifests"][manifest], error)
                    self.assertEqual(payload["manifests"]["errors"], [error])
                    self.assertEqual(payload["errors"], [{"surface": "manifest", **error}])
                    self.assertEqual(payload["registry"], {"npm": {}, "crates": {}})

    def test_manifest_errors_accumulate_and_preserve_json_handoff(self) -> None:
        module = load_script("repo_seo_baseline.py")
        for toml in ['package = "nope"\n', "[package\n"]:
            with self.subTest(toml=toml), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "Cargo.toml").write_text(toml, encoding="utf-8")
                (root / "pyproject.toml").write_text(toml.replace("package", "project"), encoding="utf-8")
                (root / "package.json").write_text('{"name":', encoding="utf-8")
                (root / "README.md").write_text("# Still collected\n", encoding="utf-8")
                result = self.run_script("--root", tmp, "--json")

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "")
                payload = json.loads(result.stdout)
                errors = {item["path"]: item for item in payload["errors"]}
                self.assertEqual(set(errors), {"package.json", "Cargo.toml", "pyproject.toml"})
                self.assertTrue(all(item["surface"] == "manifest" for item in errors.values()))
                self.assertIn("invalid JSON", errors["package.json"]["reason"])
                toml_reason = (
                    "must be a TOML table" if '"nope"' in toml else "invalid TOML"
                ) if module.tomllib else "tomllib unavailable on Python <3.11"
                for filename in ["Cargo.toml", "pyproject.toml"]:
                    self.assertIn(toml_reason, errors[filename]["reason"])
                self.assertEqual(payload["readmes"][0]["first_heading"], "# Still collected")

    def test_toml_tables_and_optional_sections_keep_existing_behavior(self) -> None:
        module = load_script("repo_seo_baseline.py")
        for cargo, python in [
            ('[package]\ndescription = "Cargo demo"\n', '[project]\nname = "python-demo"\n'),
            ("[package]\n", "[project]\n"),
            ("[workspace]\n", "[tool.demo]\n"),
            ("", ""),
        ]:
            with self.subTest(cargo=cargo, python=python), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "Cargo.toml").write_text(cargo, encoding="utf-8")
                (root / "pyproject.toml").write_text(python, encoding="utf-8")
                result = self.run_script("--root", tmp, "--json")

                self.assertEqual(result.returncode, 0 if module.tomllib else 1)
                self.assertEqual(result.stderr, "")
                payload = json.loads(result.stdout)
                if module.tomllib:
                    self.assertEqual(payload["status"], "ok")
                    self.assertEqual(payload["errors"], [])
                    if "Cargo demo" in cargo:
                        self.assertEqual(payload["manifests"]["cargo"]["description"], "Cargo demo")
                        self.assertEqual(payload["manifests"]["python"]["name"], "python-demo")
                else:
                    self.assertEqual(len(payload["errors"]), 2)
                    self.assertTrue(all("tomllib unavailable" in item["reason"] for item in payload["errors"]))

    def test_issue_template_file_emits_json_and_fails_shipwise_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"]:
                (root / name).write_text("ok\n", encoding="utf-8")
            issue_templates = root / ".github" / "ISSUE_TEMPLATE"
            issue_templates.parent.mkdir()
            issue_templates.write_text("regular file\n", encoding="utf-8")
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
            result = self.run_script("--root", tmp, "--project-yaml", str(project_yaml), "--json")

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            payload = json.loads(result.stdout)
            self.assertFalse(payload["community_files"]["issue_templates"])
            self.assertFalse(payload["shipwise"]["community_files"]["issue_templates"])
            self.assertEqual(payload["status"], "error")
            self.assertEqual(
                {item["check"] for item in payload["errors"]}, {"issue_templates", "support_path"}
            )
            self.assertTrue(all(item["surface"] == "shipwise" for item in payload["errors"]))

            issue_templates.unlink()
            passing = self.run_script("--root", tmp, "--json")
            self.assertEqual(passing.returncode, 0)
            self.assertFalse(json.loads(passing.stdout)["community_files"]["issue_templates"])

    def test_issue_template_presence_controls_keep_json_baseline(self) -> None:
        for kind, expected in [("missing", False), ("file", False), ("empty_dir", False), ("dir", True)]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / ".github" / "ISSUE_TEMPLATE"
                if kind == "file":
                    path.parent.mkdir()
                    path.write_text("regular file\n", encoding="utf-8")
                elif kind in {"empty_dir", "dir"}:
                    path.mkdir(parents=True)
                    if kind == "dir":
                        (path / "bug.md").write_text("# Bug\n", encoding="utf-8")
                result = self.run_script("--root", tmp, "--json")

                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")
                payload = json.loads(result.stdout)
                self.assertEqual(payload["community_files"]["issue_templates"], expected)
                self.assertEqual(payload["errors"], [])

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

    def test_shipwise_cli_rejects_non_string_fields(self) -> None:
        valid_fields = {
            "description": '"A repo seo helper"',
            "primary_keyword": '"repo seo"',
            "homepage_url": '"https://example.com"',
        }
        invalid_values = [
            '\n    - "A repo seo helper"',
            "[]",
            "[repo, seo]",
            '["repo", "seo"]',
            "[ repo, seo ]",
            "[repo, {foo: bar}]",
            "{}",
            "{foo: bar}",
            "{foo:bar}",
            "{foo: [repo, seo]}",
            "null",
            "Null",
            "NULL",
            "~",
            "true",
            "True",
            "TRUE",
            "false",
            "False",
            "FALSE",
            "123",
            "1.5",
            "+123",
            "-123",
            "0123",
            "0o17",
            "0xFF",
            ".5",
            "123.",
            "+12e03",
            "-2E+05",
            ".inf",
            "-.Inf",
            "+.INF",
            ".nan",
            ".NaN",
            ".NAN",
            "1e999",
            "-1e999",
            "9" * 4301,
            "123 # note",
            "null # note",
            "true # note",
            "1e999 # note",
            "9" * 4301 + " # note",
            "!!int 123",
            '!!int "123"',
            "!!bool true",
            "!!null null",
            "!!float 1e999",
            "!<tag:yaml.org,2002:int> 123",
            "&value 123",
            "&value !!int 123 # note",
            "!!int &value 123 # note",
            "&value [repo, seo] # note",
            "!!map {foo: bar} # note",
            "*numeric",
            "*numeric # note",
            "*text",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"]:
                (root / name).write_text("ok\n", encoding="utf-8")
            issue_dir = root / ".github" / "ISSUE_TEMPLATE"
            issue_dir.mkdir(parents=True)
            (issue_dir / "bug.md").write_text("# Bug\n", encoding="utf-8")
            project_yaml = root / "project.yaml"
            tail = """  keywords:
    - "repo seo"
  topics:
    - "seo"
    - "github"
    - "developer-tools"
    - "metadata"
    - "open-source"
  social_image_set: true
"""
            for field in valid_fields:
                for value in invalid_values:
                    with self.subTest(field=field, value=value):
                        fields = {**valid_fields, field: value}
                        project_yaml.write_text(
                            'value: &numeric 123\ntext: &text "repo seo"\ndiscoverability:\n'
                            + "".join(f"  {key}: {item}\n" for key, item in fields.items())
                            + tail,
                            encoding="utf-8",
                        )
                        result = self.run_script(
                            "--root", str(root), "--project-yaml", str(project_yaml), "--json"
                        )
                        self.assertEqual(result.returncode, 1, result.stderr)
                        def reject_constant(value):
                            raise ValueError(f"non-JSON constant: {value}")

                        payload = json.loads(result.stdout, parse_constant=reject_constant)
                        self.assertEqual(payload["status"], "error")
                        check = payload["shipwise"]["checks"][field]
                        self.assertEqual(check["status"], "error")
                        self.assertEqual(check["reason"], f"discoverability.{field} must be a string")
                        self.assertIn(
                            {"surface": "shipwise", "check": field, "reason": check["reason"]},
                            payload["errors"],
                        )
                        self.assertNotIsInstance(payload["shipwise"]["discoverability"][field], str)
                        if field in {"description", "primary_keyword"}:
                            alignment = payload["shipwise"]["checks"]["primary_keyword_in_description"]
                            self.assertEqual(alignment["status"], "error")

            project_yaml.write_text(
                "discoverability:\n"
                + "".join(f"  {key}: {value}\n" for key, value in valid_fields.items())
                + tail,
                encoding="utf-8",
            )
            valid = self.run_script("--root", str(root), "--project-yaml", str(project_yaml), "--json")
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(json.loads(valid.stdout)["errors"], [])

    def test_shipwise_cli_rejects_null_and_numeric_keyword_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"]:
                (root / name).write_text("ok\n", encoding="utf-8")
            issue_dir = root / ".github" / "ISSUE_TEMPLATE"
            issue_dir.mkdir(parents=True)
            (issue_dir / "bug.md").write_text("# Bug\n", encoding="utf-8")
            project_yaml = root / "project.yaml"
            for value in ["null", "true", "123", "1.5", "+123", "0o17", "0xFF", ".5", "123.", ".inf", "[repo, seo]", "{foo: bar}", "123 # note", "!!int 123", "&value 123", "&value !!int 123 # note", '!!int "123"', "*numeric", "*numeric # note", "*text"]:
                with self.subTest(value=value):
                    project_yaml.write_text(
                        f"""value: &numeric 123
text: &text "repo seo"
discoverability:
  description: {value}
  primary_keyword: {value}
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
                    for json_mode in [True, False]:
                        with self.subTest(json_mode=json_mode):
                            args = ["--root", str(root), "--project-yaml", str(project_yaml)]
                            result = self.run_script(*args, *(["--json"] if json_mode else []))
                            self.assertEqual(result.returncode, 1, result.stdout)
                            if json_mode:
                                payload = json.loads(result.stdout)
                                self.assertEqual(payload["status"], "error")
                                for field in ["description", "primary_keyword"]:
                                    self.assertEqual(
                                        payload["shipwise"]["checks"][field],
                                        {
                                            "status": "error",
                                            "evidence": None,
                                            "reason": f"discoverability.{field} must be a string",
                                        },
                                    )
                            else:
                                self.assertIn("status: error", result.stdout)
                                self.assertIn("discoverability.description must be a string", result.stdout)
                                self.assertIn("discoverability.primary_keyword must be a string", result.stdout)

    def test_shipwise_cli_redacts_invalid_homepage_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_yaml = Path(tmp) / "project.yaml"
            project_yaml.write_text(
                'discoverability:\n'
                '  description: "A repo seo helper"\n'
                '  primary_keyword: "repo seo"\n'
                '  homepage_url:\n'
                '    - "https://synthetic-user:synthetic-password@example.invalid/docs"\n',
                encoding="utf-8",
            )
            for output_args in ((), ("--json",)):
                with self.subTest(output_args=output_args):
                    result = self.run_script(
                        "--root", tmp, "--project-yaml", str(project_yaml), *output_args,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertNotIn("synthetic-user", result.stdout + result.stderr)
                    self.assertNotIn("synthetic-password", result.stdout + result.stderr)
                    self.assertIn("discoverability.homepage_url must be a string", result.stdout)
                    if output_args:
                        payload = json.loads(result.stdout)
                        self.assertIsNone(payload["shipwise"]["discoverability"]["homepage_url"])
                        self.assertEqual(payload["shipwise"]["checks"]["homepage_url"]["status"], "error")

    def test_shipwise_cli_reports_mixed_type_duplicate_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_yaml = Path(tmp) / "project.yaml"
            project_yaml.write_text(
                """discoverability:
  description: "A repo seo helper"
  primary_keyword: "repo seo"
  homepage_url: "https://example.com"
  keywords:
    - "repo seo"
  topics:
    - 1
    - 1
    - "seo"
    - "seo"
    - "github"
  social_image_set: true
""",
                encoding="utf-8",
            )
            result = self.run_script("--root", tmp, "--project-yaml", str(project_yaml), "--json")
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["shipwise"]["checks"]["topics_format"]["status"], "error")
            self.assertEqual(payload["shipwise"]["checks"]["topics_unique"]["status"], "error")
            self.assertEqual(
                {item["check"] for item in payload["errors"] if item["check"].startswith("topics_")},
                {"topics_format", "topics_unique"},
            )

    def test_shipwise_cli_preserves_string_and_missing_field_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"]:
                (root / name).write_text("ok\n", encoding="utf-8")
            issue_dir = root / ".github" / "ISSUE_TEMPLATE"
            issue_dir.mkdir(parents=True)
            (issue_dir / "bug.md").write_text("# Bug\n", encoding="utf-8")
            project_yaml = root / "project.yaml"
            fields = {
                "description": '"A repo seo helper"',
                "primary_keyword": '"repo seo"',
                "homepage_url": '"https://example.com"',
            }
            tail = """  keywords:
    - "repo seo"
  topics:
    - "seo"
    - "github"
    - "developer-tools"
    - "metadata"
    - "open-source"
  social_image_set: true
"""
            for value in ["null", "true", "123", "1.5", "[repo, seo]", "{foo: bar}", "[repo, {foo: bar}]", "{foo: [repo, seo]}", "123 # note", "!!int 123", "&value 123", "*numeric", "repo *numeric"]:
                with self.subTest(string=value):
                    project_yaml.write_text(
                        "discoverability:\n"
                        + f'  description: "A {value} helper"\n  primary_keyword: "{value}"\n'
                        + f'  homepage_url: {fields["homepage_url"]}\n'
                        + tail,
                        encoding="utf-8",
                    )
                    result = self.run_script("--root", str(root), "--project-yaml", str(project_yaml), "--json")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload["errors"], [])
                    self.assertEqual(payload["shipwise"]["discoverability"]["primary_keyword"], value)
                    self.assertEqual(payload["shipwise"]["discoverability"]["description"], f"A {value} helper")
            for description, keyword, expected in [
                ('"A repo # seo helper" # note', '"repo # seo" # note', "A repo # seo helper"),
                ("'A repo # seo helper' # note", "'repo # seo' # note", "A repo # seo helper"),
                ('&text "A repo seo helper" # note', '&keyword "repo seo" # note', "A repo seo helper"),
                ("!!str 123 # note", "!!str 123 # note", "123"),
                ('!!str &text "A repo seo helper"', '&keyword !!str "repo seo"', "A repo seo helper"),
                ("!<tag:yaml.org,2002:str> 123", "!<tag:yaml.org,2002:str> 123", "123"),
                ("! 123", "! 123", "123"),
                ('"A repo seo helper"', '"repo seo"', "A repo seo helper"),
                ("'A repo''s seo helper'", '"repo\'s seo"', "A repo's seo helper"),
                ('"A repo\'s seo helper"', "'repo''s seo'", "A repo's seo helper"),
                ("&text !!str 'A repo''s seo helper' # note", "!!str &keyword 'repo''s seo' # note", "A repo's seo helper"),
                ("'A repo''''s seo helper'", '"repo\'\'s seo"', "A repo''s seo helper"),
                (r"'A repo\n seo helper'", r"'repo\n seo'", r"A repo\n seo helper"),
                ("'A *numeric helper' # note", "'*numeric' # note", "A *numeric helper"),
            ]:
                with self.subTest(description=description, keyword=keyword):
                    project_yaml.write_text(
                        "discoverability:\n"
                        + f"  description: {description}\n  primary_keyword: {keyword}\n"
                        + '  homepage_url: &homepage "https://example.com" # note\n'
                        + tail,
                        encoding="utf-8",
                    )
                    result = self.run_script("--root", str(root), "--project-yaml", str(project_yaml), "--json")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload["errors"], [])
                    self.assertEqual(payload["shipwise"]["discoverability"]["description"], expected)
                    self.assertEqual(payload["shipwise"]["discoverability"]["primary_keyword"], expected.removeprefix("A ").removesuffix(" helper"))
                    self.assertEqual(payload["shipwise"]["discoverability"]["homepage_url"], "https://example.com")
            for field in fields:
                for missing in [True, False]:
                    with self.subTest(field=field, missing=missing):
                        values = {**fields, field: '\"\"'}
                        if missing:
                            del values[field]
                        project_yaml.write_text(
                            "discoverability:\n"
                            + "".join(f"  {key}: {value}\n" for key, value in values.items())
                            + tail,
                            encoding="utf-8",
                        )
                        result = self.run_script(
                            "--root", str(root), "--project-yaml", str(project_yaml), "--json"
                        )
                        self.assertEqual(result.returncode, 1, result.stderr)
                        check = json.loads(result.stdout)["shipwise"]["checks"][field]
                        self.assertEqual(check["reason"], f"missing discoverability.{field}")

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
        shared = public_http_mod(module)
        private_answer = [
            (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]
        with (
            mock.patch.object(shared.socket, "getaddrinfo", return_value=private_answer),
            mock.patch.object(shared, "connect_endpoint") as connect_endpoint,
        ):
            result = module.http_check("http://audit-target.example")

        self.assertEqual(result["status"], "error")
        self.assertIn("non-public", result["reason"])
        connect_endpoint.assert_not_called()

        public_answer = [
            (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        client, server = shared.socket.socketpair()
        server.sendall(
            b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n"
            b"Location: http://metadata.example/latest\r\n\r\n"
        )
        try:
            with (
                mock.patch.object(
                    shared.socket, "getaddrinfo", side_effect=[public_answer, private_answer]
                ) as getaddrinfo,
                mock.patch.object(shared, "connect_endpoint", return_value=client) as connect_endpoint,
                mock.patch.object(shared, "select_proxy", return_value=None),
            ):
                result = module.http_check("http://public.example/start")
        finally:
            server.close()

        self.assertEqual(result["status"], "error")
        self.assertIn("redirect blocked", result["reason"])
        self.assertEqual(getaddrinfo.call_count, 2)
        connect_endpoint.assert_called_once_with(public_answer[0], 15)

    def test_public_url_validation_covers_credentials_ports_dns_and_redirects(self) -> None:
        module = load_script("repo_seo_baseline.py")
        shared = public_http_mod(module)
        public_answer = [
            (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        with mock.patch.object(shared.socket, "getaddrinfo", return_value=public_answer):
            parsed, endpoints = module.validate_public_http_url("https://example.com")
        self.assertEqual(parsed.hostname, "example.com")
        self.assertEqual(endpoints, public_answer)

        invalid_urls = [
            "file:///tmp/local",
            "https://user:pass@example.com/",
            "https://example.com:not-a-port/",
            "http://example.com:0/",
        ]
        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                module.validate_public_http_url(url)

        with mock.patch.object(
            shared.socket, "getaddrinfo", side_effect=shared.socket.gaierror("dns down")
        ), self.assertRaisesRegex(ValueError, "resolution failed"):
            module.validate_public_http_url("https://unresolved.example")
        with mock.patch.object(shared.socket, "getaddrinfo", return_value=[]), self.assertRaisesRegex(
            ValueError, "no addresses"
        ):
            module.validate_public_http_url("https://empty.example")

    def test_request_uses_the_validated_endpoint_without_resolving_again(self) -> None:
        module = load_script("repo_seo_baseline.py")
        shared = public_http_mod(module)
        public_answer = [
            (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        client, server = shared.socket.socketpair()
        server.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: text/plain\r\n\r\nok"
        )
        try:
            with (
                mock.patch.object(
                    shared.socket, "getaddrinfo", return_value=public_answer
                ) as getaddrinfo,
                mock.patch.object(shared, "connect_endpoint", return_value=client) as connect_endpoint,
                mock.patch.object(shared, "select_proxy", return_value=None),
            ):
                response = module.request_public_url_once("http://rebind.example/path?q=1", 9)
        finally:
            server.close()

        self.assertEqual(response["sample_bytes"], 2)
        self.assertEqual(response["content_type"], "text/plain")
        getaddrinfo.assert_called_once()
        connect_endpoint.assert_called_once_with(public_answer[0], 9)

    def test_endpoint_connector_closes_failed_sockets(self) -> None:
        module = load_script("repo_seo_baseline.py")
        shared = public_http_mod(module)
        endpoint = (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        sock = mock.Mock()
        with mock.patch.object(shared.socket, "socket", return_value=sock):
            connected = module.connect_endpoint(endpoint, 4)
        self.assertIs(connected, sock)
        sock.settimeout.assert_called_once_with(4)
        sock.connect.assert_called_once_with(endpoint[4])

        failed_sock = mock.Mock()
        failed_sock.connect.side_effect = OSError("denied")
        with (
            mock.patch.object(shared.socket, "socket", return_value=failed_sock),
            self.assertRaisesRegex(OSError, "denied"),
        ):
            module.connect_endpoint(endpoint, 4)
        failed_sock.close.assert_called_once()

    def test_https_connection_preserves_hostname_for_sni_and_certificate_checks(self) -> None:
        module = load_script("repo_seo_baseline.py")
        shared = public_http_mod(module)
        endpoint = (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        context = mock.Mock()
        raw_socket = mock.Mock()
        wrapped_socket = mock.Mock()
        context.wrap_socket.return_value = wrapped_socket

        with (
            mock.patch.object(shared.ssl, "create_default_context", return_value=context),
            mock.patch.object(shared, "connect_endpoint", return_value=raw_socket),
        ):
            connection = module.PinnedHTTPSConnection("example.com", 443, endpoint, 7)
            connection.connect()

        context.set_alpn_protocols.assert_called_once_with(["http/1.1"])
        context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="example.com")
        self.assertIs(connection.sock, wrapped_socket)

        context.wrap_socket.side_effect = shared.ssl.SSLError("certificate failed")
        with (
            mock.patch.object(shared.ssl, "create_default_context", return_value=context),
            mock.patch.object(shared, "connect_endpoint", return_value=raw_socket),
            self.assertRaisesRegex(shared.ssl.SSLError, "certificate failed"),
        ):
            module.PinnedHTTPSConnection("example.com", 443, endpoint, 7).connect()
        raw_socket.close.assert_called_once()

    def test_request_reports_failure_when_all_pinned_endpoints_fail(self) -> None:
        module = load_script("repo_seo_baseline.py")
        shared = public_http_mod(module)
        public_answer = [
            (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        connection = mock.Mock()
        connection.request.side_effect = TimeoutError("timed out")
        with (
            mock.patch.object(shared.socket, "getaddrinfo", return_value=public_answer),
            mock.patch.object(shared, "PinnedHTTPConnection", return_value=connection),
            mock.patch.object(shared, "select_proxy", return_value=None),
            self.assertRaisesRegex(OSError, "timed out"),
        ):
            module.request_public_url_once("http://example.com", 3)
        connection.close.assert_called_once()

    def test_http_check_surfaces_status_redirect_and_transport_errors(self) -> None:
        module = load_script("repo_seo_baseline.py")
        shared = public_http_mod(module)
        cases = [
            (
                {"http_status": 404, "location": None, "content_type": None, "sample_bytes": 0, "body": b""},
                "HTTP status 404",
            ),
            (
                {"http_status": 302, "location": None, "content_type": None, "sample_bytes": 0, "body": b""},
                "missing Location",
            ),
        ]
        for response, expected_reason in cases:
            with (
                self.subTest(expected_reason=expected_reason),
                mock.patch.object(shared, "request_public_url_once", return_value=response),
            ):
                result = module.http_check("https://example.com")
            self.assertEqual(result["status"], "error")
            self.assertIn(expected_reason, result["reason"])

        with mock.patch.object(shared, "request_public_url_once", side_effect=OSError("offline")):
            result = module.http_check("https://example.com")
        self.assertEqual(result["status"], "error")
        self.assertIn("offline", result["reason"])

        redirect = {
            "http_status": 302,
            "location": "/again",
            "content_type": None,
            "sample_bytes": 0,
            "body": b"",
        }
        with mock.patch.object(shared, "request_public_url_once", return_value=redirect) as request_once:
            result = module.http_check("https://example.com")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "too many redirects")
        self.assertEqual(request_once.call_count, 6)

        success_response = {
            "http_status": 200,
            "location": None,
            "content_type": "text/html",
            "sample_bytes": 2,
            "body": b"ok",
        }
        with mock.patch.object(shared, "request_public_url_once", return_value=success_response):
            result = module.http_check("https://example.com")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["sample_bytes"], 2)

        for status in (300, 304):
            unfollowed = {
                "http_status": status,
                "location": None,
                "content_type": None,
                "sample_bytes": 0,
                "body": b"",
            }
            with (
                self.subTest(status=status),
                mock.patch.object(shared, "request_public_url_once", return_value=unfollowed),
            ):
                result = module.http_check("https://example.com")
            self.assertEqual(result["status"], "error")
            self.assertIn(f"HTTP status {status}", result["reason"])

    def test_request_preserves_semicolon_path_parameters(self) -> None:
        module = load_script("public_http.py")
        public_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        connection = mock.Mock()
        response = mock.Mock()
        response.status = 200
        response.read.return_value = b"ok"
        response.getheader.side_effect = lambda name: {
            "content-type": "text/plain",
            "location": None,
        }.get(name)
        connection.getresponse.return_value = response
        with (
            mock.patch.object(module.socket, "getaddrinfo", return_value=public_answer),
            mock.patch.object(module, "PinnedHTTPConnection", return_value=connection),
            mock.patch.object(module, "select_proxy", return_value=None),
        ):
            module.request_public_url_once("http://example.com/page;variant=mobile?q=1", 5)
        connection.request.assert_called_once_with(
            "GET",
            "/page;variant=mobile?q=1",
            headers={"User-Agent": "github-repo-seo-skill/1.0"},
        )
        connection.close.assert_called_once()

    def test_charset_from_content_type_parses_quoted_parameters(self) -> None:
        module = load_script("public_http.py")
        cases = [
            ("text/html; charset=utf-8", "utf-8"),
            ("text/html; charset = utf-8", "utf-8"),
            ("text/html; charset = shift_jis", "shift_jis"),
            ('text/html; foo="x;charset=bogus"; charset=iso-8859-1', "iso-8859-1"),
            ('text/html; charset="utf-8"', "utf-8"),
            ("text/html; charset=not-a-codec", None),
            (None, None),
            ("", None),
        ]
        for header, expected in cases:
            with self.subTest(header=header):
                self.assertEqual(module.charset_from_content_type(header), expected)

    def test_request_uses_http_proxy_when_configured(self) -> None:
        module = load_script("public_http.py")
        public_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        proxy = module.urllib.parse.urlparse("http://proxy.example:8080")
        connection = mock.Mock()
        response = mock.Mock()
        response.status = 200
        response.read.return_value = b"ok"
        response.getheader.side_effect = lambda name: {
            "content-type": "text/plain",
            "location": None,
        }.get(name)
        connection.getresponse.return_value = response
        with (
            mock.patch.object(module.socket, "getaddrinfo", return_value=public_answer),
            mock.patch.object(module, "select_proxy", return_value=proxy),
            mock.patch.object(module, "ProxyPinnedHTTPConnection", return_value=connection) as proxy_http,
            mock.patch.object(module, "PinnedHTTPConnection") as pinned,
        ):
            result = module.request_public_url_once("http://example.com/page;variant?q=1", 5)
        proxy_http.assert_called_once_with(
            "proxy.example",
            8080,
            endpoint_ip="93.184.216.34",
            target_port=80,
            timeout=5,
            tunnel_headers=None,
        )
        pinned.assert_not_called()
        connection.request.assert_called_once_with(
            "GET",
            "/page;variant?q=1",
            headers={"User-Agent": "github-repo-seo-skill/1.0", "Host": "example.com"},
        )
        self.assertEqual(result["http_status"], 200)
        connection.close.assert_called_once()

    def test_https_proxy_connect_uses_validated_endpoint_ip(self) -> None:
        module = load_script("public_http.py")
        public_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        proxy = module.urllib.parse.urlparse("http://proxy.example:8080")
        connection = mock.Mock()
        response = mock.Mock()
        response.status = 200
        response.read.return_value = b"ok"
        response.getheader.side_effect = lambda name: {
            "content-type": "text/plain",
            "location": None,
        }.get(name)
        connection.getresponse.return_value = response
        with (
            mock.patch.object(module.socket, "getaddrinfo", return_value=public_answer),
            mock.patch.object(module, "select_proxy", return_value=proxy),
            mock.patch.object(module, "ProxyPinnedHTTPSConnection", return_value=connection) as proxy_https,
            mock.patch.object(module, "PinnedHTTPSConnection") as pinned,
        ):
            result = module.request_public_url_once("https://example.com/secure", 5)
        proxy_https.assert_called_once_with(
            "proxy.example",
            8080,
            server_hostname="example.com",
            endpoint_ip="93.184.216.34",
            target_port=443,
            timeout=5,
            tunnel_headers=None,
        )
        pinned.assert_not_called()
        connection.request.assert_called_once_with(
            "GET",
            "/secure",
            headers={"User-Agent": "github-repo-seo-skill/1.0", "Host": "example.com"},
        )
        self.assertEqual(result["http_status"], 200)
        connection.close.assert_called_once()

    def test_unsupported_proxy_errors_redact_credentials(self) -> None:
        module = load_script("public_http.py")
        parsed = module.urllib.parse.urlparse("https://example.com")
        with mock.patch.object(
            module.urllib.request,
            "getproxies",
            return_value={"https": "socks5://user:secret@proxy.example:1080"},
        ), mock.patch.object(module.urllib.request, "proxy_bypass", return_value=False):
            with self.assertRaises(OSError) as raised:
                module.select_proxy(parsed)
        message = str(raised.exception)
        self.assertIn("unsupported proxy URL: socks5://proxy.example:1080", message)
        self.assertNotIn("user", message)
        self.assertNotIn("secret", message)
        self.assertEqual(
            module.redact_proxy_url("socks5://user:secret@proxy.example:1080"),
            "socks5://proxy.example:1080",
        )

    def test_select_proxy_rejects_https_proxy_scheme(self) -> None:
        """https:// proxies must fail at selection, matching request_via_proxy."""
        module = load_script("public_http.py")
        parsed = module.urllib.parse.urlparse("https://example.com")
        with mock.patch.object(
            module.urllib.request,
            "getproxies",
            return_value={"https": "https://user:secret@proxy.example:8443"},
        ), mock.patch.object(module.urllib.request, "proxy_bypass", return_value=False):
            with self.assertRaises(OSError) as raised:
                module.select_proxy(parsed)
        message = str(raised.exception)
        self.assertIn("http:// proxy for CONNECT tunneling", message)
        self.assertIn("https://proxy.example:8443", message)
        self.assertNotIn("user", message)
        self.assertNotIn("secret", message)

    def test_select_proxy_accepts_authority_form_env_values(self) -> None:
        module = load_script("public_http.py")
        parsed = module.urllib.parse.urlparse("https://example.com")
        with mock.patch.object(
            module.urllib.request,
            "getproxies",
            return_value={"https": "proxy.example:8080"},
        ), mock.patch.object(module.urllib.request, "proxy_bypass", return_value=False):
            proxy = module.select_proxy(parsed)
        self.assertIsNotNone(proxy)
        assert proxy is not None
        self.assertEqual(proxy.scheme, "http")
        self.assertEqual(proxy.hostname, "proxy.example")
        self.assertEqual(proxy.port, 8080)

    def test_select_proxy_does_not_fall_http_proxy_onto_https(self) -> None:
        module = load_script("public_http.py")
        parsed = module.urllib.parse.urlparse("https://example.com")
        with mock.patch.object(
            module.urllib.request,
            "getproxies",
            return_value={"http": "http://proxy.example:8080"},
        ), mock.patch.object(module.urllib.request, "proxy_bypass", return_value=False):
            self.assertIsNone(module.select_proxy(parsed))

    def test_select_proxy_uses_all_proxy_for_https(self) -> None:
        module = load_script("public_http.py")
        parsed = module.urllib.parse.urlparse("https://example.com")
        with mock.patch.object(
            module.urllib.request,
            "getproxies",
            return_value={"all": "http://proxy.example:8080"},
        ), mock.patch.object(module.urllib.request, "proxy_bypass", return_value=False):
            proxy = module.select_proxy(parsed)
        self.assertIsNotNone(proxy)
        assert proxy is not None
        self.assertEqual(proxy.hostname, "proxy.example")

    def test_proxy_bypass_host_brackets_ipv6(self) -> None:
        module = load_script("public_http.py")
        parsed = module.urllib.parse.urlparse("https://[2606:4700:4700::1111]:8443/")
        self.assertEqual(
            module._proxy_bypass_host(parsed),
            "[2606:4700:4700::1111]:8443",
        )
        with mock.patch.object(
            module.urllib.request,
            "proxy_bypass",
            return_value=True,
        ) as bypass, mock.patch.object(module.urllib.request, "getproxies") as getproxies:
            self.assertIsNone(module.select_proxy(parsed))
        bypass.assert_called_once_with("[2606:4700:4700::1111]:8443")
        getproxies.assert_not_called()

    def test_redact_url_tolerates_malformed_ports(self) -> None:
        module = load_script("public_http.py")
        self.assertEqual(
            module.redact_url("https://user:secret@example.com:notaport/"),
            "https://example.com:notaport/",
        )

    def test_redact_url_tolerates_malformed_bracketed_authority(self) -> None:
        module = load_script("public_http.py")
        self.assertEqual(
            module.redact_url("https://user:secret@[bad/"),
            "https://[bad/",
        )

    def test_follow_public_http_malformed_bracket_returns_structured_error(self) -> None:
        module = load_script("public_http.py")
        result = module.follow_public_http("https://user:secret@[bad/")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("user", result["url"])
        self.assertNotIn("secret", result["url"])
        self.assertTrue(result.get("reason"))

    def test_follow_public_http_redacts_malformed_port_redirect_without_traceback(self) -> None:
        module = load_script("public_http.py")
        redirect = {
            "http_status": 302,
            "location": "https://user:secret@example.com:notaport/",
            "content_type": None,
            "sample_bytes": 0,
            "body": b"",
        }
        with mock.patch.object(
            module,
            "request_public_url_once",
            side_effect=[redirect, ValueError("invalid URL port")],
        ):
            result = module.follow_public_http("https://example.com/start")
        self.assertEqual(result["status"], "error")
        self.assertIn("redirect blocked", result["reason"])
        self.assertEqual(result["url"], "https://example.com:notaport/")
        self.assertNotIn("user", result["url"])
        self.assertNotIn("secret", result["url"])

    def test_http_host_header_encodes_idna_and_brackets_ipv6(self) -> None:
        module = load_script("public_http.py")
        idna_host = "例え.テスト"
        idna_parsed = module.urllib.parse.urlparse(f"https://{idna_host}/path")
        expected_idna = idna_host.encode("idna").decode("ascii")
        self.assertEqual(module._http_host_header(idna_parsed, 443), expected_idna)
        ipv6_parsed = module.urllib.parse.urlparse("https://[2606:4700:4700::1111]/")
        self.assertEqual(
            module._http_host_header(ipv6_parsed, 443),
            "[2606:4700:4700::1111]",
        )
        # Explicit Host values must be Latin-1 encodable for http.client.
        module._http_host_header(idna_parsed, 443).encode("latin-1")

    def test_proxy_https_tunnel_brackets_ipv6_host_header(self) -> None:
        module = load_script("public_http.py")
        context = mock.Mock()
        with (
            mock.patch.object(module.ssl, "create_default_context", return_value=context),
            mock.patch.object(module.http.client.HTTPSConnection, "__init__", return_value=None),
            mock.patch.object(module.http.client.HTTPSConnection, "set_tunnel") as set_tunnel,
        ):
            module.ProxyPinnedHTTPSConnection(
                "proxy.example",
                8080,
                server_hostname="example.com",
                endpoint_ip="2606:4700:4700::1111",
                target_port=443,
                timeout=5,
                tunnel_headers={"Proxy-Authorization": "Basic abc"},
            )
        set_tunnel.assert_called_once_with(
            "[2606:4700:4700::1111]",
            443,
            headers={
                "Proxy-Authorization": "Basic abc",
                "Host": "[2606:4700:4700::1111]:443",
            },
        )

    def test_follow_public_http_redacts_credentials_on_blocked_redirect(self) -> None:
        module = load_script("public_http.py")
        redirect = {
            "http_status": 302,
            "location": "https://oauth:tokensecret@evil.example/callback",
            "content_type": None,
            "sample_bytes": 0,
            "body": b"",
        }
        with mock.patch.object(
            module,
            "request_public_url_once",
            side_effect=[redirect, ValueError("URL credentials are not allowed")],
        ):
            result = module.follow_public_http("https://example.com/start")
        self.assertEqual(result["status"], "error")
        self.assertIn("redirect blocked", result["reason"])
        self.assertEqual(result["url"], "https://evil.example/callback")
        self.assertNotIn("oauth", result["url"])
        self.assertNotIn("tokensecret", result["url"])
        self.assertNotIn("tokensecret", result["reason"])

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


class OriginResourceTests(unittest.TestCase):
    @contextmanager
    def http_site(self, routes):
        paths = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                status, content_type, body = routes.get(
                    self.path, (200, "text/html", "<html><title>Not found</title></html>")
                )
                payload = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://crawl.example:{server.server_port}", paths, server.server_port
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def run_audit(self, name, homepage, port):
        module = load_script(name)
        shared = public_http_mod(module)
        public_answer = [
            (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ]

        def connect_local(endpoint, timeout):
            connection = shared.socket.socket(endpoint[0], endpoint[1], endpoint[2])
            connection.settimeout(timeout)
            connection.connect(("127.0.0.1", port))
            return connection

        with tempfile.TemporaryDirectory() as root:
            args = [name, homepage, "--json"] if name == "site_meta_audit.py" else [
                name, "--root", root, "--homepage", homepage, "--json"
            ]
            stdout = io.StringIO()
            with (
                mock.patch.object(shared.socket, "getaddrinfo", return_value=public_answer),
                mock.patch.object(shared, "connect_endpoint", side_effect=connect_local),
                mock.patch.object(shared, "select_proxy", return_value=None),
                mock.patch.object(sys, "argv", args),
                mock.patch.object(sys, "stdout", stdout),
            ):
                if name == "repo_seo_baseline.py":
                    with mock.patch.object(module, "run_cmd", return_value={"status": "ok"}):
                        code = module.main()
                else:
                    code = module.main()
            return code, json.loads(stdout.getvalue())

    def test_sitemap_presence_requires_a_parsed_sitemap_root(self):
        namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
        bodies = (
            (f'<sm:urlset xmlns:sm="{namespace}"><sm:url><sm:loc>https://example.com/</sm:loc></sm:url></sm:urlset>', True),
            (f'<sm:sitemapindex xmlns:sm="{namespace}"/>', True),
            (f'<?xml version="1.0"?>' + "<!-- preamble -->" * 80 + f'<urlset xmlns="{namespace}"/>', True),
            ("not XML, but mentions <urlset></urlset>", False),
            ("<urlset><url></urlset>", False),
            ("<urlset>", False),
            ("<urlset><url>", False),
            ("<error><urlset/></error>", False),
            ("<!-- <urlset/> --><error/>", False),
            ("<urlset_fake/>", False),
        )
        for body, present in bodies:
            for name in ("repo_seo_baseline.py", "site_meta_audit.py"):
                routes = {
                    "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow:\n"),
                    "/sitemap.xml": (200, "application/xml", body),
                }
                with self.subTest(body=body[:80], script=name), self.http_site(routes) as (origin, paths, port):
                    code, payload = self.run_audit(name, origin, port)
                    if name == "repo_seo_baseline.py":
                        self.assertEqual(code, 0 if present else 1)
                        item = payload["site"][origin]["sitemap"]
                        self.assertEqual(item["status"], "ok" if present else "error")
                        self.assertEqual(payload["status"], "ok" if present else "error")
                        self.assertEqual({error["resource"] for error in payload["errors"]}, set() if present else {"sitemap"})
                    else:
                        self.assertEqual(code, 0)
                        self.assertEqual(payload["checks"]["has_sitemap_xml"], present)
                        item = payload["checks"]["sitemap_xml"][0]
                    self.assertEqual(item["present"], present)
                    self.assertNotIn("body", item)
                    if not present:
                        self.assertTrue(item["reason"])
                    self.assertEqual(paths, ["/", "/robots.txt", "/sitemap.xml"])

    def test_large_sitemap_sample_passes_both_audits(self):
        namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
        for root, child in (("urlset", "url"), ("sitemapindex", "sitemap")):
            entry = f"<sm:{child}><sm:loc>https://example.com/page</sm:loc></sm:{child}>"
            body = f'<sm:{root} xmlns:sm="{namespace}">' + entry * 18000 + f"</sm:{root}>"
            self.assertGreater(len(body.encode("utf-8")), 1_000_000)
            routes = {
                "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow:\n"),
                "/sitemap.xml": (200, "application/xml", body),
            }
            for name in ("repo_seo_baseline.py", "site_meta_audit.py"):
                with self.subTest(root=root, script=name), self.http_site(routes) as (origin, paths, port):
                    code, payload = self.run_audit(name, origin, port)
                    self.assertEqual(code, 0)
                    if name == "repo_seo_baseline.py":
                        item = payload["site"][origin]["sitemap"]
                        self.assertEqual(item["status"], "ok")
                        self.assertEqual(payload["errors"], [])
                    else:
                        self.assertTrue(payload["checks"]["has_sitemap_xml"])
                        item = payload["checks"]["sitemap_xml"][0]
                    self.assertTrue(item["present"])
                    self.assertNotIn("body", item)
                    self.assertEqual(paths, ["/", "/robots.txt", "/sitemap.xml"])

    def test_sitemap_byte_limit_distinguishes_eof_from_truncation(self):
        for size, closing, present in (
            (999_999, "</urlset>", True),
            (1_000_000, "</urlset>", True),
            (1_000_001, "</urlset>", True),
            (1_000_000, "", False),
        ):
            body = "<urlset>" + " " * (size - len("<urlset>" + closing)) + closing
            routes = {
                "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow:\n"),
                "/sitemap.xml": (200, "application/xml", body),
            }
            for name in ("repo_seo_baseline.py", "site_meta_audit.py"):
                with self.subTest(size=size, present=present, script=name), self.http_site(routes) as (origin, paths, port):
                    code, payload = self.run_audit(name, origin, port)
                    if name == "repo_seo_baseline.py":
                        self.assertEqual(code, 0 if present else 1)
                        item = payload["site"][origin]["sitemap"]
                    else:
                        self.assertEqual(code, 0)
                        self.assertEqual(payload["checks"]["has_sitemap_xml"], present)
                        item = payload["checks"]["sitemap_xml"][0]
                    self.assertEqual(item["present"], present)
                    self.assertEqual(item["body_truncated"], size > 1_000_000)
                    self.assertNotIn("body", item)
                    self.assertEqual(paths, ["/", "/robots.txt", "/sitemap.xml"])

    def test_document_homepage_finds_sibling_sitemap(self):
        routes = {
            "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow:\n"),
            "/sitemap.xml": (404, "text/plain", "missing"),
            "/docs/sitemap.xml": (200, "application/xml", "<urlset/>"),
        }
        for path in ("/docs/index.html", "/docs/start"):
            for name in ("repo_seo_baseline.py", "site_meta_audit.py"):
                with self.subTest(path=path, script=name), self.http_site(routes) as (origin, paths, port):
                    code, payload = self.run_audit(name, origin + path, port)
                    self.assertEqual(code, 0)
                    if name == "repo_seo_baseline.py":
                        item = payload["site"][origin + path]["sitemap"]
                        self.assertEqual(item["status"], "ok")
                        self.assertEqual(payload["errors"], [])
                    else:
                        self.assertTrue(payload["checks"]["has_sitemap_xml"])
                        item = next(item for item in payload["checks"]["sitemap_xml"] if item["present"])
                    self.assertEqual(item["url"], origin + "/docs/sitemap.xml")
                    self.assertEqual(paths, [path, "/robots.txt", "/sitemap.xml", "/docs/sitemap.xml", path + "/sitemap.xml"])

    def test_project_sitemap_can_succeed_after_an_invalid_origin_candidate(self):
        for path in ("/project/", "/project"):
            for root_sitemap in (
                (404, "text/plain", "missing"),
                (200, "text/html", "<html>missing</html>"),
                (200, "application/xml", "<error/>"),
            ):
                for name in ("repo_seo_baseline.py", "site_meta_audit.py"):
                    routes = {
                        "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow:\n"),
                        "/sitemap.xml": root_sitemap,
                        "/project/sitemap.xml": (200, "application/xml", "<urlset/>"),
                    }
                    with self.subTest(path=path, root_sitemap=root_sitemap, script=name), self.http_site(routes) as (origin, paths, port):
                        code, payload = self.run_audit(name, origin + path, port)
                        self.assertEqual(code, 0)
                        if name == "repo_seo_baseline.py":
                            item = payload["site"][origin + path.rstrip("/")]["sitemap"]
                            self.assertEqual(payload["errors"], [])
                            self.assertEqual(item["status"], "ok")
                        else:
                            self.assertTrue(payload["checks"]["has_sitemap_xml"])
                            first, item = payload["checks"]["sitemap_xml"]
                            self.assertFalse(first["present"])
                        self.assertTrue(item["present"])
                        self.assertEqual(item["url"], origin + "/project/sitemap.xml")
                        expected_page = path.rstrip("/") if name == "repo_seo_baseline.py" else path
                        self.assertEqual(paths, [expected_page, "/robots.txt", "/sitemap.xml", "/project/sitemap.xml"])

    def test_docs_sitemap_is_valid_but_docs_robots_cannot_replace_origin_robots(self):
        routes = {
            "/robots.txt": (404, "text/plain", "missing"),
            "/sitemap.xml": (404, "text/plain", "missing"),
            "/docs/robots.txt": (200, "text/plain", "User-agent: *\nDisallow:\n"),
            "/docs/sitemap.xml": (200, "application/xml", "<urlset></urlset>"),
        }
        for name in ("repo_seo_baseline.py", "site_meta_audit.py"):
            with self.subTest(script=name), self.http_site(routes) as (origin, paths, port):
                code, payload = self.run_audit(name, origin + "/docs/", port)
                if name == "repo_seo_baseline.py":
                    self.assertEqual(code, 0)
                    self.assertEqual(payload["errors"], [])
                    robots = payload["site"][origin + "/docs"]["robots"]
                    self.assertFalse(robots["present"])
                    self.assertEqual(robots["http_status"], 404)
                    self.assertEqual(robots["observation"], "not_configured")
                    self.assertEqual(robots["url"], origin + "/robots.txt")
                    self.assertEqual(payload["site"][origin + "/docs"]["sitemap"]["url"], origin + "/docs/sitemap.xml")
                else:
                    self.assertEqual(code, 0)  # Metadata CLI keeps its existing page-status exit contract.
                    self.assertFalse(payload["checks"]["has_robots_txt"])
                    self.assertTrue(payload["checks"]["has_sitemap_xml"])
                expected_page = "/docs" if name == "repo_seo_baseline.py" else "/docs/"
                self.assertEqual(paths, [expected_page, "/robots.txt", "/sitemap.xml", "/docs/sitemap.xml"])

    def test_origin_resources_pass_for_docs_and_pathless_homepages(self):
        routes = {
            "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow:\n"),
            "/sitemap.xml": (200, "application/xml", '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>'),
        }
        for name in ("repo_seo_baseline.py", "site_meta_audit.py"):
            for path in ("/docs/", ""):
                with self.subTest(script=name, path=path), self.http_site(routes) as (origin, paths, port):
                    code, payload = self.run_audit(name, origin + path, port)
                    self.assertEqual(code, 0)
                    if name == "repo_seo_baseline.py":
                        checks = payload["site"][origin + path.rstrip("/")]
                        self.assertEqual(checks["robots"]["status"], "ok")
                        self.assertEqual(checks["sitemap"]["status"], "ok")
                    else:
                        checks = payload["checks"]
                        self.assertTrue(checks["has_robots_txt"])
                        self.assertTrue(checks["has_sitemap_xml"])
                        self.assertEqual(len(checks["robots_txt"]), 1)
                        self.assertEqual(len(checks["sitemap_xml"]), 2 if path else 1)
                    expected_page = path.rstrip("/") or "/" if name == "repo_seo_baseline.py" else path or "/"
                    expected_paths = [expected_page, "/robots.txt", "/sitemap.xml"]
                    if path:
                        expected_paths.append("/docs/sitemap.xml")
                    self.assertEqual(paths, expected_paths)

    def test_soft_404_and_non_sitemap_xml_fail_baseline_gate(self):
        for robots, sitemap in (
            ((200, "text/html", "<html>missing</html>"), (200, "text/html", "<html>missing</html>")),
            ((200, "text/plain", "<html>missing</html>"), (200, "application/xml", "<error>missing</error>")),
            ((204, "text/plain", ""), (204, "application/xml", "")),
        ):
            routes = {"/robots.txt": robots, "/sitemap.xml": sitemap}
            with self.subTest(robots=robots, sitemap=sitemap), self.http_site(routes) as (origin, paths, port):
                code, payload = self.run_audit("repo_seo_baseline.py", origin, port)
                self.assertEqual(code, 1)
                checks = payload["site"][origin]
                for resource in ("robots", "sitemap"):
                    self.assertEqual(checks[resource]["status"], "error")
                    self.assertFalse(checks[resource]["present"])
                    self.assertTrue(checks[resource]["reason"])
                    self.assertNotIn("body", checks[resource])
                self.assertEqual({item["resource"] for item in payload["errors"]}, {"robots", "sitemap"})

    def test_resource_candidates_keep_authority_and_drop_query_and_fragment(self):
        module = load_script("site_meta_audit.py")
        for homepage, origin in (
            ("https://example.com", "https://example.com"),
            ("https://example.com/docs/page?lang=en#intro", "https://example.com"),
            ("http://example.com:8080/docs/", "http://example.com:8080"),
            ("https://[2606:4700:4700::1111]:8443/docs/", "https://[2606:4700:4700::1111]:8443"),
        ):
            for filename in ("robots.txt", "sitemap.xml"):
                with self.subTest(homepage=homepage, filename=filename):
                    expected = [origin + "/" + filename]
                    if filename == "sitemap.xml" and "/docs" in homepage:
                        path = "/docs/page" if "page?" in homepage else "/docs"
                        if "page?" in homepage:
                            expected.append(origin + "/docs/sitemap.xml")
                        expected.append(origin + path + "/sitemap.xml")
                    self.assertEqual(module.resource_candidates(homepage, filename), expected)

    def test_origin_resource_fetches_preserve_public_url_validation(self):
        for name in ("repo_seo_baseline.py", "site_meta_audit.py"):
            module = load_script(name)
            shared = public_http_mod(module)
            private_answer = [
                (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
            ]
            for homepage, reason in (
                ("http://private.example/docs/", "non-public"),
                ("http://dummy:dummy@public.example/docs/", "credentials"),
            ):
                with (
                    self.subTest(script=name, homepage=homepage),
                    mock.patch.object(shared.socket, "getaddrinfo", return_value=private_answer) as dns,
                    mock.patch.object(shared, "connect_endpoint") as connect,
                ):
                    items = module.site_resource_checks(homepage).values() if name == "repo_seo_baseline.py" else (
                        module.check_candidates(homepage, "robots.txt") + module.check_candidates(homepage, "sitemap.xml")
                    )
                    for item in items:
                        self.assertEqual(item["status"], "error")
                        self.assertIn(reason, item["reason"])
                        self.assertNotIn("body", item)
                    connect.assert_not_called()
                    if reason == "credentials":
                        dns.assert_not_called()


class RegistryPackageNameTests(unittest.TestCase):
    def audit(self, root: Path, *args: str):
        module = load_script("repo_seo_baseline.py")
        stdout = io.StringIO()
        def registry_response(url):
            name = url.rsplit("/", 1)[-1]
            return {"status": "ok", "url": url, "body": json.dumps({
                "crate": {"id": name, "max_version": "1.0.0"},
            })}
        with (
            mock.patch.object(sys, "argv", ["repo_seo_baseline.py", "--root", str(root), *args]),
            mock.patch.object(sys, "stdout", stdout),
            mock.patch.object(module, "run_cmd", return_value={"status": "ok"}) as run_cmd,
            mock.patch.object(module.public_http, "fetch_public_url", side_effect=registry_response) as fetch,
        ):
            code = module.main()
        self.registry_urls = [call.args[0] for call in fetch.call_args_list]
        return code, stdout.getvalue(), [call.args[0] for call in run_cmd.call_args_list]

    def test_manifest_flags_are_errors_and_never_reach_registry_commands(self) -> None:
        npm_flag = "--registry=http://127.0.0.1:9"
        cargo_flag = "--index=sparse+http://127.0.0.1:9/"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"demo"}', encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "package.json").write_text(json.dumps({"name": npm_flag}), encoding="utf-8")
            (root / "Cargo.toml").write_text(f'[package]\nname = "{cargo_flag}"\n', encoding="utf-8")

            code, output, commands = self.audit(root, "--json")

        self.assertNotIn(npm_flag, [arg for command in commands for arg in command])
        self.assertNotIn(cargo_flag, [arg for command in commands for arg in command])
        self.assertEqual(code, 1)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(set(payload["registry"]["npm"]), {"demo"})
        self.assertEqual(payload["registry"]["crates"], {})
        self.assertEqual(
            {error["path"] for error in payload["manifests"]["errors"]},
            {"nested/package.json", "Cargo.toml"},
        )
        self.assertTrue(all(error["surface"] == "manifest" for error in payload["errors"]))

    def test_invalid_manifest_name_types_and_syntax_fail_without_registry_calls(self) -> None:
        invalid_npm = [
            1, 0, True, False, None, ["demo"], {"name": "demo"}, "", " demo", "demo ",
            "demo\n", ".demo", "_demo", "demo@1", "https://example.com",
            "@scope/", "scope/demo", "@scope/demo/extra", "@scope/.foo", "@scope/..foo",
            "@scope/..", "démø", "a" * 215,
        ]
        invalid_cargo = [
            1, 0, True, False, ["demo"], {"name": "demo"}, "", " demo", "demo ", "demo\n",
            "-demo", "_demo", "1demo", "demo@1", "demo.crate", "démø", "a" * 65,
        ]
        for registry, names in (("npm", invalid_npm), ("cargo", invalid_cargo)):
            for name in names:
                with self.subTest(registry=registry, name=name), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    if registry == "npm":
                        path = "package.json"
                        (root / path).write_text(json.dumps({"name": name}), encoding="utf-8")
                    else:
                        path = "Cargo.toml"
                        value = '{name = "demo"}' if isinstance(name, dict) else json.dumps(name)
                        (root / path).write_text(f"[package]\nname = {value}\n", encoding="utf-8")
                    code, output, commands = self.audit(root, "--json")

                self.assertFalse(any(command[0] in {"npm", "cargo"} for command in commands))
                self.assertEqual(code, 1)
                payload = json.loads(output)
                self.assertEqual(payload["status"], "error")
                self.assertEqual(payload["manifests"]["errors"][0]["path"], path)
                self.assertEqual(payload["errors"][0]["surface"], "manifest")
                self.assertIn("package name", payload["errors"][0]["reason"])

    def test_invalid_cli_names_use_the_structured_error_gate(self) -> None:
        for flag, name in (
            ("--npm", "--registry=http://127.0.0.1:9"),
            ("--crate", "--index=sparse+http://127.0.0.1:9/"),
            ("--npm", "demo@1"),
            ("--npm", "@scope/.foo"),
            ("--crate", "demo.crate"),
            ("--npm", ""),
            ("--crate", ""),
        ):
            for output_mode in ([], ["--json"]):
                with self.subTest(flag=flag, name=name, mode=output_mode), tempfile.TemporaryDirectory() as tmp:
                    code, output, commands = self.audit(Path(tmp), f"{flag}={name}", *output_mode)
                self.assertFalse(any(command[0] in {"npm", "cargo"} for command in commands))
                self.assertEqual(code, 1)
                if output_mode:
                    payload = json.loads(output)
                    self.assertEqual(payload["status"], "error")
                    self.assertEqual(payload["manifests"]["errors"][0]["path"], flag)
                else:
                    self.assertIn("status: error", output)
                    self.assertIn("package name", output)

    def test_valid_names_are_deduplicated_and_passed_as_operands(self) -> None:
        npm_names = [
            "demo", "@scope/demo", "demo.js", "demo_name", "-foo", "--registry",
            "JSONStream", "214" + "a" * 211,
            "foo~bar", "foo'bar", "foo!bar", "foo(bar)", "foo*bar",
            "!foo", "~foo", "*foo", "(foo)", "'foo",
            "@scope/foo!bar", "@scope/~foo", "@scope/*", "@~scope/foo",
        ]
        cargo_names = ["demo-crate", "Demo_crate", "a" * 64]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"JSONStream"}', encoding="utf-8")
            (root / "Cargo.toml").write_text('[package]\nname = "demo-crate"\n', encoding="utf-8")
            args = [f"--npm={name}" for name in npm_names]
            args += [f"--crate={name}" for name in cargo_names]
            code, output, commands = self.audit(root, *args, "--json")

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["manifests"]["errors"], [])
        self.assertEqual(set(payload["registry"]["npm"]), set(npm_names))
        self.assertEqual(set(payload["registry"]["crates"]), set(cargo_names))
        self.assertEqual(
            [command for command in commands if command[0] == "npm"],
            [["npm", "view", "--json", "--registry", "https://registry.npmjs.org", "--", name] for name in npm_names],
        )
        self.assertEqual(
            self.registry_urls,
            ["https://crates.io/api/v1/crates/" + name for name in cargo_names],
        )
        self.assertFalse(any(command[0] == "cargo" for command in commands))
        for name in cargo_names:
            self.assertEqual(payload["registry"]["crates"][name]["name"], name)
            self.assertEqual(payload["registry"]["crates"][name]["published_version"], "1.0.0")

    def test_unnamed_npm_projects_and_cargo_workspaces_remain_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{}', encoding="utf-8")
            (root / "Cargo.toml").write_text('[workspace]\nmembers = []\n', encoding="utf-8")
            code, output, commands = self.audit(root, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["manifests"]["errors"], [])
        self.assertFalse(any(command[0] in {"npm", "cargo"} for command in commands))

    def test_invalid_names_preserve_metadata_and_homepage_audits(self) -> None:
        module = load_script("repo_seo_baseline.py")
        stdout = io.StringIO()
        npm_homepage = "https://npm-site.example"
        cargo_homepage = "https://cargo-site.example"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(json.dumps({
                "name": "--registry=http://127.0.0.1:9", "homepage": npm_homepage,
                "description": "npm metadata", "keywords": ["seo"],
            }), encoding="utf-8")
            (root / "Cargo.toml").write_text(
                '[package]\nname = "--index=sparse+http://127.0.0.1:9/"\n'
                f'homepage = "{cargo_homepage}"\ndescription = "cargo metadata"\n',
                encoding="utf-8",
            )
            with (
                mock.patch.object(sys, "argv", ["repo_seo_baseline.py", "--root", tmp, "--json"]),
                mock.patch.object(sys, "stdout", stdout),
                mock.patch.object(module, "run_cmd", return_value={"status": "ok"}) as run_cmd,
                mock.patch.object(module, "site_resource_checks", return_value={
                    "homepage": {"status": "ok"}, "robots": {"status": "ok"}, "sitemap": {"status": "ok"},
                }) as site_checks,
            ):
                code = module.main()

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(len(payload["manifests"]["npm"]), 1)
        self.assertEqual(payload["manifests"]["npm"][0]["description"], "npm metadata")
        self.assertEqual(payload["manifests"]["npm"][0]["keywords"], ["seo"])
        self.assertEqual(payload["manifests"]["cargo"]["description"], "cargo metadata")
        self.assertEqual(set(payload["site"]), {npm_homepage, cargo_homepage})
        self.assertEqual({call.args[0] for call in site_checks.call_args_list}, {npm_homepage, cargo_homepage})
        self.assertFalse(any(call.args[0][0] in {"npm", "cargo"} for call in run_cmd.call_args_list))
        self.assertEqual(len(payload["manifests"]["errors"]), 2)


class SiteMetaAuditTests(unittest.TestCase):
    def test_invalid_url_scheme_fails(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "site_meta_audit.py"), "file:///tmp/index.html", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["page"]["status"], "error")
        self.assertIn("unsupported URL scheme", payload["page"]["reason"])

    def test_text_mode_prints_reason_on_validation_failure(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "site_meta_audit.py"), "file:///tmp/index.html"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("reason: unsupported URL scheme", result.stdout)
        self.assertIn("status:", result.stdout)

    def test_json_malformed_bracket_authority_emits_structured_error(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "site_meta_audit.py"),
                "https://user:secret@[bad/",
                "--json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["page"]["status"], "error")
        self.assertNotIn("user", payload["url"])
        self.assertNotIn("secret", payload["url"])
        self.assertTrue(payload["page"].get("reason"))

    def test_json_dns_failure_emits_structured_error(self) -> None:
        """--json must keep stdout parseable when hostname resolution fails."""
        module = load_script("site_meta_audit.py")
        shared = public_http_mod(module)
        url = "https://unresolved.example/"
        stdout = io.StringIO()
        with (
            mock.patch.object(
                shared.socket,
                "getaddrinfo",
                side_effect=shared.socket.gaierror(-2, "Name or service not known"),
            ),
            mock.patch.object(sys, "argv", ["site_meta_audit.py", url, "--json"]),
            mock.patch.object(sys, "stdout", stdout),
        ):
            code = module.main()

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["url"], url)
        self.assertEqual(payload["page"]["status"], "error")
        self.assertIn("hostname resolution failed", payload["page"]["reason"])
        self.assertNotIn("usage:", stdout.getvalue().lower())

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

    def test_fetch_blocks_private_dns_before_connect(self) -> None:
        module = load_script("site_meta_audit.py")
        shared = public_http_mod(module)
        private_answer = [
            (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]
        with (
            mock.patch.object(shared.socket, "getaddrinfo", return_value=private_answer),
            mock.patch.object(shared, "connect_endpoint") as connect_endpoint,
        ):
            result = module.fetch("http://audit-target.example")

        self.assertEqual(result["status"], "error")
        self.assertIn("non-public", result["reason"])
        connect_endpoint.assert_not_called()

    def test_fetch_blocks_private_redirect_targets(self) -> None:
        module = load_script("site_meta_audit.py")
        shared = public_http_mod(module)
        private_answer = [
            (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]
        public_answer = [
            (shared.socket.AF_INET, shared.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        client, server = shared.socket.socketpair()
        server.sendall(
            b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n"
            b"Location: http://metadata.example/latest\r\n\r\n"
        )
        try:
            with (
                mock.patch.object(
                    shared.socket, "getaddrinfo", side_effect=[public_answer, private_answer]
                ) as getaddrinfo,
                mock.patch.object(shared, "connect_endpoint", return_value=client) as connect_endpoint,
                mock.patch.object(shared, "select_proxy", return_value=None),
            ):
                result = module.fetch("http://public.example/start")
        finally:
            server.close()

        self.assertEqual(result["status"], "error")
        self.assertIn("redirect blocked", result["reason"])
        self.assertEqual(getaddrinfo.call_count, 2)
        connect_endpoint.assert_called_once_with(public_answer[0], 20)

    def test_fetch_blocks_credentialed_urls(self) -> None:
        module = load_script("site_meta_audit.py")
        shared = public_http_mod(module)
        with mock.patch.object(shared, "connect_endpoint") as connect_endpoint:
            result = module.fetch("https://user:pass@example.com/")

        self.assertEqual(result["status"], "error")
        self.assertIn("credentials", result["reason"])
        connect_endpoint.assert_not_called()

    def test_cli_rejects_credentialed_urls(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "site_meta_audit.py"),
                "https://user:pass@example.com/",
                "--json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["page"]["status"], "error")
        self.assertIn("credentials", payload["page"]["reason"])
        self.assertEqual(payload["url"], "https://example.com/")
        self.assertEqual(payload["page"]["url"], "https://example.com/")
        # Credentials must not leak into JSON or stderr.
        self.assertNotIn("user:pass", result.stdout)
        self.assertNotIn("user:pass", result.stderr)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
