"""Phase 1 step D unit tests."""

from __future__ import annotations

import pytest

from app.core.llm_client import InvalidJSONError, extract_json
from app.models.curriculum import PageStatus
from app.services.ingestion_checks import (
    check_printed_consistency,
    choose_escalation,
    outcome_quality,
    printed_page_offset,
    should_escalate,
    should_process,
)
from app.services.validation import major_code_required, validate_major_code


# --- JSON fence extraction ---


def test_extract_json_fenced_block():
    assert extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}


def test_extract_json_plain_object():
    assert extract_json('{"b": "x"}') == {"b": "x"}


def test_extract_json_outermost_braces_with_surrounding_text():
    assert extract_json('prefix {"c": 2} suffix') == {"c": 2}


def test_extract_json_braces_inside_strings():
    assert extract_json('{"markdown": "a { b } c", "n": 1}')["n"] == 1


def test_extract_json_returns_dict_only():
    with pytest.raises(InvalidJSONError):
        extract_json("[1, 2, 3]")


def test_extract_json_invalid_raises():
    with pytest.raises(InvalidJSONError):
        extract_json("this is definitely not json")


def test_extract_json_empty_raises():
    with pytest.raises(InvalidJSONError):
        extract_json("")


# --- printed page consistency ---


def test_printed_consistent_adjacent():
    assert check_printed_consistency(5, 6) is None


def test_printed_gap_warns():
    assert check_printed_consistency(5, 7) is not None


def test_printed_previous_missing_ok():
    assert check_printed_consistency(None, 5) is None


def test_printed_current_missing_ok():
    assert check_printed_consistency(5, None) is None


def test_printed_both_missing_ok():
    assert check_printed_consistency(None, None) is None


# --- major_code validation ---


def test_major_required_for_grade_10_plus():
    assert major_code_required(True) is True


def test_major_not_required_below_10():
    assert major_code_required(False) is False


def test_major_missing_is_error_for_10_plus():
    assert validate_major_code(True, None) is not None


def test_major_present_ok_for_10_plus():
    assert validate_major_code(True, "math_physics") is None


def test_major_missing_ok_below_10():
    assert validate_major_code(False, None) is None


# --- resume / skipping logic ---


def test_skip_done_without_force():
    assert should_process(PageStatus.done, False, force=False, only_failed=False, overwrite_human=False) is False


def test_process_failed_by_default():
    assert should_process(PageStatus.failed, False, force=False, only_failed=False, overwrite_human=False) is True


def test_only_failed_skips_done_and_missing():
    assert should_process(PageStatus.done, False, force=False, only_failed=True, overwrite_human=False) is False
    assert should_process(None, False, force=False, only_failed=True, overwrite_human=False) is False


def test_only_failed_processes_failed():
    assert should_process(PageStatus.failed, False, force=False, only_failed=True, overwrite_human=False) is True


def test_force_processes_done():
    assert should_process(PageStatus.done, False, force=True, only_failed=False, overwrite_human=False) is True


def test_human_edited_protected_even_with_force():
    assert should_process(PageStatus.done, True, force=True, only_failed=False, overwrite_human=False) is False


def test_human_edited_overwritten_only_with_flag():
    assert should_process(PageStatus.done, True, force=True, only_failed=False, overwrite_human=True) is True


def test_pending_page_is_processed():
    assert should_process(PageStatus.pending, False, force=False, only_failed=False, overwrite_human=False) is True


# --- escalation selection ---


def _outcome(status, *, extraction=True, warnings=None):
    return {
        "status": status,
        "extraction": object() if extraction else None,
        "warnings": warnings or [],
        "usage": None,
        "latency": 0.0,
    }


def test_should_escalate_on_needs_review():
    assert should_escalate(PageStatus.needs_review, [], False) is True


def test_should_escalate_on_failed():
    assert should_escalate(PageStatus.failed, [], False) is True


def test_should_not_escalate_done_without_figures():
    assert should_escalate(PageStatus.done, [], False) is False


def test_should_escalate_done_with_figures_when_enabled():
    assert should_escalate(PageStatus.done, [{"label": "x"}], True) is True


def test_should_not_escalate_done_with_figures_when_disabled():
    assert should_escalate(PageStatus.done, [{"label": "x"}], False) is False


def test_escalation_kept_when_strictly_better():
    primary = _outcome(PageStatus.needs_review, warnings=["w"])
    escalation = _outcome(PageStatus.done)
    use, chosen = choose_escalation(primary, escalation)
    assert use is True
    assert chosen is escalation


def test_escalation_rejected_when_primary_is_better():
    primary = _outcome(PageStatus.done)
    escalation = _outcome(PageStatus.needs_review, warnings=["w"])
    use, chosen = choose_escalation(primary, escalation)
    assert use is False
    assert chosen is primary


def test_escalation_rejected_when_invalid_extraction():
    primary = _outcome(PageStatus.needs_review, warnings=["w"])
    escalation = _outcome(PageStatus.done, extraction=False)
    use, chosen = choose_escalation(primary, escalation)
    assert use is False
    assert chosen is primary


def test_escalation_rejected_when_equal_quality():
    primary = _outcome(PageStatus.needs_review, warnings=["a"])
    escalation = _outcome(PageStatus.needs_review, warnings=["b"])
    use, chosen = choose_escalation(primary, escalation)
    assert use is False
    assert chosen is primary


def test_outcome_quality_orders_statuses():
    assert outcome_quality(_outcome(PageStatus.done)) < outcome_quality(
        _outcome(PageStatus.needs_review)
    )
    assert outcome_quality(_outcome(PageStatus.needs_review)) < outcome_quality(
        _outcome(PageStatus.failed)
    )


# --- printed page offset ---


def test_printed_offset_mode():
    offset, deviations = printed_page_offset([(1, 1), (2, 2), (3, 3)])
    assert offset == 0
    assert deviations == []


def test_printed_offset_nonzero():
    offset, deviations = printed_page_offset([(2, 1), (3, 2), (4, 3)])
    assert offset == 1
    assert deviations == []


def test_printed_offset_flags_deviation():
    offset, deviations = printed_page_offset([(1, 1), (2, 2), (3, 9)])
    assert offset == 0
    assert len(deviations) == 1
    assert deviations[0]["pdf_page_index"] == 3


def test_printed_offset_without_printed_numbers():
    offset, deviations = printed_page_offset([(1, None), (2, None)])
    assert offset is None
    assert deviations == []
