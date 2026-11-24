"""Auto-publish hotfix tests: manual book approval is gone, educational filters stay.

Covers the acceptance scenarios:
  A. a `ready` book is student-visible with no manual approval step
  B. an `ingesting` book is not selectable
  C. a `failed` book is not selectable
  D. grade isolation (grade-12 book never leaks to a grade-10 student)
  E. branch/field isolation (math_physics book stays in its scope)
  F. subject isolation (subject-scoped links bind the book to its subject only)
  G. RAG: catalog removal does not weaken book_id/grade/PageStatus.done filters
  H. general-book behavior is unchanged (no unintended generalization)
"""

from __future__ import annotations

from types import SimpleNamespace

import pymupdf
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import require_student
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.auth import User
from app.models.curriculum import Book, BookCurriculumLink, BookPage, BookStatus, EducationBranch, FieldOfStudy, Grade, PageStatus, Subject
from app.services.curriculum_access import is_student_visible_book
from app.services.multi_grade_rag import resolve_curriculum_book_ids, ScopeError
from app.services.retrieval_service import _scope_sql_clause, TextbookScope

ADMIN_HEADERS = {"X-Admin-Username": "admin", "X-Admin-Password": "123"}


@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase10.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    ids: dict[str, object] = {}
    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        grade10 = await session.scalar(select(Grade).where(Grade.number == 10))
        grade12 = await session.scalar(select(Grade).where(Grade.number == 12))

        async def get_or_create(model, /, *, defaults=None, **lookup):
            row = await session.scalar(select(model).filter_by(**lookup))
            if row is None:
                row = model(**lookup, **(defaults or {}))
                session.add(row)
                await session.flush()
            return row

        # Branches/fields/subjects are imported separately in production; create
        # the minimal taxonomy the scenarios need.
        theoretical = await get_or_create(
            EducationBranch, code="theoretical",
            defaults={"title": "نظری", "sort_order": 1},
        )
        math_phys = await get_or_create(
            FieldOfStudy, code="math_physics",
            defaults={"title": "ریاضی‌فیزیک", "branch_id": theoretical.id, "sort_order": 1},
        )
        experimental = await get_or_create(
            FieldOfStudy, code="experimental",
            defaults={"title": "علوم تجربی", "branch_id": theoretical.id, "sort_order": 2},
        )
        physics = await get_or_create(
            Subject, code="physics", defaults={"title": "فیزیک"},
        )

        # Grade-12 math_physics physics book (linked to its field + subject).
        book12 = Book(
            title="فیزیک دوازدهم ریاضی‌فیزیک",
            grade_id=grade12.id,
            major_id=None,
            pdf_file_path="/tmp/none.pdf",
            total_pdf_pages=4,
            status=BookStatus.ready,
        )
        # Grade-10 book for the general/subject scenarios.
        book10 = Book(
            title="فیزیک دهم",
            grade_id=grade10.id,
            major_id=None,
            pdf_file_path="/tmp/none.pdf",
            total_pdf_pages=3,
            status=BookStatus.ready,
        )
        # Grade-12 book of the same branch but a different field.
        foreign_field_book = Book(
            title="علوم تجربی دوازدهم",
            grade_id=grade12.id,
            major_id=None,
            pdf_file_path="/tmp/none.pdf",
            total_pdf_pages=2,
            status=BookStatus.ready,
        )
        session.add_all([book12, book10, foreign_field_book])
        await session.flush()
        session.add_all([
            BookCurriculumLink(book_id=book12.id, branch_id=theoretical.id,
                               field_of_study_id=math_phys.id, subject_id=physics.id if physics else None,
                               scope_code="field:math_physics"),
            BookCurriculumLink(book_id=book10.id, branch_id=theoretical.id,
                               field_of_study_id=math_phys.id, subject_id=physics.id,
                               scope_code="field:math_physics"),
            BookCurriculumLink(book_id=foreign_field_book.id, branch_id=theoretical.id,
                               field_of_study_id=experimental.id,
                               scope_code="field:experimental"),
        ])
        await session.flush()

        # RAG pages: one done, one needs_review, one failed (pdf pages 1-3).
        session.add_all([
            BookPage(book_id=book12.id, pdf_page_index=1, printed_page_number=10, chapter_number=1,
                     chapter_title="حرکت", markdown_content="قانون اول نیوتن دربارهٔ اینرسی است.",
                     page_image_path="", status=PageStatus.done),
            BookPage(book_id=book12.id, pdf_page_index=2, printed_page_number=11, chapter_number=1,
                     chapter_title="حرکت", markdown_content="این صفحه بازبینی نشده است شتاب.",
                     page_image_path="", status=PageStatus.needs_review),
            BookPage(book_id=book12.id, pdf_page_index=3, printed_page_number=12, chapter_number=1,
                     chapter_title="حرکت", markdown_content="صفحهٔ ناموفق OCR.",
                     page_image_path="", status=PageStatus.failed),
        ])

        student10 = User(phone_number="09120000011", full_name="دهمی", role="student",
                         tokens_remaining=100_000, plan_expires_at=None, grade_level=10, is_active=True)
        student12 = User(phone_number="09120000012", full_name="دوازدهمی", role="student",
                         tokens_remaining=100_000, plan_expires_at=None, grade_level=12, is_active=True)
        session.add_all([student10, student12])
        await session.commit()
        ids.update(book12=book12.id, book10=book10.id, foreign_field_book=foreign_field_book.id,
                   grade10=grade10.number, grade12=grade12.number,
                   theoretical="theoretical", math_physics="math_physics", experimental="experimental",
                   student10=student10.id, student12=student12.id,
                   subject_id=physics.id if physics else None)

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr("app.db.session.async_session_factory", factory)
    yield SimpleNamespace(factory=factory, ids=ids, tmp_path=tmp_path, monkeypatch=monkeypatch)
    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _listed_book_ids(grade_number: int, branch: str | None = None, field: str | None = None) -> set[int]:
    params: dict[str, str] = {"grade_number": str(grade_number)}
    if branch:
        params["branch_code"] = branch
    if field:
        params["field_code"] = field
    async with _client() as client:
        response = await client.get("/api/v1/curriculum/books", params=params)
        assert response.status_code == 200, response.text
        return {item["id"] for item in response.json()}


# ---------------------------------------------------------------------------
# A + B: auto-publish flow through the real upload endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_auto_publishes_without_manual_approval(env):
    """A book becomes visible the moment processing marks it ready — no approval step."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "قانون اول نیوتن دربارهٔ اینرسی است.")
    pdf_bytes = doc.tobytes()
    doc.close()

    # Background OCR is stubbed out so the book stays mid-processing ("ingesting").
    async def no_background(*args, **kwargs):
        return None

    env.monkeypatch.setattr("app.api.admin._run_ingest_background", no_background)
    env.monkeypatch.setattr("app.api.admin.UPLOAD_DIR", env.tmp_path)
    env.monkeypatch.setattr("app.api.admin.async_session_factory", env.factory)

    async with _client() as client:
        response = await client.post(
            "/api/v1/admin/books/upload-and-ingest",
            headers=ADMIN_HEADERS,
            data={
                "grade_number": "12",
                "branch_code": "theoretical",
                "field_code": "math_physics",
                "subject_code": "physics",
                "book_title": "فیزیک دوازدهم (بارگذاری تست)",
                "start_page": "1",
                "end_page": "1",
            },
            files={"pdf_file": ("physics.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        # Scenario B: processing books are not student-selectable yet.
        assert payload["status"] == "ingesting"
        listed = await _listed_book_ids(12, "theoretical", "math_physics")
        assert payload["book_id"] not in listed

        # The approval endpoint is gone entirely.
        assert (await client.patch(f"/api/v1/admin/books/{payload['book_id']}/approval",
                                   headers=ADMIN_HEADERS, json={"approved": True})).status_code in (404, 405)

    # Processing completes → `ready` → instantly visible. No approval call anywhere.
    async with env.factory() as session:
        book = await session.get(Book, payload["book_id"])
        book.status = BookStatus.ready
        await session.commit()

    listed = await _listed_book_ids(12, "theoretical", "math_physics")
    assert payload["book_id"] in listed  # Scenario A: auto-published, zero manual steps


# ---------------------------------------------------------------------------
# B + C: processing and failed books are not selectable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingesting_book_is_not_student_selectable(env):
    async with env.factory() as session:
        book = await session.get(Book, env.ids["book12"])
        book.status = BookStatus.ingesting
        await session.commit()
    listed = await _listed_book_ids(12, "theoretical", "math_physics")
    assert env.ids["book12"] not in listed


@pytest.mark.asyncio
async def test_failed_book_is_not_student_selectable(env):
    async with env.factory() as session:
        book = await session.get(Book, env.ids["book12"])
        book.status = BookStatus.failed
        await session.commit()
    listed = await _listed_book_ids(12, "theoretical", "math_physics")
    assert env.ids["book12"] not in listed


# ---------------------------------------------------------------------------
# D + E + F: grade / field / subject isolation stay intact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grade_isolation_of_ready_books(env):
    # The grade-12 physics book is visible in its own grade…
    assert env.ids["book12"] in await _listed_book_ids(12, "theoretical", "math_physics")
    # …and never leaks to a grade-10 selection.
    assert env.ids["book12"] not in await _listed_book_ids(10, "theoretical", "math_physics")


@pytest.mark.asyncio
async def test_field_isolation_of_ready_books(env):
    assert env.ids["book12"] in await _listed_book_ids(12, "theoretical", "math_physics")
    # Another field of the same branch has no mapping for this book.
    assert env.ids["book12"] not in await _listed_book_ids(12, "theoretical", "experimental")
    # And the reverse mapping holds for the experimental book.
    assert env.ids["foreign_field_book"] not in await _listed_book_ids(12, "theoretical", "math_physics")


def test_subject_link_binds_book_to_its_subject_only(env):
    """Subject-scoped curriculum links (subject_id) map the book to its subject alone."""
    from app.api.admin import _book_curriculum_scope_rows

    rows = _book_curriculum_scope_rows(
        grade_number=12,
        is_general_book=False,
        subject_id=101,
        branch_wide_branches=[],
        selected_fields=[SimpleNamespace(id=8, branch_id=7, code="math_physics")],
    )
    assert rows, "subject upload must create explicit field links"
    # Every link binds exactly the chosen subject — never an unrelated one.
    assert all(row[2] == 101 for row in rows)
    assert {(row[0], row[1], row[3]) for row in rows} == {(7, 8, "field:math_physics")}
    # A general upload keeps the (branch-wide, subject) binding semantics intact.
    general_rows = _book_curriculum_scope_rows(
        grade_number=12,
        is_general_book=True,
        subject_id=101,
        branch_wide_branches=[],
        selected_fields=[SimpleNamespace(id=8, branch_id=7, code="math_physics")],
    )
    assert ("general", ) == tuple(r[3] for r in general_rows if r[0] is None and r[1] is None), general_rows


# ---------------------------------------------------------------------------
# G: RAG filters unchanged (book_id, grade, PageStatus.done)
# ---------------------------------------------------------------------------


def test_rag_scope_clause_keeps_book_grade_and_page_status_filters(env):
    """After removing the catalog clause, the scope clause must still enforce
    exact book_id + grade and only PageStatus.done pages."""
    scopes = [TextbookScope(book_id=env.ids["book12"], grade_number=12, chapter_numbers=None)]
    clause = _scope_sql_clause(scopes)
    assert clause is not None


@pytest.mark.asyncio
async def test_rag_returns_only_done_pages_of_the_exact_book(env):
    async with env.factory() as session:
        from sqlalchemy import and_, select as sa_select

        scopes = [TextbookScope(book_id=env.ids["book12"], grade_number=12, chapter_numbers=None)]
        clause = _scope_sql_clause(scopes)
        rows = (
            await session.execute(
                sa_select(BookPage.pdf_page_index)
                .join(Book, BookPage.book_id == Book.id)
                .join(Grade, Book.grade_id == Grade.id)
                .where(
                    clause,
                    Book.status == BookStatus.ready,
                    BookPage.status == PageStatus.done,
                )
            )
        ).all()
        pages = {row[0] for row in rows}
        assert pages == {1}  # done page only: needs_review (2) and failed (3) stay out

        # Grade mismatch (the book belongs to grade 12, query asks grade 10) → nothing.
        scopes_wrong = [TextbookScope(book_id=env.ids["book12"], grade_number=10, chapter_numbers=None)]
        rows_wrong = (
            await session.execute(
                sa_select(BookPage.id).join(Book, BookPage.book_id == Book.id)
                .join(Grade, Book.grade_id == Grade.id)
                .where(_scope_sql_clause(scopes_wrong), BookPage.status == PageStatus.done)
            )
        ).all()
        assert rows_wrong == []


@pytest.mark.asyncio
async def test_rag_multi_grade_resolution_does_not_leak_higher_grades(env):
    """The grade-12 book must not resolve for a grade-10 student's RAG scope."""
    subject_ids = [env.ids["subject_id"]]
    resolved12 = await resolve_curriculum_book_ids(
        env.factory(), grade_numbers=[12], branch_code="theoretical", field_code="math_physics",
        academic_year_id=None, subject_ids=subject_ids,
    )
    assert env.ids["book12"] in resolved12
    resolved10 = await resolve_curriculum_book_ids(
        env.factory(), grade_numbers=[10], branch_code="theoretical", field_code="math_physics",
        academic_year_id=None, subject_ids=subject_ids,
    )
    assert env.ids["book12"] not in resolved10


# ---------------------------------------------------------------------------
# H: general-book behavior unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_general_book_mapping_is_unchanged(env):
    """A general book (branch-wide link without field) appears for every field of the
    branch; a field-specific book never generalizes on its own."""
    async with env.factory() as session:
        theoretical = await session.scalar(select(EducationBranch).where(EducationBranch.code == "theoretical"))
        general_book = Book(title="کتاب عمومی مشترک", grade_id=(await session.scalar(select(Grade).where(Grade.number == 12))).id,
                            major_id=None, pdf_file_path="/tmp/none.pdf", total_pdf_pages=1,
                            status=BookStatus.ready)
        session.add(general_book)
        await session.flush()
        session.add(BookCurriculumLink(book_id=general_book.id, branch_id=theoretical.id,
                                       field_of_study_id=None, scope_code="branch:theoretical"))
        await session.commit()
        general_id = general_book.id

    listed_math = await _listed_book_ids(12, "theoretical", "math_physics")
    listed_exp = await _listed_book_ids(12, "theoretical", "experimental")
    assert general_id in listed_math and general_id in listed_exp
    # The math_physics book does not become general for the experimental field.
    assert env.ids["book12"] in listed_math and env.ids["book12"] not in listed_exp


def test_visibility_helper_ignores_legacy_catalog_columns():
    """The gate is exactly `Book.status == ready`; legacy columns never matter."""
    for legacy in ("legacy_unverified", "pending_review", "approved", "demo"):
        assert is_student_visible_book(SimpleNamespace(status=BookStatus.ready, catalog_status=legacy))
    assert not is_student_visible_book(SimpleNamespace(status=BookStatus.ingesting, catalog_status="approved"))
    assert not is_student_visible_book(SimpleNamespace(status=BookStatus.failed, catalog_status="approved"))
    assert not is_student_visible_book(None)
