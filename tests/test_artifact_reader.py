"""
Tests for the artifact_reader module.

Verifies ArtifactBundle creation, validation, project name extraction,
and reading from both inbox directories and repo docs/ directories.
"""

import os
import pytest

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin")))

from lib.artifact_reader import (
    ArtifactBundle,
    read_artifacts_from_directory,
    read_artifacts_from_docs,
    CANONICAL_ARTIFACTS,
    REQUIRED_ARTIFACTS,
)


class TestArtifactBundle:
    """Tests for the ArtifactBundle data class."""

    def test_empty_bundle_is_invalid(self):
        """An empty bundle should fail validation — VISION.md is required."""
        bundle = ArtifactBundle()
        assert not bundle.is_valid()

    def test_bundle_with_vision_is_valid(self):
        """A bundle containing at least VISION.md passes validation."""
        bundle = ArtifactBundle()
        bundle.artifacts["VISION.md"] = "# My Project\n\nSome vision content."
        assert bundle.is_valid()

    def test_get_project_name_from_letter_metadata(self):
        """Project name from letter.toml metadata takes priority over VISION.md heading."""
        bundle = ArtifactBundle()
        bundle.letter_metadata = {"project_name": "LetterName"}
        bundle.artifacts["VISION.md"] = "# VisionHeading\n\nContent."

        assert bundle.get_project_name() == "LetterName"

    def test_get_project_name_from_vision_heading(self):
        """Falls back to the first heading in VISION.md when letter has no project_name."""
        bundle = ArtifactBundle()
        bundle.artifacts["VISION.md"] = "# My Amazing Project\n\nDescription text."

        assert bundle.get_project_name() == "My Amazing Project"

    def test_get_project_name_handles_subheading(self):
        """Should extract text from ## headings as well as # headings."""
        bundle = ArtifactBundle()
        bundle.artifacts["VISION.md"] = "## SubHeadingProject\n\nBody."

        assert bundle.get_project_name() == "SubHeadingProject"

    def test_get_project_name_returns_none_when_empty(self):
        """Returns None when neither letter metadata nor vision heading is available."""
        bundle = ArtifactBundle()
        assert bundle.get_project_name() is None


class TestReadArtifactsFromDirectory:
    """Tests for reading Bridgit packages from inbox directories."""

    def test_reads_all_canonical_artifacts(self, tmp_path):
        """All five canonical artifact files should be read into the bundle."""
        for artifact_name in CANONICAL_ARTIFACTS:
            (tmp_path / artifact_name).write_text(f"# {artifact_name}\n\nContent for {artifact_name}.")

        bundle = read_artifacts_from_directory(str(tmp_path))

        assert bundle.is_valid()
        assert len(bundle.found_files) == 5
        assert len(bundle.missing_files) == 0
        for artifact_name in CANONICAL_ARTIFACTS:
            assert artifact_name in bundle.artifacts

    def test_reads_letter_toml_metadata(self, tmp_path):
        """letter.toml should be parsed into bundle.letter_metadata."""
        (tmp_path / "VISION.md").write_text("# Test Project")
        (tmp_path / "letter.toml").write_text('recipient = "krax"\nproject_name = "TestProject"\nstage = "1"')

        bundle = read_artifacts_from_directory(str(tmp_path))

        assert bundle.letter_metadata.get("recipient") == "krax"
        assert bundle.letter_metadata.get("project_name") == "TestProject"
        assert bundle.letter_metadata.get("stage") == "1"

    def test_handles_partial_package(self, tmp_path):
        """A package with only VISION.md is still valid — other files are optional."""
        (tmp_path / "VISION.md").write_text("# Partial Project\n\nOnly vision exists.")

        bundle = read_artifacts_from_directory(str(tmp_path))

        assert bundle.is_valid()
        assert "VISION.md" in bundle.found_files
        assert "PERSONAS.md" in bundle.missing_files

    def test_tracks_source_directory(self, tmp_path):
        """The bundle should record which directory it was read from."""
        (tmp_path / "VISION.md").write_text("# Test")

        bundle = read_artifacts_from_directory(str(tmp_path))
        assert bundle.source_directory == str(tmp_path)

    def test_empty_directory_is_invalid(self, tmp_path):
        """An empty directory produces an invalid bundle."""
        bundle = read_artifacts_from_directory(str(tmp_path))

        assert not bundle.is_valid()
        assert len(bundle.found_files) == 0
        assert len(bundle.missing_files) == 5


class TestReadArtifactsFromDocs:
    """Tests for reading Bridgit-projected artifacts from repo docs/ directories."""

    def test_reads_lowercase_files_from_architecture_subdir(self, tmp_path):
        """Bridgit writes lowercase filenames to docs/architecture/ — reader should map them."""
        arch_dir = tmp_path / "architecture"
        arch_dir.mkdir()
        (arch_dir / "vision.md").write_text("# Lowercase Vision")
        (arch_dir / "personas.md").write_text("# Lowercase Personas")

        bundle = read_artifacts_from_docs(str(tmp_path))

        assert "VISION.md" in bundle.artifacts
        assert "PERSONAS.md" in bundle.artifacts
        assert bundle.is_valid()

    def test_falls_back_to_parent_docs_directory(self, tmp_path):
        """If architecture/ doesn't have the file, check the docs/ root."""
        (tmp_path / "vision.md").write_text("# Root Vision")

        bundle = read_artifacts_from_docs(str(tmp_path))

        assert "VISION.md" in bundle.artifacts
        assert bundle.is_valid()
