"""Flashcard domain service (Phase 3): decks, cards, due queue, SM-2 reviews,
admin stats, and AI generation through the Shared Capability Runtime.

Generation path (all AI calls go through the runtime → ai_gateway):
  resolve server-owned sources → build numbered prompt → run_capability_json
  (capability + quota enforcement, audit row) → validate → persist cards with
  server-owned citations.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.flashcards import (
    Flashcard,
    FlashcardDeck,
    FlashcardReport,
    FlashcardReview,
    FlashcardStudySession,
    REPORT_REASONS,
    REPORT_STATUSES,
)
from app.services import capability_runtime
from app.services.flashcard_sources import ResolvedSources
from app.services.sm2 import SchedulerState, schedule_review

logger = logging.getLogger(__name__)

CAPABILITY_KEY = "flashcards"
EXPLAIN_FEATURE_KEY = "flashcards_explain"
MASTERED_INTERVAL_DAYS = 21

DIFFICULTIES: tuple[str, ...] = ("easy", "medium", "hard")
# NotebookLM-style Got it / Missed it → SM-2 quality ratings (1=فراموش کردم, 3=خوب).
GOT_RATING = 3
MISSED_RATING = 1
MAX_FOCUS_PROMPT_CHARS = 500

_DIFFICULTY_RULES: dict[str, str] = {
    "easy": (
        "سطح دشواری: آسان — اصطلاحات و تعاریف ساده، مفاهیم پایه، سؤال‌های مستقیم از متن، "
        "و پاسخ‌های کوتاه و قابل حفظ کردن بنویس."
    ),
    "medium": (
        "سطح دشواری: متوسط — مفاهیم اصلی مطلب را پوشش بده، روابط بین مطالب را بسنج، "
        "سؤال‌های مفهومی برای درک و یادآوری بساز."
    ),
    "hard": (
        "سطح دشواری: سخت — نکات عمیق‌تر مطلب را بپوشان، مفاهیم را با هم مقایسه کن، "
        "ارتباط چند مفهوم را بیار و سؤال‌هایی بنویس که فهم مطلب را بسنجد نه صرفاً حفظ کردن را."
    ),
}


# ---------------------------------------------------------------------------
# Structured model output
# ---------------------------------------------------------------------------


class GeneratedCard(BaseModel):
    front_md: str = Field(min_length=1, max_length=1200)
    back_md: str = Field(min_length=1, max_length=2000)
    hint_md: str = Field(default="", max_length=600)
    source_index: int = Field(ge=0)
    tags: list[str] = Field(default_factory=list, max_length=5)


class GeneratedCardSet(BaseModel):
    cards: list[GeneratedCard] = Field(min_length=1)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def build_generation_prompt(
    sources: ResolvedSources,
    count: int,
    *,
    difficulty: str = "medium",
    focus_prompt: str | None = None,
) -> str:
    lines = [
        f"تعداد کارت‌ها: {count}",
        _DIFFICULTY_RULES[difficulty],
        "منابع (فقط از همین‌ها کارت بساز؛ دانش بیرونی ممنوع):",
    ]
    for index, item in enumerate(sources.items):
        refs = "؛ ".join(c.get("citation", "") for c in item.citations)
        lines.append(f"\n[منبع {index}] ({refs})\n{item.text}")
    if focus_prompt and focus_prompt.strip():
        lines.append(
            "\nتمرکز درخواستی دانش‌آموز (دقیقاً همین را رعایت کن، اما فقط بر پایهٔ منابع بالا):\n"
            f"{focus_prompt.strip()}"
        )
    lines.append(
        "\nخروجی فقط یک JSON معتبر با این شکل باشد:\n"
        '{"cards":[{"front_md":"روی کارت","back_md":"پشت کارت","hint_md":"راهنما",'
        '"source_index":0,"tags":["برچسب"]}]}\n'
        "قواعد: source_index باید شمارهٔ یکی از منابع بالا باشد؛ "
        "فرمول‌ها را با LaTeX در علامت دلار ($...$) بنویس؛ متن فارسی را دقیق نگه دار."
    )
    return "\n".join(lines)


def default_deck_title(sources: ResolvedSources) -> str:
    return (sources.title_hint or "دستهٔ جدید")[:255]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_card(card: Flashcard, *, review: FlashcardReview | None = None) -> dict[str, Any]:
    return {
        "id": card.id,
        "deck_id": card.deck_id,
        "front_md": card.front_md,
        "back_md": card.back_md,
        "hint_md": card.hint_md or "",
        "citations": list(card.citations_json or []),
        "tags": list(card.tags_json or []),
        "review": serialize_review(review) if review else None,
    }


def serialize_review(review: FlashcardReview) -> dict[str, Any]:
    return {
        "ease_factor": review.ease_factor,
        "interval_days": review.interval_days,
        "repetitions": review.repetitions,
        "next_review_at": _utc(review.next_review_at).isoformat(),
        "last_rating": review.last_rating,
        "review_count": review.review_count,
    }


def serialize_report(report: FlashcardReport, *, card_front: str | None = None, user_name: str | None = None) -> dict[str, Any]:
    return {
        "id": report.id,
        "card_id": report.card_id,
        "user_id": report.user_id,
        "reason": report.reason,
        "note": report.note or "",
        "status": report.status,
        "created_at": _utc(report.created_at).isoformat() if report.created_at else None,
        "card_front": (card_front or "")[:120] or None,
        "user_name": user_name,
    }


def serialize_deck(deck: FlashcardDeck, *, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    stats = stats or {"total": 0, "due": 0, "mastered": 0, "new": 0, "last_review": None}
    total = stats["total"]
    last_review = stats.get("last_review")
    return {
        "id": deck.id,
        "title": deck.title,
        "book_id": deck.book_id,
        "chapter_number": deck.chapter_number,
        "page_start": deck.page_start,
        "page_end": deck.page_end,
        "source_type": deck.source_type,
        "is_public": bool(deck.is_public),
        "admin_approved": bool(deck.admin_approved),
        "created_at": deck.created_at.isoformat() if deck.created_at else None,
        "stats": {
            **stats,
            "last_review": _utc(last_review).isoformat() if last_review else None,
            "progress_percent": round(stats["mastered"] / total * 100, 1) if total else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------


async def get_owned_deck(session: AsyncSession, user: User, deck_id: int) -> FlashcardDeck:
    deck = await session.get(FlashcardDeck, deck_id)
    if deck is None or deck.user_id != user.id:
        raise HTTPException(status_code=404, detail="دسته یافت نشد.")
    return deck


async def get_owned_card(session: AsyncSession, user: User, card_id: int) -> tuple[Flashcard, FlashcardDeck]:
    card = await session.get(Flashcard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="کارت یافت نشد.")
    deck = await session.get(FlashcardDeck, card.deck_id)
    if deck is None or deck.user_id != user.id:
        raise HTTPException(status_code=404, detail="کارت یافت نشد.")
    return card, deck


# ---------------------------------------------------------------------------
# Decks & cards
# ---------------------------------------------------------------------------


async def deck_stats(session: AsyncSession, user_id: str, deck_ids: list[int], now: datetime) -> dict[int, dict[str, Any]]:
    """Per-deck totals computed for one user (new = no review row yet).

    ``last_review`` is the most recent real SM-2 review timestamp inside the
    deck (None when never studied) — read straight from the review rows.
    """
    out: dict[int, dict[str, Any]] = {
        d: {"total": 0, "due": 0, "mastered": 0, "new": 0, "last_review": None} for d in deck_ids
    }
    if not deck_ids:
        return out
    cards = list((await session.scalars(select(Flashcard).where(Flashcard.deck_id.in_(deck_ids)))).all())
    reviews = {
        r.card_id: r
        for r in (
            await session.scalars(
                select(FlashcardReview).where(
                    FlashcardReview.user_id == user_id,
                    FlashcardReview.card_id.in_([c.id for c in cards]) if cards else False,
                )
            )
        ).all()
    }
    for card in cards:
        bucket = out[card.deck_id]
        bucket["total"] += 1
        review = reviews.get(card.id)
        if review is None:
            bucket["new"] += 1
            bucket["due"] += 1
            continue
        if review.reviewed_at is not None and (
            bucket["last_review"] is None or _utc(review.reviewed_at) > bucket["last_review"]
        ):
            bucket["last_review"] = _utc(review.reviewed_at)
        if _utc(review.next_review_at) <= now:
            bucket["due"] += 1
        if review.interval_days >= MASTERED_INTERVAL_DAYS:
            bucket["mastered"] += 1
    return out


async def list_user_decks(session: AsyncSession, user: User, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    decks = list(
        (
            await session.scalars(
                select(FlashcardDeck).where(FlashcardDeck.user_id == user.id).order_by(FlashcardDeck.id.desc())
            )
        ).all()
    )
    stats = await deck_stats(session, user.id, [d.id for d in decks], now)
    return [serialize_deck(d, stats=stats[d.id]) for d in decks]


async def create_deck(
    session: AsyncSession,
    user: User,
    *,
    title: str,
    source_type: str = "manual",
    book_id: int | None = None,
    chapter_number: int | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
) -> FlashcardDeck:
    deck = FlashcardDeck(
        user_id=user.id,
        title=title.strip()[:255] or "دستهٔ جدید",
        source_type=source_type,
        book_id=book_id,
        chapter_number=chapter_number,
        page_start=page_start,
        page_end=page_end,
        is_public=False,
        admin_approved=False,
    )
    session.add(deck)
    await session.flush()
    return deck


async def deck_detail(session: AsyncSession, user: User, deck: FlashcardDeck, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cards = list(
        (await session.scalars(select(Flashcard).where(Flashcard.deck_id == deck.id).order_by(Flashcard.id))).all()
    )
    reviews = {
        r.card_id: r
        for r in (
            await session.scalars(
                select(FlashcardReview).where(
                    FlashcardReview.user_id == user.id,
                    FlashcardReview.card_id.in_([c.id for c in cards]) if cards else False,
                )
            )
        ).all()
    }
    stats = await deck_stats(session, user.id, [deck.id], now)
    return {
        **serialize_deck(deck, stats=stats[deck.id]),
        "cards": [serialize_card(c, review=reviews.get(c.id)) for c in cards],
    }


async def add_manual_card(
    session: AsyncSession,
    deck: FlashcardDeck,
    *,
    front_md: str,
    back_md: str,
    hint_md: str = "",
    tags: list[str] | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> Flashcard:
    card = Flashcard(
        deck_id=deck.id,
        front_md=front_md.strip(),
        back_md=back_md.strip(),
        hint_md=(hint_md or "").strip(),
        citations_json=list(citations or []),
        tags_json=list(tags or []),
    )
    session.add(card)
    await session.flush()
    return card


async def apply_review(
    session: AsyncSession, user: User, card: Flashcard, rating: int, now: datetime | None = None
) -> FlashcardReview:
    now = now or datetime.now(timezone.utc)
    review = await session.scalar(
        select(FlashcardReview).where(
            FlashcardReview.card_id == card.id, FlashcardReview.user_id == user.id
        )
    )
    state = (
        SchedulerState(review.ease_factor, review.interval_days, review.repetitions)
        if review is not None
        else SchedulerState()
    )
    result = schedule_review(state, rating, now)
    if review is None:
        review = FlashcardReview(card_id=card.id, user_id=user.id, review_count=0)
        session.add(review)
    review.ease_factor = result.ease_factor
    review.interval_days = result.interval_days
    review.repetitions = result.repetitions
    review.next_review_at = result.next_review_at
    review.last_rating = result.last_rating
    review.review_count = (review.review_count or 0) + 1
    review.reviewed_at = now
    await session.flush()
    return review


async def due_cards(session: AsyncSession, user: User, *, limit: int = 50, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    decks = {
        d.id: d
        for d in (await session.scalars(select(FlashcardDeck).where(FlashcardDeck.user_id == user.id))).all()
    }
    if not decks:
        return {"due_count": 0, "cards": []}
    cards = list(
        (await session.scalars(select(Flashcard).where(Flashcard.deck_id.in_(list(decks))))).all()
    )
    reviews = {
        r.card_id: r
        for r in (
            await session.scalars(
                select(FlashcardReview).where(
                    FlashcardReview.user_id == user.id,
                    FlashcardReview.card_id.in_([c.id for c in cards]) if cards else False,
                )
            )
        ).all()
    }
    due: list[tuple[datetime, Flashcard]] = []
    for card in cards:
        review = reviews.get(card.id)
        if review is None:
            due.append((datetime.min.replace(tzinfo=timezone.utc), card))  # new cards first
        elif _utc(review.next_review_at) <= now:
            due.append((_utc(review.next_review_at), card))
    due.sort(key=lambda item: (item[0], item[1].id))
    items = []
    for _, card in due[:limit]:
        payload = serialize_card(card, review=reviews.get(card.id))
        payload["deck_title"] = decks[card.deck_id].title
        items.append(payload)
    return {"due_count": len(due), "cards": items}


async def copy_public_deck(session: AsyncSession, user: User, source_deck: FlashcardDeck) -> FlashcardDeck:
    if not (source_deck.is_public and source_deck.admin_approved):
        raise HTTPException(status_code=404, detail="دستهٔ عمومی یافت نشد.")
    deck = await create_deck(
        session,
        user,
        title=source_deck.title,
        source_type=source_deck.source_type,
        book_id=source_deck.book_id,
        chapter_number=source_deck.chapter_number,
        page_start=source_deck.page_start,
        page_end=source_deck.page_end,
    )
    cards = list((await session.scalars(select(Flashcard).where(Flashcard.deck_id == source_deck.id))).all())
    for card in cards:
        await add_manual_card(
            session,
            deck,
            front_md=card.front_md,
            back_md=card.back_md,
            hint_md=card.hint_md,
            tags=list(card.tags_json or []),
            citations=list(card.citations_json or []),
        )
    return deck


async def library_decks(session: AsyncSession) -> list[dict[str, Any]]:
    decks = list(
        (
            await session.scalars(
                select(FlashcardDeck)
                .where(FlashcardDeck.is_public.is_(True), FlashcardDeck.admin_approved.is_(True))
                .order_by(FlashcardDeck.id.desc())
            )
        ).all()
    )
    out = []
    for deck in decks:
        count = await session.scalar(select(func.count(Flashcard.id)).where(Flashcard.deck_id == deck.id))
        payload = serialize_deck(deck)
        payload["stats"]["total"] = int(count or 0)
        out.append(payload)
    return out


# ---------------------------------------------------------------------------
# AI generation
# ---------------------------------------------------------------------------


async def generate_cards(
    session: AsyncSession,
    user: User,
    sources: ResolvedSources,
    *,
    count: int,
    deck_id: int | None,
    new_deck_title: str | None,
    difficulty: str = "medium",
    focus_prompt: str | None = None,
) -> dict[str, Any]:
    """Generate cards from resolved sources via the runtime (quota + audit + gateway).

    ``difficulty`` and ``focus_prompt`` genuinely steer the model prompt; the
    server-owned sources remain the only permitted material either way.
    """
    if deck_id is not None:
        deck = await get_owned_deck(session, user, deck_id)
    else:
        deck = None

    prompt = build_generation_prompt(sources, count, difficulty=difficulty, focus_prompt=focus_prompt)
    from app.services.learner_memory_service import build_memory_context

    memory_context = await build_memory_context(session, user.id, sources.book_id)
    try:
        result, _ = await capability_runtime.run_capability_json(
            extra_system=memory_context or None,
            session=session,
            capability_key=CAPABILITY_KEY,
            feature_key=CAPABILITY_KEY,
            user_text=prompt,
            user_id=user.id,
            user=user,
            book_id=sources.book_id,
            textbook_strict=True,
            citations=sources.all_citations,
            rag_hit_count=len(sources.items),
        )
    except HTTPException:
        raise  # capability / quota gate: rejected before any model call
    except Exception as error:  # noqa: BLE001 - never leak provider details
        # The gateway's audit row (error status) lives in this session: persist it.
        await session.commit()
        raise HTTPException(status_code=502, detail="تولید فلش‌کارت با خطا روبه‌رو شد. لطفاً دوباره تلاش کنید.") from error

    # Persist the audit row + quota usage before validating the output, so a
    # bad model response is still observable and counted.
    await session.commit()
    try:
        parsed = GeneratedCardSet.model_validate(result.content)
    except ValidationError as error:
        raise HTTPException(status_code=502, detail="پاسخ مدل برای فلش‌کارت معتبر نبود. لطفاً دوباره تلاش کنید.") from error

    valid = [c for c in parsed.cards if c.source_index < len(sources.items)][:count]
    if not valid:
        raise HTTPException(status_code=502, detail="هیچ کارت معتبر و مستندی تولید نشد. لطفاً دوباره تلاش کنید.")

    if deck is None:
        deck = await create_deck(
            session,
            user,
            title=(new_deck_title or default_deck_title(sources)),
            source_type=sources.source_type,
            book_id=sources.book_id,
            chapter_number=sources.chapter_number,
            page_start=sources.page_start,
            page_end=sources.page_end,
        )
    created: list[Flashcard] = []
    for card in valid:
        created.append(
            await add_manual_card(
                session,
                deck,
                front_md=card.front_md,
                back_md=card.back_md,
                hint_md=card.hint_md,
                tags=card.tags,
                # Citations are the server-owned source items, never model-written.
                citations=sources.items[card.source_index].citations,
            )
        )
    await session.commit()
    return {
        "deck_id": deck.id,
        "created_count": len(created),
        "requested_count": count,
        "audit_id": result.audit_id,
        "cards": [serialize_card(c) for c in created],
    }


# ---------------------------------------------------------------------------
# Study sessions (NotebookLM-style persistent progress)
# ---------------------------------------------------------------------------


def session_summary(study: FlashcardStudySession) -> dict[str, Any]:
    """Totals for the results screen, computed from the session's own results."""
    got = sum(1 for value in (study.results_json or {}).values() if value == "got")
    missed = sum(1 for value in (study.results_json or {}).values() if value == "missed")
    total = len(study.card_order_json or [])
    return {
        "total": total,
        "answered": got + missed,
        "got": got,
        "missed": missed,
        "percent": round(got / (got + missed) * 100, 1) if got + missed else 0.0,
        "status": study.status,
    }


def serialize_session(
    study: FlashcardStudySession,
    *,
    cards: list[Flashcard] | None = None,
    reviews: dict[int, FlashcardReview] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": study.id,
        "deck_id": study.deck_id,
        "mode": study.mode,
        "status": study.status,
        "position": study.position,
        "flipped": bool(study.flipped),
        "card_order": list(study.card_order_json or []),
        "results": dict(study.results_json or {}),
        "total_cards": study.total_cards,
        "summary": session_summary(study),
        "started_at": _utc(study.started_at).isoformat() if study.started_at else None,
        "last_activity_at": (
            _utc(study.last_activity_at).isoformat() if study.last_activity_at else None
        ),
        "completed_at": _utc(study.completed_at).isoformat() if study.completed_at else None,
    }
    if cards is not None:
        payload["cards"] = [
            serialize_card(card, review=(reviews or {}).get(card.id)) for card in cards
        ]
    return payload


async def _study_cards(session: AsyncSession, study: FlashcardStudySession) -> list[Flashcard]:
    """Cards of a session, ordered by the session's own card order."""
    order = [int(card_id) for card_id in (study.card_order_json or [])]
    if not order:
        return []
    rows = list(
        (await session.scalars(select(Flashcard).where(Flashcard.id.in_(order)))).all()
    )
    by_id = {card.id: card for card in rows}
    return [by_id[card_id] for card_id in order if card_id in by_id]


async def _study_reviews(
    session: AsyncSession, user: User, cards: list[Flashcard]
) -> dict[int, FlashcardReview]:
    if not cards:
        return {}
    rows = list(
        (
            await session.scalars(
                select(FlashcardReview).where(
                    FlashcardReview.user_id == user.id,
                    FlashcardReview.card_id.in_([c.id for c in cards]),
                )
            )
        ).all()
    )
    return {row.card_id: row for row in rows}


async def get_owned_study_session(
    session: AsyncSession, user: User, study_session_id: int
) -> FlashcardStudySession:
    study = await session.get(FlashcardStudySession, study_session_id)
    if study is None or study.user_id != user.id:
        raise HTTPException(status_code=404, detail="جلسهٔ مطالعه یافت نشد.")
    return study


async def close_deck_sessions(session: AsyncSession, user_id: str, deck_id: int) -> None:
    """Mark a deck's unfinished sessions as completed (kept for history, never deleted)."""
    rows = list(
        (
            await session.scalars(
                select(FlashcardStudySession).where(
                    FlashcardStudySession.user_id == user_id,
                    FlashcardStudySession.deck_id == deck_id,
                    FlashcardStudySession.status == "active",
                )
            )
        ).all()
    )
    now = datetime.now(timezone.utc)
    for study in rows:
        study.status = "completed"
        study.completed_at = study.completed_at or now


async def create_study_session(
    session: AsyncSession,
    user: User,
    deck: FlashcardDeck,
    *,
    mode: str,
    card_ids: list[int] | None = None,
    shuffle: bool = False,
    now: datetime | None = None,
) -> FlashcardStudySession:
    """Start a study run over a deck.

    - ``full``   → every card of the deck, deck order.
    - ``smart``  → only cards whose SM-2 due date has arrived (new cards included).
    - ``subset`` → explicit card list (validated to belong to this deck); used for
                   "same cards again" and "only missed" replays.
    """
    now = now or datetime.now(timezone.utc)
    deck_cards = list(
        (await session.scalars(select(Flashcard).where(Flashcard.deck_id == deck.id).order_by(Flashcard.id))).all()
    )
    if not deck_cards:
        raise HTTPException(status_code=422, detail="این دسته کارتی برای مطالعه ندارد.")

    if mode == "full":
        order = [card.id for card in deck_cards]
    elif mode == "smart":
        reviews = await _study_reviews(session, user, deck_cards)
        now_utc = now
        order = []
        for card in deck_cards:
            review = reviews.get(card.id)
            if review is None or _utc(review.next_review_at) <= now_utc:
                order.append(card.id)
        if not order:
            raise HTTPException(status_code=422, detail="در حال حاضر کارتی برای مرور هوشمند موعد ندارد.")
    elif mode == "subset":
        wanted: list[int] = []
        for card_id in card_ids or []:
            if card_id not in wanted:
                wanted.append(card_id)
        deck_card_ids = {card.id for card in deck_cards}
        unknown = [card_id for card_id in wanted if card_id not in deck_card_ids]
        if unknown or not wanted:
            raise HTTPException(status_code=422, detail="کارت‌های انتخابی متعلق به این دسته نیستند.")
        order = wanted
    else:  # pragma: no cover - guarded by Pydantic Literal
        raise HTTPException(status_code=422, detail="حالت مطالعه نامعتبر است.")

    if shuffle:
        random.shuffle(order)

    # One active run per deck: finishing/abandoning earlier runs keeps history readable.
    await close_deck_sessions(session, user.id, deck.id)
    study = FlashcardStudySession(
        user_id=user.id,
        deck_id=deck.id,
        mode=mode,
        status="active",
        position=0,
        card_order_json=order,
        results_json={},
        total_cards=len(order),
        started_at=now,
        last_activity_at=now,
    )
    session.add(study)
    await session.flush()
    return study


async def record_progress(
    session: AsyncSession,
    user: User,
    study: FlashcardStudySession,
    *,
    position: int,
    flipped: bool,
) -> FlashcardStudySession:
    """Persist navigation (current card index + answer-visibility) so reload resumes exactly."""
    order = list(study.card_order_json or [])
    if not order:
        raise HTTPException(status_code=422, detail="این جلسه کارتی برای مطالعه ندارد.")
    study.position = max(0, min(int(position), len(order) - 1))
    study.flipped = bool(flipped)
    study.last_activity_at = datetime.now(timezone.utc)
    await session.flush()
    return study


async def shuffle_study_session(
    session: AsyncSession, user: User, study: FlashcardStudySession
) -> FlashcardStudySession:
    """Re-order the session's cards in place; results and progress stay intact.

    The card the student is currently viewing keeps its position index, so the
    screen never jumps under them.
    """
    order = [int(card_id) for card_id in (study.card_order_json or [])]
    if len(order) < 2:
        return study
    current_card_id = order[study.position] if 0 <= study.position < len(order) else None
    random.shuffle(order)
    if current_card_id is not None and current_card_id in order:
        order.remove(current_card_id)
        order.insert(study.position, current_card_id)
    study.card_order_json = order
    study.last_activity_at = datetime.now(timezone.utc)
    await session.flush()
    return study


async def answer_study_card(
    session: AsyncSession,
    user: User,
    study: FlashcardStudySession,
    card: Flashcard,
    *,
    got: bool,
) -> dict[str, Any]:
    """Register Got it / Missed it for one card and feed SM-2 exactly once.

    Idempotent per session: re-answering a card that already has a result in this
    run never double-counts the SM-2 review or the session summary.
    """
    results = dict(study.results_json or {})
    key = str(card.id)
    existing = results.get(key)
    if existing is not None:
        existing_review = await session.scalar(
            select(FlashcardReview).where(
                FlashcardReview.card_id == card.id, FlashcardReview.user_id == user.id
            )
        )
        return {
            "result": existing,
            "already_recorded": True,
            "review": serialize_review(existing_review) if existing_review else None,
        }

    rating = GOT_RATING if got else MISSED_RATING
    review = await apply_review(session, user, card, rating)
    await record_review_outcomes(session, user, card, rating)
    results[key] = "got" if got else "missed"
    study.results_json = results
    study.last_activity_at = datetime.now(timezone.utc)

    # Advance to the next unanswered card (forward scan, wrapping around).
    order = [int(card_id) for card_id in (study.card_order_json or [])]
    try:
        current_index = order.index(card.id)
    except ValueError:
        current_index = max(0, min(study.position, len(order) - 1))
    next_index: int | None = None
    for step in range(1, len(order) + 1):
        candidate = (current_index + step) % len(order)
        if results.get(str(order[candidate])) is None:
            next_index = candidate
            break
    if next_index is None:
        study.status = "completed"
        study.completed_at = study.last_activity_at
        study.position = max(0, min(current_index, len(order) - 1))
    else:
        study.position = next_index
    await session.flush()
    return {
        "result": "got" if got else "missed",
        "already_recorded": False,
        "review": serialize_review(review),
    }


async def complete_study_session(
    session: AsyncSession, user: User, study: FlashcardStudySession
) -> FlashcardStudySession:
    study.status = "completed"
    study.completed_at = study.completed_at or datetime.now(timezone.utc)
    await session.flush()
    return study


async def active_study_session(
    session: AsyncSession,
    user: User,
    *,
    deck_id: int | None = None,
) -> FlashcardStudySession | None:
    """Most recent unfinished run of the user (optionally of one deck)."""
    query = select(FlashcardStudySession).where(
        FlashcardStudySession.user_id == user.id,
        FlashcardStudySession.status == "active",
    )
    if deck_id is not None:
        query = query.where(FlashcardStudySession.deck_id == deck_id)
    return await session.scalar(
        query.order_by(FlashcardStudySession.last_activity_at.desc()).limit(1)
    )


async def remove_card_from_sessions(session: AsyncSession, deck_id: int, card_id: int) -> None:
    """Drop a deleted card from every unfinished session of its deck.

    Positions shift so navigation stays consistent; a session that has run out of
    cards is marked completed instead of pointing at nothing.
    """
    rows = list(
        (
            await session.scalars(
                select(FlashcardStudySession).where(
                    FlashcardStudySession.deck_id == deck_id,
                    FlashcardStudySession.status == "active",
                )
            )
        ).all()
    )
    for study in rows:
        order = [int(value) for value in (study.card_order_json or [])]
        if card_id not in order:
            continue
        removed_index = order.index(card_id)
        order = [value for value in order if value != card_id]
        study.card_order_json = order
        results = {
            key: value
            for key, value in (study.results_json or {}).items()
            if key != str(card_id)
        }
        study.results_json = results
        study.total_cards = len(order)
        if not order:
            study.status = "completed"
            study.completed_at = study.completed_at or datetime.now(timezone.utc)
            study.position = 0
        else:
            if removed_index < study.position:
                study.position -= 1
            study.position = max(0, min(study.position, len(order) - 1))
        study.last_activity_at = datetime.now(timezone.utc)
    if rows:
        await session.flush()


async def full_session_payload(
    session: AsyncSession, user: User, study: FlashcardStudySession
) -> dict[str, Any]:
    """Session state plus its cards in session order (what the client renders)."""
    cards = await _study_cards(session, study)
    reviews = await _study_reviews(session, user, cards)
    return serialize_session(study, cards=cards, reviews=reviews)


async def study_session_detail(study: FlashcardStudySession) -> dict[str, Any]:
    """Lightweight session state (no cards) for progress/shuffle/complete calls."""
    return serialize_session(study)


# ---------------------------------------------------------------------------
# Explain (grounded, textbook-strict)
# ---------------------------------------------------------------------------


async def _explain_materials(
    session: AsyncSession, card: Flashcard
) -> tuple[list[str], list[dict[str, Any]], bool]:
    """Fetch the server-owned textbook text behind a card's citations.

    Returns ``(texts, citations, grounded_in_book)``. When the cited pages cannot
    be retrieved from the database, only the card's own stored content is used and
    ``grounded_in_book`` is False — the model is then told not to invent sources.
    """
    citations = list(card.citations_json or [])
    pairs: list[tuple[int, int]] = []
    for citation in citations:
        book_id, page_index = citation.get("book_id"), citation.get("pdf_page_index")
        if isinstance(book_id, int) and isinstance(page_index, int):
            pair = (book_id, page_index)
            if pair not in pairs:
                pairs.append(pair)
    texts: list[str] = []
    grounded = False
    if pairs:
        from app.models.curriculum import BookPage, PageStatus

        rows = list(
            (
                await session.scalars(
                    select(BookPage).where(
                        BookPage.book_id.in_({book_id for book_id, _ in pairs}),
                        BookPage.status.in_([PageStatus.done, PageStatus.needs_review]),
                    )
                )
            ).all()
        )
        wanted_pages = {page for _, page in pairs}
        for row in rows:
            if row.pdf_page_index not in wanted_pages:
                continue
            text = (row.markdown_content or "").strip()
            if text:
                texts.append(text[:MAX_BOOK_PAGE_CHARS])
                grounded = True
    return texts, citations, grounded


MAX_BOOK_PAGE_CHARS = 3000


def build_explain_prompt(
    card: Flashcard,
    texts: list[str],
    *,
    grounded: bool,
) -> str:
    lines = [
        "یک فلش‌کارت درسی را برای دانش‌آموز توضیح بده.",
        "",
        f"روی کارت: {card.front_md.strip()[:800]}",
        f"پشت کارت (پاسخ): {card.back_md.strip()[:1200]}",
    ]
    if (card.hint_md or "").strip():
        lines.append(f"راهنمای کارت: {card.hint_md.strip()[:400]}")
    if grounded and texts:
        lines.append("")
        lines.append("متن اصلی کتاب (فقط بر پایهٔ همین توضیح بده):")
        for index, text in enumerate(texts):
            lines.append(f"[صفحهٔ کتاب {index + 1}]\n{text}")
    else:
        lines.append("")
        lines.append(
            "متن اصلی صفحهٔ کتاب در دسترس نیست؛ فقط بر اساس محتوای ذخیره‌شدهٔ همین کارت توضیح بده "
            "و هیچ ارجاع یا صفحهٔ تازه‌ای ادعا نکن."
        )
    lines.append(
        "\nقواعد: توضیح را با زبان ساده و قابل فهم برای دانش‌آموز بنویس؛ در صورت نیاز یک مثال کوتاه بیار؛ "
        "فرمول‌ها را با LaTeX در علامت دلار ($...$) بنویس؛ از اطلاعات بیرونی از منابع بالا استفاده نکن؛ "
        "اگر به صفحهٔ کتاب اشاره می‌کنی فقط از ارجاع‌های کارت استفاده کن؛ "
        "حداکثر حدود ۲۵۰ کلمه؛ خروجی فقط متن توضیح باشد بدون سرصفحهٔ اضافه."
    )
    return "\n".join(lines)


async def explain_card(
    session: AsyncSession,
    user: User,
    card: Flashcard,
    deck: FlashcardDeck,
) -> dict[str, Any]:
    """Grounded supplementary explanation through the central runtime.

    The textbook pages are re-read from the server database; if they are not
    retrievable the explanation is limited to the card's stored content and no new
    citation is claimed. Capability flag, quota and audit all apply.
    """
    texts, citations, grounded = await _explain_materials(session, card)
    prompt = build_explain_prompt(card, texts, grounded=grounded)
    from app.services.learner_memory_service import build_memory_context

    memory_context = await build_memory_context(session, user.id, deck.book_id)
    try:
        result, _blocks, _skill = await capability_runtime.run_capability_text(
            extra_system=memory_context or None,
            session=session,
            capability_key=CAPABILITY_KEY,
            feature_key=EXPLAIN_FEATURE_KEY,
            user_text=prompt,
            user_id=user.id,
            user=user,
            book_id=deck.book_id,
            textbook_strict=True,
            citations=citations,
            rag_hit_count=len(texts) if grounded else 0,
        )
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001 - never leak provider details
        await session.commit()
        raise HTTPException(status_code=502, detail="تولید توضیح با خطا روبه‌رو شد. لطفاً دوباره تلاش کنید.") from error
    await session.commit()
    explanation = result.content if isinstance(result.content, str) else str(result.content)
    return {
        "explain_md": explanation.strip()[:6000],
        "audit_id": result.audit_id,
        "grounded_in_book": grounded,
        "citations": citations,
    }


# ---------------------------------------------------------------------------
# Review side effects (learner memory + mastery), shared by review endpoints
# ---------------------------------------------------------------------------


async def record_review_outcomes(
    session: AsyncSession, user: User, card: Flashcard, rating: int
) -> None:
    """Best-effort side effects of a review (never blocks the review itself)."""
    first = (card.citations_json or [{}])[0] if card.citations_json else {}
    from app.services.learner_memory_service import record_review_outcome

    try:
        await record_review_outcome(
            session,
            user_id=user.id,
            book_id=first.get("book_id"),
            chapter_number=first.get("chapter_number"),
            topic=first.get("chapter_title") or card.front_md[:60],
            correct=rating >= 3,
        )
    except Exception:  # noqa: BLE001 - memory is best-effort
        logger.exception("flashcards.memory_update_failed card=%s", card.id)
    try:
        from app.services import mastery_service

        if first.get("book_id") is not None:
            await mastery_service.record_component(
                session,
                user_id=user.id,
                book_id=int(first["book_id"]),
                chapter_number=first.get("chapter_number"),
                component="flash",
                correct=1 if rating >= 3 else 0,
                total=1,
            )
    except Exception:  # noqa: BLE001 - mastery is best-effort
        logger.exception("flashcards.mastery_update_failed card=%s", card.id)


# ---------------------------------------------------------------------------
# Card issue reports (Phase 3 redesign)
# ---------------------------------------------------------------------------
async def report_card(
    session: AsyncSession,
    user: User,
    card_id: int,
    *,
    reason: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Record a student issue report on an owned card (one open report per card)."""
    card, _deck = await get_owned_card(session, user, card_id)
    clean_reason = (reason or "").strip().lower()
    if clean_reason not in REPORT_REASONS:
        raise HTTPException(status_code=422, detail="دلیل گزارش معتبر نیست.")
    open_existing = await session.scalar(
        select(FlashcardReport).where(
            FlashcardReport.card_id == card.id,
            FlashcardReport.user_id == user.id,
            FlashcardReport.status == "open",
        )
    )
    if open_existing is not None:
        raise HTTPException(status_code=409, detail="گزارش بازی از این کارت دارید؛ در انتظار بررسی است.")
    row = FlashcardReport(card_id=card.id, user_id=user.id, reason=clean_reason, note=(note or "").strip()[:300])
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return serialize_report(row)


async def resolve_report(session: AsyncSession, report_id: int, *, status: str) -> dict[str, Any]:
    """Admin triage: mark a report resolved or dismissed (never deletes history)."""
    if status not in REPORT_STATUSES:
        raise HTTPException(status_code=422, detail="وضعیت گزارش معتبر نیست.")
    row = await session.get(FlashcardReport, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="گزارش یافت نشد.")
    row.status = status
    await session.commit()
    await session.refresh(row)
    return serialize_report(row)


async def admin_list_reports(
    session: AsyncSession, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Recent card reports with owner and card context for the admin triage queue."""
    query = select(FlashcardReport).order_by(FlashcardReport.id.desc()).limit(limit)
    if status:
        query = query.where(FlashcardReport.status == status)
    reports = list((await session.scalars(query)).all())
    out: list[dict[str, Any]] = []
    for row in reports:
        card = await session.get(Flashcard, row.card_id)
        user = await session.get(User, row.user_id)
        out.append(
            serialize_report(
                row,
                card_front=card.front_md if card else None,
                user_name=(user.full_name or user.phone_number) if user else None,
            )
        )
    return out


__all__ = [
    "CAPABILITY_KEY",
    "DIFFICULTIES",
    "EXPLAIN_FEATURE_KEY",
    "GOT_RATING",
    "GeneratedCardSet",
    "MISSED_RATING",
    "MAX_FOCUS_PROMPT_CHARS",
    "active_study_session",
    "add_manual_card",
    "answer_study_card",
    "apply_review",
    "build_explain_prompt",
    "build_generation_prompt",
    "close_deck_sessions",
    "complete_study_session",
    "copy_public_deck",
    "create_deck",
    "create_study_session",
    "deck_detail",
    "deck_stats",
    "due_cards",
    "explain_card",
    "full_session_payload",
    "generate_cards",
    "get_owned_card",
    "get_owned_deck",
    "get_owned_study_session",
    "library_decks",
    "list_user_decks",
    "record_progress",
    "record_review_outcomes",
    "remove_card_from_sessions",
    "report_card",
    "resolve_report",
    "admin_list_reports",
    "serialize_card",
    "serialize_deck",
    "serialize_report",
    "serialize_review",
    "serialize_session",
    "session_summary",
    "shuffle_study_session",
    "study_session_detail",
]
