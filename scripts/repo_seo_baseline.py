#!/usr/bin/env python3
"""Collect repo/package SEO evidence for open-source projects."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import public_http
from public_http import (  # noqa: E402
    PinnedHTTPConnection,
    PinnedHTTPSConnection,
    connect_endpoint,
    http_check,
    request_public_url_once,
    validate_public_http_url,
)
from site_meta_audit import crawl_resource_checks  # noqa: E402

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
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "timeout", "command": args}
    except UnicodeDecodeError:
        return {"status": "error", "reason": "decode_error", "command": args}
    except OSError:
        return {"status": "error", "reason": "execution_error", "command": args}

    return {
        "status": "ok" if result.returncode == 0 else "error",
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "command": args,
    }


def finite_json_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number must be finite")
    return number


def read_json(path: Path) -> tuple[dict | None, dict | None]:
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            parse_float=finite_json_number,
            parse_constant=finite_json_number,
        )
    except UnicodeDecodeError as exc:
        return None, {"status": "error", "path": str(path), "reason": f"invalid UTF-8: {exc}"}
    except OSError as exc:
        return None, {"status": "error", "path": str(path), "reason": str(exc)}
    except json.JSONDecodeError as exc:
        return None, {"status": "error", "path": str(path), "reason": f"invalid JSON: {exc}"}
    except (ValueError, RecursionError):
        return None, {"status": "error", "path": str(path), "reason": "JSON value exceeds supported numeric or nesting limits"}
    if not isinstance(data, dict):
        return None, {"status": "error", "path": str(path), "reason": "JSON root must be an object"}
    return data, None


def read_toml(path: Path) -> tuple[dict | None, dict | None]:
    if not tomllib:
        return None, {"status": "error", "path": str(path), "reason": "tomllib unavailable on Python <3.11"}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")), None
    except UnicodeDecodeError as exc:
        return None, {"status": "error", "path": str(path), "reason": f"invalid UTF-8: {exc}"}
    except OSError as exc:
        return None, {"status": "error", "path": str(path), "reason": str(exc)}
    except tomllib.TOMLDecodeError as exc:
        return None, {"status": "error", "path": str(path), "reason": f"invalid TOML: {exc}"}


def redact_evidence(value: object) -> object:
    """Remove URL userinfo from manifest URLs and command diagnostics."""
    if isinstance(value, str):
        return re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]+", lambda match: public_http.redact_url(match.group()), value)
    if isinstance(value, list):
        return [redact_evidence(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_evidence(item) for key, item in value.items()}
    return value


def normalize_homepage(value: object, *, strict: bool = False, label: str = "homepage") -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        if strict:
            raise ValueError(f"{label} must be a string containing an http(s) URL")
        return None
    value = value.strip()
    try:
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("missing http(s) scheme or hostname")
        _ = parsed.port
        # A trailing slash can select a different document and changes relative links.
        # Only the origin-root slash is equivalent to an empty HTTP path.
        path = "" if parsed.path == "/" and not parsed.params else parsed.path
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, ""))
    except ValueError:
        if strict:
            raise ValueError(f"{label} must be an http(s) URL with a valid hostname and port: {public_http.redact_url(value)}") from None
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
        resources = crawl_resource_checks(homepage)
        for resource, key in (("robots", "robots_txt"), ("sitemap", "sitemap_xml")):
            candidates = resources[key]
            item = next((candidate for candidate in candidates if candidate["present"]), candidates[0])
            checks[resource] = dict(item)
            if not item["present"] and item.get("observation") != "not_configured":
                checks[resource]["status"] = "error"
            checks[resource]["candidates"] = candidates
        if "sitemap_discovery" in resources:
            checks["sitemap"]["sitemap_discovery"] = resources["sitemap_discovery"]
    else:
        skipped = {"status": "skipped", "reason": "registry or source-host URL, not a project site"}
        checks["robots"] = skipped
        checks["sitemap"] = skipped
    return checks


def registry_name_error(name: object, registry: str, path: str) -> dict | None:
    if registry == "npm":
        valid = (
            isinstance(name, str)
            and len(name) <= 214
            and not name.startswith((".", "_"))
            and re.fullmatch(r"(?:@[A-Za-z0-9._~'!()*-]+/)?[A-Za-z0-9_~'!()*-][A-Za-z0-9._~'!()*-]*", name) is not None
        )
    else:
        valid = isinstance(name, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name) is not None
    if valid:
        return None
    return {"status": "error", "path": path, "reason": f"invalid {registry} package name"}


def validate_toml_evidence(manifest: dict, table: str, errors: list[dict]) -> None:
    """Reject unsupported exported values without discarding valid sibling fields."""
    for field, value in list(manifest.items()):
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError, RecursionError) as exc:
            detail = (
                "contains a TOML date/time value" if isinstance(exc, TypeError)
                else "contains a non-finite number" if isinstance(exc, ValueError)
                else "exceeds supported nesting limits"
            )
            reason = f"{table}.{field} {detail}"
            errors.append({"status": "error", "path": manifest["path"], "reason": reason})
            manifest[field] = None
            manifest.update({"status": "error", "reason": reason})


def collect_manifests(root: Path) -> dict:
    manifests: dict[str, object] = {"npm": [], "cargo": None, "python": None, "errors": []}

    for path in sorted(root.glob("**/package.json")):
        if "node_modules" in path.parts:
            continue
        data, json_error = read_json(path)
        if json_error:
            manifests["errors"].append({**json_error, "path": str(path.relative_to(root))})
            continue
        name_error = (
            registry_name_error(data["name"], "npm", str(path.relative_to(root))) if "name" in data else None
        )
        manifest = {
            "path": str(path.relative_to(root)),
            "name": data.get("name"),
            "version": data.get("version"),
            "private": data.get("private") is True,
            "description": data.get("description"),
            "homepage": data.get("homepage"),
            "repository": data.get("repository"),
            "keywords": data.get("keywords"),
            "publishConfig": data.get("publishConfig"),
        }
        if name_error:
            manifests["errors"].append(name_error)
            manifest.update({"status": "error", "reason": name_error["reason"]})
        manifests["npm"].append(manifest)

    cargo = root / "Cargo.toml"
    cargo_data = None
    if cargo.exists():
        cargo_data, cargo_error = read_toml(cargo)
        if cargo_error:
            manifests["errors"].append({**cargo_error, "path": str(cargo.relative_to(root))})
            manifests["cargo"] = {"path": "Cargo.toml", "status": "error", "reason": cargo_error["reason"]}
    if cargo_data:
        package = cargo_data.get("package", {})
        if not isinstance(package, dict):
            error = {"path": "Cargo.toml", "status": "error", "reason": "package must be a TOML table"}
            manifests["errors"].append(error)
            manifests["cargo"] = error
        else:
            name_error = registry_name_error(package["name"], "cargo", "Cargo.toml") if "name" in package else None
            manifests["cargo"] = {
                "path": "Cargo.toml",
                "name": package.get("name"),
                "version": package.get("version"),
                "publish": package.get("publish"),
                "description": package.get("description"),
                "homepage": package.get("homepage"),
                "repository": package.get("repository"),
                "readme": package.get("readme"),
                "keywords": package.get("keywords"),
                "categories": package.get("categories"),
            }
            if name_error:
                manifests["errors"].append(name_error)
                manifests["cargo"].update({"status": "error", "reason": name_error["reason"]})
            validate_toml_evidence(manifests["cargo"], "package", manifests["errors"])

    workspace = cargo_data.get("workspace") if cargo_data else None
    if isinstance(workspace, dict) and (workspace.get("members") or cargo_data.get("package")):
        metadata = run_cmd(["cargo", "metadata", "--no-deps", "--format-version", "1", "--locked", "--offline"], cwd=root)
        manifests["cargo_members"] = []
        try:
            if metadata.get("status") != "ok":
                raise ValueError("cargo metadata unavailable or failed")
            data = json.loads(metadata.get("stdout", ""))
            if not isinstance(data, dict) or not isinstance(data.get("workspace_members"), list) or not isinstance(data.get("packages"), list):
                raise ValueError("invalid cargo metadata")
            for package in data["packages"]:
                if not isinstance(package, dict) or package.get("id") not in data["workspace_members"]:
                    continue
                path = Path(package["manifest_path"])
                manifest = {field: package.get(field) for field in (
                    "name", "version", "description", "homepage", "repository", "readme", "keywords", "categories", "publish"
                )}
                manifest["path"] = str(path.relative_to(root))
                name_error = registry_name_error(manifest["name"], "cargo", manifest["path"])
                if name_error:
                    manifests["errors"].append(name_error)
                    manifest.update({"status": "error", "reason": name_error["reason"]})
                if path == cargo:
                    manifests["cargo"] = manifest
                else:
                    manifests["cargo_members"].append(manifest)
        except (ValueError, KeyError, TypeError):
            manifests["errors"].append({"status": "error", "path": "Cargo.toml", "reason": "cannot collect Cargo workspace members", "detail": redact_evidence(metadata)})

    pyproject = root / "pyproject.toml"
    pyproject_data = None
    if pyproject.exists():
        pyproject_data, pyproject_error = read_toml(pyproject)
        if pyproject_error:
            manifests["errors"].append({**pyproject_error, "path": str(pyproject.relative_to(root))})
            manifests["python"] = {"path": "pyproject.toml", "status": "error", "reason": pyproject_error["reason"]}
    if pyproject_data:
        project = pyproject_data.get("project", {})
        if not isinstance(project, dict):
            error = {"path": "pyproject.toml", "status": "error", "reason": "project must be a TOML table"}
            manifests["errors"].append(error)
            manifests["python"] = error
        else:
            manifests["python"] = {
                "path": "pyproject.toml",
                "name": project.get("name"),
                "description": project.get("description"),
                "urls": project.get("urls"),
                "keywords": project.get("keywords"),
            }
            validate_toml_evidence(manifests["python"], "project", manifests["errors"])

    return manifests


def collect_readmes(root: Path) -> list[dict]:
    readmes = []
    for path in sorted(
        path for directory in (root, root / ".github", root / "docs")
        for path in directory.glob("*") if path.name.lower().startswith("readme")
    ):
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
    for item in [manifests.get("cargo"), *manifests.get("cargo_members", []), *manifests.get("npm", [])]:
        if not isinstance(item, dict):
            continue
        value = item.get("homepage")
        try:
            homepage = normalize_homepage(value, strict=True)
        except ValueError as exc:
            manifests["errors"].append({"status": "error", "path": item["path"], "reason": str(exc)})
            continue
        if homepage and homepage not in urls:
            urls.append(homepage)
    return urls


def parse_scalar(value: str) -> object:
    value = value.strip()
    tag = None
    # Properties precede scalar content; quoted property/comment characters
    # remain literal text rather than participating in type classification.
    while match := re.match(r"(!\S*|&\S+)(?:\s+|$)", value):
        property_value = match.group(1)
        if property_value.startswith("!"):
            tag = property_value
        value = value[match.end():]
    if tag is not None and tag not in {"!", "!!str", "!<tag:yaml.org,2002:str>"}:
        return None
    quoted = re.fullmatch(r'''("(?:[^"\\]|\\.)*"|'(?:[^']|'')*')(?:\s+#.*)?''', value)
    if quoted:
        literal = quoted.group(1)
        content = literal[1:-1]
        return content.replace("''", "'") if literal.startswith("'") else content
    value = re.split(r"(?:^|\s+)#", value, maxsplit=1)[0].rstrip()
    # Aliases cannot be typed without resolving the document's anchors.
    if value.startswith("*"):
        return None
    if value.startswith(("[", "{")):
        return [] if value == "[]" else None
    if tag is not None:
        return value
    if value in {"[]", ""}:
        return [] if value == "[]" else ""
    if value in {"true", "True", "TRUE", "false", "False", "FALSE"}:
        return value.lower() == "true"
    if value in {"null", "Null", "NULL", "~"}:
        return None
    # Numeric values are invalid for this gate; classify YAML 1.2 core forms
    # without creating huge integers or non-finite, non-JSON floats.
    if re.fullmatch(
        r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"
        r"|0o[0-7]+|0x[0-9a-fA-F]+|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN)",
        value,
    ):
        return None
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
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not in_block:
            if re.fullmatch(r"discoverability:(?:[ \t]+#.*|[ \t]*)", line):
                in_block = True
            continue
        if line and not line.startswith(" "):
            break
        if line.startswith("    - "):
            if not current_list:
                raise ValueError(f"{path}: list item without list key in discoverability block")
            data.setdefault(current_list, [])
            if not isinstance(data[current_list], list):
                raise ValueError(f"{path}: {current_list} is not a list")
            data[current_list].append(parse_scalar(line.removeprefix("    - ")))
            continue
        # Only direct two-space members belong to this restricted block.
        # Reject nested mappings rather than promoting their keys.
        indentation = len(line) - len(line.lstrip(" "))
        if indentation != 2 or line[2:].startswith("\t") or ":" not in line:
            raise ValueError(f"{path}: unsupported discoverability line")
        key, raw_value = line.strip().split(":", 1)
        empty_header = not raw_value.strip() or raw_value.lstrip().startswith("#")
        value = [] if empty_header else parse_scalar(raw_value)
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
    directories = (root, root / ".github", root / "docs")
    issue_templates = root / ".github" / "ISSUE_TEMPLATE"
    paths = {
        "readme": [item["path"] for item in collect_readmes(root)],
        "license": [name for name in ["LICENSE", "LICENSE.md", "COPYING"] if (root / name).is_file()],
        **{key: sorted(
            str(path.relative_to(root)) for directory in directories for path in directory.glob("*")
            if path.is_file() and path.name.lower() in {name.lower() for name in names}
        ) for key, names in {
            "contributing": ["CONTRIBUTING.md", "CONTRIBUTING"],
            "code_of_conduct": ["CODE_OF_CONDUCT.md", "CODE_OF_CONDUCT"],
            "security": ["SECURITY.md", "SECURITY"],
        }.items()},
    }
    template_candidates = sorted(
        str(path.relative_to(root)) for path in issue_templates.iterdir()
        if path.is_file() and path.suffix.lower() in {".md", ".yml", ".yaml"}
        and path.name.lower() not in {"config.yml", "config.yaml"} and path.stat().st_size > 0
    ) if issue_templates.is_dir() else []
    return {
        **{key: bool(value) for key, value in paths.items()},
        "issue_templates": bool(template_candidates),
        "community_file_paths": paths,
        "issue_template_candidates": template_candidates,
    }


def evaluate_shipwise_project(root: Path, project_yaml: Path) -> dict:
    discoverability = parse_shipwise_discoverability(project_yaml)
    topics = discoverability.get("topics")
    keywords = discoverability.get("keywords")
    text_fields = {
        field: discoverability.get(field, "")
        for field in ("description", "primary_keyword", "homepage_url")
    }
    type_errors = {}
    for field, value in text_fields.items():
        if not isinstance(value, str):
            type_errors[field] = check_item(False, None, f"discoverability.{field} must be a string")
            text_fields[field] = ""
            if field == "homepage_url":
                discoverability[field] = None
    homepage = text_fields["homepage_url"]
    primary_keyword = text_fields["primary_keyword"].strip()
    description = text_fields["description"].strip()

    if not isinstance(topics, list):
        topics = []
    if not isinstance(keywords, list):
        keywords = []
    normalized_homepage = normalize_homepage(homepage, strict=bool(homepage), label="discoverability.homepage_url")
    homepage_has_credentials = False
    if normalized_homepage:
        parsed_homepage = urllib.parse.urlparse(normalized_homepage)
        homepage_has_credentials = parsed_homepage.username is not None or parsed_homepage.password is not None
        normalized_homepage = public_http.redact_url(normalized_homepage)
        discoverability["homepage_url"] = public_http.redact_url(str(homepage))
    community_files = collect_community_files(root)

    invalid_topics = [
        item for item in topics
        if not isinstance(item, str) or re.fullmatch(r"[a-z0-9-]{1,50}", item) is None
    ]
    # Invalid topic values may be unhashable; retain them as error evidence.
    duplicate_topics = []
    for item in topics:
        if topics.count(item) > 1 and item not in duplicate_topics:
            duplicate_topics.append(item)
    duplicate_topics.sort(key=str)
    invalid_keyword_indexes = [
        index for index, item in enumerate(keywords)
        if not isinstance(item, str) or not item.strip()
    ]
    primary_occurrences = description.casefold().count(primary_keyword.casefold()) if primary_keyword and description else 0
    primary_in_description = bool(
        primary_occurrences
    )

    checks = {
        "description": check_item(bool(description), description, "missing discoverability.description"),
        "primary_keyword": check_item(bool(primary_keyword), primary_keyword, "missing discoverability.primary_keyword"),
        "primary_keyword_in_description": check_item(
            primary_in_description,
            {"primary_keyword": primary_keyword, "description": description},
            "primary keyword must appear in discoverability.description",
        ),
        "keywords": check_item(
            bool(keywords) and not invalid_keyword_indexes,
            keywords,
            f"discoverability.keywords has invalid nonblank-string entries at indexes {invalid_keyword_indexes}"
            if invalid_keyword_indexes else "missing discoverability.keywords",
        ),
        "topics_count": check_item(5 <= len(topics) <= 20, len(topics), "topics must contain 5 to 20 entries"),
        "topics_format": check_item(not invalid_topics, invalid_topics, "topics must be lowercase hyphenated GitHub topic slugs"),
        "topics_unique": check_item(not duplicate_topics, duplicate_topics, "topics must not contain duplicates"),
        "homepage_url": check_item(
            bool(normalized_homepage) and not homepage_has_credentials,
            normalized_homepage,
            "URL credentials are not allowed" if homepage_has_credentials else "missing discoverability.homepage_url",
        ),
        "social_image_set": check_item(
            discoverability.get("social_image_set") is True,
            discoverability.get("social_image_set"),
            "social preview image is not marked as set",
        ),
        "readme": check_item(community_files["readme"], community_files["readme"], "README missing"),
        "license": check_item(community_files["license"], community_files["license"], "LICENSE missing"),
        "contributing": check_item(
            community_files["contributing"], community_files["contributing"], "CONTRIBUTING missing"
        ),
        "code_of_conduct": check_item(
            community_files["code_of_conduct"], community_files["code_of_conduct"], "CODE_OF_CONDUCT missing"
        ),
        "security": check_item(community_files["security"], community_files["security"], "SECURITY missing"),
        "issue_templates": check_item(
            community_files["issue_templates"], community_files["issue_templates"], "issue templates missing"
        ),
        "support_path": check_item(
            community_files["issue_templates"] and community_files["contributing"],
            {**community_files, "validation_scope": "candidate file presence; GitHub support path not validated"},
            "support path candidates require both issue templates and CONTRIBUTING",
        ),
    }

    checks.update(type_errors)

    return {
        "project_yaml": str(project_yaml),
        "discoverability": discoverability,
        "community_files": community_files,
        "keyword_observations": {
            "primary_keyword_occurrences": primary_occurrences,
            "matching_basis": "casefolded_substring",
            "interpretation": "Includes word fragments; repetition alone does not establish keyword stuffing.",
        },
        "checks": checks,
    }


def collect_errors(evidence: dict) -> list[dict]:
    errors: list[dict] = []
    for item in evidence.get("manifests", {}).get("errors", []):
        errors.append({"surface": "manifest", **item})

    for homepage, checks in evidence.get("site", {}).items():
        for resource, resource_check in checks.items():
            if resource_check.get("status") == "error" and resource_check.get("observation") != "not_configured":
                errors.append({
                    "surface": "site",
                    "resource": resource,
                    "url": resource_check.get("url", homepage),
                    "reason": resource_check.get("reason", f"{resource} check failed"),
                })

    for name, item in evidence.get("shipwise", {}).get("checks", {}).items():
        if item.get("status") == "error":
            errors.append({"surface": "shipwise", "check": name, "reason": item.get("reason", "check failed")})

    return errors


def crate_registry_check(name: str, local_version: object = None) -> dict:
    url = "https://crates.io/api/v1/crates/" + urllib.parse.quote(name, safe="")
    response = public_http.fetch_public_url(url)
    result = {key: value for key, value in response.items() if key != "body"}
    result.update({"registry": "crates.io", "local_version": local_version})
    if response.get("http_status") == 404:
        result["observation"] = "missing"
    if response.get("status") != "ok":
        return result
    try:
        if response.get("body_truncated"):
            raise ValueError("truncated crates.io response")
        data = json.loads(response.get("body", ""))
        crate = data.get("crate") if isinstance(data, dict) else None
        if not isinstance(crate, dict) or crate.get("id") != name or not isinstance(crate.get("max_version"), str):
            raise ValueError("crates.io response lacks exact crate identity/version")
        result.update({"name": crate["id"], "published_version": crate["max_version"], "package_url": "https://crates.io/crates/" + name})
        if isinstance(local_version, str):
            result["version_matches"] = local_version == crate["max_version"]
    except ValueError:
        result.update({"status": "error", "reason": "cannot verify exact crate identity/version from crates.io response"})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect repo/package SEO baseline evidence.")
    parser.add_argument("--root", default=".", help="Repository root to inspect.")
    parser.add_argument("--homepage", action="append", default=[], help="Homepage URL to check. Can be repeated.")
    parser.add_argument("--npm", action="append", default=[], help="npm package name to verify. Can be repeated.")
    parser.add_argument("--crate", action="append", default=[], help="crates.io package name to verify. Can be repeated.")
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
    repo_view = run_cmd(["gh", "repo", "view", "--json", "nameWithOwner,description,homepageUrl,repositoryTopics,visibility,defaultBranchRef"], cwd=root)
    github_homepages = []
    if repo_view.get("status") == "ok":
        try:
            github = json.loads(repo_view.get("stdout", ""))
            homepage = normalize_homepage(github.get("homepageUrl"), strict=True, label="GitHub homepage") if isinstance(github, dict) else None
            if homepage:
                github_homepages.append(homepage)
        except (ValueError, TypeError):
            if repo_view.get("stdout"):
                repo_view.update({"status": "error", "reason": "cannot collect GitHub homepage from repo metadata"})
    homepages = list(dict.fromkeys(explicit_homepages + infer_homepages(manifests) + github_homepages))
    npm_packages: list[str] = []
    crate_names: list[str] = []
    for option, values, registry, names in (
        ("--npm", args.npm, "npm", npm_packages),
        ("--crate", args.crate, "cargo", crate_names),
    ):
        for name in values:
            name_error = registry_name_error(name, registry, option)
            if name_error:
                manifests["errors"].append(name_error)
            elif name not in names:
                names.append(name)

    for item in manifests.get("npm", []):
        if (
            isinstance(item, dict) and item.get("status") != "error"
            and not item.get("private") and item.get("name") and item["name"] not in npm_packages
        ):
            npm_packages.append(item["name"])
    cargo_packages = [item for item in [manifests.get("cargo"), *manifests.get("cargo_members", [])] if isinstance(item, dict)]
    for cargo in cargo_packages:
        publish = cargo.get("publish")
        public_target = publish is None or publish is True or (isinstance(publish, list) and "crates-io" in publish)
        if cargo.get("status") != "error" and cargo.get("name") and public_target and cargo["name"] not in crate_names:
            crate_names.append(cargo["name"])

    shipwise = {}
    if args.project_yaml:
        project_yaml = Path(args.project_yaml).resolve()
        try:
            shipwise = evaluate_shipwise_project(root, project_yaml)
        except ValueError as exc:
            parser.error(str(exc))

    site = {}
    for homepage in homepages:
        safe_homepage = public_http.redact_url(homepage)
        checks = site_resource_checks(homepage)
        # Redacted URLs can coincide; a passing duplicate must not hide a failure.
        if safe_homepage not in site or checks["homepage"]["status"] == "error":
            site[safe_homepage] = checks

    evidence = {
        "root": str(root),
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "git": {
            "status": run_cmd(["git", "status", "--short", "--branch"], cwd=root),
            "remote": run_cmd(["git", "remote", "get-url", "origin"], cwd=root),
            "head": run_cmd(["git", "rev-parse", "HEAD"], cwd=root),
            "repo_view": repo_view,
        },
        "manifests": manifests,
        "readmes": collect_readmes(root),
        "registry": {
            "npm": {pkg: run_cmd(["npm", "view", "--json", "--registry", "https://registry.npmjs.org", "--", pkg], cwd=root) for pkg in npm_packages},
            "crates": {crate: crate_registry_check(crate, next((item.get("version") for item in cargo_packages if item.get("name") == crate), None)) for crate in crate_names},
        },
        "site": site,
        "community_files": collect_community_files(root),
        "shipwise": shipwise,
    }
    evidence = redact_evidence(evidence)
    errors = collect_errors(evidence)
    evidence["status"] = "error" if errors else "ok"
    evidence["errors"] = errors

    if args.json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print(f"root: {root}")
        print(f"npm packages: {', '.join(npm_packages) or 'none'}")
        print(f"crates: {', '.join(crate_names) or 'none'}")
        print(f"homepages: {', '.join(site) or 'none'}")
        sys.stdout.write(f"status: {evidence['status']}\n")
        if errors:
            sys.stdout.write("errors:\n")
            for item in errors:
                sys.stdout.write(f"- {item.get('surface')}: {item.get('reason')}\n")
        print("Run with --json for full evidence.")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
