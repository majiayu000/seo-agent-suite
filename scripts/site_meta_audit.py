#!/usr/bin/env python3
"""Audit basic crawlable metadata for a public URL."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import public_http
from public_http import fetch_public_url, redact_url  # noqa: E402

_MAX_SITEMAP_CANDIDATES = 10


class MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self.h1: list[str] = []
        self._in_h1 = False
        self._current_h1: list[str] = []
        self.meta: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.base_href: str | None = None
        self._location = "outside_head_body"
        self.json_ld_count = 0
        self._in_json_ld = False
        self.json_ld: list[dict] = []
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag in {"head", "body"}:
            self._location = tag
        elif tag == "base" and self._location == "head" and self.base_href is None:
            self.base_href = attr.get("href")
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
            self._current_h1 = []
        elif tag == "meta":
            attr["location"] = self._location
            self.meta.append(attr)
        elif tag == "link":
            attr["location"] = self._location
            self.links.append(attr)
        elif tag == "script" and attr.get("type", "").lower() == "application/ld+json":
            self.json_ld_count += 1
            self._in_json_ld = True
            self._json_ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"head", "body"}:
            self._location = "outside_head_body"
        elif tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
            text = " ".join("".join(self._current_h1).split())
            if text:
                self.h1.append(text)
        elif tag == "script":
            if self._in_json_ld:
                self.json_ld.append(json_ld_evidence("".join(self._json_ld_parts)))
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_ld_parts.append(data)
        elif self._in_title:
            self.title += data
        elif self._in_h1:
            self._current_h1.append(data)

    def finish(self) -> None:
        self.close()
        if self._in_json_ld:
            self.json_ld.append({"status": "incomplete_script", "types": [], "ids": []})
            self._in_json_ld = False


def json_ld_evidence(body: str) -> dict:
    evidence: dict = {"types": [], "ids": []}
    if not body.strip():
        return {**evidence, "status": "empty"}
    try:
        value = json.loads(body)
    except (ValueError, RecursionError) as exc:
        # Parser diagnostics contain positions, rather than reproducing page data.
        reason = exc.msg if isinstance(exc, json.JSONDecodeError) else "JSON nesting exceeds parser limit"
        return {**evidence, "status": "invalid_json", "error": reason}
    evidence["status"] = "parsed"
    evidence["top_level"] = "object" if isinstance(value, dict) else "array" if isinstance(value, list) else "scalar"
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(reversed(node))
        elif isinstance(node, dict):
            types = node.get("@type", [])
            for item in types if isinstance(types, list) else [types]:
                if isinstance(item, str) and item not in evidence["types"]:
                    evidence["types"].append(item)
            identifier = node.get("@id")
            if isinstance(identifier, str) and identifier not in evidence["ids"]:
                evidence["ids"].append(redact_url(identifier))
            pending.extend(reversed(list(node.values())))
    return evidence


def fetch(url: str, timeout: int = 20) -> dict:
    return fetch_public_url(url, timeout=timeout)


def first_meta(parser: MetaParser, key: str, value: str) -> str | None:
    for item in parser.meta:
        if item.get(key, "").lower() == value.lower():
            return item.get("content") or None
    return None


def all_meta_prefix(parser: MetaParser, key: str, prefix: str) -> dict[str, str]:
    output = {}
    for item in parser.meta:
        name = item.get(key, "")
        if name.startswith(prefix):
            output[name] = item.get("content", "")
    return output


def first_link(parser: MetaParser, rel: str) -> str | None:
    for item in parser.links:
        rels = {part.lower() for part in item.get("rel", "").split()}
        if rel.lower() in rels:
            return item.get("href") or None
    return None


def link_evidence(parser: MetaParser, base_url: str, rel: str) -> list[dict]:
    output = []
    for item in parser.links:
        if rel in item.get("rel", "").lower().split():
            href = item.get("href", "")
            evidence = {**item, "href": redact_url(href)}
            try:
                base = urllib.parse.urljoin(base_url, parser.base_href or "")
                evidence["resolved_url"] = redact_url(urllib.parse.urljoin(base, href)) if href else None
            except ValueError:
                evidence["resolved_url"] = None
                evidence["resolution_error"] = "invalid document base or link URL"
            output.append(evidence)
    return output


def resource_candidates(base_url: str, filename: str) -> list[str]:
    parsed = urllib.parse.urlparse(base_url)
    origin_relative = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/" + filename, "", "", ""))
    if filename != "sitemap.xml":
        return [origin_relative]
    project_relative = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/" + filename, "", "", "")
    )
    page_relative = urllib.parse.urljoin(base_url, filename)
    return list(dict.fromkeys([origin_relative, page_relative, project_relative]))


def check_candidates(base_url: str, filename: str) -> list[dict]:
    return [resource_check(fetch(candidate), filename) for candidate in resource_candidates(base_url, filename)]


def resource_check(item: dict, filename: str) -> dict:
    evidence = sitemap_evidence(item) if filename == "sitemap.xml" and item.get("http_status") == 200 else None
    present, reason = resource_present(item, filename, evidence)
    result = {key: value for key, value in item.items() if key != "body"}
    result["present"] = present
    if reason:
        result["reason"] = reason
    if filename == "robots.txt" and item.get("http_status") in {404, 410}:
        result["observation"] = "not_configured"
    if evidence is not None:
        result["sitemap_evidence"] = evidence
    return result


def crawl_resource_checks(base_url: str) -> dict:
    robots = [fetch(candidate) for candidate in resource_candidates(base_url, "robots.txt")]
    declarations = []
    for item in robots:
        if item.get("status") != "ok" or item.get("http_status") != 200:
            continue
        for line in str(item.get("body") or "").splitlines():
            name, separator, value = line.partition(":")
            if separator and name.strip().lower() == "sitemap":
                target = value.split("#", 1)[0].strip()
                if target:
                    declarations.append(target)
    # Each candidate still goes through fetch's public URL/DNS/redirect boundary.
    candidates = list(dict.fromkeys(declarations + resource_candidates(base_url, "sitemap.xml")))
    checked = candidates[:_MAX_SITEMAP_CANDIDATES]
    robots_truncated = any(item.get("body_truncated") for item in robots)
    return {
        "robots_txt": [resource_check(item, "robots.txt") for item in robots],
        "sitemap_xml": [resource_check(fetch(candidate), "sitemap.xml") for candidate in checked],
        "sitemap_discovery": {
            "declaration_count": len(declarations), "unique_candidate_count": len(candidates),
            "checked_count": len(checked), "omitted_count": len(candidates) - len(checked),
            "complete": len(checked) == len(candidates) and not robots_truncated,
            "robots_body_truncated": robots_truncated,
        },
    }


def sitemap_evidence(item: dict) -> dict:
    truncated = bool(item.get("body_truncated"))
    evidence: dict = {"scope": "sample" if truncated else "complete_response", "well_formed": None if truncated else False,
                      "root": None, "namespace": None, "expected_namespace": False,
                      "loc_count": 0, "non_absolute_loc_count": 0}
    parser = ElementTree.XMLPullParser(events=("start", "end"))
    try:
        parser.feed(str(item.get("body") or "").strip())
        if not truncated:
            parser.close()
        for event, element in parser.read_events():
            if event == "start" and evidence["root"] is None:
                namespace, _, root = element.tag.rpartition("}")
                evidence["root"] = root
                evidence["namespace"] = namespace.lstrip("{") or None
                evidence["expected_namespace"] = evidence["namespace"] == "http://www.sitemaps.org/schemas/sitemap/0.9"
            if event == "end" and element.tag.rsplit("}", 1)[-1] == "loc":
                evidence["loc_count"] += 1
                try:
                    location = urllib.parse.urlsplit((element.text or "").strip())
                    absolute = location.scheme in {"http", "https"} and bool(location.netloc)
                except ValueError:
                    absolute = False
                if not absolute:
                    evidence["non_absolute_loc_count"] += 1
        if not truncated:
            evidence["well_formed"] = True
    except ElementTree.ParseError as exc:
        evidence["error"] = str(exc)
    return evidence


def resource_present(item: dict, filename: str, evidence: dict | None = None) -> tuple[bool, str]:
    if item.get("status") != "ok" or item.get("http_status") != 200:
        return False, item.get("reason", "not HTTP 200")
    body = str(item.get("body") or "").strip()
    content_type = str(item.get("content_type") or "").lower()
    if "<html" in body[:500].lower() or "text/html" in content_type:
        return False, "looks like HTML, not a crawl resource"
    if filename == "sitemap.xml":
        evidence = evidence if evidence is not None else sitemap_evidence(item)
        if evidence.get("error") or evidence.get("root") is None:
            return False, "invalid sitemap XML"
        if evidence["root"] not in {"urlset", "sitemapindex"}:
            return False, "missing sitemap XML root"
    return True, ""


def audit(url: str) -> dict:
    collected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    page = fetch(url)
    result = {"url": redact_url(url), "collected_at": collected_at,
              "capture": {"scope": "raw_html", "body_truncated": page.get("body_truncated"), "rendered": False},
              "page": {key: value for key, value in page.items() if key != "body"}}
    if page.get("status") != "ok":
        return result

    parser = MetaParser()
    parser.feed(page["body"])
    parser.finish()
    base = page.get("url") or url
    resources = crawl_resource_checks(base)
    robots, sitemap = resources["robots_txt"], resources["sitemap_xml"]

    result.update(
        {
            "title": " ".join(parser.title.split()),
            "meta_description": first_meta(parser, "name", "description"),
            "robots_meta": first_meta(parser, "name", "robots"),
            "robots_meta_declarations": [item for item in parser.meta if item.get("name", "").lower() == "robots" or item.get("name", "").lower().startswith("googlebot")],
            "canonical": redact_url(first_link(parser, "canonical")) if first_link(parser, "canonical") else None,
            "canonicals": link_evidence(parser, base, "canonical"),
            "hreflang": [item for item in link_evidence(parser, base, "alternate") if item.get("hreflang")],
            "open_graph": all_meta_prefix(parser, "property", "og:"),
            "twitter": all_meta_prefix(parser, "name", "twitter:"),
            "json_ld_count": parser.json_ld_count,
            "json_ld": parser.json_ld,
            "h1": parser.h1,
            "checks": {
                "has_title": bool(" ".join(parser.title.split())),
                "has_meta_description": bool(first_meta(parser, "name", "description")),
                "has_canonical": bool(first_link(parser, "canonical")),
                "has_og_title": bool(all_meta_prefix(parser, "property", "og:").get("og:title")),
                "has_json_ld": parser.json_ld_count > 0,
                "has_robots_txt": any(item.get("present") for item in robots),
                "has_sitemap_xml": any(item.get("present") for item in sitemap),
                "robots_txt": robots,
                "sitemap_xml": sitemap,
                "sitemap_discovery": resources["sitemap_discovery"],
            },
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit crawlable page metadata.")
    parser.add_argument("url", help="Public URL to inspect.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args()
    # Leave URL/DNS validation to audit→fetch so --json always emits structured
    # page errors (exit 1) instead of argparse usage text (exit 2) on resolution failures.
    result = audit(args.url)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        page = result.get("page", {})
        print(f"url: {result.get('url', args.url)}")
        print(f"status: {page.get('http_status')}")
        if page.get("status") == "error" and page.get("reason"):
            print(f"reason: {page.get('reason')}")
        print(f"title: {result.get('title')}")
        print(f"description: {result.get('meta_description')}")
        print(f"canonical: {result.get('canonical')}")
    return 0 if result.get("page", {}).get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
