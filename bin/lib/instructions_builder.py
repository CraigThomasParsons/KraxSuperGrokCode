"""
instructions_builder.py — Assembles Grok project Instructions from user preferences + artifacts.

Grok Code Projects have an Instructions field (up to 12,000 chars) that acts as
a per-project system prompt injected into every conversation. This module builds
that Instructions string by layering:

1. Fixed user preferences from templates/instructions_base.md
2. Project-specific context auto-derived from Bridgit artifacts (VISION.md, etc.)

The output is ready to be set via GrokApiClient.set_instructions().
"""

import os
from typing import Optional

# Grok's hard limit for the Instructions field.
MAX_INSTRUCTIONS_LENGTH = 12000

# Character budgets for each artifact section to ensure we stay under the limit.
# Base preferences get priority, then vision, constraints, personas.
VISION_CHAR_BUDGET = 2000
CONSTRAINTS_CHAR_BUDGET = 1500
PERSONAS_CHAR_BUDGET = 500

# Locate the templates directory relative to this module's position in bin/lib/.
TEMPLATES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "templates"))
BASE_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "instructions_base.md")


def build(artifact_bundle) -> str:
    """
    Assemble a complete Instructions string from base preferences + Bridgit artifacts.

    Args:
        artifact_bundle: An ArtifactBundle instance from artifact_reader.py.
                         Must have an 'artifacts' dict keyed by canonical filenames.

    Returns:
        A string ready to be set as Grok project Instructions, capped at 12,000 chars.
    """
    sections = []

    # Layer 1: Fixed user preferences from the base template.
    base_template_content = _load_base_template()
    if base_template_content:
        sections.append(base_template_content)

    # Layer 2: Project-specific context derived from Bridgit artifacts.
    vision_section = _build_vision_section(artifact_bundle)
    if vision_section:
        sections.append(vision_section)

    constraints_section = _build_constraints_section(artifact_bundle)
    if constraints_section:
        sections.append(constraints_section)

    personas_section = _build_personas_section(artifact_bundle)
    if personas_section:
        sections.append(personas_section)

    # Join all sections with double newlines for readability.
    combined_instructions = "\n\n".join(sections)

    # Apply smart truncation if we exceed the Grok limit.
    if len(combined_instructions) > MAX_INSTRUCTIONS_LENGTH:
        combined_instructions = _truncate_smart(combined_instructions)

    return combined_instructions


def _load_base_template() -> Optional[str]:
    """
    Read the fixed preferences template from templates/instructions_base.md.

    Returns None if the template file doesn't exist, allowing the builder
    to still produce Instructions from artifacts alone.
    """
    if not os.path.isfile(BASE_TEMPLATE_PATH):
        return None

    try:
        with open(BASE_TEMPLATE_PATH, "r", encoding="utf-8") as template_file:
            return template_file.read().strip()
    except (OSError, IOError):
        return None


def _build_vision_section(artifact_bundle) -> Optional[str]:
    """
    Extract project purpose from VISION.md and format as an Instructions section.

    Truncates to VISION_CHAR_BUDGET to leave room for other sections.
    """
    vision_content = artifact_bundle.artifacts.get("VISION.md", "")
    if not vision_content.strip():
        return None

    # Take the first N characters of the vision document.
    trimmed_vision = vision_content.strip()[:VISION_CHAR_BUDGET]

    # If we truncated mid-line, cut back to the last complete line.
    if len(vision_content.strip()) > VISION_CHAR_BUDGET:
        last_newline_position = trimmed_vision.rfind("\n")
        if last_newline_position > 0:
            trimmed_vision = trimmed_vision[:last_newline_position]
        trimmed_vision += "\n\n*(truncated for brevity)*"

    return f"## Project Purpose\n\n{trimmed_vision}"


def _build_constraints_section(artifact_bundle) -> Optional[str]:
    """
    Extract technical constraints from CONSTRAINTS.md and format as Instructions section.
    """
    constraints_content = artifact_bundle.artifacts.get("CONSTRAINTS.md", "")
    if not constraints_content.strip():
        return None

    trimmed_constraints = constraints_content.strip()[:CONSTRAINTS_CHAR_BUDGET]

    if len(constraints_content.strip()) > CONSTRAINTS_CHAR_BUDGET:
        last_newline_position = trimmed_constraints.rfind("\n")
        if last_newline_position > 0:
            trimmed_constraints = trimmed_constraints[:last_newline_position]
        trimmed_constraints += "\n\n*(truncated for brevity)*"

    return f"## Technical Constraints\n\n{trimmed_constraints}"


def _build_personas_section(artifact_bundle) -> Optional[str]:
    """
    Extract target user summary from PERSONAS.md and format as Instructions section.
    """
    personas_content = artifact_bundle.artifacts.get("PERSONAS.md", "")
    if not personas_content.strip():
        return None

    trimmed_personas = personas_content.strip()[:PERSONAS_CHAR_BUDGET]

    if len(personas_content.strip()) > PERSONAS_CHAR_BUDGET:
        last_newline_position = trimmed_personas.rfind("\n")
        if last_newline_position > 0:
            trimmed_personas = trimmed_personas[:last_newline_position]
        trimmed_personas += "\n\n*(truncated for brevity)*"

    return f"## Target Users\n\n{trimmed_personas}"


def _truncate_smart(instructions_text: str) -> str:
    """
    Truncate the combined instructions to fit within Grok's 12,000 char limit.

    Strategy: cut from the end (personas first, then constraints, then vision)
    while preserving the base template in full. Falls back to a hard cut at
    the character limit if section-level truncation isn't enough.
    """
    if len(instructions_text) <= MAX_INSTRUCTIONS_LENGTH:
        return instructions_text

    # Hard cutoff as a last resort — find the last complete line before the limit.
    truncated_text = instructions_text[:MAX_INSTRUCTIONS_LENGTH]
    last_newline_position = truncated_text.rfind("\n")
    if last_newline_position > 0:
        truncated_text = truncated_text[:last_newline_position]

    return truncated_text + "\n\n*(Instructions truncated to fit 12,000 character limit)*"
