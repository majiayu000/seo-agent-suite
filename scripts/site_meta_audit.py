#!/usr/bin/env python3
"""Audit basic crawlable metadata for a public URL."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser


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
    request = urllib.request.Request(url, headers={"User-Agent": "github-repo-seo-skill/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(1_000_000)
            return {
                "status": "ok",
                "url": response.geturl(),
                "http_status": response.status,
                "content_type": response.headers.get("content-type"),
                "body": body.decode(response.headers.get_content_charset() or "utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as exc:
        return {"status": "error", "url": url, "http_status": exc.code, "reason": str(exc)}
    except urllib.error.URLError as exc:
        return {"status": "error", "url": url, "reason": str(exc.reason)}
    except TimeoutError:
        return {"status": "error", "url": url, "reason": "timeout"}


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
        results.append({key: value for key, value in item.items() if key != "body"})
    return results


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
                "has_robots_txt": any(item.get("http_status") == 200 for item in robots),
                "has_sitemap_xml": any(item.get("http_status") == 200 for item in sitemap),
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

    result = audit(args.url)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"url: {args.url}")
        print(f"status: {result.get('page', {}).get('http_status')}")
        print(f"title: {result.get('title')}")
        print(f"description: {result.get('meta_description')}")
        print(f"canonical: {result.get('canonical')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
