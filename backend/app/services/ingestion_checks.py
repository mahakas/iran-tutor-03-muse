"""Pure ingestion checks and decisions (unit-testable, no I/O)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

_STATUS_RANK = {"done": 0, "needs_review": 1, "failed": 2}


def _status_value(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def check_printed_consistency(prev_printed: int | None, current_printed: int | None) -> str | None:
    """Return a warning string when page numbers do not increase by 1."""
    if (
        prev_printed is not None
        and current_printed is not None
        and current_printed != prev_printed + 1
    ):
        return (
            f"printed_page_number {current_printed} inconsistent with neighbor "
            f"{prev_printed} (expected {prev_printed + 1})"
        )
    return None


def should_process(
    prev_status: Any,
    edited_human: bool,
    *,
    force: bool,
    only_failed: bool,
    overwrite_human: bool,
) -> bool:
    """Decide whether a page needs to be (re)processed.

    Human-edited pages are protected: ``--force`` never overwrites them unless
    ``overwrite_human`` is explicitly set.
    """
    if edited_human and not overwrite_human:
        return False
    if force:
        return True
    if only_failed:
        return prev_status is not None and _status_value(prev_status) == "failed"
    return prev_status is None or _status_value(prev_status) != "done"


def should_escalate(status: Any, visual_elements: list, escalate_figures: bool) -> bool:
    """Return True when the page should be re-processed by the escalation model."""
    value = _status_value(status)
    if value in ("needs_review", "failed"):
        return True
    if escalate_figures and visual_elements:
        return True
    return False


def outcome_quality(outcome: dict[str, Any]) -> tuple[int, int]:
    """Rank an extraction outcome; lower is better.

    Status rank first (done < needs_review < failed), then warning count.
    Outcomes without a parsed extraction are always the worst.
    """
    value = _status_value(outcome.get("status", "failed"))
    rank = _STATUS_RANK.get(value, 3)
    if outcome.get("extraction") is None:
        rank = max(rank, 3)
    return (rank, len(outcome.get("warnings") or []))


def choose_escalation(
    primary_outcome: dict[str, Any], escalation_outcome: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    """Keep the escalation result only when it is strictly better.

    Returns ``(use_escalation, chosen_outcome)``. If the escalated result is
    missing a valid extraction (JSON validation failure) or is not better than
    the primary result, the primary result is kept.
    """
    if escalation_outcome.get("extraction") is None:
        return (False, primary_outcome)
    if outcome_quality(escalation_outcome) < outcome_quality(primary_outcome):
        return (True, escalation_outcome)
    return (False, primary_outcome)


def printed_page_offset(
    entries: Iterable[tuple[int, int]],
) -> tuple[int | None, list[dict[str, Any]]]:
    """Compute the most common ``pdf_index - printed_page`` offset.

    Returns ``(offset, deviations)`` where each deviation contains the page
    index, printed page number and its own offset.
    """
    pairs = [(idx, printed) for idx, printed in entries if printed is not None]
    if not pairs:
        return (None, [])
    offsets = [idx - printed for idx, printed in pairs]
    counts = Counter(offsets)
    mode_offset, _ = counts.most_common(1)[0]
    deviations = [
        {
            "pdf_page_index": idx,
            "printed_page_number": printed,
            "offset": idx - printed,
            "message": (
                f"pdf index {idx} and printed page {printed} imply offset {idx - printed}, "
                f"expected {mode_offset}"
            ),
        }
        for idx, printed in pairs
        if idx - printed != mode_offset
    ]
    return (mode_offset, deviations)
