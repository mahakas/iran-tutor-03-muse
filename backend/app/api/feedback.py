"""Student feedback API: report a wrong or unclear AI answer (Phase 1, Rule 3).

Reports land directly in the admin **Flag Queue** (`ai_audit_logs.status=flagged`),
which is the same queue surfaced by `/admin` -> Observability.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.governance import AiAuditLog
from app.services.rbac import get_optional_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])

VALID_REASONS = ("wrong_answer", "not_from_book", "unclear", "inappropriate", "other")


class FlagAnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=48)
    note: str | None = Field(default=None, max_length=500)


@router.post("/flag")
async def flag_ai_answer(
    body: FlagAnswerBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Attribute a report to the calling student and flag the audit record."""
    user = await get_optional_user(request, session)
    if user is None:
        raise HTTPException(status_code=401, detail="برای ثبت گزارش باید وارد شوید.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="حساب کاربری شما غیرفعال شده است.")

    if not body.audit_id:
        raise HTTPException(status_code=422, detail="شناسهٔ پاسخ (audit_id) لازم است.")

    row = await session.get(AiAuditLog, body.audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="پاسخ موردنظر پیدا نشد.")
    if row.user_id is not None and row.user_id != user.id:
        raise HTTPException(status_code=403, detail="این پاسخ به حساب شما تعلق ندارد.")

    reason = (body.reason or "other").strip().lower()
    if reason not in VALID_REASONS:
        reason = "other"
    note = (body.note or "").strip()[:200]
    row.status = "flagged"
    row.flag_reason = (f"student_report:{reason}" + (f" — {note}" if note else ""))[:255]
    row.flagged_by = user.id
    await session.commit()

    logger.info(
        "feedback.flag audit_id=%s user=%s reason=%s", row.id, user.id[:8], reason
    )
    return {
        "flagged": True,
        "audit_id": row.id,
        "status": row.status,
        "reason": reason,
    }
