#!/usr/bin/env python3
"""Behavior checks for local audit scripts."""

from __future__ import annotations

import importlib.util
import io
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


def public_http_mod(module):
    """Return the shared public_http module used by audit scripts."""
    return module.public_http


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
