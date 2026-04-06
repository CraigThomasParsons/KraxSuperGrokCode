"""
Tests for the inbox_classifier module.

Verifies that the classifier correctly identifies Auralis jobs, Bridgit packages,
and unknown/invalid inbox entries based on their file contents.
"""

import os
import tempfile
import pytest

# The classifier lives in bin/lib/ — add the parent to sys.path for imports.
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin")))

from lib.inbox_classifier import classify_package, AURALIS_JOB, BRIDGIT_PACKAGE, UNKNOWN_PACKAGE


class TestClassifyPackage:
    """Tests for classify_package() routing decisions."""

    def test_auralis_job_detected_when_job_json_present(self, tmp_path):
        """Directories containing job.json should be classified as Auralis jobs."""
        job_json_path = tmp_path / "job.json"
        job_json_path.write_text('{"action": "create_project", "name": "TestJob"}')

        result = classify_package(str(tmp_path))
        assert result == AURALIS_JOB

    def test_bridgit_package_detected_when_letter_and_vision_present(self, tmp_path):
        """Directories with both letter.toml and VISION.md are Bridgit packages."""
        (tmp_path / "letter.toml").write_text('recipient = "krax"\nproject_name = "MyProject"')
        (tmp_path / "VISION.md").write_text("# My Project\n\nA test project for unit tests.")

        result = classify_package(str(tmp_path))
        assert result == BRIDGIT_PACKAGE

    def test_bridgit_package_with_all_artifacts(self, tmp_path):
        """A full Bridgit package with all 5 artifacts should still classify as bridgit_package."""
        (tmp_path / "letter.toml").write_text('recipient = "krax"')
        (tmp_path / "VISION.md").write_text("# Vision")
        (tmp_path / "PERSONAS.md").write_text("# Personas")
        (tmp_path / "EPICS.md").write_text("# Epics")
        (tmp_path / "STORIES.md").write_text("# Stories")
        (tmp_path / "CONSTRAINTS.md").write_text("# Constraints")

        result = classify_package(str(tmp_path))
        assert result == BRIDGIT_PACKAGE

    def test_auralis_takes_priority_over_bridgit(self, tmp_path):
        """If both job.json and letter.toml exist, Auralis classification wins."""
        (tmp_path / "job.json").write_text('{"action": "test"}')
        (tmp_path / "letter.toml").write_text('recipient = "krax"')
        (tmp_path / "VISION.md").write_text("# Vision")

        result = classify_package(str(tmp_path))
        assert result == AURALIS_JOB

    def test_letter_toml_alone_is_unknown(self, tmp_path):
        """letter.toml without VISION.md is classified as unknown (incomplete package)."""
        (tmp_path / "letter.toml").write_text('recipient = "krax"')

        result = classify_package(str(tmp_path))
        assert result == UNKNOWN_PACKAGE

    def test_vision_md_alone_is_unknown(self, tmp_path):
        """VISION.md without letter.toml is classified as unknown (stray file)."""
        (tmp_path / "VISION.md").write_text("# Vision")

        result = classify_package(str(tmp_path))
        assert result == UNKNOWN_PACKAGE

    def test_empty_directory_is_unknown(self, tmp_path):
        """An empty inbox directory should be classified as unknown."""
        result = classify_package(str(tmp_path))
        assert result == UNKNOWN_PACKAGE

    def test_nonexistent_directory_is_unknown(self):
        """A path that doesn't exist at all should be classified as unknown."""
        result = classify_package("/nonexistent/fake/path/abc123")
        assert result == UNKNOWN_PACKAGE
