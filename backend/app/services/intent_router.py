"""Auto-Mode Router (Phase 4): choose tutor / problem_solver / question_designer.

- Primary path: LLM classification through the AI gateway, feature key
  `intent_router` (admin-routable in `feature_model_routes`). The gateway audits it.
- Fallback path: deterministic Persian keyword rules when the model call fails
  or returns an invalid mode. The fallback decision is audited explicitly.

Every decision is recorded in `ai_audit_logs` (glass-box rule).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_gateway import (
    CallContext,
    complete_json_via_gateway,
    record_decision_audit,
)

logger = logging.getLogger(__name__)

ROUTER_FEATURE = "intent_router"
ROUTABLE_MODES: tuple[str, ...] = ("tutor", "problem_solver", "question_designer")

_ROUTER_SYSTEM = (
    "تو مسیریاب حالت‌های یک معلم خصوصی هستی. نیت پیام دانش‌آموز را در یکی از سه حالت "
    "طبقه‌بندی کن: tutor (توضیح مفهوم و راهنمایی)، problem_solver (حل تمرین یا مسئله)، "
    "question_designer (طراحی سؤال تمرینی یا آزمون). فقط JSON برگردان با کلیدهای "
    '"mode"، "confidence" (عدد بین ۰ و ۱) و "reason" (یک جملهٔ کوتاه).'
)

_SOLVER_RE = re.compile(r"حل\s|حل کن|حلش|مسئله|مساله|تمرین|محاسبه|چطور حل|جواب.*بده|مرحله به مرحله")
_DESIGNER_RE = re.compile(r"سؤال\s*(بساز|طراح|بده|جدید)|سوال\s*(بساز|طراح|بده|جدید)|تست بساز|آزمون بساز|کوییز|کویز|quiz")


@dataclass(frozen=True)
class RouterDecision:
    mode: str
    confidence: float
    reason: str
    source: str  # "llm" | "heuristic"
    audit_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("audit_id", None)
        return payload


def heuristic_mode(query: str) -> tuple[str, str]:
    text = query or ""
    if _DESIGNER_RE.search(text):
        return "question_designer", "کلیدواژهٔ طراحی سؤال"
    if _SOLVER_RE.search(text):
        return "problem_solver", "کلیدواژهٔ حل تمرین"
    return "tutor", "پیش‌فرض توضیح مفهوم"


def _parse_llm_decision(content: Any) -> tuple[str, float, str] | None:
    import json

    if isinstance(content, dict):
        payload = content
    else:
        try:
            payload = json.loads(str(content))
        except (TypeError, ValueError):
            return None
    if not isinstance(payload, dict):
        return None
    mode = str(payload.get("mode") or "").strip()
    if mode not in ROUTABLE_MODES:
        return None
    try:
        confidence = float(payload.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(1.0, max(0.0, confidence))
    reason = str(payload.get("reason") or "")[:200]
    return mode, confidence, reason


async def route_intent(
    *,
    query: str,
    user_id: str | None,
    session_id: str | None,
    db_session: AsyncSession | None,
) -> RouterDecision:
    """Classify a student message. Never raises; always returns a decision."""
    try:
        result = await complete_json_via_gateway(
            ctx=CallContext(
                feature_key=ROUTER_FEATURE,
                user_id=user_id,
                session_id=session_id,
                textbook_strict=False,
            ),
            messages=[
                {"role": "system", "content": _ROUTER_SYSTEM},
                {"role": "user", "content": query[:1500]},
            ],
            session=db_session,
        )
        parsed = _parse_llm_decision(result.content)
        if parsed is not None:
            mode, confidence, reason = parsed
            return RouterDecision(
                mode=mode,
                confidence=confidence,
                reason=reason or "طبقه‌بندی مدل",
                source="llm",
                audit_id=result.audit_id,
            )
        logger.warning("intent_router.invalid_output; using heuristic")
    except Exception:  # noqa: BLE001 - routing must never block the student
        logger.exception("intent_router.llm_failed; using heuristic")

    mode, reason = heuristic_mode(query)
    audit_id = await record_decision_audit(
        feature_key=ROUTER_FEATURE,
        user_id=user_id,
        session_id=session_id,
        request_text=query[:1500],
        decision={"mode": mode, "confidence": 0.4, "reason": reason, "source": "heuristic"},
        flag_reason="router_heuristic_fallback",
        session=db_session,
    )
    return RouterDecision(
        mode=mode, confidence=0.4, reason=reason, source="heuristic", audit_id=audit_id
    )
