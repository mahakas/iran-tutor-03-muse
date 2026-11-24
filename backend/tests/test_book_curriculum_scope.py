"""Tests for exact branch, field and general textbook applicability links."""

from __future__ import annotations

from types import SimpleNamespace

from app.api.admin import (
    _book_curriculum_scope_rows,
    _branch_wide_applicability_codes,
)


def test_field_only_upload_does_not_grant_whole_branch_applicability():
    branch_codes = _branch_wide_applicability_codes(
        applicable_branch_codes=[],
        branch_code=None,
        selected_field_codes=["math_physics"],
    )
    branch = SimpleNamespace(id=1, code="theoretical")
    field = SimpleNamespace(id=11, branch_id=1, code="math_physics")

    rows = _book_curriculum_scope_rows(
        grade_number=12,
        is_general_book=False,
        subject_id=3,
        branch_wide_branches=[branch] if branch.code in branch_codes else [],
        selected_fields=[field],
    )

    assert rows == [(1, 11, 3, "field:math_physics")]
    assert not any(scope_code.startswith("branch:") for *_ids, scope_code in rows)


def test_branch_only_upload_creates_branch_wide_link():
    branch_codes = _branch_wide_applicability_codes(
        applicable_branch_codes=[],
        branch_code="technical_vocational",
        selected_field_codes=[],
    )
    branch = SimpleNamespace(id=2, code="technical_vocational")

    rows = _book_curriculum_scope_rows(
        grade_number=10,
        is_general_book=False,
        subject_id=4,
        branch_wide_branches=[branch] if branch.code in branch_codes else [],
        selected_fields=[],
    )

    assert rows == [(2, None, 4, "branch:technical_vocational")]


def test_explicit_branch_wide_grant_can_coexist_with_field_specific_links():
    branch_codes = _branch_wide_applicability_codes(
        applicable_branch_codes=["theoretical"],
        branch_code=None,
        selected_field_codes=["math_physics"],
    )
    branch = SimpleNamespace(id=1, code="theoretical")
    field = SimpleNamespace(id=11, branch_id=1, code="math_physics")

    rows = _book_curriculum_scope_rows(
        grade_number=12,
        is_general_book=False,
        subject_id=3,
        branch_wide_branches=[branch] if branch.code in branch_codes else [],
        selected_fields=[field],
    )

    assert rows == [
        (1, None, 3, "branch:theoretical"),
        (1, 11, 3, "field:math_physics"),
    ]


def test_general_book_is_a_separate_explicit_global_scope():
    branch_codes = _branch_wide_applicability_codes(
        applicable_branch_codes=[],
        branch_code=None,
        selected_field_codes=["math_physics"],
    )
    branch = SimpleNamespace(id=1, code="theoretical")
    field = SimpleNamespace(id=11, branch_id=1, code="math_physics")

    rows = _book_curriculum_scope_rows(
        grade_number=12,
        is_general_book=True,
        subject_id=None,
        branch_wide_branches=[branch] if branch.code in branch_codes else [],
        selected_fields=[field],
    )

    assert rows == [
        (None, None, None, "general"),
        (1, 11, None, "field:math_physics"),
    ]
