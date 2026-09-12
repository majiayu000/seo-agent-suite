#!/usr/bin/env python3
"""Audit basic crawlable metadata for a public URL."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import public_http
from public_http import charset_from_content_type, fetch_public_http

# Re-export for tests that patch socket/connect helpers through this script.
socket = public_http.socket
connect_endpoint = public_http.connect_endpoint
request_public_url_once = public_http.request_public_url_once


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
        self.json_ld_count = 0
        self._in_json_ld = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
            self._current_h1 = []
        elif tag == "meta":
            self.meta.append(attr)
        elif tag == "link":
            self.links.append(attr)
        elif tag == "script" and attr.get("type", "").lower() == "application/ld+json":
            self.json_ld_count += 1
            self._in_json_ld = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
            text = " ".join("".join(self._current_h1).split())
            if text:
                self.h1.append(text)
        elif tag == "script":
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._in_h1:
            self._current_h1.append(data)


def fetch(url: str, timeout: int = 20) -> dict:
    result = fetch_public_http(url, timeout=timeout, max_body=1_000_000)
    if result.get("status") != "ok":
        return {key: value for key, value in result.items() if key != "body"}

    body = result.get("body") or b""
    charset = charset_from_content_type(result.get("content_type")) or "utf-8"
    return {
        "status": "ok",
        "url": result["url"],
        "http_status": result["http_status"],
        "content_type": result.get("content_type"),
        "body": body.decode(charset, errors="replace"),
    }


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


def resource_candidates(base_url: str, filename: str) -> list[str]:
    parsed = urllib.parse.urlparse(base_url)
    origin = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    page_relative = urllib.parse.urljoin(base_url if base_url.endswith("/") else base_url.rsplit("/", 1)[0] + "/", filename)
    origin_relative = origin.rstrip("/") + "/" + filename
    return list(dict.fromkeys([page_relative, origin_relative]))


def check_candidates(base_url: str, filename: str) -> list[dict]:
    results = []
    for candidate in resource_candidates(base_url, filename):
        item = fetch(candidate)
        present, reason = resource_present(item, filename)
        public_item = {key: value for key, value in item.items() if key != "body"}
        public_item["present"] = present
        if reason:
            public_item["reason"] = reason
        results.append(public_item)
    return results


def resource_present(item: dict, filename: str) -> tuple[bool, str]:
    if item.get("status") != "ok" or item.get("http_status") != 200:
        return False, item.get("reason", "not HTTP 200")
    body = str(item.get("body") or "").strip()
    content_type = str(item.get("content_type") or "").lower()
    if "<html" in body[:500].lower() or "text/html" in content_type:
        return False, "looks like HTML, not a crawl resource"
    if filename == "sitemap.xml" and "<urlset" not in body[:1000] and "<sitemapindex" not in body[:1000]:
        return False, "missing sitemap XML root"
    return True, ""


def audit(url: str) -> dict:
    page = fetch(url)
    result = {"url": url, "page": {key: value for key, value in page.items() if key != "body"}}
    if page.get("status") != "ok":
        return result

    parser = MetaParser()
    parser.feed(page["body"])
    base = page.get("url") or url
    robots = check_candidates(base, "robots.txt")
    sitemap = check_candidates(base, "sitemap.xml")

    result.update(
        {
            "title": " ".join(parser.title.split()),
            "meta_description": first_meta(parser, "name", "description"),
            "robots_meta": first_meta(parser, "name", "robots"),
            "canonical": first_link(parser, "canonical"),
            "open_graph": all_meta_prefix(parser, "property", "og:"),
            "twitter": all_meta_prefix(parser, "name", "twitter:"),
            "json_ld_count": parser.json_ld_count,
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
            },
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit crawlable page metadata.")
    parser.add_argument("url", help="Public URL to inspect.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        parser.error(f"url must be an http(s) URL: {args.url}")
    if parsed.username is not None or parsed.password is not None:
        parser.error("URL credentials are not allowed")

    result = audit(args.url)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"url: {args.url}")
        print(f"status: {result.get('page', {}).get('http_status')}")
        print(f"title: {result.get('title')}")
        print(f"description: {result.get('meta_description')}")
        print(f"canonical: {result.get('canonical')}")
    return 0 if result.get("page", {}).get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
