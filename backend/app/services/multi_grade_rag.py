"""Multi-grade, multi-book textbook retrieval with concept-link expansion (Phase 4).

Flow:
1. `build_scopes` turns the student's grade filter (10/11/12) and optional
   book list into exact (book, grade, major) scopes. Only `ready` books are used.
2. `search_multi_grade` runs hybrid search over all scopes at once.
3. `expand_with_concept_links` follows admin-curated `concept_links` from the
   top hits to chapters of linked books, restricted to the selected grades.
   Expansion hits are tagged `via_concept_link` so the UI and audit log can show
   why a cross-grade citation appeared.
4. `lookup_pages` resolves chapter/printed-page references to real pages.

No outside knowledge is introduced here: every returned item is a stored
`book_pages` row with its printed page and chapter metadata.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concepts import ConceptLink
from app.models.curriculum import (
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
from app.services.retrieval_service import TextbookScope, search_textbook_scopes

MAX_GRADES = 3
MAX_BOOKS = 12


class ScopeError(ValueError):
    """Raised when a requested grade/book combination is invalid."""


async def resolve_curriculum_book_ids(
    session: AsyncSession,
    *,
    grade_numbers: Sequence[int],
    branch_code: str,
    field_code: str | None,
    academic_year_id: int | None,
    subject_ids: Sequence[int] | None = None,
    requested_book_ids: Sequence[int] | None = None,
) -> list[int]:
    """Resolve approved editions for the selected branch/field/year/subject.

    An anchor edition must have at least one normalized subject link. This is
    the authorization boundary for multi-grade retrieval; its returned IDs,
    never raw client-supplied IDs, are passed to search_multi_grade.
    """
    grades = sorted({int(grade) for grade in grade_numbers})
    if not grades or any(grade not in (10, 11, 12) for grade in grades):
        raise ScopeError("grade_numbers must be within 10, 11, 12")
    if len(grades) > MAX_GRADES:
        raise ScopeError("too many grades")
    if not subject_ids:
        raise ScopeError("the anchor textbook must have an approved subject mapping for multi-grade retrieval")
    subject_ids = sorted(
        set(
            (
                await session.scalars(
                    select(Subject.id).where(
                        Subject.id.in_([int(subject_id) for subject_id in subject_ids]),
                        Subject.is_active.is_(True),
                    )
                )
            ).all()
        )
    )
    if not subject_ids:
        raise ScopeError("the anchor textbook has no active subject mapping for multi-grade retrieval")
    if not branch_code:
        raise ScopeError("branch_code is required for multi-grade retrieval")

    branch = await session.scalar(
        select(EducationBranch).where(
            EducationBranch.code == branch_code,
            EducationBranch.is_active.is_(True),
        )
    )
    if branch is None or any(not branch.min_grade <= grade <= branch.max_grade for grade in grades):
        raise ScopeError("selected branch is not valid for every requested grade")

    selected_field = None
    if field_code:
        selected_field = await session.scalar(
            select(FieldOfStudy).where(
                FieldOfStudy.code == field_code,
                FieldOfStudy.branch_id == branch.id,
                FieldOfStudy.is_active.is_(True),
            )
        )
        if selected_field is None:
            raise ScopeError("selected field does not belong to the selected branch")
    elif (
        await session.scalar(
            select(FieldOfStudy.id)
            .where(
                FieldOfStudy.branch_id == branch.id,
                FieldOfStudy.is_active.is_(True),
            )
            .limit(1)
        )
    ) is not None:
        raise ScopeError("a field of study is required for this branch")

    # Every candidate edition must have an explicit active subject link.
    # A NULL subject is not an authorization wildcard for multi-grade retrieval.
    subject_match = BookCurriculumLink.subject_id.in_(subject_ids)
    applicable_links = [
        exists(
            select(BookCurriculumLink.id).where(
                BookCurriculumLink.book_id == Book.id,
                BookCurriculumLink.branch_id.is_(None),
                BookCurriculumLink.field_of_study_id.is_(None),
                subject_match,
            )
        ),
        exists(
            select(BookCurriculumLink.id).where(
                BookCurriculumLink.book_id == Book.id,
                BookCurriculumLink.branch_id == branch.id,
                BookCurriculumLink.field_of_study_id.is_(None),
                subject_match,
            )
        ),
    ]
    if selected_field is not None:
        applicable_links.append(
            exists(
                select(BookCurriculumLink.id).where(
                    BookCurriculumLink.book_id == Book.id,
                    BookCurriculumLink.branch_id == branch.id,
                    BookCurriculumLink.field_of_study_id == selected_field.id,
                    subject_match,
                )
            )
        )

    year_condition = (
        Book.academic_year_id == academic_year_id
        if academic_year_id is not None
        else Book.academic_year_id.is_(None)
    )
    predicates = [
        Book.status == BookStatus.ready,
        Grade.number.in_(grades),
        year_condition,
        or_(*applicable_links),
    ]
    statement = (
        select(Book.id)
        .join(Grade, Book.grade_id == Grade.id)
        .where(*predicates)
        .order_by(Grade.number.asc(), Book.id.asc())
    )

    requested_ids: list[int] | None = None
    if requested_book_ids is not None:
        requested_ids = sorted({int(book_id) for book_id in requested_book_ids})
        if not requested_ids:
            raise ScopeError("book_ids cannot be empty when explicitly supplied")
        if len(requested_ids) > MAX_BOOKS:
            raise ScopeError("too many books")
        statement = statement.where(Book.id.in_(requested_ids))

    allowed_ids = [int(book_id) for book_id in (await session.scalars(statement)).all()]
    if len(allowed_ids) > MAX_BOOKS:
        raise ScopeError(
            f"too many textbooks match the selected curriculum scope (maximum {MAX_BOOKS}); "
            "narrow the subject or explicitly select textbooks"
        )
    if requested_ids is not None:
        missing = sorted(set(requested_ids) - set(allowed_ids))
        if missing:
            raise ScopeError(
                "books are not approved for the selected grades, branch, field, subject, and academic year: "
                f"{missing}"
            )
    if not allowed_ids:
        raise ScopeError("no approved textbooks are available in the selected curriculum scope")
    return allowed_ids


async def build_scopes(
    session: AsyncSession,
    *,
    grade_numbers: Sequence[int],
    book_ids: Sequence[int],
) -> list[TextbookScope]:
    """Build retrieval scopes from server-authorized book IDs only."""
    if not book_ids:
        raise ScopeError("authorized book_ids are required for multi-grade retrieval")
    grades = sorted({int(g) for g in grade_numbers})
    if not grades:
        raise ScopeError("at least one grade is required")
    if any(g not in (10, 11, 12) for g in grades):
        raise ScopeError("grade_numbers must be within 10, 11, 12")
    if len(grades) > MAX_GRADES:
        raise ScopeError("too many grades")

    statement = (
        select(Book, Grade.number, Major.code)
        .join(Grade, Book.grade_id == Grade.id)
        .outerjoin(Major, Book.major_id == Major.id)
        .where(
            Grade.number.in_(grades),
            Book.status == BookStatus.ready,
            )
        .order_by(Grade.number.asc(), Book.id.asc())
    )
    ids = sorted({int(book_id) for book_id in book_ids})
    if not ids:
        raise ScopeError("authorized book_ids are required for multi-grade retrieval")
    statement = statement.where(Book.id.in_(ids))
    rows = (await session.execute(statement)).all()

    found = {book.id for book, _, _ in rows}
    missing = sorted(set(ids) - found)
    if missing:
        raise ScopeError(f"authorized books are not ready or do not match selected grades: {missing}")

    return [
        TextbookScope(book_id=book.id, grade_number=grade, major_code=major or "general")
        for book, grade, major in rows
    ]


async def search_multi_grade(
    session: AsyncSession,
    query: str,
    *,
    grade_numbers: Sequence[int],
    book_ids: Sequence[int] | None = None,
    top_k: int = 6,
    expand_links: bool = True,
) -> dict[str, Any]:
    """Hybrid search across grades plus optional concept-link expansion.

    Returns {"results": [...], "scopes": [...], "expanded": int}.
    """
    scopes = await build_scopes(session, grade_numbers=grade_numbers, book_ids=book_ids)
    if not scopes:
        return {"results": [], "scopes": [], "expanded": 0}

    primary = await search_textbook_scopes(
        query, scopes=scopes, top_k=top_k, route_session=session
    )
    for item in primary:
        item["via_concept_link"] = False

    expanded: list[dict[str, Any]] = []
    if expand_links and primary:
        authorized_book_ids = {scope.book_id for scope in scopes}
        seeds = [(r["book_id"], r["chapter_number"]) for r in primary if r.get("chapter_number")]
        link_scopes = await expand_with_concept_links(
            session,
            seeds=seeds,
            allowed_grades=grade_numbers,
            allowed_book_ids=authorized_book_ids,
        )
        if link_scopes:
            expanded = await search_textbook_scopes(
                query, scopes=link_scopes, top_k=max(2, top_k // 2), route_session=session
            )
            for item in expanded:
                item["via_concept_link"] = True

    merged = _dedupe_pages(primary + expanded)
    return {"results": merged[: top_k + 2], "scopes": scopes, "expanded": len(expanded)}


async def expand_with_concept_links(
    session: AsyncSession,
    *,
    seeds: Iterable[tuple[int, int]],
    allowed_grades: Sequence[int],
    allowed_book_ids: set[int] | Sequence[int],
) -> list[TextbookScope]:
    """Chapter-level scopes for books linked to the seed chapters.

    Links are followed in both directions. Targets outside `allowed_grades` are
    dropped so an explicit grade filter is never silently widened.
    """
    seed_set = {(int(b), int(c)) for b, c in seeds}
    if not seed_set:
        return []
    book_ids = {b for b, _ in seed_set}
    rows = (
        await session.execute(
            select(ConceptLink).where(
                or_(
                    ConceptLink.source_book_id.in_(book_ids),
                    ConceptLink.target_book_id.in_(book_ids),
                )
            )
        )
    ).scalars().all()

    targets: dict[int, set[int]] = defaultdict(set)
    for link in rows:
        if (link.source_book_id, link.source_chapter) in seed_set:
            targets[link.target_book_id].add(link.target_chapter)
        if (link.target_book_id, link.target_chapter) in seed_set:
            targets[link.source_book_id].add(link.source_chapter)
    if not targets:
        return []

    allowed = set(int(g) for g in allowed_grades)
    allowed_ids = {int(book_id) for book_id in allowed_book_ids}
    target_ids = sorted(set(targets) & allowed_ids)
    if not target_ids:
        return []
    book_rows = (
        await session.execute(
            select(Book.id, Grade.number, Major.code)
            .join(Grade, Book.grade_id == Grade.id)
            .outerjoin(Major, Book.major_id == Major.id)
            .where(
                Book.id.in_(target_ids),
                Book.status == BookStatus.ready,
                    )
        )
    ).all()
    scopes: list[TextbookScope] = []
    for book_id, grade, major in book_rows:
        if grade not in allowed:
            continue
        scopes.append(
            TextbookScope(
                book_id=book_id,
                grade_number=grade,
                major_code=major or "general",
                chapter_numbers=frozenset(targets[book_id]),
            )
        )
    return scopes


async def lookup_pages(
    session: AsyncSession,
    *,
    book_id: int,
    chapter_number: int | None = None,
    printed_page_number: int | None = None,
    limit: int = 20,
) -> list[BookPage]:
    """Find approved pages by chapter or printed page number (for explicit citations)."""
    if chapter_number is None and printed_page_number is None:
        raise ScopeError("chapter_number or printed_page_number is required")
    conditions = [BookPage.book_id == book_id, BookPage.status == PageStatus.done]
    if chapter_number is not None:
        conditions.append(BookPage.chapter_number == chapter_number)
    if printed_page_number is not None:
        conditions.append(BookPage.printed_page_number == printed_page_number)
    rows = (
        await session.execute(
            select(BookPage).where(*conditions).order_by(BookPage.pdf_page_index.asc()).limit(limit)
        )
    ).scalars().all()
    return list(rows)


def _dedupe_pages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the best-scoring hit per (book, page); preserve order by score."""
    best: dict[tuple[int, int], dict[str, Any]] = {}
    for item in items:
        key = (item["book_id"], item["pdf_page_index"])
        current = best.get(key)
        if current is None or item.get("score", 0) > current.get("score", 0):
            best[key] = item
    return sorted(best.values(), key=lambda it: it.get("score", 0), reverse=True)
