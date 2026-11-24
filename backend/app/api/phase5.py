"""Phase 5 student API: mistake bank, mastery path, Deep Solve, immersive reader.

Every route re-checks its capability (`check_capability_access`) so admin toggles
and plan/role allow-lists apply server-side, not only in the menu.
"""

from __future__ import annotations

from typing import Any, Literal


from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import enforce_student_book_grade_level, require_student
from app.db.session import get_session
from app.models.auth import User
from app.services import deep_solve_service as ds
from app.services import immersive_service as imm
from app.services import mastery_service
from app.services import mistake_bank_service as mbs
from app.services.capability_service import check_capability_access

router = APIRouter(tags=["phase5"])


class AnswerBody(BaseModel):
    choice: str = Field(min_length=1, max_length=1)


class LearningEvidenceBody(BaseModel):
    objective_id: int = Field(gt=0)
    book_id: int = Field(gt=0)
    pdf_page_index: int | None = Field(default=None, ge=0)
    source_type: Literal["self_assessment", "performance_task", "reading"]
    source_ref: str | None = Field(default=None, max_length=128)
    score: float | None = Field(default=None, ge=0, le=100)
    qualitative_level: Literal["needs_support", "developing", "proficient", "advanced", "not_observed"] | None = None
    rubric: dict[str, Any] = Field(default_factory=dict)
    feedback: str | None = Field(default=None, max_length=4000)


class DeepSolveCreateBody(BaseModel):
    problem_text: str = Field(min_length=1, max_length=4000)
    book_id: int = Field(gt=0)
    chapter_number: int | None = Field(default=None, ge=1, le=99)


class DeepSolveActionBody(BaseModel):
    action: Literal["hint1", "hint2", "reveal_step", "full_solution"]


class AssistBody(BaseModel):
    action: Literal["summarize", "explain"]
    pdf_page_index: int = Field(ge=0)
    selection: str | None = Field(default=None, max_length=6000)


# ---------------------------------------------------------------------------
# Mistake bank
# ---------------------------------------------------------------------------
@router.get("/api/v1/mistakes")
async def list_mistakes(
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    book_id: int | None = Query(default=None, gt=0),
    chapter_number: int | None = Query(default=None, ge=1, le=99),
    error_tag: str | None = Query(default=None, max_length=16),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await check_capability_access(session, "mistake_bank", current_user)
    return await mbs.list_items(
        session,
        current_user,
        status=status,
        limit=limit,
        offset=offset,
        book_id=book_id,
        chapter_number=chapter_number,
        error_tag=error_tag,
    )


@router.get("/api/v1/mistakes/practice-set")
async def mistake_practice_set(
    limit: int = Query(default=5, ge=1, le=20),
    book_id: int | None = Query(default=None, gt=0),
    chapter_number: int | None = Query(default=None, ge=1, le=99),
    error_tag: str | None = Query(default=None, max_length=16),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await check_capability_access(session, "mistake_bank", current_user)
    return await mbs.practice_set(
        session,
        current_user,
        limit=limit,
        book_id=book_id,
        chapter_number=chapter_number,
        error_tag=error_tag,
    )


@router.post("/api/v1/mistakes/{item_id}/answer")
async def answer_mistake(
    item_id: int,
    body: AnswerBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await check_capability_access(session, "mistake_bank", current_user)
    return await mbs.answer_item(session, current_user, item_id, body.choice)


@router.post("/api/v1/mistakes/{item_id}/flashcard", status_code=201)
async def mistake_to_flashcard(
    item_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await check_capability_access(session, "mistake_bank", current_user)
    await check_capability_access(session, "flashcards", current_user)
    return await mbs.send_to_flashcards(session, current_user, item_id)


# ---------------------------------------------------------------------------
# Mastery path
# ---------------------------------------------------------------------------
@router.get("/api/v1/mastery/books/{book_id}")
async def my_mastery_path(
    book_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await enforce_student_book_grade_level(session, current_user, book_id)
    await check_capability_access(session, "mastery_path", current_user)
    return await mastery_service.book_tree(session, user_id=current_user.id, book_id=book_id)



@router.get("/api/v1/mastery/books/{book_id}/objectives")
async def my_objective_mastery_path(
    book_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await enforce_student_book_grade_level(session, current_user, book_id)
    await check_capability_access(session, "mastery_path", current_user)
    return await mastery_service.objective_tree(session, user_id=current_user.id, book_id=book_id)


@router.post("/api/v1/mastery/evidence", status_code=201)
async def record_mastery_evidence(
    body: LearningEvidenceBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await enforce_student_book_grade_level(session, current_user, body.book_id)
    await check_capability_access(session, "mastery_path", current_user)
    row = await mastery_service.record_objective_evidence(
        session,
        user_id=current_user.id,
        objective_id=body.objective_id,
        source_type=body.source_type,
        source_ref=body.source_ref,
        score=body.score,
        qualitative_level=body.qualitative_level,
        rubric=body.rubric,
        feedback=body.feedback,
        book_id=body.book_id,
        pdf_page_index=body.pdf_page_index,
    )
    return {
        "id": row.id,
        "objective_id": row.objective_id,
        "book_id": row.book_id,
        "source_type": row.source_type,
        "score": row.score,
        "qualitative_level": row.qualitative_level,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
    }


# ---------------------------------------------------------------------------
# Deep Solve
# ---------------------------------------------------------------------------
@router.post("/api/v1/deep-solve/sessions", status_code=201)
async def create_deep_solve(
    body: DeepSolveCreateBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await check_capability_access(session, "deep_solve", current_user)
    await enforce_student_book_grade_level(session, current_user, body.book_id)
    row = await ds.create_session(
        session,
        current_user,
        problem_text=body.problem_text,
        book_id=body.book_id,
        chapter_number=body.chapter_number,
    )
    return ds.public_view(row)


@router.get("/api/v1/deep-solve/sessions")
async def list_deep_solve(
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await check_capability_access(session, "deep_solve", current_user)
    rows = await ds.list_sessions(session, current_user.id)
    return {"items": [{"id": r.id, "problem_text": r.problem_text, "status": r.status, "topic": r.topic} for r in rows]}


@router.get("/api/v1/deep-solve/sessions/{session_id}")
async def get_deep_solve(
    session_id: str,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await check_capability_access(session, "deep_solve", current_user)
    row = await ds.get_owned(session, current_user, session_id)
    return ds.public_view(row)


@router.post("/api/v1/deep-solve/sessions/{session_id}/actions")
async def deep_solve_action(
    session_id: str,
    body: DeepSolveActionBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await check_capability_access(session, "deep_solve", current_user)
    row = await ds.apply_action(session, current_user, session_id, body.action)
    return ds.public_view(row)


# ---------------------------------------------------------------------------
# Immersive reader
# ---------------------------------------------------------------------------
@router.get("/api/v1/immersive/books/{book_id}")
async def immersive_overview(
    book_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await enforce_student_book_grade_level(session, current_user, book_id)
    await check_capability_access(session, "immersive_reader", current_user)
    return await imm.book_overview(session, book_id)


@router.get("/api/v1/immersive/books/{book_id}/pages/{pdf_page_index}")
async def immersive_page(
    book_id: int,
    pdf_page_index: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await enforce_student_book_grade_level(session, current_user, book_id)
    await check_capability_access(session, "immersive_reader", current_user)
    return await imm.page_detail(session, book_id, pdf_page_index)


@router.get("/api/v1/immersive/books/{book_id}/pages/{pdf_page_index}/image")
async def immersive_page_image(
    book_id: int,
    pdf_page_index: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    from pathlib import Path

    await enforce_student_book_grade_level(session, current_user, book_id)
    await check_capability_access(session, "immersive_reader", current_user)
    path = await imm.page_image_path(session, book_id, pdf_page_index)
    if not Path(path).is_file():
        raise HTTPException(status_code=404, detail="فایل تصویر صفحه در دسترس نیست.")
    return FileResponse(path, media_type="image/png")


@router.post("/api/v1/immersive/books/{book_id}/assist")
async def immersive_assist(
    book_id: int,
    body: AssistBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await enforce_student_book_grade_level(session, current_user, book_id)
    await check_capability_access(session, "immersive_reader", current_user)
    return await imm.assist(
        session,
        current_user,
        book_id=book_id,
        action=body.action,
        pdf_page_index=body.pdf_page_index,
        selection=body.selection,
    )
