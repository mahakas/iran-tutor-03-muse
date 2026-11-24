"""Phase 6 Living Book: one chapter compiled into an interactive study view.

Shared cache: one row per (book, chapter, content_hash). The hash covers the chapter's
approved pages, so an edited chapter gets a fresh entry and stale ones are never served.
Generation is textbook-strict and goes through `capability_runtime` (gateway + audit).
Every item is checked deterministically before caching:
  * concepts / callouts / flashcards must cite a printed page inside this chapter;
  * mermaid diagrams pass the diagram guard;
  * quiz items pass the Phase 5 Validator Gate (`quiz_validator.validate_questions`).
Rejected items are stored with reasons (glass box), never shown to the student.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.curriculum import Book, BookPage, BookStatus, PageStatus
from app.models.phase6 import LivingBookCache
from app.services import capability_runtime
from app.services.ai_gateway import record_decision_audit
from app.services.book_scope import book_scope, require_grade
from app.services.capability_service import require_capability_enabled
from app.services.immersive_service import citation_for_page
from app.services.quiz_validator import validate_questions
from app.services.visual_safety import UnsafeVisualError, validate_mermaid

CAPABILITY_KEY = "living_book"
SCHEMA_VERSION = "living-book-v1"
MAX_SOURCE_CHARS = 14000
MAX_CONCEPTS = 8
MAX_CALLOUTS = 6
MAX_QUIZ = 5
MAX_CARDS = 8


def _page_text(page: BookPage) -> str:
    return (page.markdown_content or "").strip()


async def chapter_pages(session: AsyncSession, book_id: int, chapter_number: int) -> list[BookPage]:
    rows = await session.scalars(
        select(BookPage)
        .where(
            BookPage.book_id == book_id,
            BookPage.chapter_number == chapter_number,
            BookPage.status == PageStatus.done,
        )
        .order_by(BookPage.pdf_page_index.asc())
    )
    return list(rows.all())


def content_hash_for(pages: list[BookPage]) -> str:
    digest = hashlib.sha256(SCHEMA_VERSION.encode("utf-8"))
    for page in pages:
        digest.update(f"\x1e{page.pdf_page_index}\x1f{page.printed_page_number}\x1f".encode("utf-8"))
        digest.update(_page_text(page).encode("utf-8"))
    return digest.hexdigest()


def _source_text(pages: list[BookPage]) -> str:
    parts: list[str] = []
    total = 0
    for page in pages:
        chunk = f"[صفحه چاپی {page.printed_page_number}]\n{_page_text(page)}"
        if total + len(chunk) > MAX_SOURCE_CHARS:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)


def _as_dict(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _pages_by_number(pages: list[BookPage]) -> dict[int, BookPage]:
    return {int(p.printed_page_number): p for p in pages if p.printed_page_number is not None}


def _citation_for(page: BookPage | None, book: Book) -> dict[str, Any] | None:
    if page is None:
        return None
    return citation_for_page(book, page)


def assemble_living_book(
    raw: dict[str, Any],
    *,
    pages: list[BookPage],
    book: Book,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic grounding and safety pass. Returns (accepted_blocks, rejected)."""
    by_page = _pages_by_number(pages)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def reject(kind: str, reason: str, item: Any) -> None:
        rejected.append({"kind": kind, "reason": reason, "item": item})

    def grounded_page(item: dict[str, Any]) -> BookPage | None:
        try:
            number = int(item.get("page"))
        except (TypeError, ValueError):
            return None
        return by_page.get(number)

    for item in (raw.get("concepts") or [])[:MAX_CONCEPTS]:
        if not isinstance(item, dict):
            continue
        page = grounded_page(item)
        if page is None:
            reject("concept", "page_not_in_chapter", item)
            continue
        accepted.append({
            "type": "text_markdown",
            "content": f"**{str(item.get('title') or '')[:200]}**\n\n{str(item.get('text') or '')[:1500]}",
            "metadata": {"section": "concept", "citation": _citation_for(page, book)["citation"]},
        })

    for item in (raw.get("callouts") or [])[:MAX_CALLOUTS]:
        if not isinstance(item, dict):
            continue
        page = grounded_page(item)
        if page is None:
            reject("callout", "page_not_in_chapter", item)
            continue
        tone = str(item.get("tone") or "tip")
        accepted.append({
            "type": "callout_tip",
            "content": str(item.get("text") or "")[:1200],
            "metadata": {"tone": tone if tone in {"tip", "note", "warning"} else "tip",
                         "citation": _citation_for(page, book)["citation"]},
        })

    for item in (raw.get("diagrams") or [])[:2]:
        if not isinstance(item, dict):
            continue
        try:
            source = validate_mermaid(item.get("source"))
        except UnsafeVisualError as error:
            reject("diagram", str(error), item)
            continue
        page = grounded_page(item)
        if page is None:
            reject("diagram", "page_not_in_chapter", item)
            continue
        accepted.append({
            "type": "diagram_mermaid",
            "content": source,
            "metadata": {"title": str(item.get("title") or "")[:200],
                         "citation": _citation_for(page, book)["citation"]},
        })

    for item in (raw.get("flashcards") or [])[:MAX_CARDS]:
        if not isinstance(item, dict):
            continue
        page = grounded_page(item)
        front, back = str(item.get("front") or "").strip(), str(item.get("back") or "").strip()
        if page is None or not front or not back:
            reject("flashcard", "page_not_in_chapter" if page is None else "empty", item)
            continue
        accepted.append({
            "type": "flashcard_item",
            "content": front[:1200],
            "metadata": {"back": back[:2000], "citation": _citation_for(page, book)["citation"]},
        })
    return accepted, rejected


async def _validated_quiz(
    session: AsyncSession, user: User, raw: dict[str, Any], *, pages: list[BookPage], book: Book
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    by_page = _pages_by_number(pages)
    items: list[dict[str, Any]] = []
    item_pages: list[BookPage] = []
    for item in (raw.get("quiz") or [])[:MAX_QUIZ]:
        if not isinstance(item, dict):
            continue
        page = None
        try:
            page = by_page.get(int(item.get("page")))
        except (TypeError, ValueError):
            page = None
        if page is None:
            continue
        question = {
            "prompt": item.get("prompt"),
            "choices": item.get("choices"),
            "correct_option": str(item.get("correct_option") or "").upper(),
            "explanation": item.get("explanation"),
        }
        items.append({"question": question, "source_text": _page_text(page)})
        item_pages.append(page)
    if not items:
        return [], [], None
    outcome = await validate_questions(session, items=items, user_id=user.id, book_id=book.id)
    # `decisions` follow input order; accepted questions keep that order for non-rejected ones.
    kept_pages = [item_pages[d.index] for d in outcome.decisions if d.verdict != "rejected"]
    accepted = []
    for question, page in zip(outcome.accepted, kept_pages, strict=False):
        accepted.append({
            "type": "quiz_item",
            "content": str(question.get("prompt") or ""),
            "metadata": {
                "choices": question.get("choices"),
                "correct_option": question.get("correct_option"),
                "explanation": question.get("explanation"),
                "citation": _citation_for(page, book)["citation"],
            },
        })
    rejected = [
        {"kind": "quiz", "reason": ",".join(d.reasons) or d.verdict, "item": None}
        for d in outcome.decisions
        if d.verdict == "rejected"
    ]
    return accepted, rejected, outcome.audit_id


async def get_living_book(session: AsyncSession, user: User, *, book_id: int, chapter_number: int) -> dict[str, Any]:
    await require_capability_enabled(session, CAPABILITY_KEY, user)
    book = await session.get(Book, book_id)
    if book is None or book.status != BookStatus.ready:
        raise HTTPException(status_code=404, detail="کتاب آماده‌ای با این شناسه یافت نشد.")
    scope = await book_scope(session, book_id)
    require_grade(scope)
    pages = await chapter_pages(session, book_id, chapter_number)
    if not pages:
        raise HTTPException(status_code=404, detail="این فصل صفحهٔ آماده‌ای ندارد.")
    digest = content_hash_for(pages)
    printed = sorted({p.printed_page_number for p in pages if p.printed_page_number is not None})
    chapter_title = pages[0].chapter_title or f"فصل {chapter_number}"

    cached = await session.scalar(
        select(LivingBookCache).where(
            LivingBookCache.book_id == book_id,
            LivingBookCache.chapter_number == chapter_number,
            LivingBookCache.content_hash == digest,
        )
    )
    if cached is not None:
        cached.hit_count = (cached.hit_count or 0) + 1
        await record_decision_audit(
            feature_key=CAPABILITY_KEY,
            user_id=user.id,
            session_id=None,
            request_text=f"living_book cache hit book={book_id} chapter={chapter_number}",
            decision={"cache": "hit", "content_hash": digest[:16], "blocks": len(cached.blocks_json)},
            flag_reason="living_book_cache_hit",
            session=session,
        )
        await session.commit()
        return _payload(book, chapter_number, chapter_title, digest, printed, cached.blocks_json, cached.rejected_json, cache_hit=True)

    citations = [_citation_for(p, book) for p in pages]
    user_text = (
        f"فصل {chapter_number}: {chapter_title}\n"
        f"صفحه‌های چاپی: {', '.join(str(n) for n in printed)}\n\n"
        f"متن فصل:\n{_source_text(pages)}"
    )
    result, _skill = await capability_runtime.run_capability_json(
        session=session,
        capability_key=CAPABILITY_KEY,
        user_text=user_text,
        feature_key=CAPABILITY_KEY,
        user_id=user.id,
        book_id=book_id,
        textbook_strict=True,
        citations=citations,
        rag_hit_count=len(pages),
        grade_scope=str(scope.grade_number),
        subject_scope=scope.major_code,
        user=user,
        enforce=True,
    )
    raw = _as_dict(result.content)
    if raw is None:
        await session.commit()
        raise HTTPException(status_code=502, detail="خروجی کتاب زنده معتبر نبود؛ دوباره تلاش کنید.")

    blocks, rejected = assemble_living_book(raw, pages=pages, book=book)
    quiz_blocks, quiz_rejected, _validator_audit = await _validated_quiz(session, user, raw, pages=pages, book=book)
    blocks.extend(quiz_blocks)
    rejected.extend(quiz_rejected)

    row = LivingBookCache(
        book_id=book_id,
        chapter_number=chapter_number,
        chapter_title=chapter_title[:255],
        content_hash=digest,
        blocks_json=blocks,
        rejected_json=rejected,
        model_name=result.model_name,
        generated_by_user_id=user.id,
        hit_count=0,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        # Another student generated the same chapter first; serve the stored copy.
        await session.rollback()
        cached = await session.scalar(
            select(LivingBookCache).where(
                LivingBookCache.book_id == book_id,
                LivingBookCache.chapter_number == chapter_number,
                LivingBookCache.content_hash == digest,
            )
        )
        if cached is None:
            raise HTTPException(status_code=409, detail="تولید همزمان کتاب زنده؛ دوباره تلاش کنید.")
        return _payload(book, chapter_number, chapter_title, digest, printed, cached.blocks_json, cached.rejected_json, cache_hit=True)
    return _payload(book, chapter_number, chapter_title, digest, printed, blocks, rejected, cache_hit=False)


def _payload(
    book: Book,
    chapter_number: int,
    chapter_title: str,
    digest: str,
    printed: list[int],
    blocks: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    *,
    cache_hit: bool,
) -> dict[str, Any]:
    # Students see accepted blocks only. Rejections count is shown; reasons stay in /admin.
    return {
        "book_id": book.id,
        "book_title": book.title,
        "chapter_number": chapter_number,
        "chapter_title": chapter_title,
        "content_hash": digest,
        "printed_pages": printed,
        "cache_hit": cache_hit,
        "blocks": blocks,
        "rejected_count": len(rejected),
    }
