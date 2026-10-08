#!/usr/bin/env python3
"""Report envelope, CLI, and politeness helper tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from seo_agent_suite import SCHEMA_VERSION, __version__  # noqa: E402
from seo_agent_suite.cli import main as cli_main  # noqa: E402
from seo_agent_suite.paths import suite_root  # noqa: E402
from seo_agent_suite.report import (  # noqa: E402
    findings_from_site_audit,
    enrich_site_result,
    enrich_repo_evidence,
)


def load_script(name: str):
    """Load scripts under their natural module names (shared with CLI/package)."""
    from seo_agent_suite.paths import load_script as package_load

    return package_load(name)


class SuitePathsTests(unittest.TestCase):
    def test_suite_root_finds_scripts(self) -> None:
        root = suite_root()
        self.assertTrue((root / "scripts" / "public_http.py").is_file())
        self.assertEqual(root, ROOT)


class ReportEnvelopeTests(unittest.TestCase):
    def test_site_findings_for_missing_meta(self) -> None:
        raw = {
            "url": "https://example.com/",
            "page": {"status": "ok", "http_status": 200},
            "checks": {
                "has_title": False,
                "has_meta_description": False,
                "has_canonical": True,
                "has_og_title": False,
                "has_json_ld": False,
                "has_robots_txt": True,
                "has_sitemap_xml": False,
            },
        }
        enriched = enrich_site_result(raw)
        self.assertEqual(enriched["schema_version"], SCHEMA_VERSION)
        self.assertEqual(enriched["tool_version"], __version__)
        self.assertEqual(enriched["target"]["kind"], "site")
        self.assertEqual(enriched["status"], "partial")
        ids = {f["id"] for f in enriched["findings"]}
        self.assertIn("site.meta.title.missing", ids)
        self.assertIn("site.meta.canonical.present", ids)
        # legacy fields preserved
        self.assertEqual(enriched["checks"]["has_canonical"], True)

    def test_resource_failures_remain_unknown_and_confirmed_absence_fails(self) -> None:
        from unittest.mock import patch
        site = load_script("site_meta_audit.py")
        url = "https://example.com/docs/page"
        page = {"status": "ok", "url": url, "http_status": 200,
                "content_type": "text/html", "body": "<title>Example</title>",
                "body_truncated": False}
        for code, reason, expected in [(403, "HTTP 403", "unknown"),
                                       (None, "timeout", "unknown"),
                                       (404, "HTTP 404", "missing")]:
            with self.subTest(code=code):
                def fetch(target):
                    if target == url:
                        return page
                    return {"status": "error", "url": target, "http_status": code,
                            "reason": reason, "body": "", "body_truncated": False}
                with patch.object(site, "fetch", side_effect=fetch):
                    raw = site.audit(url)
                result = enrich_site_result(raw)
                for fid in ("site.crawl.robots_txt", "site.crawl.sitemap"):
                    finding = next(f for f in result["findings"] if f["id"].startswith(fid))
                    self.assertEqual(finding["id"], f"{fid}.{expected}")
                    self.assertEqual(finding["status"], "fail" if expected == "missing" else "unknown")
                for original in raw["findings"]:
                    self.assertTrue(any(f.get("code") == original["code"] for f in result["findings"]))

    def test_site_fetch_error_finding(self) -> None:
        raw = {
            "url": "https://example.com/",
            "page": {"status": "error", "reason": "hostname resolution failed"},
        }
        enriched = enrich_site_result(raw)
        self.assertEqual(enriched["status"], "error")
        self.assertEqual(enriched["findings"][0]["id"], "site.fetch.failed")

    def test_repo_errors_become_findings(self) -> None:
        evidence = {
            "root": "/tmp/repo",
            "status": "error",
            "errors": [{"surface": "manifest", "path": "package.json", "reason": "invalid JSON"}],
            "readmes": [{"path": "README.md"}],
            "community_files": {"readme": True, "license": True},
        }
        enriched = enrich_repo_evidence(evidence)
        self.assertEqual(enriched["schema_version"], SCHEMA_VERSION)
        self.assertTrue(any(f["id"] == "repo.manifest.package.json" for f in enriched["findings"]))
        self.assertEqual(enriched["errors"][0]["path"], "package.json")


class RobotsHelperTests(unittest.TestCase):
    def test_robots_path_allowed(self) -> None:
        http = load_script("public_http.py")
        body = "User-agent: *\nDisallow: /secret\nAllow: /secret/public\n"
        self.assertFalse(http.robots_path_allowed(body, "/secret"))
        self.assertTrue(http.robots_path_allowed(body, "/secret/public"))
        self.assertTrue(http.robots_path_allowed(body, "/ok"))
        self.assertIn("seo-agent-suite/0.2.0", http.USER_AGENT)


class CliTests(unittest.TestCase):
    def test_cli_version(self) -> None:
        code = cli_main(["version"])
        self.assertEqual(code, 0)

    def test_cli_doctor(self) -> None:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["doctor"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["doctor"]["has_repo_script"])

    def test_cli_repo_baseline_json(self) -> None:
        import io
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "README.md").write_text("# demo\n", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli_main(["repo-baseline", "--root", tmp, "--json"])
            payload = json.loads(buf.getvalue())
        self.assertIn(code, {0, 1})
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertIn("findings", payload)
        self.assertEqual(payload["target"]["kind"], "repo")

    def test_mcp_missing_extra_is_usage_error_and_runtime_errors_propagate(self) -> None:
        import io
        from contextlib import redirect_stderr
        from unittest.mock import patch, Mock
        from seo_agent_suite import mcp_server
        with patch.object(mcp_server, "_require_mcp", side_effect=ImportError("missing mcp")):
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli_main(["mcp"]), 2)
            self.assertIn("MCP extra not installed", error.getvalue())
        server = Mock()
        server.run.side_effect = ImportError("runtime failure")
        with patch.object(mcp_server, "build_server", return_value=server):
            with self.assertRaisesRegex(ImportError, "runtime failure"):
                cli_main(["mcp"])

    def test_console_script_module(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-m", "seo_agent_suite", "doctor"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tool_version"], __version__)


if __name__ == "__main__":
    unittest.main()
