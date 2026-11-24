"""Phase 5 mastery path: chapter scores from exams, flashcards and solve sessions.

Score = weighted mean of the per-component accuracy (exam 0.5, flashcards 0.3,
solve 0.2), renormalised over components that have evidence. A chapter is
mastered when its score reaches the book threshold (admin-configurable). Chapters
unlock sequentially unless the admin switches the book to `open` mode or sets a
per-chapter override.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import (
    AcademicYear,
    Book,
    BookCurriculumLink,
    BookPage,
    BookPageObjective,
    BookStatus,
    CurriculumUnit,
    LearningEvidence,
    LearningObjective,
    ObjectivePrerequisite,
    PageStatus,
    Subject,
)
from app.models.phase5 import MasteryBookSettings, MasteryChapterProgress
from app.services.curriculum_access import is_student_visible_book

WEIGHTS: dict[str, float] = {"exam": 0.5, "flash": 0.3, "solve": 0.2}
DEFAULT_THRESHOLD = 0.7
UNLOCK_MODES = ("sequential", "open")
OVERRIDE_VALUES = ("locked", "open")


async def record_component(
    session: AsyncSession,
    *,
    user_id: str,
    book_id: int,
    chapter_number: int | None,
    component: str,
    correct: int,
    total: int,
) -> MasteryChapterProgress | None:
    """Add evidence for one chapter. Silently ignores events without chapter or total."""
    if component not in WEIGHTS or chapter_number is None or total <= 0:
        return None
    row = await session.scalar(
        select(MasteryChapterProgress).where(
            MasteryChapterProgress.user_id == user_id,
            MasteryChapterProgress.book_id == book_id,
            MasteryChapterProgress.chapter_number == chapter_number,
        )
    )
    if row is None:
        row = MasteryChapterProgress(
            user_id=user_id,
            book_id=book_id,
            chapter_number=chapter_number,
            exam_correct=0,
            exam_total=0,
            flash_correct=0,
            flash_total=0,
            solve_correct=0,
            solve_total=0,
        )
        session.add(row)
    setattr(row, f"{component}_correct", int(getattr(row, f"{component}_correct") or 0) + max(0, min(correct, total)))
    setattr(row, f"{component}_total", int(getattr(row, f"{component}_total") or 0) + total)
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


def chapter_score(row: MasteryChapterProgress | None) -> float | None:
    if row is None:
        return None
    weighted = 0.0
    weight_sum = 0.0
    for component, weight in WEIGHTS.items():
        total = int(getattr(row, f"{component}_total") or 0)
        if total <= 0:
            continue
        correct = int(getattr(row, f"{component}_correct") or 0)
        weighted += weight * (correct / total)
        weight_sum += weight
    if weight_sum == 0:
        return None
    return round(weighted / weight_sum, 4)


def _breakdown(row: MasteryChapterProgress | None) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for component in WEIGHTS:
        out[component] = {
            "correct": int(getattr(row, f"{component}_correct", 0) or 0) if row else 0,
            "total": int(getattr(row, f"{component}_total", 0) or 0) if row else 0,
        }
    return out


async def get_settings(session: AsyncSession, book_id: int) -> MasteryBookSettings:
    settings = await session.get(MasteryBookSettings, book_id)
    if settings is None:
        settings = MasteryBookSettings(
            book_id=book_id,
            threshold=DEFAULT_THRESHOLD,
            unlock_mode="sequential",
            chapter_overrides_json={},
        )
    return settings


def serialize_settings(settings: MasteryBookSettings) -> dict[str, Any]:
    return {
        "book_id": settings.book_id,
        "threshold": float(settings.threshold),
        "unlock_mode": settings.unlock_mode,
        "chapter_overrides": dict(settings.chapter_overrides_json or {}),
    }


async def _chapters(session: AsyncSession, book_id: int) -> list[dict[str, Any]]:
    pages = (
        await session.scalars(
            select(BookPage)
            .where(
                BookPage.book_id == book_id,
                BookPage.chapter_number.is_not(None),
                BookPage.status == PageStatus.done,
            )
            .order_by(BookPage.pdf_page_index.asc())
        )
    ).all()
    seen: dict[int, dict[str, Any]] = {}
    for page in pages:
        if page.chapter_number in seen:
            seen[page.chapter_number]["page_end"] = page.pdf_page_index
            continue
        seen[page.chapter_number] = {
            "chapter_number": page.chapter_number,
            "chapter_title": page.chapter_title or f"فصل {page.chapter_number}",
            "page_start": page.pdf_page_index,
            "page_end": page.pdf_page_index,
        }
    return list(seen.values())


async def book_tree(session: AsyncSession, *, user_id: str, book_id: int) -> dict[str, Any]:
    book = await session.get(Book, book_id)
    if not is_student_visible_book(book):
        raise HTTPException(status_code=404, detail="کتاب آماده و منتشرشده یافت نشد.")
    settings = await get_settings(session, book_id)
    threshold = float(settings.threshold)
    overrides = dict(settings.chapter_overrides_json or {})
    progress = {
        row.chapter_number: row
        for row in (
            await session.scalars(
                select(MasteryChapterProgress).where(
                    MasteryChapterProgress.user_id == user_id,
                    MasteryChapterProgress.book_id == book_id,
                )
            )
        ).all()
    }
    nodes: list[dict[str, Any]] = []
    previous_mastered = True
    for index, chapter in enumerate(await _chapters(session, book_id)):
        number = chapter["chapter_number"]
        row = progress.get(number)
        score = chapter_score(row)
        mastered = score is not None and score >= threshold
        override = overrides.get(str(number))
        locked_reason: str | None = None
        if override == "locked":
            locked_reason = "admin_locked"
        elif override == "open":
            locked_reason = None
        elif settings.unlock_mode == "sequential" and index > 0 and not previous_mastered:
            locked_reason = "previous_chapter_not_mastered"
        if locked_reason:
            status = "locked"
        elif mastered:
            status = "mastered"
        elif score is None:
            status = "not_started"
        else:
            status = "in_progress"
        nodes.append(
            {
                **chapter,
                "score": score,
                "threshold": threshold,
                "status": status,
                "locked_reason": locked_reason,
                "override": override,
                "evidence": _breakdown(row),
            }
        )
        previous_mastered = mastered
    return {
        "book": {"id": book.id, "title": book.title},
        "threshold": threshold,
        "unlock_mode": settings.unlock_mode,
        "mastered_count": sum(1 for node in nodes if node["status"] == "mastered"),
        "chapters": nodes,
    }


async def update_settings(
    session: AsyncSession,
    *,
    book_id: int,
    threshold: float | None = None,
    unlock_mode: str | None = None,
    actor: str = "admin",
) -> MasteryBookSettings:
    if await session.get(Book, book_id) is None:
        raise HTTPException(status_code=404, detail="کتاب یافت نشد.")
    settings = await session.get(MasteryBookSettings, book_id)
    if settings is None:
        settings = MasteryBookSettings(
            book_id=book_id, threshold=DEFAULT_THRESHOLD, unlock_mode="sequential", chapter_overrides_json={}
        )
        session.add(settings)
    if threshold is not None:
        if not 0.3 <= threshold <= 1.0:
            raise HTTPException(status_code=422, detail="آستانهٔ تسلط باید بین ۰٫۳ و ۱ باشد.")
        settings.threshold = float(threshold)
    if unlock_mode is not None:
        if unlock_mode not in UNLOCK_MODES:
            raise HTTPException(status_code=422, detail="حالت باز شدن نامعتبر است.")
        settings.unlock_mode = unlock_mode
    settings.updated_by = actor
    settings.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return settings


async def set_chapter_override(
    session: AsyncSession, *, book_id: int, chapter_number: int, override: str | None, actor: str = "admin"
) -> MasteryBookSettings:
    if override is not None and override not in OVERRIDE_VALUES:
        raise HTTPException(status_code=422, detail="مقدار قفل فصل نامعتبر است.")
    settings = await update_settings(session, book_id=book_id, actor=actor)
    overrides = dict(settings.chapter_overrides_json or {})
    if override is None:
        overrides.pop(str(chapter_number), None)
    else:
        overrides[str(chapter_number)] = override
    settings.chapter_overrides_json = overrides
    await session.flush()
    return settings


QUALITATIVE_MASTERED_LEVELS = {"proficient", "advanced", "mastered"}
QUALITATIVE_NEEDS_SUPPORT_LEVELS = {"needs_support", "not_observed"}


def _evidence_progress(
    rows: list[LearningEvidence],
    *,
    assessment_profile: str,
    threshold: float,
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda item: item.observed_at, reverse=True)
    latest_submission = ordered[0] if ordered else None
    verified_rows = [row for row in ordered if getattr(row, "verification_status", "unverified") == "verified"]
    latest = verified_rows[0] if verified_rows else latest_submission
    level = None
    if latest is not None:
        level = latest.qualitative_level or (latest.rubric_json or {}).get("overall_level")

    if not ordered:
        status = "not_started"
        score = None
    elif not verified_rows:
        # Student-submitted self-assessments and practical work cannot independently
        # certify mastery. An authorized reviewer must verify the evidence first.
        status = "submitted_for_review" if any(
            getattr(row, "verification_status", "unverified") == "unverified" for row in ordered
        ) else "needs_support"
        score = None
    elif assessment_profile in {"qualitative_descriptive", "performance"}:
        if level in QUALITATIVE_MASTERED_LEVELS:
            status = "mastered"
        elif level in QUALITATIVE_NEEDS_SUPPORT_LEVELS:
            status = "needs_support"
        else:
            status = "developing"
        score = None
    else:
        scored = [float(row.score) for row in verified_rows if row.score is not None][:5]
        score = round(sum(scored) / len(scored), 2) if scored else None
        if score is None:
            status = "developing"
        elif score >= threshold:
            status = "mastered"
        else:
            status = "developing"

    return {
        "status": status,
        "score": score,
        "qualitative_level": level,
        "evidence_count": len(ordered),
        "latest_evidence": (
            {
                # Display the latest submission, even when an older verified
                # submission continues to determine the mastery score/status.
                "source_type": latest_submission.source_type,
                "score": latest_submission.score,
                "qualitative_level": (
                    latest_submission.qualitative_level
                    or (latest_submission.rubric_json or {}).get("overall_level")
                ),
                "verification_status": getattr(latest_submission, "verification_status", "unverified"),
                "review_note": getattr(latest_submission, "review_note", None),
                "reviewed_at": (
                    latest_submission.reviewed_at.isoformat()
                    if getattr(latest_submission, "reviewed_at", None)
                    else None
                ),
                "feedback": latest_submission.feedback,
                "observed_at": (
                    latest_submission.observed_at.isoformat()
                    if latest_submission.observed_at
                    else None
                ),
            }
            if latest_submission is not None
            else None
        ),
        "evidence": [
            {
                "id": row.id,
                "source_type": row.source_type,
                "score": row.score,
                "qualitative_level": row.qualitative_level,
                "verification_status": getattr(row, "verification_status", "unverified"),
                "reviewed_at": row.reviewed_at.isoformat() if getattr(row, "reviewed_at", None) else None,
                "review_note": getattr(row, "review_note", None),
                "rubric": dict(row.rubric_json or {}),
                "feedback": row.feedback,
                "observed_at": row.observed_at.isoformat() if row.observed_at else None,
            }
            for row in ordered[:8]
        ],
    }


async def record_objective_evidence(
    session: AsyncSession,
    *,
    user_id: str,
    objective_id: int,
    source_type: str,
    source_ref: str | None,
    score: float | None,
    qualitative_level: str | None,
    rubric: dict[str, Any],
    feedback: str | None,
    book_id: int | None = None,
    pdf_page_index: int | None = None,
) -> LearningEvidence:
    objective = await session.get(LearningObjective, objective_id)
    if objective is None or not objective.is_active:
        raise HTTPException(status_code=404, detail="هدف یادگیری یافت نشد.")
    profile = objective.assessment_profile or "mixed"
    if profile == "qualitative_descriptive" and qualitative_level is None:
        raise HTTPException(status_code=422, detail="برای این هدف، سطح ارزیابی توصیفی لازم است.")
    if profile == "performance" and qualitative_level is None and not rubric:
        raise HTTPException(status_code=422, detail="برای هدف مهارتی، سطح یا روبرک عملکرد ثبت کنید.")
    if profile == "written" and score is None:
        raise HTTPException(status_code=422, detail="برای این هدف، نمرهٔ ارزیابی لازم است.")
    if profile == "mixed" and score is None and qualitative_level is None and not rubric:
        raise HTTPException(status_code=422, detail="حداقل یک شاهد کمی، توصیفی یا عملکردی لازم است.")

    if book_id is None:
        raise HTTPException(status_code=422, detail="برای ثبت شاهد یادگیری، انتخاب کتاب رسمی الزامی است.")

    page_id = None
    if book_id is not None:
        book = await session.get(Book, book_id)
        if not is_student_visible_book(book):
            raise HTTPException(status_code=404, detail="کتاب آماده و منتشرشده یافت نشد.")
        unit = await session.get(CurriculumUnit, objective.unit_id)
        if unit is None or unit.grade_id != book.grade_id:
            raise HTTPException(status_code=422, detail="هدف یادگیری با پایهٔ این کتاب سازگار نیست.")

        book_year = await session.get(AcademicYear, book.academic_year_id) if book.academic_year_id else None
        expected_year_code = book_year.code if book_year is not None else None
        if expected_year_code:
            if unit.scope_code not in {expected_year_code, "unspecified"} or unit.academic_year_id not in {
                None,
                book.academic_year_id,
            }:
                raise HTTPException(status_code=422, detail="نسخهٔ سال تحصیلی هدف با نسخهٔ کتاب سازگار نیست.")
        elif unit.scope_code != "unspecified" or unit.academic_year_id is not None:
            raise HTTPException(status_code=422, detail="هدف نسخه‌دار به کتابی بدون سال تحصیلی متصل نمی‌شود.")

        book_links = (
            await session.scalars(
                select(BookCurriculumLink).where(BookCurriculumLink.book_id == book_id)
            )
        ).all()
        linked_subject_ids = {link.subject_id for link in book_links if link.subject_id is not None}
        if linked_subject_ids and unit.subject_id not in linked_subject_ids:
            raise HTTPException(status_code=422, detail="درس هدف یادگیری با درس این کتاب سازگار نیست.")
        if unit.branch_id is not None:
            branch_match = any(
                link.branch_id == unit.branch_id
                and (
                    (link.field_of_study_id is None and unit.field_of_study_id is None)
                    or (
                        link.field_of_study_id is not None
                        and (
                            unit.field_of_study_id is None
                            or link.field_of_study_id == unit.field_of_study_id
                        )
                    )
                )
                for link in book_links
            )
            if not branch_match:
                raise HTTPException(status_code=422, detail="شاخه یا رشتهٔ هدف یادگیری با کتاب سازگار نیست.")
    if pdf_page_index is not None:
        if book_id is None:
            raise HTTPException(status_code=422, detail="برای ثبت شمارهٔ صفحه، شناسهٔ کتاب لازم است.")
        page = await session.scalar(
            select(BookPage).where(
                BookPage.book_id == book_id,
                BookPage.pdf_page_index == pdf_page_index,
                BookPage.status == PageStatus.done,
            )
        )
        if page is None:
            raise HTTPException(status_code=404, detail="صفحهٔ تأییدشدهٔ کتاب یافت نشد.")
        mapped_objectives = (
            await session.scalars(
                select(BookPageObjective.objective_id).where(BookPageObjective.book_page_id == page.id)
            )
        ).all()
        if not mapped_objectives:
            raise HTTPException(status_code=422, detail="برای این صفحه هنوز نگاشت هدف یادگیری تأیید نشده است.")
        if objective_id not in mapped_objectives:
            raise HTTPException(status_code=422, detail="این هدف به صفحهٔ انتخاب‌شده متصل نیست.")
        page_id = page.id

    row = None
    if source_ref:
        row = await session.scalar(
            select(LearningEvidence).where(
                LearningEvidence.user_id == user_id,
                LearningEvidence.objective_id == objective_id,
                LearningEvidence.book_id == book_id,
                LearningEvidence.source_type == source_type,
                LearningEvidence.source_ref == source_ref,
            )
        )
    if row is not None:
        if row.book_page_id != page_id:
            raise HTTPException(
                status_code=409,
                detail="این شناسهٔ شاهد قبلاً برای صفحهٔ دیگری از همین کتاب استفاده شده است.",
            )
        if row.verification_status != "unverified":
            raise HTTPException(
                status_code=409,
                detail="شاهد بازبینی‌شده قابل ویرایش مجدد نیست؛ برای ارسال جدید شناسهٔ تازه بسازید.",
            )
    else:
        row = LearningEvidence(
            user_id=user_id,
            objective_id=objective_id,
            source_type=source_type,
            source_ref=source_ref,
        )
        session.add(row)
    row.book_id = book_id
    row.book_page_id = page_id
    row.score = score
    row.qualitative_level = qualitative_level
    row.rubric_json = dict(rubric or {})
    row.verification_status = "unverified"
    row.reviewed_at = None
    row.feedback = feedback
    row.observed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return row


async def objective_tree(
    session: AsyncSession,
    *,
    user_id: str,
    book_id: int,
) -> dict[str, Any]:
    """Objective-level mastery, respecting academic-year scope and prerequisite edges."""
    book = await session.get(Book, book_id)
    if not is_student_visible_book(book):
        raise HTTPException(status_code=404, detail="کتاب آماده و منتشرشده یافت نشد.")

    year_code = None
    if book.academic_year_id is not None:
        year = await session.get(AcademicYear, book.academic_year_id)
        year_code = year.code if year is not None else None
    scope_condition = (
        CurriculumUnit.scope_code.in_([year_code, "unspecified"])
        if year_code
        else CurriculumUnit.scope_code == "unspecified"
    )
    book_links = (
        await session.scalars(
            select(BookCurriculumLink).where(BookCurriculumLink.book_id == book_id)
        )
    ).all()
    subject_ids = {link.subject_id for link in book_links if link.subject_id is not None}
    branch_terms = []
    for link in book_links:
        if link.branch_id is None:
            continue
        branch_conditions = [CurriculumUnit.branch_id == link.branch_id]
        if link.field_of_study_id is None:
            branch_conditions.append(CurriculumUnit.field_of_study_id.is_(None))
        else:
            branch_conditions.append(
                or_(
                    CurriculumUnit.field_of_study_id == link.field_of_study_id,
                    CurriculumUnit.field_of_study_id.is_(None),
                )
            )
        branch_terms.append(and_(*branch_conditions))
    branch_scope_condition = (
        or_(
            and_(CurriculumUnit.branch_id.is_(None), CurriculumUnit.field_of_study_id.is_(None)),
            *branch_terms,
        )
        if branch_terms
        else and_(CurriculumUnit.branch_id.is_(None), CurriculumUnit.field_of_study_id.is_(None))
    )
    mapped_objective_ids = set(
        (
            await session.scalars(
                select(BookPageObjective.objective_id)
                .join(BookPage, BookPageObjective.book_page_id == BookPage.id)
                .join(LearningObjective, BookPageObjective.objective_id == LearningObjective.id)
                .join(CurriculumUnit, LearningObjective.unit_id == CurriculumUnit.id)
                .where(
                    BookPage.book_id == book_id,
                    BookPage.status == PageStatus.done,
                    CurriculumUnit.grade_id == book.grade_id,
                    CurriculumUnit.is_active.is_(True),
                    LearningObjective.is_active.is_(True),
                    scope_condition,
                    branch_scope_condition,
                    CurriculumUnit.subject_id.in_(subject_ids) if subject_ids else True,
                    (
                        or_(
                            CurriculumUnit.academic_year_id.is_(None),
                            CurriculumUnit.academic_year_id == book.academic_year_id,
                        )
                        if book.academic_year_id is not None
                        else CurriculumUnit.academic_year_id.is_(None)
                    ),
                )
            )
        ).all()
    )
    relevance_terms = []
    # Page-to-objective mappings are authoritative when present. An OR with
    # subject-wide objectives would nullify these mappings and widen mastery.
    if mapped_objective_ids:
        relevance_terms.append(LearningObjective.id.in_(mapped_objective_ids))
    elif subject_ids:
        relevance_terms.append(CurriculumUnit.subject_id.in_(subject_ids))
    if not relevance_terms:
        return {
            "book": {"id": book.id, "title": book.title},
            "academic_year_code": year_code,
            "threshold": None,
            "mastered_count": 0,
            "objectives": [],
            "message": "برای این کتاب هنوز درس یا پیوند هدف یادگیری وارد نشده است.",
        }

    rows = (
        await session.execute(
            select(LearningObjective, CurriculumUnit, Subject)
            .join(CurriculumUnit, LearningObjective.unit_id == CurriculumUnit.id)
            .join(Subject, CurriculumUnit.subject_id == Subject.id)
            .where(
                CurriculumUnit.grade_id == book.grade_id,
                CurriculumUnit.is_active.is_(True),
                LearningObjective.is_active.is_(True),
                scope_condition,
                (
                    and_(
                        CurriculumUnit.academic_year_id.is_(None),
                        CurriculumUnit.scope_code == "unspecified",
                    )
                    if book.academic_year_id is None
                    else and_(
                        or_(
                            CurriculumUnit.academic_year_id.is_(None),
                            CurriculumUnit.academic_year_id == book.academic_year_id,
                        ),
                        scope_condition,
                    )
                ),
                branch_scope_condition,
                or_(*relevance_terms),
            )
            .order_by(Subject.title, CurriculumUnit.sort_order, LearningObjective.code)
        )
    ).all()
    objectives = [objective for objective, _unit, _subject in rows]
    objective_ids = [objective.id for objective in objectives]
    if not objective_ids:
        return {
            "book": {"id": book.id, "title": book.title},
            "academic_year_code": year_code,
            "threshold": None,
            "mastered_count": 0,
            "objectives": [],
        }

    prereq_rows = (
        await session.execute(
            select(
                ObjectivePrerequisite.objective_id,
                LearningObjective.id,
                LearningObjective.code,
                LearningObjective.title,
                LearningObjective.assessment_profile,
            )
            .join(LearningObjective, ObjectivePrerequisite.prerequisite_id == LearningObjective.id)
            .join(CurriculumUnit, LearningObjective.unit_id == CurriculumUnit.id)
            .where(
                ObjectivePrerequisite.objective_id.in_(objective_ids),
                CurriculumUnit.grade_id == book.grade_id,
                CurriculumUnit.is_active.is_(True),
                LearningObjective.is_active.is_(True),
                scope_condition,
                (
                    and_(
                        CurriculumUnit.academic_year_id.is_(None),
                        CurriculumUnit.scope_code == "unspecified",
                    )
                    if book.academic_year_id is None
                    else or_(
                        CurriculumUnit.academic_year_id.is_(None),
                        CurriculumUnit.academic_year_id == book.academic_year_id,
                    )
                ),
                branch_scope_condition,
            )
        )
    ).all()
    prerequisite_ids = {row[1] for row in prereq_rows}
    all_evidence_ids = set(objective_ids) | prerequisite_ids
    evidence_rows = (
        await session.scalars(
            select(LearningEvidence)
            .where(
                LearningEvidence.user_id == user_id,
                LearningEvidence.book_id == book_id,
                LearningEvidence.objective_id.in_(all_evidence_ids),
            )
            .order_by(LearningEvidence.observed_at.desc(), LearningEvidence.id.desc())
        )
    ).all()
    evidence_by_objective: dict[int, list[LearningEvidence]] = {}
    for evidence in evidence_rows:
        evidence_by_objective.setdefault(evidence.objective_id, []).append(evidence)

    settings = await get_settings(session, book_id)
    threshold = float(settings.threshold) * 100
    profile_by_id = {objective.id: objective.assessment_profile for objective in objectives}
    profile_by_id.update({row[1]: row[4] for row in prereq_rows})
    progress_by_id = {
        objective_id: _evidence_progress(
            evidence_by_objective.get(objective_id, []),
            assessment_profile=profile_by_id.get(objective_id, "mixed"),
            threshold=threshold,
        )
        for objective_id in all_evidence_ids
    }
    titles_by_id = {row[1]: {"code": row[2], "title": row[3]} for row in prereq_rows}
    prerequisites_by_objective: dict[int, list[int]] = {}
    for objective_id, prerequisite_id, _code, _title, _profile in prereq_rows:
        prerequisites_by_objective.setdefault(objective_id, []).append(prerequisite_id)

    nodes: list[dict[str, Any]] = []
    for objective, unit, subject in rows:
        progress = progress_by_id[objective.id]
        prerequisite_items = [
            {
                **titles_by_id[prerequisite_id],
                "status": progress_by_id.get(
                    prerequisite_id,
                    {"status": "not_started"},
                )["status"],
            }
            for prerequisite_id in prerequisites_by_objective.get(objective.id, [])
        ]
        prerequisite_blocked = any(
            item["status"] != "mastered" for item in prerequisite_items
        )
        status = progress["status"]
        if prerequisite_blocked and status != "mastered":
            status = "locked"
        nodes.append(
            {
                "id": objective.id,
                "code": objective.code,
                "title": objective.title,
                "description": objective.description,
                "competency_type": objective.competency_type,
                "assessment_profile": objective.assessment_profile,
                "unit": {"id": unit.id, "code": unit.code, "title": unit.title, "type": unit.unit_type},
                "subject": {"code": subject.code, "title": subject.title},
                "status": status,
                "score": progress["score"],
                "qualitative_level": progress["qualitative_level"],
                "evidence_count": progress["evidence_count"],
                "latest_evidence": progress["latest_evidence"],
                "evidence": progress["evidence"],
                "prerequisites": prerequisite_items,
            }
        )

    return {
        "book": {"id": book.id, "title": book.title},
        "academic_year_code": year_code,
        "threshold": threshold,
        "mastered_count": sum(1 for node in nodes if node["status"] == "mastered"),
        "objectives": nodes,
    }
