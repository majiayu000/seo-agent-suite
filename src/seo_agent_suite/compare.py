"""Offline comparison of two explicitly supplied report byte strings.

The fixed input bounds apply only to this command/API, not other collectors.
This validates recorded consistency, not authenticity or current site state.
"""
from __future__ import annotations

import hashlib
import json
import math

from seo_agent_suite import __version__
from seo_agent_suite.comparison_metadata import validate_site_comparison_metadata

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_CONTAINER_DEPTH = 64
EXIT_CODES = {"comparable": 0, "incomparable": 1, "invalid_input": 2}


class InvalidInput(ValueError):
    """A deterministic input rejection, without echoing report contents."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInput("duplicate_object_key")
        result[key] = value
    return result


def _constant(_):
    raise InvalidInput("nonfinite_number")


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise InvalidInput("nonfinite_number")
    return number


def _check_depth(text):
    # String-aware lexical bound before json.loads and recursive validation.
    # JSON syntax remains the standard parser's responsibility; this is not a
    # general parser resource-safety guarantee. The root container is depth 1.
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_CONTAINER_DEPTH:
                raise InvalidInput("depth_limit_exceeded")
        elif char in "]}":
            depth -= 1


def _parse(data):
    if type(data) is not bytes:
        raise InvalidInput("expected_bytes")
    if len(data) > MAX_INPUT_BYTES:
        raise InvalidInput("size_limit_exceeded")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidInput("invalid_utf8") from None
    _check_depth(text)
    try:
        report = json.loads(text, object_pairs_hook=_object,
                            parse_constant=_constant, parse_float=_float)
    except InvalidInput:
        raise
    except RecursionError:
        raise InvalidInput("parser_recursion_limit") from None
    except (ValueError, OverflowError):
        raise InvalidInput("invalid_json") from None
    if not isinstance(report, dict):
        raise InvalidInput("expected_report_object")
    return report


def _result():
    return {
        "comparison_result_version": "1.0",
        "status": "incomparable",
        "scope": "five_raw_html_lexical_presence_checks",
        "resources": "excluded",
        "resolution_meaning": "passed_in_recorded_capture_not_deployment_indexing_or_ranking",
        "inputs": {"before": {"sha256": None}, "after": {"sha256": None}},
        "reasons": [],
        "changes": [],
        "counts": None,
    }


def invalid_input_result(side, reason):
    """Build the same output shape for a CLI read failure (no input digest)."""
    result = _result()
    result["status"] = "invalid_input"
    result["reasons"] = [{"input": side, "code": reason}]
    return result


def compare_reports(before: bytes, after: bytes) -> dict:
    """Compare exact UTF-8 report bytes, with no I/O and no input mutation.

    Returns comparable / incomparable / invalid_input. No findings-severity
    gate is applied. Both entire reports must be eligible before any lifecycle
    result is emitted. Digests identify supplied bytes, not trusted provenance.
    """
    result = _result()
    reports = {}
    for side, data in (("before", before), ("after", after)):
        if type(data) is bytes and len(data) <= MAX_INPUT_BYTES:
            result["inputs"][side]["sha256"] = hashlib.sha256(data).hexdigest()
        try:
            reports[side] = _parse(data)
        except InvalidInput as exc:
            result["status"] = "invalid_input"
            result["reasons"].append({"input": side, "code": str(exc)})
    if result["status"] == "invalid_input":
        return result

    for side, report in reports.items():
        target = report.get("target")
        if isinstance(target, dict) and target.get("kind") != "site":
            result["reasons"].append({"input": side, "code": "unsupported_target_kind"})
            continue
        if not isinstance(report.get("comparison"), dict):
            result["reasons"].append({"input": side, "code": "missing_comparison_metadata"})
            continue
        errors = validate_site_comparison_metadata(report)
        if errors:
            result["reasons"].append({"input": side, "code": "invalid_comparison_metadata", "details": errors})
            continue
        metadata = report["comparison"]
        if metadata["producer"]["tool_version"] != __version__:
            result["reasons"].append({"input": side, "code": "unsupported_tool_version"})
        if metadata["target"]["identity_state"] != "exact":
            result["reasons"].append({"input": side, "code": "unknown_target_identity"})
        if metadata["collection"]["completion"] != "complete":
            result["reasons"].append({"input": side, "code": "collection_not_complete"})
        if any(row["completion"] != "complete" or row["outcome"] not in ("pass", "fail")
               for row in metadata["evaluations"]):
            result["reasons"].append({"input": side, "code": "evaluations_not_complete"})
    if result["reasons"]:
        return result

    left, right = reports["before"]["comparison"], reports["after"]["comparison"]
    for key in ("contract_version", "producer", "target", "scope"):
        if left[key] != right[key]:
            result["reasons"].append({"input": "pair", "code": key + "_mismatch"})
    if result["reasons"]:
        return result

    counts = dict.fromkeys(("new", "persistent", "resolved", "unchanged_passing"), 0)
    transitions = {("pass", "fail"): "new", ("fail", "fail"): "persistent",
                   ("fail", "pass"): "resolved", ("pass", "pass"): "unchanged_passing"}
    # The shared semantic validator guarantees the full sorted rule/page ledger.
    for index, (old, new) in enumerate(zip(left["evaluations"], right["evaluations"])):
        outcome = transitions[(old["outcome"], new["outcome"])]
        counts[outcome] += 1
        if outcome == "unchanged_passing":
            continue
        change = {"rule_id": old["rule_id"], "subject_id": old["subject_id"], "outcome": outcome}
        for side, row in (("before", old), ("after", new)):
            change[side] = {"outcome": row["outcome"],
                            "evaluation_ref": f"/comparison/evaluations/{index}",
                            "evidence_refs": list(row["evidence_refs"]),
                            "legacy_finding_ids": list(row["legacy_finding_ids"])}
        result["changes"].append(change)
    result.update(status="comparable", counts=counts, target=dict(left["target"]))
    return result
