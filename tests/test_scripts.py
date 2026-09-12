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
        module = load_script("public_http.py")
        private_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]
        with (
            mock.patch.object(module.socket, "getaddrinfo", return_value=private_answer),
            mock.patch.object(module, "connect_endpoint") as connect_endpoint,
        ):
            result = module.http_check("http://audit-target.example")

        self.assertEqual(result["status"], "error")
        self.assertIn("non-public", result["reason"])
        connect_endpoint.assert_not_called()

        public_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        client, server = module.socket.socketpair()
        server.sendall(
            b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n"
            b"Location: http://metadata.example/latest\r\n\r\n"
        )
        try:
            with (
                mock.patch.object(
                    module.socket, "getaddrinfo", side_effect=[public_answer, private_answer]
                ) as getaddrinfo,
                mock.patch.object(module, "connect_endpoint", return_value=client) as connect_endpoint,
            ):
                result = module.http_check("http://public.example/start")
        finally:
            server.close()

        self.assertEqual(result["status"], "error")
        self.assertIn("redirect blocked", result["reason"])
        self.assertEqual(getaddrinfo.call_count, 2)
        connect_endpoint.assert_called_once_with(public_answer[0], 15)

    def test_public_url_validation_covers_credentials_ports_dns_and_redirects(self) -> None:
        module = load_script("public_http.py")
        public_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        with mock.patch.object(module.socket, "getaddrinfo", return_value=public_answer):
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
            module.socket, "getaddrinfo", side_effect=module.socket.gaierror("dns down")
        ), self.assertRaisesRegex(ValueError, "resolution failed"):
            module.validate_public_http_url("https://unresolved.example")
        with mock.patch.object(module.socket, "getaddrinfo", return_value=[]), self.assertRaisesRegex(
            ValueError, "no addresses"
        ):
            module.validate_public_http_url("https://empty.example")

    def test_request_uses_the_validated_endpoint_without_resolving_again(self) -> None:
        module = load_script("public_http.py")
        public_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        client, server = module.socket.socketpair()
        server.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: text/plain\r\n\r\nok"
        )
        try:
            with (
                mock.patch.object(
                    module.socket, "getaddrinfo", return_value=public_answer
                ) as getaddrinfo,
                mock.patch.object(module, "connect_endpoint", return_value=client) as connect_endpoint,
            ):
                response = module.request_public_url_once("http://rebind.example/path?q=1", 9)
        finally:
            server.close()

        self.assertEqual(response["sample_bytes"], 2)
        self.assertEqual(response["content_type"], "text/plain")
        getaddrinfo.assert_called_once()
        connect_endpoint.assert_called_once_with(public_answer[0], 9)

    def test_endpoint_connector_closes_failed_sockets(self) -> None:
        module = load_script("public_http.py")
        endpoint = (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        sock = mock.Mock()
        with mock.patch.object(module.socket, "socket", return_value=sock):
            connected = module.connect_endpoint(endpoint, 4)
        self.assertIs(connected, sock)
        sock.settimeout.assert_called_once_with(4)
        sock.connect.assert_called_once_with(endpoint[4])

        failed_sock = mock.Mock()
        failed_sock.connect.side_effect = OSError("denied")
        with (
            mock.patch.object(module.socket, "socket", return_value=failed_sock),
            self.assertRaisesRegex(OSError, "denied"),
        ):
            module.connect_endpoint(endpoint, 4)
        failed_sock.close.assert_called_once()

    def test_https_connection_preserves_hostname_for_sni_and_certificate_checks(self) -> None:
        module = load_script("public_http.py")
        endpoint = (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        context = mock.Mock()
        raw_socket = mock.Mock()
        wrapped_socket = mock.Mock()
        context.wrap_socket.return_value = wrapped_socket

        with (
            mock.patch.object(module.ssl, "create_default_context", return_value=context),
            mock.patch.object(module, "connect_endpoint", return_value=raw_socket),
        ):
            connection = module.PinnedHTTPSConnection("example.com", 443, endpoint, 7)
            connection.connect()

        context.set_alpn_protocols.assert_called_once_with(["http/1.1"])
        context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="example.com")
        self.assertIs(connection.sock, wrapped_socket)

        context.wrap_socket.side_effect = module.ssl.SSLError("certificate failed")
        with (
            mock.patch.object(module.ssl, "create_default_context", return_value=context),
            mock.patch.object(module, "connect_endpoint", return_value=raw_socket),
            self.assertRaisesRegex(module.ssl.SSLError, "certificate failed"),
        ):
            module.PinnedHTTPSConnection("example.com", 443, endpoint, 7).connect()
        raw_socket.close.assert_called_once()

    def test_request_reports_failure_when_all_pinned_endpoints_fail(self) -> None:
        module = load_script("public_http.py")
        public_answer = [
            (module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        connection = mock.Mock()
        connection.request.side_effect = TimeoutError("timed out")
        with (
            mock.patch.object(module.socket, "getaddrinfo", return_value=public_answer),
            mock.patch.object(module, "PinnedHTTPConnection", return_value=connection),
            self.assertRaisesRegex(OSError, "timed out"),
        ):
            module.request_public_url_once("http://example.com", 3)
        connection.close.assert_called_once()

    def test_http_check_surfaces_status_redirect_and_transport_errors(self) -> None:
        module = load_script("public_http.py")
        cases = [
            ({"http_status": 404, "location": None, "content_type": None, "sample_bytes": 0}, "HTTP status 404"),
            ({"http_status": 302, "location": None, "content_type": None, "sample_bytes": 0}, "missing Location"),
        ]
        for response, expected_reason in cases:
            with (
                self.subTest(expected_reason=expected_reason),
                mock.patch.object(module, "request_public_url_once", return_value=response),
            ):
                result = module.http_check("https://example.com")
            self.assertEqual(result["status"], "error")
            self.assertIn(expected_reason, result["reason"])

        with mock.patch.object(module, "request_public_url_once", side_effect=OSError("offline")):
            result = module.http_check("https://example.com")
        self.assertEqual(result["status"], "error")
        self.assertIn("offline", result["reason"])

        redirect = {"http_status": 302, "location": "/again", "content_type": None, "sample_bytes": 0}
        with mock.patch.object(module, "request_public_url_once", return_value=redirect) as request_once:
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
        with mock.patch.object(module, "request_public_url_once", return_value=success_response):
            result = module.http_check("https://example.com")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["sample_bytes"], 2)
        self.assertNotIn("body", result)

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
            ('text/html; foo="x;charset=bogus"; charset=iso-8859-1', "iso-8859-1"),
            ('text/html; charset="utf-8"', "utf-8"),
            ("text/html; charset=not-a-codec", None),
            (None, None),
            ("", None),
        ]
        for header, expected in cases:
            with self.subTest(header=header):
                self.assertEqual(module.charset_from_content_type(header), expected)

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

    def test_cli_rejects_url_credentials(self) -> None:
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

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("URL credentials are not allowed", result.stderr)

    def test_fetch_blocks_private_dns_and_private_redirect_targets(self) -> None:
        module = load_script("site_meta_audit.py")
        http = module.public_http
        private_answer = [
            (http.socket.AF_INET, http.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]
        with (
            mock.patch.object(http.socket, "getaddrinfo", return_value=private_answer),
            mock.patch.object(http, "connect_endpoint") as connect_endpoint,
        ):
            result = module.fetch("http://audit-target.example")

        self.assertEqual(result["status"], "error")
        self.assertIn("non-public", result["reason"])
        connect_endpoint.assert_not_called()

        public_answer = [
            (http.socket.AF_INET, http.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        client, server = http.socket.socketpair()
        server.sendall(
            b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n"
            b"Location: http://metadata.example/latest\r\n\r\n"
        )
        try:
            with (
                mock.patch.object(
                    http.socket, "getaddrinfo", side_effect=[public_answer, private_answer]
                ) as getaddrinfo,
                mock.patch.object(http, "connect_endpoint", return_value=client) as connect_endpoint,
            ):
                result = module.fetch("http://public.example/start")
        finally:
            server.close()

        self.assertEqual(result["status"], "error")
        self.assertIn("redirect blocked", result["reason"])
        self.assertEqual(getaddrinfo.call_count, 2)
        connect_endpoint.assert_called_once_with(public_answer[0], 20)

    def test_fetch_rejects_credentials_and_unsupported_schemes(self) -> None:
        module = load_script("site_meta_audit.py")
        for url in ("file:///tmp/index.html", "https://user:pass@example.com/"):
            with self.subTest(url=url):
                result = module.fetch(url)
            self.assertEqual(result["status"], "error")
            self.assertTrue(
                "unsupported URL scheme" in result["reason"]
                or "credentials" in result["reason"]
            )

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
