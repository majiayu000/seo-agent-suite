"""Stable Report Envelope + Finding helpers for agent consumption."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping

from seo_agent_suite import SCHEMA_VERSION, __version__

Severity = str  # high|medium|low|info
Confidence = str  # confirmed|likely|hypothesis
FindingStatus = str  # fail|pass|skip|unknown|error

_COMMUNITY_SKIP_KEYS = frozenset({"community_file_paths", "issue_template_candidates"})


def make_finding(
    *,
    id: str,
    title: str,
    severity: Severity = "medium",
    confidence: Confidence = "confirmed",
    surface: str,
    status: FindingStatus = "fail",
    detail: str = "",
    evidence: list[dict[str, Any]] | None = None,
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "id": id,
        "title": title,
        "severity": severity,
        "confidence": confidence,
        "surface": surface,
        "status": status,
        "detail": detail,
        "evidence": evidence or [],
    }
    if action:
        finding["action"] = action
    return finding


def attach_envelope(
    payload: MutableMapping[str, Any],
    *,
    target_kind: str,
    target_id: str,
    findings: Iterable[Mapping[str, Any]],
    status: str | None = None,
) -> dict[str, Any]:
    """Add schema_version / tool_version / target / findings without dropping fields."""
    out = dict(payload)
    out["schema_version"] = SCHEMA_VERSION
    out["tool_version"] = __version__
    out["target"] = {"kind": target_kind, "id": target_id}
    out["findings"] = list(findings)
    if status is not None:
        out["status"] = status
    elif "status" not in out:
        out["status"] = _infer_status(out, out["findings"])
    return out


def _infer_status(payload: Mapping[str, Any], findings: list[Mapping[str, Any]]) -> str:
    page = payload.get("page")
    if isinstance(page, Mapping) and page.get("status") == "error":
        return "error"
    if payload.get("errors"):
        return "error"
    if any(f.get("status") in {"fail", "error"} for f in findings):
        return "partial"
    return "ok"


def findings_from_site_audit(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    page = result.get("page") if isinstance(result.get("page"), Mapping) else {}
    url = str(result.get("url") or "")

    if page.get("status") == "error":
        findings.append(
            make_finding(
                id="site.fetch.failed",
                title="Public page fetch failed",
                severity="high",
                confidence="confirmed",
                surface="crawl",
                status="error",
                detail=str(page.get("reason") or "fetch failed"),
                evidence=[{"kind": "url", "value": url}],
                action={
                    "summary": "Confirm the URL is public http(s) and reachable from this environment.",
                    "retest": f"seo-agent site-meta {url} --json",
                },
            )
        )
        return findings

    if result.get("capture", {}).get("scope") == "raw_response":
        return findings
    checks = result.get("checks") if isinstance(result.get("checks"), Mapping) else {}
    check_specs = (
        ("has_title", "site.meta.title", "title element", "high", "meta"),
        ("has_meta_description", "site.meta.description", "meta description", "medium", "meta"),
        ("has_canonical", "site.meta.canonical", "canonical link", "medium", "meta"),
        ("has_og_title", "site.meta.og_title", "og:title", "low", "meta"),
        ("has_json_ld", "site.meta.json_ld", "JSON-LD", "low", "meta"),
        ("has_robots_txt", "site.crawl.robots_txt", "robots.txt", "medium", "crawl"),
        ("has_sitemap_xml", "site.crawl.sitemap", "sitemap.xml", "medium", "crawl"),
    )
    for key, fid, label, severity, surface in check_specs:
        present = bool(checks.get(key))
        resource_key = {"has_robots_txt": "robots_txt", "has_sitemap_xml": "sitemap_xml"}.get(key)
        resources = checks.get(resource_key) if resource_key else None
        if not present and isinstance(resources, list) and resources:
            confirmed_missing = all(
                item.get("http_status") in {404, 410} for item in resources
            )
            if not confirmed_missing:
                findings.append(make_finding(
                    id=f"{fid}.unknown", title=f"Cannot determine {label} availability",
                    severity="info", confidence="hypothesis", surface=surface,
                    status="unknown", detail="Resource responses do not establish absence.",
                    evidence=[{"kind": "json_pointer", "path": f"/checks/{resource_key}"}],
                ))
                continue
        findings.append(
            make_finding(
                id=f"{fid}.{'present' if present else 'missing'}",
                title=f"{'Found' if present else 'Missing'} {label}",
                severity="info" if present else severity,
                confidence="confirmed",
                surface=surface,
                status="pass" if present else "fail",
                detail=f"checks.{key}={present}",
                evidence=[
                    {"kind": "json_pointer", "path": f"/checks/{key}"},
                    {"kind": "url", "value": url},
                ],
                action=None
                if present
                else {
                    "summary": f"Add or expose {label} for this URL.",
                    "retest": f"seo-agent site-meta {url} --json",
                },
            )
        )
    return findings


def findings_from_repo_baseline(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    root = str(evidence.get("root") or "")

    for err in evidence.get("errors") or []:
        if not isinstance(err, Mapping):
            continue
        surface = str(err.get("surface") or "repo")
        check = err.get("check") or err.get("path") or err.get("resource") or "error"
        findings.append(
            make_finding(
                id=f"repo.{surface}.{check}",
                title=f"{surface} issue: {check}",
                severity="high" if surface in {"shipwise", "site"} else "medium",
                confidence="confirmed",
                surface=surface,
                status="fail",
                detail=str(err.get("reason") or "check failed"),
                evidence=[{"kind": "error", "value": dict(err)}],
                action={
                    "summary": "Resolve the listed surface error, then re-run the repo baseline.",
                    "retest": f"seo-agent repo-baseline --root {root} --json",
                },
            )
        )

    readmes = evidence.get("readmes") or []
    if isinstance(readmes, list) and not readmes:
        findings.append(
            make_finding(
                id="repo.readme.missing",
                title="No README found at repository root candidates",
                severity="high",
                confidence="confirmed",
                surface="repo",
                status="fail",
                detail="collect_readmes returned an empty list",
                evidence=[{"kind": "json_pointer", "path": "/readmes"}],
            )
        )

    community = evidence.get("community_files")
    if isinstance(community, Mapping):
        for name, value in community.items():
            if name in _COMMUNITY_SKIP_KEYS:
                continue
            if value is False:
                findings.append(
                    make_finding(
                        id=f"repo.community.{name}.missing",
                        title=f"Community file missing: {name}",
                        severity="low",
                        confidence="confirmed",
                        surface="repo",
                        status="fail",
                        detail=f"community_files.{name}=false",
                        evidence=[{"kind": "json_pointer", "path": f"/community_files/{name}"}],
                    )
                )

    if not findings and evidence.get("status") == "ok":
        findings.append(
            make_finding(
                id="repo.baseline.ok",
                title="Repo baseline collected without structured errors",
                severity="info",
                confidence="confirmed",
                surface="repo",
                status="pass",
                detail="status=ok and errors=[] — not a ranking claim",
                evidence=[{"kind": "json_pointer", "path": "/status"}],
            )
        )
    return findings


def enrich_site_result(result: MutableMapping[str, Any]) -> dict[str, Any]:
    findings = findings_from_site_audit(result)
    for item in result.get("findings") or []:
        if isinstance(item, Mapping) and "code" in item:
            findings.append({**item, **make_finding(
                id=f"site.assessment.{item['code']}", title=str(item.get("message") or item["code"]),
                severity={"error": "high", "warning": "medium"}.get(item.get("severity"), "info"),
                confidence=str(item.get("confidence") or "Hypothesis").lower(),
                surface="site", status="fail" if item.get("severity") == "error" else "unknown",
                evidence=[{"kind": "json_pointer", "path": str(item.get("evidence") or "")}],
            )})
    page = result.get("page") if isinstance(result.get("page"), Mapping) else {}
    fetch_ok = page.get("status") == "ok"
    if not fetch_ok:
        status = "error"
    elif any(f.get("status") == "fail" for f in findings):
        status = "partial"
    else:
        status = "ok"
    return attach_envelope(
        result,
        target_kind="site",
        target_id=str(result.get("url") or ""),
        findings=findings,
        status=status,
    )


def enrich_repo_evidence(evidence: MutableMapping[str, Any]) -> dict[str, Any]:
    findings = findings_from_repo_baseline(evidence)
    return attach_envelope(
        evidence,
        target_kind="repo",
        target_id=str(evidence.get("root") or ""),
        findings=findings,
        status=evidence.get("status"),
    )
