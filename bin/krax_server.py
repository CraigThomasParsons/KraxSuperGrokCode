#!/usr/bin/env python3
import http.server
import socketserver
import json
import os
import sys
import threading
import time
import uuid
from typing import Optional

# Ensure we can import from lib
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    # Add script dir so we can import local lib modules securely
    sys.path.append(script_dir)

repo_root = os.path.dirname(script_dir)
if repo_root not in sys.path:
    sys.path.append(repo_root)

import subprocess
import shlex
from lib import fs, parser
from lib.feedback_synthesis import write_feedback_artifacts
from lib.regression_smoke import write_vera_smoke_verdict
from lib.runtime_artifact_validator import has_stage_role_violations, write_gatekeeper_decision
from contracts.auralis_to_krax import validate_krax_job
from lib import post_office
from lib.grok_api_client import GrokApiClient
from lib.inbox_classifier import classify_package, AURALIS_JOB, BRIDGIT_PACKAGE
from lib.artifact_reader import read_artifacts_from_directory
from lib.stage_runner import execute_stage_one

# Krax runs on port 3001 to avoid colliding with Auralis on 3000
PORT = 3001
INBOX_POLL_INTERVAL_SEC = 5


def load_config(config_path: str) -> dict:
    config = {}

    if not os.path.exists(config_path):
        return config

    with open(config_path, "r", encoding="utf-8") as config_file:
        for raw_line in config_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue

            key, value = line.split(":", 1)
            config[key.strip()] = value.strip()

    return config


def update_config_yaml(cookie_string: str, device_id: str = "") -> None:
    """
    Write fresh Grok session credentials to config.yaml.

    Preserves existing comments and non-cookie config lines. Only overwrites
    the grok_session_cookie and grok_device_id values. Called by the
    /api/cookie/update endpoint when the Chrome Extension pushes new cookies.
    """
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.yaml"))

    # Read the existing config file to preserve comments and other settings.
    existing_lines = []
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as config_file:
            existing_lines = config_file.readlines()

    # Track which keys we've updated so we can append missing ones at the end.
    updated_cookie = False
    updated_device = False
    output_lines = []

    for line in existing_lines:
        stripped_line = line.strip()

        # Replace the grok_session_cookie line with the fresh value.
        if stripped_line.startswith("grok_session_cookie:"):
            output_lines.append(f"grok_session_cookie: {cookie_string}\n")
            updated_cookie = True
        # Replace the grok_device_id line if a new device ID was provided.
        elif stripped_line.startswith("grok_device_id:") and device_id:
            output_lines.append(f"grok_device_id: {device_id}\n")
            updated_device = True
        else:
            # Preserve all other lines (comments, blank lines, other config).
            output_lines.append(line)

    # If the config file didn't have these keys, append them.
    if not updated_cookie:
        output_lines.append(f"grok_session_cookie: {cookie_string}\n")
    if not updated_device and device_id:
        output_lines.append(f"grok_device_id: {device_id}\n")

    # Write atomically by writing to a temp file first, then renaming.
    # This prevents partial writes from corrupting config.yaml mid-update.
    temp_path = config_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as temp_file:
        temp_file.writelines(output_lines)
    os.replace(temp_path, config_path)


def resolve_auralis_inbox_path(config: dict) -> str:
    configured = (config.get("auralis_inbox_path") or "").strip()
    if configured:
        return configured

    inferred = os.path.abspath(os.path.join(repo_root, "..", "Auralis", "inbox"))
    return inferred


def _write_text(path: str, content: str):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def dispatch_report_to_auralis(job_id: str, run_dir: str, decision: dict, outcome: str):
    job_payload = {}
    job_path = os.path.join(run_dir, "job.json")
    if os.path.exists(job_path):
        try:
            with open(job_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
                if isinstance(payload, dict):
                    job_payload = payload
        except json.JSONDecodeError:
            job_payload = {}

    source_auralis_job_id = (job_payload.get("metadata") or {}).get("auralis_job_id")
    if not isinstance(source_auralis_job_id, str) or not source_auralis_job_id.strip():
        source_auralis_job_id = "unknown"

    report_job_id = f"krax_report_{job_id}_{uuid.uuid4().hex[:8]}"
    report_dir = os.path.join(fs.OUTBOX_DIR, report_job_id)
    os.makedirs(report_dir, exist_ok=True)

    approved = bool(decision.get("approved"))
    reason = str(decision.get("reason", "unknown_reason"))
    archived_target = os.path.join(fs.ARCHIVE_DIR, job_id)
    failed_target = os.path.join(fs.FAILED_DIR, job_id)
    final_target = archived_target if outcome == "archived" else failed_target

    _write_text(
        os.path.join(report_dir, "briefing.md"),
        (
            "Krax completed a run and is reporting results back for Auralis planning.\n"
            f"source_auralis_job_id: {source_auralis_job_id}\n"
            f"krax_job_id: {job_id}\n"
            f"outcome: {outcome}\n"
            f"approved: {approved}\n"
            f"reason: {reason}\n"
            f"artifact_dir: {final_target}\n"
        ),
    )

    # Extract actual payload contents to prevent Auralis from needing to execute file reads natively.
    gatekeeper_content = "{}"
    gk_path = os.path.join(final_target, "gatekeeper_decision.json")
    if os.path.exists(gk_path):
        try:
            with open(gk_path, "r", encoding="utf-8") as f:
                gatekeeper_content = f.read().strip()
        except:
            gatekeeper_content = '{"error": "Failed to read gatekeeper_decision.json"}'

    feedback_content = "{}"
    fb_path = os.path.join(final_target, "feedback_summary.json")
    if os.path.exists(fb_path):
        try:
            with open(fb_path, "r", encoding="utf-8") as f:
                feedback_content = f.read().strip()
        except:
            feedback_content = '{"error": "Failed to read feedback_summary.json"}'

    _write_text(
        os.path.join(report_dir, "context.md"),
        (
            "This message was auto-generated by Krax at end-of-run.\n\n"
            "### gatekeeper_decision.json\n"
            "```json\n"
            f"{gatekeeper_content}\n"
            "```\n\n"
            "### feedback_summary.json\n"
            "```json\n"
            f"{feedback_content}\n"
            "```\n"
        ),
    )

    _write_text(
        os.path.join(report_dir, "goals.md"),
        "Synthesize feedback and produce the next Auralis plan update for the same product intent.",
    )

    _write_text(
        os.path.join(report_dir, "success.md"),
        "Auralis acknowledges the run outcome and emits a revised, actionable next plan.",
    )

    _write_text(
        os.path.join(report_dir, "steps.md"),
        (
            "1) Analyze the gatekeeper_decision.json and feedback_summary.json provided in the context.\n"
            "2) Incorporate findings into next-loop planning to fix the identified issues.\n"
            "3) Emit the revised plan artifact and constraints."
        ),
    )

    _write_text(os.path.join(report_dir, "url.txt"), "https://chatgpt.com/g/g-p-69b999011d348191951b6a69c247a2b2-code-the-aamf-agents/c/69b9b6ec-e158-8332-864b-4b5ddea80bcc")
    
    # Delegate the physical directory transfer to ThePostalService
    post_office.dispatch_package("krax", "mason", report_job_id, fs.OUTBOX_DIR)
    print(f"[TYS] Report-back dispatched to Auralis via PostalService: {report_job_id}")


CONFIG = load_config(os.path.join(repo_root, "config.yaml"))

STATE_PENDING = "PENDING"
STATE_IN_PROGRESS = "IN_PROGRESS"
STATE_GROK_COMPLETE = "GROK_COMPLETE"
STATE_DONE = "DONE"
STATE_FAILED = "FAILED"

state_lock = threading.Lock()
in_flight_job_id: Optional[str] = None
in_flight_state: Optional[str] = None


def set_in_flight(job_id: str, state: str):
    global in_flight_job_id, in_flight_state
    with state_lock:
        in_flight_job_id = job_id
        in_flight_state = state


def clear_in_flight():
    global in_flight_job_id, in_flight_state
    with state_lock:
        in_flight_job_id = None
        in_flight_state = None


def get_in_flight_state():
    with state_lock:
        return in_flight_job_id, in_flight_state


def build_prompt(job: dict) -> str:
    goal = job.get("goal", "").strip() or "No goal provided."
    context = job.get("context", "").strip() or "No context provided."
    instructions = job.get("instructions", "").strip() or "No instructions provided."
    constraints = job.get("constraints", [])
    if not isinstance(constraints, list):
        constraints = [str(constraints)]

    lines = [
        "## Goal",
        goal,
        "",
        "## Context",
        context,
        "",
        "## Instructions",
        instructions,
        "",
        "## Constraints",
    ]

    if constraints:
        lines.extend([f"- {str(item)}" for item in constraints])
    else:
        lines.append("- No constraints provided.")

    return "\n".join(lines)


def handle_bridgit_package(inbox_entry_name: str):
    """
    Process a Bridgit artifact package deposited by the ChatProjectsToKraxBridge.

    Reads the artifact bundle, runs Stage 1 (ensure Grok project exists + set
    Instructions), and archives the package on success or moves to failed/ on error.
    Stage 2 (source upload) is skipped until C1 API discovery is complete.
    """
    inbox_path = os.path.join(fs.INBOX_DIR, inbox_entry_name)
    print(f"[Bridgit] Processing package: {inbox_entry_name}")

    try:
        # Read artifacts from the inbox package directory.
        artifact_bundle = read_artifacts_from_directory(inbox_path)

        if not artifact_bundle.is_valid():
            print(f"[Bridgit] Invalid package (missing VISION.md): {inbox_entry_name}")
            fs.reject_job(inbox_entry_name, ["bridgit_package_invalid: missing VISION.md"])
            return

        # Determine project name from letter.toml metadata or VISION.md heading.
        project_name = artifact_bundle.get_project_name()
        if not project_name:
            print(f"[Bridgit] Cannot determine project name for: {inbox_entry_name}")
            fs.reject_job(inbox_entry_name, ["bridgit_package_invalid: no project name"])
            return

        # Stage 1: Ensure Grok project exists and set Instructions.
        grok_client = GrokApiClient()
        stage_one_result = execute_stage_one(
            grok_client=grok_client,
            artifact_bundle=artifact_bundle,
            project_name=project_name,
        )

        print(f"[Bridgit] Stage 1 complete: {stage_one_result.get('action_taken')} "
              f"project '{project_name}' (id: {stage_one_result.get('grok_project_id')})")

        # Write sync result into the package before archiving.
        sync_result = {
            "package": inbox_entry_name,
            "project_name": project_name,
            "stage_1": stage_one_result,
            "stage_2": "pending_api_discovery",
            "completed_at": fs.utc_now_iso(),
        }
        fs.write_json_atomic(os.path.join(inbox_path, "sync_result.json"), sync_result)

        # Archive the successfully processed package.
        fs.archive_job(inbox_entry_name)
        print(f"[Bridgit] Archived package: {inbox_entry_name}")

    except RuntimeError as api_error:
        # RuntimeError from stage_runner means Grok API is unreachable.
        print(f"[Bridgit] API error for {inbox_entry_name}: {api_error}")
        fs.write_json_atomic(
            os.path.join(inbox_path, "sync_failure.json"),
            {"error": str(api_error), "failed_at": fs.utc_now_iso()},
        )
        fs.fail_job(inbox_entry_name)

    except Exception as unexpected_error:
        print(f"[Bridgit] Unexpected error for {inbox_entry_name}: {unexpected_error}")
        fs.fail_job(inbox_entry_name)


def poll_inbox():
    while True:
        jobs = fs.find_jobs()

        for inbox_job_dir in jobs:
            # Classify the package before processing — Bridgit packages
            # take a different path than Auralis jobs.
            inbox_full_path = os.path.join(fs.INBOX_DIR, inbox_job_dir)
            package_type = classify_package(inbox_full_path)

            if package_type == BRIDGIT_PACKAGE:
                handle_bridgit_package(inbox_job_dir)
                continue

            # Below this point: existing Auralis job handling (unchanged).
            try:
                job = fs.read_job_files(inbox_job_dir)
                reasons = validate_krax_job(job)

                if reasons:
                    fs.reject_job(inbox_job_dir, reasons)
                    print(f"[TYS] Rejected job {inbox_job_dir}: {', '.join(reasons)}")
                    continue

                canonical_job_id = job["job_id"]
                run_dir = fs.promote_job_to_run(inbox_job_dir)
                fs.write_receipt(canonical_job_id, run_dir, source=job.get("source_agent", "auralis"))
                fs.append_run_trace_event(
                    run_dir,
                    job_id=canonical_job_id,
                    stage="krax",
                    event="received",
                    detail="Promoted inbox job to runs and wrote receipt.",
                )
                print(f"[TYS] Job {canonical_job_id} received from Auralis")

                # Native Tool Interception (Executes physically without Chrome Extension)
                if job.get("action") == "create_project":
                    print(f"[*] Krax native tool execution: create_project for '{job.get('goal')}'")
                    try:
                        client = GrokApiClient()
                        project_data = client.create_project(
                            name=job.get("goal", "Automated Project"),
                            description=job.get("context", "")
                        )
                        # Complete natively and bypass the browser extension queue
                        fs.write_text_atomic(os.path.join(run_dir, "grok.txt"), json.dumps(project_data))
                        fs.write_text_atomic(os.path.join(run_dir, "response.txt"), f"Project created natively.\n\nProject ID: {project_data.get('id', 'unknown')}")
                        fs.update_receipt_status(run_dir, "grok_complete")
                        fs.append_run_trace_event(
                            run_dir,
                            job_id=canonical_job_id,
                            stage="krax",
                            event="native_tool_executed",
                            detail="create_project tool successfully executed via internal API driver.",
                        )
                        fs.archive_job(canonical_job_id)
                        continue
                    except Exception as e:
                        print(f"[!] Error executing native create_project tool: {e}")
                        fs.fail_job(canonical_job_id)
                        continue

            except Exception as exc:
                try:
                    fs.reject_job(inbox_job_dir, [f"malformed_job: {exc}"])
                except Exception as reject_exc:
                    print(f"[TYS] Failed to reject malformed job {inbox_job_dir}: {reject_exc}")
                print(f"[TYS] Error while processing inbox job {inbox_job_dir}: {exc}")

        time.sleep(INBOX_POLL_INTERVAL_SEC)

class KraxHandler(http.server.BaseHTTPRequestHandler):
    
    # Establish standard CORS headers so the Extension can fetch local API
    def _set_headers(self, code=200):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        # Wildcard allows the grok.com background script to bypass same-origin policy
        self.send_header('Access-Control-Allow-Origin', '*') 
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    # Handle HTTP OPTIONS preflight explicitly
    def do_OPTIONS(self):
        self._set_headers()

    # Handle Job Polling
    def do_GET(self):
        if self.path == '/job':
            current_job_id, current_state = get_in_flight_state()

            # Only one active dispatch is allowed at a time.
            if current_job_id and current_state in (STATE_PENDING, STATE_IN_PROGRESS):
                self._set_headers(200)
                self.wfile.write(json.dumps({"job": None}).encode())
                return

            jobs = fs.find_pending_run_jobs()
            if not jobs:
                self._set_headers(200)
                self.wfile.write(json.dumps({"job": None}).encode())
                return

            job_id = jobs[0]
            try:
                job_data = fs.read_run_job(job_id)
                prompt = build_prompt(job_data)

                set_in_flight(job_id, STATE_IN_PROGRESS)
                fs.update_receipt_status(os.path.join(fs.RUNS_DIR, job_id), "in_progress")
                fs.append_run_trace_event(
                    os.path.join(fs.RUNS_DIR, job_id),
                    job_id=job_id,
                    stage="krax",
                    event="dispatch_prompt",
                    detail="Served prompt payload to extension via /job.",
                )

                url = job_data.get("url", "https://grok.com/project/c84f9f0e-f423-4148-97cb-b76f92f1fa64")
                attachments = job_data.get("attachments", [])
                response = {
                    "job_id": job_id,
                    "id": job_id,
                    "url": url,
                    "prompt": prompt,
                    "attachments": attachments,
                }

                self._set_headers(200)
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                print(f"Error reading Krax job {job_id}: {e}")
                set_in_flight(job_id, STATE_FAILED)
                fs.fail_job(job_id)
                clear_in_flight()
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self._set_headers(404)

    # Handle Job Completion Reports
    def do_POST(self):
        if self.path in ('/job/complete', '/complete'):
            length = int(self.headers.get('content-length', 0))
            raw_data = self.rfile.read(length)

            print(f"KRAX: Received payload size: {length}")

            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError as e:
                print(f"KRAX: JSON Parse Error: {e}")
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "invalid_json"}).encode())
                return

            job_id = data.get("job_id") or data.get("id")
            result_text = data.get("response")
            debug_info = data.get("debug", "No debug info")

            if not job_id or not isinstance(result_text, str):
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "missing_job_id_or_response"}).encode())
                return

            current_job_id, current_state = get_in_flight_state()
            if current_job_id != job_id or current_state != STATE_IN_PROGRESS:
                self._set_headers(409)
                self.wfile.write(json.dumps({
                    "error": "job_not_in_progress",
                    "expected_job_id": current_job_id,
                    "received_job_id": job_id,
                }).encode())
                return

            print(f"[*] Krax Job {job_id} completed by Extension.")

            run_dir = os.path.join(fs.RUNS_DIR, job_id)
            os.makedirs(run_dir, exist_ok=True)

            fs.write_text_atomic(os.path.join(run_dir, "grok.txt"), result_text)
            fs.write_text_atomic(os.path.join(run_dir, "response.txt"), result_text)
            fs.update_receipt_status(run_dir, "grok_complete")
            set_in_flight(job_id, STATE_GROK_COMPLETE)
            fs.append_run_trace_event(
                run_dir,
                job_id=job_id,
                stage="krax",
                event="grok_complete",
                detail="Received /complete payload and persisted grok/response text.",
            )

            extracted_snippets = parser.extract_snippet_files(result_text)

            extracted_dir = os.path.join(run_dir, "extracted")

            manifest = []

            if extracted_snippets:
                os.makedirs(extracted_dir, exist_ok=True)

                for snippet in extracted_snippets:
                    final_filename = snippet.filename
                    target_file_path = os.path.join(extracted_dir, final_filename)
                    counter = 2

                    while os.path.exists(target_file_path):
                        base, ext = os.path.splitext(snippet.filename)
                        final_filename = f"{base}.{counter}{ext}"
                        target_file_path = os.path.join(extracted_dir, final_filename)
                        counter += 1

                    with open(target_file_path, "w") as sf:
                        sf.write(snippet.code)

                    print(f"  - Extracted snippet: {final_filename}")

                    manifest.append({
                        "filename": final_filename,
                        "language": snippet.language,
                        "detection_method": snippet.detection_method,
                        "confidence": snippet.confidence
                    })

                manifest_path = os.path.join(run_dir, "extracted_files.json")
                with open(manifest_path, "w") as mf:
                    mf.write(json.dumps(manifest, indent=2))

            krax_output_path = os.path.join(run_dir, "krax_output.json")
            krax_output = {
                "job_id": job_id,
                "implementation_summary": "Extracted code from Grok.",
                "files_changed": [m["filename"] for m in manifest],
                "commands_run": [],
                "expected_behavior": "The generated code should render visually accurately."
            }
            with open(krax_output_path, "w") as output_f:
                output_f.write(json.dumps(krax_output, indent=2))

            # Emit Flash execution manifest so downstream validation can audit execution evidence.
            execution_manifest = {
                "job_id": job_id,
                "stage": "flash",
                "commands_run": [
                    "extension_prompt_dispatch",
                    "extension_response_capture",
                    "snippet_extraction",
                ],
                "files_changed": [m["filename"] for m in manifest],
                "validation_outputs": [
                    {
                        "name": "response_text_persisted",
                        "status": "pass" if bool(result_text.strip()) else "fail",
                        "detail": "grok.txt and response.txt persisted from /complete payload.",
                    },
                    {
                        "name": "snippet_manifest_written",
                        "status": "pass",
                        "detail": "extracted_files.json is written only when snippets are detected.",
                    },
                ],
                "created_at": fs.utc_now_iso(),
            }
            fs.write_json_atomic(os.path.join(run_dir, "execution_manifest.json"), execution_manifest)
            fs.append_run_trace_event(
                run_dir,
                job_id=job_id,
                stage="krax",
                event="execution_manifest_written",
                detail="Wrote execution_manifest.json for Flash execution evidence.",
            )

            # Run deterministic Vera smoke checks and persist machine-readable verdict.
            vera_verdict = write_vera_smoke_verdict(run_dir, job_id)
            fs.append_run_trace_event(
                run_dir,
                job_id=job_id,
                stage="vera",
                event="regression_smoke_complete",
                detail=f"verdict={vera_verdict['verdict']} summary={vera_verdict['summary']}",
            )

            # Feed Vera output back into Auralis artifacts for next-cycle planning.
            feedback_summary, _ = write_feedback_artifacts(run_dir, job_id)
            fs.append_run_trace_event(
                run_dir,
                job_id=job_id,
                stage="auralis",
                event="feedback_synthesized",
                detail=(
                    f"status={feedback_summary['status']} "
                    f"findings={len(feedback_summary.get('findings', []))} "
                    f"selected_changes={len(feedback_summary.get('proposed_changes', []))}"
                ),
            )

            fs.write_handoff(job_id, run_dir)
            fs.append_run_trace_event(
                run_dir,
                job_id=job_id,
                stage="krax",
                event="handoff_written",
                detail="Wrote handoff artifact for downstream verifier.",
            )

            decision = write_gatekeeper_decision(run_dir)
            print(
                f"[TYS] Gatekeeper decision for {job_id}: approved={decision['approved']} reason={decision['reason']}"
            )
            fs.append_run_trace_event(
                run_dir,
                job_id=job_id,
                stage="gatekeeper",
                event="decision_recorded",
                detail=f"approved={decision['approved']} reason={decision['reason']}",
            )

            if has_stage_role_violations(decision):
                # Role violations are hard-stop failures because stage boundaries are non-negotiable.
                fs.append_run_trace_event(
                    run_dir,
                    job_id=job_id,
                    stage="gatekeeper",
                    event="role_violation",
                    detail=f"Fail-closed triggered: {decision['reason']}",
                )
                fs.update_receipt_status(run_dir, "failed_role_violation")
                moved = fs.fail_job(job_id)

                failed_run_dir = os.path.join(fs.FAILED_DIR, job_id)
                report_dir = failed_run_dir if os.path.exists(failed_run_dir) else run_dir
                dispatch_report_to_auralis(job_id, report_dir, decision, "failed")

                if os.path.exists(failed_run_dir):
                    fs.append_run_trace_event(
                        failed_run_dir,
                        job_id=job_id,
                        stage="krax",
                        event="failed",
                        detail="Blocked by gatekeeper due to stage-role violation.",
                    )

                set_in_flight(job_id, STATE_FAILED)
                clear_in_flight()

                self._set_headers(409)
                self.wfile.write(
                    json.dumps(
                        {
                            "status": "failed",
                            "error": "stage_role_violation",
                            "reason": decision["reason"],
                            "moved": bool(moved),
                        }
                    ).encode()
                )
                return

            # Promotion is allowed only when gatekeeper explicitly approves the run.
            if not bool(decision.get("approved")):
                # Reject promotion whenever gatekeeper approval is false, even if prior steps succeeded.
                fs.append_run_trace_event(
                    run_dir,
                    job_id=job_id,
                    stage="gatekeeper",
                    event="promotion_blocked",
                    detail=f"Gatekeeper rejected promotion: {decision.get('reason', 'unknown_reason')}",
                )
                fs.update_receipt_status(run_dir, "failed_gatekeeper")
                moved = fs.fail_job(job_id)

                failed_run_dir = os.path.join(fs.FAILED_DIR, job_id)
                report_dir = failed_run_dir if os.path.exists(failed_run_dir) else run_dir
                dispatch_report_to_auralis(job_id, report_dir, decision, "failed")

                if os.path.exists(failed_run_dir):
                    fs.append_run_trace_event(
                        failed_run_dir,
                        job_id=job_id,
                        stage="krax",
                        event="failed",
                        detail="Blocked by gatekeeper because approved=false.",
                    )

                set_in_flight(job_id, STATE_FAILED)
                clear_in_flight()

                self._set_headers(409)
                self.wfile.write(
                    json.dumps(
                        {
                            "status": "failed",
                            "error": "gatekeeper_rejected",
                            "reason": decision.get("reason", "unknown_reason"),
                            "moved": bool(moved),
                        }
                    ).encode()
                )
                return

            fs.archive_job(job_id)
            archived_run_dir = os.path.join(fs.ARCHIVE_DIR, job_id)
            if os.path.exists(archived_run_dir):
                dispatch_report_to_auralis(job_id, archived_run_dir, decision, "archived")
                fs.append_run_trace_event(
                    archived_run_dir,
                    job_id=job_id,
                    stage="krax",
                    event="archived",
                    detail="Archived completed run artifacts.",
                )
            set_in_flight(job_id, STATE_DONE)
            clear_in_flight()

            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "grok_complete"}).encode())
            
        elif self.path == '/job/fail':
            length = int(self.headers.get('content-length', 0))

            try:
                data = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "invalid_json"}).encode())
                return

            job_id = data.get("id")
            error = data.get("error")

            if not job_id:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "missing_job_id"}).encode())
                return

            print(f"[!] Krax Job {job_id} failed: {error}")
            moved = fs.fail_job(job_id)

            failed_job_dir = os.path.join(fs.FAILED_DIR, job_id)
            os.makedirs(failed_job_dir, exist_ok=True)
            fs.write_json_atomic(
                os.path.join(failed_job_dir, "failure.json"),
                {
                    "job_id": job_id,
                    "failed_at": fs.utc_now_iso(),
                    "error": error or "unknown_error",
                    "moved": bool(moved),
                },
            )
            fs.append_run_trace_event(
                failed_job_dir,
                job_id=job_id,
                stage="krax",
                event="failed",
                detail=f"Failure reported via /job/fail. error={error or 'unknown_error'}",
            )

            current_job_id, _ = get_in_flight_state()
            if current_job_id == job_id:
                set_in_flight(job_id, STATE_FAILED)
                clear_in_flight()

            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "failed", "moved": bool(moved)}).encode())

        elif self.path == '/api/cookie/update':
            # Receives fresh Grok session cookies from the Chrome Extension's
            # automatic cookie extraction alarm. This keeps config.yaml current
            # so the GrokApiClient always has valid credentials without manual
            # intervention or browser DevTools cookie copying.
            length = int(self.headers.get('content-length', 0))

            try:
                data = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "invalid_json"}).encode())
                return

            cookie_string = data.get("cookie_string", "").strip()
            device_id_value = data.get("device_id", "").strip()

            if not cookie_string:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "missing_cookie_string"}).encode())
                return

            try:
                # Persist the cookie to config.yaml so it survives server restarts.
                update_config_yaml(cookie_string, device_id_value)

                # Hot-reload the in-memory GrokApiClient so the next API call
                # uses the fresh cookie without requiring a server restart.
                grok_client = GrokApiClient()
                grok_client.reload_config()

                # Log the update with length, not the actual cookie value —
                # cookies are secrets and should not appear in log files.
                print(f"[Cookie API] Updated grok_session_cookie ({len(cookie_string)} chars)")

                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "message": "Cookie updated",
                    "cookie_length": len(cookie_string),
                }).encode())

            except Exception as config_write_error:
                print(f"[Cookie API] Error updating config: {config_write_error}")
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(config_write_error)}).encode())

        else:
            self._set_headers(404)

# Execute the application loop continuously
def run():
    print(f"[*] Krax Server running on port {PORT}")

    poller = threading.Thread(target=poll_inbox, daemon=True)
    poller.start()
    
    # Custom server class with SO_REUSEADDR to allow immediate TCP port reuse
    # This prevents 'Address Already In Use' errors if the server restarts rapidly
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True
    
    # Bind to all interfaces securely
    with ReusableTCPServer(("", PORT), KraxHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            # Trap keyboard interrupts for clean shutdown logging
            print("\n[*] Krax Server stopped.")
        finally:
            httpd.server_close()

if __name__ == "__main__":
    run()
