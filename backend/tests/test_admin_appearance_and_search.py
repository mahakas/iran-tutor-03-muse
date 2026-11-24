"""Tests for Admin Appearance persistence, Diff Markers snapshot, and Admin/User search endpoints."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import admin as admin_api
from app.core import config as config_mod
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.chat import ChatSession
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.models.exam import ExamSession, ExamStatus
from app.services import account_service, ingestion_service


async def _setup_db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin_app_search.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    user_files_root = tmp_path / "user_files"
    user_files_root.mkdir(parents=True, exist_ok=True)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(account_service, "USER_FILES_DIR", user_files_root)
    monkeypatch.setattr(ingestion_service, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(admin_api, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(admin_api, "async_session_factory", factory)

    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        await session.flush()

        grade = await session.scalar(select(Grade).where(Grade.number == 12))
        major = await session.scalar(select(Major).where(Major.code == "math_physics"))

        ready_book = Book(
            title="فیزیک دوازدهم آزمایشی",
            grade_id=grade.id,
            major_id=major.id,
            pdf_file_path=str(tmp_path / "phys.pdf"),
            total_pdf_pages=1,
            status=BookStatus.ready,
            catalog_status="approved",
        )
        draft_book = Book(
            title="شیمی پیش‌نویس مخفی",
            grade_id=grade.id,
            major_id=major.id,
            pdf_file_path=str(tmp_path / "chem.pdf"),
            total_pdf_pages=1,
            status=BookStatus.ingesting,
        )
        session.add_all([ready_book, draft_book])
        await session.flush()

        session.add_all(
            [
                BookPage(
                    book_id=ready_book.id,
                    pdf_page_index=1,
                    printed_page_number=14,
                    chapter_number=1,
                    chapter_title="حرکت بر خط راست",
                    markdown_content="سرعت متوسط برابر نسبت جابه‌جایی به زمان است.",
                    page_image_path=str(tmp_path / "p1.png"),
                    status=PageStatus.done,
                ),
                BookPage(
                    book_id=draft_book.id,
                    pdf_page_index=1,
                    printed_page_number=3,
                    chapter_number=1,
                    chapter_title="مقدمه مخفی",
                    markdown_content="این صفحه هنوز تایید نشده است.",
                    page_image_path=str(tmp_path / "c1.png"),
                    status=PageStatus.needs_review,
                ),
            ]
        )
        await session.commit()
        book_id = ready_book.id

    async def override_get_session():
        async with factory() as session:
            yield session

    settings = SimpleNamespace(
        demo_mode=True,
        sms_provider="demo",
        sms_api_key=None,
        sms_template=None,
        sms_sender=None,
        sms_webhook_url=None,
        payment_provider="demo",
        zarinpal_merchant_id=None,
        zarinpal_sandbox=False,
        admin_username="admin",
        admin_password="secret-pw",
        auth_secret="test-auth-secret",
        llm_api_key="test-llm-key",
        public_app_url=None,
        admin_session_ttl_seconds=3600,
        otp_ttl_seconds=300,
        otp_resend_seconds=0,
        otp_max_attempts=5,
        user_session_ttl_seconds=86400,
        vision_model_primary="demo-vision",
    )
    monkeypatch.setattr(config_mod, "get_settings", lambda: settings)
    monkeypatch.setattr("app.api.admin.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.account.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.plans.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.auth_billing_service.get_settings", lambda: settings)
    app.dependency_overrides[get_session] = override_get_session
    return engine, factory, book_id


async def _login_student(client: AsyncClient, phone: str, *, full_name: str | None = None) -> tuple[str, str]:
    req = await client.post("/api/v1/auth/request-otp", json={"phone_number": phone})
    assert req.status_code == 200
    code = req.json()["demo_code"]
    ver = await client.post(
        "/api/v1/auth/verify-otp",
        json={"phone_number": phone, "code": code, "full_name": full_name},
    )
    assert ver.status_code == 200
    payload = ver.json()
    return payload["token"], payload["user"]["id"]


@pytest.mark.asyncio
async def test_admin_preferences_persist_across_logout_and_relogin_and_diff_original(tmp_path, monkeypatch):
    engine, _, book_id = await _setup_db(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Unauthenticated requests are rejected
            assert (await client.get("/api/v1/admin/preferences")).status_code == 401
            assert (await client.put("/api/v1/admin/preferences", json={})).status_code == 401
            assert (await client.post("/api/v1/admin/preferences/reset", json={"section": "appearance"})).status_code == 401

            # 2. Admin login
            login1 = await client.post(
                "/api/v1/admin/auth/login",
                json={"username": "admin", "password": "secret-pw"},
            )
            assert login1.status_code == 200
            token1 = login1.json()["token"]
            headers1 = {"X-Admin-Token": token1}

            # 3. Defaults include diff_markers=True
            initial = await client.get("/api/v1/admin/preferences", headers=headers1)
            assert initial.status_code == 200
            prefs0 = initial.json()["preferences"]
            assert prefs0["appearance"]["diff_markers"] is True
            assert prefs0["appearance"]["code_font_size"] == 13

            # 4. Validation rejects invalid contrast/color
            bad_color = await client.put(
                "/api/v1/admin/preferences",
                headers=headers1,
                json={"appearance": {"dark": {"accent": "red"}}},
            )
            assert bad_color.status_code == 422
            bad_code_font = await client.put(
                "/api/v1/admin/preferences",
                headers=headers1,
                json={"appearance": {"code_font_size": 99}},
            )
            assert bad_code_font.status_code == 422

            # 5. Customize all admin appearance settings (including separate light/dark + system + motion + diff_markers)
            saved = await client.put(
                "/api/v1/admin/preferences",
                headers=headers1,
                json={
                    "appearance": {
                        "visual_style": "modern",
                        "color_mode": "system",
                        "separate_mode_themes": True,
                        "light": {
                            "theme": "ocean",
                            "accent": "#0284c7",
                            "background": "#f5f9fc",
                            "foreground": "#162636",
                            "font_family": "system",
                        },
                        "dark": {
                            "theme": "violet",
                            "accent": "#a78bfa",
                            "background": "#131021",
                            "foreground": "#f1ecfe",
                            "font_family": "mono",
                        },
                        "ui_font_size": 16,
                        "code_font_size": 15,
                        "reduce_motion": "on",
                        "contrast": 80,
                        "diff_markers": False,
                    }
                },
            )
            assert saved.status_code == 200
            ap = saved.json()["preferences"]["appearance"]
            assert ap["color_mode"] == "system"
            assert ap["light"]["accent"] == "#0284c7"
            assert ap["dark"]["accent"] == "#a78bfa"
            assert ap["ui_font_size"] == 16
            assert ap["code_font_size"] == 15
            assert ap["reduce_motion"] == "on"
            assert ap["contrast"] == 80
            assert ap["diff_markers"] is False

            # 6. Logout and clear client cookies, then login fresh -> preferences MUST persist!
            logout = await client.post("/api/v1/admin/auth/logout", headers=headers1)
            assert logout.status_code == 200
            client.cookies.clear()

            login2 = await client.post(
                "/api/v1/admin/auth/login",
                json={"username": "admin", "password": "secret-pw"},
            )
            assert login2.status_code == 200
            headers2 = {"X-Admin-Token": login2.json()["token"]}

            restored = await client.get("/api/v1/admin/preferences", headers=headers2)
            assert restored.status_code == 200
            restored_ap = restored.json()["preferences"]["appearance"]
            assert restored_ap["color_mode"] == "system"
            assert restored_ap["light"]["accent"] == "#0284c7"
            assert restored_ap["dark"]["accent"] == "#a78bfa"
            assert restored_ap["ui_font_size"] == 16
            assert restored_ap["code_font_size"] == 15
            assert restored_ap["reduce_motion"] == "on"
            assert restored_ap["contrast"] == 80
            assert restored_ap["diff_markers"] is False

            # 7. Editing book page preserves original_markdown_content on first edit for Diff Markers
            fix1 = await client.put(
                f"/api/v1/admin/books/{book_id}/pages/1",
                headers=headers2,
                json={"markdown_content": "سرعت متوسط برابر $\\frac{\\Delta x}{\\Delta t}$ است."},
            )
            assert fix1.status_code == 200
            assert fix1.json()["original_markdown_content"] == "سرعت متوسط برابر نسبت جابه‌جایی به زمان است."

            # Subsequent edit keeps original snapshot intact
            fix2 = await client.put(
                f"/api/v1/admin/books/{book_id}/pages/1",
                headers=headers2,
                json={"markdown_content": "نسخه سوم ویرایش‌شده"},
            )
            assert fix2.status_code == 200
            assert fix2.json()["original_markdown_content"] == "سرعت متوسط برابر نسبت جابه‌جایی به زمان است."

            pages_list = await client.get(f"/api/v1/admin/books/{book_id}/pages", headers=headers2)
            assert pages_list.status_code == 200
            assert pages_list.json()[0]["original_markdown_content"] == "سرعت متوسط برابر نسبت جابه‌جایی به زمان است."

            # 8. Reset appearance returns defaults
            rst = await client.post(
                "/api/v1/admin/preferences/reset",
                headers=headers2,
                json={"section": "appearance"},
            )
            assert rst.status_code == 200
            assert rst.json()["preferences"]["appearance"]["diff_markers"] is True
            assert rst.json()["preferences"]["appearance"]["code_font_size"] == 13
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_curriculum_and_account_search_endpoints(tmp_path, monkeypatch):
    engine, factory, book_id = await _setup_db(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Unauthenticated admin/account search rejected
            assert (await client.get("/api/v1/admin/search?q=فیزیک")).status_code == 401
            assert (await client.get("/api/v1/account/search?q=فیزیک")).status_code == 401

            # Create two students with isolated chats, exams & files
            tok_a, uid_a = await _login_student(client, "09121112233", full_name="سارا احمدی")
            tok_b, uid_b = await _login_student(client, "09129998877", full_name="علی رضایی")

            from datetime import datetime, timedelta, timezone

            async with factory() as db:
                db.add_all(
                    [
                        ChatSession(
                            book_id=book_id,
                            user_id=uid_a,
                            grade_number=12,
                            major_code="math_physics",
                            mode="tutor",
                            title="تمرین حرکت سارا",
                            messages=[],
                        ),
                        ChatSession(
                            book_id=book_id,
                            user_id=uid_b,
                            grade_number=12,
                            major_code="math_physics",
                            mode="tutor",
                            title="تمرین محرمانه علی",
                            messages=[],
                        ),
                        ExamSession(
                            book_id=book_id,
                            user_id=uid_a,
                            grade_number=12,
                            major_code="math_physics",
                            title="آزمون حرکت سارا",
                            exam_type="konkoor",
                            time_limit_seconds=600,
                            status=ExamStatus.active,
                            questions=[],
                            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                        ),
                    ]
                )
                await db.commit()

            # Public curriculum search returns only ready books & approved pages
            cur_res = await client.get("/api/v1/curriculum/search?q=حرکت")
            assert cur_res.status_code == 200
            cur_data = cur_res.json()
            assert len(cur_data["topics"]) == 1
            assert cur_data["topics"][0]["book_id"] == book_id

            cur_draft = await client.get("/api/v1/curriculum/search?q=مخفی")
            assert cur_draft.status_code == 200
            assert cur_draft.json()["books"] == []
            assert cur_draft.json()["topics"] == []

            # Authenticated student search returns own chats/exams only
            acc_res = await client.get(
                "/api/v1/account/search?q=حرکت",
                headers={"Authorization": f"Bearer {tok_a}"},
            )
            assert acc_res.status_code == 200
            acc_data = acc_res.json()
            assert [c["title"] for c in acc_data["chats"]] == ["تمرین حرکت سارا"]
            assert [e["title"] for e in acc_data["exams"]] == ["آزمون حرکت سارا"]

            acc_leak_check = await client.get(
                "/api/v1/account/search?q=محرمانه",
                headers={"Authorization": f"Bearer {tok_a}"},
            )
            assert acc_leak_check.status_code == 200
            assert acc_leak_check.json()["chats"] == []

            # Admin search finds books (including ingesting), pages, users, and plans
            admin_login = await client.post(
                "/api/v1/admin/auth/login",
                json={"username": "admin", "password": "secret-pw"},
            )
            admin_headers = {"X-Admin-Token": admin_login.json()["token"]}

            ad_books = await client.get("/api/v1/admin/search?q=مخفی", headers=admin_headers)
            assert ad_books.status_code == 200
            assert len(ad_books.json()["books"]) == 1
            assert len(ad_books.json()["pages"]) == 1

            ad_users = await client.get("/api/v1/admin/search?q=0912111", headers=admin_headers)
            assert ad_users.status_code == 200
            assert len(ad_users.json()["users"]) == 1
            assert ad_users.json()["users"][0]["full_name"] == "سارا احمدی"

            ad_plans = await client.get("/api/v1/admin/search?q=حرفه‌ای", headers=admin_headers)
            assert ad_plans.status_code == 200
            assert any(p["code"] == "pro" for p in ad_plans.json()["plans"])

            # Empty query (`q=`) populates browse tabs immediately without returning 422
            browse_cur = await client.get("/api/v1/curriculum/search?q=")
            assert browse_cur.status_code == 200
            assert len(browse_cur.json()["books"]) >= 1
            assert len(browse_cur.json()["topics"]) >= 1

            browse_acc = await client.get(
                "/api/v1/account/search?q=",
                headers={"Authorization": f"Bearer {tok_a}"},
            )
            assert browse_acc.status_code == 200
            browse_acc_data = browse_acc.json()
            assert len(browse_acc_data["books"]) >= 1
            assert len(browse_acc_data["chats"]) == 1
            assert len(browse_acc_data["exams"]) == 1

            browse_adm = await client.get("/api/v1/admin/search?q=", headers=admin_headers)
            assert browse_adm.status_code == 200
            browse_adm_data = browse_adm.json()
            assert len(browse_adm_data["books"]) >= 1
            assert len(browse_adm_data["pages"]) >= 1
            assert len(browse_adm_data["users"]) >= 2
            assert len(browse_adm_data["plans"]) >= 1
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
