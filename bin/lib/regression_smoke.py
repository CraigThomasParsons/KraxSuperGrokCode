"""Regression smoke evaluator for per-run Vera verdict generation.

This module performs lightweight, deterministic checks on core run artifacts and
returns a machine-readable verdict payload used by gatekeeper validation.
"""

import os
from typing import Any

from lib import fs


def _check_file_non_empty(run_dir: str, relative_path: str) -> tuple[bool, str]:
    """Return pass/fail and detail for non-empty file checks within a run directory."""
    target_path = os.path.join(run_dir, relative_path)

    # Missing files are hard failures for smoke checks because they indicate incomplete flow.
    if not os.path.exists(target_path):
        return False, f"missing:{relative_path}"

    try:
        with open(target_path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except OSError as exc:
        return False, f"read_error:{relative_path}:{exc}"

    if not content:
        return False, f"empty:{relative_path}"

    return True, f"ok:{relative_path}"


def _build_evidence_item(run_dir: str, *, kind: str, relative_path: str, note: str = "") -> dict[str, Any]:
    """Build one evidence item with existence and size metadata."""
    absolute_path = os.path.join(run_dir, relative_path)
    exists = os.path.exists(absolute_path)
    size_bytes = 0

    # Size metadata helps operators triage suspiciously empty artifacts.
    if exists:
        try:
            size_bytes = int(os.path.getsize(absolute_path))
        except OSError:
            size_bytes = 0

    item_payload: dict[str, Any] = {
        "kind": kind,
        "path": relative_path,
        "exists": exists,
        "size_bytes": size_bytes,
    }
    if note:
        item_payload["note"] = note
    return item_payload


def build_vera_evidence_bundle(run_dir: str, job_id: str) -> dict[str, Any]:
    """Build standardized Vera evidence bundle artifact for one run."""
    items = [
        _build_evidence_item(run_dir, kind="artifact", relative_path="grok.txt", note="Captured model response."),
        _build_evidence_item(
            run_dir,
            kind="artifact",
            relative_path="execution_manifest.json",
            note="Flash execution manifest from implementation stage.",
        ),
        _build_evidence_item(
            run_dir,
            kind="trace",
            relative_path="run_trace.json",
            note="Cross-stage timeline used for causality checks.",
        ),
    ]

    return {
        "job_id": job_id,
        "stage": "vera",
        "bundle_id": f"vera-evidence-{job_id}",
        "items": items,
        "created_at": fs.utc_now_iso(),
    }


def write_vera_evidence_bundle(run_dir: str, job_id: str) -> dict[str, Any]:
    """Persist standardized Vera evidence bundle artifact and return payload."""
    bundle_payload = build_vera_evidence_bundle(run_dir, job_id)
    fs.write_json_atomic(os.path.join(run_dir, "vera_evidence.json"), bundle_payload)
    return bundle_payload


def build_vera_smoke_verdict(run_dir: str, job_id: str) -> dict[str, Any]:
    """Build a Vera verdict payload from deterministic regression smoke checks."""
    smoke_checks: list[dict[str, Any]] = []

    # Check 1 ensures the completion response is persisted for auditing and replay.
    grok_passed, grok_detail = _check_file_non_empty(run_dir, "grok.txt")
    smoke_checks.append(
        {
            "name": "grok_response_persisted",
            "passed": grok_passed,
            "detail": grok_detail,
            "evidence_refs": ["grok.txt"],
        }
    )

    # Check 2 ensures Flash manifest output is available for downstream verification.
    manifest_passed, manifest_detail = _check_file_non_empty(run_dir, "execution_manifest.json")
    smoke_checks.append(
        {
            "name": "flash_manifest_available",
            "passed": manifest_passed,
            "detail": manifest_detail,
            "evidence_refs": ["execution_manifest.json"],
        }
    )

    # Check 3 ensures the run trace exists so cross-stage causality can be validated.
    trace_passed, trace_detail = _check_file_non_empty(run_dir, "run_trace.json")
    smoke_checks.append(
        {
            "name": "run_trace_available",
            "passed": trace_passed,
            "detail": trace_detail,
            "evidence_refs": ["run_trace.json"],
        }
    )

    verdict = "pass" if all(bool(item.get("passed")) for item in smoke_checks) else "fail"
    summary = "regression_smoke_passed" if verdict == "pass" else "regression_smoke_failed"
    # Reason is intentionally short and explicit because it is consumed by gatekeeper and operators.
    reason = "All required smoke checks passed with linked evidence." if verdict == "pass" else "One or more smoke checks failed; see evidence bundle."

    return {
        "job_id": job_id,
        "stage": "vera",
        "verdict": verdict,
        "summary": summary,
        "reason": reason,
        "evidence_bundle_ref": "vera_evidence.json",
        "smoke_checks": smoke_checks,
        "evidence_refs": ["grok.txt", "execution_manifest.json", "run_trace.json"],
        "created_at": fs.utc_now_iso(),
    }


def write_vera_smoke_verdict(run_dir: str, job_id: str) -> dict[str, Any]:
    """Persist Vera smoke verdict artifact in the run directory and return payload."""
    # Evidence bundle is written first so verdict can reference a stable artifact path.
    write_vera_evidence_bundle(run_dir, job_id)

    # Build verdict only after evidence exists to guarantee link integrity.
    verdict_payload = build_vera_smoke_verdict(run_dir, job_id)
    fs.write_json_atomic(os.path.join(run_dir, "vera.json"), verdict_payload)
    return verdict_payload
