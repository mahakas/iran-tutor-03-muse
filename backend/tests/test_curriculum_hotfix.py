"""Regression tests for curriculum-scoped mastery and evidence validation."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.auth import User  # noqa: F401 - register referenced auth tables
from app.models.curriculum import (
    AcademicYear,
    Book,
    BookCurriculumLink,
    BookPage,
    BookStatus,
    CurriculumUnit,
    EducationBranch,
    FieldOfStudy,
    Grade,
    LearningEvidence,
    LearningObjective,
    ObjectivePrerequisite,
    PageStatus,
    Subject,
)
from app.models.phase5 import MasteryBookSettings, MasteryChapterProgress  # noqa: F401
from app.services import mastery_service


@pytest.fixture
async def curriculum_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _create_curriculum(session: AsyncSession):
    grade = Grade(number=10, title="دهم", has_major=True)
    branch = EducationBranch(
        code="theoretical",
        title="نظری",
        min_grade=10,
        max_grade=12,
        is_active=True,
    )
    year = AcademicYear(code="1405", title="۱۴۰۵–۱۴۰۶", is_active=True)
    subject = Subject(code="physics", title="فیزیک", is_active=True)
    session.add_all([grade, branch, year, subject])
    await session.flush()
    field = FieldOfStudy(
        branch_id=branch.id,
        code="math_physics",
        title="ریاضی‌فیزیک",
        is_active=True,
    )
    session.add(field)
    await session.flush()

    book = Book(
        title="فیزیک دهم",
        grade_id=grade.id,
        academic_year_id=year.id,
        edition_label="چاپ ۱۴۰۵",
        print_year=1405,
        status=BookStatus.ready,
        catalog_status="approved",
        pdf_file_path="/tmp/physics.pdf",
        total_pdf_pages=10,
    )
    session.add(book)
    await session.flush()
    session.add(
        BookCurriculumLink(
            book_id=book.id,
            branch_id=branch.id,
            field_of_study_id=field.id,
            subject_id=subject.id,
            scope_code="field:math_physics:physics",
        )
    )
    await session.flush()
    return grade, branch, field, year, subject, book


@pytest.mark.asyncio
async def test_objective_tree_handles_prerequisites_and_scoped_units(curriculum_session):
    session = curriculum_session
    grade, branch, field, year, subject, book = await _create_curriculum(session)
    unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=subject.id,
        branch_id=branch.id,
        field_of_study_id=field.id,
        academic_year_id=year.id,
        scope_code=year.code,
        code="unit-1",
        title="حرکت",
    )
    session.add(unit)
    await session.flush()
    first = LearningObjective(
        unit_id=unit.id,
        code="physics.motion.basic",
        title="شناخت حرکت",
        assessment_profile="written",
    )
    second = LearningObjective(
        unit_id=unit.id,
        code="physics.motion.velocity",
        title="شناخت سرعت",
        assessment_profile="written",
    )
    other_branch = EducationBranch(
        code="technical_vocational",
        title="فنی‌وحرفه‌ای",
        min_grade=10,
        max_grade=12,
        is_active=True,
    )
    session.add(other_branch)
    await session.flush()
    other_field = FieldOfStudy(
        branch_id=other_branch.id,
        code="electronics",
        title="الکترونیک",
        is_active=True,
    )
    session.add(other_field)
    await session.flush()
    other_unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=subject.id,
        branch_id=other_branch.id,
        field_of_study_id=other_field.id,
        academic_year_id=year.id,
        scope_code=year.code,
        code="unit-other-branch",
        title="واحد خارج از شاخه",
    )
    session.add(other_unit)
    await session.flush()
    other_objective = LearningObjective(
        unit_id=other_unit.id,
        code="physics.electronics.basic",
        title="هدف خارج از شاخهٔ کتاب",
        assessment_profile="written",
    )
    session.add_all([first, second, other_objective])
    await session.flush()
    session.add(
        ObjectivePrerequisite(
            objective_id=second.id,
            prerequisite_id=first.id,
        )
    )
    await session.commit()

    result = await mastery_service.objective_tree(
        session,
        user_id="student-1",
        book_id=book.id,
    )

    by_code = {item["code"]: item for item in result["objectives"]}
    assert set(by_code) == {"physics.motion.basic", "physics.motion.velocity"}
    assert "physics.electronics.basic" not in by_code
    assert by_code["physics.motion.basic"]["status"] == "not_started"
    assert by_code["physics.motion.velocity"]["status"] == "locked"
    assert by_code["physics.motion.velocity"]["prerequisites"][0]["code"] == "physics.motion.basic"


@pytest.mark.asyncio
async def test_ready_book_is_exposed_by_chapter_mastery_tree_without_approval(curriculum_session):
    """Auto-publish hotfix: a ready book (even with legacy catalog_status) is usable."""
    session = curriculum_session
    grade = Grade(number=5, title="پنجم", has_major=False)
    session.add(grade)
    await session.flush()
    book = Book(
        title="کتاب تأییدنشده",
        grade_id=grade.id,
        status=BookStatus.ready,
        catalog_status="legacy_unverified",
        pdf_file_path="/tmp/unverified.pdf",
        total_pdf_pages=1,
    )
    session.add(book)
    await session.commit()

    tree = await mastery_service.book_tree(session, user_id="student-1", book_id=book.id)
    assert tree["book"]["id"] == book.id


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["subject", "branch_field", "academic_year"])
async def test_evidence_rejects_objectives_outside_selected_book_scope(
    curriculum_session,
    mismatch: str,
):
    session = curriculum_session
    grade, branch, field, year, subject, book = await _create_curriculum(session)

    unit_subject = subject
    unit_branch = branch
    unit_field = field
    unit_year = year
    unit_scope = year.code

    if mismatch == "subject":
        unit_subject = Subject(code="chemistry", title="شیمی", is_active=True)
        session.add(unit_subject)
        await session.flush()
    elif mismatch == "branch_field":
        unit_branch = EducationBranch(
            code="technical_vocational",
            title="فنی‌وحرفه‌ای",
            min_grade=10,
            max_grade=12,
            is_active=True,
        )
        session.add(unit_branch)
        await session.flush()
        unit_field = FieldOfStudy(
            branch_id=unit_branch.id,
            code="electronics",
            title="الکترونیک",
            is_active=True,
        )
        session.add(unit_field)
        await session.flush()
    else:
        unit_year = AcademicYear(code="1404", title="۱۴۰۴–۱۴۰۵", is_active=False)
        session.add(unit_year)
        await session.flush()
        unit_scope = unit_year.code

    unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=unit_subject.id,
        branch_id=unit_branch.id,
        field_of_study_id=unit_field.id,
        academic_year_id=unit_year.id,
        scope_code=unit_scope,
        code=f"unit-{mismatch}",
        title="واحد ناسازگار",
    )
    session.add(unit)
    await session.flush()
    objective = LearningObjective(
        unit_id=unit.id,
        code=f"objective.{mismatch}",
        title="هدف ناسازگار",
        assessment_profile="written",
    )
    session.add(objective)
    await session.commit()

    with pytest.raises(HTTPException) as error:
        await mastery_service.record_objective_evidence(
            session,
            user_id="student-1",
            objective_id=objective.id,
            source_type="self_assessment",
            source_ref=f"test-{mismatch}",
            score=80,
            qualitative_level=None,
            rubric={},
            feedback=None,
            book_id=book.id,
        )

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_evidence_with_page_rejects_objective_not_mapped_to_that_page(curriculum_session):
    session = curriculum_session
    grade, branch, field, year, subject, book = await _create_curriculum(session)
    unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=subject.id,
        branch_id=branch.id,
        field_of_study_id=field.id,
        academic_year_id=year.id,
        scope_code=year.code,
        code="unit-page-map",
        title="صفحه‌نگاری",
    )
    session.add(unit)
    await session.flush()
    objective = LearningObjective(
        unit_id=unit.id,
        code="objective.page-map",
        title="هدف خارج از صفحه",
        assessment_profile="written",
    )
    page = BookPage(
        book_id=book.id,
        pdf_page_index=1,
        printed_page_number=10,
        markdown_content="متن آزمایشی",
        page_image_path="/tmp/page.png",
        status=PageStatus.done,
    )
    other_objective = LearningObjective(
        unit_id=unit.id,
        code="objective.other",
        title="هدف دیگر",
        assessment_profile="written",
    )
    session.add_all([objective, other_objective, page])
    await session.flush()
    from app.models.curriculum import BookPageObjective

    session.add(
        BookPageObjective(
            book_page_id=page.id,
            objective_id=other_objective.id,
            relevance=100,
        )
    )
    await session.commit()

    with pytest.raises(HTTPException) as error:
        await mastery_service.record_objective_evidence(
            session,
            user_id="student-1",
            objective_id=objective.id,
            source_type="reading",
            source_ref="page-1",
            score=70,
            qualitative_level=None,
            rubric={},
            feedback=None,
            book_id=book.id,
            pdf_page_index=1,
        )

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_objective_tree_does_not_widen_to_another_subject_page_mapping(curriculum_session):
    session = curriculum_session
    grade, branch, field, year, physics, book = await _create_curriculum(session)
    chemistry = Subject(code="chemistry", title="شیمی", is_active=True)
    session.add(chemistry)
    await session.flush()

    physics_unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=physics.id,
        branch_id=branch.id,
        field_of_study_id=field.id,
        academic_year_id=year.id,
        scope_code=year.code,
        code="physics-unit-scope",
        title="فیزیک",
    )
    chemistry_unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=chemistry.id,
        branch_id=branch.id,
        field_of_study_id=field.id,
        academic_year_id=year.id,
        scope_code=year.code,
        code="chemistry-unit-scope",
        title="شیمی",
    )
    session.add_all([physics_unit, chemistry_unit])
    await session.flush()
    physics_objective = LearningObjective(
        unit_id=physics_unit.id,
        code="physics.scope.objective",
        title="هدف فیزیک",
        assessment_profile="written",
    )
    chemistry_objective = LearningObjective(
        unit_id=chemistry_unit.id,
        code="chemistry.scope.objective",
        title="هدف شیمی",
        assessment_profile="written",
    )
    page = BookPage(
        book_id=book.id,
        pdf_page_index=1,
        printed_page_number=1,
        markdown_content="متن فیزیک",
        page_image_path="/tmp/physics-scope.png",
        status=PageStatus.done,
    )
    session.add_all([physics_objective, chemistry_objective, page])
    await session.flush()
    from app.models.curriculum import BookPageObjective

    # Deliberately attach a different-subject objective to this book's page.
    session.add(
        BookPageObjective(
            book_page_id=page.id,
            objective_id=chemistry_objective.id,
            relevance=100,
        )
    )
    await session.commit()

    result = await mastery_service.objective_tree(
        session,
        user_id="student-scope",
        book_id=book.id,
    )

    codes = {item["code"] for item in result["objectives"]}
    assert "physics.scope.objective" in codes
    assert "chemistry.scope.objective" not in codes


@pytest.mark.asyncio
async def test_objective_tree_does_not_reuse_evidence_from_another_book_edition(curriculum_session):
    session = curriculum_session
    grade, branch, field, year, subject, book = await _create_curriculum(session)
    user = User(phone_number="09120000002", role="student", is_active=True)
    session.add(user)
    await session.flush()

    unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=subject.id,
        branch_id=branch.id,
        field_of_study_id=field.id,
        academic_year_id=year.id,
        scope_code=year.code,
        code="edition-evidence-unit",
        title="واحد نسخه‌دار",
    )
    session.add(unit)
    await session.flush()
    objective = LearningObjective(
        unit_id=unit.id,
        code="physics.edition.evidence",
        title="هدف نسخه‌دار",
        assessment_profile="written",
    )
    other_book = Book(
        title="نسخهٔ دیگر فیزیک دهم",
        grade_id=grade.id,
        academic_year_id=year.id,
        status=BookStatus.ready,
        catalog_status="approved",
        pdf_file_path="/tmp/physics-other.pdf",
        total_pdf_pages=10,
    )
    session.add_all([objective, other_book])
    await session.flush()
    session.add(
        BookCurriculumLink(
            book_id=other_book.id,
            branch_id=branch.id,
            field_of_study_id=field.id,
            subject_id=subject.id,
            scope_code="field:math_physics:physics-other-edition",
        )
    )
    session.add(
        LearningEvidence(
            user_id=user.id,
            objective_id=objective.id,
            book_id=other_book.id,
            source_type="performance_task",
            source_ref="other-edition-evidence",
            score=100,
            verification_status="verified",
            reviewed_at=datetime.now(timezone.utc),
            observed_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    result = await mastery_service.objective_tree(
        session,
        user_id=user.id,
        book_id=book.id,
    )

    objective_result = next(item for item in result["objectives"] if item["code"] == objective.code)
    assert objective_result["status"] == "not_started"
    assert objective_result["evidence_count"] == 0


@pytest.mark.asyncio
async def test_student_cannot_overwrite_reviewed_learning_evidence(curriculum_session):
    session = curriculum_session
    grade, branch, field, year, subject, book = await _create_curriculum(session)
    user = User(phone_number="09120000003", role="student", is_active=True)
    session.add(user)
    await session.flush()
    unit = CurriculumUnit(
        grade_id=grade.id,
        subject_id=subject.id,
        branch_id=branch.id,
        field_of_study_id=field.id,
        academic_year_id=year.id,
        scope_code=year.code,
        code="reviewed-evidence-unit",
        title="واحد شواهد",
    )
    session.add(unit)
    await session.flush()
    objective = LearningObjective(
        unit_id=unit.id,
        code="physics.reviewed.evidence",
        title="هدف شواهد",
        assessment_profile="written",
    )
    session.add(objective)
    await session.commit()

    saved = await mastery_service.record_objective_evidence(
        session,
        user_id=user.id,
        objective_id=objective.id,
        source_type="self_assessment",
        source_ref="immutable-reviewed-evidence",
        score=85,
        qualitative_level=None,
        rubric={},
        feedback="ارسال اولیه",
        book_id=book.id,
    )
    saved.verification_status = "verified"
    saved.reviewed_at = datetime.now(timezone.utc)
    await session.commit()

    with pytest.raises(HTTPException) as error:
        await mastery_service.record_objective_evidence(
            session,
            user_id=user.id,
            objective_id=objective.id,
            source_type="self_assessment",
            source_ref="immutable-reviewed-evidence",
            score=10,
            qualitative_level=None,
            rubric={},
            feedback="تلاش برای جایگزینی پس از تأیید",
            book_id=book.id,
        )

    assert error.value.status_code == 409
    await session.refresh(saved)
    assert saved.verification_status == "verified"
    assert saved.score == 85


@pytest.mark.asyncio
async def test_immersive_assist_rejects_text_not_present_on_cited_page(curriculum_session, monkeypatch):
    from app.services import immersive_service

    session = curriculum_session
    _grade, _branch, _field, _year, _subject, book = await _create_curriculum(session)
    page = BookPage(
        book_id=book.id,
        pdf_page_index=0,
        printed_page_number=1,
        markdown_content="سرعت متوسط برابر جابه‌جایی تقسیم بر زمان است.",
        page_image_path="/tmp/reader-selection.png",
        status=PageStatus.done,
    )
    session.add(page)
    await session.commit()

    async def unexpected_model_call(**_kwargs):
        raise AssertionError("LLM must not receive a selection outside the cited textbook page")

    monkeypatch.setattr(immersive_service, "run_capability_text", unexpected_model_call)

    with pytest.raises(HTTPException) as error:
        await immersive_service.assist(
            session,
            SimpleNamespace(id="student-reader"),
            book_id=book.id,
            action="explain",
            pdf_page_index=0,
            selection="متنی که در این صفحه وجود ندارد",
        )

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_immersive_assist_accepts_normalized_text_from_same_page(curriculum_session, monkeypatch):
    from types import SimpleNamespace
    from app.services import immersive_service

    session = curriculum_session
    _grade, _branch, _field, _year, _subject, book = await _create_curriculum(session)
    page = BookPage(
        book_id=book.id,
        pdf_page_index=0,
        printed_page_number=1,
        markdown_content="سرعت متوسط **برابر جابه‌جایی تقسیم بر زمان** است.",
        page_image_path="/tmp/reader-selection-valid.png",
        status=PageStatus.done,
    )
    session.add(page)
    await session.commit()
    captured = {}

    async def fake_model_call(**kwargs):
        captured["user_text"] = kwargs["user_text"]
        return SimpleNamespace(content="توضیح معتبر", audit_id="audit-reader"), [], None

    monkeypatch.setattr(immersive_service, "run_capability_text", fake_model_call)

    result = await immersive_service.assist(
        session,
        SimpleNamespace(id="student-reader"),
        book_id=book.id,
        action="explain",
        pdf_page_index=0,
        selection="برابر جابه‌جایی تقسیم بر زمان",
    )

    assert result["answer"] == "توضیح معتبر"
    assert "برابر جابه‌جایی تقسیم بر زمان" in captured["user_text"]
    assert "فیزیک دهم" in result["citation"]["citation"]
