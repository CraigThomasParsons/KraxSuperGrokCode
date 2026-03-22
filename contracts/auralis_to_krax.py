"""Auralis -> Krax contract definitions and validation helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "v1"

REQUIRED_FIELDS = [
    "schema_version",
    "job_id",
    "correlation_id",
    "created_at",
    "source_agent",
    "attempt",
    "goal",
    "context",
    "instructions",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_krax_job(
    *,
    goal: str,
    context: str,
    instructions: str,
    constraints: list[str] | None = None,
    artifact_refs: list[str] | None = None,
    artifacts_expected: list[str] | None = None,
    source_run: str = "",
    metadata: dict[str, Any] | None = None,
    source_agent: str = "auralis",
    attempt: int = 1,
    causation_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": str(uuid4()),
        "correlation_id": correlation_id or str(uuid4()),
        "causation_id": causation_id,
        "created_at": utc_now_iso(),
        "source_agent": source_agent,
        "attempt": attempt,
        "goal": goal,
        "context": context,
        "instructions": instructions,
        "constraints": constraints or [],
        "artifact_refs": artifact_refs or [],
        "artifacts_expected": artifacts_expected or [],
        "source_run": source_run,
        "metadata": metadata or {},
    }


def validate_krax_job(job: dict[str, Any]) -> list[str]:
    reasons: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in job:
            reasons.append(field)

    if reasons:
        return reasons

    if job.get("schema_version") != SCHEMA_VERSION:
        reasons.append("schema_version")

    if job.get("source_agent") != "auralis":
        reasons.append("source_agent")

    attempt = job.get("attempt")
    if not isinstance(attempt, int) or attempt < 1:
        reasons.append("attempt")

    for field in ("job_id", "correlation_id", "created_at", "goal", "context", "instructions"):
        value = job.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(field)

    return sorted(set(reasons))
