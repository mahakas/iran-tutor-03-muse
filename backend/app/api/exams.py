"""Timed, persistent multiple-choice exam API (OTP-authenticated & token-metered)."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import enforce_student_grade_level, require_student, resolve_book_scope
from app.core.llm_client import track_token_usage
from app.db.session import get_session
from app.models.auth import User
from app.models.curriculum import Book
from app.models.exam import ExamSession
from app.services.auth_billing_service import record_and_deduct_usage
from app.services.capability_service import check_capability_access
from app.services.quota_service import enforce_ai_quota
from app.services.exam_service import create_exam, exam_summary, public_exam, submit_exam

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/exams", tags=["exams"])


class CreateExamRequest(BaseModel):
    grade_number: int = Field(ge=1, le=12)
    major_code: str | None = Field(default=None, max_length=64)
    branch_code: str | None = Field(default=None, max_length=64)
    book_id: int = Field(gt=0)
    chapter_title: str | None = Field(default=None, max_length=255)
    question_count: int = Field(default=5, ge=3, le=20)
    time_limit_minutes: int = Field(default=15, ge=5, le=120)
    exam_type: Literal["konkoor", "final"] = "konkoor"


class SubmitExamRequest(BaseModel):
    answers: dict[str, str | None] = Field(default_factory=dict, max_length=20)


@router.post("")
async def start_exam(
    body: CreateExamRequest,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=body.book_id,
        grade_number=body.grade_number,
        major_code=body.major_code,
        branch_code=body.branch_code,
    )
    enforce_student_grade_level(current_user, grade.number)
    await check_capability_access(session, "quiz", current_user)
    await enforce_ai_quota(session, user=current_user, feature_key="quiz")
    try:
        with track_token_usage() as usage:
            exam = await create_exam(
                session,
                book_id=book.id,
                grade_number=grade.number,
                major_code=major_code,
                branch_code=body.branch_code,
                question_count=body.question_count,
                time_limit_minutes=body.time_limit_minutes,
                exam_type=body.exam_type,
                chapter_title=body.chapter_title,
                user_id=current_user.id,
            )
    except LookupError as error:
        raise HTTPException(status_code=409, detail="no approved pages found for this exam scope") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        if "TUTOR_MODEL" in str(error):
            raise HTTPException(status_code=503, detail="question-generation model is not configured") from error
        logger.exception("exam creation failed")
        raise HTTPException(status_code=503, detail="exam service is temporarily unavailable") from error
    except Exception as error:  # noqa: BLE001
        logger.exception("exam creation failed")
        raise HTTPException(status_code=503, detail="exam service is temporarily unavailable") from error

    payload = public_exam(exam)
    if usage.total_tokens > 0:
        usage_info = await record_and_deduct_usage(
            session,
            user=current_user,
            action="exam_create",
            book_id=book.id,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )
        payload["usage"] = usage_info
    return payload


@router.get("")
async def list_exams(
    book_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    query = (
        select(ExamSession, Book.title)
        .outerjoin(Book, ExamSession.book_id == Book.id)
        .where(ExamSession.user_id == current_user.id)
        .order_by(ExamSession.created_at.desc())
        .limit(limit)
    )
    if book_id is not None:
        query = query.where(ExamSession.book_id == book_id)
    rows = (await session.execute(query)).all()
    return [exam_summary(exam, book_title=book_title) for exam, book_title in rows]


@router.get("/{exam_id}")
async def get_exam(
    exam_id: str,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    exam = await session.scalar(
        select(ExamSession).where(ExamSession.id == exam_id, ExamSession.user_id == current_user.id)
    )
    if exam is None:
        raise HTTPException(status_code=404, detail="exam not found")
    return public_exam(exam, include_report=True)


@router.post("/{exam_id}/submit")
async def finish_exam(
    exam_id: str,
    body: SubmitExamRequest,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    exam = await session.scalar(
        select(ExamSession).where(ExamSession.id == exam_id, ExamSession.user_id == current_user.id)
    )
    if exam is None:
        raise HTTPException(status_code=404, detail="exam not found")
    try:
        report = submit_exam(exam, body.answers)
    except TimeoutError as error:
        await session.commit()
        raise HTTPException(status_code=410, detail="exam time has expired") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    await session.commit()
    await _record_exam_memory(
        session, user_id=current_user.id, book_id=exam.book_id, report=report, exam=exam
    )
    return {"exam_id": exam.id, "status": "submitted", "report_card": report}


async def _record_exam_memory(
    session: AsyncSession, *, user_id: str, book_id: int, report: dict[str, object], exam: object | None = None
) -> None:
    """Phase 4/5: per-chapter results feed L2/L3 memory, chapter mastery, and the mistake bank.

    Best effort: a failure here is logged and rolled back, and never blocks grading.
    """
    from app.services import mastery_service, mistake_bank_service
    from app.services.learner_memory_service import record_quiz_outcome

    buckets: dict[int | None, list[int]] = {}
    for item in report.get("by_question", []) or []:  # type: ignore[union-attr]
        source = item.get("source") if isinstance(item, dict) else None
        chapter = source.get("chapter_number") if isinstance(source, dict) else None
        chapter = chapter if isinstance(chapter, int) else None
        bucket = buckets.setdefault(chapter, [0, 0])
        bucket[1] += 1
        if item.get("correct"):
            bucket[0] += 1
    try:
        for chapter, (correct, total) in buckets.items():
            topic = f"آزمون فصل {chapter}" if chapter is not None else "آزمون کتاب"
            await record_quiz_outcome(
                session,
                user_id=user_id,
                book_id=book_id,
                chapter_number=chapter,
                topic=topic,
                correct=correct,
                total=total,
                source_type="quiz",
            )
            if chapter is not None:
                await mastery_service.record_component(
                    session,
                    user_id=user_id,
                    book_id=book_id,
                    chapter_number=chapter,
                    component="exam",
                    correct=correct,
                    total=total,
                )
        if exam is not None:
            await mistake_bank_service.record_exam_mistakes(
                session, user_id=user_id, exam=exam, report=dict(report)  # type: ignore[arg-type]
            )
        await session.commit()
    except Exception:  # noqa: BLE001 - memory must never break exam grading
        await session.rollback()
        logging.getLogger(__name__).exception("exam memory update failed")