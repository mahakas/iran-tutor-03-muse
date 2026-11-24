"""Three-layer learner memory (Phase 4).

L1 - session trace: short sliding window of recent turns in one chat session.
L2 - per (book, chapter) facts: mastered topics, weak spots, notes. Extracted
     asynchronously after a chat/quiz/flashcard interaction through the AI
     gateway (feature `memory`, fully audited). Admin-edited rows keep the
     admin's wording; later evidence only raises `evidence_count`.
L3 - longitudinal profile: deterministic roll-up of L2 (no extra model call).

Memory is learner state, never textbook evidence: it is injected as a
personalisation hint and is never cited as a source.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.curriculum import Book
from app.models.learner_memory import LearnerMemory
from app.services.ai_gateway import CallContext, complete_json_via_gateway

logger = logging.getLogger(__name__)

L1_WINDOW = 12
L2_CONTEXT_LIMIT = 8
L2_KINDS = ("mastered", "weak", "note")
PROFILE_TOPIC_KEY = "profile"
MEMORY_FEATURE = "memory"

_EXTRACT_SYSTEM = (
    "تو موتور حافظهٔ آموزشی هستی. از گفت‌وگوی دانش‌آموز، حداکثر ۳ واقعیت یادگیری "
    "کوتاه و مشخص استخراج کن. فقط JSON با کلیدهای facts برگردان؛ هر fact شامل: "
    '"kind" (mastered|weak|note)، "topic" (عنوان کوتاه)، "chapter_number" (عدد یا null)، '
    '"fact_fa" (یک جمله فارسی). اگر چیزی قابل‌یادگیری نبود، facts را خالی بگذار. '
    "دانش بیرونی وارد نکن."
)


def _slug(topic: str) -> str:
    cleaned = re.sub(r"\s+", " ", topic.strip())[:120]
    return cleaned.casefold()


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# L1 - session trace
# ---------------------------------------------------------------------------
async def record_l1_turn(
    session: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    book_id: int | None,
    mode: str,
    query: str,
    answer_excerpt: str,
) -> None:
    session.add(
        LearnerMemory(
            user_id=user_id,
            layer="L1",
            kind="turn",
            book_id=book_id,
            session_id=session_id,
            content_fa=f"سؤال: {query[:300]} | پاسخ: {answer_excerpt[:300]}",
            source_type="chat",
            created_by="system",
            data_json={"mode": mode},
        )
    )
    await session.flush()
    # Keep only the newest L1_WINDOW turns of this session.
    keep_ids = list(
        await session.scalars(
            select(LearnerMemory.id)
            .where(
                LearnerMemory.user_id == user_id,
                LearnerMemory.layer == "L1",
                LearnerMemory.session_id == session_id,
            )
            .order_by(LearnerMemory.id.desc())
            .limit(L1_WINDOW)
        )
    )
    if keep_ids:
        await session.execute(
            delete(LearnerMemory).where(
                LearnerMemory.user_id == user_id,
                LearnerMemory.layer == "L1",
                LearnerMemory.session_id == session_id,
                LearnerMemory.id.not_in(keep_ids),
            )
        )


# ---------------------------------------------------------------------------
# L2 - per book/chapter facts
# ---------------------------------------------------------------------------
async def upsert_l2_fact(
    session: AsyncSession,
    *,
    user_id: str,
    kind: str,
    topic: str,
    content_fa: str,
    book_id: int | None,
    chapter_number: int | None,
    session_id: str | None,
    source_type: str,
    created_by: str = "system",
) -> LearnerMemory:
    if kind not in L2_KINDS:
        kind = "note"
    topic_key = _slug(topic) or "general"
    existing = await session.scalar(
        select(LearnerMemory).where(
            LearnerMemory.user_id == user_id,
            LearnerMemory.layer == "L2",
            LearnerMemory.book_id == book_id,
            LearnerMemory.chapter_number == chapter_number,
            LearnerMemory.topic_key == topic_key,
        )
    )
    if existing is None:
        row = LearnerMemory(
            user_id=user_id,
            layer="L2",
            kind=kind,
            book_id=book_id,
            chapter_number=chapter_number,
            session_id=session_id,
            topic_key=topic_key,
            content_fa=content_fa[:1000],
            evidence_count=1,
            source_type=source_type,
            created_by=created_by,
            data_json={"topic": topic[:120]},
        )
        session.add(row)
        await session.flush()
        return row

    existing.evidence_count = (existing.evidence_count or 0) + 1
    existing.session_id = session_id or existing.session_id
    existing.source_type = source_type
    existing.kind = kind
    # Admin wording is authoritative: never overwrite an admin-edited fact.
    if not existing.edited_by_admin:
        existing.content_fa = content_fa[:1000]
    existing.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return existing


async def extract_l2_from_turn(
    *,
    user_id: str,
    session_id: str | None,
    book_id: int | None,
    chapter_number: int | None,
    query: str,
    answer: str,
    source_type: str = "chat",
) -> int:
    """Background job: ask the `memory` route for facts, then upsert L2 rows.

    Runs in its own DB session so a failure never affects the student response.
    Returns the number of facts written.
    """
    if not query.strip():
        return 0
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM},
        {
            "role": "user",
            "content": f"سؤال دانش‌آموز:\n{query[:1500]}\n\nپاسخ:\n{answer[:2500]}",
        },
    ]
    try:
        async with async_session_factory() as db:
            result = await complete_json_via_gateway(
                ctx=CallContext(
                    feature_key=MEMORY_FEATURE,
                    user_id=user_id,
                    session_id=session_id,
                    book_id=book_id,
                    textbook_strict=False,
                ),
                messages=messages,
                session=db,
            )
            facts = _parse_facts(result.content)
            written = 0
            for fact in facts:
                await upsert_l2_fact(
                    db,
                    user_id=user_id,
                    kind=fact["kind"],
                    topic=fact["topic"],
                    content_fa=fact["fact_fa"],
                    book_id=book_id,
                    chapter_number=fact.get("chapter_number") or chapter_number,
                    session_id=session_id,
                    source_type=source_type,
                )
                written += 1
            if written:
                await rebuild_l3_profile(db, user_id)
            await db.commit()
            return written
    except Exception:  # noqa: BLE001 - memory is best-effort
        logger.exception("learner_memory.extract_failed user=%s", user_id)
        return 0


def _parse_facts(content: Any) -> list[dict[str, Any]]:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", text or "", re.S)
        if not match:
            return []
        try:
            payload = json.loads(match.group(0))
        except ValueError:
            return []
    raw = payload.get("facts") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    facts: list[dict[str, Any]] = []
    for item in raw[:3]:
        if not isinstance(item, dict):
            continue
        fact_fa = str(item.get("fact_fa") or "").strip()
        topic = str(item.get("topic") or "").strip()
        if not fact_fa or not topic:
            continue
        chapter = item.get("chapter_number")
        facts.append(
            {
                "kind": str(item.get("kind") or "note"),
                "topic": topic,
                "fact_fa": fact_fa,
                "chapter_number": int(chapter) if isinstance(chapter, int) else None,
            }
        )
    return facts


async def record_quiz_outcome(
    session: AsyncSession,
    *,
    user_id: str,
    book_id: int,
    chapter_number: int | None,
    topic: str,
    correct: int,
    total: int,
    source_type: str = "quiz",
) -> LearnerMemory | None:
    """Deterministic L2 update from a quiz/flashcard result (no LLM needed)."""
    if total <= 0:
        return None
    ratio = correct / total
    kind = "mastered" if ratio >= 0.8 else "weak" if ratio < 0.5 else "note"
    content = f"نتیجهٔ {correct} از {total} در «{topic[:80]}»."
    row = await upsert_l2_fact(
        session,
        user_id=user_id,
        kind=kind,
        topic=topic,
        content_fa=content,
        book_id=book_id,
        chapter_number=chapter_number,
        session_id=None,
        source_type=source_type,
    )
    await rebuild_l3_profile(session, user_id)
    return row


# ---------------------------------------------------------------------------
# L3 - longitudinal profile
# ---------------------------------------------------------------------------
async def rebuild_l3_profile(session: AsyncSession, user_id: str) -> LearnerMemory:
    l2_rows = (
        await session.scalars(
            select(LearnerMemory).where(
                LearnerMemory.user_id == user_id, LearnerMemory.layer == "L2"
            )
        )
    ).all()
    book_ids = {row.book_id for row in l2_rows if row.book_id is not None}
    book_titles: dict[int, str] = {}
    if book_ids:
        for book_id, title in (
            await session.execute(select(Book.id, Book.title).where(Book.id.in_(book_ids)))
        ).all():
            book_titles[book_id] = title

    weak = sorted((r for r in l2_rows if r.kind == "weak"), key=lambda r: -r.evidence_count)[:5]
    mastered = sorted((r for r in l2_rows if r.kind == "mastered"), key=lambda r: -r.evidence_count)[:5]
    chapters = {(r.book_id, r.chapter_number) for r in l2_rows if r.chapter_number is not None}
    total_evidence = sum(r.evidence_count or 0 for r in l2_rows)

    lines: list[str] = []
    if mastered:
        lines.append("مسلط‌تر: " + "؛ ".join(r.topic_key for r in mastered))
    if weak:
        lines.append("نیازمند تمرین بیشتر: " + "؛ ".join(r.topic_key for r in weak))
    if chapters:
        lines.append(f"فصل‌های بررسی‌شده: {len(chapters)} فصل در {len(book_ids)} کتاب")
    if not lines:
        lines.append("هنوز داده‌ای برای پروفایل یادگیری جمع نشده است.")
    summary = " | ".join(lines)

    profile = await session.scalar(
        select(LearnerMemory).where(
            LearnerMemory.user_id == user_id,
            LearnerMemory.layer == "L3",
            LearnerMemory.topic_key == PROFILE_TOPIC_KEY,
        )
    )
    data = {
        "chapters_seen": len(chapters),
        "books": [{"book_id": b, "title": book_titles.get(b)} for b in sorted(book_ids)],
        "weak_topics": [r.topic_key for r in weak],
        "mastered_topics": [r.topic_key for r in mastered],
        "total_evidence": total_evidence,
    }
    if profile is None:
        profile = LearnerMemory(
            user_id=user_id,
            layer="L3",
            kind="profile",
            topic_key=PROFILE_TOPIC_KEY,
            content_fa=summary,
            source_type="rollup",
            created_by="system",
            data_json=data,
        )
        session.add(profile)
    else:
        profile.data_json = data
        profile.updated_at = datetime.now(timezone.utc)
        if not profile.edited_by_admin:
            profile.content_fa = summary
    await session.flush()
    return profile


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------
async def build_memory_context(
    session: AsyncSession | None, user_id: str | None, book_id: int | None
) -> str:
    """Compact learner-state block for the capability runtime system prompt."""
    if session is None or not user_id:
        return ""
    try:
        profile = await session.scalar(
            select(LearnerMemory).where(
                LearnerMemory.user_id == user_id,
                LearnerMemory.layer == "L3",
                LearnerMemory.topic_key == PROFILE_TOPIC_KEY,
            )
        )
        l2_query = select(LearnerMemory).where(
            LearnerMemory.user_id == user_id, LearnerMemory.layer == "L2"
        )
        if book_id is not None:
            l2_query = l2_query.where(LearnerMemory.book_id == book_id)
        l2_rows = (
            await session.scalars(
                l2_query.order_by(LearnerMemory.evidence_count.desc(), LearnerMemory.updated_at.desc())
                .limit(L2_CONTEXT_LIMIT)
            )
        ).all()
    except Exception:  # noqa: BLE001 - memory must never break answering
        logger.exception("learner_memory.context_failed user=%s", user_id)
        return ""

    if profile is None and not l2_rows:
        return ""
    lines = [
        "حافظهٔ یادگیرنده (فقط برای شخصی‌سازی پاسخ؛ منبع درسی نیست و نباید استناد شود):"
    ]
    if profile is not None and profile.content_fa:
        lines.append(f"- پروفایل: {profile.content_fa}")
    for row in l2_rows:
        chapter = f"فصل {row.chapter_number}" if row.chapter_number is not None else "کلی"
        lines.append(f"- [{chapter}] {row.content_fa}")
    return "\n".join(lines)


def serialize_memory(row: LearnerMemory) -> dict[str, Any]:
    return {
        "id": row.id,
        "layer": row.layer,
        "kind": row.kind,
        "book_id": row.book_id,
        "chapter_number": row.chapter_number,
        "session_id": row.session_id,
        "topic_key": row.topic_key,
        "content_fa": row.content_fa,
        "evidence_count": row.evidence_count,
        "source_type": row.source_type,
        "created_by": row.created_by,
        "edited_by_admin": bool(row.edited_by_admin),
        "data": row.data_json or {},
        "created_at": _utc(row.created_at).isoformat(),
        "updated_at": _utc(row.updated_at).isoformat(),
    }


async def memory_counts(session: AsyncSession, user_id: str) -> dict[str, int]:
    rows = (
        await session.execute(
            select(LearnerMemory.layer, func.count())
            .where(LearnerMemory.user_id == user_id)
            .group_by(LearnerMemory.layer)
        )
    ).all()
    counts = {"L1": 0, "L2": 0, "L3": 0}
    for layer, count in rows:
        counts[layer] = int(count)
    return counts


async def record_review_outcome(
    session: AsyncSession,
    *,
    user_id: str,
    book_id: int | None,
    chapter_number: int | None,
    topic: str,
    correct: bool,
) -> LearnerMemory | None:
    """Flashcard review -> cumulative L2 topic tally (stable, not per-card flip-flop).

    Counts live in `data_json` so repeated reviews converge: >=80% correct is
    `mastered`, <50% is `weak`, otherwise `note`. Admin-edited wording is kept.
    """
    topic_key = _slug(topic) or "general"
    row = await session.scalar(
        select(LearnerMemory).where(
            LearnerMemory.user_id == user_id,
            LearnerMemory.layer == "L2",
            LearnerMemory.book_id == book_id,
            LearnerMemory.chapter_number == chapter_number,
            LearnerMemory.topic_key == topic_key,
        )
    )
    correct_total = int((row.data_json or {}).get("review_correct", 0)) if row else 0
    total = int((row.data_json or {}).get("review_total", 0)) if row else 0
    correct_total += 1 if correct else 0
    total += 1
    ratio = correct_total / total
    kind = "mastered" if ratio >= 0.8 else "weak" if ratio < 0.5 else "note"
    summary = f"در مرورهای فلش‌کارت {correct_total} از {total} پاسخ درست بوده است."
    row = await upsert_l2_fact(
        session,
        user_id=user_id,
        kind=kind,
        topic=topic,
        content_fa=summary,
        book_id=book_id,
        chapter_number=chapter_number,
        session_id=None,
        source_type="flashcard",
    )
    row.data_json = {
        **(row.data_json or {}),
        "review_correct": correct_total,
        "review_total": total,
    }
    await rebuild_l3_profile(session, user_id)
    return row
