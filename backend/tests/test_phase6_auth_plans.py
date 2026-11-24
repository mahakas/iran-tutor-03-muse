"""Phase 6 tests: SMS OTP auth, token-based plans, billing settings, quotas, and admin management."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from app.models.auth import OtpCode, Plan, TokenUsageLog, User
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.services import payment_provider, retrieval_service, sms_provider
from app.services.auth_billing_service import normalize_iranian_phone


def test_normalize_iranian_phone_formats_and_rejects_invalid():
    assert normalize_iranian_phone("09123456789") == "09123456789"
    assert normalize_iranian_phone("۰۹۱۲۳۴۵۶۷۸۹") == "09123456789"
    assert normalize_iranian_phone("+98 912-345-6789") == "09123456789"
    assert normalize_iranian_phone("00989123456789") == "09123456789"
    assert normalize_iranian_phone("989123456789") == "09123456789"
    assert normalize_iranian_phone("9123456789") == "09123456789"

    for bad in ("", "08123456789", "0912345678", "091234567890", "abc"):
        with pytest.raises(ValueError):
            normalize_iranian_phone(bad)


def test_provider_factories_select_configured_adapters():
    demo_cfg = SimpleNamespace(
        demo_mode=False,
        sms_provider="demo",
        sms_api_key=None,
        sms_template=None,
        sms_sender=None,
        sms_webhook_url=None,
        payment_provider="demo",
        zarinpal_merchant_id=None,
        zarinpal_sandbox=False,
    )
    assert isinstance(sms_provider.get_sms_provider(demo_cfg), sms_provider.DemoSmsProvider)
    assert isinstance(payment_provider.get_payment_provider(demo_cfg), payment_provider.DemoPaymentProvider)

    kavenegar_cfg = SimpleNamespace(**{**demo_cfg.__dict__, "sms_provider": "kavenegar", "sms_api_key": "k-key"})
    assert isinstance(sms_provider.get_sms_provider(kavenegar_cfg), sms_provider.KavenegarSmsProvider)

    smsir_cfg = SimpleNamespace(
        **{**demo_cfg.__dict__, "sms_provider": "sms_ir", "sms_api_key": "ir-key", "sms_template": "123"}
    )
    assert isinstance(sms_provider.get_sms_provider(smsir_cfg), sms_provider.SmsIrSmsProvider)

    webhook_cfg = SimpleNamespace(
        **{**demo_cfg.__dict__, "sms_provider": "webhook", "sms_webhook_url": "https://sms.example/send"}
    )
    assert isinstance(sms_provider.get_sms_provider(webhook_cfg), sms_provider.WebhookSmsProvider)

    zp_cfg = SimpleNamespace(
        **{**demo_cfg.__dict__, "payment_provider": "zarinpal", "zarinpal_merchant_id": "merchant-123"}
    )
    assert isinstance(payment_provider.get_payment_provider(zp_cfg), payment_provider.ZarinpalPaymentProvider)


async def _setup_test_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase6.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

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
            title="فیزیک ۳ — تست",
            grade_id=grade.id,
            major_id=major.id,
            pdf_file_path="dummy.pdf",
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
                chapter_title="حرکت بر خط راست",
                markdown_content="مفاهیم و فرمول‌های کلیدی کتاب: شیب نمودار مکان ـ زمان برابر سرعت است.",
                visual_elements=[],
                page_image_path="dummy.png",
                status=PageStatus.done,
                warnings=[],
            )
        )
        await session.commit()
        book_id = book.id
    return engine, factory, book_id


def _demo_settings():
    return SimpleNamespace(
        demo_mode=True,
        llm_base_url="http://127.0.0.1:9/v1",
        llm_api_key="test-key",
        tutor_model="demo-tutor",
        vision_model_primary="demo-vision",
        speech_to_text_model="demo-speech",
        admin_username="admin",
        admin_password="123",
        admin_session_ttl_seconds=3600,
        auth_secret="phase6-test-secret",
        user_session_ttl_seconds=86400,
        otp_ttl_seconds=180,
        otp_resend_seconds=60,
        otp_max_attempts=3,
        sms_provider="demo",
        sms_api_key=None,
        sms_sender=None,
        sms_template=None,
        sms_webhook_url=None,
        payment_provider="demo",
        zarinpal_merchant_id=None,
        zarinpal_sandbox=False,
        public_app_url="http://test",
        vector_backend="qdrant",
        embedding_dimension=64,
        embedding_model="demo",
    )


@pytest.mark.asyncio
async def test_otp_auth_flow_cooldown_attempts_and_starter_tokens(tmp_path, monkeypatch):
    engine, factory, book_id = await _setup_test_db(tmp_path)
    cfg = _demo_settings()
    monkeypatch.setattr(config_mod, "get_settings", lambda: cfg)
    monkeypatch.setattr("app.api.auth.get_settings", lambda: cfg)
    monkeypatch.setattr("app.api.plans.get_settings", lambda: cfg)
    monkeypatch.setattr("app.services.auth_billing_service.get_settings", lambda: cfg)
    monkeypatch.setattr("app.services.sms_provider.get_settings", lambda: cfg)
    monkeypatch.setattr("app.services.payment_provider.get_settings", lambda: cfg)
    monkeypatch.setattr("app.services.tutor_service.get_settings", lambda: cfg)
    monkeypatch.setattr("app.services.exam_service.get_settings", lambda: cfg)
    monkeypatch.setattr("app.core.llm_client.get_settings", lambda: cfg)
    monkeypatch.setattr(retrieval_service, "async_session_factory", factory)
    monkeypatch.setattr(retrieval_service, "get_settings", lambda: cfg)
    # Demo-mode generation has no answer-key verdicts; the Validator Gate is covered by
    # test_phase5_deep_learning.py. Here the gate is stubbed to accept all candidates so the
    # token/usage assertions in this test stay about auth, plans and metering.
    from app.services import quiz_validator
    from app.services.quiz_validator import ValidationOutcome

    async def _approve_all(session, *, items, user_id, book_id, exam_id=None):
        return ValidationOutcome(accepted=[dict(item["question"]) for item in items])

    monkeypatch.setattr(quiz_validator, "validate_questions", _approve_all)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Unauthenticated student endpoints must reject with 401
            unauthed = await client.post(
                "/api/v1/tutor/ask",
                json={"query": "سرعت", "grade_number": 12, "major_code": "math_physics", "book_id": book_id},
            )
            assert unauthed.status_code == 401
            assert (await client.get("/api/v1/tutor/sessions")).status_code == 401
            assert (await client.get("/api/v1/exams")).status_code == 401
            assert (await client.get("/api/v1/auth/me")).json() == {"authenticated": False, "user": None}

            # Public plans list is visible before login and matches exact pricing/durations
            plans_resp = await client.get("/api/v1/plans")
            assert plans_resp.status_code == 200
            plans = {p["code"]: p for p in plans_resp.json()["plans"]}
            assert plans["normal"]["price_toman"] == 500_000
            assert plans["normal"]["duration_days"] == 30
            assert plans["pro"]["price_toman"] == 900_000
            assert plans["pro"]["duration_days"] == 30
            assert plans["vip"]["price_toman"] == 2_750_000
            assert plans["vip"]["duration_days"] == 90
            assert plans["vip"]["token_quota"] > plans["pro"]["token_quota"] > plans["normal"]["token_quota"]

            # Request OTP using Persian digits + +98 normalization
            otp_req = await client.post("/api/v1/auth/request-otp", json={"phone_number": "+98 ۹۱۲ ۳۴۵ ۶۷۸۹"})
            assert otp_req.status_code == 200
            otp_data = otp_req.json()
            assert otp_data["phone_number"] == "09123456789"
            code = otp_data["demo_code"]
            assert len(code) == 6

            # Resend cooldown triggers 429
            resend_resp = await client.post("/api/v1/auth/request-otp", json={"phone_number": "09123456789"})
            assert resend_resp.status_code == 429

            # Wrong code increments attempts and eventually invalidates at max_attempts (3)
            bad_code = "000000" if code != "000000" else "111111"
            assert (await client.post("/api/v1/auth/verify-otp", json={"phone_number": "09123456789", "code": bad_code})).status_code == 401
            assert (await client.post("/api/v1/auth/verify-otp", json={"phone_number": "09123456789", "code": bad_code})).status_code == 401
            assert (await client.post("/api/v1/auth/verify-otp", json={"phone_number": "09123456789", "code": bad_code})).status_code == 401
            # 4th attempt sees consumed/locked OTP
            assert (await client.post("/api/v1/auth/verify-otp", json={"phone_number": "09123456789", "code": code})).status_code in {401, 429}

            # Bypass cooldown in DB to issue a fresh valid OTP
            async with factory() as s:
                latest_otp = await s.scalar(select(OtpCode).order_by(OtpCode.created_at.desc()))
                latest_otp.created_at = datetime.now(timezone.utc) - timedelta(seconds=120)
                await s.commit()

            otp_req2 = await client.post("/api/v1/auth/request-otp", json={"phone_number": "09123456789"})
            assert otp_req2.status_code == 200
            code2 = otp_req2.json()["demo_code"]

            verify = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": "09123456789", "code": code2, "full_name": "علی رضایی"},
            )
            assert verify.status_code == 200
            v_data = verify.json()
            assert v_data["authenticated"] is True
            assert v_data["is_new_user"] is True
            assert v_data["user"]["plan_code"] == "trial"
            assert v_data["user"]["tokens_remaining"] == 15_000
            assert v_data["user"]["full_name"] == "علی رضایی"
            token = v_data["token"]
            async with factory() as profile_session:
                profile_student = await profile_session.scalar(
                    select(User).where(User.phone_number == "09123456789")
                )
                assert profile_student is not None
                profile_student.grade_level = 12
                await profile_session.commit()

            # Test X-User-Token header without cookies (iframe proxy safe)
            headers = {"X-User-Token": token}
            me_client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
            async with me_client as clean_client:
                me_resp = await clean_client.get("/api/v1/auth/me", headers=headers)
                assert me_resp.status_code == 200
                assert me_resp.json()["authenticated"] is True
                assert me_resp.json()["user"]["phone_number"] == "09123456789"

                # Ask tutor -> consumes tokens and records TokenUsageLog
                ask_resp = await clean_client.post(
                    "/api/v1/tutor/ask",
                    headers=headers,
                    json={
                        "query": "شیب نمودار مکان زمان چیست؟",
                        "grade_number": 12,
                        "major_code": "math_physics",
                        "book_id": book_id,
                    },
                )
                assert ask_resp.status_code == 200
                ask_data = ask_resp.json()
                assert ask_data["usage"]["total_tokens"] > 0
                assert ask_data["usage"]["cost_toman"] >= 1
                assert ask_data["usage"]["tokens_remaining"] < 15_000

                # Create exam -> consumes tokens too
                exam_resp = await clean_client.post(
                    "/api/v1/exams",
                    headers=headers,
                    json={
                        "grade_number": 12,
                        "major_code": "math_physics",
                        "book_id": book_id,
                        "question_count": 3,
                        "time_limit_minutes": 10,
                        "exam_type": "konkoor",
                    },
                )
                assert exam_resp.status_code == 200
                assert exam_resp.json()["usage"]["total_tokens"] > 0

                # Check usage history
                usage_resp = await clean_client.get("/api/v1/plans/usage", headers=headers)
                assert usage_resp.status_code == 200
                assert len(usage_resp.json()["logs"]) == 2

                # Exhaust user's tokens and verify 402 Payment Required
                async with factory() as s:
                    db_user = await s.scalar(select(User).where(User.phone_number == "09123456789"))
                    db_user.tokens_remaining = 0
                    await s.commit()

                blocked = await clean_client.post(
                    "/api/v1/tutor/ask",
                    headers=headers,
                    json={
                        "query": "سؤال بعدی",
                        "grade_number": 12,
                        "major_code": "math_physics",
                        "book_id": book_id,
                    },
                )
                assert blocked.status_code == 402

                # Buy Pro plan via demo checkout -> restores balance & unlocks tutoring
                checkout = await clean_client.post(
                    "/api/v1/plans/checkout",
                    headers=headers,
                    json={"plan_code": "pro"},
                )
                assert checkout.status_code == 200
                c_data = checkout.json()
                assert c_data["status"] == "paid"
                assert c_data["user"]["plan_code"] == "pro"
                assert c_data["user"]["plan_title"] == "حرفه‌ای"
                assert c_data["user"]["tokens_remaining"] == 1_200_000
                assert c_data["user"]["days_remaining"] == 30

                # Now asking succeeds again!
                unblocked = await clean_client.post(
                    "/api/v1/tutor/ask",
                    headers=headers,
                    json={
                        "query": "شتاب متوسط",
                        "grade_number": 12,
                        "major_code": "math_physics",
                        "book_id": book_id,
                    },
                )
                assert unblocked.status_code == 200

                # User isolation: a second user cannot see user 1's exam or chat session
                exam_id = exam_resp.json()["id"]
                chat_resp = await clean_client.post(
                    "/api/v1/tutor/sessions",
                    headers=headers,
                    json={
                        "book_id": book_id,
                        "grade_number": 12,
                        "major_code": "math_physics",
                        "mode": "tutor",
                        "title": "جلسه شخصی",
                        "messages": [{"id": "m1", "role": "user", "content": "سلام"}],
                    },
                )
                assert chat_resp.status_code == 200
                chat_id = chat_resp.json()["id"]

                otp_b = await clean_client.post("/api/v1/auth/request-otp", json={"phone_number": "09129998877"})
                assert otp_b.status_code == 200
                verify_b = await clean_client.post(
                    "/api/v1/auth/verify-otp",
                    json={"phone_number": "09129998877", "code": otp_b.json()["demo_code"]},
                )
                assert verify_b.status_code == 200
                headers_b = {"X-User-Token": verify_b.json()["token"]}
                assert (await clean_client.get("/api/v1/tutor/sessions", headers=headers_b)).json() == []
                assert (await clean_client.get(f"/api/v1/tutor/sessions/{chat_id}", headers=headers_b)).status_code == 404
                assert (await clean_client.get("/api/v1/exams", headers=headers_b)).json() == []
                assert (await clean_client.get(f"/api/v1/exams/{exam_id}", headers=headers_b)).status_code == 404
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_billing_and_user_management(tmp_path, monkeypatch):
    engine, factory, _ = await _setup_test_db(tmp_path)
    cfg = _demo_settings()
    monkeypatch.setattr(admin_api, "async_session_factory", factory)
    monkeypatch.setattr(admin_api, "get_settings", lambda: cfg)
    monkeypatch.setattr("app.services.auth_billing_service.get_settings", lambda: cfg)

    async with factory() as s:
        u = User(
            id="u-admin-test",
            phone_number="09121112233",
            full_name="مریم محمدی",
            plan_code="trial",
            plan_title="هدیه ثبت‌نام",
            tokens_total=15000,
            tokens_remaining=10000,
            tokens_used_total=5000,
            plan_expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        s.add(u)
        s.add(
            TokenUsageLog(
                user_id=u.id,
                action="tutor_ask",
                book_id=1,
                prompt_tokens=3000,
                completion_tokens=2000,
                total_tokens=5000,
                cost_toman=5000,
            )
        )
        await s.commit()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Unauthenticated admin billing/users must fail 401
            assert (await client.get("/api/v1/admin/billing")).status_code == 401
            assert (await client.get("/api/v1/admin/users")).status_code == 401
            assert (await client.get("/api/v1/admin/users/u-admin-test/usage")).status_code == 401

            login = await client.post("/api/v1/admin/auth/login", json={"username": "admin", "password": "123"})
            assert login.status_code == 200
            admin_headers = {"X-Admin-Token": login.json()["token"]}

            # Inspect billing settings & plans
            billing = await client.get("/api/v1/admin/billing", headers=admin_headers)
            assert billing.status_code == 200
            assert billing.json()["settings"]["token_price_per_1k_toman"] == 1000
            assert len(billing.json()["plans"]) == 3

            # Edit token price & starter gift settings
            upd_settings = await client.put(
                "/api/v1/admin/billing/settings",
                headers=admin_headers,
                json={"token_price_per_1k_toman": 1500, "starter_tokens": 20000, "starter_duration_days": 10},
            )
            assert upd_settings.status_code == 200
            assert upd_settings.json()["settings"]["token_price_per_1k_toman"] == 1500

            # Edit Economic plan price, token quota, and duration
            upd_plan = await client.put(
                "/api/v1/admin/billing/plans/normal",
                headers=admin_headers,
                json={"price_toman": 550000, "token_quota": 600000, "duration_days": 45},
            )
            assert upd_plan.status_code == 200
            assert upd_plan.json()["plan"]["price_toman"] == 550000
            assert upd_plan.json()["plan"]["token_quota"] == 600000
            assert upd_plan.json()["plan"]["duration_days"] == 45

            # List users and verify usage aggregation
            users_resp = await client.get("/api/v1/admin/users?q=0912111", headers=admin_headers)
            assert users_resp.status_code == 200
            data = users_resp.json()
            assert data["summary"]["total_users"] == 1
            assert data["users"][0]["tokens_used_today"] == 5000

            # Assign VIP plan + extra tokens to user from admin
            upd_user = await client.put(
                "/api/v1/admin/users/u-admin-test",
                headers=admin_headers,
                json={"plan_code": "vip", "apply_plan_defaults": True, "add_tokens": 50000},
            )
            assert upd_user.status_code == 200
            updated_u = upd_user.json()["user"]
            assert updated_u["plan_code"] == "vip"
            assert updated_u["plan_title"] == "هوشمندانه"
            assert updated_u["tokens_remaining"] == 4_050_000
            assert updated_u["days_remaining"] == 90

            # Detailed per-user token usage report
            usage_report = await client.get("/api/v1/admin/users/u-admin-test/usage", headers=admin_headers)
            assert usage_report.status_code == 200
            ur = usage_report.json()
            assert ur["user"]["id"] == "u-admin-test"
            assert len(ur["by_action"]) == 1
            assert ur["by_action"][0]["action"] == "tutor_ask"
            assert ur["by_action"][0]["total_tokens"] == 5000
            assert len(ur["daily"]) == 1
            assert ur["daily"][0]["total_tokens"] == 5000
            assert len(ur["logs"]) == 1
            assert ur["logs"][0]["book_title"] == "فیزیک ۳ — تست"
            assert len(ur["transactions"]) == 1
            assert ur["transactions"][0]["provider"] == "admin_grant"
            assert (await client.get("/api/v1/admin/users/non-existent-id/usage", headers=admin_headers)).status_code == 404
    finally:
        await engine.dispose()
