#!/usr/bin/env python3
"""Create a canonical v1 Krax job in inbox/ for manual or local testing."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json_atomic(file_path: Path, payload: dict) -> None:
    temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp_path, file_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enqueue a Krax job into inbox/.")
    parser.add_argument(
        "--goal",
        default="Build a small joke generator app with simple, readable code.",
        help="Primary goal for Grok.",
    )
    parser.add_argument(
        "--context",
        default="Manual Krax test job created from local tool.",
        help="Execution context for Grok.",
    )
    parser.add_argument(
        "--instructions",
        default=(
            "Write code for a minimal joke generator. Include one main file and a short usage example."
        ),
        help="Concrete implementation instructions.",
    )
    parser.add_argument(
        "--constraint",
        action="append",
        default=[],
        help="Constraint line to add (can be supplied multiple times).",
    )
    parser.add_argument(
        "--source-agent",
        default="auralis",
        help="Source agent name stored in the contract.",
    )
    parser.add_argument(
        "--job-id",
        default=None,
        help="Optional explicit job_id. Default is a generated UUID.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    krax_root = Path(__file__).resolve().parents[1]
    inbox_dir = krax_root / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    job_id = args.job_id or str(uuid.uuid4())
    job_dir = inbox_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    payload = {
        "schema_version": "v1",
        "job_id": job_id,
        "correlation_id": str(uuid.uuid4()),
        "causation_id": None,
        "created_at": utc_now_iso(),
        "source_agent": args.source_agent,
        "attempt": 1,
        "goal": args.goal,
        "context": args.context,
        "instructions": args.instructions,
        "constraints": args.constraint,
        "artifact_refs": [],
        "artifacts_expected": ["krax_output.json", "extracted/*"],
        "source_run": None,
        "metadata": {
            "created_by": "tools/enqueue_krax_job.py",
            "kind": "manual_test",
        },
    }

    write_json_atomic(job_dir / "job.json", payload)

    print(f"ENQUEUED {job_id}")
    print(f"JOB_DIR {job_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
