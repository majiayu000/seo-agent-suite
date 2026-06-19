#!/usr/bin/env python3
"""Collect repo/package SEO evidence for open-source projects."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 fallback
    tomllib = None


def run_cmd(args: list[str], cwd: Path | None = None, timeout: int = 20) -> dict:
    if not shutil.which(args[0]):
        return {"status": "skipped", "reason": f"{args[0]} not found"}
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "timeout", "command": args}

    return {
        "status": "ok" if result.returncode == 0 else "error",
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "command": args,
    }


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_toml(path: Path) -> dict | None:
    if not tomllib:
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None


def http_check(url: str, timeout: int = 15) -> dict:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "github-repo-seo-skill/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2048)
            return {
                "status": "ok",
                "url": response.geturl(),
                "http_status": response.status,
                "content_type": response.headers.get("content-type"),
                "sample_bytes": len(body),
            }
    except urllib.error.HTTPError as exc:
        return {"status": "error", "url": url, "http_status": exc.code, "reason": str(exc)}
    except urllib.error.URLError as exc:
        return {"status": "error", "url": url, "reason": str(exc.reason)}
    except TimeoutError:
        return {"status": "error", "url": url, "reason": "timeout"}


def normalize_homepage(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(value)
        normalized = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
        return normalized.rstrip("/")
    return None


def should_check_site_resources(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    registry_or_repo_hosts = {
        "github.com",
        "www.github.com",
        "npmjs.com",
        "www.npmjs.com",
        "crates.io",
        "www.crates.io",
        "lib.rs",
        "www.lib.rs",
        "pypi.org",
        "www.pypi.org",
    }
    return parsed.netloc.lower() not in registry_or_repo_hosts


def site_resource_checks(homepage: str) -> dict:
    checks = {"homepage": http_check(homepage)}
    if should_check_site_resources(homepage):
        checks["robots"] = http_check(homepage.rstrip("/") + "/robots.txt")
        checks["sitemap"] = http_check(homepage.rstrip("/") + "/sitemap.xml")
    else:
        skipped = {"status": "skipped", "reason": "registry or source-host URL, not a project site"}
        checks["robots"] = skipped
        checks["sitemap"] = skipped
    return checks


def collect_manifests(root: Path) -> dict:
    manifests: dict[str, object] = {"npm": [], "cargo": None, "python": None}

    for path in sorted(root.glob("**/package.json")):
        if "node_modules" in path.parts:
            continue
        data = read_json(path)
        if not data:
            continue
        manifests["npm"].append(
            {
                "path": str(path.relative_to(root)),
                "name": data.get("name"),
                "description": data.get("description"),
                "homepage": data.get("homepage"),
                "repository": data.get("repository"),
                "keywords": data.get("keywords"),
                "publishConfig": data.get("publishConfig"),
            }
        )

    cargo = root / "Cargo.toml"
    cargo_data = read_toml(cargo) if cargo.exists() else None
    if cargo_data:
        package = cargo_data.get("package", {})
        manifests["cargo"] = {
            "path": "Cargo.toml",
            "name": package.get("name"),
            "description": package.get("description"),
            "homepage": package.get("homepage"),
            "repository": package.get("repository"),
            "readme": package.get("readme"),
            "keywords": package.get("keywords"),
            "categories": package.get("categories"),
        }

    pyproject = root / "pyproject.toml"
    pyproject_data = read_toml(pyproject) if pyproject.exists() else None
    if pyproject_data:
        project = pyproject_data.get("project", {})
        manifests["python"] = {
            "path": "pyproject.toml",
            "name": project.get("name"),
            "description": project.get("description"),
            "urls": project.get("urls"),
            "keywords": project.get("keywords"),
        }

    return manifests


def collect_readmes(root: Path) -> list[dict]:
    readmes = []
    for path in sorted(root.glob("README*")):
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        non_empty = [line.strip() for line in lines if line.strip()]
        readmes.append(
            {
                "path": str(path.relative_to(root)),
                "line_count": len(lines),
                "first_heading": next((line for line in non_empty if line.startswith("#")), None),
                "first_non_empty": non_empty[0] if non_empty else None,
            }
        )
    return readmes


def infer_homepages(manifests: dict) -> list[str]:
    urls: list[str] = []
    cargo = manifests.get("cargo") or {}
    cargo_home = normalize_homepage(cargo.get("homepage")) if isinstance(cargo, dict) else None
    if cargo_home:
        urls.append(cargo_home)

    for item in manifests.get("npm", []):
        if not isinstance(item, dict):
            continue
        homepage = normalize_homepage(item.get("homepage"))
        if homepage and homepage not in urls:
            urls.append(homepage)

    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect repo/package SEO baseline evidence.")
    parser.add_argument("--root", default=".", help="Repository root to inspect.")
    parser.add_argument("--homepage", action="append", default=[], help="Homepage URL to check. Can be repeated.")
    parser.add_argument("--npm", action="append", default=[], help="npm package name to verify. Can be repeated.")
    parser.add_argument("--crate", action="append", default=[], help="crates.io package name to search. Can be repeated.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    manifests = collect_manifests(root)
    explicit_homepages = [url for url in (normalize_homepage(item) for item in args.homepage) if url]
    homepages = list(dict.fromkeys(explicit_homepages + infer_homepages(manifests)))
    npm_packages = list(args.npm)
    crate_names = list(args.crate)

    for item in manifests.get("npm", []):
        if isinstance(item, dict) and item.get("name") and item["name"] not in npm_packages:
            npm_packages.append(item["name"])
    cargo = manifests.get("cargo")
    if isinstance(cargo, dict) and cargo.get("name") and cargo["name"] not in crate_names:
        crate_names.append(cargo["name"])

    evidence = {
        "root": str(root),
        "git": {
            "status": run_cmd(["git", "status", "--short", "--branch"], cwd=root),
            "remote": run_cmd(["git", "remote", "get-url", "origin"], cwd=root),
            "repo_view": run_cmd(
                [
                    "gh",
                    "repo",
                    "view",
                    "--json",
                    "nameWithOwner,description,homepageUrl,repositoryTopics,visibility,defaultBranchRef",
                ],
                cwd=root,
            ),
        },
        "manifests": manifests,
        "readmes": collect_readmes(root),
        "registry": {
            "npm": {pkg: run_cmd(["npm", "view", pkg, "--json"], cwd=root) for pkg in npm_packages},
            "crates": {crate: run_cmd(["cargo", "search", crate, "--limit", "3"], cwd=root) for crate in crate_names},
        },
        "site": {
            homepage: site_resource_checks(homepage)
            for homepage in homepages
        },
    }

    if args.json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print(f"root: {root}")
        print(f"npm packages: {', '.join(npm_packages) or 'none'}")
        print(f"crates: {', '.join(crate_names) or 'none'}")
        print(f"homepages: {', '.join(homepages) or 'none'}")
        print("Run with --json for full evidence.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
