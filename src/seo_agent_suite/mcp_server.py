"""Thin MCP server exposing the same audits as the CLI (optional extra)."""

from __future__ import annotations

import json
from typing import Any


def _require_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised via CLI message
        raise ImportError(
            "The mcp package is required. Install with: pip install 'seo-agent-suite[mcp]'"
        ) from exc
    return FastMCP


def build_server():
    FastMCP = _require_mcp()
    mcp = FastMCP(
        "seo-agent-suite",
        instructions=(
            "Evidence-backed SEO audits for open-source discoverability. "
            "Prefer findings[] (Confirmed/Likely/Hypothesis). "
            "Does not claim rankings or mutate remote sites."
        ),
    )

    @mcp.tool()
    def doctor() -> str:
        """Check that suite scripts and common local tools are available."""
        from seo_agent_suite.cli import cmd_doctor
        import argparse
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_doctor(argparse.Namespace())
        return buf.getvalue()

    @mcp.tool()
    def repo_baseline(
        root: str = ".",
        homepage: list[str] | None = None,
        npm: list[str] | None = None,
        crate: list[str] | None = None,
        project_yaml: str | None = None,
    ) -> str:
        """Collect repository/package SEO baseline evidence as a Report Envelope JSON string."""
        from seo_agent_suite.cli import cmd_repo_baseline
        import argparse
        import io
        from contextlib import redirect_stdout

        args = argparse.Namespace(
            root=root,
            homepage=homepage or [],
            npm=npm or [],
            crate=crate or [],
            project_yaml=project_yaml,
            json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cmd_repo_baseline(args)
        payload = buf.getvalue()
        # Attach exit hint for agents without breaking JSON
        try:
            data: dict[str, Any] = json.loads(payload)
            data["exit_code"] = code
            return json.dumps(data, indent=2, sort_keys=True)
        except json.JSONDecodeError:
            return payload

    @mcp.tool()
    def site_meta(url: str) -> str:
        """Audit crawlable page metadata for one public URL; returns Report Envelope JSON."""
        from seo_agent_suite.cli import cmd_site_meta
        import argparse
        import io
        from contextlib import redirect_stdout

        args = argparse.Namespace(url=url, json=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cmd_site_meta(args)
        payload = buf.getvalue()
        try:
            data: dict[str, Any] = json.loads(payload)
            data["exit_code"] = code
            return json.dumps(data, indent=2, sort_keys=True)
        except json.JSONDecodeError:
            return payload

    return mcp


def run_stdio() -> None:
    server = build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    run_stdio()
