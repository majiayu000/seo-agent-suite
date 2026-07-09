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


def read_toml(path: Path) -> tuple[dict | None, dict | None]:
    if not tomllib:
        return None, {"status": "error", "path": str(path), "reason": "tomllib unavailable on Python <3.11"}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")), None
    except OSError as exc:
        return None, {"status": "error", "path": str(path), "reason": str(exc)}
    except tomllib.TOMLDecodeError as exc:
        return None, {"status": "error", "path": str(path), "reason": f"invalid TOML: {exc}"}


def http_check(url: str, timeout: int = 15) -> dict:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"status": "error", "url": url, "reason": "unsupported URL scheme"}
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


def normalize_homepage(value: str | None, *, strict: bool = False, label: str = "homepage") -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(value)
        normalized = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
        return normalized.rstrip("/")
    if strict:
        raise ValueError(f"{label} must be an http(s) URL: {value}")
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
    manifests: dict[str, object] = {"npm": [], "cargo": None, "python": None, "errors": []}

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
    cargo_data = None
    if cargo.exists():
        cargo_data, cargo_error = read_toml(cargo)
        if cargo_error:
            manifests["errors"].append({**cargo_error, "path": str(cargo.relative_to(root))})
            manifests["cargo"] = {"path": "Cargo.toml", "status": "error", "reason": cargo_error["reason"]}
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
    pyproject_data = None
    if pyproject.exists():
        pyproject_data, pyproject_error = read_toml(pyproject)
        if pyproject_error:
            manifests["errors"].append({**pyproject_error, "path": str(pyproject.relative_to(root))})
            manifests["python"] = {"path": "pyproject.toml", "status": "error", "reason": pyproject_error["reason"]}
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


def parse_scalar(value: str) -> object:
    value = value.strip()
    if value in {"[]", ""}:
        return [] if value == "[]" else ""
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def parse_shipwise_discoverability(path: Path) -> dict:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read project yaml: {exc}") from exc

    in_block = False
    current_list: str | None = None
    data: dict[str, object] = {}

    for line in lines:
        if not in_block:
            if line.strip() == "discoverability:" and not line.startswith(" "):
                in_block = True
            continue
        if line and not line.startswith(" "):
            break
        if not line.strip():
            continue
        if line.startswith("    - "):
            if not current_list:
                raise ValueError(f"{path}: list item without list key in discoverability block")
            data.setdefault(current_list, [])
            if not isinstance(data[current_list], list):
                raise ValueError(f"{path}: {current_list} is not a list")
            data[current_list].append(parse_scalar(line.removeprefix("    - ")))
            continue
        if not line.startswith("  ") or ":" not in line:
            raise ValueError(f"{path}: unsupported discoverability line: {line}")
        key, raw_value = line.strip().split(":", 1)
        value = [] if raw_value.strip() == "" else parse_scalar(raw_value)
        data[key] = value
        current_list = key if value == [] else None

    if not in_block:
        raise ValueError(f"{path}: missing discoverability block")
    return data


def check_item(ok: bool, evidence: object, reason: str = "") -> dict:
    result = {"status": "ok" if ok else "error", "evidence": evidence}
    if reason and not ok:
        result["reason"] = reason
    return result


def collect_community_files(root: Path) -> dict:
    issue_templates = root / ".github" / "ISSUE_TEMPLATE"
    return {
        "readme": (root / "README.md").exists() or any(root.glob("README.*")),
        "license": any((root / name).exists() for name in ["LICENSE", "LICENSE.md", "COPYING"]),
        "contributing": any((root / name).exists() for name in ["CONTRIBUTING.md", "CONTRIBUTING"]),
        "code_of_conduct": any((root / name).exists() for name in ["CODE_OF_CONDUCT.md", "CODE_OF_CONDUCT"]),
        "security": any((root / name).exists() for name in ["SECURITY.md", "SECURITY"]),
        "issue_templates": issue_templates.exists() and any(issue_templates.iterdir()),
    }


def evaluate_shipwise_project(root: Path, project_yaml: Path) -> dict:
    discoverability = parse_shipwise_discoverability(project_yaml)
    topics = discoverability.get("topics")
    keywords = discoverability.get("keywords")
    homepage = discoverability.get("homepage_url")
    primary_keyword = str(discoverability.get("primary_keyword") or "").strip()
    description = str(discoverability.get("description") or "").strip()

    if not isinstance(topics, list):
        topics = []
    if not isinstance(keywords, list):
        keywords = []
    normalized_homepage = normalize_homepage(str(homepage or ""), strict=bool(homepage), label="discoverability.homepage_url")
    community_files = collect_community_files(root)

    invalid_topics = [
        item for item in topics
        if not isinstance(item, str) or len(item) > 50 or item.lower() != item or " " in item
    ]
    repeated_primary = (
        description.lower().count(primary_keyword.lower()) > 1 if primary_keyword and description else False
    )

    checks = {
        "description": check_item(bool(description), description, "missing discoverability.description"),
        "primary_keyword": check_item(bool(primary_keyword), primary_keyword, "missing discoverability.primary_keyword"),
        "keywords": check_item(bool(keywords), keywords, "missing discoverability.keywords"),
        "topics_count": check_item(5 <= len(topics) <= 20, len(topics), "topics must contain 5 to 20 entries"),
        "topics_format": check_item(not invalid_topics, invalid_topics, "topics must be lowercase hyphenated GitHub topic slugs"),
        "homepage_url": check_item(bool(normalized_homepage), normalized_homepage, "missing discoverability.homepage_url"),
        "social_image_set": check_item(
            discoverability.get("social_image_set") is True,
            discoverability.get("social_image_set"),
            "social preview image is not marked as set",
        ),
        "keyword_stuffing": check_item(not repeated_primary, description, "primary keyword repeated too often in description"),
        "readme": check_item(community_files["readme"], community_files["readme"], "README missing"),
        "license": check_item(community_files["license"], community_files["license"], "LICENSE missing"),
        "support_path": check_item(
            community_files["issue_templates"] or community_files["contributing"],
            community_files,
            "missing issue templates or CONTRIBUTING support path",
        ),
    }

    return {
        "project_yaml": str(project_yaml),
        "discoverability": discoverability,
        "community_files": community_files,
        "checks": checks,
    }


def collect_errors(evidence: dict) -> list[dict]:
    errors: list[dict] = []
    for item in evidence.get("manifests", {}).get("errors", []):
        errors.append({"surface": "manifest", **item})

    for homepage, checks in evidence.get("site", {}).items():
        homepage_check = checks.get("homepage", {})
        if homepage_check.get("status") == "error":
            errors.append({"surface": "site", "url": homepage, "reason": homepage_check.get("reason", "homepage check failed")})

    for name, item in evidence.get("shipwise", {}).get("checks", {}).items():
        if item.get("status") == "error":
            errors.append({"surface": "shipwise", "check": name, "reason": item.get("reason", "check failed")})

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect repo/package SEO baseline evidence.")
    parser.add_argument("--root", default=".", help="Repository root to inspect.")
    parser.add_argument("--homepage", action="append", default=[], help="Homepage URL to check. Can be repeated.")
    parser.add_argument("--npm", action="append", default=[], help="npm package name to verify. Can be repeated.")
    parser.add_argument("--crate", action="append", default=[], help="crates.io package name to search. Can be repeated.")
    parser.add_argument("--project-yaml", help="Shipwise project.yaml to validate against discoverability checks.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"--root must be an existing directory: {root}")
    manifests = collect_manifests(root)
    try:
        explicit_homepages = [
            url for url in (normalize_homepage(item, strict=True, label="--homepage") for item in args.homepage) if url
        ]
    except ValueError as exc:
        parser.error(str(exc))
    homepages = list(dict.fromkeys(explicit_homepages + infer_homepages(manifests)))
    npm_packages = list(args.npm)
    crate_names = list(args.crate)

    for item in manifests.get("npm", []):
        if isinstance(item, dict) and item.get("name") and item["name"] not in npm_packages:
            npm_packages.append(item["name"])
    cargo = manifests.get("cargo")
    if isinstance(cargo, dict) and cargo.get("name") and cargo["name"] not in crate_names:
        crate_names.append(cargo["name"])

    shipwise = {}
    if args.project_yaml:
        project_yaml = Path(args.project_yaml).resolve()
        try:
            shipwise = evaluate_shipwise_project(root, project_yaml)
        except ValueError as exc:
            parser.error(str(exc))

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
        "community_files": collect_community_files(root),
        "shipwise": shipwise,
    }
    errors = collect_errors(evidence)
    evidence["status"] = "error" if errors else "ok"
    evidence["errors"] = errors

    if args.json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print(f"root: {root}")
        print(f"npm packages: {', '.join(npm_packages) or 'none'}")
        print(f"crates: {', '.join(crate_names) or 'none'}")
        print(f"homepages: {', '.join(homepages) or 'none'}")
        sys.stdout.write(f"status: {evidence['status']}\n")
        if errors:
            sys.stdout.write("errors:\n")
            for item in errors:
                sys.stdout.write(f"- {item.get('surface')}: {item.get('reason')}\n")
        print("Run with --json for full evidence.")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
