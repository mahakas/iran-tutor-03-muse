"""Shared post-answer persistence for tutor turns (Phase 4).

Used by both `/ask` and the streaming runner so usage deduction, the L1 session
trace, and the async L2 extraction behave identically.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.services.auth_billing_service import record_and_deduct_usage
from app.services.learner_memory_service import extract_l2_from_turn, record_l1_turn
from app.services.chat_stream_hooks import schedule_l2_extraction


def _primary_source(result: dict[str, Any]) -> tuple[int | None, int | None]:
    sources = result.get("sources") or []
    if not sources:
        return None, None
    first = sources[0]
    return first.get("book_id"), first.get("chapter_number")


async def finish_turn_success(
    db: AsyncSession,
    *,
    user_id: str,
    params: Any,
    mode: str,
    result: dict[str, Any],
    usage: Any,
) -> None:
    """Commit usage (when tokens were used) and the L1 trace; schedule L2 extraction."""
    if not isinstance(db, AsyncSession):
        # Non-DB callers (test doubles) keep the pre-Phase-4 behaviour: nothing persists.
        return
    user = await db.get(User, user_id)
    if usage.total_tokens > 0 and user is not None:
        result["usage"] = await record_and_deduct_usage(
            db,
            user=user,
            action="tutor_ask",
            book_id=_primary_source(result)[0] or params.book_id,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )
    else:
        await db.commit()

    book_id, chapter = _primary_source(result)
    book_id = book_id or params.book_id
    if params.chat_session_id:
        await record_l1_turn(
            db,
            user_id=user_id,
            session_id=params.chat_session_id,
            book_id=book_id,
            mode=mode,
            query=params.query,
            answer_excerpt=str(result.get("answer") or ""),
        )
        await db.commit()

    schedule_l2_extraction(
        extract_l2_from_turn(
            user_id=user_id,
            session_id=params.chat_session_id,
            book_id=book_id,
            chapter_number=chapter,
            query=params.query,
            answer=str(result.get("answer") or ""),
        )
    )
