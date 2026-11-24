"""Pure validation helpers (unit-testable)."""

from __future__ import annotations


def validate_major_code(has_major: bool, major_code: str | None) -> str | None:
    """Return an error message if ``major_code`` is required but missing."""
    if has_major and not major_code:
        return "major_code is required for grades 10-12"
    return None


def major_code_required(has_major: bool) -> bool:
    """Grades 10-12 (``has_major``) require a major code."""
    return has_major
