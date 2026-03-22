import os
import shutil
import json
from datetime import datetime, timezone
from typing import Optional, Dict

# Establish absolute paths from the root of the Krax codebase
# This ensures execution works regardless of the current working directory
KRAX_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
INBOX_DIR = os.path.join(KRAX_ROOT, "inbox")
RUNS_DIR = os.path.join(KRAX_ROOT, "runs")
OUTBOX_DIR = os.path.join(KRAX_ROOT, "outbox")
ARCHIVE_DIR = os.path.join(KRAX_ROOT, "archive")
FAILED_DIR = os.path.join(KRAX_ROOT, "failed")

# The specific files required for a job to be valid
# Krax runs entirely on the strict phase 1 job.json contract
REQUIRED_FILES = ["job.json"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json_atomic(file_path: str, payload: dict):
    temp_path = f"{file_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp_path, file_path)


def write_text_atomic(file_path: str, content: str):
    temp_path = f"{file_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(temp_path, file_path)


def _load_json_if_exists(path: str) -> dict:
    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError:
            return {}

    return payload if isinstance(payload, dict) else {}


def append_run_trace_event(run_dir: str, *, job_id: str, stage: str, event: str, detail: str):
    trace_path = os.path.join(run_dir, "run_trace.json")
    payload = _load_json_if_exists(trace_path)

    now = utc_now_iso()
    events = payload.get("events")
    if not isinstance(events, list):
        events = []

    events.append(
        {
            "at": now,
            "stage": stage,
            "event": event,
            "detail": detail,
        }
    )

    started_at = payload.get("started_at")
    if not isinstance(started_at, str) or not started_at.strip():
        started_at = now

    trace_payload = {
        "job_id": job_id,
        "started_at": started_at,
        "updated_at": now,
        "events": events,
    }
    write_json_atomic(trace_path, trace_payload)

def find_jobs():
    """
    Scans the inbox directory for pending work.
    Returns a sorted list of job IDs based on subdirectories found.
    """
    # Initialize an empty list to gather valid job directories
    jobs = []
    
    # If the inbox directory hasn't even been created yet, return empty
    # This prevents crash loops on fresh system installs
    if not os.path.exists(INBOX_DIR):
        return []
    
    # Iterate over every item dropped into the inbox folder
    for item in os.listdir(INBOX_DIR):
        job_path = os.path.join(INBOX_DIR, item)
        
        # We assume every folder in the inbox represents a distinct job package
        # Loose files are ignored to prevent processing partial drops
        if os.path.isdir(job_path):
            jobs.append(item)
            
    # Yield jobs in alphabetical/chronological order
    return sorted(jobs)

def read_job_files(job_id: str) -> Dict[str, str]:
    """
    Reads the strict job.json contract into memory.
    Raises ValueError if the contract is absent or unparseable.
    """
    # Locate the definitive path for this specific job package
    job_dir = os.path.join(INBOX_DIR, job_id)
    payload = {}
    
    # Check for the existence of the critical job payload
    contract_path = os.path.join(job_dir, "job.json")
    
    # Abort if the caller failed to provide the minimum required specification
    if not os.path.exists(contract_path):
        raise ValueError(f"Job {job_id} missing mandatory contract: job.json")
        
    # Read the payload safely ensuring UTF-8 encoding compatibility
    with open(contract_path, "r", encoding="utf-8") as f:
        # Load the JSON string directly into a python dictionary
        try:
            payload = json.load(f)
        except json.JSONDecodeError as e:
            # Trap decode errors to prevent the worker from crashing outright
            raise ValueError(f"Job {job_id} has malformed job.json: {e}")
            
    # Return the dictionary for further processing by the logic layer
    return payload


def read_run_job(job_id: str) -> Dict[str, str]:
    run_dir = os.path.join(RUNS_DIR, job_id)
    contract_path = os.path.join(run_dir, "job.json")

    if not os.path.exists(contract_path):
        raise ValueError(f"Run {job_id} missing job.json")

    with open(contract_path, "r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Run {job_id} has malformed job.json: {exc}")

def compose_briefing(job_id: str, job_data: dict) -> str:
    """
    Compiles the dictionary payload into a raw prompt for Grok.
    This injects the constraints and instructions as plaintext.
    """
    # Begin building the prompt line by line into a list
    # The prompt drives Grok's code generation strictly locally
    lines = []
    
    # Provide system context first so Grok understands its role
    lines.append(f"## KRAX AUTOMATED WORKER - Job ID: {job_id}")
    lines.append("I am Krax, an automated bot. Execute the following immediately.")
    lines.append("")
    
    # State the primary goal clearly for the LLM
    lines.append("### GOAL")
    lines.append(job_data.get("goal", "Implement standard functional feature."))
    lines.append("")
    
    # Provide environmental constraints if any were passed down
    lines.append("### CONTEXT")
    lines.append(job_data.get("context", "General web context."))
    lines.append("")
    
    # Inject the actual instructions for what must be coded
    lines.append("### INSTRUCTIONS")
    lines.append(job_data.get("instructions", "Write concise code."))
    lines.append("")
    
    # Reiterate constraint formats to force good output formatting
    lines.append("### CONSTRAINTS")
    lines.append("1. Provide all technical output in markdown FENCED CODE BLOCKS.")
    lines.append("2. DO NOT provide unnecessary pleasantries.")
    
    # Ensure any specialized constraints are passed through
    for constraint in job_data.get("constraints", []):
        lines.append(f"- {constraint}")
        
    # Compile the array of strings into a single solid block
    return "\n".join(lines)

def init_run(job_id: str) -> str:
    """
    Generates a scratch directory for the actively executing job.
    This directory isolates the execution state cleanly.
    """
    # Determine the strict pathway in the runs/ folder subsystem
    run_dir = os.path.join(RUNS_DIR, job_id)
    
    # Safely create the folder tree, ignoring if it already exists
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def promote_job_to_run(job_id: str) -> str:
    src = os.path.join(INBOX_DIR, job_id)
    dst = os.path.join(RUNS_DIR, job_id)

    if os.path.exists(dst):
        shutil.rmtree(dst)

    shutil.move(src, dst)
    return dst


def find_pending_run_jobs():
    jobs = []

    if not os.path.exists(RUNS_DIR):
        return []

    for item in os.listdir(RUNS_DIR):
        run_path = os.path.join(RUNS_DIR, item)
        if not os.path.isdir(run_path):
            continue

        if not os.path.exists(os.path.join(run_path, "job.json")):
            continue

        if os.path.exists(os.path.join(run_path, "response.txt")):
            continue

        jobs.append(item)

    return sorted(jobs)


def write_receipt(job_id: str, run_dir: str, source: str = "auralis"):
    payload = {
        "job_id": job_id,
        "received_at": utc_now_iso(),
        "status": "received",
        "source": source,
    }
    write_json_atomic(os.path.join(run_dir, "receipt.json"), payload)


def update_receipt_status(run_dir: str, status: str):
    receipt_path = os.path.join(run_dir, "receipt.json")
    payload = {}

    if os.path.exists(receipt_path):
        with open(receipt_path, "r", encoding="utf-8") as handle:
            try:
                payload = json.load(handle)
            except json.JSONDecodeError:
                payload = {}

    payload["status"] = status
    payload["updated_at"] = utc_now_iso()
    write_json_atomic(receipt_path, payload)


def reject_job(job_id: str, reasons: list[str]):
    src = os.path.join(INBOX_DIR, job_id)
    dst = os.path.join(FAILED_DIR, job_id)

    if os.path.exists(dst):
        shutil.rmtree(dst)

    shutil.move(src, dst)
    rejection = {
        "job_id": job_id,
        "rejected_at": utc_now_iso(),
        "reasons": reasons,
        "missing_fields": reasons,
    }
    write_json_atomic(os.path.join(dst, "rejection.json"), rejection)

def archive_job(job_id: str):
    """
    Moves a successfully processed job from the inbox to the archive.
    This cleans up the queue and prevents redundant executions.
    """
    # Define source and destination path coordinates
    src = os.path.join(INBOX_DIR, job_id)
    if not os.path.exists(src):
        src = os.path.join(RUNS_DIR, job_id)
    if not os.path.exists(src):
        return False
    dst = os.path.join(ARCHIVE_DIR, job_id)
    
    # If a previous run shares this ID, clobber it to force freshness
    if os.path.exists(dst):
        shutil.rmtree(dst)
        
    # Physically move the folder tree across the filesystem
    shutil.move(src, dst)
    return True

def fail_job(job_id: str):
    """
    Moves a fundamentally broken job into the failure queue.
    This enables post-mortem analysis without blocking the main worker.
    """
    # Define source and destination path coordinates for failures
    src = os.path.join(INBOX_DIR, job_id)
    if not os.path.exists(src):
        src = os.path.join(RUNS_DIR, job_id)
    if not os.path.exists(src):
        return False
    dst = os.path.join(FAILED_DIR, job_id)
    
    # If the fail box already contains this, wipe it out first
    if os.path.exists(dst):
        shutil.rmtree(dst)
        
    # Execute the folder relocation atomically
    shutil.move(src, dst)
    return True

def write_handoff(job_id: str, run_dir: str):
    """
    Signals to the broader system that Krax has finished generating.
    In phase 2, this will trigger the PostalService routing mechanism.
    """
    # Ensure the outbox pipeline folder is primed
    os.makedirs(OUTBOX_DIR, exist_ok=True)
    
    # Write a flat text marker so Auralis/Vera can proceed 
    handoff_path = os.path.join(OUTBOX_DIR, f"{job_id}_handoff.md")
    with open(handoff_path, "w") as f:
        f.write(f"# Krax Job {job_id} Handoff\n")
        f.write(f"Run Directory: {run_dir}\n")
        f.write("Status: Passed to Vera for testing.\n")
