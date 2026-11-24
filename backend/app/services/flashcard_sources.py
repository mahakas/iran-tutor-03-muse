"""Server-owned source resolution for flashcard generation (Phase 3).

Three sources are supported. In every case the text and its textbook citations
are read from the database on the server, never from the client:

(a) ``book``    — chapter and/or printed-page range of an ingested book (page rows).
(b) ``chat``    — selected messages of one of the student's own chat sessions. Only
                  messages that carry textbook citations are used, so every card can
                  point back to a book page.
(c) ``mistake`` — wrong answers from one of the student's own exam sessions.

Each resolved item becomes one numbered source in the generation prompt; the
model may only reference these numbers, which prevents invented citations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession
from app.models.curriculum import Book, BookPage, PageStatus
from app.models.exam import ExamSession
from app.services.tutor_service import _source_reference

MAX_BOOK_PAGES = 8
MAX_CHAT_MESSAGES = 10
MAX_TEXT_CHARS = 4000
_CITATION_KEYS = (
    "book_id",
    "book_title",
    "grade_number",
    "chapter_number",
    "chapter_title",
    "pdf_page_index",
    "printed_page_number",
)


@dataclass
class SourceItem:
    text: str
    citations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ResolvedSources:
    source_type: str
    items: list[SourceItem]
    book_id: int | None = None
    chapter_number: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    title_hint: str = ""

    @property
    def all_citations(self) -> list[dict[str, Any]]:
        seen: set[tuple[Any, Any]] = set()
        out: list[dict[str, Any]] = []
        for item in self.items:
            for citation in item.citations:
                key = (citation.get("book_id"), citation.get("pdf_page_index"))
                if key in seen:
                    continue
                seen.add(key)
                out.append(citation)
        return out


def normalize_citation(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only the server-known citation fields and add the Persian reference."""
    payload = {key: raw.get(key) for key in _CITATION_KEYS}
    payload["citation"] = _source_reference(raw)
    return payload


async def resolve_book_source(
    session: AsyncSession,
    *,
    book: Book,
    chapter_number: int | None,
    page_start: int | None,
    page_end: int | None,
) -> ResolvedSources:
    if chapter_number is None and page_start is None:
        raise HTTPException(status_code=422, detail="فصل یا بازهٔ صفحه را مشخص کنید.")
    if page_start is not None and page_end is not None and page_end < page_start:
        raise HTTPException(status_code=422, detail="بازهٔ صفحه نامعتبر است.")

    query = select(BookPage).where(
        BookPage.book_id == book.id,
        BookPage.status.in_([PageStatus.done, PageStatus.needs_review]),
    )
    if chapter_number is not None:
        query = query.where(BookPage.chapter_number == chapter_number)
    if page_start is not None:
        query = query.where(BookPage.pdf_page_index >= page_start)
    if page_end is not None:
        query = query.where(BookPage.pdf_page_index <= page_end)
    rows = list((await session.scalars(query.order_by(BookPage.pdf_page_index.asc()))).all())
    rows = [row for row in rows if (row.markdown_content or "").strip()]
    if not rows:
        raise HTTPException(
            status_code=422,
            detail="در این فصل یا بازهٔ صفحه، متن تأییدشده‌ای برای ساخت فلش‌کارت پیدا نشد.",
        )
    if len(rows) > MAX_BOOK_PAGES:
        raise HTTPException(
            status_code=422,
            detail=f"این بازه {len(rows)} صفحه دارد؛ حداکثر {MAX_BOOK_PAGES} صفحه مجاز است. بازه را کوچک‌تر کنید.",
        )

    items: list[SourceItem] = []
    for row in rows:
        citation = normalize_citation(
            {
                "book_id": book.id,
                "book_title": book.title,
                "grade_number": None,
                "chapter_number": row.chapter_number,
                "chapter_title": row.chapter_title,
                "pdf_page_index": row.pdf_page_index,
                "printed_page_number": row.printed_page_number,
            }
        )
        items.append(
            SourceItem(text=row.markdown_content.strip()[:MAX_TEXT_CHARS], citations=[citation])
        )
    first, last = rows[0], rows[-1]
    chapter = chapter_number if chapter_number is not None else first.chapter_number
    title_hint = f"{book.title} — فصل {chapter}" if chapter is not None else f"{book.title} — صفحه‌های {first.pdf_page_index}–{last.pdf_page_index}"
    return ResolvedSources(
        source_type="book",
        items=items,
        book_id=book.id,
        chapter_number=chapter,
        page_start=first.printed_page_number,
        page_end=last.printed_page_number,
        title_hint=title_hint,
    )


async def resolve_chat_source(
    session: AsyncSession,
    *,
    user_id: str,
    chat_session_id: str,
    message_ids: list[str],
) -> ResolvedSources:
    """Resolve chat messages. Client-written message text is used only as the
    body of the card; every citation is re-validated against ``book_pages`` on
    the server and rebuilt from the database row. Unverifiable citations are
    dropped, and messages without any verified citation are rejected."""
    chat = await session.get(ChatSession, chat_session_id)
    if chat is None or chat.user_id != user_id:
        raise HTTPException(status_code=404, detail="گفت‌وگو یافت نشد.")
    if not message_ids or len(set(message_ids)) > MAX_CHAT_MESSAGES:
        raise HTTPException(status_code=422, detail=f"بین ۱ تا {MAX_CHAT_MESSAGES} پیام انتخاب کنید.")
    by_id = {str(message.get("id")): message for message in (chat.messages or [])}
    missing = [mid for mid in message_ids if mid not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail="برخی پیام‌های انتخابی در این گفت‌وگو نیستند.")

    candidates: list[tuple[str, dict[str, Any]]] = []
    for mid in message_ids:
        message = by_id[mid]
        content = str(message.get("content") or "").strip()
        for source in message.get("sources") or []:
            if isinstance(source, dict) and source.get("pdf_page_index") is not None:
                candidates.append((content, source))

    pairs = {
        (int(src["book_id"]), int(src["pdf_page_index"]))
        for _, src in candidates
        if src.get("book_id") is not None
    }
    verified: dict[tuple[int, int], BookPage] = {}
    if pairs:
        rows = (
            await session.scalars(
                select(BookPage).where(
                    BookPage.book_id.in_({b for b, _ in pairs}),
                    BookPage.pdf_page_index.in_({p for _, p in pairs}),
                )
            )
        ).all()
        verified = {(row.book_id, row.pdf_page_index): row for row in rows}

    items: list[SourceItem] = []
    used_message_ids: set[str] = set()
    for mid in message_ids:
        message = by_id[mid]
        content = str(message.get("content") or "").strip()
        citations: list[dict[str, Any]] = []
        for source in message.get("sources") or []:
            if not isinstance(source, dict) or source.get("book_id") is None or source.get("pdf_page_index") is None:
                continue
            row = verified.get((int(source["book_id"]), int(source["pdf_page_index"])))
            if row is None:
                continue  # not a real page of the textbook → never cite it
            citations.append(
                normalize_citation(
                    {
                        "book_id": row.book_id,
                        "book_title": await _book_title(session, row.book_id),
                        "chapter_number": row.chapter_number,
                        "chapter_title": row.chapter_title,
                        "pdf_page_index": row.pdf_page_index,
                        "printed_page_number": row.printed_page_number,
                    }
                )
            )
        if not content or not citations:
            continue  # ungrounded messages are never turned into cards
        items.append(SourceItem(text=content[:MAX_TEXT_CHARS], citations=citations))
        used_message_ids.add(mid)
    if not items:
        raise HTTPException(
            status_code=422,
            detail="پیام‌های انتخابی به صفحهٔ معتبری از کتاب ارجاع ندارند؛ فقط پاسخ‌های مستند قابل تبدیل هستند.",
        )
    return ResolvedSources(
        source_type="chat",
        items=items,
        book_id=chat.book_id,
        title_hint=f"گفت‌وگو: {chat.title}",
    )


async def _book_title(session: AsyncSession, book_id: int) -> str:
    title = await session.scalar(select(Book.title).where(Book.id == book_id))
    return title or "کتاب درسی"


async def resolve_mistake_source(
    session: AsyncSession,
    *,
    user_id: str,
    exam_id: str,
    question_ids: list[str] | None,
) -> ResolvedSources:
    exam = await session.get(ExamSession, exam_id)
    if exam is None or exam.user_id != user_id:
        raise HTTPException(status_code=404, detail="آزمون یافت نشد.")
    report = exam.report_card or {}
    wrong = [
        row
        for row in (report.get("by_question") or [])
        if row.get("answer") is not None and not row.get("correct")
    ]
    if question_ids is not None:
        wanted = set(question_ids)
        wrong = [row for row in wrong if row.get("id") in wanted]
    if not wrong:
        raise HTTPException(status_code=422, detail="پاسخ نادرست قابل‌استفاده‌ای در این آزمون پیدا نشد.")
    questions = {str(q.get("id")): q for q in (exam.questions or [])}

    items: list[SourceItem] = []
    for row in wrong[:MAX_CHAT_MESSAGES]:
        question = questions.get(str(row.get("id")))
        if question is None:
            continue
        choices = question.get("choices") or {}
        correct = question.get("correct_option")
        text = (
            f"سؤال: {question.get('prompt', '')}\n"
            f"گزینهٔ درست ({correct}): {choices.get(correct, '')}\n"
            f"توضیح: {question.get('explanation', '')}"
        )
        source = question.get("source") or {}
        citation = normalize_citation(
            {
                "book_id": source.get("book_id", exam.book_id),
                "book_title": source.get("book_title"),
                "chapter_number": source.get("chapter_number"),
                "chapter_title": source.get("chapter_title"),
                "pdf_page_index": source.get("pdf_page_index"),
                "printed_page_number": source.get("printed_page_number"),
            }
        )
        items.append(SourceItem(text=text[:MAX_TEXT_CHARS], citations=[citation]))
    if not items:
        raise HTTPException(status_code=422, detail="پاسخ نادرست قابل‌استفاده‌ای در این آزمون پیدا نشد.")
    return ResolvedSources(
        source_type="mistake",
        items=items,
        book_id=exam.book_id,
        title_hint=f"اشتباهات آزمون: {exam.title}",
    )


__all__ = [
    "MAX_BOOK_PAGES",
    "ResolvedSources",
    "SourceItem",
    "normalize_citation",
    "resolve_book_source",
    "resolve_chat_source",
    "resolve_mistake_source",
]
