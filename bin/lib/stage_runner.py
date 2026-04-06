"""
stage_runner.py — Orchestrates Krax Stage 1 (Project CRUD + Instructions) and Stage 2 (Source Upload).

Stage 1: Ensure a Grok Code Project exists for the given artifact bundle,
         then set its Instructions from the bundle's content + user preferences.

Stage 2: Upload all artifact files as Grok project Sources.
         (Blocked on C1 API discovery — source upload methods not yet implemented.)

This module is the bridge between the inbox poller (krax_server.py) and the
Grok API client. It handles the high-level workflow while delegating API calls
to GrokApiClient and artifact reading to artifact_reader.
"""

import os
import json
from typing import Dict, Any, Optional

from lib.grok_api_client import GrokApiClient
from lib import instructions_builder
from lib.fs import write_json_atomic, utc_now_iso


def execute_stage_one(
    grok_client: GrokApiClient,
    artifact_bundle,
    project_name: str,
    output_directory: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Stage 1: Ensure a Grok project exists and set its Instructions.

    Steps:
    1. Verify Grok API connectivity (health check)
    2. Search for an existing project by name
    3. Create the project if it doesn't exist
    4. Build and set project Instructions from artifacts + user preferences
    5. Write grok_project.json with the result metadata

    Args:
        grok_client: An initialized GrokApiClient instance.
        artifact_bundle: An ArtifactBundle from artifact_reader.
        project_name: The name to use for the Grok project.
        output_directory: Optional directory to write grok_project.json into.
                          Defaults to the artifact bundle's source directory.

    Returns:
        A dict with keys: grok_project_id, project_name, action_taken, instructions_set.

    Raises:
        RuntimeError: If the Grok API is unreachable or the session cookie is expired.
        ValueError: If the artifact bundle is invalid or project name is empty.
    """
    # Validate inputs before making any API calls.
    if not project_name or not project_name.strip():
        raise ValueError("project_name cannot be empty for Stage 1 execution.")

    if not artifact_bundle.is_valid():
        raise ValueError("ArtifactBundle is missing required artifacts (at minimum VISION.md).")

    # Step 1: Health check — fail fast with a clear message if the cookie is stale.
    print(f"[StageRunner] Starting Stage 1 for project '{project_name}'...")
    api_is_healthy = grok_client.health_check()
    if not api_is_healthy:
        raise RuntimeError(
            "Grok API health check failed — the session cookie may be expired. "
            "Update grok_session_cookie in config.yaml and retry."
        )

    # Step 2: Check if the project already exists to prevent duplicates.
    print(f"[StageRunner] Checking for existing project '{project_name}'...")
    existing_project = grok_client.find_project_by_name(project_name)

    grok_project_id = None
    action_taken = ""

    if existing_project is not None:
        # Project found — reuse it instead of creating a duplicate.
        grok_project_id = existing_project.get("workspaceId", "")
        action_taken = "found"
        print(f"[StageRunner] Found existing project: {grok_project_id}")
    else:
        # Step 3: Create the project since it doesn't exist yet.
        # Build instructions early so we can include them at creation time.
        print(f"[StageRunner] No existing project found. Creating '{project_name}'...")
        instructions_text = instructions_builder.build(artifact_bundle)
        creation_response = grok_client.create_project(project_name, instructions_text)

        # Grok's workspace API uses "workspaceId" as the identifier.
        grok_project_id = creation_response.get("workspaceId", "")
        action_taken = "created"
        print(f"[StageRunner] Created project: {grok_project_id}")

    # Step 4: Build Instructions from artifacts + base template.
    # For new projects, instructions were already set at creation time,
    # but we always update to ensure the latest artifact content is applied.
    # For existing projects, this is the first time instructions are pushed.
    if action_taken != "created":
        instructions_text = instructions_builder.build(artifact_bundle)
    instructions_were_set = False

    if instructions_text.strip() and grok_project_id:
        if action_taken == "created":
            # Instructions were already included in the creation payload,
            # so we just record success without making an extra API call.
            instructions_were_set = True
            print(f"[StageRunner] Instructions set at creation ({len(instructions_text)} chars)")
        else:
            try:
                # Push updated Instructions to an existing project.
                grok_client.update_instructions(grok_project_id, instructions_text)
                instructions_were_set = True
                print(f"[StageRunner] Instructions updated ({len(instructions_text)} chars)")
            except Exception as instructions_error:
                # Non-fatal: log the error but don't fail the whole stage.
                print(f"[StageRunner] WARNING: Failed to set Instructions: {instructions_error}")

    # Step 5: Write the result artifact to disk.
    result_payload = {
        "grok_project_id": grok_project_id,
        "project_name": project_name,
        "action_taken": action_taken,
        "instructions_set": instructions_were_set,
        "instructions_length": len(instructions_text),
        "completed_at": utc_now_iso(),
    }

    # Determine where to write the result file.
    target_directory = output_directory or artifact_bundle.source_directory
    if target_directory and os.path.isdir(target_directory):
        result_path = os.path.join(target_directory, "grok_project.json")
        write_json_atomic(result_path, result_payload)
        print(f"[StageRunner] Wrote result to {result_path}")

    return result_payload

    return ""
