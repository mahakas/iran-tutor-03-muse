"""Read-only curriculum selectors for student and admin clients."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_student
from app.db.session import get_session
from app.models.auth import User
from app.models.capabilities import SourceFigure
from app.models.curriculum import (
    AcademicYear,
    Book,
    BookCurriculumLink,
    BookPage,
    BookStatus,
    EducationBranch,
    EducationCycle,
    FieldOfStudy,
    Grade,
    Major,
    PageStatus,
    Subject,
)
from app.services.capability_service import check_capability_access
from app.services.curriculum_access import is_student_visible_book
from app.services.kb_ingestion_service import figures_dir
from app.services.search_normalize import search_key, sql_search_key

router = APIRouter(prefix="/api/v1/curriculum", tags=["curriculum"])


@router.get("/grades")
async def list_grades(session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    rows = (
        await session.execute(
            select(Grade, EducationCycle.code, EducationCycle.title)
            .outerjoin(EducationCycle, Grade.cycle_id == EducationCycle.id)
            .order_by(Grade.number)
        )
    ).all()
    return [
        {
            "number": grade.number,
            "title": grade.title,
            "has_major": grade.has_major,
            "cycle_code": cycle_code,
            "cycle_title": cycle_title,
        }
        for grade, cycle_code, cycle_title in rows
    ]


@router.get("/cycles")
async def list_cycles(session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    rows = (await session.scalars(select(EducationCycle).order_by(EducationCycle.sort_order))).all()
    return [{"code": item.code, "title": item.title, "sort_order": item.sort_order} for item in rows]


@router.get("/branches")
async def list_branches(
    grade_number: int | None = Query(None, ge=1, le=12),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    stmt = select(EducationBranch).where(EducationBranch.is_active.is_(True))
    if grade_number is not None:
        stmt = stmt.where(
            EducationBranch.min_grade <= grade_number,
            EducationBranch.max_grade >= grade_number,
        )
    rows = (await session.scalars(stmt.order_by(EducationBranch.sort_order, EducationBranch.title))).all()
    return [
        {
            "code": item.code,
            "title": item.title,
            "min_grade": item.min_grade,
            "max_grade": item.max_grade,
        }
        for item in rows
    ]


@router.get("/fields")
async def list_fields(
    branch_code: str | None = Query(None, max_length=64),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    stmt = (
        select(FieldOfStudy, EducationBranch.code, EducationBranch.title)
        .join(EducationBranch, FieldOfStudy.branch_id == EducationBranch.id)
        .where(FieldOfStudy.is_active.is_(True), EducationBranch.is_active.is_(True))
    )
    if branch_code:
        stmt = stmt.where(EducationBranch.code == branch_code)
    rows = (
        await session.execute(stmt.order_by(EducationBranch.sort_order, FieldOfStudy.sort_order, FieldOfStudy.title))
    ).all()
    return [
        {
            "code": field.code,
            "title": field.title,
            "branch_code": code,
            "branch_title": branch_title,
        }
        for field, code, branch_title in rows
    ]


@router.get("/academic-years")
async def list_academic_years(
    active_only: bool = Query(False),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    stmt = select(AcademicYear)
    if active_only:
        stmt = stmt.where(AcademicYear.is_active.is_(True))
    rows = (await session.scalars(stmt.order_by(AcademicYear.code.desc()))).all()
    return [
        {"code": item.code, "title": item.title, "is_active": item.is_active}
        for item in rows
    ]


@router.get("/subjects")
async def list_subjects(
    active_only: bool = Query(True),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    stmt = select(Subject)
    if active_only:
        stmt = stmt.where(Subject.is_active.is_(True))
    rows = (await session.scalars(stmt.order_by(Subject.title))).all()
    return [{"code": item.code, "title": item.title, "description": item.description} for item in rows]


@router.get("/tree")
async def curriculum_tree(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    cycles = (await session.scalars(select(EducationCycle).order_by(EducationCycle.sort_order))).all()
    grades = (await session.scalars(select(Grade).order_by(Grade.number))).all()
    branches = (
        await session.scalars(
            select(EducationBranch)
            .where(EducationBranch.is_active.is_(True))
            .order_by(EducationBranch.sort_order)
        )
    ).all()
    fields = (
        await session.execute(
            select(FieldOfStudy, EducationBranch.code)
            .join(EducationBranch, FieldOfStudy.branch_id == EducationBranch.id)
            .where(FieldOfStudy.is_active.is_(True))
            .order_by(EducationBranch.sort_order, FieldOfStudy.sort_order)
        )
    ).all()
    fields_by_branch: dict[str, list[dict[str, object]]] = {}
    for item, branch_code in fields:
        fields_by_branch.setdefault(branch_code, []).append({"code": item.code, "title": item.title})
    return {
        "cycles": [
            {
                "code": cycle.code,
                "title": cycle.title,
                "grades": [
                    {"number": grade.number, "title": grade.title}
                    for grade in grades
                    if grade.cycle_id == cycle.id
                ],
            }
            for cycle in cycles
        ],
        "branches": [
            {
                "code": branch.code,
                "title": branch.title,
                "min_grade": branch.min_grade,
                "max_grade": branch.max_grade,
                "fields": fields_by_branch.get(branch.code, []),
            }
            for branch in branches
        ],
    }


@router.get("/majors")
async def list_majors(session: AsyncSession = Depends(get_session)) -> list[dict[str, str]]:
    """Legacy theoretical-field endpoint retained for older frontend builds."""
    majors = (await session.scalars(select(Major).order_by(Major.id))).all()
    return [{"code": major.code, "title": major.title} for major in majors]


@router.get("/books")
async def list_books(
    grade_number: int = Query(ge=1, le=12),
    major_code: str | None = Query(None, max_length=64),
    session: AsyncSession = Depends(get_session),
    branch_code: str | None = Query(None, max_length=64),
    field_code: str | None = Query(None, max_length=64),
    academic_year_code: str | None = Query(None, max_length=24),
) -> list[dict[str, object]]:
    """List textbook editions that apply to the selected curriculum context.

    major_code is kept as a compatibility alias for the old theoretical-only selector.
    """
    grade = await session.scalar(select(Grade).where(Grade.number == grade_number))
    if grade is None:
        raise HTTPException(status_code=404, detail="grade not found")

    selected_branch: EducationBranch | None = None
    selected_field: FieldOfStudy | None = None
    selected_major: Major | None = None
    legacy_major_only = bool(major_code and branch_code is None and field_code is None)

    # major_code is an older name for field_code. When branch_code is supplied,
    # normalize it into the new selector instead of querying only Book.major_id.
    if major_code and branch_code is not None:
        if field_code is not None and field_code != major_code:
            raise HTTPException(status_code=422, detail="major_code and field_code must identify the same field")
        field_code = field_code or major_code
    elif major_code and branch_code is None:
        if grade.number < 10:
            raise HTTPException(status_code=422, detail="major selection is only valid for upper secondary grades")
        selected_major = await session.scalar(select(Major).where(Major.code == major_code))
        if selected_major is None:
            raise HTTPException(status_code=404, detail="major not found")
        # Compatibility path: older clients sent only a theoretical Major.code.
        branch_code = "theoretical"
        field_code = major_code

    if grade.number >= 10:
        if not branch_code:
            raise HTTPException(status_code=422, detail="برای پایه‌های دهم تا دوازدهم باید شاخهٔ تحصیلی انتخاب شود.")
        selected_branch = await session.scalar(
            select(EducationBranch).where(
                EducationBranch.code == branch_code,
                EducationBranch.is_active.is_(True),
            )
        )
        if selected_branch is None:
            raise HTTPException(status_code=404, detail="education branch not found")
        if not selected_branch.min_grade <= grade.number <= selected_branch.max_grade:
            raise HTTPException(status_code=422, detail="این شاخه برای پایهٔ انتخاب‌شده تعریف نشده است.")

        active_field_id = await session.scalar(
            select(FieldOfStudy.id)
            .where(
                FieldOfStudy.branch_id == selected_branch.id,
                FieldOfStudy.is_active.is_(True),
            )
            .limit(1)
        )
        if field_code:
            selected_field = await session.scalar(
                select(FieldOfStudy).where(
                    FieldOfStudy.code == field_code,
                    FieldOfStudy.branch_id == selected_branch.id,
                    FieldOfStudy.is_active.is_(True),
                )
            )
            if selected_field is None:
                raise HTTPException(status_code=404, detail="field of study not found")
        elif active_field_id is not None:
            raise HTTPException(status_code=422, detail="برای شاخهٔ انتخاب‌شده باید رشتهٔ تحصیلی نیز انتخاب شود.")
    elif branch_code or field_code:
        raise HTTPException(status_code=422, detail="انتخاب شاخه یا رشته برای پایه‌های ۱ تا ۹ مجاز نیست.")

    selected_year: AcademicYear | None = None
    if academic_year_code:
        selected_year = await session.scalar(
            select(AcademicYear).where(AcademicYear.code == academic_year_code)
        )
        if selected_year is None:
            raise HTTPException(status_code=404, detail="academic year not found")

    conditions = [
        Book.grade_id == grade.id,
        Book.status == BookStatus.ready,
    ]
    if selected_year is not None:
        conditions.append(Book.academic_year_id == selected_year.id)

    link_exists = exists(
        select(BookCurriculumLink.id).where(BookCurriculumLink.book_id == Book.id)
    )
    if selected_branch is not None:
        scope_terms = [
            and_(
                BookCurriculumLink.branch_id == selected_branch.id,
                BookCurriculumLink.field_of_study_id.is_(None),
            ),
            and_(
                BookCurriculumLink.branch_id.is_(None),
                BookCurriculumLink.field_of_study_id.is_(None),
            ),
        ]
        if selected_field is not None:
            scope_terms.append(BookCurriculumLink.field_of_study_id == selected_field.id)
            legacy_major = await session.scalar(
                select(Major).where(Major.code == selected_field.code)
            )
            legacy_field_match = Book.major_id == legacy_major.id if legacy_major else False
        else:
            legacy_field_match = False
        applicable_link = exists(
            select(BookCurriculumLink.id).where(
                BookCurriculumLink.book_id == Book.id,
                or_(*scope_terms),
            )
        )
        # Unmigrated legacy general books remain discoverable; edition-specific links
        # prevent a book assigned to another field from leaking into this selection.
        untouched_general = and_(~link_exists, Book.major_id.is_(None))
        conditions.append(or_(applicable_link, untouched_general, legacy_field_match))
    else:
        general_link = exists(
            select(BookCurriculumLink.id).where(
                BookCurriculumLink.book_id == Book.id,
                BookCurriculumLink.branch_id.is_(None),
                BookCurriculumLink.field_of_study_id.is_(None),
            )
        )
        untouched_general = and_(~link_exists, Book.major_id.is_(None))
        conditions.append(or_(general_link, untouched_general))

    books = (
        await session.scalars(select(Book).where(*conditions).order_by(Book.title, Book.id.desc()))
    ).all()
    if legacy_major_only and academic_year_code is None:
        return [
            {
                "id": book.id,
                "title": book.title,
                "grade_number": grade_number,
                "major_code": major_code,
                "status": book.status.value,
            }
            for book in books
        ]
    result: list[dict[str, object]] = []
    for book in books:
        book_year_code = academic_year_code
        book_year_id = getattr(book, "academic_year_id", None)
        if book_year_id is not None and hasattr(session, "get"):
            book_year = await session.get(AcademicYear, book_year_id)
            if book_year is not None:
                book_year_code = book_year.code
        result.append(
            {
                "id": book.id,
                "title": book.title,
                "grade_number": grade_number,
                "major_code": major_code or (selected_field.code if selected_field else "general"),
                "branch_code": selected_branch.code if selected_branch else None,
                "field_code": selected_field.code if selected_field else None,
                "academic_year_code": book_year_code,
                "edition_label": getattr(book, "edition_label", None),
                "print_year": getattr(book, "print_year", None),
                "publisher": getattr(book, "publisher", None),
                "status": book.status.value,
            }
        )
    return result


@router.get("/search")
async def search_curriculum(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=10, ge=1, le=25),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    term = q.strip()
    pattern = f"%{search_key(term)}%" if term else None

    book_stmt = (
        select(Book, Grade.number, Grade.title, Major.code, Major.title)
        .join(Grade, Book.grade_id == Grade.id)
        .outerjoin(Major, Book.major_id == Major.id)
        .where(Book.status == BookStatus.ready)
    )
    if pattern is not None:
        book_stmt = book_stmt.where(
            or_(
                sql_search_key(Book.title).like(pattern),
                sql_search_key(Grade.title).like(pattern),
                sql_search_key(Major.title).like(pattern),
            )
        )
    book_rows = (await session.execute(book_stmt.order_by(Book.title).limit(limit))).all()

    topic_stmt = (
        select(BookPage, Book.title, Grade.number, Major.code)
        .join(Book, BookPage.book_id == Book.id)
        .join(Grade, Book.grade_id == Grade.id)
        .outerjoin(Major, Book.major_id == Major.id)
        .where(Book.status == BookStatus.ready, BookPage.status == PageStatus.done)
    )
    if pattern is not None:
        topic_stmt = topic_stmt.where(
            or_(
                sql_search_key(BookPage.chapter_title).like(pattern),
                sql_search_key(BookPage.markdown_content).like(pattern),
                sql_search_key(Book.title).like(pattern),
            )
        )
    topic_rows = (
        await session.execute(topic_stmt.order_by(Book.id.desc(), BookPage.pdf_page_index.asc()).limit(limit))
    ).all()

    return {
        "query": term,
        "books": [
            {
                "id": book.id,
                "title": book.title,
                "grade_number": grade_num,
                "grade_title": grade_title,
                "major_code": major_code or "general",
                "major_title": major_title,
                "academic_year_id": getattr(book, "academic_year_id", None),
                "edition_label": getattr(book, "edition_label", None),
            }
            for book, grade_num, grade_title, major_code, major_title in book_rows
        ],
        "topics": [
            {
                "book_id": page.book_id,
                "book_title": book_title,
                "grade_number": grade_num,
                "major_code": major_code or "general",
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title,
                "printed_page_number": page.printed_page_number,
                "pdf_page_index": page.pdf_page_index,
            }
            for page, book_title, grade_num, major_code in topic_rows
        ],
    }


@router.get("/books/{book_id}/figures/{figure_id}/image")
async def student_figure_image(
    book_id: int,
    figure_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Read-only figure image for students. Only for books with status=ready."""
    await check_capability_access(session, "immersive_reader", current_user)
    book = await session.get(Book, book_id)
    if not is_student_visible_book(book):
        raise HTTPException(status_code=404, detail="کتاب آماده‌ای با این شناسه یافت نشد.")
    figure = await session.get(SourceFigure, figure_id)
    if figure is None or figure.book_id != book_id:
        raise HTTPException(status_code=404, detail="شکل یافت نشد.")
    root = figures_dir(book_id).resolve()
    path = Path(figure.image_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="فایل تصویر شکل در دسترس نیست.")
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
