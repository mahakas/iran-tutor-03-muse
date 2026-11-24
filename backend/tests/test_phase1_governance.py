"""Phase 1 tests: encrypted AI provider vault, model routing, quotas, RBAC,
central AI gateway auditing, and the glass-box observability API.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import crypto
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.auth import User
from app.models.governance import AiAuditLog, AiProvider, FeatureModelRoute, UserQuota
from app.services import ai_gateway, ai_provider_service, quota_service, rate_limiter

ADMIN_HEADERS = {"X-Admin-Username": "admin", "X-Admin-Password": "123"}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


async def _build_env(tmp_path, monkeypatch):
    """Isolated SQLite database + demo settings for the whole phase-1 surface."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase1.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        await session.commit()

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    # Routes that open their own session (admin settings/books/users) must also hit
    # the isolated DB instead of the real engine, or they would reach for Postgres.
    from app.db import session as db_session_mod

    monkeypatch.setattr(db_session_mod, "async_session_factory", factory)
    for module_name in (
        "app.api.admin",
        "app.api.account",
        "app.api.auth",
        "app.api.plans",
        "app.api.tutor",
        "app.api.exams",
        "app.api.curriculum",
        "app.api.feedback",
    ):
        module = __import__(module_name, fromlist=["async_session_factory"])
        if hasattr(module, "async_session_factory"):
            monkeypatch.setattr(module, "async_session_factory", factory)

    settings = SimpleNamespace(
        demo_mode=True,
        admin_username="admin",
        admin_password="123",
        admin_session_ttl_seconds=3600,
        admin_session_secret=None,
        secret_key="phase1-test-secret-key",
        auth_secret="phase1-auth-secret",
        llm_api_key="phase1-llm-key",
        llm_base_url="https://example.invalid/v1",
        tutor_model="route-default-model",
        vision_model_primary="route-vision-model",
        speech_to_text_model="route-stt-model",
        embedding_model="route-embed-model",
        otp_ttl_seconds=300,
        otp_resend_seconds=0,
        otp_max_attempts=5,
        user_session_ttl_seconds=86400,
        redis_url=None,
        rate_limit_enabled=True,
        sms_provider="demo",
        payment_provider="demo",
        qdrant_url="http://127.0.0.1:6333",
        qdrant_collection="test",
        zarinpal_merchant_id=None,
        zarinpal_sandbox=False,
        public_app_url=None,
        sms_api_key=None,
        sms_template=None,
        sms_sender=None,
        sms_webhook_url=None,
        vision_model_a="route-vision-a",
        vision_model_b="route-vision-b",
        vector_backend="qdrant",
        embedding_base_url=None,
        embedding_api_key=None,
        embedding_dimension=64,
        audio_base_url=None,
        audio_api_key=None,
        escalate_figures=False,
        llm_timeout=30,
        max_concurrency=2,
    )
    for module_path in (
        "app.api.admin",
        "app.api.auth",
        "app.api.account",
        "app.api.plans",
        "app.api.tutor",
        "app.api.exams",
        "app.core.config",
        "app.core.crypto",
        "app.core.llm_client",
        "app.services.auth_billing_service",
        "app.services.ai_gateway",
        "app.services.ai_provider_service",
        "app.services.quota_service",
        "app.services.rate_limiter",
    ):
        monkeypatch.setattr(f"{module_path}.get_settings", lambda: settings, raising=False)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)

    await rate_limiter.close_rate_limiter()
    return engine, factory, settings


async def _login_student(client: AsyncClient, phone: str) -> tuple[str, dict]:
    requested = await client.post("/api/v1/auth/request-otp", json={"phone_number": phone})
    assert requested.status_code == 200
    code = requested.json()["demo_code"]
    verified = await client.post(
        "/api/v1/auth/verify-otp", json={"phone_number": phone, "code": code}
    )
    assert verified.status_code == 200
    payload = verified.json()
    return payload["token"], payload["user"]


# ---------------------------------------------------------------------------
# 1. Encryption / key vault
# ---------------------------------------------------------------------------


def test_secrets_are_encrypted_at_rest_and_masked_on_read(monkeypatch):
    settings = SimpleNamespace(secret_key="unit-test-secret", admin_username="admin", admin_password="x", llm_api_key="y")
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)

    raw = "sk-very-secret-provider-key-1234567890"
    stored = crypto.encrypt_secret(raw)

    assert stored is not None
    assert stored.startswith("enc:v1:")
    assert raw not in stored
    assert crypto.decrypt_secret(stored) == raw
    assert crypto.is_encrypted(stored) is True

    # Masking never reveals more than 3 leading + 4 trailing characters.
    masked = crypto.mask_api_key(raw)
    assert masked.startswith("sk-")
    assert masked.endswith("7890")
    assert raw not in masked

    # Blank / None input stays None so clearing and "leave unchanged" differ.
    assert crypto.encrypt_secret(None) is None
    assert crypto.encrypt_secret("   ") is None


def test_decrypt_tolerates_legacy_plaintext_and_wrong_key(monkeypatch):
    settings = SimpleNamespace(secret_key="key-a")
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    stored = crypto.encrypt_secret("legacy-secret-value")

    # A row written before encryption existed is passed through unchanged.
    assert crypto.decrypt_secret("plain-legacy-key") == "plain-legacy-key"

    # A different SECRET_KEY cannot decode the value: it returns None, never garbage.
    monkeypatch.setattr(crypto, "get_settings", lambda: SimpleNamespace(secret_key="key-b"))
    assert crypto.decrypt_secret(stored) is None


# ---------------------------------------------------------------------------
# 2. RBAC: /api/v1/admin/* must reject anonymous (401) and students (403)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_routes_reject_anonymous_and_students(tmp_path, monkeypatch):
    engine, _factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            phase1_paths = (
                ("GET", "/api/v1/admin/providers"),
                ("GET", "/api/v1/admin/routes"),
                ("GET", "/api/v1/admin/quotas"),
                ("GET", "/api/v1/admin/audit-logs"),
                ("GET", "/api/v1/admin/audit-logs/summary"),
            )

            # 1) No credentials at all -> 401
            for method, path in phase1_paths:
                response = await client.request(method, path)
                assert response.status_code == 401, f"{method} {path} -> {response.status_code}"

            # 2) A valid student session must not unlock the admin area -> 403
            token, _user = await _login_student(client, "09120000001")
            student_headers = {"Authorization": f"Bearer {token}"}
            for method, path in phase1_paths:
                response = await client.request(method, path, headers=student_headers)
                assert response.status_code == 403, f"{method} {path} -> {response.status_code}"

            # 3) The legacy admin session still works.
            ok = await client.get("/api/v1/admin/providers", headers=ADMIN_HEADERS)
            assert ok.status_code == 200
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_role_user_session_can_reach_admin_api(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token, user = await _login_student(client, "09120000002")
            async with factory() as session:
                row = await session.get(User, user["id"])
                row.role = "admin"
                await session.commit()

            response = await client.get(
                "/api/v1/admin/providers", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["providers"] == []
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 3. Provider CRUD never leaks the raw key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_crud_never_returns_plaintext_api_key(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/api/v1/admin/providers",
                headers=ADMIN_HEADERS,
                json={
                    "name": "OpenAI اصلی",
                    "provider_type": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-live-abcdefghijklmnop",
                    "capabilities": ["chat", "vision", "STT", "bogus"],
                },
            )
            assert created.status_code == 200, created.text
            payload = created.json()["provider"]
            assert payload["api_key"] is None
            assert payload["has_api_key"] is True
            assert "sk-live" not in str(payload)
            assert payload["capabilities"] == ["chat", "vision", "stt"]

            provider_id = payload["id"]
            listed = await client.get("/api/v1/admin/providers", headers=ADMIN_HEADERS)
            assert "sk-live" not in listed.text

            # Ciphertext is stored, and it decrypts back to the original value.
            async with factory() as session:
                row = await session.get(AiProvider, provider_id)
                assert row.encrypted_api_key.startswith("enc:v1:")
                assert "sk-live" not in row.encrypted_api_key
                assert crypto.decrypt_secret(row.encrypted_api_key) == "sk-live-abcdefghijklmnop"

                # --- routing -------------------------------------------------
                route_resp = await client.put(
                    "/api/v1/admin/routes",
                    headers=ADMIN_HEADERS,
                    json={
                        "feature_key": "chat",
                        "provider_id": provider_id,
                        "model_name": "gpt-route-model",
                        "temperature": 0.3,
                    },
                )
                assert route_resp.status_code == 200, route_resp.text
                assert route_resp.json()["route"]["model_name"] == "gpt-route-model"

                resolved = await ai_provider_service.resolve_feature_route(session, "chat")
                assert resolved is not None
                assert resolved.source == "route"
                assert resolved.model_name == "gpt-route-model"
                assert resolved.api_key == "sk-live-abcdefghijklmnop"

                # --- deleting a provider that routes use is blocked ----------
                blocked = await client.delete(
                    f"/api/v1/admin/providers/{provider_id}", headers=ADMIN_HEADERS
                )
                assert blocked.status_code == 409

            # Clearing the key removes it entirely.
            cleared = await client.put(
                f"/api/v1/admin/providers/{provider_id}",
                headers=ADMIN_HEADERS,
                json={"clear_api_key": True},
            )
            assert cleared.status_code == 200
            assert cleared.json()["provider"]["has_api_key"] is False
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_feature_route_is_rejected(tmp_path, monkeypatch):
    engine, _factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/api/v1/admin/providers",
                headers=ADMIN_HEADERS,
                json={"name": "P", "provider_type": "openai_compatible"},
            )
            provider_id = created.json()["provider"]["id"]
            response = await client.put(
                "/api/v1/admin/routes",
                headers=ADMIN_HEADERS,
                json={"feature_key": "not_a_feature", "provider_id": provider_id, "model_name": "m"},
            )
            assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 4. Gateway: audit row + quota accounting for every call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_writes_audit_log_and_updates_quota(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            user = User(phone_number="09120000010", role="student", tokens_remaining=10_000)
            session.add(user)
            await session.commit()
            user_id = user.id

        async def fake_complete_text(model, messages):
            assert model == "route-default-model"
            return "پاسخ آزمایشی مسیر راه‌اندازی"

        monkeypatch.setattr(ai_gateway, "complete_text", fake_complete_text)

        async with factory() as session:
            ctx = ai_gateway.CallContext(
                feature_key="chat",
                user_id=user_id,
                session_id="sess-1",
                textbook_strict=True,
                citations=[
                    {
                        "book_id": 1,
                        "book_title": "فیزیک ۳",
                        "chapter_title": "حرکت",
                        "printed_page_number": 14,
                    }
                ],
                rag_hit_count=1,
            )
            result = await ai_gateway.complete_text_via_gateway(
                ctx=ctx,
                messages=[{"role": "user", "content": "شیب نمودار چیست؟"}],
                session=session,
            )
            await session.commit()

            assert result.content == "پاسخ آزمایشی مسیر راه‌اندازی"
            assert result.audit_id

            audit = await session.get(AiAuditLog, result.audit_id)
            assert audit is not None
            assert audit.feature_key == "chat"
            assert audit.status == "success"
            assert audit.model_name == "route-default-model"
            assert audit.rag_hit_count == 1
            assert audit.rag_citations_json[0]["printed_page_number"] == 14
            assert audit.tokens_in > 0 and audit.tokens_out > 0
            assert audit.latency_ms >= 0
            assert audit.estimated_cost_usd >= 0
            assert audit.request_messages_json[0]["content"] == "شیب نمودار چیست؟"
            assert "پاسخ آزمایشی" in (audit.response_text or "")

            quota = await session.scalar(
                select(UserQuota).where(
                    UserQuota.user_id == user_id, UserQuota.feature_key == "chat"
                )
            )
            assert quota is not None
            assert quota.daily_requests_used == 1
            assert quota.daily_tokens_used == audit.tokens_in + audit.tokens_out
            assert quota.monthly_tokens_used == quota.daily_tokens_used
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_gateway_auto_flags_rag_miss_in_textbook_strict_mode(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async def fake_complete_text(model, messages):
            return "پاسخ بدون منبع"

        monkeypatch.setattr(ai_gateway, "complete_text", fake_complete_text)

        async with factory() as session:
            ctx = ai_gateway.CallContext(
                feature_key="chat", textbook_strict=True, citations=[], rag_hit_count=0
            )
            result = await ai_gateway.complete_text_via_gateway(
                ctx=ctx, messages=[{"role": "user", "content": "سؤال"}], session=session
            )
            await session.commit()

            audit = await session.get(AiAuditLog, result.audit_id)
            assert audit.status == "flagged"
            assert audit.flag_reason == "rag_miss_in_textbook_strict_mode"
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_gateway_records_error_rows_when_provider_fails(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async def exploding_complete_text(model, messages):
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(ai_gateway, "complete_text", exploding_complete_text)

        async with factory() as session:
            ctx = ai_gateway.CallContext(feature_key="chat", textbook_strict=False)
            with pytest.raises(RuntimeError):
                await ai_gateway.complete_text_via_gateway(
                    ctx=ctx, messages=[{"role": "user", "content": "سؤال"}], session=session
                )
            await session.commit()
            audit = await session.scalar(
                select(AiAuditLog).order_by(AiAuditLog.created_at.desc())
            )
            assert audit is not None
            assert audit.status == "error"
            assert "provider exploded" in (audit.error_message or "")
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_gateway_uses_admin_route_model_over_env_default(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            provider = AiProvider(
                name="Router",
                provider_type="openai_compatible",
                base_url="https://router.invalid/v1",
                capabilities=["chat"],
            )
            seen: dict[str, str] = {}

            async def fake_complete_text(model, messages, **kwargs):
                seen["model"] = model
                seen["base_url"] = kwargs["base_url"]
                return "ok"

            monkeypatch.setattr(ai_gateway, "complete_text", fake_complete_text)
            session.add(provider)
            await session.flush()
            session.add(
                FeatureModelRoute(
                    feature_key="solve", provider_id=provider.id, model_name="admin-routed-model"
                )
            )
            await session.commit()

            ctx = ai_gateway.CallContext(feature_key="solve")
            await ai_gateway.complete_text_via_gateway(
                ctx=ctx, messages=[{"role": "user", "content": "x"}], session=session
            )
            assert seen["model"] == "admin-routed-model"
            assert seen["base_url"] == "https://router.invalid/v1"
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 5. Quota enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quota_blocks_when_daily_token_budget_is_exhausted(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        from datetime import datetime, timedelta, timezone

        async with factory() as session:
            user = User(
                phone_number="09120000020",
                role="student",
                tokens_remaining=10_000,
                plan_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
            session.add(user)
            await session.commit()

            decision = await quota_service.enforce_ai_quota(
                session, user=user, feature_key="chat"
            )
            assert decision.allowed is True
            assert decision.daily_tokens_limit > 0

            # Simulate a fully spent daily budget.
            quota = await quota_service.get_or_create_quota(
                session, user_id=user.id, feature_key="chat"
            )
            quota.daily_tokens_used = decision.daily_tokens_limit
            await session.commit()

            from fastapi import HTTPException

            with pytest.raises(HTTPException) as excinfo:
                await quota_service.enforce_ai_quota(session, user=user, feature_key="chat")
            assert excinfo.value.status_code == 402
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_quota_windows_roll_over_on_new_day(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        from datetime import datetime, timedelta, timezone

        async with factory() as session:
            user = User(phone_number="09120000021", role="student", tokens_remaining=10_000)
            session.add(user)
            await session.commit()

            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            quota = await quota_service.get_or_create_quota(
                session, user_id=user.id, feature_key="chat", now=yesterday
            )
            quota.daily_tokens_used = 999
            quota.daily_requests_used = 999
            await session.commit()

            rolled = await quota_service.get_or_create_quota(
                session, user_id=user.id, feature_key="chat"
            )
            assert rolled.daily_tokens_used == 0
            assert rolled.daily_requests_used == 0
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_rate_limiter_uses_local_window_without_redis(monkeypatch):
    settings = SimpleNamespace(redis_url=None, rate_limit_enabled=True)
    monkeypatch.setattr(rate_limiter, "get_settings", lambda: settings)
    await rate_limiter.close_rate_limiter()

    allowed = 0
    blocked = 0
    for _ in range(5):
        decision = await rate_limiter.check_rate_limit(
            identity="user-1", bucket="ai:chat", limit=3, window_seconds=60
        )
        if decision.allowed:
            allowed += 1
        else:
            blocked += 1
            assert decision.retry_after_seconds >= 1
    assert allowed == 3
    assert blocked == 2
    await rate_limiter.close_rate_limiter()


@pytest.mark.asyncio
async def test_rate_limiter_disabled_short_circuits(monkeypatch):
    settings = SimpleNamespace(redis_url=None, rate_limit_enabled=False)
    monkeypatch.setattr(rate_limiter, "get_settings", lambda: settings)
    for _ in range(10):
        decision = await rate_limiter.check_rate_limit(
            identity="u", bucket="b", limit=1, window_seconds=60
        )
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# 6. Observability API + student flag queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observability_api_filters_and_flags(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            for index, status in enumerate(("success", "error", "flagged")):
                session.add(
                    AiAuditLog(
                        feature_key="chat" if index != 1 else "quiz",
                        model_name="m",
                        request_messages_json=[{"role": "user", "content": f"q{index}"}],
                        response_text=f"answer {index}",
                        rag_citations_json=[],
                        rag_hit_count=index,
                        tokens_in=10 * index,
                        tokens_out=5 * index,
                        estimated_cost_usd=0.001 * index,
                        latency_ms=100 * index,
                        status=status,
                    )
                )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            everything = await client.get("/api/v1/admin/audit-logs", headers=ADMIN_HEADERS)
            assert everything.status_code == 200
            assert everything.json()["total"] == 3

            only_errors = await client.get(
                "/api/v1/admin/audit-logs?status=error", headers=ADMIN_HEADERS
            )
            assert only_errors.json()["total"] == 1

            only_chat = await client.get(
                "/api/v1/admin/audit-logs?feature_key=chat", headers=ADMIN_HEADERS
            )
            assert only_chat.json()["total"] == 2
            assert "request_messages_json" not in only_chat.json()["items"][0]

            flagged = await client.get(
                "/api/v1/admin/audit-logs?flagged_only=true", headers=ADMIN_HEADERS
            )
            assert flagged.json()["total"] == 1

            summary = await client.get("/api/v1/admin/audit-logs/summary", headers=ADMIN_HEADERS)
            assert summary.status_code == 200
            assert summary.json()["totals"]["calls"] == 3
            assert summary.json()["totals"]["flagged"] == 1
            assert "chat" in summary.json()["by_feature"]

            item_id = everything.json()["items"][0]["id"]
            detail = await client.get(
                f"/api/v1/admin/audit-logs/{item_id}", headers=ADMIN_HEADERS
            )
            assert detail.status_code == 200
            assert "request_messages_json" in detail.json()["item"]

            # Admin manual flag
            flagged_by_admin = await client.post(
                f"/api/v1/admin/audit-logs/{item_id}/flag",
                headers=ADMIN_HEADERS,
                json={"reason": "پاسخ غیرمستند"},
            )
            assert flagged_by_admin.status_code == 200
            assert flagged_by_admin.json()["item"]["status"] == "flagged"
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_student_can_flag_an_ai_answer_into_admin_queue(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            session.add(
                AiAuditLog(
                    feature_key="chat",
                    model_name="m",
                    request_messages_json=[],
                    response_text="پاسخ اشتباه",
                    rag_citations_json=[],
                    rag_hit_count=1,
                    status="success",
                )
            )
            await session.commit()
            audit_id = await session.scalar(select(AiAuditLog.id))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Anonymous reporting is rejected.
            anonymous = await client.post(
                "/api/v1/feedback/flag", json={"audit_id": audit_id}
            )
            assert anonymous.status_code == 401

            token, user = await _login_student(client, "09120000030")
            reported = await client.post(
                "/api/v1/feedback/flag",
                json={"audit_id": audit_id, "note": "پاسخ با کتاب نمی‌خواند"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert reported.status_code == 200, reported.text
            assert reported.json()["flagged"] is True

            async with factory() as session:
                row = await session.get(AiAuditLog, audit_id)
                assert row.status == "flagged"
                assert row.flag_reason.startswith("student_report:")
                assert row.flagged_by == user["id"]

            # The flag is visible in the admin queue.
            queue = await client.get(
                "/api/v1/admin/audit-logs?flagged_only=true", headers=ADMIN_HEADERS
            )
            assert queue.json()["total"] == 1

            # A missing audit id is a validation error, not a 500.
            bad = await client.post(
                "/api/v1/feedback/flag",
                json={},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert bad.status_code == 422
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


# ---------------------------------------------------------------------------
# 7. Admin user RBAC + quota policy endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_edit_role_and_quota_policy(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            user = User(phone_number="09120000040", role="student", tokens_remaining=1000)
            session.add(user)
            await session.commit()
            user_id = user.id

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Owner final-review decision: academic placement (grade/major) is
            # student-owned self-service data — the admin role endpoint closed
            # that capability, so the payload no longer carries it and any
            # attempt is rejected loudly.
            updated = await client.put(
                f"/api/v1/admin/users/{user_id}/role",
                headers=ADMIN_HEADERS,
                json={"role": "teacher"},
            )
            assert updated.status_code == 200
            body = updated.json()["user"]
            assert body["role"] == "teacher"
            assert body["grade_level"] is None
            assert body["major"] is None

            academic_edit = await client.put(
                f"/api/v1/admin/users/{user_id}/role",
                headers=ADMIN_HEADERS,
                json={"role": "teacher", "grade_level": 12, "major": "math_physics"},
            )
            assert academic_edit.status_code == 422

            invalid_role = await client.put(
                f"/api/v1/admin/users/{user_id}/role",
                headers=ADMIN_HEADERS,
                json={"role": "superuser"},
            )
            assert invalid_role.status_code == 422

            policy = await client.put(
                "/api/v1/admin/quotas",
                headers=ADMIN_HEADERS,
                json={"daily_tokens": 1234, "requests_per_minute": 7},
            )
            assert policy.status_code == 200
            assert policy.json()["policy"]["daily_tokens"] == 1234
            assert policy.json()["policy"]["requests_per_minute"] == 7

            read_back = await client.get("/api/v1/admin/quotas", headers=ADMIN_HEADERS)
            assert read_back.json()["policy"]["daily_tokens"] == 1234

            snapshot = await client.get(
                f"/api/v1/admin/users/{user_id}/quota", headers=ADMIN_HEADERS
            )
            assert snapshot.status_code == 200
            assert snapshot.json()["quota"]["daily_tokens_limit"] == 1234
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_tutor_ask_writes_audit_row_end_to_end(tmp_path, monkeypatch):
    """A real /api/v1/tutor/ask call must produce an audit row (demo mode)."""
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus

        async with factory() as session:
            grade = await session.scalar(select(Grade).where(Grade.number == 12))
            major = await session.scalar(select(Major).where(Major.code == "math_physics"))
            book = Book(
                title="فیزیک ۳ — تست فاز ۱",
                grade_id=grade.id,
                major_id=major.id,
                pdf_file_path=str(tmp_path / "b.pdf"),
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
                    markdown_content="شیب نمودار مکان زمان برابر سرعت است.",
                    page_image_path=str(tmp_path / "p.png"),
                    status=PageStatus.done,
                )
            )
            await session.commit()
            book_id = book.id

        async def forced_pages(*args, **kwargs):
            return [
                {
                    "book_id": book_id,
                    "book_title": "فیزیک ۳ — تست فاز ۱",
                    "grade_number": 12,
                    "major_code": "math_physics",
                    "chapter_number": 1,
                    "chapter_title": "حرکت شناسی",
                    "pdf_page_index": 1,
                    "printed_page_number": 10,
                    "full_text": "شیب نمودار مکان زمان برابر سرعت است.",
                    "score": 0.9,
                }
            ]

        import app.services.tutor_service as tutor_service

        monkeypatch.setattr(tutor_service, "search_textbook", forced_pages)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token, student = await _login_student(client, "09120000050")
            async with factory() as session:
                row = await session.get(User, student["id"])
                from datetime import datetime, timedelta, timezone

                row.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                row.tokens_remaining = 50_000
                row.grade_level = 12
                await session.commit()
            response = await client.post(
                "/api/v1/tutor/ask",
                json={
                    "query": "شیب نمودار مکان زمان چه معنایی دارد؟",
                    "grade_number": 12,
                    "major_code": "math_physics",
                    "book_id": book_id,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["audit_id"]

        async with factory() as session:
            rows = (await session.scalars(select(AiAuditLog))).all()
            assert len(rows) == 1
            assert rows[0].feature_key == "chat"
            assert rows[0].status == "success"
            assert rows[0].rag_hit_count == 1
            assert rows[0].user_id is not None
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()

# ---------------------------------------------------------------------------
# 8. Gateway latency + feedback endpoint contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_records_nonzero_latency_and_cost(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async def fake_complete_text(model, messages):
            return "پاسخ"

        monkeypatch.setattr(ai_gateway, "complete_text", fake_complete_text)

        async with factory() as session:
            ctx = ai_gateway.CallContext(feature_key="chat", rag_hit_count=1)
            result = await ai_gateway.complete_text_via_gateway(
                ctx=ctx, messages=[{"role": "user", "content": "x"}], session=session
            )
            await session.commit()
            audit = await session.get(AiAuditLog, result.audit_id)
            assert audit.latency_ms >= 1
            assert audit.estimated_cost_usd > 0
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_feedback_endpoint_rejects_foreign_and_invalid_reports(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            owner = User(phone_number="09120000060", role="student")
            other = User(phone_number="09120000061", role="student")
            session.add_all([owner, other])
            await session.flush()
            session.add(
                AiAuditLog(
                    user_id=owner.id,
                    feature_key="chat",
                    model_name="m",
                    request_messages_json=[],
                    response_text="r",
                    rag_citations_json=[],
                    status="success",
                )
            )
            await session.commit()
            audit_id = await session.scalar(select(AiAuditLog.id))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token, _u = await _login_student(client, "09120000061")
            headers = {"Authorization": f"Bearer {token}"}

            # Another student's answer cannot be flagged by this caller.
            foreign = await client.post(
                "/api/v1/feedback/flag", json={"audit_id": audit_id}, headers=headers
            )
            assert foreign.status_code == 403

            missing = await client.post(
                "/api/v1/feedback/flag", json={}, headers=headers
            )
            assert missing.status_code == 422

            unknown = await client.post(
                "/api/v1/feedback/flag",
                json={"audit_id": "00000000-0000-0000-0000-000000000000"},
                headers=headers,
            )
            assert unknown.status_code == 404
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


def test_mask_api_key_and_provider_serialization_never_include_secret(monkeypatch):
    monkeypatch.setattr(
        crypto, "get_settings", lambda: SimpleNamespace(secret_key="mask-test-key")
    )
    provider = AiProvider(
        id=7,
        name="X",
        provider_type="openai",
        base_url="https://x.invalid/v1",
        encrypted_api_key=crypto.encrypt_secret("sk-abcdefghijklmnop"),
        capabilities=["chat"],
        is_active=True,
    )
    payload = ai_provider_service.serialize_provider(provider)
    assert "sk-abcdefghijklmnop" not in str(payload)
    assert payload["api_key"] is None
    assert payload["has_api_key"] is True


# ---------------------------------------------------------------------------
# 11. Structural audit: *every* admin operation is guarded, and no response or
#     log line can carry a plaintext secret.
# ---------------------------------------------------------------------------


def _admin_operations() -> list[tuple[str, str]]:
    """Enumerate every operational (method, path) under /api/v1/admin from the live app."""
    from fastapi.routing import APIRoute

    def prefix_of(route) -> str:
        ctx = getattr(route, "include_context", None)
        return (getattr(ctx, "prefix", "") or "") if ctx is not None else ""

    def collect(routes, prefix: str = ""):
        for route in routes:
            if isinstance(route, APIRoute):
                yield prefix + route.path, route
                continue
            original = getattr(route, "original_router", None)
            if original is not None:
                yield from collect(
                    getattr(original, "routes", []) or [], prefix + prefix_of(route)
                )
                continue
            inner = getattr(route, "routes", None)
            if inner:
                yield from collect(inner, prefix)

    operations = []
    for path, route in collect(app.routes):
        if not path.startswith("/api/v1/admin"):
            continue
        for method in sorted(set(route.methods or ()) & {"GET", "POST", "PUT", "PATCH", "DELETE"}):
            operations.append((method, path))
    return operations


def test_every_admin_operation_carries_require_admin():
    """A structural guard: adding an unguarded admin route fails this test immediately."""
    from app.api.admin import require_admin

    def declared_dependencies(route) -> set:
        found: set = set()

        def visit(dep):
            if dep.call is not None:
                found.add(dep.call)
            for child in dep.dependencies or ():
                visit(child)

        for dep in route.dependant.dependencies:
            visit(dep)
        return found

    from fastapi.routing import APIRoute

    def prefix_of(route) -> str:
        ctx = getattr(route, "include_context", None)
        return (getattr(ctx, "prefix", "") or "") if ctx is not None else ""

    def collect(routes, prefix: str = ""):
        for route in routes:
            if isinstance(route, APIRoute):
                yield prefix + route.path, route
                continue
            original = getattr(route, "original_router", None)
            if original is not None:
                yield from collect(
                    getattr(original, "routes", []) or [], prefix + prefix_of(route)
                )
                continue
            inner = getattr(route, "routes", None)
            if inner:
                yield from collect(inner, prefix)

    public_paths = {
        "/api/v1/admin/auth/login",
        "/api/v1/admin/auth/logout",
        "/api/v1/admin/auth/session",
    }
    guarded, public, unguarded = 0, 0, []
    for path, route in collect(app.routes):
        if not path.startswith("/api/v1/admin"):
            continue
        has_guard = require_admin in declared_dependencies(route)
        if has_guard:
            guarded += 1
        elif path in public_paths:
            public += 1
        else:
            unguarded.append(path)

    assert guarded >= 20, f"only {guarded} guarded admin routers — did the guard get dropped?"
    assert unguarded == [], f"admin routes without require_admin: {sorted(set(unguarded))}"
    assert public == 3, f"expected exactly 3 public auth routes, got {public}"


@pytest.mark.asyncio
async def test_no_admin_response_ever_contains_a_plaintext_secret(tmp_path, monkeypatch, caplog):
    """Sweep every admin GET with real secrets configured and scan the payloads + logs."""
    import logging as _logging

    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)

    provider_secret = "sk-LEAKCANARY-provider-9f8e7d6c5b4a3210"
    env_secret = "sk-LEAKCANARY-envvalue-1a2b3c4d5e6f"
    try:
        async with factory() as session:
            provider = AiProvider(
                name="leak-canary",
                provider_type="openai_compatible",
                base_url="https://example.invalid/v1",
                encrypted_api_key=crypto.encrypt_secret(provider_secret),
                capabilities=["chat", "embedding"],
                is_active=True,
            )
            session.add(provider)
            billing = await session.get(
                __import__("app.models.auth", fromlist=["BillingSettings"]).BillingSettings, 1
            )
            billing.system_config = {"llm_api_key": env_secret, "sms_api_key": "kavenegar-canary-000"}
            await session.commit()
            provider_id = provider.id

        caplog.set_level(_logging.DEBUG)
        secrets = (
            provider_secret,
            env_secret,
            "kavenegar-canary-000",
            "LEAKCANARY",
        )

        # Every parameterless admin GET is a pure read: safe to sweep in-process.
        # (POST probes make outbound calls and are covered by the diagnostics test.)
        suspicious = [
            (m, p)
            for m, p in _admin_operations()
            if m == "GET"
            and not p.startswith("/api/v1/admin/auth")
            and "{" not in p
        ]

        checked = 0
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for method, path in suspicious:
                response = await client.request(method, path, headers=ADMIN_HEADERS)
                body = response.text
                for secret in secrets:
                    assert secret not in body, f"{method} {path} leaked secret {secret!r}"
                checked += 1

            # The provider list must still show a mask, so masking is not silently broken.
            listed = await client.get("/api/v1/admin/providers", headers=ADMIN_HEADERS)
            payload = listed.json()["providers"]
            assert payload and payload[0]["api_key"] is None
            assert payload[0]["api_key_masked"].endswith(provider_secret[-4:])
            assert payload[0]["has_api_key"] is True
            assert payload[0]["id"] == provider_id

        assert checked >= 10, f"leak sweep only exercised {checked} endpoints"

        log_text = "\n".join(record.getMessage() for record in caplog.records)
        for secret in secrets:
            assert secret not in log_text, f"a secret was written to the logs: {secret!r}"
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()
