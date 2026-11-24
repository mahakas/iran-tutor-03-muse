"""Phase 4 tests.

- Multi-grade retrieval (>= 2 grades) and concept-link scope rules.
- L1/L2/L3 memory updates, injection, and admin edit/delete.
- Auto-Mode router decisions audited in ai_audit_logs.
- Stop / Regenerate streaming leaves no orphan rows; cursor resume works.
- Chat search, soft delete (Recycle Bin), restore, and permanent delete.

No network I/O: every model call is a deterministic fake at the gateway level,
and the database is SQLite.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import require_student
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.auth import User
from app.models.chat import ChatSession
from app.models.concepts import ConceptLink
from app.models.curriculum import AcademicYear, Book, BookCurriculumLink, BookPage, BookStatus, EducationBranch, FieldOfStudy, Grade, Major, PageStatus, Subject
from app.models.governance import AiAuditLog
from app.models.learner_memory import LearnerMemory
from app.services import (
    ai_gateway,
    capability_service,
    chat_stream,
    intent_router,
    learner_memory_service as lms,
    multi_grade_rag,
    retrieval_service,
    skill_seed,
    tutor_turns,
)
from app.services.multi_grade_rag import ScopeError

ADMIN_HEADERS = {"X-Admin-Username": "admin", "X-Admin-Password": "123"}
NOW = datetime.now(timezone.utc)
ANSWER = "نیرو عاملی است که حرکت را تغییر می‌دهد. " * 6


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase4.sqlite3'}")
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
        await capability_service.seed_capabilities(session)
        await skill_seed.seed_skills(session)
        major = await session.scalar(select(Major).where(Major.code == "math_physics"))
        branch = await session.scalar(
            select(EducationBranch).where(EducationBranch.code == "theoretical")
        )
        field = await session.scalar(
            select(FieldOfStudy).where(FieldOfStudy.code == "math_physics")
        )
        academic_year = AcademicYear(
            code="1405-1406",
            title="۱۴۰۵–۱۴۰۶",
            is_active=True,
        )
        subject = Subject(code="physics", title="فیزیک", is_active=True)
        session.add_all([academic_year, subject])
        await session.flush()
        books: dict[int, Book] = {}
        for grade_number, chapter, text in (
            (10, 3, "نیرو و حرکت در فیزیک دهم، نیرو کشش یا هل دادن است"),
            (11, 2, "نیرو در فیزیک یازدهم با شتاب رابطه دارد"),
            (12, 1, "قانون دوم نیوتون: نیروی خالص برابر جرم ضربدر شتاب است"),
        ):
            grade = await session.scalar(select(Grade).where(Grade.number == grade_number))
            book = Book(
                title=f"فیزیک پایه {grade_number}",
                grade_id=grade.id,
                major_id=major.id,
                academic_year_id=academic_year.id,
                pdf_file_path="/tmp/none.pdf",
                total_pdf_pages=5,
                status=BookStatus.ready,
                catalog_status="approved",
            )
            session.add(book)
            await session.flush()
            session.add(
                BookCurriculumLink(
                    book_id=book.id,
                    branch_id=branch.id,
                    field_of_study_id=field.id,
                    subject_id=subject.id,
                    scope_code="field:math_physics:physics",
                )
            )
            session.add(
                BookPage(
                    book_id=book.id,
                    pdf_page_index=1,
                    printed_page_number=20 + grade_number,
                    chapter_number=chapter,
                    chapter_title=f"فصل {chapter}",
                    markdown_content=text,
                    page_image_path="/tmp/none.png",
                    status=PageStatus.done,
                )
            )
            books[grade_number] = book
        student = User(
            phone_number="09121000001", full_name="دانش‌آموز", role="student",
            grade_level=12,
            tokens_remaining=1_000_000, plan_expires_at=NOW + timedelta(days=30), is_active=True,
        )
        other = User(
            phone_number="09121000002", full_name="دیگری", role="student",
            tokens_remaining=1_000_000, plan_expires_at=NOW + timedelta(days=30), is_active=True,
        )
        session.add_all([student, other])
        await session.flush()
        ids.update(
            student_id=student.id,
            other_id=other.id,
            book10=books[10].id,
            book11=books[11].id,
            book12=books[12].id,
            subject_id=subject.id,
        )
        await session.commit()

    async def override_get_session():
        async with factory() as session:
            yield session

    async def override_student():
        async with factory() as session:
            return await session.get(User, ids["student_id"])

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_student] = override_student
    from app.db import session as db_session_mod

    monkeypatch.setattr(db_session_mod, "async_session_factory", factory)
    monkeypatch.setattr(ai_gateway, "async_session_factory", factory)
    monkeypatch.setattr(chat_stream, "async_session_factory", factory)
    monkeypatch.setattr(lms, "async_session_factory", factory)
    monkeypatch.setattr(retrieval_service, "async_session_factory", factory)
    # Demo lexical branch: deterministic token overlap, runs on SQLite.
    monkeypatch.setattr(
        retrieval_service, "get_settings",
        lambda: SimpleNamespace(demo_mode=True, vector_backend="qdrant", qdrant_collection="t"),
    )
    monkeypatch.setattr(
        ai_gateway, "get_settings",
        lambda: SimpleNamespace(tutor_model="test-model", llm_timeout=5),
    )
    monkeypatch.setattr(chat_stream, "CHUNK_CHARS", 40)
    monkeypatch.setattr(chat_stream, "CHUNK_DELAY_SECONDS", 0)
    chat_stream.reset_stream_store_for_tests(None)

    fake = SimpleNamespace(
        text_calls=[], json_calls=[], text_reply=ANSWER, json_reply=None, text_delay=0.0,
    )

    async def fake_complete_text(model, messages):
        fake.text_calls.append(messages)
        if fake.text_delay:
            await asyncio.sleep(fake.text_delay)
        return fake.text_reply

    async def fake_stream_text(model, messages, on_chunk):
        fake.text_calls.append(messages)
        if fake.text_delay:
            await asyncio.sleep(fake.text_delay)
        content = fake.text_reply
        for start in range(0, len(content), 40):
            await on_chunk(content[start : start + 40])
        return content

    async def fake_complete_json(model, messages):
        fake.json_calls.append(messages)
        if callable(fake.json_reply):
            return fake.json_reply(messages)
        return fake.json_reply or {"facts": []}

    monkeypatch.setattr(ai_gateway, "complete_text", fake_complete_text)
    monkeypatch.setattr(ai_gateway, "stream_text", fake_stream_text)
    monkeypatch.setattr(ai_gateway, "complete_json", fake_complete_json)

    env_obj = SimpleNamespace(factory=factory, ids=ids, fake=fake)
    yield env_obj
    chat_stream.reset_stream_store_for_tests(None)
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_student, None)
    await engine.dispose()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _count(factory, model, *where) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


# ---------------------------------------------------------------------------
# 1. Multi-grade retrieval
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multi_grade_search_returns_pages_from_at_least_two_grades(env):
    async with env.factory() as session:
        result = await multi_grade_rag.search_multi_grade(
            session,
            "نیرو",
            grade_numbers=[10, 11, 12],
            book_ids=[env.ids["book10"], env.ids["book11"], env.ids["book12"]],
            top_k=6,
            expand_links=False,
        )
    grades = {item["grade_number"] for item in result["results"]}
    assert len(grades) >= 2
    assert {10, 11, 12} >= grades
    # Every citation carries its own book and printed page (textbook fidelity).
    for item in result["results"]:
        assert item["book_title"].startswith("فیزیک پایه")
        assert item["printed_page_number"] is not None


@pytest.mark.asyncio
async def test_multi_grade_book_resolution_enforces_branch_field_year_and_subject(env):
    async with env.factory() as session:
        year = await session.scalar(
            select(AcademicYear).where(AcademicYear.code == "1405-1406")
        )
        grade10 = await session.scalar(select(Grade).where(Grade.number == 10))
        foreign_branch = EducationBranch(
            code="technical_scope_test",
            title="شاخهٔ فنی آزمون",
            min_grade=10,
            max_grade=12,
            is_active=True,
        )
        session.add(foreign_branch)
        await session.flush()
        foreign_field = FieldOfStudy(
            branch_id=foreign_branch.id,
            code="electronics_scope_test",
            title="الکترونیک آزمون",
            is_active=True,
        )
        session.add(foreign_field)
        await session.flush()
        same_branch_other_field = await session.scalar(
            select(FieldOfStudy).where(FieldOfStudy.code == "islamic_studies")
        )
        theoretical_branch = await session.scalar(
            select(EducationBranch).where(EducationBranch.code == "theoretical")
        )
        selected_field = await session.scalar(
            select(FieldOfStudy).where(FieldOfStudy.code == "math_physics")
        )

        foreign_book = Book(
            title="کتاب فنی خارج از رشتهٔ انتخابی",
            grade_id=grade10.id,
            academic_year_id=year.id,
            pdf_file_path="/tmp/foreign.pdf",
            total_pdf_pages=1,
            status=BookStatus.ready,
            catalog_status="approved",
        )
        same_branch_foreign_field_book = Book(
            title="کتاب رشتهٔ دیگر در همان شاخه",
            grade_id=grade10.id,
            academic_year_id=year.id,
            pdf_file_path="/tmp/same-branch-foreign-field.pdf",
            total_pdf_pages=1,
            status=BookStatus.ready,
            catalog_status="approved",
        )
        hidden_book = Book(
            title="کتاب قدیمی تأییدنشده",
            grade_id=grade10.id,
            academic_year_id=year.id,
            pdf_file_path="/tmp/hidden.pdf",
            total_pdf_pages=1,
            status=BookStatus.ready,
            catalog_status="legacy_unverified",
        )
        pending_book = Book(
            title="کتاب در انتظار بررسی",
            grade_id=grade10.id,
            academic_year_id=year.id,
            pdf_file_path="/tmp/pending.pdf",
            total_pdf_pages=1,
            status=BookStatus.ready,
            catalog_status="pending_review",
        )
        missing_subject_book = Book(
            title="کتاب بدون پیوند رسمی درس",
            grade_id=grade10.id,
            academic_year_id=year.id,
            pdf_file_path="/tmp/missing-subject.pdf",
            total_pdf_pages=1,
            status=BookStatus.ready,
            catalog_status="approved",
        )
        session.add_all(
            [foreign_book, same_branch_foreign_field_book, hidden_book, pending_book, missing_subject_book]
        )
        await session.flush()
        session.add_all(
            [
                BookCurriculumLink(
                    book_id=foreign_book.id,
                    branch_id=foreign_branch.id,
                    field_of_study_id=foreign_field.id,
                    scope_code="field:electronics_scope_test",
                ),
                BookCurriculumLink(
                    book_id=same_branch_foreign_field_book.id,
                    branch_id=theoretical_branch.id,
                    field_of_study_id=same_branch_other_field.id,
                    scope_code="field:islamic_studies",
                ),
                BookCurriculumLink(
                    book_id=missing_subject_book.id,
                    branch_id=theoretical_branch.id,
                    field_of_study_id=selected_field.id,
                    subject_id=None,
                    scope_code="field:math_physics:unmapped-subject",
                ),
            ]
        )
        session.add_all(
            [
                BookCurriculumLink(
                    book_id=hidden_book.id,
                    branch_id=(await session.scalar(
                        select(EducationBranch).where(EducationBranch.code == "theoretical")
                    )).id,
                    field_of_study_id=(await session.scalar(
                        select(FieldOfStudy).where(FieldOfStudy.code == "math_physics")
                    )).id,
                    scope_code="field:legacy_hidden",
                ),
                BookCurriculumLink(
                    book_id=pending_book.id,
                    branch_id=(await session.scalar(
                        select(EducationBranch).where(EducationBranch.code == "theoretical")
                    )).id,
                    field_of_study_id=(await session.scalar(
                        select(FieldOfStudy).where(FieldOfStudy.code == "math_physics")
                    )).id,
                    scope_code="field:pending_hidden",
                ),
            ]
        )
        await session.commit()

        resolved = await multi_grade_rag.resolve_curriculum_book_ids(
            session,
            grade_numbers=[10, 11, 12],
            branch_code="theoretical",
            field_code="math_physics",
            academic_year_id=year.id,
            subject_ids=[env.ids["subject_id"]],
        )

        assert set(resolved) == {
            env.ids["book10"],
            env.ids["book11"],
            env.ids["book12"],
        }
        assert foreign_book.id not in resolved
        assert same_branch_foreign_field_book.id not in resolved
        # Auto-publish hotfix: catalog_status no longer gates resolution — these two
        # stay out only because their links carry no subject mapping at all.
        assert hidden_book.id not in resolved
        assert pending_book.id not in resolved
        assert missing_subject_book.id not in resolved

        with pytest.raises(ScopeError):
            await multi_grade_rag.resolve_curriculum_book_ids(
                session,
                grade_numbers=[10, 11, 12],
                branch_code="theoretical",
                field_code="math_physics",
                academic_year_id=year.id,
                subject_ids=[env.ids["subject_id"]],
                requested_book_ids=[foreign_book.id],
            )

        with pytest.raises(ScopeError):
            await multi_grade_rag.resolve_curriculum_book_ids(
                session,
                grade_numbers=[10, 11, 12],
                branch_code="theoretical",
                field_code="math_physics",
                academic_year_id=year.id + 1,
                subject_ids=[env.ids["subject_id"]],
            )

        # Branches with active fields must not silently fall back to branch-wide scope.
        with pytest.raises(ScopeError, match="field of study is required"):
            await multi_grade_rag.resolve_curriculum_book_ids(
                session,
                grade_numbers=[10, 11, 12],
                branch_code="technical_scope_test",
                field_code=None,
                academic_year_id=year.id,
                subject_ids=[env.ids["subject_id"]],
            )


@pytest.mark.asyncio
async def test_multi_grade_resolution_caps_automatically_matched_books(env):
    async with env.factory() as session:
        year = await session.scalar(
            select(AcademicYear).where(AcademicYear.code == "1405-1406")
        )
        grade10 = await session.scalar(select(Grade).where(Grade.number == 10))
        branch = await session.scalar(
            select(EducationBranch).where(EducationBranch.code == "theoretical")
        )
        field = await session.scalar(
            select(FieldOfStudy).where(FieldOfStudy.code == "math_physics")
        )
        for index in range(10):
            book = Book(
                title=f"کتاب تکمیلی فیزیک {index}",
                grade_id=grade10.id,
                major_id=None,
                academic_year_id=year.id,
                pdf_file_path=f"/tmp/extra-{index}.pdf",
                total_pdf_pages=1,
                status=BookStatus.ready,
                catalog_status="approved",
            )
            session.add(book)
            await session.flush()
            session.add(
                BookCurriculumLink(
                    book_id=book.id,
                    branch_id=branch.id,
                    field_of_study_id=field.id,
                    subject_id=env.ids["subject_id"],
                    scope_code=f"field:math_physics:extra:{index}",
                )
            )
        await session.commit()

        with pytest.raises(ScopeError, match="too many textbooks"):
            await multi_grade_rag.resolve_curriculum_book_ids(
                session,
                grade_numbers=[10, 11, 12],
                branch_code="theoretical",
                field_code="math_physics",
                academic_year_id=year.id,
                subject_ids=[env.ids["subject_id"]],
            )


@pytest.mark.asyncio
async def test_grade_filter_is_strict_and_never_widened(env):
    async with env.factory() as session:
        result = await multi_grade_rag.search_multi_grade(
            session,
            "نیرو",
            grade_numbers=[11],
            book_ids=[env.ids["book11"]],
            expand_links=False,
        )
    assert result["results"]
    assert {item["grade_number"] for item in result["results"]} == {11}


@pytest.mark.asyncio
async def test_build_scopes_rejects_bad_grade_and_foreign_book(env):
    async with env.factory() as session:
        with pytest.raises(ScopeError):
            await multi_grade_rag.build_scopes(
                session, grade_numbers=[9], book_ids=[env.ids["book10"]]
            )
        with pytest.raises(ScopeError):
            await multi_grade_rag.build_scopes(
                session, grade_numbers=[10], book_ids=[env.ids["book12"]]
            )


@pytest.mark.asyncio
async def test_concept_link_expands_only_to_selected_grades(env):
    async with env.factory() as session:
        session.add(
            ConceptLink(
                source_book_id=env.ids["book10"], source_chapter=3,
                target_book_id=env.ids["book12"], target_chapter=1,
                relation="same_concept", label_fa="نیرو و قانون دوم",
            )
        )
        await session.commit()

    async with env.factory() as session:
        allowed_both = await multi_grade_rag.expand_with_concept_links(
            session,
            seeds=[(env.ids["book10"], 3)],
            allowed_grades=[10, 12],
            allowed_book_ids={env.ids["book10"], env.ids["book12"]},
        )
        allowed_ten = await multi_grade_rag.expand_with_concept_links(
            session,
            seeds=[(env.ids["book10"], 3)],
            allowed_grades=[10],
            allowed_book_ids={env.ids["book10"]},
        )
        disallowed_book = await multi_grade_rag.expand_with_concept_links(
            session,
            seeds=[(env.ids["book10"], 3)],
            allowed_grades=[10, 12],
            allowed_book_ids={env.ids["book10"]},
        )
    assert len(allowed_both) == 1
    assert allowed_both[0].grade_number == 12
    assert allowed_both[0].chapter_numbers == frozenset({1})
    assert allowed_ten == []  # the grade-12 filter is not silently widened
    assert disallowed_book == []  # a valid grade cannot widen the authorized book allowlist


@pytest.mark.asyncio
async def test_chapter_and_printed_page_lookup(env):
    async with env.factory() as session:
        by_chapter = await multi_grade_rag.lookup_pages(
            session, book_id=env.ids["book11"], chapter_number=2
        )
        by_page = await multi_grade_rag.lookup_pages(
            session, book_id=env.ids["book11"], printed_page_number=31
        )
        none = await multi_grade_rag.lookup_pages(
            session, book_id=env.ids["book11"], printed_page_number=999
        )
    assert len(by_chapter) == 1 and by_chapter[0].chapter_number == 2
    assert len(by_page) == 1
    assert none == []


@pytest.mark.asyncio
async def test_ask_endpoint_multi_grade_cites_two_grades(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/tutor/ask",
            json={
                "query": "نیرو",
                "grade_number": None,
                "grade_numbers": [10, 11, 12],
                "book_id": env.ids["book12"],
                "branch_code": "theoretical",
                "major_code": "math_physics",
                "top_k": 6,
                "mode": "tutor",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    cited_grades = {source["grade_number"] for source in body["sources"]}
    assert len(cited_grades) >= 2
    assert body["scope_count"] == 3
    assert "پایه" in body["answer"]


@pytest.mark.asyncio
async def test_audio_tutor_accepts_and_validates_education_branch(env, monkeypatch):
    from app.api import tutor as tutor_api

    seen: dict[str, object] = {}
    original_resolve_scope = tutor_api.resolve_book_scope

    async def tracked_resolve_scope(*args, **kwargs):
        seen["branch_code"] = kwargs.get("branch_code")
        return await original_resolve_scope(*args, **kwargs)

    async def no_capability_gate(*args, **kwargs):
        return None

    async def no_quota_gate(*args, **kwargs):
        return None

    async def no_attachment(*args, **kwargs):
        return None

    async def fake_audio_answer(**kwargs):
        return {"answer": "پاسخ مبتنی بر کتاب", "sources": []}

    monkeypatch.setattr(tutor_api, "resolve_book_scope", tracked_resolve_scope)
    monkeypatch.setattr(tutor_api, "check_capability_access", no_capability_gate)
    monkeypatch.setattr(tutor_api, "enforce_ai_quota", no_quota_gate)
    monkeypatch.setattr(tutor_api, "_maybe_store_tutor_attachment", no_attachment)
    monkeypatch.setattr(tutor_api, "verify_audio", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tutor_api, "answer_audio_question", fake_audio_answer)

    async with _client() as client:
        response = await client.post(
            "/api/v1/tutor/ask-audio",
            files={"audio": ("question.wav", b"audio", "audio/wav")},
            data={
                "grade_number": "12",
                "book_id": str(env.ids["book12"]),
                "major_code": "math_physics",
                "branch_code": "theoretical",
                "mode": "tutor",
            },
        )

    assert response.status_code == 200, response.text
    assert seen["branch_code"] == "theoretical"
    assert response.json()["answer"] == "پاسخ مبتنی بر کتاب"


@pytest.mark.asyncio
async def test_single_book_tutor_and_exam_respect_student_grade_level(env):
    async with env.factory() as session:
        student = await session.get(User, env.ids["student_id"])
        student.grade_level = 10
        await session.commit()

    async with _client() as client:
        tutor_response = await client.post(
            "/api/v1/tutor/ask",
            json={
                "query": "قانون دوم نیوتون",
                "grade_number": 12,
                "book_id": env.ids["book12"],
                "branch_code": "theoretical",
                "major_code": "math_physics",
                "mode": "tutor",
            },
        )
        exam_response = await client.post(
            "/api/v1/exams",
            json={
                "grade_number": 12,
                "book_id": env.ids["book12"],
                "branch_code": "theoretical",
                "major_code": "math_physics",
                "question_count": 5,
                "time_limit_minutes": 15,
                "exam_type": "konkoor",
            },
        )
        reader_response = await client.get(f"/api/v1/immersive/books/{env.ids['book12']}")
        mastery_response = await client.get(f"/api/v1/mastery/books/{env.ids['book12']}")

    assert tutor_response.status_code == 422
    assert exam_response.status_code == 422
    assert reader_response.status_code == 422
    assert mastery_response.status_code == 422


@pytest.mark.asyncio
async def test_multi_grade_endpoint_enforces_student_grade_ceiling(env):
    async with env.factory() as session:
        student = await session.get(User, env.ids["student_id"])
        student.grade_level = 10
        await session.commit()

    async with _client() as client:
        too_high_anchor = await client.post(
            "/api/v1/tutor/ask",
            json={
                "query": "نیرو",
                "grade_numbers": [10, 12],
                "book_id": env.ids["book12"],
                "branch_code": "theoretical",
                "major_code": "math_physics",
            },
        )
        too_high_cross_grade = await client.post(
            "/api/v1/tutor/ask",
            json={
                "query": "نیرو",
                "grade_numbers": [10, 11],
                "book_id": env.ids["book10"],
                "branch_code": "theoretical",
                "major_code": "math_physics",
            },
        )

    assert too_high_anchor.status_code == 422
    assert too_high_cross_grade.status_code == 422


@pytest.mark.asyncio
async def test_multi_grade_unknown_profile_uses_anchor_grade_as_ceiling(env):
    async with env.factory() as session:
        student = await session.get(User, env.ids["student_id"])
        student.grade_level = None
        await session.commit()

    async with _client() as client:
        resp = await client.post(
            "/api/v1/tutor/ask",
            json={
                "query": "نیرو",
                "grade_numbers": [10, 12],
                "book_id": env.ids["book10"],
                "branch_code": "theoretical",
                "major_code": "math_physics",
            },
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_multi_grade_endpoint_requires_anchor_and_branch(env):
    async with _client() as client:
        no_anchor = await client.post(
            "/api/v1/tutor/ask",
            json={"query": "نیرو", "grade_numbers": [10, 11, 12]},
        )
        no_branch = await client.post(
            "/api/v1/tutor/ask",
            json={
                "query": "نیرو",
                "grade_numbers": [10, 11, 12],
                "book_id": env.ids["book12"],
                "major_code": "math_physics",
            },
        )
        wrong_field_branch = await client.post(
            "/api/v1/tutor/ask",
            json={
                "query": "نیرو",
                "grade_numbers": [10, 11, 12],
                "book_id": env.ids["book12"],
                "branch_code": "technical_vocational",
                "major_code": "math_physics",
            },
        )

    assert no_anchor.status_code == 422
    assert no_branch.status_code == 422
    assert wrong_field_branch.status_code == 422


@pytest.mark.asyncio
async def test_ask_endpoint_rejects_missing_scope(env):
    async with _client() as client:
        resp = await client.post("/api/v1/tutor/ask", json={"query": "نیرو", "mode": "tutor"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 2. Learner memory: L1 / L2 / L3, injection, admin edit
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_l2_upsert_increments_evidence_and_respects_admin_edit(env):
    async with env.factory() as session:
        row = await lms.upsert_l2_fact(
            session, user_id=env.ids["student_id"], kind="weak", topic="قانون دوم نیوتون",
            content_fa="در تشخیص نیروی خالص اشتباه می‌کند.", book_id=env.ids["book12"],
            chapter_number=1, session_id=None, source_type="chat",
        )
        await session.commit()
        row_id = row.id
    async with env.factory() as session:
        again = await lms.upsert_l2_fact(
            session, user_id=env.ids["student_id"], kind="mastered", topic="قانون دوم نیوتون",
            content_fa="حالا درست حل می‌کند.", book_id=env.ids["book12"],
            chapter_number=1, session_id=None, source_type="chat",
        )
        assert again.id == row_id
        assert again.evidence_count == 2
        assert again.kind == "mastered"
        await session.commit()
    # Admin edits the wording: later automatic evidence must not overwrite it.
    async with _client() as client:
        put = await client.put(
            f"/api/v1/admin/users/{env.ids['student_id']}/memory",
            headers=ADMIN_HEADERS,
            json={"items": [{"id": row_id, "layer": "L2", "kind": "weak",
                             "content_fa": "ویرایش مدیر: نیاز به تمرین دارد."}]},
        )
    assert put.status_code == 200, put.text
    async with env.factory() as session:
        await lms.upsert_l2_fact(
            session, user_id=env.ids["student_id"], kind="note", topic="قانون دوم نیوتون",
            content_fa="متن خودکار جدید", book_id=env.ids["book12"],
            chapter_number=1, session_id=None, source_type="chat",
        )
        await session.commit()
        row = await session.get(LearnerMemory, row_id)
        assert row.content_fa == "ویرایش مدیر: نیاز به تمرین دارد."
        assert row.edited_by_admin is True
        assert row.evidence_count == 3


@pytest.mark.asyncio
async def test_l3_profile_rolls_up_l2_and_context_injects_it(env):
    async with env.factory() as session:
        await lms.upsert_l2_fact(
            session, user_id=env.ids["student_id"], kind="mastered", topic="نیرو",
            content_fa="نیرو را خوب می‌شناسد.", book_id=env.ids["book10"],
            chapter_number=3, session_id=None, source_type="chat",
        )
        await lms.upsert_l2_fact(
            session, user_id=env.ids["student_id"], kind="weak", topic="شتاب",
            content_fa="شتاب را با سرعت اشتباه می‌گیرد.", book_id=env.ids["book11"],
            chapter_number=2, session_id=None, source_type="quiz",
        )
        profile = await lms.rebuild_l3_profile(session, env.ids["student_id"])
        await session.commit()
        assert "شتاب" in profile.content_fa
        assert profile.data_json["chapters_seen"] == 2
        assert profile.data_json["weak_topics"] == ["شتاب"]

    async with env.factory() as session:
        context = await lms.build_memory_context(session, env.ids["student_id"], env.ids["book11"])
    assert "حافظهٔ یادگیرنده" in context
    assert "شتاب را با سرعت" in context
    assert "نیرو را خوب" not in context  # book-scoped L2 injection


@pytest.mark.asyncio
async def test_l1_trace_is_windowed_per_session(env):
    async with env.factory() as session:
        for index in range(lms.L1_WINDOW + 5):
            await lms.record_l1_turn(
                session, user_id=env.ids["student_id"], session_id="s-1",
                book_id=env.ids["book10"], mode="tutor",
                query=f"سؤال {index}", answer_excerpt="پاسخ",
            )
        await session.commit()
    assert await _count(
        env.factory, LearnerMemory,
        LearnerMemory.layer == "L1", LearnerMemory.session_id == "s-1",
    ) == lms.L1_WINDOW


@pytest.mark.asyncio
async def test_review_outcomes_converge_into_l2_topic(env):
    async with env.factory() as session:
        for correct in (True, True, True, True, False):
            await lms.record_review_outcome(
                session, user_id=env.ids["student_id"], book_id=env.ids["book12"],
                chapter_number=1, topic="قانون دوم", correct=correct,
            )
        await session.commit()
        row = await session.scalar(
            select(LearnerMemory).where(LearnerMemory.layer == "L2", LearnerMemory.topic_key == "قانون دوم")
        )
    assert row.data_json["review_total"] == 5
    assert row.data_json["review_correct"] == 4
    assert row.kind == "mastered"  # 80%


@pytest.mark.asyncio
async def test_chat_turn_writes_l1_and_async_l2_extraction(env):
    env.fake.json_reply = {"facts": [{"kind": "weak", "topic": "شتاب", "chapter_number": 2,
                                      "fact_fa": "شتاب را با سرعت اشتباه گرفته است."}]}
    async with _client() as client:
        resp = await client.post(
            "/api/v1/tutor/ask",
            json={"query": "نیرو و شتاب", "grade_number": 11, "major_code": "math_physics",
                  "book_id": env.ids["book11"], "top_k": 3, "mode": "tutor", "chat_session_id": "chat-l1"},
        )
    assert resp.status_code == 200, resp.text
    # The extraction job runs in the background; give it a short window.
    for _ in range(50):
        if await _count(env.factory, LearnerMemory, LearnerMemory.layer == "L2") > 0:
            break
        await asyncio.sleep(0.02)
    assert await _count(env.factory, LearnerMemory, LearnerMemory.layer == "L1") == 1
    assert await _count(env.factory, LearnerMemory, LearnerMemory.layer == "L2") == 1
    assert await _count(env.factory, LearnerMemory, LearnerMemory.layer == "L3") == 1
    audit = await _count(env.factory, AiAuditLog, AiAuditLog.feature_key == "memory")
    assert audit == 1


@pytest.mark.asyncio
async def test_admin_memory_get_put_delete_and_student_is_blocked(env):
    uid = env.ids["student_id"]
    async with _client() as client:
        assert (await client.get(f"/api/v1/admin/users/{uid}/memory")).status_code == 401
        created = await client.put(
            f"/api/v1/admin/users/{uid}/memory", headers=ADMIN_HEADERS,
            json={"items": [{"layer": "L2", "kind": "note", "book_id": env.ids["book10"],
                             "chapter_number": 3, "topic_key": "نیرو",
                             "content_fa": "مدیر: نیرو را با مثال روزمره یاد بگیرد."}]},
        )
        assert created.status_code == 200, created.text
        items = created.json()["items"]
        note = next(i for i in items if i["topic_key"] == "نیرو")
        assert note["created_by"] == "admin" and note["edited_by_admin"] is True
        assert created.json()["user"]["id"] == uid

        l1_put = await client.put(
            f"/api/v1/admin/users/{uid}/memory", headers=ADMIN_HEADERS,
            json={"items": [{"id": note["id"], "layer": "L1", "content_fa": "x"}]},
        )
        assert l1_put.status_code == 422

        deleted = await client.delete(
            f"/api/v1/admin/users/{uid}/memory?memory_id={note['id']}", headers=ADMIN_HEADERS
        )
        assert deleted.status_code == 200 and deleted.json()["deleted"] == 1
        reset = await client.delete(f"/api/v1/admin/users/{uid}/memory", headers=ADMIN_HEADERS)
        assert reset.status_code == 200
        assert reset.json()["counts"] == {"L1": 0, "L2": 0, "L3": 0}


@pytest.mark.asyncio
async def test_admin_concept_link_crud_and_validation(env):
    async with _client() as client:
        created = await client.post(
            "/api/v1/admin/concept-links", headers=ADMIN_HEADERS,
            json={"source_book_id": env.ids["book10"], "source_chapter": 3,
                  "target_book_id": env.ids["book12"], "target_chapter": 1,
                  "relation": "prerequisite", "label_fa": "پیش‌نیاز"},
        )
        assert created.status_code == 200, created.text
        link_id = created.json()["id"]
        assert created.json()["target"]["grade_number"] == 12

        dup = await client.post(
            "/api/v1/admin/concept-links", headers=ADMIN_HEADERS,
            json={"source_book_id": env.ids["book10"], "source_chapter": 3,
                  "target_book_id": env.ids["book12"], "target_chapter": 1},
        )
        assert dup.status_code == 409

        self_link = await client.post(
            "/api/v1/admin/concept-links", headers=ADMIN_HEADERS,
            json={"source_book_id": env.ids["book10"], "source_chapter": 3,
                  "target_book_id": env.ids["book10"], "target_chapter": 3},
        )
        assert self_link.status_code == 422

        listed = await client.get("/api/v1/admin/concept-links", headers=ADMIN_HEADERS)
        assert any(item["id"] == link_id for item in listed.json()["items"])
        gone = await client.delete(f"/api/v1/admin/concept-links/{link_id}", headers=ADMIN_HEADERS)
        assert gone.status_code == 200


# ---------------------------------------------------------------------------
# 3. Auto-Mode router
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_auto_mode_uses_router_decision_and_audits_it(env):
    env.fake.json_reply = {"mode": "question_designer", "confidence": 0.9, "reason": "درخواست سؤال"}
    async with _client() as client:
        resp = await client.post(
            "/api/v1/tutor/ask",
            json={"query": "یک سؤال تستی بساز", "grade_number": 11, "major_code": "math_physics", "book_id": env.ids["book11"],
                  "top_k": 3, "auto_mode": True},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "question_designer"
    assert body["router"]["source"] == "llm"
    assert await _count(env.factory, AiAuditLog, AiAuditLog.feature_key == "intent_router") == 1


@pytest.mark.asyncio
async def test_auto_mode_falls_back_to_heuristic_and_audits_fallback(env):
    def broken(messages):
        raise RuntimeError("router model down")

    env.fake.json_reply = broken
    async with _client() as client:
        resp = await client.post(
            "/api/v1/tutor/ask",
            json={"query": "این تمرین را حل کن", "grade_number": 11, "major_code": "math_physics", "book_id": env.ids["book11"],
                  "top_k": 3, "auto_mode": True},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "problem_solver"
    assert resp.json()["router"]["source"] == "heuristic"
    async with env.factory() as session:
        row = await session.scalar(
            select(AiAuditLog).where(AiAuditLog.feature_key == "intent_router",
                                     AiAuditLog.flag_reason == "router_heuristic_fallback")
        )
    assert row is not None


@pytest.mark.asyncio
async def test_auto_mode_stream_rechecks_routed_capability_before_generation(env, monkeypatch):
    from app.models.capabilities import Capability
    from app.services.intent_router import RouterDecision

    async def force_quiz_route(**kwargs):
        return RouterDecision(
            mode="question_designer",
            confidence=0.99,
            reason="test route",
            source="heuristic",
        )

    monkeypatch.setattr(intent_router, "route_intent", force_quiz_route)
    async with env.factory() as session:
        quiz = await session.get(Capability, "quiz")
        quiz.is_enabled = False
        await session.commit()

    body = dict(
        _STREAM_BODY,
        book_id=env.ids["book11"],
        chat_session_id="chat-auto-disabled-quiz",
        auto_mode=True,
    )
    async with _client() as client:
        started = await client.post("/api/v1/tutor/stream", json=body)
        assert started.status_code == 200, started.text
        payload = started.json()
        chunks, end = await _read_stream(client, payload["stream_id"])

    assert end["status"] == "error"
    assert chunks == []
    assert env.fake.text_calls == []
    assert await _count(
        env.factory,
        AiAuditLog,
        AiAuditLog.feature_key == "quiz",
    ) == 0


def test_router_heuristic_and_invalid_llm_output():
    assert intent_router.heuristic_mode("مسئله را حل کن")[0] == "problem_solver"
    assert intent_router.heuristic_mode("سؤال طراحی کن")[0] == "question_designer"
    assert intent_router.heuristic_mode("توان چیست؟")[0] == "tutor"
    assert intent_router._parse_llm_decision({"mode": "chatbot"}) is None
    assert intent_router._parse_llm_decision('{"mode":"tutor","confidence":7}') == ("tutor", 1.0, "")


# ---------------------------------------------------------------------------
# 4. Streaming: Stop / Regenerate / cursor, no orphan rows
# ---------------------------------------------------------------------------
async def _read_stream(client: AsyncClient, stream_id: str, cursor: int = 0) -> tuple[list[str], dict]:
    text_chunks: list[str] = []
    end: dict = {}
    async with client.stream("GET", f"/api/v1/tutor/stream/{stream_id}?cursor={cursor}") as resp:
        assert resp.status_code == 200
        event = None
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
                if event == "chunk":
                    text_chunks.append(payload["text"])
                elif event == "end":
                    end = payload
    return text_chunks, end


_STREAM_BODY = {"query": "نیرو چیست؟", "grade_number": 11, "major_code": "math_physics", "book_id": None,
                "top_k": 3, "mode": "tutor",
                "chat_session_id": "chat-stream"}


@pytest.mark.asyncio
async def test_stream_completes_then_regenerate_produces_new_stream(env):
    body = dict(_STREAM_BODY, book_id=env.ids["book11"])
    async with _client() as client:
        first = (await client.post("/api/v1/tutor/stream", json=body)).json()
        chunks, end = await _read_stream(client, first["stream_id"])
        assert end["status"] == "done"
        assert "".join(chunks).startswith(ANSWER[:20])
        assert end["final"]["sources"]
        # Cursor resume: reading from index 2 returns the tail only, no duplicates.
        tail, _ = await _read_stream(client, first["stream_id"], cursor=2)
        assert tail == chunks[2:]

        regen = (await client.post(
            "/api/v1/tutor/stream", json=dict(body, regenerate_of=first["stream_id"])
        )).json()
        assert regen["stream_id"] != first["stream_id"]
        chunks2, end2 = await _read_stream(client, regen["stream_id"])
        assert end2["status"] == "done"
        assert "".join(chunks2) == "".join(chunks)

    # Completed runs persist: one L1 row per completed turn, two model calls, two audit rows.
    assert await _count(env.factory, AiAuditLog, AiAuditLog.feature_key == "chat") == 2
    assert await _count(env.factory, LearnerMemory, LearnerMemory.layer == "L1") == 2


@pytest.mark.asyncio
async def test_stop_mid_generation_leaves_no_orphan_rows(env):
    env.fake.text_delay = 5.0  # generation is still running when Stop arrives
    body = dict(_STREAM_BODY, book_id=env.ids["book11"], chat_session_id="chat-stopped")
    chats_before = await _count(env.factory, ChatSession)
    audits_before = await _count(env.factory, AiAuditLog)
    async with _client() as client:
        started = (await client.post("/api/v1/tutor/stream", json=body)).json()
        await asyncio.sleep(0.1)
        stop = await client.post(f"/api/v1/tutor/stream/{started['stream_id']}/stop")
        assert stop.status_code == 200
        chunks, end = await _read_stream(client, started["stream_id"])
    assert end["status"] == "stopped"
    assert chunks == []
    assert await _count(env.factory, AiAuditLog) == audits_before
    assert await _count(env.factory, LearnerMemory) == 0
    assert await _count(env.factory, ChatSession) == chats_before


@pytest.mark.asyncio
async def test_stop_during_chunk_emission_rolls_back_usage_and_memory(env):
    chat_stream.CHUNK_DELAY_SECONDS = 0.05
    body = dict(_STREAM_BODY, book_id=env.ids["book11"], chat_session_id="chat-partial")
    async with _client() as client:
        started = (await client.post("/api/v1/tutor/stream", json=body)).json()
        stream_id = started["stream_id"]
        for _ in range(100):
            store = await chat_stream.get_stream_store()
            status, _, chunks = await store.read(stream_id, 0)
            if chunks:
                break
            await asyncio.sleep(0.02)
        assert chunks, "generation should have started emitting"
        await client.post(f"/api/v1/tutor/stream/{stream_id}/stop")
        _, end = await _read_stream(client, stream_id)
    chat_stream.CHUNK_DELAY_SECONDS = 0
    assert end["status"] == "stopped"
    assert await _count(env.factory, LearnerMemory) == 0
    assert await _count(env.factory, AiAuditLog, AiAuditLog.feature_key == "chat") == 0


@pytest.mark.asyncio
async def test_stream_is_private_to_its_owner(env):
    body = dict(_STREAM_BODY, book_id=env.ids["book11"])
    async with _client() as client:
        started = (await client.post("/api/v1/tutor/stream", json=body)).json()
        await _read_stream(client, started["stream_id"])
    async def as_other_student():
        async with env.factory() as session:
            return await session.get(User, env.ids["other_id"])

    app.dependency_overrides[require_student] = as_other_student
    try:
        async with _client() as client:
            resp = await client.get(f"/api/v1/tutor/stream/{started['stream_id']}")
            assert resp.status_code == 404
            stop = await client.post(f"/api/v1/tutor/stream/{started['stream_id']}/stop")
            assert stop.status_code == 404
    finally:
        async def back():
            async with env.factory() as session:
                return await session.get(User, env.ids["student_id"])
        app.dependency_overrides[require_student] = back


# ---------------------------------------------------------------------------
# 5. Chat search and Recycle Bin
# ---------------------------------------------------------------------------
async def _make_chat(env, title: str, text: str) -> str:
    async with _client() as client:
        resp = await client.post(
            "/api/v1/tutor/sessions",
            json={"book_id": env.ids["book11"], "grade_number": 11, "major_code": "math_physics",
                  "mode": "tutor", "title": title,
                  "messages": [{"id": "m1", "role": "user", "content": text}]},
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_search_restore_and_recycle_bin_round_trip(env):
    keep_id = await _make_chat(env, "درس نیرو", "شتاب گرانش چقدر است؟")
    trash_id = await _make_chat(env, "گفت‌وگوی دیگر", "درباره کار و انرژی")
    async with _client() as client:
        found = await client.get("/api/v1/tutor/sessions/search", params={"q": "گرانش"})
        assert found.status_code == 200
        assert [r["id"] for r in found.json()["results"]] == [keep_id]
        assert "گرانش" in found.json()["results"][0]["match"]["snippet"]

        deleted = await client.delete(f"/api/v1/tutor/sessions/{trash_id}")
        assert deleted.json() == {"deleted": True, "soft": True, "id": trash_id}
        active_ids = [s["id"] for s in (await client.get("/api/v1/tutor/sessions")).json()]
        assert trash_id not in active_ids
        assert (await client.get(f"/api/v1/tutor/sessions/{trash_id}")).status_code == 404
        assert (await client.get("/api/v1/tutor/sessions/search", params={"q": "انرژی"})).json()["count"] == 0

        bin_items = (await client.get("/api/v1/tutor/sessions/trash")).json()
        assert [b["id"] for b in bin_items] == [trash_id]
        assert bin_items[0]["deleted_at"]

        # Admin monitoring sees the deleted chat with its owner.
        admin_view = await client.get("/api/v1/admin/chat-sessions", headers=ADMIN_HEADERS,
                                      params={"status": "deleted"})
        assert admin_view.status_code == 200
        assert admin_view.json()["deleted_total"] == 1
        assert admin_view.json()["items"][0]["id"] == trash_id

        restored = await client.post(f"/api/v1/tutor/sessions/{trash_id}/restore")
        assert restored.status_code == 200
        assert restored.json()["deleted_at"] is None
        assert trash_id in [s["id"] for s in (await client.get("/api/v1/tutor/sessions")).json()]

        # Permanent delete only from the bin.
        assert (await client.delete(f"/api/v1/tutor/sessions/{trash_id}/permanent")).status_code == 409
        await client.delete(f"/api/v1/tutor/sessions/{trash_id}")
        purged = await client.delete(f"/api/v1/tutor/sessions/{trash_id}/permanent")
        assert purged.status_code == 200 and purged.json()["soft"] is False
    assert await _count(env.factory, ChatSession, ChatSession.id == trash_id) == 0


@pytest.mark.asyncio
async def test_other_students_chats_are_not_searchable(env):
    async with env.factory() as session:
        session.add(ChatSession(
            book_id=env.ids["book11"], user_id=env.ids["other_id"], grade_number=11,
            major_code="general", mode="tutor", title="خصوصی", messages=[{"id": "x", "role": "user",
                                                                       "content": "رمز نیرو"}],
        ))
        await session.commit()
    async with _client() as client:
        result = await client.get("/api/v1/tutor/sessions/search", params={"q": "رمز"})
    assert result.json()["count"] == 0


@pytest.mark.asyncio
async def test_scope_error_is_422_for_multi_grade_stream(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/tutor/stream",
            json={
                "query": "نیرو",
                "grade_numbers": [9],
                "book_id": env.ids["book10"],
                "branch_code": "theoretical",
                "major_code": "math_physics",
                "top_k": 3,
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_exam_submit_records_per_chapter_quiz_memory(env):
    """Phase 4: exam grading feeds L2 per chapter and rebuilds L3 (best effort)."""
    from app.api.exams import _record_exam_memory

    report = {
        "by_question": [
            {"id": "q1", "correct": True, "source": {"chapter_number": 2}},
            {"id": "q2", "correct": True, "source": {"chapter_number": 2}},
            {"id": "q3", "correct": False, "source": {"chapter_number": 2}},
            {"id": "q4", "correct": False, "source": {"chapter_number": 3}},
        ]
    }
    async with env.factory() as session:
        await _record_exam_memory(
            session, user_id=env.ids["student_id"], book_id=env.ids["book12"], report=report
        )
    async with env.factory() as session:
        rows = (
            await session.scalars(
                select(LearnerMemory).where(
                    LearnerMemory.user_id == env.ids["student_id"], LearnerMemory.layer == "L2"
                )
            )
        ).all()
        by_chapter = {row.chapter_number: row for row in rows if row.source_type == "quiz"}
        profile = await session.scalar(
            select(LearnerMemory).where(
                LearnerMemory.user_id == env.ids["student_id"], LearnerMemory.layer == "L3"
            )
        )
    assert by_chapter[2].kind == "note" and "2 از 3" in by_chapter[2].content_fa
    assert by_chapter[3].kind == "weak"
    assert profile is not None
