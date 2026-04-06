"""
inbox_classifier.py — Classifies inbox packages by their content type.

The Krax inbox can receive two types of packages:
1. Auralis jobs (contain job.json) — dispatched to the Chrome Extension pipeline
2. Bridgit packages (contain letter.toml + artifacts) — dispatched to Stage 1/2

This module inspects the contents of each inbox directory and returns a
classification string that the poll_inbox() loop uses for routing.
"""

import os

# Classification constants used by poll_inbox() for routing decisions.
AURALIS_JOB = "auralis_job"
BRIDGIT_PACKAGE = "bridgit_package"
UNKNOWN_PACKAGE = "unknown"


def classify_package(inbox_directory: str) -> str:
    """
    Inspect an inbox directory and determine its package type.

    Returns one of:
    - "auralis_job": contains job.json (existing Auralis code-generation path)
    - "bridgit_package": contains letter.toml + at least VISION.md
    - "unknown": does not match any known pattern (will be rejected)
    """
    if not os.path.isdir(inbox_directory):
        return UNKNOWN_PACKAGE

    # Check for Auralis job format first — this is the existing primary path.
    job_json_path = os.path.join(inbox_directory, "job.json")
    if os.path.isfile(job_json_path):
        return AURALIS_JOB

    # Check for Bridgit artifact package — letter.toml is the routing envelope.
    letter_toml_path = os.path.join(inbox_directory, "letter.toml")
    vision_md_path = os.path.join(inbox_directory, "VISION.md")

    has_letter = os.path.isfile(letter_toml_path)
    has_vision = os.path.isfile(vision_md_path)

    # A valid Bridgit package must have letter.toml AND at least VISION.md.
    # letter.toml alone could be a corrupted package; VISION.md alone could
    # be a stray file — requiring both prevents false positives.
    if has_letter and has_vision:
        return BRIDGIT_PACKAGE

    # If only letter.toml exists but no VISION.md, this is likely a
    # corrupted or incomplete Bridgit package.
    if has_letter and not has_vision:
        return UNKNOWN_PACKAGE

    return UNKNOWN_PACKAGE
