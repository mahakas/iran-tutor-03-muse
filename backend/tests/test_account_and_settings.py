"""Comprehensive tests for Account Menu APIs: profile, OTP phone change, preferences, storage & sessions."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import config as config_mod
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.auth import BillingSettings, Plan, User, UserFile, UserSession
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.services import account_service, multimodal_service


async def _setup_test_env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'account_test.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    user_files_root = tmp_path / "user_files"
    user_files_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(account_service, "USER_FILES_DIR", user_files_root)

    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        await session.flush()

        grade = await session.scalar(select(Grade).where(Grade.number == 12))
        major = await session.scalar(select(Major).where(Major.code == "math_physics"))
        book = Book(
            title="فیزیک ۳ — تست حساب کاربری",
            grade_id=grade.id,
            major_id=major.id,
            pdf_file_path=str(tmp_path / "physics.pdf"),
            total_pdf_pages=1,
            status=BookStatus.ready,
            catalog_status="approved",
        )
        session.add(book)
        await session.flush()
        session.add(
            BookPage(
                book_id=book.id,
                pdf_page_index=1,
                printed_page_number=10,
                chapter_number=1,
                chapter_title="حرکت شناسی",
                markdown_content="در حرکت یکنواخت سرعت ثابت است.",
                page_image_path=str(tmp_path / "page_1.png"),
                status=PageStatus.done,
            )
        )
        await session.commit()

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
        admin_password="secret",
        admin_session_secret="test-account-secret-key",
        auth_secret="test-auth-secret-key",
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
    monkeypatch.setattr("app.api.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.account.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.plans.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.auth_billing_service.get_settings", lambda: settings)
    app.dependency_overrides[get_session] = override_get_session
    return engine, factory


async def _login_student(client: AsyncClient, phone: str, *, full_name: str | None = None, ua: str = "TestAgent/1.0") -> tuple[str, dict]:
    req = await client.post("/api/v1/auth/request-otp", json={"phone_number": phone})
    assert req.status_code == 200
    code = req.json()["demo_code"]
    ver = await client.post(
        "/api/v1/auth/verify-otp",
        json={"phone_number": phone, "code": code, "full_name": full_name},
        headers={"User-Agent": ua},
    )
    assert ver.status_code == 200
    payload = ver.json()
    return payload["token"], payload["user"]


def _make_png_bytes(color: str = "teal") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_session_lifecycle_no_store_and_logout_revocation(tmp_path, monkeypatch):
    engine, factory = await _setup_test_env(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Unauthenticated access to private account routes must fail
            unauth = await client.get("/api/v1/account/profile")
            assert unauth.status_code == 401

            token1, _ = await _login_student(client, "09121112233", full_name="سارا محمدی", ua="Chrome/120 Windows")
            token2, _ = await _login_student(client, "09121112233", ua="Firefox/122 Linux")

            # List active sessions using token1
            sess_res = await client.get(
                "/api/v1/account/sessions",
                headers={"Authorization": f"Bearer {token1}"},
            )
            assert sess_res.status_code == 200
            assert sess_res.headers.get("cache-control") == "no-store"
            sessions = sess_res.json()["sessions"]
            assert len(sessions) == 2
            current_sess = [s for s in sessions if s["is_current"]]
            other_sess = [s for s in sessions if not s["is_current"]]
            assert len(current_sess) == 1
            assert len(other_sess) == 1

            # Revoke other sessions
            rev_others = await client.post(
                "/api/v1/account/sessions/revoke-others",
                headers={"Authorization": f"Bearer {token1}"},
            )
            assert rev_others.status_code == 200
            assert rev_others.json()["revoked_count"] == 1

            # Revoked token2 is immediately rejected by backend
            me_token2 = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token2}"},
            )
            assert me_token2.status_code == 200
            assert me_token2.json()["authenticated"] is False

            prof_token2 = await client.get(
                "/api/v1/account/profile",
                headers={"Authorization": f"Bearer {token2}"},
            )
            assert prof_token2.status_code == 401

            # Logout on token1 revokes its UserSession and blocks reuse
            logout_res = await client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {token1}"},
            )
            assert logout_res.status_code == 200
            assert logout_res.json()["authenticated"] is False

            reuse_after_logout = await client.get(
                "/api/v1/account/profile",
                headers={"Authorization": f"Bearer {token1}"},
            )
            assert reuse_after_logout.status_code == 401

        async with factory() as db:
            rows = (await db.scalars(select(UserSession))).all()
            assert len(rows) == 2
            assert all(r.revoked_at is not None for r in rows)
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_profile_avatar_and_otp_verified_phone_change(tmp_path, monkeypatch):
    engine, _ = await _setup_test_env(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token, _ = await _login_student(client, "09123334455", full_name="مریم رضایی")
            # Register a second user to test duplicate phone rejection
            await _login_student(client, "09129998877", full_name="کاربر دیگر")

            # Invalid email is rejected
            bad_email = await client.put(
                "/api/v1/account/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"email": "not-an-email"},
            )
            assert bad_email.status_code == 422

            # Valid update persists first_name, last_name, full_name, email
            upd = await client.put(
                "/api/v1/account/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"first_name": "مریم", "last_name": "کریمی", "email": "maryam@example.com"},
            )
            assert upd.status_code == 200
            u = upd.json()["user"]
            assert u["first_name"] == "مریم"
            assert u["last_name"] == "کریمی"
            assert u["full_name"] == "مریم کریمی"
            assert u["email"] == "maryam@example.com"
            assert u["role"] == "student"

            # Upload avatar & retrieve it
            png = _make_png_bytes()
            av_res = await client.post(
                "/api/v1/account/profile/avatar",
                headers={"Authorization": f"Bearer {token}"},
                files={"avatar": ("me.png", png, "image/png")},
            )
            assert av_res.status_code == 200
            assert av_res.json()["user"]["avatar_url"] is not None

            av_get = await client.get(
                "/api/v1/account/profile/avatar",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert av_get.status_code == 200
            assert av_get.headers["content-type"] == "image/png"

            # Replace avatar — should only keep 1 active profile_avatar file in storage
            av_res2 = await client.post(
                "/api/v1/account/profile/avatar",
                headers={"Authorization": f"Bearer {token}"},
                files={"avatar": ("me2.png", _make_png_bytes("navy"), "image/png")},
            )
            assert av_res2.status_code == 200

            storage = (
                await client.get(
                    "/api/v1/account/storage",
                    headers={"Authorization": f"Bearer {token}"},
                )
            ).json()
            assert storage["total_files"] == 1

            # Delete avatar
            av_del = await client.delete(
                "/api/v1/account/profile/avatar",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert av_del.status_code == 200
            assert av_del.json()["user"]["avatar_url"] is None

            # Phone change rejects existing user's phone with 409
            dup_phone = await client.post(
                "/api/v1/account/profile/phone/request-otp",
                headers={"Authorization": f"Bearer {token}"},
                json={"new_phone_number": "09129998877"},
            )
            assert dup_phone.status_code == 409

            # Request OTP for unused phone, reject wrong code, accept valid code
            req_phone = await client.post(
                "/api/v1/account/profile/phone/request-otp",
                headers={"Authorization": f"Bearer {token}"},
                json={"new_phone_number": "09127776655"},
            )
            assert req_phone.status_code == 200
            demo_code = req_phone.json()["demo_code"]

            wrong_verify = await client.post(
                "/api/v1/account/profile/phone/verify",
                headers={"Authorization": f"Bearer {token}"},
                json={"new_phone_number": "09127776655", "code": "000000"},
            )
            assert wrong_verify.status_code == 401

            good_verify = await client.post(
                "/api/v1/account/profile/phone/verify",
                headers={"Authorization": f"Bearer {token}"},
                json={"new_phone_number": "09127776655", "code": demo_code},
            )
            assert good_verify.status_code == 200
            assert good_verify.json()["user"]["phone_number"] == "09127776655"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_preferences_validation_independent_modes_and_persistence(tmp_path, monkeypatch):
    engine, _ = await _setup_test_env(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token, _ = await _login_student(client, "09124445566")

            # Reject invalid contrast / font size / color hex
            bad_pref = await client.put(
                "/api/v1/account/preferences",
                headers={"Authorization": f"Bearer {token}"},
                json={"appearance": {"ui_font_size": 42}},
            )
            assert bad_pref.status_code == 422

            bad_hex = await client.put(
                "/api/v1/account/preferences",
                headers={"Authorization": f"Bearer {token}"},
                json={"appearance": {"light": {"accent": "not-a-hex"}}},
            )
            assert bad_hex.status_code == 422

            # Save independent light and dark customizations + general + appearance + notifications + privacy
            upd = await client.put(
                "/api/v1/account/preferences",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "general": {"language": "en", "timezone": "UTC"},
                    "appearance": {
                        "visual_style": "modern",
                        "color_mode": "dark",
                        "separate_mode_themes": True,
                        "light": {
                            "theme": "ocean",
                            "accent": "#0284c7",
                            "background": "#f5f9fc",
                            "font_family": "vazir",
                        },
                        "dark": {
                            "theme": "violet",
                            "accent": "#a78bfa",
                            "background": "#131021",
                            "foreground": "#f1ecfe",
                            "font_family": "sahel",
                        },
                        "ui_font_size": 16,
                        "code_font_size": 15,
                        "reduce_motion": "on",
                        "contrast": 75,
                    },
                    "notifications": {
                        "email_updates": True,
                        "usage_alerts": False,
                        "plan_expiry_reminders": True,
                        "exam_reminders": False,
                        "security_alerts": True,
                    },
                    "privacy": {"store_uploaded_attachments": False},
                },
            )
            assert upd.status_code == 200
            prefs = upd.json()["preferences"]
            assert prefs["general"]["language"] == "en"
            assert prefs["appearance"]["visual_style"] == "modern"
            assert prefs["appearance"]["light"]["theme"] == "ocean"
            assert prefs["appearance"]["light"]["accent"] == "#0284c7"
            assert prefs["appearance"]["light"]["font_family"] == "vazir"
            assert prefs["appearance"]["dark"]["theme"] == "violet"
            assert prefs["appearance"]["dark"]["accent"] == "#a78bfa"
            assert prefs["appearance"]["dark"]["font_family"] == "sahel"
            assert prefs["appearance"]["ui_font_size"] == 16
            assert prefs["appearance"]["code_font_size"] == 15
            assert prefs["appearance"]["contrast"] == 75
            assert prefs["notifications"]["email_updates"] is True
            assert prefs["notifications"]["usage_alerts"] is False
            assert prefs["notifications"]["exam_reminders"] is False
            assert prefs["privacy"]["store_uploaded_attachments"] is False

            # Logout and re-login -> preferences MUST persist!
            await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
            token_again, user_again = await _login_student(client, "09124445566")
            assert user_again["preferences"]["appearance"]["light"]["accent"] == "#0284c7"
            assert user_again["preferences"]["appearance"]["dark"]["accent"] == "#a78bfa"
            assert user_again["preferences"]["general"]["language"] == "en"

            # Reset appearance restores defaults while keeping general language
            rst = await client.post(
                "/api/v1/account/preferences/reset",
                headers={"Authorization": f"Bearer {token_again}"},
                json={"section": "appearance"},
            )
            assert rst.status_code == 200
            after_reset = rst.json()["preferences"]
            assert after_reset["appearance"]["ui_font_size"] == 14
            assert after_reset["general"]["language"] == "en"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_storage_quotas_ownership_isolation_and_tutor_attachment_flag(tmp_path, monkeypatch):
    engine, factory = await _setup_test_env(tmp_path, monkeypatch)
    try:
        # Shrink starter storage to 4 KB for quota testing while Pro plan has 250 MB
        async with factory() as db:
            billing = await db.get(BillingSettings, 1)
            billing.starter_storage_bytes = 4096
            await db.commit()

        async def fake_answer_image(**kwargs):
            return {"answer": "پاسخ تمرین تصویری", "recognized_question": "x+1=2", "sources": []}

        monkeypatch.setattr("app.api.tutor.answer_image_question", fake_answer_image)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token_a, _ = await _login_student(client, "09125550001")
            token_b, _ = await _login_student(client, "09125550002")
            async with factory() as db:
                student_a = await db.scalar(
                    select(User).where(User.phone_number == "09125550001")
                )
                assert student_a is not None
                student_a.grade_level = 12
                await db.commit()

            # Upload 1 image and 1 markdown document for user A (both small)
            png_bytes = _make_png_bytes()
            up1 = await client.post(
                "/api/v1/account/storage/files",
                headers={"Authorization": f"Bearer {token_a}"},
                files={"file": ("diagram.png", png_bytes, "image/png")},
            )
            assert up1.status_code == 200
            file_img = up1.json()["file"]

            md_bytes = b"# Physics Notes\nVelocity is derivative of position."
            up2 = await client.post(
                "/api/v1/account/storage/files",
                headers={"Authorization": f"Bearer {token_a}"},
                files={"file": ("notes.md", md_bytes, "text/markdown")},
            )
            assert up2.status_code == 200
            file_md = up2.json()["file"]

            # Non-double-counting summary check
            summary = up2.json()["storage"]
            assert summary["quota_bytes"] == 4096
            assert summary["total_files"] == 2
            assert summary["categories"]["images"]["bytes"] == len(png_bytes)
            assert summary["categories"]["files"]["bytes"] == len(md_bytes)
            assert summary["categories"]["audio"]["bytes"] == 0
            assert summary["used_bytes"] == len(png_bytes) + len(md_bytes)
            assert summary["used_bytes"] + summary["remaining_bytes"] == summary["quota_bytes"]

            # Exceeding 4 KB starter storage quota returns 413
            too_big = b"A" * 4000
            up_over = await client.post(
                "/api/v1/account/storage/files",
                headers={"Authorization": f"Bearer {token_a}"},
                files={"file": ("big.txt", too_big, "text/plain")},
            )
            assert up_over.status_code == 413

            # Search & category filter work
            search_res = await client.get(
                "/api/v1/account/storage/files?q=notes&category=file",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert search_res.status_code == 200
            assert search_res.json()["total"] == 1
            assert search_res.json()["items"][0]["id"] == file_md["id"]

            # Ownership isolation: User B cannot inspect, download, or delete User A's file
            assert (
                await client.get(
                    f"/api/v1/account/storage/files/{file_img['id']}",
                    headers={"Authorization": f"Bearer {token_b}"},
                )
            ).status_code == 404
            assert (
                await client.get(
                    f"/api/v1/account/storage/files/{file_img['id']}/content",
                    headers={"Authorization": f"Bearer {token_b}"},
                )
            ).status_code == 404
            assert (
                await client.delete(
                    f"/api/v1/account/storage/files/{file_img['id']}",
                    headers={"Authorization": f"Bearer {token_b}"},
                )
            ).status_code == 404

            # HTML file preview is neutralized to text/plain to prevent XSS
            html_up = await client.post(
                "/api/v1/account/storage/files",
                headers={"Authorization": f"Bearer {token_a}"},
                files={"file": ("snippet.html", b"<script>alert(1)</script>", "text/html")},
            )
            assert html_up.status_code == 200
            html_id = html_up.json()["file"]["id"]
            html_preview = await client.get(
                f"/api/v1/account/storage/files/{html_id}/content",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert html_preview.status_code == 200
            assert html_preview.headers["content-type"].startswith("text/plain")

            # Upgrade User A to Pro (demo checkout immediately completes) -> quota increases to 250 MB!
            chk = await client.post(
                "/api/v1/plans/checkout",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"plan_code": "pro"},
            )
            assert chk.status_code == 200
            assert chk.json()["status"] == "paid"
            assert chk.json()["user"]["storage_quota_bytes"] == 250 * 1024 * 1024

            # Now the 4 KB file upload succeeds under Pro quota
            up_now_ok = await client.post(
                "/api/v1/account/storage/files",
                headers={"Authorization": f"Bearer {token_a}"},
                files={"file": ("big.txt", too_big, "text/plain")},
            )
            assert up_now_ok.status_code == 200

            # Tutor ask-image saves attachment when store_uploaded_attachments=True
            ask1 = await client.post(
                "/api/v1/tutor/ask-image",
                headers={"Authorization": f"Bearer {token_a}"},
                data={"grade_number": "12", "major_code": "math_physics", "book_id": "1"},
                files={"image": ("homework.png", png_bytes, "image/png")},
            )
            assert ask1.status_code == 200
            assert "saved_file" in ask1.json()

            # Turn off store_uploaded_attachments -> tutor ask-image does NOT store in UserFile
            await client.put(
                "/api/v1/account/preferences",
                headers={"Authorization": f"Bearer {token_a}"},
                json={"privacy": {"store_uploaded_attachments": False}},
            )
            ask2 = await client.post(
                "/api/v1/tutor/ask-image",
                headers={"Authorization": f"Bearer {token_a}"},
                data={"grade_number": "12", "major_code": "math_physics", "book_id": "1"},
                files={"image": ("private.png", png_bytes, "image/png")},
            )
            assert ask2.status_code == 200
            assert "saved_file" not in ask2.json()

            # Deleting User A's file frees exact bytes
            del_res = await client.delete(
                f"/api/v1/account/storage/files/{file_md['id']}",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            assert del_res.status_code == 200
            assert del_res.json()["deleted"] is True
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
