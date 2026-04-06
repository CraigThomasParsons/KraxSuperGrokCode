"""
artifact_reader.py — Reads Bridgit artifact packages from inbox or docs directories.

When the ChatProjectsToKraxBridge deposits a package into Krax's inbox via
ThePostalService, it contains structured markdown artifacts (VISION.md, PERSONAS.md,
etc.) plus a letter.toml with routing metadata. This module reads those files into
a typed ArtifactBundle for Stage 1/2 consumption.

Also supports reading from a repo's docs/architecture/ directory for local
development and manual testing.
"""

import os
from typing import Dict, List, Optional

# The five canonical artifact files that Bridgit projects into repos.
# Listed in the deterministic upload order used by Stage 2.
CANONICAL_ARTIFACTS = [
    "VISION.md",
    "PERSONAS.md",
    "EPICS.md",
    "STORIES.md",
    "CONSTRAINTS.md",
]

# Minimum required files for a valid package — VISION is the non-negotiable
# anchor that all other artifacts reference.
REQUIRED_ARTIFACTS = ["VISION.md"]

# When reading from a repo's docs/architecture/ directory, Bridgit writes
# lowercase filenames. This mapping allows the reader to find them.
LOWERCASE_ARTIFACT_MAP = {
    "vision.md": "VISION.md",
    "personas.md": "PERSONAS.md",
    "epics.md": "EPICS.md",
    "stories.md": "STORIES.md",
    "constraints.md": "CONSTRAINTS.md",
}


class ArtifactBundle:
    """
    Holds the contents of a Bridgit artifact package.

    Attributes:
        artifacts: dict mapping canonical filename (e.g., "VISION.md") to its
                   string content. Only files that exist are included.
        found_files: list of canonical filenames that were successfully read.
        missing_files: list of canonical filenames that were expected but absent.
        letter_metadata: dict parsed from letter.toml, or empty if not present.
        source_directory: the directory the artifacts were read from.
    """

    def __init__(self):
        self.artifacts: Dict[str, str] = {}
        self.found_files: List[str] = []
        self.missing_files: List[str] = []
        self.letter_metadata: Dict[str, str] = {}
        self.source_directory: str = ""

    def is_valid(self) -> bool:
        """Check whether the bundle has the minimum required artifacts."""
        for required_file in REQUIRED_ARTIFACTS:
            if required_file not in self.artifacts:
                return False
        return True

    def get_project_name(self) -> Optional[str]:
        """
        Extract a project name from the bundle metadata or VISION.md content.

        Priority order:
        1. letter.toml 'project_name' field
        2. First heading line from VISION.md
        3. None if neither is available
        """
        # Check letter.toml metadata first — most explicit source.
        letter_project_name = self.letter_metadata.get("project_name", "").strip()
        if letter_project_name:
            return letter_project_name

        # Fall back to extracting the first heading from VISION.md.
        vision_content = self.artifacts.get("VISION.md", "")
        for line in vision_content.splitlines():
            stripped_line = line.strip()
            if stripped_line.startswith("#"):
                # Remove markdown heading markers and return the text.
                heading_text = stripped_line.lstrip("#").strip()
                if heading_text:
                    return heading_text

        return None


def read_artifacts_from_directory(directory_path: str) -> ArtifactBundle:
    """
    Read Bridgit artifacts from an inbox package directory.

    Expects uppercase filenames (VISION.md, PERSONAS.md, etc.) as deposited
    by the ChatProjectsToKraxBridge. Also reads letter.toml if present.
    """
    bundle = ArtifactBundle()
    bundle.source_directory = directory_path

    # Read letter.toml metadata if it exists in the package directory.
    letter_path = os.path.join(directory_path, "letter.toml")
    if os.path.isfile(letter_path):
        bundle.letter_metadata = _parse_simple_toml(letter_path)

    # Scan for each canonical artifact file.
    for artifact_filename in CANONICAL_ARTIFACTS:
        artifact_path = os.path.join(directory_path, artifact_filename)

        if os.path.isfile(artifact_path):
            content = _read_file_safe(artifact_path)
            if content is not None:
                bundle.artifacts[artifact_filename] = content
                bundle.found_files.append(artifact_filename)
            else:
                bundle.missing_files.append(artifact_filename)
        else:
            bundle.missing_files.append(artifact_filename)

    return bundle


def read_artifacts_from_docs(repo_docs_path: str) -> ArtifactBundle:
    """
    Read Bridgit-projected artifacts from a repo's docs/architecture/ directory.

    Bridgit writes lowercase filenames (vision.md, personas.md, etc.) when
    projecting into repos. This function maps them back to canonical uppercase
    names for Stage 2 consumption.
    """
    bundle = ArtifactBundle()
    bundle.source_directory = repo_docs_path

    # The architecture subdirectory where Bridgit projects most artifacts.
    architecture_dir = os.path.join(repo_docs_path, "architecture")
    search_directories = [architecture_dir, repo_docs_path]

    # Scan for lowercase variants and map them to canonical names.
    for artifact_filename in CANONICAL_ARTIFACTS:
        lowercase_name = artifact_filename.lower()
        found = False

        for search_dir in search_directories:
            candidate_path = os.path.join(search_dir, lowercase_name)
            if os.path.isfile(candidate_path):
                content = _read_file_safe(candidate_path)
                if content is not None:
                    bundle.artifacts[artifact_filename] = content
                    bundle.found_files.append(artifact_filename)
                    found = True
                    break

        if not found:
            bundle.missing_files.append(artifact_filename)

    return bundle


def _parse_simple_toml(toml_path: str) -> Dict[str, str]:
    """
    Parse a simple flat TOML file into a string-to-string dictionary.

    Only handles top-level key = "value" pairs — no nested tables, arrays,
    or complex types. This is sufficient for letter.toml files which only
    contain routing metadata (recipient, project_id, stage).
    """
    parsed_values: Dict[str, str] = {}

    try:
        with open(toml_path, "r", encoding="utf-8") as toml_file:
            for raw_line in toml_file:
                line = raw_line.strip()

                # Skip comments and empty lines.
                if not line or line.startswith("#"):
                    continue

                # Split on first '=' to get key-value pair.
                if "=" not in line:
                    continue

                key_part, value_part = line.split("=", 1)
                clean_key = key_part.strip()
                clean_value = value_part.strip().strip('"').strip("'")
                parsed_values[clean_key] = clean_value

    except (OSError, IOError):
        pass

    return parsed_values


def _read_file_safe(file_path: str) -> Optional[str]:
    """
    Read a text file and return its content, or None on any I/O error.

    Gracefully handles encoding issues by falling back to latin-1.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as file_handle:
            return file_handle.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="latin-1") as file_handle:
                return file_handle.read()
        except (OSError, IOError):
            return None
    except (OSError, IOError):
        return None
