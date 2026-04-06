"""
Tests for the instructions_builder module.

Verifies that project Instructions are correctly assembled from the base
template and artifact bundle content, with proper section formatting and
character limit enforcement.
"""

import os
import pytest

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bin")))

from lib.instructions_builder import build, MAX_INSTRUCTIONS_LENGTH
from lib.artifact_reader import ArtifactBundle


class TestBuildInstructions:
    """Tests for the build() function."""

    def test_includes_base_template(self):
        """The output should include content from templates/instructions_base.md."""
        bundle = ArtifactBundle()
        bundle.artifacts["VISION.md"] = "# Test Project\n\nA test vision."

        result = build(bundle)

        # The base template contains this section header.
        assert "Coding Standards" in result

    def test_includes_vision_section(self):
        """VISION.md content should appear under a '## Project Purpose' heading."""
        bundle = ArtifactBundle()
        bundle.artifacts["VISION.md"] = "# Test Vision\n\nThis project tests the builder."

        result = build(bundle)

        assert "## Project Purpose" in result
        assert "tests the builder" in result

    def test_includes_constraints_section(self):
        """CONSTRAINTS.md content should appear under '## Technical Constraints'."""
        bundle = ArtifactBundle()
        bundle.artifacts["VISION.md"] = "# Vision\n\nBase vision."
        bundle.artifacts["CONSTRAINTS.md"] = "# Constraints\n\nMust use Python 3.10+."

        result = build(bundle)

        assert "## Technical Constraints" in result
        assert "Python 3.10+" in result

    def test_includes_personas_section(self):
        """PERSONAS.md content should appear under '## Target Users'."""
        bundle = ArtifactBundle()
        bundle.artifacts["VISION.md"] = "# Vision\n\nBase vision."
        bundle.artifacts["PERSONAS.md"] = "# Personas\n\nDevelopers who write Go and Python."

        result = build(bundle)

        assert "## Target Users" in result
        assert "Go and Python" in result

    def test_omits_missing_artifacts(self):
        """Sections for missing artifacts should not appear in the output."""
        bundle = ArtifactBundle()
        bundle.artifacts["VISION.md"] = "# Vision\n\nJust vision, nothing else."

        result = build(bundle)

        assert "## Project Purpose" in result
        assert "## Technical Constraints" not in result
        assert "## Target Users" not in result

    def test_output_respects_character_limit(self):
        """Output must never exceed Grok's 12,000 character limit."""
        bundle = ArtifactBundle()
        # Generate oversized content for each artifact.
        bundle.artifacts["VISION.md"] = "# Vision\n\n" + ("A" * 5000)
        bundle.artifacts["CONSTRAINTS.md"] = "# Constraints\n\n" + ("B" * 5000)
        bundle.artifacts["PERSONAS.md"] = "# Personas\n\n" + ("C" * 5000)

        result = build(bundle)

        assert len(result) <= MAX_INSTRUCTIONS_LENGTH

    def test_empty_bundle_still_includes_base_template(self):
        """Even with no artifacts, the base template should still be present."""
        bundle = ArtifactBundle()

        result = build(bundle)

        # Should still contain base template content if the file exists.
        # If the template is missing, result could be empty — but since we
        # just verified it exists, check for its content.
        assert len(result) > 0

    def test_priority_order_preserves_base_and_vision(self):
        """When truncation happens, base template and vision should be preserved."""
        bundle = ArtifactBundle()
        bundle.artifacts["VISION.md"] = "# Vision\n\nCritical project purpose text."
        bundle.artifacts["CONSTRAINTS.md"] = "# Constraints\n\n" + ("X" * 10000)
        bundle.artifacts["PERSONAS.md"] = "# Personas\n\n" + ("Y" * 10000)

        result = build(bundle)

        # Vision should always survive since it has higher priority.
        assert "Critical project purpose text" in result
        assert len(result) <= MAX_INSTRUCTIONS_LENGTH
