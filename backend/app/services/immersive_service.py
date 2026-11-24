"""Phase 5 Immersive Reader: TOC, page detail, and grounded assist actions.

Pages are served only for ready books and only to students with the
`immersive_reader` capability. Assist actions run through `capability_runtime`
with textbook strictness and cite the exact page the student is viewing.
"""

from __future__ import annotations

import html
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.curriculum import (
    AcademicYear,
    Book,
    BookCurriculumLink,
    BookPage,
    BookStatus,
    EducationBranch,
    FieldOfStudy,
    Grade,
    Major,
    PageStatus,
    Subject,
)
from app.services import kb_ingestion_service
from app.services.capability_runtime import run_capability_text
from app.services.curriculum_access import is_student_visible_book

IMMERSIVE_CAPABILITY = "immersive_reader"
ASSIST_INSTRUCTIONS = {
    "summarize": "این بخش از کتاب درسی را در چند نکتهٔ کوتاه خلاصه کن.",
    "explain": "مفهوم اصلی این بخش از کتاب درسی را ساده و گام‌به‌گام توضیح بده.",
}


def _normalize_selected_text(value: str) -> str:
    """Normalize rendered textbook text and Markdown for safe page-substring checks."""
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r" \1 ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r" \1 ", text)
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه")
    text = re.sub(r"[\u200c\u200f\u202a-\u202e\u0640]", "", text)
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).casefold()
    return " ".join(text.split())


async def _ready_book(session: AsyncSession, book_id: int) -> Book:
    book = await session.get(Book, book_id)
    if not is_student_visible_book(book):
        raise HTTPException(status_code=404, detail="کتاب آماده‌ای با این شناسه یافت نشد.")
    return book


async def book_overview(session: AsyncSession, book_id: int) -> dict[str, Any]:
    book = await _ready_book(session, book_id)
    pages = (
        await session.scalars(
            select(BookPage)
            .where(BookPage.book_id == book_id, BookPage.status == PageStatus.done)
            .order_by(BookPage.pdf_page_index.asc())
        )
    ).all()
    chapters: dict[int, dict[str, Any]] = {}
    for page in pages:
        if page.chapter_number is None:
            continue
        entry = chapters.setdefault(
            page.chapter_number,
            {
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title or f"فصل {page.chapter_number}",
                "page_start": page.pdf_page_index,
                "page_end": page.pdf_page_index,
                "printed_start": page.printed_page_number,
                "printed_end": page.printed_page_number,
            },
        )
        entry["page_end"] = page.pdf_page_index
        if page.printed_page_number is not None:
            entry["printed_end"] = page.printed_page_number
    grade = await session.get(Grade, book.grade_id)
    major = await session.get(Major, book.major_id) if book.major_id else None
    metadata = await _book_scope_metadata(session, book)
    return {
        "id": book.id,
        "title": book.title,
        "grade_number": grade.number if grade else None,
        "major_code": major.code if major else "general",
        **metadata,
        "page_count": len(pages),
        "chapters": list(chapters.values()),
        "pages": [
            {
                "pdf_page_index": page.pdf_page_index,
                "printed_page_number": page.printed_page_number,
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title,
            }
            for page in pages
        ],
    }


async def _book_scope_metadata(session: AsyncSession, book: Book) -> dict[str, Any]:
    """Resolve stable edition and scope labels for student-facing citations."""
    year = await session.get(AcademicYear, book.academic_year_id) if book.academic_year_id else None
    rows = (
        await session.execute(
            select(
                EducationBranch.title,
                FieldOfStudy.title,
                Subject.title,
            )
            .select_from(BookCurriculumLink)
            .outerjoin(EducationBranch, BookCurriculumLink.branch_id == EducationBranch.id)
            .outerjoin(FieldOfStudy, BookCurriculumLink.field_of_study_id == FieldOfStudy.id)
            .outerjoin(Subject, BookCurriculumLink.subject_id == Subject.id)
            .where(BookCurriculumLink.book_id == book.id)
        )
    ).all()
    branch_titles = list(dict.fromkeys(row[0] for row in rows if row[0]))
    field_titles = list(dict.fromkeys(row[1] for row in rows if row[1]))
    subject_titles = list(dict.fromkeys(row[2] for row in rows if row[2]))
    return {
        "academic_year_code": year.code if year else None,
        "edition_label": book.edition_label,
        "print_year": book.print_year,
        "publisher": book.publisher,
        "branch_titles": branch_titles,
        "field_titles": field_titles,
        "subject_titles": subject_titles,
    }


def citation_for_page(
    book: Book,
    page: BookPage,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    chapter = page.chapter_title or (f"فصل {page.chapter_number}" if page.chapter_number else "فصل نامشخص")
    printed = f"صفحه چاپی {page.printed_page_number}" if page.printed_page_number is not None else "صفحه نامشخص"
    branch_titles = metadata.get("branch_titles") or []
    field_titles = metadata.get("field_titles") or []
    edition_labels = []
    if branch_titles:
        edition_labels.append("شاخه " + "، ".join(branch_titles))
    if field_titles:
        edition_labels.append("رشته " + "، ".join(field_titles))
    if metadata.get("academic_year_code"):
        edition_labels.append("سال تحصیلی " + str(metadata["academic_year_code"]))
    if metadata.get("edition_label"):
        edition_labels.append(str(metadata["edition_label"]))
    if metadata.get("print_year"):
        edition_labels.append("چاپ " + str(metadata["print_year"]))
    if metadata.get("publisher"):
        edition_labels.append("ناشر " + str(metadata["publisher"]))
    edition = "، " + "، ".join(edition_labels) if edition_labels else ""
    return {
        "book_id": book.id,
        "book_title": book.title,
        "chapter_number": page.chapter_number,
        "chapter_title": page.chapter_title,
        "pdf_page_index": page.pdf_page_index,
        "printed_page_number": page.printed_page_number,
        **metadata,
        "citation": f"{book.title}{edition}، {chapter}، {printed}",
    }


async def page_detail(session: AsyncSession, book_id: int, pdf_page_index: int) -> dict[str, Any]:
    book = await _ready_book(session, book_id)
    page = await session.scalar(
        select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == pdf_page_index)
    )
    if page is None or page.status != PageStatus.done:
        raise HTTPException(status_code=404, detail="صفحه یافت نشد.")
    figures = await kb_ingestion_service.list_figures(session, book_id=book_id, page_index=pdf_page_index)
    metadata = await _book_scope_metadata(session, book)
    return {
        **citation_for_page(book, page, metadata),
        "markdown_content": page.markdown_content,
        "figures": [kb_ingestion_service.serialize_figure(figure) for figure in figures],
    }


async def page_image_path(session: AsyncSession, book_id: int, pdf_page_index: int) -> str:
    await _ready_book(session, book_id)
    page = await session.scalar(
        select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == pdf_page_index)
    )
    if page is None or page.status != PageStatus.done or not page.page_image_path:
        raise HTTPException(status_code=404, detail="تصویر صفحه موجود نیست.")
    return page.page_image_path


async def assist(
    session: AsyncSession,
    user: User,
    *,
    book_id: int,
    action: str,
    pdf_page_index: int,
    selection: str | None = None,
) -> dict[str, Any]:
    if action not in ASSIST_INSTRUCTIONS:
        raise HTTPException(status_code=422, detail="اقدام نامعتبر است.")
    book = await _ready_book(session, book_id)
    page = await session.scalar(
        select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == pdf_page_index)
    )
    if page is None or page.status != PageStatus.done:
        raise HTTPException(status_code=404, detail="صفحه یافت نشد.")
    page_text = (page.markdown_content or "").strip()
    selected_text = (selection or "").strip()
    if selected_text:
        normalized_page = _normalize_selected_text(page_text)
        normalized_selection = _normalize_selected_text(selected_text)
        if not normalized_selection or normalized_selection not in normalized_page:
            raise HTTPException(
                status_code=422,
                detail="متن انتخاب‌شده بخشی از متن ثبت‌شدهٔ همین صفحهٔ کتاب نیست.",
            )
        context = selected_text
    else:
        context = page_text
    if not context:
        raise HTTPException(status_code=409, detail="متنی برای این صفحه ثبت نشده است.")
    metadata = await _book_scope_metadata(session, book)
    citation = citation_for_page(book, page, metadata)
    try:
        result, _blocks, _skill = await run_capability_text(
            session=session,
            capability_key=IMMERSIVE_CAPABILITY,
            feature_key=IMMERSIVE_CAPABILITY,
            user_text=f"{ASSIST_INSTRUCTIONS[action]}\n\nمتن کتاب:\n{context[:6000]}",
            user_id=user.id,
            book_id=book_id,
            textbook_strict=True,
            citations=[citation],
            rag_hit_count=1,
            user=user,
            enforce=True,
        )
    except Exception:
        # Persist the gateway audit row even when the call fails (glass box), then re-raise.
        await session.commit()
        raise
    await session.commit()
    return {"answer": result.content, "citation": citation, "audit_id": result.audit_id, "action": action}
