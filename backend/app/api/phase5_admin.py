"""Phase 5 admin governance & glass-box oversight (`/api/v1/admin/*`, admin only).

Admins can see each student's mistake bank, mastery progress, Deep Solve sessions
and Validator Gate rejections, and can edit mastery rules. Every admin edit is
written to `admin_action_logs`.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.db.session import get_session
from app.models.auth import User
from app.models.curriculum import Book
from app.models.phase5 import (
    AdminActionLog,
    DeepSolveSession,
    MasteryChapterProgress,
    MistakeBankItem,
    QuizValidationLog,
)
from app.services import mastery_service
from app.services import mistake_bank_service as mbs

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-phase5"],
    dependencies=[Depends(require_admin)],
)


class MasterySettingsBody(BaseModel):
    threshold: float | None = Field(default=None, ge=0.3, le=1.0)
    unlock_mode: Literal["sequential", "open"] | None = None


class ChapterOverrideBody(BaseModel):
    override: Literal["locked", "open"] | None = None


async def _user_or_404(session: AsyncSession, user_id: str) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    return user


def _log(session: AsyncSession, action: str, target: str, payload: dict[str, Any]) -> None:
    session.add(AdminActionLog(actor="admin", action=action, target=target, payload_json=payload))


@router.get("/users/{user_id}/mistakes")
async def admin_user_mistakes(
    user_id: str,
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _user_or_404(session, user_id)
    result = await mbs.list_items(session, user, status=status, limit=limit, offset=0)
    return {"user_id": user_id, **result}


@router.get("/users/{user_id}/mastery")
async def admin_user_mastery(
    user_id: str,
    book_id: int | None = Query(default=None, gt=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _user_or_404(session, user_id)
    if book_id is not None:
        return {"user_id": user_id, **(await mastery_service.book_tree(session, user_id=user_id, book_id=book_id))}
    rows = (
        await session.scalars(
            select(MasteryChapterProgress).where(MasteryChapterProgress.user_id == user_id)
        )
    ).all()
    books: dict[int, dict[str, Any]] = {}
    for row in rows:
        entry = books.setdefault(row.book_id, {"book_id": row.book_id, "chapters": []})
        entry["chapters"].append(
            {
                "chapter_number": row.chapter_number,
                "score": mastery_service.chapter_score(row),
                "exam": [row.exam_correct, row.exam_total],
                "flash": [row.flash_correct, row.flash_total],
                "solve": [row.solve_correct, row.solve_total],
            }
        )
    for entry in books.values():
        book = await session.get(Book, entry["book_id"])
        entry["book_title"] = book.title if book else None
        entry["chapters"].sort(key=lambda c: c["chapter_number"])
    return {"user_id": user_id, "books": list(books.values())}


@router.get("/users/{user_id}/deep-solve-sessions")
async def admin_user_deep_solve(
    user_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _user_or_404(session, user_id)
    rows = (
        await session.scalars(
            select(DeepSolveSession)
            .where(DeepSolveSession.user_id == user_id)
            .order_by(DeepSolveSession.created_at.desc())
            .limit(100)
        )
    ).all()
    return {
        "user_id": user_id,
        "items": [
            {
                "id": row.id,
                "book_id": row.book_id,
                "problem_text": row.problem_text,
                "topic": row.topic,
                "status": row.status,
                "current_step": row.current_step,
                "total_steps": len(row.steps_json or []),
                "hint_levels": (row.state_json or {}).get("hint_levels", {}),
                "tutor_revealed": (row.state_json or {}).get("tutor_revealed", []),
                "full_revealed": bool((row.state_json or {}).get("full_revealed")),
                "steps": row.steps_json or [],
                "final_answer": row.final_answer,
                "mastery_recorded": bool(row.mastery_recorded),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@router.get("/users/{user_id}/quiz-validation")
async def admin_user_validation(
    user_id: str,
    verdict: Literal["approved", "fixed", "rejected"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _user_or_404(session, user_id)
    stmt = select(QuizValidationLog).where(QuizValidationLog.user_id == user_id)
    if verdict:
        stmt = stmt.where(QuizValidationLog.verdict == verdict)
    rows = (await session.scalars(stmt.order_by(QuizValidationLog.id.desc()).limit(limit))).all()
    return {
        "user_id": user_id,
        "items": [
            {
                "id": row.id,
                "exam_id": row.exam_id,
                "book_id": row.book_id,
                "question_index": row.question_index,
                "verdict": row.verdict,
                "reasons": list(row.reasons_json or []),
                "question": dict(row.question_json or {}),
                "audit_id": row.audit_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@router.get("/mastery/books/{book_id}/settings")
async def admin_mastery_settings(book_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    if await session.get(Book, book_id) is None:
        raise HTTPException(status_code=404, detail="کتاب یافت نشد.")
    return mastery_service.serialize_settings(await mastery_service.get_settings(session, book_id))


@router.put("/mastery/books/{book_id}/settings")
async def admin_update_mastery_settings(
    book_id: int,
    body: MasterySettingsBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    settings = await mastery_service.update_settings(
        session, book_id=book_id, threshold=body.threshold, unlock_mode=body.unlock_mode
    )
    _log(session, "mastery.settings_update", f"book:{book_id}", body.model_dump(exclude_none=True))
    await session.commit()
    return mastery_service.serialize_settings(settings)


@router.put("/mastery/books/{book_id}/chapters/{chapter_number}/override")
async def admin_chapter_override(
    book_id: int,
    chapter_number: int,
    body: ChapterOverrideBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    settings = await mastery_service.set_chapter_override(
        session, book_id=book_id, chapter_number=chapter_number, override=body.override
    )
    _log(
        session,
        "mastery.chapter_override",
        f"book:{book_id}:chapter:{chapter_number}",
        {"override": body.override},
    )
    await session.commit()
    return mastery_service.serialize_settings(settings)


@router.get("/action-logs")
async def admin_action_logs(
    target: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(AdminActionLog)
    if target:
        stmt = stmt.where(AdminActionLog.target.like(f"{target}%"))
    rows = (await session.scalars(stmt.order_by(AdminActionLog.id.desc()).limit(limit))).all()
    return {
        "items": [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "target": row.target,
                "payload": dict(row.payload_json or {}),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }
