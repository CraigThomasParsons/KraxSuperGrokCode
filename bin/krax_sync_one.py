#!/usr/bin/env python3
"""
krax_sync_one.py — Single-project sync runner for cron invocation.

Processes exactly ONE Bridgit package from the inbox per run, then exits.
Designed to be called every 3 hours by krax-sync.sh via cron. At one package
per run, a backlog of N packages clears in N * 3 hours — this keeps each
invocation fast and failures isolated to a single package.

Flow:
  1. Initialize GrokApiClient (triggers browser_cookie3 bootstrap if needed)
  2. Hot-reload config to pick up latest cookie from Chrome Extension
  3. Health check the Grok API — exit early if cookie is expired
  4. Scan inbox for Bridgit packages (skip Auralis jobs and unknowns)
  5. Pick the oldest package (FIFO by directory name sort order)
  6. Read artifacts, extract project name, run Stage 1
  7. Archive on success, move to failed/ on error
"""

import os
import sys

# Ensure bin/ and project root are on sys.path so lib imports resolve.
# This is necessary because cron runs with a minimal environment that
# doesn't inherit the PYTHONPATH from interactive shells.
script_directory = os.path.dirname(os.path.abspath(__file__))
if script_directory not in sys.path:
    sys.path.insert(0, script_directory)

project_root = os.path.dirname(script_directory)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from lib import fs
from lib.grok_api_client import GrokApiClient
from lib.inbox_classifier import classify_package, BRIDGIT_PACKAGE
from lib.artifact_reader import read_artifacts_from_directory
from lib.stage_runner import execute_stage_one


def find_oldest_bridgit_package() -> str:
    """
    Scan the inbox for Bridgit packages and return the oldest one.

    "Oldest" is determined by sorted directory name order, which matches
    the behavior of fs.find_jobs(). This gives us FIFO processing — the
    package that's been waiting longest gets handled first.

    Returns the directory name (not full path) of the oldest package,
    or an empty string if no Bridgit packages are waiting.
    """
    # Get all inbox entries sorted alphabetically (same as find_jobs).
    all_inbox_entries = fs.find_jobs()

    # Filter to only Bridgit packages — skip Auralis jobs and unknowns.
    for entry_name in all_inbox_entries:
        entry_full_path = os.path.join(fs.INBOX_DIR, entry_name)
        package_type = classify_package(entry_full_path)
        if package_type == BRIDGIT_PACKAGE:
            return entry_name

    return ""


def sync_one_package() -> bool:
    """
    Main sync logic: pick one package, run Stage 1, archive or fail.

    Returns True if a package was successfully processed, False if there
    was nothing to do or an error occurred.
    """
    # Step 1: Initialize the Grok API client. If no cookie is configured,
    # the constructor will attempt a browser_cookie3 bootstrap from Chrome's
    # on-disk cookie database.
    print("[krax-sync] Initializing GrokApiClient...")
    grok_client = GrokApiClient()

    # Step 2: Hot-reload config.yaml to pick up the latest cookie pushed
    # by the Chrome Extension's automatic 1-minute refresh cycle.
    config_changed = grok_client.reload_config()
    if config_changed:
        print("[krax-sync] Config reloaded — cookie was updated since last run.")

    # Step 3: Health check — verify the Grok API is reachable before
    # committing to any package processing. A stale cookie is the most
    # common failure mode and should be reported clearly.
    if not grok_client.is_configured():
        print("[krax-sync] ERROR: No Grok session cookie configured.")
        print("[krax-sync] Ensure the Chrome Extension is running or install browser_cookie3.")
        return False

    print("[krax-sync] Running health check against Grok API...")
    api_is_healthy = grok_client.health_check()
    if not api_is_healthy:
        print("[krax-sync] ERROR: Grok API health check failed — cookie may be expired.")
        print("[krax-sync] The Chrome Extension should refresh it automatically when Chrome is open.")
        return False

    print("[krax-sync] Grok API is healthy.")

    # Step 4: Find the oldest Bridgit package waiting in the inbox.
    package_name = find_oldest_bridgit_package()
    if not package_name:
        print("[krax-sync] No Bridgit packages in inbox. Nothing to do.")
        return False

    inbox_path = os.path.join(fs.INBOX_DIR, package_name)
    print(f"[krax-sync] Processing package: {package_name}")

    # Step 5: Read the artifact bundle from the inbox package directory.
    try:
        artifact_bundle = read_artifacts_from_directory(inbox_path)
    except Exception as read_error:
        print(f"[krax-sync] ERROR reading artifacts from {package_name}: {read_error}")
        fs.fail_job(package_name)
        return False

    # Validate the bundle — VISION.md is the minimum required artifact.
    if not artifact_bundle.is_valid():
        print(f"[krax-sync] Invalid package (missing VISION.md): {package_name}")
        fs.write_json_atomic(
            os.path.join(inbox_path, "sync_failure.json"),
            {"error": "missing_vision_md", "failed_at": fs.utc_now_iso()},
        )
        fs.fail_job(package_name)
        return False

    # Step 6: Determine the project name from letter.toml or VISION.md heading.
    project_name = artifact_bundle.get_project_name()
    if not project_name:
        print(f"[krax-sync] Cannot determine project name for: {package_name}")
        fs.write_json_atomic(
            os.path.join(inbox_path, "sync_failure.json"),
            {"error": "no_project_name", "failed_at": fs.utc_now_iso()},
        )
        fs.fail_job(package_name)
        return False

    print(f"[krax-sync] Project name: {project_name}")

    # Step 7: Run Stage 1 — ensure Grok project exists and set Instructions.
    try:
        stage_one_result = execute_stage_one(
            grok_client=grok_client,
            artifact_bundle=artifact_bundle,
            project_name=project_name,
        )

        action_taken = stage_one_result.get("action_taken", "unknown")
        grok_project_id = stage_one_result.get("grok_project_id", "unknown")
        print(f"[krax-sync] Stage 1 complete: {action_taken} project '{project_name}' (id: {grok_project_id})")

        # Write the sync result into the package before archiving.
        sync_result = {
            "package": package_name,
            "project_name": project_name,
            "stage_1": stage_one_result,
            "stage_2": "pending_api_discovery",
            "completed_at": fs.utc_now_iso(),
        }
        fs.write_json_atomic(os.path.join(inbox_path, "sync_result.json"), sync_result)

        # Archive the successfully processed package.
        fs.archive_job(package_name)
        print(f"[krax-sync] Archived: {package_name}")
        return True

    except RuntimeError as api_error:
        # RuntimeError from stage_runner means the Grok API call failed.
        print(f"[krax-sync] API error for {package_name}: {api_error}")
        fs.write_json_atomic(
            os.path.join(inbox_path, "sync_failure.json"),
            {"error": str(api_error), "failed_at": fs.utc_now_iso()},
        )
        fs.fail_job(package_name)
        return False

    except Exception as unexpected_error:
        # Catch-all for unexpected failures to prevent orphaned packages.
        print(f"[krax-sync] Unexpected error for {package_name}: {unexpected_error}")
        fs.write_json_atomic(
            os.path.join(inbox_path, "sync_failure.json"),
            {"error": str(unexpected_error), "failed_at": fs.utc_now_iso()},
        )
        fs.fail_job(package_name)
        return False


if __name__ == "__main__":
    print(f"[krax-sync] Starting single-project sync at {fs.utc_now_iso()}")
    success = sync_one_package()
    exit_code = 0 if success else 1
    print(f"[krax-sync] Finished (success={success})")
    sys.exit(exit_code)
