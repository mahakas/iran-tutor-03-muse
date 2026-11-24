"""Resolve a book's grade and major for textbook-scoped retrieval (shared by Phase 6 services)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import Book, Grade, Major


@dataclass(frozen=True)
class BookScope:
    book_id: int
    title: str
    grade_number: int | None
    major_code: str


async def book_scope(session: AsyncSession, book_id: int) -> BookScope:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="کتاب یافت نشد.")
    grade = await session.get(Grade, book.grade_id)
    major = await session.get(Major, book.major_id) if book.major_id else None
    return BookScope(
        book_id=book.id,
        title=book.title,
        grade_number=grade.number if grade else None,
        major_code=major.code if major else "general",
    )


def require_grade(scope: BookScope) -> int:
    """`search_textbook` needs an exact grade; refuse books that have none."""
    if scope.grade_number is None:
        raise HTTPException(status_code=422, detail="پایهٔ این کتاب مشخص نیست؛ جستجوی کتاب ممکن نیست.")
    return scope.grade_number


def source_citation(source: dict, book_title: str) -> dict:
    """Return a search hit annotated with the printed-page citation label."""
    chapter_number = source.get("chapter_number")
    chapter = source.get("chapter_title") or (f"فصل {chapter_number}" if chapter_number else "فصل نامشخص")
    printed_page = source.get("printed_page_number")
    printed = f"صفحه چاپی {printed_page}" if printed_page is not None else "صفحه نامشخص"
    return {
        **source,
        "book_title": book_title,
        "citation": f"{book_title}، {chapter}، {printed}",
    }
