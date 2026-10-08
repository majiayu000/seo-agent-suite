#!/usr/bin/env python3
"""Audit basic crawlable metadata for a public URL."""

from __future__ import annotations

import argparse
import json
import re
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
_CRAWLERS = ("Googlebot", "OAI-SearchBot", "GPTBot")
_SEVERITY = {"info": 0, "warning": 1, "error": 2}
_LIMIT_REASONS = {"http_attempt_budget_exhausted", "http_body_budget_exhausted"}


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
        self._location = "head"
        self.json_ld_count = 0
        self._in_json_ld = False
        self.json_ld: list[dict] = []
        self._json_ld_parts: list[str] = []
        self._template_depth = 0
        self._svg_depth = 0
        self._raw_text_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "template":
            self._template_depth += 1
        if self._template_depth:
            return
        # HTML permits an omitted head tag. The first body element closes the
        # implicit head; subsequent metadata must not reopen it.
        if self._location == "head" and tag not in {
            "html", "head", "base", "link", "meta", "title", "style", "script", "noscript",
        }:
            self._location = "body"
        if tag == "svg":
            self._svg_depth += 1
        if tag in {"script", "style"}:
            self._raw_text_tag = tag
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag in {"head", "body"}:
            self._location = tag
        elif tag == "base" and self._location == "head" and self.base_href is None:
            self.base_href = attr.get("href")
        elif tag == "title" and not self._svg_depth:
            self._in_title = True
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            # Recover lexical evidence at heading boundaries, not an HTML5 DOM.
            self._finish_h1()
            self._in_h1 = tag == "h1"
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
        if self._template_depth:
            if tag == "template":
                self._template_depth -= 1
            return
        if tag == "svg":
            self._svg_depth = max(0, self._svg_depth - 1)
        if tag == self._raw_text_tag:
            self._raw_text_tag = None
        if tag in {"head", "body"}:
            self._location = "outside_head_body"
        elif tag == "title":
            self._in_title = False
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._finish_h1()
        elif tag == "script":
            if self._in_json_ld:
                self.json_ld.append(json_ld_evidence("".join(self._json_ld_parts)))
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._template_depth:
            return
        if self._in_json_ld:
            self._json_ld_parts.append(data)
        elif self._raw_text_tag is not None:
            return
        elif self._in_title:
            self.title += data
        elif self._in_h1:
            self._current_h1.append(data)
        elif self._location == "head" and data.strip():
            self._location = "body"

    def _finish_h1(self) -> None:
        """Retain active nonempty H1 text once, including malformed markup."""
        if self._in_h1:
            text = " ".join("".join(self._current_h1).split())
            if text:
                self.h1.append(text)
        self._in_h1 = False
        self._current_h1 = []

    def finish(self) -> None:
        self.close()
        self._finish_h1()
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


def fetch(url: str, timeout: int = 20, *, budget: public_http.HTTPAttemptBudget | None = None,
          body_budget: public_http.HTTPBodyBudget | None = None) -> dict:
    return fetch_public_url(url, timeout=timeout,
                            **({"budget": budget} if budget is not None else {}),
                            **({"body_budget": body_budget} if body_budget is not None else {}))


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


def open_graph_evidence(parser: MetaParser) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Return a compatibility summary and sanitized, ordered OG declarations.

    The first root of each media kind (including :url aliases) owns only its
    properties before the next OG root. Other OG fields retain last-value
    summary behavior; the declarations, not the summary, preserve all evidence.
    """
    summary: dict[str, str] = {}
    declarations: list[dict[str, str]] = []
    seen_media: set[str] = set()
    active_media: str | None = None
    for item in parser.meta:
        name = item.get("property", "")
        if not name.startswith("og:"):
            continue
        # Match the existing URL-userinfo redaction policy, including URLs in
        # free text. Do not copy arbitrary, potentially sensitive HTML attributes.
        content = re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]+",
                         lambda match: redact_url(match.group()),
                         redact_url(item.get("content", "")))
        declarations.append({"property": name, "content": content,
                             "location": item.get("location", "outside_head_body")})
        parts = name.split(":")
        media = parts[1] if parts[1] in {"image", "video", "audio"} else None
        if media and (len(parts) == 2 or parts[2:] == ["url"]):
            active_media = media if media not in seen_media else None
            seen_media.add(media)
            if active_media:
                summary[name] = content
        elif media:
            if active_media == media:
                # First declaration wins even when its content is blank.
                summary.setdefault(name, content)
        else:
            summary[name] = content
            if len(parts) == 2:
                active_media = None
    return summary, declarations


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


def encoded_resource(item: dict) -> bool:
    encoding = str(item.get("content_encoding") or "").strip().lower()
    media_type = str(item.get("content_type") or "").split(";", 1)[0].strip().lower()
    return encoding not in {"", "identity"} or media_type in {"application/gzip", "application/x-gzip", "application/zip"}


def resource_check(item: dict, filename: str) -> dict:
    evidence = sitemap_evidence(item) if filename == "sitemap.xml" and item.get("http_status") == 200 else None
    present, reason = resource_present(item, filename, evidence)
    result = {key: value for key, value in item.items() if key != "body"}
    result["present"] = (None if item.get("reason_code") in _LIMIT_REASONS and not present else present)
    if reason:
        result["reason"] = ("Body allowance left resource evidence incomplete; absence is unknown"
                            if item.get("reason_code") == "http_body_budget_exhausted" and item.get("status") == "ok"
                            else reason)
    if item.get("status") == "ok" and encoded_resource(item):
        result["observation"] = "unsupported_encoding"
    if filename == "robots.txt" and item.get("http_status") in {404, 410}:
        result["observation"] = "not_configured"
    if evidence is not None:
        result["sitemap_evidence"] = evidence
    return result


def robots_path(value: str) -> str:
    """Compare UTF-8 and percent escapes without decoding reserved characters."""
    value = urllib.parse.quote(value, safe="/%:*?$!&'()+,;=@[]-._~")
    def normalize(match: re.Match) -> str:
        byte = int(match.group(1), 16)
        char = chr(byte)
        return char if char.isascii() and (char.isalnum() or char in "-._~") else "%" + match.group(1).upper()
    return re.sub(r"%([0-9a-fA-F]{2})", normalize, value)


def robots_match(pattern: str, target: str) -> bool:
    # Literal segments avoid regex backtracking on untrusted wildcard patterns.
    anchored = pattern.endswith("$")
    parts = (pattern[:-1] if anchored else pattern).split("*")
    if not target.startswith(parts[0]):
        return False
    offset = len(parts[0])
    if len(parts) == 1:
        return not anchored or offset == len(target)
    for part in parts[1:-1]:
        found = target.find(part, offset)
        if found < 0:
            return False
        offset = found + len(part)
    if anchored:
        return target.endswith(parts[-1]) and len(target) - len(parts[-1]) >= offset
    return target.find(parts[-1], offset) >= 0


def robots_access(item: dict, url: str) -> dict:
    """Local rule evaluation, not proof of CDN access or crawler behavior/cache."""
    base = {"allowed": None, "matched_agents": [], "matched_rule": None}
    if item.get("http_status") in {404, 410}:
        return {agent: {**base, "allowed": True, "reason": "not_configured"} for agent in _CRAWLERS}
    if item.get("status") != "ok" or item.get("http_status") != 200 or item.get("body_truncated") or not resource_present(item, "robots.txt")[0]:
        return {agent: {**base, "reason": "robots_unavailable_or_incomplete"} for agent in _CRAWLERS}
    groups = []
    agents, rules = [], []
    has_rule = False
    for number, line in enumerate(str(item.get("body") or "").lstrip("\ufeff").splitlines(), 1):
        name, separator, value = line.split("#", 1)[0].partition(":")
        if not separator:
            continue
        name, value = name.strip().lower(), value.strip()
        if name == "user-agent":
            if has_rule:
                groups.append((agents, rules))
                agents, rules, has_rule = [], [], False
            agents.append(value.lower())
        elif name in {"allow", "disallow"} and agents:
            has_rule = True
            if value.startswith("/"):
                rules.append({"directive": name, "pattern": value, "line": number})
    groups.append((agents, rules))
    parsed = urllib.parse.urlsplit(url)
    target = robots_path((parsed.path or "/") + ("?" + parsed.query if parsed.query else ""))
    output = {}
    for agent in _CRAWLERS:
        # Product-token match, with Google's documented version/wildcard suffixes.
        selected = [(names, entries) for names, entries in groups if any(
            name.split("/", 1)[0].rstrip("*") == agent.lower() for name in names if name != "*")]
        if not selected:
            selected = [(names, entries) for names, entries in groups if "*" in names]
        matches = [rule for _, entries in selected for rule in entries if robots_match(robots_path(rule["pattern"]), target)]
        winner = max(matches, key=lambda rule: (len(urllib.parse.unquote_to_bytes(robots_path(rule["pattern"]).rstrip("*"))), rule["directive"] == "allow"), default=None)
        output[agent] = {
            "allowed": winner is None or winner["directive"] == "allow" or parsed.path == "/robots.txt",
            "matched_agents": sorted({name for names, _ in selected for name in names}),
            "matched_rule": {**winner, "pattern": redact_url(winner["pattern"])} if winner else None,
            "reason": "matched_rule" if winner else "no_matching_rule",
        }
    return output


def crawl_resource_checks(base_url: str, *, budget: public_http.HTTPAttemptBudget | None = None,
          body_budget: public_http.HTTPBodyBudget | None = None) -> dict:
    options = {"budget": budget} if budget is not None else {}
    if body_budget is not None:
        options["body_budget"] = body_budget
    robots = [fetch(candidate, **options) for candidate in resource_candidates(base_url, "robots.txt")]
    declarations = []
    for item in robots:
        if not resource_present(item, "robots.txt")[0]:
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
    sitemap_checks = []
    checked_count = 0
    for candidate in checked:
        before = budget.attempts_used if budget is not None else body_budget.attempts_started if body_budget is not None else 0
        item = fetch(candidate, **options)
        # A refused, never-started candidate is unavailable, not checked. A
        # started redirect/fallback chain remains counted with its evidence.
        after = budget.attempts_used if budget is not None else body_budget.attempts_started if body_budget is not None else 0
        if item.get("reason_code") not in _LIMIT_REASONS or after > before:
            checked_count += 1
        sitemap_checks.append(resource_check(item, "sitemap.xml"))
    budget_denied = any(item.get("reason_code") in _LIMIT_REASONS for item in robots + sitemap_checks)
    robots_unavailable = (budget is not None or body_budget is not None) and any(
        item.get("status") != "ok" and item.get("http_status") not in {404, 410} for item in robots
    )
    return {
        "robots_txt": [resource_check(item, "robots.txt") for item in robots],
        "robots_access": robots_access(robots[0], base_url),
        "sitemap_xml": sitemap_checks,
        "sitemap_discovery": {
            "declaration_count": len(declarations), "unique_candidate_count": len(candidates),
            "checked_count": checked_count, "omitted_count": len(candidates) - checked_count,
            "complete": len(checked) == len(candidates) and not robots_truncated and not any(encoded_resource(item) for item in robots) and not budget_denied and not robots_unavailable,
            "robots_body_truncated": robots_truncated,
        },
    }


def sitemap_evidence(item: dict) -> dict:
    truncated = bool(item.get("body_truncated"))
    evidence: dict = {"scope": "sample" if truncated else "complete_response", "well_formed": None if truncated else False,
                      "root": None, "namespace": None, "expected_namespace": False,
                      "loc_count": 0, "non_absolute_loc_count": 0}
    if encoded_resource(item):
        return {**evidence, "scope": "unsupported_encoding", "well_formed": None}
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
    if encoded_resource(item):
        return False, "encoded response is not decompressed by this audit"
    body = str(item.get("body") or "").strip()
    content_type = str(item.get("content_type") or "").lower()
    # Sitemap XML can contain comments or XHTML-prefixed child elements.
    # Let its parsed root identify the document, rather than arbitrary text.
    if "text/html" in content_type or (filename != "sitemap.xml" and "<html" in body[:500].lower()):
        return False, "looks like HTML, not a crawl resource"
    if filename == "sitemap.xml":
        evidence = evidence if evidence is not None else sitemap_evidence(item)
        if evidence.get("error") or evidence.get("root") is None:
            return False, "invalid sitemap XML"
        if evidence["root"] not in {"urlset", "sitemapindex"}:
            return False, "missing sitemap XML root"
        # Preserve the existing namespace-less compatibility mode, whose
        # expected_namespace evidence remains false. Foreign vocabularies
        # must not pass merely because their local root name is familiar.
        if evidence.get("namespace") is not None and not evidence.get("expected_namespace"):
            return False, "unexpected sitemap XML namespace"
    return True, ""


def indexing_evidence(parser: MetaParser | None, page: dict) -> dict:
    evidence = [{"source": "meta", "value": item.get("content", "")} for item in (parser.meta if parser is not None else [])
                if item.get("location") == "head" and item.get("name", "").lower() in {"robots", "googlebot"}]
    noindex = any(set(re.split(r"[\s,]+", item["value"].lower())) & {"noindex", "none"} for item in evidence)
    for header in page.get("x_robots_tag", []):
        scope = ""
        for part in header.lower().split(","):
            prefix, separator, value = part.strip().partition(":")
            # These are parameterized directives, not crawler scopes.
            if separator and prefix in {"unavailable_after", "max-snippet", "max-image-preview", "max-video-preview"}:
                continue
            if separator and re.fullmatch(r"[a-z_-]+", prefix.strip()):
                scope, part = prefix.strip(), value
            if scope in {"", "googlebot"} and set(part.strip().split()) & {"noindex", "none"}:
                noindex = True
        evidence.append({"source": "x_robots_tag", "value": header})
    return {"crawler": "Googlebot", "noindex": True if noindex else None if parser is None or page.get("body_truncated") else False,
            "evidence": evidence, "scope": "observed_raw_response", "indexed": "unknown"}


def canonical_key(url: str) -> tuple:
    parsed = urllib.parse.urlsplit(url)
    return (parsed.scheme.lower(), (parsed.hostname or "").lower(),
            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
            robots_path(parsed.path or "/"), robots_path(parsed.query))


def canonical_assessment(result: dict) -> dict:
    declarations = result["canonicals"]
    targets = []
    invalid = False
    for item in declarations:
        target = item.get("resolved_url")
        try:
            parsed = urllib.parse.urlsplit(target or "")
            valid = (parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.port != 0
                     and not parsed.fragment and not any(char.isspace() for char in target or "")
                     and item.get("location") == "head")
        except ValueError:
            valid = False
        invalid |= not valid
        if valid:
            targets.append(urllib.parse.urldefrag(target)[0])
    targets = list({canonical_key(target): target for target in targets}.values())
    complete = not result["capture"]["body_truncated"]
    # HTTP Link declarations are retained, but aren't parsed by this HTML check.
    headers_need_review = any(re.search(r'\brel\s*=\s*(?:"[^"\n]*\bcanonical\b|canonical(?:\s|;|,|$))', header, re.I)
                              for header in result["page"].get("link_headers", []))
    if invalid:
        status = "invalid"
    elif len(targets) > 1:
        status = "conflicting"
    elif not complete or headers_need_review:
        status = "unknown"
    elif not targets:
        status = "missing"
    else:
        status = "self" if canonical_key(targets[0]) == canonical_key(result["page"]["url"]) else "other"
    return {"status": status, "targets": targets, "declaration_count": len(declarations),
            "scope": "html_links", "http_link_headers_need_review": headers_need_review}


def assess(result: dict, parser: MetaParser | None, resources: dict | None) -> None:
    findings = result["findings"]
    def add(code: str, severity: str, message: str, evidence: str, confidence: str = "Confirmed") -> None:
        findings.append({"code": code, "severity": severity, "confidence": confidence, "message": message, "evidence": evidence})
    indexing = indexing_evidence(parser, result["page"])
    result["assessment"] = {"indexing": indexing, "html_metadata_applicable": parser is not None}
    if indexing["noindex"]:
        add("noindex_declared", "error", "The observed response declares noindex for Googlebot; this does not measure current index state.", "assessment.indexing")
    if parser is None:
        return
    canonical = canonical_assessment(result)
    json_ld = result["json_ld"]
    parse_valid = all(item["status"] == "parsed" for item in json_ld) if json_ld else None
    if result["capture"]["body_truncated"]:
        parse_valid = None
        add("capture_incomplete", "warning", "HTML is truncated; absence and complete validation are unknown.", "capture")
    result["assessment"].update({
        "crawl_access": resources["robots_access"], "indexing": indexing, "canonical": canonical,
        "json_ld_parse_valid": parse_valid,
        "observations": {"title_length": len(result["title"]), "description_length": len(result["meta_description"] or ""), "nonempty_h1_count": len(result["h1"])},
    })
    for agent, access in resources["robots_access"].items():
        if access["allowed"] is False:
            add("robots_disallow_" + agent.lower(), "error" if agent == "Googlebot" else "info", f"robots.txt disallows this URL for {agent}; this does not prove deindexing or actual network access.", "assessment.crawl_access." + agent)
        elif access["allowed"] is None:
            add("robots_unknown_" + agent.lower(), "warning", f"Cannot determine robots.txt permission for {agent} from this response.", "assessment.crawl_access." + agent)
    if indexing["noindex"] and resources["robots_access"]["Googlebot"]["allowed"] is False:
        add("noindex_hidden_by_robots", "warning", "A robots.txt block can prevent Googlebot from seeing noindex; removal from the index is not established.", "assessment")
    if canonical["status"] in {"invalid", "conflicting"}:
        add("canonical_" + canonical["status"], "error", "HTML canonical declarations are invalid or conflicting.", "canonicals")
    elif canonical["status"] == "other":
        add("canonical_other", "warning", "HTML canonical points to another URL; verify that this is intentional. It is a signal, not a noindex directive.", "canonicals", "Likely")
    elif canonical["status"] == "unknown":
        add("canonical_unknown", "warning", "Canonical assessment is incomplete; review capture coverage and HTTP Link headers.", "assessment.canonical")
    if len(result["canonicals"]) > 1:
        add("canonical_multiple", "warning", "Multiple HTML canonical declarations were observed.", "canonicals")
    if any(item["status"] in {"invalid_json", "empty"} for item in json_ld):
        add("json_ld_parse_error", "error", "At least one JSON-LD block is empty or invalid JSON. Parsing is separate from schema validity.", "json_ld")
    elif any(item["status"] == "incomplete_script" for item in json_ld):
        add("json_ld_incomplete", "warning", "An unfinished JSON-LD script cannot be validated.", "json_ld")
    for key in ("title", "meta_description"):
        present = bool((result[key] or "").strip()) if key == "meta_description" else bool(result[key])
        if not present and not result["capture"]["body_truncated"]:
            add(key + "_missing", "warning", f"No nonempty {key} was observed.", key)
    if len(result["h1"]) != 1:
        add("h1_review", "info", "Review the observed heading hierarchy in context; H1 count alone is not an indexing failure.", "h1", "Likely")


def _execution_result(result: dict, budget: public_http.HTTPAttemptBudget | None,
                      body_budget: public_http.HTTPBodyBudget | None = None) -> dict:
    if budget is None and body_budget is None:
        return result
    events = []
    substantive = False
    def inspect(value: object, path: str) -> None:
        nonlocal substantive
        if isinstance(value, dict):
            if value.get("reason_code") in _LIMIT_REASONS:
                events.append({"reason_code": value["reason_code"], "stage": "page" if path == "page" else "crawl_resources", "evidence": path})
            if value.get("http_status") is not None or value.get("redirects") or value.get("endpoint_errors") or value.get("status") == "error":
                substantive = True
            for key, child in value.items():
                inspect(child, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                inspect(child, f"{path}[{index}]")
    inspect(result, "")
    result["execution"] = {
        "limits": {**({"max_http_attempts": budget.max_http_attempts} if budget is not None else {}),
                   **({"max_http_body_bytes": body_budget.max_http_body_bytes} if body_budget is not None else {})},
        "usage": {**({"http_attempts": budget.attempts_used} if budget is not None else {}),
                  **({"http_body_bytes": body_budget.bytes_used} if body_budget is not None else {})},
        "completion": "complete" if not events else "partial" if substantive else "blocked",
        "limit_events": events,
        "coverage_scope": "completion describes only collection omitted by this attempt allowance, not full audit coverage",
        "coverage_exclusions": ["DNS, HTTP headers, TLS/proxy framing and subprocess requests are not counted", "No elapsed-time or response-byte allowance is enforced", "Unknown robots declarations are not included in known-candidate counts"],
    }
    if body_budget is not None:
        result["execution"]["coverage_scope"] = "completion describes only collection omitted by the selected allowances, not full audit coverage"
        result["execution"]["coverage_exclusions"] = [
            "Body bytes count encoded payload exposed by reads, including lookahead and exposed partial failures",
            "Physical network traffic, socket buffering, headers, framing and bytes hidden by failed reads are not counted",
            "No elapsed-time, decompression, parser-depth or total-memory bound is enforced",
            "Unknown robots declarations are not included in known-candidate counts",
        ]
    if events and result["page"].get("status") == "ok":
        for code in sorted({event["reason_code"] for event in events}):
            message = ("HTTP attempt allowance stopped auxiliary collection; unchecked resources are unavailable, not missing."
                       if code == "http_attempt_budget_exhausted" else
                       "HTTP exposed body-payload byte allowance limited collection; incomplete or unchecked evidence cannot prove absence.")
            result["findings"].append({"code": code, "severity": "warning", "confidence": "Confirmed",
                                       "message": message, "evidence": "execution.limit_events"})
    return result


def _resource_presence(items: list[dict]) -> bool | None:
    if any(item.get("present") for item in items):
        return True
    if any(item.get("present") is None for item in items):
        return None
    return False


def audit(url: str, *, max_http_attempts: int | None = None, max_http_body_bytes: int | None = None) -> dict:
    budget = public_http.HTTPAttemptBudget(max_http_attempts) if max_http_attempts is not None else None
    options = {"budget": budget} if budget is not None else {}
    body_budget = public_http.HTTPBodyBudget(max_http_body_bytes) if max_http_body_bytes is not None else None
    if body_budget is not None:
        options["body_budget"] = body_budget
    collected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    page = fetch(url, **options)
    result = {"url": redact_url(url), "collected_at": collected_at,
              "capture": {"scope": "raw_html", "body_truncated": page.get("body_truncated"), "rendered": False},
              "page": {key: value for key, value in page.items() if key != "body"}, "findings": []}
    if page.get("status") != "ok":
        result["findings"].append({"code": "page_fetch_error", "severity": "error", "confidence": "Confirmed",
                                   "message": "Page fetch failed; metadata assessment is unavailable.", "evidence": "page"})
        return _execution_result(result, budget, body_budget)

    media_type = str(page.get("content_type") or "").split(";", 1)[0].strip().lower()
    encoded = encoded_resource(page)
    if encoded or media_type not in {"text/html", "application/xhtml+xml"}:
        reason = "unsupported_encoding" if encoded else "non_html" if media_type else "unknown_media_type"
        result["capture"]["scope"] = "raw_response"
        result["findings"].append({"code": "html_metadata_unavailable", "severity": "warning", "confidence": "Confirmed",
                                   "message": f"HTML metadata checks were skipped ({reason}); no missing-metadata verdict is made.",
                                   "evidence": "page"})
        assess(result, None, None)
        return _execution_result(result, budget, body_budget)

    parser = MetaParser()
    parser.feed(page["body"])
    parser.finish()
    open_graph, open_graph_declarations = open_graph_evidence(parser)
    base = page.get("url") or url
    resources = crawl_resource_checks(base, **options)
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
            "open_graph": open_graph,
            "open_graph_declarations": open_graph_declarations,
            "twitter": all_meta_prefix(parser, "name", "twitter:"),
            "json_ld_count": parser.json_ld_count,
            "json_ld": parser.json_ld,
            "h1": parser.h1,
            "checks": {
                "has_title": bool(" ".join(parser.title.split())),
                "has_meta_description": bool((first_meta(parser, "name", "description") or "").strip()),
                "has_canonical": bool(first_link(parser, "canonical")),
                "has_og_title": bool(open_graph.get("og:title")),
                "has_json_ld": parser.json_ld_count > 0,
                "has_robots_txt": _resource_presence(robots),
                "has_sitemap_xml": _resource_presence(sitemap),
                "robots_txt": robots,
                "sitemap_xml": sitemap,
                "sitemap_discovery": resources["sitemap_discovery"],
            },
        }
    )
    assess(result, parser, resources)
    return _execution_result(result, budget, body_budget)


def _nonnegative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a nonnegative integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit crawlable page metadata.")
    parser.add_argument("url", help="Public URL to inspect.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--fail-on", choices=tuple(_SEVERITY), help="Exit 1 for findings at this severity or higher; default only fails on page fetch errors.")
    parser.add_argument("--max-http-attempts", type=_nonnegative_int, help="Optional logical target-attempt allowance shared across this audit; 0 starts no HTTP attempts.")
    parser.add_argument("--max-http-body-bytes", type=_nonnegative_int, help="Optional cumulative encoded payload bytes exposed by HTTP reads, including lookahead/partial reads; not network traffic or bytes hidden by failed reads. 0 starts no fetches.")
    args = parser.parse_args()
    # Leave URL/DNS validation to audit→fetch so --json always emits structured
    # page errors (exit 1) instead of argparse usage text (exit 2) on resolution failures.
    result = audit(args.url, **({"max_http_attempts": args.max_http_attempts} if args.max_http_attempts is not None else {}),
                   **({"max_http_body_bytes": args.max_http_body_bytes} if args.max_http_body_bytes is not None else {}))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        page = result.get("page", {})
        print(f"url: {result.get('url', args.url)}")
        print(f"status: {page.get('http_status')}")
        if page.get("status") in {"error", "unavailable"} and page.get("reason"):
            print(f"reason: {page.get('reason')}")
        print(f"title: {result.get('title')}")
        print(f"description: {result.get('meta_description')}")
        print(f"canonical: {result.get('canonical')}")
        for finding in result["findings"]:
            print(f"{finding['severity']} [{finding['confidence']}] {finding['code']}: {finding['message']}")
    if result.get("page", {}).get("status") != "ok":
        return 1
    return int(bool(args.fail_on and any(_SEVERITY[item["severity"]] >= _SEVERITY[args.fail_on] for item in result["findings"])))


if __name__ == "__main__":
    sys.exit(main())
