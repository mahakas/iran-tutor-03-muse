"""Curriculum endpoints enforce grade/major selection rules."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.curriculum import list_books
from app.api.dependencies import resolve_book_scope
from app.models.curriculum import BookStatus, Book, EducationBranch, FieldOfStudy, Grade, BookCurriculumLink
from app.services.curriculum_access import is_student_visible_book


class FakeSession:
    def __init__(self, grade, major=None, books=(), scalar_values=None):
        self.grade = grade
        self.major = major
        self.books = list(books)
        self.scalar_calls = 0
        self.scalar_values = list(scalar_values or [])

    async def scalar(self, statement):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return self.grade
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return self.major

    async def scalars(self, statement):
        return SimpleNamespace(all=lambda: self.books)


@pytest.mark.asyncio
async def test_list_books_for_high_school_requires_and_scopes_major():
    grade = SimpleNamespace(id=12, number=12, has_major=True)
    major = SimpleNamespace(id=2, code="math_physics")
    book = SimpleNamespace(
        id=5,
        title="فیزیک ۳",
        status=BookStatus.ready,
    )
    theoretical = SimpleNamespace(id=1, code="theoretical", min_grade=10, max_grade=12, is_active=True)
    field = SimpleNamespace(id=2, code="math_physics", branch_id=1, is_active=True)
    session = FakeSession(grade, scalar_values=[major, theoretical, 2, field], books=[book])

    response = await list_books(
        12,
        "math_physics",
        session,
        branch_code=None,
        field_code=None,
        academic_year_code=None,
    )

    assert response == [
        {
            "id": 5,
            "title": "فیزیک ۳",
            "grade_number": 12,
            "major_code": "math_physics",
            "status": "ready",
        }
    ]


@pytest.mark.asyncio
async def test_list_books_rejects_high_school_without_major():
    grade = SimpleNamespace(id=12, number=12, has_major=True)
    session = FakeSession(grade)

    with pytest.raises(HTTPException) as error:
        await list_books(
            12,
            None,
            session,
            branch_code=None,
            field_code=None,
            academic_year_code=None,
        )

    assert error.value.status_code == 422
    assert session.scalar_calls == 1



@pytest.mark.asyncio
async def test_list_books_for_technical_branch_uses_branch_scope():
    grade = SimpleNamespace(id=10, number=10, has_major=True)
    branch = SimpleNamespace(
        id=2,
        code="technical_vocational",
        min_grade=10,
        max_grade=12,
        is_active=True,
    )
    book = SimpleNamespace(id=21, title="نقشه‌کشی فنی", status=BookStatus.ready)
    session = FakeSession(grade, scalar_values=[branch], books=[book])

    response = await list_books(
        10,
        None,
        session,
        branch_code="technical_vocational",
        field_code=None,
        academic_year_code=None,
    )

    assert response[0]["id"] == 21
    assert response[0]["branch_code"] == "technical_vocational"
    assert response[0]["field_code"] is None


@pytest.mark.asyncio
async def test_resolve_book_scope_accepts_approved_technical_branch_book():
    book = SimpleNamespace(
        id=41,
        grade_id=10,
        major_id=None,
        status=BookStatus.ready,
        catalog_status="approved",
    )
    grade = SimpleNamespace(id=10, number=10, has_major=True)
    branch = SimpleNamespace(id=3, code="technical_vocational", min_grade=10, max_grade=12, is_active=True)
    session = FakeSession(
        grade,
        scalar_values=[branch, None, 501],  # no fields on branch, matching applicability link
    )
    # resolve_book_scope loads the grade via get(), so its first scalar is the branch.
    async def fake_scalar(statement):
        return session.scalar_values.pop(0) if session.scalar_values else None

    session.scalar = fake_scalar

    async def fake_get(model, identifier):
        return {Book: book, Grade: grade}.get(model)

    session.get = fake_get

    resolved_book, resolved_grade, resolved_field = await resolve_book_scope(
        session,
        book_id=41,
        grade_number=10,
        major_code=None,
        branch_code="technical_vocational",
    )

    assert resolved_book is book
    assert resolved_grade is grade
    assert resolved_field is None


@pytest.mark.asyncio
async def test_resolve_book_scope_rejects_field_from_another_branch():
    book = SimpleNamespace(
        id=42,
        grade_id=12,
        major_id=None,
        status=BookStatus.ready,
        catalog_status="approved",
    )
    grade = SimpleNamespace(id=12, number=12, has_major=True)
    branch = SimpleNamespace(id=3, code="technical_vocational", min_grade=10, max_grade=12, is_active=True)
    field = SimpleNamespace(id=9, code="math_physics", branch_id=1, is_active=True)
    session = FakeSession(grade, scalar_values=[branch, field])

    async def fake_scalar(statement):
        return session.scalar_values.pop(0) if session.scalar_values else None

    session.scalar = fake_scalar

    async def fake_get(model, identifier):
        return {Book: book, Grade: grade}.get(model)

    session.get = fake_get

    with pytest.raises(HTTPException) as error:
        await resolve_book_scope(
            session,
            book_id=42,
            grade_number=12,
            major_code="math_physics",
            branch_code="technical_vocational",
        )

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_resolve_book_scope_allows_ready_book_without_manual_approval():
    """Auto-publish hotfix: catalog_status no longer gates book resolution."""
    book = SimpleNamespace(
        id=43,
        grade_id=12,
        major_id=None,
        status=BookStatus.ready,
        catalog_status="pending_review",
    )
    grade_row = SimpleNamespace(id=12, number=12, has_major=True)
    branch = SimpleNamespace(id=3, code="technical_vocational", min_grade=10, max_grade=12, is_active=True)
    session = FakeSession(
        grade_row,
        scalar_values=[branch, None, 501],  # no fields on branch, matching applicability link
    )

    async def fake_scalar(statement):
        return session.scalar_values.pop(0) if session.scalar_values else None

    session.scalar = fake_scalar

    async def fake_get(model, identifier):
        if model is Book:
            return book
        if model is Grade:
            return grade_row
        return None

    session.get = fake_get

    resolved_book, resolved_grade, resolved_field = await resolve_book_scope(
        session,
        book_id=43,
        grade_number=12,
        major_code=None,
        branch_code="technical_vocational",
    )
    assert resolved_book is book and resolved_grade.number == 12

from app.services.mastery_service import _evidence_progress


def test_learning_evidence_is_not_mastery_until_verified():
    row = SimpleNamespace(
        observed_at=None,
        verification_status="unverified",
        qualitative_level="advanced",
        rubric_json={"overall_level": "advanced"},
        score=None,
        source_type="performance_task",
        feedback="student submitted",
        id=1,
        reviewed_at=None,
    )

    progress = _evidence_progress(
        [row],
        assessment_profile="performance",
        threshold=70,
    )

    assert progress["status"] == "submitted_for_review"
    assert progress["score"] is None


def test_verified_performance_evidence_can_mark_mastery():
    row = SimpleNamespace(
        observed_at=None,
        verification_status="verified",
        qualitative_level="advanced",
        rubric_json={"overall_level": "advanced"},
        score=None,
        source_type="performance_task",
        feedback="teacher verified",
        id=2,
        reviewed_at=None,
    )

    progress = _evidence_progress(
        [row],
        assessment_profile="performance",
        threshold=70,
    )

    assert progress["status"] == "mastered"
    assert progress["qualitative_level"] == "advanced"



def test_ready_book_is_visible_regardless_of_legacy_catalog_status():
    """Auto-publish hotfix: only processing status gates student visibility."""
    for legacy in ("legacy_unverified", "pending_review", "approved", "demo"):
        book = SimpleNamespace(status=BookStatus.ready, catalog_status=legacy)
        assert is_student_visible_book(book)


def test_non_ready_book_is_not_visible():
    for status in (BookStatus.created, BookStatus.ingesting, BookStatus.failed):
        book = SimpleNamespace(status=status, catalog_status="approved")
        assert not is_student_visible_book(book)
    assert not is_student_visible_book(None)


@pytest.mark.asyncio
async def test_list_books_normalizes_major_code_when_branch_is_also_supplied():
    grade = SimpleNamespace(id=10, number=10, has_major=True)
    branch = SimpleNamespace(
        id=3,
        code="technical_vocational",
        min_grade=10,
        max_grade=12,
        is_active=True,
    )
    field = SimpleNamespace(id=9, code="electronics", branch_id=3, is_active=True)
    book = SimpleNamespace(id=60, title="الکترونیک", status=BookStatus.ready)
    session = FakeSession(grade, scalar_values=[branch, field.id, field, None], books=[book])

    response = await list_books(
        10,
        "electronics",
        session,
        branch_code="technical_vocational",
        field_code=None,
        academic_year_code=None,
    )

    assert response[0]["id"] == 60
    assert response[0]["branch_code"] == "technical_vocational"
    assert response[0]["field_code"] == "electronics"


@pytest.mark.asyncio
async def test_list_books_requires_field_for_any_branch_that_has_active_fields():
    grade = SimpleNamespace(id=10, number=10, has_major=True)
    branch = SimpleNamespace(
        id=3,
        code="technical_vocational",
        min_grade=10,
        max_grade=12,
        is_active=True,
    )
    session = FakeSession(grade, scalar_values=[branch, 9])

    with pytest.raises(HTTPException) as error:
        await list_books(
            10,
            None,
            session,
            branch_code="technical_vocational",
            field_code=None,
            academic_year_code=None,
        )

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_resolve_book_scope_does_not_let_legacy_major_override_conflicting_links():
    from app.models.curriculum import Major

    book = SimpleNamespace(
        id=70,
        grade_id=12,
        major_id=5,
        status=BookStatus.ready,
        catalog_status="approved",
    )
    grade = SimpleNamespace(id=12, number=12, has_major=True)
    major = SimpleNamespace(id=5, code="math_physics")
    branch = SimpleNamespace(id=3, code="theoretical", min_grade=10, max_grade=12, is_active=True)
    field = SimpleNamespace(id=8, code="math_physics", branch_id=3, is_active=True)
    session = FakeSession(
        grade,
        scalar_values=[branch, field.id, field, None, 999],
    )

    async def fake_get(model, identifier):
        return {Book: book, Grade: grade, Major: major}.get(model)

    async def fake_scalar(statement):
        return session.scalar_values.pop(0) if session.scalar_values else None

    session.get = fake_get
    session.scalar = fake_scalar

    with pytest.raises(HTTPException) as error:
        await resolve_book_scope(
            session,
            book_id=70,
            grade_number=12,
            major_code="math_physics",
            branch_code="theoretical",
        )

    assert error.value.status_code == 422
