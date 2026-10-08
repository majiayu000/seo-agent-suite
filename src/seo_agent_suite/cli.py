"""seo-agent console entrypoint."""

from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Sequence

from seo_agent_suite import SCHEMA_VERSION, __version__
from seo_agent_suite.comparison_metadata import build_site_comparison_metadata
from seo_agent_suite.comparison_runtime import resolve_site_runtime_policy
from seo_agent_suite.paths import ensure_scripts_on_path, load_script, suite_root
from seo_agent_suite.report import (
    attach_envelope,
    findings_from_repo_baseline,
    enrich_site_result,
)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_version(_: argparse.Namespace) -> int:
    root = suite_root()
    print(f"seo-agent-suite {__version__}")
    print(f"schema_version {SCHEMA_VERSION}")
    print(f"suite_root {root}")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    """Environment self-check for agents (core paths need no network)."""
    import shutil

    root = suite_root()
    scripts = ensure_scripts_on_path()
    checks = {
        "suite_root": str(root),
        "scripts_dir": str(scripts),
        "python": sys.executable,
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "has_repo_script": (scripts / "repo_seo_baseline.py").is_file(),
        "has_site_script": (scripts / "site_meta_audit.py").is_file(),
        "has_public_http": (scripts / "public_http.py").is_file(),
        "tools": {
            "gh": bool(shutil.which("gh")),
            "npm": bool(shutil.which("npm")),
            "cargo": bool(shutil.which("cargo")),
            "git": bool(shutil.which("git")),
        },
        "mcp_extra": False,
    }
    try:
        import mcp  # noqa: F401

        checks["mcp_extra"] = True
    except ImportError:
        pass

    ok = checks["has_repo_script"] and checks["has_site_script"] and checks["has_public_http"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
        "status": "ok" if ok else "error",
        "doctor": checks,
    }
    _print_json(payload)
    return 0 if ok else 1


def cmd_repo_baseline(args: argparse.Namespace) -> int:
    module = load_script("repo_seo_baseline.py")
    argv = ["repo_seo_baseline.py", "--root", args.root, "--json"]
    for homepage in args.homepage or []:
        argv.extend(["--homepage", homepage])
    for npm in args.npm or []:
        argv.extend(["--npm", npm])
    for crate in args.crate or []:
        argv.extend(["--crate", crate])
    if args.project_yaml:
        argv.extend(["--project-yaml", args.project_yaml])

    buf = io.StringIO()
    old_argv = sys.argv
    try:
        sys.argv = argv
        with redirect_stdout(buf):
            code = module.main()
    except SystemExit as exc:
        code = int(exc.code or 2)
    finally:
        sys.argv = old_argv

    text = buf.getvalue().strip()
    if not text:
        return code if code is not None else 2
    try:
        evidence = json.loads(text)
    except json.JSONDecodeError:
        sys.stdout.write(buf.getvalue())
        return code

    if "findings" not in evidence or "schema_version" not in evidence:
        evidence = attach_envelope(
            evidence,
            target_kind="repo",
            target_id=str(evidence.get("root") or Path(args.root).resolve()),
            findings=findings_from_repo_baseline(evidence),
            status=evidence.get("status"),
        )

    if args.json:
        _print_json(evidence)
    else:
        print(f"root: {evidence.get('root')}")
        print(f"status: {evidence.get('status')}")
        print(f"findings: {len(evidence.get('findings') or [])}")
        errors = evidence.get("errors") or []
        if errors:
            print("errors:")
            for item in errors:
                print(f"- {item.get('surface')}: {item.get('reason')}")
        print("Run with --json for full evidence + findings.")
    return 1 if evidence.get("errors") else 0


def cmd_site_meta(args: argparse.Namespace) -> int:
    module = load_script("site_meta_audit.py")
    audit_options: dict = {}
    result = module.audit(args.url, **audit_options)
    if "findings" not in result or "schema_version" not in result:
        result = enrich_site_result(result)
    result["comparison"] = build_site_comparison_metadata(
        result, args.url, resolve_site_runtime_policy(module, audit_options=audit_options)
    )
    if args.json:
        _print_json(result)
    else:
        page = result.get("page", {})
        print(f"url: {result.get('url', args.url)}")
        print(f"status: {result.get('status')}")
        print(f"http_status: {page.get('http_status')}")
        if page.get("status") == "error" and page.get("reason"):
            print(f"reason: {page.get('reason')}")
        print(f"title: {result.get('title')}")
        print(f"findings: {len(result.get('findings') or [])}")
    page = result.get("page", {})
    return 0 if page.get("status") == "ok" else 1


def cmd_compare(args: argparse.Namespace) -> int:
    """Read exactly two regular files; never invoke a collector or provider."""
    import os
    import stat

    from seo_agent_suite.compare import (
        EXIT_CODES, MAX_INPUT_BYTES, compare_reports, invalid_input_result,
    )

    inputs = []
    result = None
    for side in ("before", "after"):
        fd = None
        try:
            path = getattr(args, side)
            if path == "-":
                result = invalid_input_result(side, "stdin_not_supported")
                break
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                result = invalid_input_result(side, "expected_regular_file")
                break
            with os.fdopen(fd, "rb") as stream:
                fd = None
                data = stream.read(MAX_INPUT_BYTES + 1)
            inputs.append(data)
        except (OSError, ValueError):
            result = invalid_input_result(side, "unreadable_file")
            break
        finally:
            if fd is not None:
                os.close(fd)
    if result is None:
        result = compare_reports(*inputs)
    if args.json:
        _print_json(result)
    else:
        print(f"comparison: {result['status']}")
        print("Scope: five recorded raw-HTML presence checks; resources excluded.")
        if result["counts"] is not None:
            for key, count in result["counts"].items():
                print(f"{key}: {count}")
            print("Resolved means passed in this capture, not deployed or indexed.")
        else:
            for reason in result["reasons"]:
                print(f"{reason['input']}: {reason['code']}")
    return EXIT_CODES[result["status"]]


def cmd_mcp(_: argparse.Namespace) -> int:
    try:
        from seo_agent_suite.mcp_server import build_server

        server = build_server()
    except ImportError as exc:
        print(
            "MCP extra not installed. Install with: pip install 'seo-agent-suite[mcp]'",
            file=sys.stderr,
        )
        print(f"detail: {exc}", file=sys.stderr)
        return 2
    server.run(transport="stdio")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seo-agent",
        description=(
            "Evidence-backed SEO audits for agents. "
            "Works with Codex skills, Cursor, Claude Code, or MCP."
        ),
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit.")
    sub = parser.add_subparsers(dest="command")

    p_ver = sub.add_parser("version", help="Show package / schema version and suite root.")
    p_ver.set_defaults(func=cmd_version)

    p_doc = sub.add_parser("doctor", help="Check that scripts and local tools are available.")
    p_doc.set_defaults(func=cmd_doctor)

    p_repo = sub.add_parser(
        "repo-baseline",
        aliases=["repo"],
        help="Collect repository / package / optional Shipwise discoverability evidence.",
    )
    p_repo.add_argument("--root", default=".", help="Repository root to inspect.")
    p_repo.add_argument("--homepage", action="append", default=[], help="Homepage URL. Repeatable.")
    p_repo.add_argument("--npm", action="append", default=[], help="npm package name. Repeatable.")
    p_repo.add_argument("--crate", action="append", default=[], help="crates.io package name. Repeatable.")
    p_repo.add_argument(
        "--project-yaml",
        help="Optional Shipwise project.yaml (adapter; suite works without Shipwise).",
    )
    p_repo.add_argument("--json", action="store_true", help="Emit JSON Report Envelope.")
    p_repo.set_defaults(func=cmd_repo_baseline)

    p_site = sub.add_parser(
        "site-meta",
        aliases=["site"],
        help="Audit crawlable metadata for one public URL.",
    )
    p_site.add_argument("url", help="Public http(s) URL to inspect.")
    p_site.add_argument("--json", action="store_true", help="Emit JSON Report Envelope.")
    p_site.set_defaults(func=cmd_site_meta)

    p_compare = sub.add_parser("compare", help="Compare two recorded reports offline.")
    p_compare.add_argument("before", help="Before report: regular UTF-8 JSON file, max 8 MiB.")
    p_compare.add_argument("after", help="After report: regular UTF-8 JSON file, max 8 MiB.")
    p_compare.add_argument("--json", action="store_true", help="Emit JSON comparison result.")
    p_compare.set_defaults(func=cmd_compare)

    p_mcp = sub.add_parser(
        "mcp",
        help="Run the optional MCP server (requires: pip install 'seo-agent-suite[mcp]').",
    )
    p_mcp.set_defaults(func=cmd_mcp)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if getattr(args, "version", False) and not getattr(args, "command", None):
        return cmd_version(args)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
