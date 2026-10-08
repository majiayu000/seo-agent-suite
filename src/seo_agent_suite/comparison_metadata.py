"""Versioned page-only comparison evidence; pure, additive, and offline.

This is a producer contract, not a comparator or a provenance attestation.
The runtime resolver lives separately so building/validating metadata never
loads source, fetches a URL, reads a file, or mutates the containing report.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from seo_agent_suite import SCHEMA_VERSION, __version__

RULES = (
    ("site.meta.canonical", "has_canonical"),
    ("site.meta.description", "has_meta_description"),
    ("site.meta.json_ld", "has_json_ld"),
    ("site.meta.og_title", "has_og_title"),
    ("site.meta.title", "has_title"),
)
_MISSING = object()


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _valid_url(value):
    if not isinstance(value, str) or not value or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in {"http", "https"} and bool(parsed.netloc)
                and bool(parsed.hostname) and parsed.username is None
                and parsed.password is None and (parsed.port is None or 1 <= parsed.port <= 65535))
    except (ValueError, TypeError):
        return False


def _pointer(report, pointer):
    value = report
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return _MISSING
    for token in pointer[1:].split("/"):
        # Invalid RFC6901 escapes are not silently accepted.
        i = 0
        while i < len(token):
            if token[i] == "~":
                if i + 1 == len(token) or token[i + 1] not in "01":
                    return _MISSING
                i += 1
            i += 1
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isascii() and token.isdigit() and len(token) <= len(str(len(value))) and str(int(token)) == token and int(token) < len(value):
            value = value[int(token)]
        else:
            return _MISSING
    return value


def _refs(report, *pointers):
    return [p for p in pointers if _pointer(report, p) is not _MISSING]


def _policy(policy):
    policy = _mapping(policy)
    limits = {}
    for key, minimum in (("max_body_bytes", 1), ("timeout_seconds", 1), ("max_redirects", 0)):
        value = policy.get(key)
        limits[key] = value if type(value) is int and value >= minimum else None
    raw = _mapping(policy.get("request_headers"))
    ua = raw.get("User-Agent")
    headers = {"User-Agent": ua if isinstance(ua, str) and ua else None,
               "Accept": "*/*" if raw.get("Accept") == "*/*" else None}
    verified = all(v is not None for v in (*limits.values(), *headers.values()))
    return limits, headers, verified


def _fetch_ok(page):
    status = page.get("http_status")
    # A short local sample cannot establish that HTTP 206 contains the full page.
    return (page.get("status") == "ok" and type(status) is int
            and 200 <= status < 300 and status != 206)


def _target(report, original):
    page = _mapping(report.get("page"))
    requested = effective = None
    redaction = "unknown"
    reason = "requested_identity_unavailable"
    if isinstance(original, str):
        try:
            parsed = urlsplit(original)
            has_userinfo = parsed.username is not None or parsed.password is not None
        except ValueError:
            has_userinfo = False
        if has_userinfo:
            redaction = "applied"
            reason = "requested_identity_redacted"
        elif original == report.get("url") and _valid_url(original):
            requested = original
            redaction = "none"
            reason = "effective_identity_unavailable"
    if _fetch_ok(page) and _valid_url(page.get("url")):
        effective = page["url"]
    exact = requested is not None and effective is not None
    return {"kind": "site", "identity_state": "exact" if exact else "unknown",
            "requested_url": requested, "effective_url": effective,
            "reason": None if exact else reason}, redaction


def _capture_state(report):
    page = _mapping(report.get("page"))
    capture = _mapping(report.get("capture"))
    status = page.get("http_status")
    if page.get("status") == "error" or (type(status) is int and not 200 <= status < 300):
        return "page_fetch_error", False
    if not _fetch_ok(page):
        return "missing_capture_evidence", False
    media = page.get("content_type")
    encoding = page.get("content_encoding", _MISSING)
    if not isinstance(media, str):
        media = ""
    media = media.split(";", 1)[0].strip().lower()
    if encoding is _MISSING or (encoding is not None and not isinstance(encoding, str)):
        return "missing_capture_evidence", False
    encoded = (encoding or "").strip().lower() not in {"", "identity"}
    if encoded or media in {"application/gzip", "application/x-gzip", "application/zip"}:
        return "unsupported_encoding", False
    if not media:
        return "unknown_media_type", False
    if media not in {"text/html", "application/xhtml+xml"}:
        return "non_html", False
    complete_flags = (type(capture.get("body_truncated")) is bool
                      and type(page.get("body_truncated")) is bool
                      and capture["body_truncated"] == page["body_truncated"])
    if capture.get("scope") != "raw_html" or capture.get("rendered") is not False or not complete_flags:
        return "missing_capture_evidence", False
    return None, capture["body_truncated"]


def build_site_comparison_metadata(result, requested_url, runtime_policy):
    """Build metadata only for the CLI's newly collected, enriched site report.

    ``requested_url`` must be the original invocation argument, never an old
    report's display URL. ``runtime_policy`` contains independently verified
    effective settings; absent/unverified settings must be None.
    """
    result = _mapping(result)
    limits, headers, verified = _policy(runtime_policy)
    target, redaction = _target(result, requested_url)
    problem, truncated = _capture_state(result)
    checks = _mapping(result.get("checks"))
    findings = result.get("findings")
    findings = findings if isinstance(findings, list) else []
    ids = [f.get("id") for f in findings if isinstance(f, dict)]
    rows = []
    for rule, key in RULES:
        reason = problem
        outcome, completion = "unknown", "incomplete"
        if problem == "non_html":
            outcome, completion = "skip", "not_applicable"
        elif problem is None:
            value = checks.get(key)
            if type(value) is not bool:
                reason = "missing_check_evidence"
            elif value:
                outcome, completion, reason = "pass", "complete", "observed_present"
            elif truncated:
                reason = "body_truncated"
            else:
                outcome, completion, reason = "fail", "complete", "confirmed_absent"
        suffix = {"pass": "present", "fail": "missing", "unknown": "unknown"}.get(outcome)
        link = f"{rule}.{suffix}"
        rows.append({"rule_id": rule, "subject_id": "page", "outcome": outcome,
                     "completion": completion, "reason": reason,
                     "evidence_refs": _refs(result, "/page") if problem else _refs(result, f"/checks/{key}", "/capture"),
                     "legacy_finding_ids": [link] if suffix and ids.count(link) == 1 and problem not in {"page_fetch_error", "non_html"} else []})
    reasons = []
    if problem:
        reasons.append(problem)
    elif truncated:
        reasons.append("body_truncated")
    if problem is None and any(type(checks.get(key)) is not bool for _, key in RULES):
        reasons.append("missing_check_evidence")
    if target["identity_state"] != "exact" and problem != "page_fetch_error":
        reasons.append("identity_unavailable")
    if not verified:
        reasons.append("configuration_unverified")
    if not verified or target["identity_state"] != "exact":
        completion = "unknown"
    elif problem == "page_fetch_error" or truncated:
        completion = "incomplete"
    elif problem == "non_html":
        completion = "not_applicable"
    elif reasons:
        completion = "unknown"
    else:
        completion = "complete"
    # Failed collection has incomplete evidence even though effective identity
    # is necessarily unknown. Configuration uncertainty remains the top gate.
    if problem == "page_fetch_error" and verified:
        completion = "incomplete"
    return {
        "contract_version": "1.0",
        "producer": {"id": "seo-agent-suite/site-meta", "tool_version": __version__,
                     "report_schema_version": SCHEMA_VERSION, "ruleset_id": "site.raw_html.presence", "ruleset_version": "1"},
        "target": target,
        "scope": {"method": "raw_html_lexical_presence_v1", "rendered": False,
                  "subject_ids": ["page"], "rule_ids": [r for r, _ in RULES],
                  "limits": limits, "request_headers": headers, "resources": "excluded", "adapters": [],
                  "configuration_status": "verified" if verified else "unknown"},
        "collection": {"completion": completion, "reasons": reasons,
                       "evidence_refs": _refs(result, "/page", "/capture")},
        "provenance": {"identity_policy": "exact_input_and_successful_response_v1",
                       "requested_url_ref": "/url" if "url" in result else None,
                       "effective_url_ref": "/page/url" if _pointer(result, "/page/url") is not _MISSING else None,
                       "url_redaction": redaction,
                       "resources": {"comparison_scope": "excluded", "coverage": "unknown",
                                     "reason": "not_assessed_by_this_contract",
                                     "evidence_refs": _refs(result, "/checks/robots_txt", "/checks/sitemap_xml", "/checks/sitemap_discovery")}},
        "evaluations": rows,
    }


def _same(left, right):
    """Strict JSON equality: bool is not an integer; no extra object fields."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def validate_site_comparison_metadata(report, requested_url=_MISSING, runtime_policy=_MISSING):
    """Return deterministic semantic errors; never upgrade or mutate a report.

    Without original invocation inputs this validates stored consistency, not
    historical honesty. Pass independently retained inputs to check producer
    settings/provenance during production or tests. No schema dependency.
    """
    if not isinstance(report, dict) or not isinstance(report.get("comparison"), dict):
        return ["missing comparison metadata"]
    metadata = report["comparison"]
    errors = []
    target = _mapping(metadata.get("target"))
    scope = _mapping(metadata.get("scope"))
    provenance = _mapping(metadata.get("provenance"))
    original = target.get("requested_url") if requested_url is _MISSING else requested_url
    policy = {**_mapping(scope.get("limits")), "request_headers": scope.get("request_headers")} if runtime_policy is _MISSING else runtime_policy
    expected = build_site_comparison_metadata(report, original, policy)
    if requested_url is _MISSING and provenance.get("url_redaction") == "applied":
        if target.get("requested_url") is not None:
            errors.append("redacted requested identity must be null")
        expected["target"]["requested_url"] = None
        expected["target"]["identity_state"] = "unknown"
        expected["target"]["reason"] = "requested_identity_redacted"
        expected["provenance"]["url_redaction"] = "applied"
    # A failed/non-exact capture may conservatively leave redaction unknown
    # even when its safe requested string is retained (reviewed error example).
    if target.get("identity_state") == "unknown" and provenance.get("url_redaction") == "unknown":
        expected["provenance"]["url_redaction"] = "unknown"
    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported containing report schema")
    version = _mapping(metadata.get("producer")).get("tool_version")
    if not isinstance(version, str) or not version or report.get("tool_version") != version:
        errors.append("producer version differs from containing report")
    else:
        expected["producer"]["tool_version"] = version
    if _mapping(report.get("target")).get("kind") != "site":
        errors.append("unsupported target kind")
    if (expected["target"]["identity_state"] == "exact"
            and _mapping(report.get("target")).get("id") != expected["target"]["requested_url"]):
        errors.append("containing report target differs from requested identity")
    # References are links, not identity keys: valid unique pointers and an
    # empty subset of existing legacy links are explicitly permitted.
    pairs = [(metadata.get("collection"), expected["collection"]),
             (provenance.get("resources"), expected["provenance"]["resources"])]
    actual_rows = metadata.get("evaluations")
    if isinstance(actual_rows, list) and len(actual_rows) == len(expected["evaluations"]):
        pairs.extend(zip(actual_rows, expected["evaluations"]))
    for actual, wanted in pairs:
        if not isinstance(actual, dict):
            continue
        refs = actual.get("evidence_refs")
        if isinstance(refs, list) and all(isinstance(p, str) and _pointer(report, p) is not _MISSING for p in refs) and len(set(refs)) == len(refs):
            wanted["evidence_refs"] = refs
        if "legacy_finding_ids" in wanted:
            links = actual.get("legacy_finding_ids")
            if isinstance(links, list) and all(isinstance(link, str) and link in wanted["legacy_finding_ids"] for link in links) and len(set(links)) == len(links):
                wanted["legacy_finding_ids"] = links
    for key in expected:
        if not _same(metadata.get(key, _MISSING), expected[key]):
            errors.append(f"invalid {key}: disagrees with containing evidence or contract")
    if set(metadata) != set(expected):
        errors.append("unsupported comparison fields")
    # Explicit pointer/link checks produce useful diagnostics even when the
    # same corruption also violates the deterministic expected ledger.
    groups = [_mapping(metadata.get("collection")), _mapping(provenance.get("resources"))]
    rows = metadata.get("evaluations")
    if isinstance(rows, list):
        groups.extend(row for row in rows if isinstance(row, dict))
    for group in groups:
        refs = group.get("evidence_refs")
        if isinstance(refs, list):
            for ref in refs:
                if _pointer(report, ref) is _MISSING:
                    errors.append("unresolved evidence pointer")
    findings = report.get("findings")
    ids = [f.get("id") for f in findings if isinstance(f, dict)] if isinstance(findings, list) else []
    if isinstance(rows, list):
        for row in rows:
            links = row.get("legacy_finding_ids") if isinstance(row, dict) else None
            if isinstance(links, list) and any(ids.count(link) != 1 for link in links):
                errors.append("legacy finding link must resolve uniquely")
    return list(dict.fromkeys(errors))
