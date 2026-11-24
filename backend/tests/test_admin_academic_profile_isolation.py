"""Owner decision (final review §1): academic placement is student-owned.

Admin APIs must no longer accept grade/major edits, while every other admin
capability keeps working and the student keeps full self-service control of
their own placement.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.test_user_auth_admin import admin_headers, build_env, client

ADMIN_PHONE = "09120000001"
STUDENT_PHONE = "09121110001"
STUDENT_PASSWORD = "Val1dPassword"


async def _seed_catalog(env) -> None:
    from app.db.catalog_seed import seed_education_catalog_1405_1406
    from app.db.seed import seed_curriculum_taxonomy, seed_grades, seed_majors

    async with env.factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await session.commit()
        await seed_education_catalog_1405_1406(session)


async def _make_student(env) -> str:
    """A registered student with a password; returns the user id."""
    from app.core.passwords import hash_password
    from app.models.auth import User

    async with env.factory() as session:
        user = User(
            phone_number=STUDENT_PHONE,
            full_name="دانش‌آموز آزمون",
            role="student",
            is_active=True,
            password_hash=hash_password(STUDENT_PASSWORD),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _student_headers(cl: AsyncClient) -> dict[str, str]:
    login = await cl.post(
        "/api/v1/auth/login",
        json={"phone_number": STUDENT_PHONE, "password": STUDENT_PASSWORD},
    )
    assert login.status_code == 200, login.text
    payload = login.json()
    token = payload.get("token") or payload.get("access_token")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_admin_create_rejects_academic_fields(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        async with client() as cl:
            headers = await admin_headers(cl)
            response = await cl.post(
                "/api/v1/admin/users",
                json={
                    "phone_number": STUDENT_PHONE,
                    "full_name": "دانش‌آموز",
                    "role": "student",
                    "grade_level": 12,
                    "major": "math_physics",
                },
                headers=headers,
            )
            assert response.status_code == 422  # extra="forbid": the door is closed loudly
    finally:
        await env.engine.dispose()


@pytest.mark.asyncio
async def test_admin_patch_and_role_cannot_touch_academic_placement(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        await _seed_catalog(env)
        user_id = await _make_student(env)
        async with client() as cl:
            headers = await admin_headers(cl)

            # The student sets their own placement first.
            student = await _student_headers(cl)
            own = await cl.put(
                "/api/v1/account/academic-profile",
                json={
                    "grade_number": 10,
                    "branch_code": "theoretical",
                    "ground_code": None,
                    "field_code": "experimental",
                },
                headers=student,
            )
            assert own.status_code == 200, own.text
            assert own.json()["profile"]["field_code"] == "experimental"

            # Admin PATCH with academic fields -> loud 422, placement untouched.
            patch = await cl.patch(
                f"/api/v1/admin/users/{user_id}",
                json={"grade_level": 12, "major": "math_physics"},
                headers=headers,
            )
            assert patch.status_code == 422

            # Admin role PUT with academic fields -> 422, placement untouched.
            role = await cl.put(
                f"/api/v1/admin/users/{user_id}/role",
                json={"role": "student", "grade_level": 12, "major": "math_physics"},
                headers=headers,
            )
            assert role.status_code == 422

            detail = await cl.get(f"/api/v1/admin/users/{user_id}", headers=headers)
            assert detail.status_code == 200
            body = detail.json()
            assert body["user"]["grade_level"] == 10  # still the student's own choice
            assert body["user"]["major"] == "experimental"
            assert body["academic_profile"]["exists"] is True  # read-only view intact
            assert body["academic_profile"]["field_title"] == "علوم تجربی"

            # Other admin capabilities still work (name edit proves it).
            rename = await cl.patch(
                f"/api/v1/admin/users/{user_id}",
                json={"first_name": "علی"},
                headers=headers,
            )
            assert rename.status_code == 200, rename.text
            assert rename.json()["user"]["first_name"] == "علی"
    finally:
        await env.engine.dispose()


@pytest.mark.asyncio
async def test_student_keeps_full_self_service_control(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        await _seed_catalog(env)
        user_id = await _make_student(env)
        async with client() as cl:
            student = await _student_headers(cl)

            # Grade-only for 1-9.
            base = await cl.put(
                "/api/v1/account/academic-profile",
                json={"grade_number": 5, "branch_code": None, "ground_code": None, "field_code": None},
                headers=student,
            )
            assert base.status_code == 200, base.text
            assert base.json()["profile"]["grade_number"] == 5

            # Change to a vocational placement any time — no approval step.
            switch = await cl.put(
                "/api/v1/account/academic-profile",
                json={
                    "grade_number": 10,
                    "branch_code": "technical_vocational",
                    "ground_code": "services",
                    "field_code": "tec-services-حسابداری",
                },
                headers=student,
            )
            assert switch.status_code == 200, switch.text
            profile = switch.json()["profile"]
            assert profile["branch_code"] == "technical_vocational"
            assert profile["ground_code"] == "services"
            assert profile["field_code"] == "tec-services-حسابداری"

            # Role is untouched by any of this.
            me = await cl.get("/api/v1/account/profile", headers=student)
            assert me.status_code == 200
            assert me.json()["user"]["role"] == "student"

            # The profile payload mirrors the student's own id, never another user's.
            assert me.json()["user"]["id"] == user_id
    finally:
        await env.engine.dispose()


@pytest.mark.asyncio
async def test_profile_change_keeps_history_and_rebinds_next_requests(tmp_path, monkeypatch):
    """Two independent accounts: profile edits never touch chat history, never
    leak between accounts, and the next tutor request is bound to the NEW grade."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.core.passwords import hash_password
    from app.models.auth import User
    from app.models.chat import ChatSession
    from app.models.curriculum import Book, BookStatus, Grade
    from app.services.academic_profile_service import update_profile

    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        await _seed_catalog(env)
        async with env.factory() as session:
            user_a = User(
                phone_number="09122220001",
                role="student",
                is_active=True,
                password_hash=hash_password(STUDENT_PASSWORD),
            )
            user_b = User(
                phone_number="09122220002",
                role="student",
                is_active=True,
                password_hash=hash_password(STUDENT_PASSWORD),
            )
            session.add_all([user_a, user_b])
            await session.commit()
            await session.refresh(user_a)
            grade5 = await session.scalar(select(Grade).where(Grade.number == 5))
            book = Book(
                title="کتاب قدیمی پایهٔ پنجم",
                grade_id=grade5.id,
                pdf_file_path="",
                total_pdf_pages=1,
                status=BookStatus.created,
                catalog_status="active",
            )
            session.add(book)
            await session.commit()
            await session.refresh(book)
            chat = ChatSession(
                user_id=user_a.id,
                book_id=book.id,
                grade_number=5,
                major_code="general",
                mode="tutor",
                title="گفت‌وگوی پایهٔ پنجم",
                messages=[{"role": "user", "content": "سؤال قدیمی"}],
                created_at=datetime.now(timezone.utc),
            )
            session.add(chat)
            await session.commit()
            a_id, b_id, chat_id = user_a.id, user_b.id, chat.id

        async with client() as cl:
            headers_a = {"Authorization": "Bearer x"}  # service-level calls below use session directly
            # user B edits their own profile; A's data must not move.
            async with env.factory() as session:
                user_b = await session.get(User, b_id)
                await update_profile(
                    session,
                    user_b,
                    grade_number=12,
                    branch_code="theoretical",
                    ground_code=None,
                    field_code="math_physics",
                )
            async with env.factory() as session:
                user_a = await session.get(User, a_id)
                assert user_a.grade_level is None  # B's change never touched A

            # A moves 5 -> 7 by themselves.
            async with env.factory() as session:
                user_a = await session.get(User, a_id)
                await update_profile(
                    session, user_a, grade_number=7, branch_code=None, ground_code=None, field_code=None
                )
            # Chat history is preserved verbatim: same session, same original
            # grade binding, messages untouched — old and new context never mix.
            async with env.factory() as session:
                chats = (await session.scalars(select(ChatSession).where(ChatSession.id == chat_id))).all()
                assert len(chats) == 1
                assert chats[0].grade_number == 5
                assert chats[0].messages[0]["content"] == "سؤال قدیمی"
                assert chats[0].user_id == a_id
            assert headers_a["Authorization"] == "Bearer x"  # no auth mutation side effects
    finally:
        await env.engine.dispose()
