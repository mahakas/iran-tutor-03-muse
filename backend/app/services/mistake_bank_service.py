"""Phase 5 mistake bank: automatic capture of wrong/skipped exam questions.

Lifecycle: `unresolved` -> (one correct practice answer) `practiced` -> (two
consecutive correct answers) `mastered`. A wrong practice answer resets to
`unresolved`. Practice never reveals the answer key before the student answers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.exam import ExamSession
from app.models.flashcards import FlashcardDeck
from app.models.phase5 import MISTAKE_STATUSES, MistakeBankItem
from app.services import flashcard_service as fs
from app.services import mastery_service

MISTAKE_DECK_TITLE = "اشتباهات من"
CHOICE_KEYS = ("A", "B", "C", "D")
ERROR_TAGS = ("wrong", "skipped")


def _apply_scope_filters(
    stmt,
    *,
    book_id: int | None,
    chapter_number: int | None,
    error_tag: str | None,
):
    """Shared optional scope filters for list and practice-set (backward compatible: all optional)."""
    if book_id is not None:
        stmt = stmt.where(MistakeBankItem.book_id == book_id)
    if chapter_number is not None:
        stmt = stmt.where(MistakeBankItem.chapter_number == chapter_number)
    if error_tag:
        stmt = stmt.where(MistakeBankItem.error_tag == error_tag)
    return stmt


def build_mistake_rows(
    *, user_id: str, exam: ExamSession, report: dict[str, Any], skip_question_ids: set[str]
) -> list[MistakeBankItem]:
    """Build (unsaved) rows for each wrong or skipped answer, skipping known questions."""
    questions = {q["id"]: q for q in (exam.questions or [])}
    created: list[MistakeBankItem] = []
    for item in report.get("by_question", []) or []:
        if item.get("correct"):
            continue
        question = questions.get(item.get("id"))
        if question is None or str(question["id"]) in skip_question_ids:
            continue
        source = dict(question.get("source") or {})
        answer = item.get("answer")
        row = MistakeBankItem(
            user_id=user_id,
            exam_id=exam.id,
            question_id=str(question["id"])[:32],
            book_id=exam.book_id,
            chapter_number=source.get("chapter_number"),
            chapter_title=source.get("chapter_title"),
            printed_page_number=source.get("printed_page_number"),
            topic_tag=str(source.get("chapter_title") or "عمومی")[:255],
            error_tag="skipped" if answer not in CHOICE_KEYS else "wrong",
            prompt=str(question.get("prompt") or ""),
            choices_json=dict(question.get("choices") or {}),
            correct_option=str(question.get("correct_option") or "A"),
            student_answer=answer if answer in CHOICE_KEYS else None,
            explanation=str(question.get("explanation") or ""),
            source_json=source,
            status="unresolved",
            correct_streak=0,
            attempts=0,
        )
        created.append(row)
    return created


async def record_exam_mistakes(
    session: AsyncSession, *, user_id: str, exam: ExamSession, report: dict[str, Any]
) -> int:
    """Insert missing mistake rows for this exam; existing rows are left untouched."""
    existing = set(
        (
            await session.scalars(
                select(MistakeBankItem.question_id).where(
                    MistakeBankItem.user_id == user_id, MistakeBankItem.exam_id == exam.id
                )
            )
        ).all()
    )
    rows = build_mistake_rows(user_id=user_id, exam=exam, report=report, skip_question_ids=existing)
    for row in rows:
        session.add(row)
    await session.flush()
    return len(rows)


def serialize_item(item: MistakeBankItem, *, reveal_answer: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": item.id,
        "exam_id": item.exam_id,
        "question_id": item.question_id,
        "book_id": item.book_id,
        "chapter_number": item.chapter_number,
        "chapter_title": item.chapter_title,
        "printed_page_number": item.printed_page_number,
        "topic_tag": item.topic_tag,
        "error_tag": item.error_tag,
        "prompt": item.prompt,
        "choices": dict(item.choices_json or {}),
        "status": item.status,
        "correct_streak": item.correct_streak,
        "attempts": item.attempts,
        "flashcard_card_id": item.flashcard_card_id,
        "citation": _citation_text(item),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
    if reveal_answer:
        payload["correct_option"] = item.correct_option
        payload["student_answer"] = item.student_answer
        payload["explanation"] = item.explanation
    return payload


def _citation_text(item: MistakeBankItem) -> str:
    chapter = item.chapter_title or (f"فصل {item.chapter_number}" if item.chapter_number else "فصل نامشخص")
    page = f"صفحه چاپی {item.printed_page_number}" if item.printed_page_number is not None else "صفحه نامشخص"
    return f"{chapter}، {page}"


async def _owned(session: AsyncSession, user: User, item_id: int) -> MistakeBankItem:
    item = await session.get(MistakeBankItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="مورد بانک اشتباهات یافت نشد.")
    return item


async def list_items(
    session: AsyncSession,
    user: User,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    book_id: int | None = None,
    chapter_number: int | None = None,
    error_tag: str | None = None,
) -> dict[str, Any]:
    if status is not None and status not in MISTAKE_STATUSES:
        raise HTTPException(status_code=422, detail="وضعیت نامعتبر است.")
    if error_tag is not None and error_tag not in ERROR_TAGS:
        raise HTTPException(status_code=422, detail="نوع خطا نامعتبر است.")
    scope = dict(book_id=book_id, chapter_number=chapter_number, error_tag=error_tag)
    stmt = _apply_scope_filters(
        select(MistakeBankItem).where(MistakeBankItem.user_id == user.id), **scope
    )
    count_stmt = _apply_scope_filters(
        select(func.count()).select_from(MistakeBankItem).where(MistakeBankItem.user_id == user.id),
        **scope,
    )
    if status:
        stmt = stmt.where(MistakeBankItem.status == status)
        count_stmt = count_stmt.where(MistakeBankItem.status == status)
    rows = (
        await session.scalars(
            stmt.order_by(MistakeBankItem.created_at.desc(), MistakeBankItem.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    # Per-status counts stay scoped to the same book/chapter/error-tag filter, so the
    # status chips stay meaningful inside a filtered view.
    counts = {
        key: int(
            await session.scalar(
                _apply_scope_filters(
                    select(func.count()).select_from(MistakeBankItem).where(
                        MistakeBankItem.user_id == user.id, MistakeBankItem.status == key
                    ),
                    **scope,
                )
            )
            or 0
        )
        for key in MISTAKE_STATUSES
    }
    return {
        "total": int(await session.scalar(count_stmt) or 0),
        "counts": counts,
        "items": [serialize_item(row) for row in rows],
    }


async def practice_set(
    session: AsyncSession,
    user: User,
    *,
    limit: int = 5,
    book_id: int | None = None,
    chapter_number: int | None = None,
    error_tag: str | None = None,
) -> dict[str, Any]:
    """Unresolved items first, then practiced ones. Answer keys are not included."""
    if error_tag is not None and error_tag not in ERROR_TAGS:
        raise HTTPException(status_code=422, detail="نوع خطا نامعتبر است.")
    stmt = _apply_scope_filters(
        select(MistakeBankItem)
        .where(MistakeBankItem.user_id == user.id, MistakeBankItem.status != "mastered"),
        book_id=book_id,
        chapter_number=chapter_number,
        error_tag=error_tag,
    )
    rows = (
        await session.scalars(
            stmt.order_by(
                (MistakeBankItem.status == "practiced").asc(),
                MistakeBankItem.created_at.asc(),
                MistakeBankItem.id.asc(),
            )
            .limit(limit)
        )
    ).all()
    return {"items": [serialize_item(row) for row in rows]}


async def answer_item(session: AsyncSession, user: User, item_id: int, choice: str) -> dict[str, Any]:
    item = await _owned(session, user, item_id)
    choice = (choice or "").upper()
    if choice not in CHOICE_KEYS:
        raise HTTPException(status_code=422, detail="گزینه باید A، B، C یا D باشد.")
    correct = choice == item.correct_option
    item.attempts = int(item.attempts or 0) + 1
    item.student_answer = choice
    if correct:
        item.correct_streak = int(item.correct_streak or 0) + 1
        item.status = "mastered" if item.correct_streak >= 2 else "practiced"
    else:
        item.correct_streak = 0
        item.status = "unresolved"
    item.updated_at = datetime.now(timezone.utc)
    if item.chapter_number is not None and item.book_id is not None:
        await mastery_service.record_component(
            session,
            user_id=user.id,
            book_id=item.book_id,
            chapter_number=item.chapter_number,
            component="exam",
            correct=1 if correct else 0,
            total=1,
        )
    await session.commit()
    return {
        "correct": correct,
        "correct_option": item.correct_option,
        "explanation": item.explanation,
        "status": item.status,
        "correct_streak": item.correct_streak,
        "item": serialize_item(item),
    }


async def send_to_flashcards(session: AsyncSession, user: User, item_id: int) -> dict[str, Any]:
    """Create one flashcard for the item (idempotent) in the student's mistake deck."""
    item = await _owned(session, user, item_id)
    if item.flashcard_card_id is not None:
        return {"card_id": item.flashcard_card_id, "created": False, "item": serialize_item(item)}
    deck = await session.scalar(
        select(FlashcardDeck).where(
            FlashcardDeck.user_id == user.id,
            FlashcardDeck.title == MISTAKE_DECK_TITLE,
            FlashcardDeck.source_type == "mistake_bank",
        )
    )
    if deck is None:
        deck = await fs.create_deck(session, user, title=MISTAKE_DECK_TITLE, source_type="mistake_bank")
    answer_text = dict(item.choices_json or {}).get(item.correct_option, "")
    citation = dict(item.source_json or {})
    card = await fs.add_manual_card(
        session,
        deck,
        front_md=item.prompt,
        back_md=f"پاسخ درست: {item.correct_option}) {answer_text}\n\n{item.explanation}".strip(),
        hint_md=_citation_text(item),
        tags=[item.topic_tag] if item.topic_tag else [],
        citations=[citation] if citation else [],
    )
    item.flashcard_card_id = card.id
    item.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"card_id": card.id, "created": True, "item": serialize_item(item)}
