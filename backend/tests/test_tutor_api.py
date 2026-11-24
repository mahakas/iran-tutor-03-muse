"""Tutor endpoint enforces the selected book's grade and major."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import require_student
from app.db.session import get_session
from app.main import app
from app.models.auth import User
from app.models.curriculum import Book, Grade, Major


def _fake_student() -> SimpleNamespace:
    return SimpleNamespace(
        id="user-test-1",
        phone_number="09123456789",
        full_name="دانش‌آموز تست",
        plan_code="trial",
        plan_title="هدیه ثبت‌نام",
        tokens_total=15000,
        tokens_remaining=15000,
        tokens_used_total=0,
        plan_expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        grade_level=12,
        is_active=True,
    )


class FakeSession:
    async def scalar(self, statement):
        sql = str(statement)
        params = statement.compile().params
        if "education_branches" in sql:
            return SimpleNamespace(
                id=3, code="theoretical", min_grade=10, max_grade=12, is_active=True
            )
        if "fields_of_study" in sql:
            if "fields_of_study.code" not in sql:
                return 5
            code = next(
                (value for value in params.values() if value in {"math_physics", "experimental"}),
                None,
            )
            if code == "math_physics":
                return SimpleNamespace(
                    id=5, code="math_physics", branch_id=3, is_active=True
                )
            return None
        if "book_curriculum_links" in sql:
            # This legacy fixture has major_id metadata but no normalized link rows.
            return None
        return None

    async def get(self, model, identity):
        if model is Book and identity == 1:
            return SimpleNamespace(
                id=1,
                grade_id=12,
                major_id=2,
                status="ready",
                catalog_status="approved",
                academic_year_id=None,
            )
        if model is Grade and identity == 12:
            return SimpleNamespace(number=12, has_major=True)
        if model is Major and identity == 2:
            return SimpleNamespace(code="math_physics")
        return None


@pytest.mark.asyncio
async def test_tutor_rejects_major_that_does_not_match_selected_book(monkeypatch):
    async def fake_session():
        yield FakeSession()

    async def should_not_answer(**kwargs):
        raise AssertionError("must reject before retrieval")

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[require_student] = _fake_student
    monkeypatch.setattr("app.api.tutor.answer_from_textbook", should_not_answer)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/tutor/ask",
                json={
                    "query": "سوال فیزیک",
                    "grade_number": 12,
                    "major_code": "experimental",
                    "book_id": 1,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "field of study" in response.json()["detail"]


@pytest.mark.asyncio
async def test_tutor_passes_server_verified_curriculum_to_rag(monkeypatch):
    async def fake_session():
        yield FakeSession()

    async def fake_answer(**kwargs):
        assert kwargs["grade_number"] == 12
        assert kwargs["major_code"] == "math_physics"
        assert kwargs["book_id"] == 1
        assert kwargs["mode"] == "problem_solver"
        return {"answer": "پاسخ مستند", "sources": [], "retrieved_count": 0}

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[require_student] = _fake_student
    monkeypatch.setattr("app.api.tutor.answer_from_textbook", fake_answer)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/tutor/ask",
                json={
                    "query": "سوال فیزیک",
                    "grade_number": 12,
                    "major_code": "math_physics",
                    "book_id": 1,
                    "mode": "problem_solver",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "پاسخ مستند"


@pytest.mark.asyncio
async def test_chat_sessions_roundtrip_crud(tmp_path):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.db.base import Base
    from app.db.seed import seed_curriculum_taxonomy, seed_grades, seed_majors

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'chat_test.sqlite3'}",
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await session.flush()
        grade = await session.get(Grade, 12)
        major = await session.get(Major, 1)
        book = Book(
            title="فیزیک ۳",
            grade_id=grade.id,
            major_id=major.id,
            pdf_file_path="dummy.pdf",
            total_pdf_pages=1,
            status="ready",
            catalog_status="approved",
        )
        user = User(
            id="user-chat-1",
            phone_number="09120000001",
            plan_code="trial",
            plan_title="هدیه ثبت‌نام",
            tokens_total=15000,
            tokens_remaining=15000,
            plan_expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            grade_level=12,
        )
        session.add_all([book, user])
        await session.commit()
        await session.refresh(book)
        await session.refresh(user)
        book_id = book.id

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_student] = lambda: user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            create_resp = await client.post(
                "/api/v1/tutor/sessions",
                json={
                    "book_id": book_id,
                    "grade_number": 12,
                    "major_code": "math_physics",
                    "mode": "tutor",
                    "title": "حرکت بر خط راست",
                    "messages": [
                        {"id": "m1", "role": "user", "content": "سرعت متوسط چیست؟"},
                        {"id": "m2", "role": "assistant", "content": "نسبت جابه‌جایی به زمان.", "sources": []},
                    ],
                },
            )
            assert create_resp.status_code == 200
            session_id = create_resp.json()["id"]

            list_resp = await client.get("/api/v1/tutor/sessions")
            assert list_resp.status_code == 200
            assert len(list_resp.json()) == 1
            assert list_resp.json()[0]["message_count"] == 2

            upd_resp = await client.put(
                f"/api/v1/tutor/sessions/{session_id}",
                json={
                    "mode": "problem_solver",
                    "messages": [
                        {"id": "m1", "role": "user", "content": "سرعت متوسط چیست؟"},
                        {"id": "m2", "role": "assistant", "content": "نسبت جابه‌جایی به زمان.", "sources": []},
                        {"id": "m3", "role": "user", "content": "مثال حل کن"},
                    ],
                },
            )
            assert upd_resp.status_code == 200
            assert upd_resp.json()["message_count"] == 3
            assert upd_resp.json()["mode"] == "problem_solver"

            get_resp = await client.get(f"/api/v1/tutor/sessions/{session_id}")
            assert get_resp.status_code == 200
            assert len(get_resp.json()["messages"]) == 3

            del_resp = await client.delete(f"/api/v1/tutor/sessions/{session_id}")
            assert del_resp.status_code == 200
            assert (await client.get("/api/v1/tutor/sessions")).json() == []
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
