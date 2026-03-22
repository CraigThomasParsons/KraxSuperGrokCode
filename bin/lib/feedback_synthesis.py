"""Feedback synthesis helpers for generating revised Auralis planning artifacts.

This module converts Vera validation output into a concise feedback summary and
a next-cycle Plan v1 artifact that can be consumed by Auralis.
"""

import json
import os
from typing import Any

from lib import fs


def _load_json_or_empty(path: str) -> dict[str, Any]:
    """Load a JSON object from disk and return empty object on decode failures."""
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as handle:
            decoded = json.load(handle)
            return decoded if isinstance(decoded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _derive_findings_from_vera(vera_payload: dict[str, Any]) -> list[str]:
    """Derive human-readable findings list from Vera smoke check payload."""
    findings: list[str] = []

    # Preserve each smoke check outcome so next-loop planning can react deterministically.
    smoke_checks = vera_payload.get("smoke_checks")
    if isinstance(smoke_checks, list):
        for check in smoke_checks:
            if not isinstance(check, dict):
                continue
            name = str(check.get("name", "unknown_check"))
            passed = bool(check.get("passed"))
            detail = str(check.get("detail", "no_detail"))
            findings.append(f"{name}:{'pass' if passed else 'fail'}:{detail}")

    if not findings:
        # Emit a fallback finding so downstream artifacts always have actionable content.
        findings.append("vera_feedback_unavailable")

    return findings


def _select_single_improvement(findings: list[str]) -> dict[str, str]:
    """Select exactly one improvement candidate for the one-change-per-run pilot."""
    selected_finding = findings[0] if findings else "vera_feedback_unavailable"

    # Keep the pilot intentionally strict by selecting one improvement target per loop.
    return {
        "id": "change-001",
        "title": f"Address finding: {selected_finding}",
        "rationale": "Pilot policy limits each loop to one actionable improvement.",
    }


def build_feedback_summary(run_dir: str, job_id: str) -> dict[str, Any]:
    """Build feedback_summary.json payload from Vera verdict and findings."""
    vera_payload = _load_json_or_empty(os.path.join(run_dir, "vera.json"))

    verdict = str(vera_payload.get("verdict", "fail"))
    # Failed verdicts force revision while pass verdicts allow stable incremental iteration.
    status = "stable_iteration" if verdict == "pass" else "needs_revision"
    summary = (
        "Vera checks passed; carry intent forward with incremental refinement."
        if verdict == "pass"
        else "Vera checks failed; revise plan constraints and acceptance checks."
    )

    findings = _derive_findings_from_vera(vera_payload)
    proposed_changes = [_select_single_improvement(findings)]

    return {
        "job_id": job_id,
        "source_stage": "vera",
        "pilot": "one_change_per_run_v1",
        "status": status,
        "summary": summary,
        "findings": findings,
        "proposed_changes": proposed_changes,
        "created_at": fs.utc_now_iso(),
    }


def build_plan_v1_next(run_dir: str, job_id: str, feedback_summary: dict[str, Any]) -> dict[str, Any]:
    """Build revised plan_v1_next.json payload to feed back into Auralis."""
    job_payload = _load_json_or_empty(os.path.join(run_dir, "job.json"))

    goal = str(job_payload.get("goal", "Refine implementation intent from prior run.")).strip()
    context = str(job_payload.get("context", "No prior context provided.")).strip()

    summary = f"Refined intent for next loop: {goal}. Prior context: {context}."

    constraints = [
        # Keep constraints high-signal and stage-safe to avoid downstream role drift.
        "Preserve original product intent while addressing Vera findings.",
        "Keep stage-role boundaries intact across all artifacts.",
    ]

    # Apply only the selected pilot change so each run performs one controlled improvement.
    proposed_changes = feedback_summary.get("proposed_changes")
    if isinstance(proposed_changes, list) and proposed_changes:
        selected_change = proposed_changes[0]
        if isinstance(selected_change, dict):
            selected_title = str(selected_change.get("title", "")).strip()
            selected_rationale = str(selected_change.get("rationale", "")).strip()
            if selected_title:
                constraints.append(selected_title)
            if selected_rationale:
                constraints.append(f"Rationale: {selected_rationale}")

    acceptance_checks = [
        # Keep acceptance checks objective so gatekeeper decisions remain machine-evaluable.
        "All required runtime artifacts validate against schemas.",
        "Regression smoke verdict is pass with evidence linked.",
    ]

    return {
        "job_id": job_id,
        "stage": "auralis",
        "summary": summary,
        "constraints": constraints,
        "acceptance_checks": acceptance_checks,
        "created_at": fs.utc_now_iso(),
    }


def write_feedback_artifacts(run_dir: str, job_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write feedback_summary.json and plan_v1_next.json to run directory."""
    # Generate both artifacts from the same source payload to keep them mutually coherent.
    feedback_summary = build_feedback_summary(run_dir, job_id)
    plan_v1_next = build_plan_v1_next(run_dir, job_id, feedback_summary)

    # Persist summary first, then revised plan, matching the intended feedback flow order.
    fs.write_json_atomic(os.path.join(run_dir, "feedback_summary.json"), feedback_summary)
    fs.write_json_atomic(os.path.join(run_dir, "plan_v1_next.json"), plan_v1_next)

    return feedback_summary, plan_v1_next
