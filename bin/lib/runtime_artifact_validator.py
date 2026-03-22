"""Runtime artifact validation and gatekeeper decision helpers.

This module evaluates per-run artifact completeness, role-boundary compliance,
and baseline coherence checks before promotion decisions are recorded.
"""

import json
import os
import re
from typing import Any

from lib import fs

SCHEMA_ROOT = os.path.join(fs.KRAX_ROOT, "contracts", "runtime_artifacts")

SCHEMA_BY_ARTIFACT = {
    "plan_v1.json": "plan_v1.schema.json",
    "plan_v1_next.json": "plan_v1_next.schema.json",
    "plan_v2.json": "plan_v2.schema.json",
    "tasks.json": "tasks.schema.json",
    "feedback_summary.json": "feedback_summary.schema.json",
    "execution_manifest.json": "execution_manifest.schema.json",
    "vera.json": "vera.schema.json",
    "vera_evidence.json": "vera_evidence.schema.json",
    "run_trace.json": "run_trace.schema.json",
}

EXPECTED_ARTIFACT_STAGE = {
    "plan_v1.json": "auralis",
    "plan_v1_next.json": "auralis",
    "plan_v2.json": "krax",
}

ALLOWED_TASK_STAGES = {"mason", "flash"}

ALLOWED_RUN_TRACE_EVENTS = {
    "auralis": {"feedback_synthesized"},
    "krax": {
        "received",
        "dispatch_prompt",
        "grok_complete",
        "execution_manifest_written",
        "handoff_written",
        "archived",
        "failed",
    },
    "vera": {"regression_smoke_complete"},
    "gatekeeper": {"decision_recorded", "role_violation", "promotion_blocked"},
}

STAGE_ROLE_CHECK_PREFIX = "stage_role"
BASELINE_CHECK_PREFIX = "baseline"
MASON_QUALITY_CHECK_PREFIX = "mason_quality"
SPRINT_SLICER_CHECK_PREFIX = "sprint_slicer"
FLASH_MANIFEST_CHECK_PREFIX = "flash_manifest"
IMPROVEMENT_PILOT_CHECK_PREFIX = "improvement_pilot"

REQUIRED_KRAX_TRACE_EVENTS = {
    "received",
    "dispatch_prompt",
    "grok_complete",
    "handoff_written",
}

# Gatekeeper events are appended after decision evaluation, so they cannot be
# required at evaluation time without causing a deterministic false negative.
REQUIRED_GATEKEEPER_TRACE_EVENTS: set[str] = set()
REQUIRED_VERA_TRACE_EVENTS = {"regression_smoke_complete"}

SPRINT_SLICE_FILE_PATTERN = re.compile(r"^sprint_[0-9]{2}\.json$")
MAX_TASKS_PER_SPRINT_SLICE = 10


def _read_json(path: str) -> tuple[dict[str, Any] | None, str | None]:
    """Read a JSON object from disk and normalize errors as string codes."""
    if not os.path.exists(path):
        return None, "missing"

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc}"

    if not isinstance(payload, dict):
        return None, "invalid_type: expected object"

    return payload, None


def _required_fields_from_schema(schema_path: str) -> list[str]:
    """Extract top-level required field names from a JSON schema file."""
    schema_payload, err = _read_json(schema_path)
    if err or not schema_payload:
        return []

    required = schema_payload.get("required", [])
    if not isinstance(required, list):
        return []

    return [item for item in required if isinstance(item, str)]


def _validate_required_fields(payload: dict[str, Any], required_fields: list[str]) -> list[str]:
    """Return required field names that are absent from payload."""
    missing = []
    for field in required_fields:
        if field not in payload:
            missing.append(field)
    return missing


def _get_check_value(check_name: str, checks: list[dict[str, Any]]) -> bool | None:
    """Get the boolean result for a named check if it exists."""
    for check in checks:
        if check.get("name") == check_name:
            return bool(check.get("passed"))
    return None


def has_stage_role_violations(decision: dict[str, Any]) -> bool:
    """Return True when any stage-role check explicitly fails."""
    checks = decision.get("checks", [])
    if not isinstance(checks, list):
        return False

    for check in checks:
        name = check.get("name")
        passed = check.get("passed")
        if isinstance(name, str) and name.startswith(f"{STAGE_ROLE_CHECK_PREFIX}:") and passed is False:
            return True

    return False


def _has_failed_prefix(checks: list[dict[str, Any]], prefix: str) -> bool:
    """Return True when at least one check with prefix has passed=False."""
    for check in checks:
        name = check.get("name")
        passed = check.get("passed")
        if isinstance(name, str) and name.startswith(prefix) and passed is False:
            return True
    return False


def _has_failed_contract_checks(checks: list[dict[str, Any]]) -> bool:
    """Return True when non-baseline, non-stage-role checks contain failures."""
    for check in checks:
        name = check.get("name")
        passed = check.get("passed")
        if not isinstance(name, str):
            continue
        if name.startswith(f"{BASELINE_CHECK_PREFIX}:"):
            continue
        if name.startswith(f"{STAGE_ROLE_CHECK_PREFIX}:"):
            continue
        if passed is False:
            return True
    return False


def _evaluate_mason_task_quality(
    *,
    checks: list[dict[str, Any]],
    failures: list[str],
    tasks_payload: dict[str, Any] | None,
):
    """Evaluate Mason task quality: owner, done criteria, and dependency integrity."""
    # Missing or malformed payload is a hard failure for all Mason quality checks.
    if not isinstance(tasks_payload, dict):
        checks.append({"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:owner_present", "passed": False})
        checks.append({"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:done_criteria_present", "passed": False})
        checks.append({"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:dependency_refs_exist", "passed": False})
        checks.append({"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:dependency_order_valid", "passed": False})
        failures.append(f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:prereq_missing")
        return

    tasks = tasks_payload.get("tasks")
    if not isinstance(tasks, list):
        checks.append({"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:owner_present", "passed": False})
        checks.append({"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:done_criteria_present", "passed": False})
        checks.append({"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:dependency_refs_exist", "passed": False})
        checks.append({"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:dependency_order_valid", "passed": False})
        failures.append(f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:invalid_tasks_array")
        return

    owner_issues = []
    done_criteria_issues = []
    id_issues = []
    dependency_ref_issues = []
    dependency_order_issues = []

    id_to_index: dict[str, int] = {}
    # Pass 1 builds a stable task id index and validates required task-level fields.
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            owner_issues.append(f"task[{idx}]:invalid_type")
            done_criteria_issues.append(f"task[{idx}]:invalid_type")
            id_issues.append(f"task[{idx}]:invalid_type")
            continue

        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            id_issues.append(f"task[{idx}]:missing_id")
            continue

        if task_id in id_to_index:
            id_issues.append(f"task[{idx}]:duplicate_id={task_id}")
        else:
            id_to_index[task_id] = idx

        owner = task.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            owner_issues.append(f"task[{idx}]:missing_owner")

        done_criteria = task.get("done_criteria")
        if not isinstance(done_criteria, list) or len(done_criteria) == 0:
            done_criteria_issues.append(f"task[{idx}]:missing_done_criteria")

    # Pass 2 validates dependency references and enforces forward-only ordering.
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            dependency_ref_issues.append(f"task[{idx}]:invalid_type")
            dependency_order_issues.append(f"task[{idx}]:invalid_type")
            continue

        depends_on = task.get("depends_on", [])
        if depends_on is None:
            depends_on = []
        if not isinstance(depends_on, list):
            dependency_ref_issues.append(f"task[{idx}]:depends_on_invalid_type")
            dependency_order_issues.append(f"task[{idx}]:depends_on_invalid_type")
            continue

        for dep in depends_on:
            if not isinstance(dep, str) or not dep.strip():
                dependency_ref_issues.append(f"task[{idx}]:blank_dependency")
                continue
            dep_index = id_to_index.get(dep)
            if dep_index is None:
                dependency_ref_issues.append(f"task[{idx}]:missing_dependency={dep}")
                continue
            if dep_index >= idx:
                dependency_order_issues.append(f"task[{idx}]:dependency_not_before={dep}")

    owner_ok = not owner_issues
    done_criteria_ok = not done_criteria_issues
    dependency_refs_ok = not dependency_ref_issues and not id_issues
    dependency_order_ok = not dependency_order_issues and not id_issues

    checks.append({"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:owner_present", "passed": owner_ok})
    checks.append(
        {"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:done_criteria_present", "passed": done_criteria_ok}
    )
    checks.append(
        {"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:dependency_refs_exist", "passed": dependency_refs_ok}
    )
    checks.append(
        {"name": f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:dependency_order_valid", "passed": dependency_order_ok}
    )

    if owner_issues:
        failures.append(f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:owner_issues={'|'.join(owner_issues)}")
    if done_criteria_issues:
        failures.append(
            f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:done_criteria_issues={'|'.join(done_criteria_issues)}"
        )
    if id_issues:
        failures.append(f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:id_issues={'|'.join(id_issues)}")
    if dependency_ref_issues:
        failures.append(
            f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:dependency_ref_issues={'|'.join(dependency_ref_issues)}"
        )
    if dependency_order_issues:
        failures.append(
            f"{MASON_QUALITY_CHECK_PREFIX}:tasks.json:dependency_order_issues={'|'.join(dependency_order_issues)}"
        )


def _evaluate_sprint_slicer_output(
    *,
    run_dir: str,
    checks: list[dict[str, Any]],
    failures: list[str],
    tasks_payload: dict[str, Any] | None,
):
    """Evaluate Mason sprint-slice artifacts for format, coverage, and bounded size."""
    # Sprint slicing requires a valid tasks payload to validate references and coverage.
    if not isinstance(tasks_payload, dict):
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:slices_present", "passed": False})
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:slice_format", "passed": False})
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:bounded_size", "passed": False})
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:task_coverage", "passed": False})
        failures.append(f"{SPRINT_SLICER_CHECK_PREFIX}:tasks_payload_missing")
        return

    tasks = tasks_payload.get("tasks")
    if not isinstance(tasks, list):
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:slices_present", "passed": False})
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:slice_format", "passed": False})
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:bounded_size", "passed": False})
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:task_coverage", "passed": False})
        failures.append(f"{SPRINT_SLICER_CHECK_PREFIX}:invalid_tasks_array")
        return

    valid_task_ids = set()
    for task in tasks:
        if isinstance(task, dict):
            task_id = task.get("id")
            if isinstance(task_id, str) and task_id.strip():
                valid_task_ids.add(task_id)

    slice_file_names = sorted(
        [name for name in os.listdir(run_dir) if SPRINT_SLICE_FILE_PATTERN.match(name)]
    )
    if not slice_file_names:
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:slices_present", "passed": False})
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:slice_format", "passed": False})
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:bounded_size", "passed": False})
        checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:task_coverage", "passed": False})
        failures.append(f"{SPRINT_SLICER_CHECK_PREFIX}:missing_slice_files")
        return

    checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:slices_present", "passed": True})

    format_issues = []
    bounded_size_issues = []
    coverage_issues = []
    seen_slice_task_ids: list[str] = []

    for slice_file_name in slice_file_names:
        slice_path = os.path.join(run_dir, slice_file_name)
        slice_payload, slice_err = _read_json(slice_path)

        if slice_err or not isinstance(slice_payload, dict):
            format_issues.append(f"{slice_file_name}:invalid_json")
            continue

        sprint_id = slice_payload.get("sprint_id")
        stage = slice_payload.get("stage")
        job_id = slice_payload.get("job_id")
        task_ids = slice_payload.get("task_ids")

        expected_sprint_id = slice_file_name.replace(".json", "")
        if sprint_id != expected_sprint_id:
            format_issues.append(f"{slice_file_name}:sprint_id_mismatch={sprint_id}")

        if stage != "mason":
            format_issues.append(f"{slice_file_name}:invalid_stage={stage}")

        if job_id != tasks_payload.get("job_id"):
            format_issues.append(f"{slice_file_name}:job_id_mismatch={job_id}")

        if not isinstance(task_ids, list) or len(task_ids) == 0:
            format_issues.append(f"{slice_file_name}:invalid_task_ids")
            continue

        if len(task_ids) > MAX_TASKS_PER_SPRINT_SLICE:
            bounded_size_issues.append(
                f"{slice_file_name}:size={len(task_ids)}:max={MAX_TASKS_PER_SPRINT_SLICE}"
            )

        for task_id in task_ids:
            if not isinstance(task_id, str) or not task_id.strip():
                coverage_issues.append(f"{slice_file_name}:blank_task_id")
                continue
            if task_id not in valid_task_ids:
                coverage_issues.append(f"{slice_file_name}:unknown_task_id={task_id}")
            seen_slice_task_ids.append(task_id)

    duplicate_task_ids = [task_id for task_id in seen_slice_task_ids if seen_slice_task_ids.count(task_id) > 1]
    if duplicate_task_ids:
        deduped = sorted(set(duplicate_task_ids))
        coverage_issues.append(f"duplicate_task_ids={'|'.join(deduped)}")

    uncovered_task_ids = sorted(valid_task_ids.difference(set(seen_slice_task_ids)))
    if uncovered_task_ids:
        coverage_issues.append(f"uncovered_task_ids={'|'.join(uncovered_task_ids)}")

    checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:slice_format", "passed": len(format_issues) == 0})
    checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:bounded_size", "passed": len(bounded_size_issues) == 0})
    checks.append({"name": f"{SPRINT_SLICER_CHECK_PREFIX}:task_coverage", "passed": len(coverage_issues) == 0})

    if format_issues:
        failures.append(f"{SPRINT_SLICER_CHECK_PREFIX}:format_issues={'|'.join(format_issues)}")
    if bounded_size_issues:
        failures.append(f"{SPRINT_SLICER_CHECK_PREFIX}:size_issues={'|'.join(bounded_size_issues)}")
    if coverage_issues:
        failures.append(f"{SPRINT_SLICER_CHECK_PREFIX}:coverage_issues={'|'.join(coverage_issues)}")


def _evaluate_flash_execution_manifest(
    *,
    checks: list[dict[str, Any]],
    failures: list[str],
    manifest_payload: dict[str, Any] | None,
):
    """Evaluate Flash execution manifest for required run metadata quality."""
    # Manifest quality checks are fail-closed because downstream verification depends on them.
    if not isinstance(manifest_payload, dict):
        checks.append({"name": f"{FLASH_MANIFEST_CHECK_PREFIX}:commands_logged", "passed": False})
        checks.append({"name": f"{FLASH_MANIFEST_CHECK_PREFIX}:files_changed_recorded", "passed": False})
        checks.append({"name": f"{FLASH_MANIFEST_CHECK_PREFIX}:validation_outputs_present", "passed": False})
        failures.append(f"{FLASH_MANIFEST_CHECK_PREFIX}:manifest_missing")
        return

    commands_run = manifest_payload.get("commands_run")
    files_changed = manifest_payload.get("files_changed")
    validation_outputs = manifest_payload.get("validation_outputs")

    commands_logged = isinstance(commands_run, list)
    files_changed_recorded = isinstance(files_changed, list)
    validation_outputs_present = isinstance(validation_outputs, list) and len(validation_outputs) > 0

    checks.append({"name": f"{FLASH_MANIFEST_CHECK_PREFIX}:commands_logged", "passed": commands_logged})
    checks.append(
        {"name": f"{FLASH_MANIFEST_CHECK_PREFIX}:files_changed_recorded", "passed": files_changed_recorded}
    )
    checks.append(
        {"name": f"{FLASH_MANIFEST_CHECK_PREFIX}:validation_outputs_present", "passed": validation_outputs_present}
    )

    if not commands_logged:
        failures.append(f"{FLASH_MANIFEST_CHECK_PREFIX}:commands_run_invalid")
    if not files_changed_recorded:
        failures.append(f"{FLASH_MANIFEST_CHECK_PREFIX}:files_changed_invalid")
    if not validation_outputs_present:
        failures.append(f"{FLASH_MANIFEST_CHECK_PREFIX}:validation_outputs_missing")


def _evaluate_vera_regression_verdict(
    *,
    checks: list[dict[str, Any]],
    failures: list[str],
    vera_payload: dict[str, Any] | None,
    evidence_payload: dict[str, Any] | None,
):
    """Evaluate Vera regression smoke verdict quality and evidence presence."""
    # Regression checks must be explicit to satisfy Sprint B exit gate requirements.
    if not isinstance(vera_payload, dict):
        checks.append({"name": "regression:smoke_pass", "passed": False})
        checks.append({"name": "regression:evidence_present", "passed": False})
        checks.append({"name": "coherence:evidence_bundle_link", "passed": False})
        checks.append({"name": "coherence:vera_summary", "passed": False})
        failures.append("regression:vera_payload_missing")
        return

    verdict = vera_payload.get("verdict")
    summary = vera_payload.get("summary")
    evidence_refs = vera_payload.get("evidence_refs")
    evidence_bundle_ref = vera_payload.get("evidence_bundle_ref")
    smoke_checks = vera_payload.get("smoke_checks")

    smoke_pass = verdict == "pass"
    evidence_present = isinstance(evidence_refs, list) and len(evidence_refs) > 0
    bundle_link_present = (
        isinstance(evidence_bundle_ref, str)
        and evidence_bundle_ref == "vera_evidence.json"
        and isinstance(evidence_payload, dict)
    )
    coherence_present = isinstance(summary, str) and bool(summary.strip()) and isinstance(smoke_checks, list)

    checks.append({"name": "regression:smoke_pass", "passed": smoke_pass})
    checks.append({"name": "regression:evidence_present", "passed": evidence_present})
    checks.append({"name": "coherence:evidence_bundle_link", "passed": bundle_link_present})
    checks.append({"name": "coherence:vera_summary", "passed": coherence_present})

    if not smoke_pass:
        failures.append("regression:smoke_failed")
    if not evidence_present:
        failures.append("regression:evidence_missing")
    if not bundle_link_present:
        failures.append("coherence:evidence_bundle_missing_or_unlinked")
    if not coherence_present:
        failures.append("coherence:vera_summary_missing")


def _evaluate_one_change_pilot(
    *,
    checks: list[dict[str, Any]],
    failures: list[str],
    feedback_payload: dict[str, Any] | None,
):
    """Evaluate one-change-per-run pilot policy using feedback_summary payload."""
    # Pilot checks are explicit so policy drift is visible in gatekeeper output.
    if not isinstance(feedback_payload, dict):
        checks.append({"name": f"{IMPROVEMENT_PILOT_CHECK_PREFIX}:single_change_selected", "passed": False})
        checks.append({"name": f"{IMPROVEMENT_PILOT_CHECK_PREFIX}:change_has_rationale", "passed": False})
        failures.append(f"{IMPROVEMENT_PILOT_CHECK_PREFIX}:feedback_summary_missing")
        return

    proposed_changes = feedback_payload.get("proposed_changes")
    pilot = feedback_payload.get("pilot")

    single_change_selected = (
        pilot == "one_change_per_run_v1"
        and isinstance(proposed_changes, list)
        and len(proposed_changes) == 1
    )

    change_has_rationale = False
    if single_change_selected:
        selected_change = proposed_changes[0]
        if isinstance(selected_change, dict):
            title = selected_change.get("title")
            rationale = selected_change.get("rationale")
            change_has_rationale = (
                isinstance(title, str)
                and bool(title.strip())
                and isinstance(rationale, str)
                and bool(rationale.strip())
            )

    checks.append(
        {
            "name": f"{IMPROVEMENT_PILOT_CHECK_PREFIX}:single_change_selected",
            "passed": single_change_selected,
        }
    )
    checks.append(
        {
            "name": f"{IMPROVEMENT_PILOT_CHECK_PREFIX}:change_has_rationale",
            "passed": change_has_rationale,
        }
    )

    if not single_change_selected:
        failures.append(f"{IMPROVEMENT_PILOT_CHECK_PREFIX}:single_change_policy_violation")
    if not change_has_rationale:
        failures.append(f"{IMPROVEMENT_PILOT_CHECK_PREFIX}:missing_change_rationale")


def evaluate_run_artifacts(run_dir: str) -> dict[str, Any]:
    """Evaluate one run directory and return the gatekeeper decision payload."""
    checks = []
    failures = []

    job_payload, _ = _read_json(os.path.join(run_dir, "job.json"))
    job_id = (job_payload or {}).get("job_id", os.path.basename(run_dir))

    for artifact_name, schema_name in SCHEMA_BY_ARTIFACT.items():
        artifact_path = os.path.join(run_dir, artifact_name)
        schema_path = os.path.join(SCHEMA_ROOT, schema_name)

        # Every required artifact must exist, decode as JSON, and contain required fields.
        payload, payload_err = _read_json(artifact_path)
        required_fields = _required_fields_from_schema(schema_path)

        if payload_err:
            checks.append({"name": f"{artifact_name}:exists_and_json", "passed": False})
            failures.append(f"{artifact_name}:{payload_err}")
            continue

        if not isinstance(payload, dict):
            checks.append({"name": f"{artifact_name}:required_fields", "passed": False})
            failures.append(f"{artifact_name}:invalid_type: expected object")
            continue

        checks.append({"name": f"{artifact_name}:exists_and_json", "passed": True})

        missing_fields = _validate_required_fields(payload, required_fields)
        if missing_fields:
            checks.append({"name": f"{artifact_name}:required_fields", "passed": False})
            failures.append(f"{artifact_name}:missing_required={','.join(missing_fields)}")
        else:
            checks.append({"name": f"{artifact_name}:required_fields", "passed": True})

    # Stage checks are isolated so role violations are explicit and fail-closed.
    for artifact_name, expected_stage in EXPECTED_ARTIFACT_STAGE.items():
        exists_check = _get_check_value(f"{artifact_name}:exists_and_json", checks)
        required_check = _get_check_value(f"{artifact_name}:required_fields", checks)

        if exists_check is not True or required_check is not True:
            checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:{artifact_name}:stage", "passed": True})
            continue

        payload, _ = _read_json(os.path.join(run_dir, artifact_name))
        stage = payload.get("stage") if isinstance(payload, dict) else None
        if stage != expected_stage:
            checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:{artifact_name}:stage", "passed": False})
            failures.append(f"{STAGE_ROLE_CHECK_PREFIX}:{artifact_name}:expected_stage={expected_stage}:found={stage}")
        else:
            checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:{artifact_name}:stage", "passed": True})

    tasks_exists = _get_check_value("tasks.json:exists_and_json", checks)
    tasks_required = _get_check_value("tasks.json:required_fields", checks)
    if tasks_exists is True and tasks_required is True:
        tasks_payload, _ = _read_json(os.path.join(run_dir, "tasks.json"))
        tasks_stage = tasks_payload.get("stage") if isinstance(tasks_payload, dict) else None
        tasks = tasks_payload.get("tasks") if isinstance(tasks_payload, dict) else []

        if tasks_stage not in ALLOWED_TASK_STAGES:
            checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:tasks.json:stage", "passed": False})
            failures.append(f"{STAGE_ROLE_CHECK_PREFIX}:tasks.json:invalid_stage={tasks_stage}")
        else:
            checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:tasks.json:stage", "passed": True})

        owner_violations = []
        if isinstance(tasks, list):
            for idx, task in enumerate(tasks):
                if not isinstance(task, dict):
                    owner_violations.append(f"task[{idx}]:invalid_type")
                    continue
                owner = task.get("owner")
                if owner != tasks_stage:
                    owner_violations.append(f"task[{idx}]:owner={owner}:stage={tasks_stage}")

        if owner_violations:
            checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:tasks.json:owner_matches_stage", "passed": False})
            failures.append(
                f"{STAGE_ROLE_CHECK_PREFIX}:tasks.json:owner_mismatch={'|'.join(owner_violations)}"
            )
        else:
            checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:tasks.json:owner_matches_stage", "passed": True})

        _evaluate_mason_task_quality(checks=checks, failures=failures, tasks_payload=tasks_payload)
        _evaluate_sprint_slicer_output(
            run_dir=run_dir,
            checks=checks,
            failures=failures,
            tasks_payload=tasks_payload,
        )
    else:
        checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:tasks.json:stage", "passed": True})
        checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:tasks.json:owner_matches_stage", "passed": True})
        _evaluate_mason_task_quality(checks=checks, failures=failures, tasks_payload=None)
        _evaluate_sprint_slicer_output(run_dir=run_dir, checks=checks, failures=failures, tasks_payload=None)

    feedback_exists = _get_check_value("feedback_summary.json:exists_and_json", checks)
    feedback_required = _get_check_value("feedback_summary.json:required_fields", checks)
    if feedback_exists is True and feedback_required is True:
        feedback_payload, _ = _read_json(os.path.join(run_dir, "feedback_summary.json"))
        _evaluate_one_change_pilot(checks=checks, failures=failures, feedback_payload=feedback_payload)
    else:
        _evaluate_one_change_pilot(checks=checks, failures=failures, feedback_payload=None)

    manifest_exists = _get_check_value("execution_manifest.json:exists_and_json", checks)
    manifest_required = _get_check_value("execution_manifest.json:required_fields", checks)
    if manifest_exists is True and manifest_required is True:
        manifest_payload, _ = _read_json(os.path.join(run_dir, "execution_manifest.json"))
        _evaluate_flash_execution_manifest(checks=checks, failures=failures, manifest_payload=manifest_payload)
    else:
        _evaluate_flash_execution_manifest(checks=checks, failures=failures, manifest_payload=None)

    vera_exists = _get_check_value("vera.json:exists_and_json", checks)
    vera_required = _get_check_value("vera.json:required_fields", checks)
    evidence_exists = _get_check_value("vera_evidence.json:exists_and_json", checks)
    evidence_required = _get_check_value("vera_evidence.json:required_fields", checks)
    evidence_payload: dict[str, Any] | None = None

    if evidence_exists is True and evidence_required is True:
        evidence_payload, _ = _read_json(os.path.join(run_dir, "vera_evidence.json"))

    if vera_exists is True and vera_required is True:
        vera_payload, _ = _read_json(os.path.join(run_dir, "vera.json"))
        _evaluate_vera_regression_verdict(
            checks=checks,
            failures=failures,
            vera_payload=vera_payload,
            evidence_payload=evidence_payload,
        )
    else:
        _evaluate_vera_regression_verdict(
            checks=checks,
            failures=failures,
            vera_payload=None,
            evidence_payload=evidence_payload,
        )

    # Causality checks rely on a valid run trace and emit explicit pass/fail entries.
    run_trace_exists = _get_check_value("run_trace.json:exists_and_json", checks)
    run_trace_required = _get_check_value("run_trace.json:required_fields", checks)
    if run_trace_exists is True and run_trace_required is True:
        run_trace_payload, _ = _read_json(os.path.join(run_dir, "run_trace.json"))
        events = run_trace_payload.get("events") if isinstance(run_trace_payload, dict) else []
        trace_violations = []
        trace_order_violation = False
        trace_missing_required = []

        if isinstance(events, list):
            last_at = ""
            seen_by_stage: dict[str, set[str]] = {}
            for idx, event in enumerate(events):
                if not isinstance(event, dict):
                    trace_violations.append(f"event[{idx}]:invalid_type")
                    continue
                stage = event.get("stage")
                name = event.get("event")
                at = event.get("at")

                # ISO8601 UTC strings compare lexicographically when format is consistent.
                if isinstance(at, str):
                    if last_at and at < last_at:
                        trace_order_violation = True
                    if at >= last_at:
                        last_at = at

                if not isinstance(stage, str):
                    trace_violations.append(f"event[{idx}]:unsupported_stage={stage}")
                    continue

                allowed_events = ALLOWED_RUN_TRACE_EVENTS.get(stage)
                if not allowed_events:
                    trace_violations.append(f"event[{idx}]:unsupported_stage={stage}")
                    continue
                if name not in allowed_events:
                    trace_violations.append(f"event[{idx}]:{stage}.{name}")

                if isinstance(stage, str) and isinstance(name, str):
                    seen_by_stage.setdefault(stage, set()).add(name)

            missing_krax = sorted(REQUIRED_KRAX_TRACE_EVENTS.difference(seen_by_stage.get("krax", set())))
            missing_gatekeeper = sorted(
                REQUIRED_GATEKEEPER_TRACE_EVENTS.difference(seen_by_stage.get("gatekeeper", set()))
            )
            missing_vera = sorted(REQUIRED_VERA_TRACE_EVENTS.difference(seen_by_stage.get("vera", set())))
            trace_missing_required = [
                *[f"krax.{name}" for name in missing_krax],
                *[f"vera.{name}" for name in missing_vera],
                *[f"gatekeeper.{name}" for name in missing_gatekeeper],
            ]

        if trace_violations:
            checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:run_trace.json:event_stage_ownership", "passed": False})
            failures.append(
                f"{STAGE_ROLE_CHECK_PREFIX}:run_trace.json:event_stage_ownership={'|'.join(trace_violations)}"
            )
        else:
            checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:run_trace.json:event_stage_ownership", "passed": True})

        if trace_order_violation:
            checks.append({"name": f"{BASELINE_CHECK_PREFIX}:causality:ordered_timestamps", "passed": False})
            failures.append(f"{BASELINE_CHECK_PREFIX}:causality:run_trace_unordered")
        else:
            checks.append({"name": f"{BASELINE_CHECK_PREFIX}:causality:ordered_timestamps", "passed": True})

        if trace_missing_required:
            checks.append({"name": f"{BASELINE_CHECK_PREFIX}:causality:required_events", "passed": False})
            failures.append(
                f"{BASELINE_CHECK_PREFIX}:causality:missing_events={'|'.join(trace_missing_required)}"
            )
        else:
            checks.append({"name": f"{BASELINE_CHECK_PREFIX}:causality:required_events", "passed": True})
    else:
        checks.append({"name": f"{STAGE_ROLE_CHECK_PREFIX}:run_trace.json:event_stage_ownership", "passed": True})
        checks.append({"name": f"{BASELINE_CHECK_PREFIX}:causality:ordered_timestamps", "passed": True})
        checks.append({"name": f"{BASELINE_CHECK_PREFIX}:causality:required_events", "passed": True})

    # Baseline aggregation ensures gatekeeper emits consistent top-level summary checks.
    contract_failed = _has_failed_contract_checks(checks)
    stage_role_failed = _has_failed_prefix(checks, f"{STAGE_ROLE_CHECK_PREFIX}:")
    causality_failed = _has_failed_prefix(checks, f"{BASELINE_CHECK_PREFIX}:causality:")

    checks.append({"name": f"{BASELINE_CHECK_PREFIX}:contract", "passed": not contract_failed})
    checks.append({"name": f"{BASELINE_CHECK_PREFIX}:stage_role", "passed": not stage_role_failed})
    checks.append({"name": f"{BASELINE_CHECK_PREFIX}:causality", "passed": not causality_failed})

    baseline_failed = contract_failed or stage_role_failed or causality_failed
    if baseline_failed:
        failures.append(f"{BASELINE_CHECK_PREFIX}:one_or_more_checks_failed")

    approved = len(failures) == 0
    reason = "all_baseline_checks_passed" if approved else "; ".join(failures)

    return {
        "job_id": job_id,
        "approved": approved,
        "reason": reason,
        "checks": checks,
        "created_at": fs.utc_now_iso(),
    }


def write_gatekeeper_decision(run_dir: str) -> dict[str, Any]:
    """Persist gatekeeper decision artifact to run directory."""
    decision = evaluate_run_artifacts(run_dir)
    decision_path = os.path.join(run_dir, "gatekeeper_decision.json")
    fs.write_json_atomic(decision_path, decision)
    return decision
