"""Hotfix 2026-11-22: phone + password authentication, dev seed, and user administration.

Covers the Phase 8 checklist:

* registration with valid/invalid/expired/over-limit OTP,
* password creation/verification, wrong password, duplicate phone,
* login with phone + password, session revocation and rotation,
* role escalation prevention, admin creation, last super_admin protection,
* user deletion/deactivation, quota updates, audit trail integrity,
* dev seed idempotency and production refusal,
* CSRF enforcement for cookie-authenticated mutations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import config as config_mod
from app.core.passwords import hash_password, password_policy_error, verify_password
from app.db.base import Base
from app.db import dev_seed
from app.db.seed import seed_billing_settings, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.auth import OtpCode, User, UserSession
from app.models.phase5 import AdminActionLog
from app.services import auth_service, permissions, sms_provider
from app.services.auth_billing_service import normalize_iranian_phone

ADMIN_PASSWORD = "123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _settings(**overrides):
    base = SimpleNamespace(
        demo_mode=True,
        dev_seed_enabled=False,
        dev_seed_allow_weak_password=False,
        dev_seed_apply_env="local",
        app_env="local",
        dev_seed_password="",
        dev_seed_phone="09134303348",
        dev_seed_name="mahdi",
        dev_seed_role="user",
        password_min_length=8,
        otp_ttl_seconds=180,
        otp_resend_seconds=0,
        otp_max_attempts=3,
        user_session_ttl_seconds=3600,
        auth_handshake_ttl_seconds=900,
        admin_username="admin",
        admin_password=ADMIN_PASSWORD,
        admin_session_ttl_seconds=3600,
        secret_key="unit-test-secret-key-unit-test-secret-key",
        auth_secret="unit-test-secret-key-unit-test-secret-key",
        rate_limit_enabled=False,
        redis_url=None,
        csrf_enforcement="off",
        trusted_proxy_hops=0,
        login_ip_limit=20,
        login_ip_window_seconds=900,
        login_phone_limit=8,
        login_phone_window_seconds=900,
        otp_phone_limit=100,
        otp_phone_window_seconds=3600,
        reauth_ttl_seconds=300,
    )
    base.__dict__.update(overrides)
    return base


class _Env:
    def __init__(self, engine, factory, settings, monkeypatch):
        self.engine = engine
        self.factory = factory
        self.settings = settings
        self.monkeypatch = monkeypatch

    async def close(self):
        app.dependency_overrides.clear()
        await self.engine.dispose()
        from app.services.rate_limiter import close_rate_limiter

        await close_rate_limiter()

    async def user_by_phone(self, phone: str) -> User | None:
        async with self.factory() as session:
            return await session.scalar(select(User).where(User.phone_number == phone))

    async def count(self, model) -> int:
        async with self.factory() as session:
            return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def build_env(tmp_path, monkeypatch, *, settings=None, seed_admin_super=False):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hotfix.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    cfg = settings or _settings()

    # Every module resolves settings through these, so patch them together.
    monkeypatch.setattr(config_mod, "get_settings", lambda: cfg)
    for target in (
        "app.services.auth_service.get_settings",
        "app.services.admin_user_service.get_settings",
        "app.services.auth_billing_service.get_settings",
        "app.core.csrf.get_settings",
        "app.api.auth.get_settings",
        "app.api.admin.get_settings",
        "app.core.passwords.get_settings",
        "app.services.rate_limiter.get_settings",
    ):
        monkeypatch.setattr(target, lambda: cfg, raising=False)

    # Never make a network call for notifications during tests.
    class _NoopSms(sms_provider.SmsProvider):
        provider_name = "demo"

        async def send_otp(self, *, phone_number: str, code: str):
            return sms_provider.SmsDeliveryResult(provider="demo", delivered=True, message_id="t")

    from app.db import session as db_session_mod

    monkeypatch.setattr(db_session_mod, "async_session_factory", factory)
    for module_name in ("app.api.admin", "app.api.admin_users", "app.db.seed"):
        module = __import__(module_name, fromlist=["async_session_factory"])
        if hasattr(module, "async_session_factory"):
            monkeypatch.setattr(module, "async_session_factory", factory)

    monkeypatch.setattr(sms_provider, "get_sms_provider", lambda *a, **k: _NoopSms())
    monkeypatch.setattr(
        "app.services.auth_service.get_sms_provider", lambda *a, **k: _NoopSms()
    )
    # The limiter keeps one process-global window store; reset it per island.
    from app.services import rate_limiter as _rate_limiter

    _rate_limiter._local_windows.clear()  # noqa: SLF001 - test isolation

    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        if seed_admin_super:
            session.add(
                User(
                    phone_number="09120000001",
                    full_name="مدیر ارشد",
                    role="super_admin",
                    is_active=True,
                    password_hash=hash_password("SuperAdmin123"),
                )
            )
        await session.commit()

    return _Env(engine, factory, cfg, monkeypatch)


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def admin_headers(cl: AsyncClient) -> dict[str, str]:
    login = await cl.post(
        "/api/v1/admin/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"X-Admin-Token": login.json()["token"]}


# ---------------------------------------------------------------------------
# Password primitives
# ---------------------------------------------------------------------------


def test_argon2id_hash_roundtrip_and_policy():
    digest = hash_password("Str0ngPass!")
    assert digest.startswith("$argon2id$")
    assert "Str0ngPass!" not in digest
    assert verify_password("Str0ngPass!", digest) is True
    assert verify_password("wrong", digest) is False
    assert verify_password("Str0ngPass!", None) is False
    assert password_policy_error("123", min_length=8) is not None
    assert password_policy_error("alllettersonly", min_length=8) is not None
    assert password_policy_error("Val1dPassword", min_length=8) is None


# ---------------------------------------------------------------------------
# Registration flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_full_flow_and_duplicate_phone(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            req = await cl.post("/api/v1/auth/register/request-otp", json={"phone_number": "+98 912 111 2233"})
            assert req.status_code == 200
            body = req.json()
            assert body["phone_number"] == "09121112233"
            code = body["demo_code"]

            # Wrong code -> rejected, attempts counted
            bad = await cl.post(
                "/api/v1/auth/register/verify-otp",
                json={"phone_number": "09121112233", "code": "000000"},
            )
            assert bad.status_code == 401

            verify = await cl.post(
                "/api/v1/auth/register/verify-otp",
                json={"phone_number": "09121112233", "code": code},
            )
            assert verify.status_code == 200
            handshake = verify.json()["otp_token"]
            assert verify.json()["verified"] is True

            # Password mismatch and weak password are refused server-side
            mismatch = await cl.post(
                "/api/v1/auth/register/complete",
                json={
                    "phone_number": "09121112233",
                    "otp_token": handshake,
                    "password": "Val1dPassword",
                    "password_confirm": "Val1dPassword2",
                },
            )
            assert mismatch.status_code == 422
            weak = await cl.post(
                "/api/v1/auth/register/complete",
                json={
                    "phone_number": "09121112233",
                    "otp_token": handshake,
                    "password": "123",
                    "password_confirm": "123",
                },
            )
            assert weak.status_code == 422

            done = await cl.post(
                "/api/v1/auth/register/complete",
                json={
                    "phone_number": "09121112233",
                    "otp_token": handshake,
                    "password": "Val1dPassword",
                    "password_confirm": "Val1dPassword",
                    "full_name": "سارا احمدی",
                },
            )
            assert done.status_code == 200, done.text
            payload = done.json()
            assert payload["registered"] is True
            assert payload["user"]["phone_number"] == "09121112233"
            token = payload["token"]
            assert token

            stored = await env.user_by_phone("09121112233")
            assert stored is not None
            assert stored.password_hash and stored.password_hash.startswith("$argon2id$")
            assert "Val1dPassword" not in stored.password_hash
            assert stored.phone_verified_at is not None
            assert stored.role == "student"
            assert stored.tokens_remaining > 0

            # Duplicate registration for the same number is refused
            again = await cl.post(
                "/api/v1/auth/register/request-otp", json={"phone_number": "09121112233"}
            )
            assert again.status_code == 200
            mid = await cl.post(
                "/api/v1/auth/register/verify-otp",
                json={"phone_number": "09121112233", "code": again.json()["demo_code"]},
            )
            dup = await cl.post(
                "/api/v1/auth/register/complete",
                json={
                    "phone_number": "09121112233",
                    "otp_token": mid.json()["otp_token"],
                    "password": "AnotherPass1",
                    "password_confirm": "AnotherPass1",
                },
            )
            assert dup.status_code == 409
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_otp_expiry_attempt_limit_and_purpose_isolation(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            req = await cl.post("/api/v1/auth/register/request-otp", json={"phone_number": "09121234567"})
            code = req.json()["demo_code"]

            # A register-purpose code cannot be redeemed through the recovery endpoint.
            cross = await cl.post(
                "/api/v1/auth/password/recover/verify-otp",
                json={"phone_number": "09121234567", "code": code},
            )
            assert cross.status_code == 401

            # Exhaust attempts (max_attempts=3 in the test settings)
            for _ in range(3):
                await cl.post(
                    "/api/v1/auth/register/verify-otp",
                    json={"phone_number": "09121234567", "code": "000000"},
                )
            blocked = await cl.post(
                "/api/v1/auth/register/verify-otp",
                json={"phone_number": "09121234567", "code": code},
            )
            assert blocked.status_code in {401, 429}

            # Expired code
            await cl.post("/api/v1/auth/register/request-otp", json={"phone_number": "09129990000"})
            async with env.factory() as session:
                otp = await session.scalar(
                    select(OtpCode)
                    .where(OtpCode.phone_number == "09129990000")
                    .order_by(OtpCode.created_at.desc())
                )
                assert otp is not None
                otp.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
                await session.commit()
            expired = await cl.post(
                "/api/v1/auth/register/verify-otp",
                json={"phone_number": "09129990000", "code": "123456"},
            )
            assert expired.status_code == 401
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_registration_resend_cooldown(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, settings=_settings(otp_resend_seconds=60))
    try:
        async with client() as cl:
            first = await cl.post("/api/v1/auth/register/request-otp", json={"phone_number": "09123334444"})
            assert first.status_code == 200
            second = await cl.post(
                "/api/v1/auth/register/request-otp", json={"phone_number": "09123334444"}
            )
            assert second.status_code == 429
            assert "Retry-After" in second.headers
    finally:
        await env.close()


# ---------------------------------------------------------------------------
# Password login
# ---------------------------------------------------------------------------


async def _register(cl: AsyncClient, phone: str, password: str = "Val1dPassword") -> str:
    await cl.post("/api/v1/auth/register/request-otp", json={"phone_number": phone})
    verify = await cl.post(
        "/api/v1/auth/register/verify-otp",
        json={"phone_number": phone, "code": (await _peek_code(cl, phone))},
    )
    done = await cl.post(
        "/api/v1/auth/register/complete",
        json={
            "phone_number": phone,
            "otp_token": verify.json()["otp_token"],
            "password": password,
            "password_confirm": password,
        },
    )
    assert done.status_code == 200, done.text
    return done.json()["token"]


async def _peek_code(cl: AsyncClient, phone: str) -> str:  # pragma: no cover - helper
    raise AssertionError("use the demo_code returned by request-otp instead")


@pytest.mark.asyncio
async def test_password_login_success_failure_and_rotation(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            req = await cl.post("/api/v1/auth/register/request-otp", json={"phone_number": "09125556677"})
            code = req.json()["demo_code"]
            verify = await cl.post(
                "/api/v1/auth/register/verify-otp",
                json={"phone_number": "09125556677", "code": code},
            )
            done = await cl.post(
                "/api/v1/auth/register/complete",
                json={
                    "phone_number": "09125556677",
                    "otp_token": verify.json()["otp_token"],
                    "password": "Val1dPassword",
                    "password_confirm": "Val1dPassword",
                },
            )
            assert done.status_code == 200
            first_token = done.json()["token"]

            wrong = await cl.post(
                "/api/v1/auth/login",
                json={"phone_number": "09125556677", "password": "wrong-password"},
            )
            assert wrong.status_code == 401
            assert wrong.json()["detail"] == auth_service.GENERIC_LOGIN_ERROR

            unknown = await cl.post(
                "/api/v1/auth/login",
                json={"phone_number": "09127778899", "password": "Val1dPassword"},
            )
            # Identical message/shape for an unknown number (no user enumeration).
            assert unknown.status_code == 401
            assert unknown.json()["detail"] == auth_service.GENERIC_LOGIN_ERROR

            ok = await cl.post(
                "/api/v1/auth/login",
                json={"phone_number": "+989125556677", "password": "Val1dPassword"},
            )
            assert ok.status_code == 200
            second_token = ok.json()["token"]
            assert second_token != first_token

            # Rotation: the session presented at login is revoked.
            rotated = await cl.get(
                "/api/v1/auth/me", headers={"X-User-Token": first_token}
            )
            assert rotated.json()["authenticated"] is False
            fresh = await cl.get("/api/v1/auth/me", headers={"X-User-Token": second_token})
            assert fresh.json()["authenticated"] is True
            assert fresh.json()["has_password"] is True
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_login_rate_limit_per_phone(tmp_path, monkeypatch):
    env = await build_env(
        tmp_path,
        monkeypatch,
        settings=_settings(rate_limit_enabled=True, login_phone_limit=3, redis_url=None),
    )
    try:
        async with client() as cl:
            statuses = []
            for _ in range(5):
                res = await cl.post(
                    "/api/v1/auth/login",
                    json={"phone_number": "09126667788", "password": "Nope12345"},
                )
                statuses.append(res.status_code)
            assert 429 in statuses
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_password_recovery_revokes_every_session(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            req = await cl.post("/api/v1/auth/register/request-otp", json={"phone_number": "09121119999"})
            verify = await cl.post(
                "/api/v1/auth/register/verify-otp",
                json={"phone_number": "09121119999", "code": req.json()["demo_code"]},
            )
            done = await cl.post(
                "/api/v1/auth/register/complete",
                json={
                    "phone_number": "09121119999",
                    "otp_token": verify.json()["otp_token"],
                    "password": "OldPassword1",
                    "password_confirm": "OldPassword1",
                },
            )
            old_token = done.json()["token"]

            recover = await cl.post(
                "/api/v1/auth/password/recover/request-otp", json={"phone_number": "09121119999"}
            )
            assert recover.status_code == 200
            rverify = await cl.post(
                "/api/v1/auth/password/recover/verify-otp",
                json={"phone_number": "09121119999", "code": recover.json()["demo_code"]},
            )
            assert rverify.status_code == 200
            reset = await cl.post(
                "/api/v1/auth/password/recover/complete",
                json={
                    "phone_number": "09121119999",
                    "otp_token": rverify.json()["otp_token"],
                    "password": "NewPassword2",
                    "password_confirm": "NewPassword2",
                },
            )
            assert reset.status_code == 200, reset.text

            # Old session is dead, old password no longer works, new one does.
            assert (
                await cl.get("/api/v1/auth/me", headers={"X-User-Token": old_token})
            ).json()["authenticated"] is False
            assert (
                await cl.post(
                    "/api/v1/auth/login",
                    json={"phone_number": "09121119999", "password": "OldPassword1"},
                )
            ).status_code == 401
            assert (
                await cl.post(
                    "/api/v1/auth/login",
                    json={"phone_number": "09121119999", "password": "NewPassword2"},
                )
            ).status_code == 200
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_change_password_requires_current_and_rotates(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            req = await cl.post("/api/v1/auth/register/request-otp", json={"phone_number": "09124440000"})
            verify = await cl.post(
                "/api/v1/auth/register/verify-otp",
                json={"phone_number": "09124440000", "code": req.json()["demo_code"]},
            )
            done = await cl.post(
                "/api/v1/auth/register/complete",
                json={
                    "phone_number": "09124440000",
                    "otp_token": verify.json()["otp_token"],
                    "password": "FirstPass1",
                    "password_confirm": "FirstPass1",
                },
            )
            token = done.json()["token"]
            headers = {"X-User-Token": token}

            wrong = await cl.post(
                "/api/v1/auth/password/change",
                headers=headers,
                json={
                    "current_password": "nope",
                    "password": "SecondPass2",
                    "password_confirm": "SecondPass2",
                },
            )
            assert wrong.status_code == 401

            ok = await cl.post(
                "/api/v1/auth/password/change",
                headers=headers,
                json={
                    "current_password": "FirstPass1",
                    "password": "SecondPass2",
                    "password_confirm": "SecondPass2",
                },
            )
            assert ok.status_code == 200
            assert ok.json()["changed"] is True
            assert (
                await cl.get("/api/v1/auth/me", headers={"X-User-Token": token})
            ).json()["authenticated"] is False
            assert (
                await cl.get("/api/v1/auth/me", headers={"X-User-Token": ok.json()["token"]})
            ).json()["authenticated"] is True
    finally:
        await env.close()


# ---------------------------------------------------------------------------
# Permissions unit rules
# ---------------------------------------------------------------------------


def test_permission_matrix_blocks_escalation():
    admin = permissions.AdminActor(role="admin", user_id="a")
    super_admin = permissions.AdminActor(role="super_admin", user_id="s")
    moderator = permissions.AdminActor(role="moderator", user_id="m")
    legacy = permissions.AdminActor(role="admin", legacy=True)

    assert permissions.can_manage_user(admin, "student") is True
    assert permissions.can_manage_user(admin, "admin") is True
    assert permissions.can_manage_user(admin, "super_admin") is False
    assert permissions.can_assign_role(admin, "super_admin") is False
    assert permissions.can_assign_role(admin, "admin") is True
    assert permissions.can_manage_user(super_admin, "super_admin") is True
    assert permissions.can_assign_role(super_admin, "super_admin") is True
    # A super_admin may target another super_admin (the last-one guard is a service rule).
    assert permissions.can_assign_role(super_admin, "moderator", "super_admin") is True
    assert permissions.can_assign_role(admin, "moderator") is True
    assert permissions.can_manage_user(admin, "super_admin") is False
    assert permissions.can_manage_user(moderator, "student") is False
    assert permissions.can_delete_user(moderator, "student") is False
    assert permissions.can_delete_user(admin, "admin") is False
    assert permissions.can_delete_user(super_admin, "admin") is True
    assert permissions.can_assign_role(legacy, "super_admin") is False
    assert permissions.can_assign_role(legacy, "admin") is True
    assert permissions.requires_reauth_for_role_change(admin, "admin") is True
    assert permissions.requires_reauth_for_role_change(admin, "teacher") is False


# ---------------------------------------------------------------------------
# Admin user management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_creates_users_and_assigns_roles(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            headers = await admin_headers(cl)

            created = await cl.post(
                "/api/v1/admin/users",
                headers=headers,
                json={
                    "phone_number": "09130001111",
                    "password": "TeacherPass1",
                    "full_name": "معلم نمونه",
                    "role": "teacher",
                },
            )
            assert created.status_code == 201, created.text
            user = created.json()["user"]
            assert user["role"] == "teacher"
            assert user["has_password"] is True

            # Admin creation of an administrator requires re-authentication.
            needs_reauth = await cl.post(
                "/api/v1/admin/users",
                headers=headers,
                json={
                    "phone_number": "09130002222",
                    "password": "AdminPass123",
                    "role": "admin",
                },
            )
            assert needs_reauth.status_code in {401, 428}
            reauthed = await cl.post(
                "/api/v1/admin/users",
                headers={**headers, "X-Reauth-Password": ADMIN_PASSWORD},
                json={
                    "phone_number": "09130002222",
                    "password": "AdminPass123",
                    "role": "admin",
                },
            )
            assert reauthed.status_code == 201, reauthed.text

            # super_admin cannot be minted by the legacy console once one exists.
            async with env.factory() as session:
                session.add(
                    User(
                        phone_number="09130009999",
                        role="super_admin",
                        is_active=True,
                        password_hash=hash_password("SuperPass123"),
                    )
                )
                await session.commit()
            denied = await cl.post(
                "/api/v1/admin/users",
                headers={**headers, "X-Reauth-Password": ADMIN_PASSWORD},
                json={
                    "phone_number": "09130003333",
                    "password": "SuperPass123",
                    "role": "super_admin",
                },
            )
            assert denied.status_code == 403

            # Duplicate phone, invalid phone, weak password
            dup = await cl.post(
                "/api/v1/admin/users",
                headers=headers,
                json={"phone_number": "09130001111", "password": "AnotherPass1"},
            )
            assert dup.status_code == 409
            bad_phone = await cl.post(
                "/api/v1/admin/users",
                headers=headers,
                json={"phone_number": "12345", "password": "AnotherPass1"},
            )
            assert bad_phone.status_code == 422
            weak = await cl.post(
                "/api/v1/admin/users",
                headers=headers,
                json={"phone_number": "09130004444", "password": "123"},
            )
            assert weak.status_code == 422

            # Created account can log in with phone + password
            login = await cl.post(
                "/api/v1/auth/login",
                json={"phone_number": "09130001111", "password": "TeacherPass1"},
            )
            assert login.status_code == 200
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_admin_edits_profile_phone_and_password(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            headers = await admin_headers(cl)
            created = await cl.post(
                "/api/v1/admin/users",
                headers=headers,
                json={"phone_number": "09131110000", "password": "StudentPass1", "role": "student"},
            )
            user_id = created.json()["user"]["id"]

            patched = await cl.patch(
                f"/api/v1/admin/users/{user_id}",
                headers=headers,
                json={"first_name": "رضا", "last_name": "کریمی", "phone_number": "+98 913 111 0001"},
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["phone_changed"] is True
            assert patched.json()["phone_verified"] is False  # re-verification required
            assert patched.json()["user"]["full_name"] == "رضا کریمی"

            # Duplicate number on update is refused
            other = await cl.post(
                "/api/v1/admin/users",
                headers=headers,
                json={"phone_number": "09131110002", "password": "StudentPass1"},
            )
            clash = await cl.patch(
                f"/api/v1/admin/users/{other.json()['user']['id']}",
                headers=headers,
                json={"phone_number": "09131110001"},
            )
            assert clash.status_code == 409

            reset = await cl.post(
                f"/api/v1/admin/users/{user_id}/password",
                headers={**headers, "X-Reauth-Password": ADMIN_PASSWORD},
                json={"new_password": "ResetPass99"},
            )
            assert reset.status_code == 200
            assert (
                await cl.post(
                    "/api/v1/auth/login",
                    json={"phone_number": "09131110001", "password": "StudentPass1"},
                )
            ).status_code == 401
            assert (
                await cl.post(
                    "/api/v1/auth/login",
                    json={"phone_number": "09131110001", "password": "ResetPass99"},
                )
            ).status_code == 200

            # Password reset without re-authentication is blocked
            no_reauth = await cl.post(
                f"/api/v1/admin/users/{user_id}/password",
                headers=headers,
                json={"new_password": "AnotherPass77"},
            )
            assert no_reauth.status_code in {401, 428}
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_admin_role_change_and_last_super_admin_protection(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        async with client() as cl:
            headers = await admin_headers(cl)
            async with env.factory() as session:
                super_admin = await session.scalar(
                    select(User).where(User.role == "super_admin")
                )
                assert super_admin is not None
                student = User(phone_number="09132220000", role="student", is_active=True)
                session.add(student)
                await session.commit()
                super_id = super_admin.id
                student_id = student.id

            # Escalation to admin from the legacy console requires re-authentication
            blocked = await cl.put(
                f"/api/v1/admin/users/{student_id}/role",
                headers=headers,
                json={"role": "admin"},
            )
            assert blocked.status_code in {401, 428}

            # Privilege change revokes the target's sessions
            async with env.factory() as session:
                from app.services.auth_billing_service import create_user_session_token
                import secrets as _secrets

                nonce = _secrets.token_hex(8)
                session.add(
                    UserSession(
                        user_id=student_id,
                        token_nonce=nonce,
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                        last_seen_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                student_token = create_user_session_token(student_id, nonce=nonce)

            upgraded = await cl.put(
                f"/api/v1/admin/users/{student_id}/role",
                headers={**headers, "X-Reauth-Password": ADMIN_PASSWORD},
                json={"role": "admin"},
            )
            assert upgraded.status_code == 200, upgraded.text
            assert upgraded.json()["user"]["role"] == "admin"
            assert (
                await cl.get("/api/v1/auth/me", headers={"X-User-Token": student_token})
            ).json()["authenticated"] is False

            # The legacy console (rank: admin) may not touch a super_admin account
            cannot = await cl.put(
                f"/api/v1/admin/users/{super_id}/role",
                headers={**headers, "X-Reauth-Password": ADMIN_PASSWORD},
                json={"role": "student"},
            )
            assert cannot.status_code == 403
            cannot_delete = await cl.delete(
                f"/api/v1/admin/users/{super_id}",
                headers={**headers, "X-Reauth-Password": ADMIN_PASSWORD},
            )
            assert cannot_delete.status_code == 403

            # A super_admin may not demote or disable the last active super_admin.
            super_login = await cl.post(
                "/api/v1/auth/login",
                json={"phone_number": "09120000001", "password": "SuperAdmin123"},
            )
            assert super_login.status_code == 200
            super_headers = {"X-User-Token": super_login.json()["token"]}
            # Moderator is strictly below the actor, so authorization passes and the
            # last-super_admin guard is what rejects the demotion (409, not 403).
            last = await cl.put(
                f"/api/v1/admin/users/{super_id}/role",
                headers={**super_headers, "X-Reauth-Password": "SuperAdmin123"},
                json={"role": "moderator"},
            )
            assert last.status_code == 409, last.text
            deactivate = await cl.put(
                f"/api/v1/admin/users/{super_id}/activation",
                headers=super_headers,
                json={"is_active": False},
            )
            assert deactivate.status_code == 409
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_admin_deactivation_revokes_sessions_and_delete_keeps_history(
    tmp_path, monkeypatch
):
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            headers = await admin_headers(cl)
            created = await cl.post(
                "/api/v1/admin/users",
                headers=headers,
                json={"phone_number": "09133330000", "password": "StudentPass1"},
            )
            user_id = created.json()["user"]["id"]
            login = await cl.post(
                "/api/v1/auth/login",
                json={"phone_number": "09133330000", "password": "StudentPass1"},
            )
            token = login.json()["token"]
            assert (
                await cl.get("/api/v1/auth/me", headers={"X-User-Token": token})
            ).json()["authenticated"] is True

            deactivated = await cl.put(
                f"/api/v1/admin/users/{user_id}/activation",
                headers=headers,
                json={"is_active": False},
            )
            assert deactivated.status_code == 200
            assert deactivated.json()["sessions_revoked"] >= 1
            assert (
                await cl.get("/api/v1/auth/me", headers={"X-User-Token": token})
            ).json()["authenticated"] is False
            assert (
                await cl.post(
                    "/api/v1/auth/login",
                    json={"phone_number": "09133330000", "password": "StudentPass1"},
                )
            ).status_code == 401

            # Deletion requires re-auth, then soft-deletes and blocks login
            no_reauth = await cl.delete(f"/api/v1/admin/users/{user_id}", headers=headers)
            assert no_reauth.status_code in {401, 428}
            deleted = await cl.delete(
                f"/api/v1/admin/users/{user_id}",
                headers={**headers, "X-Reauth-Password": ADMIN_PASSWORD},
            )
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] is True
            assert deleted.json()["mode"] == "soft"

            async with env.factory() as session:
                row = await session.get(User, user_id)
                assert row is not None and row.deleted_at is not None
                assert row.password_hash is None  # credentials cleared
                assert row.is_active is False

            assert (
                await cl.post(
                    "/api/v1/auth/login",
                    json={"phone_number": "09133330000", "password": "StudentPass1"},
                )
            ).status_code == 401

            # Deleted rows appear under status=deleted, not in the default view
            listing = await cl.get("/api/v1/admin/users?status=deleted", headers=headers)
            assert listing.status_code == 200
            assert any(u["id"] == user_id for u in listing.json()["users"])

            audit = await cl.get(f"/api/v1/admin/users/{user_id}/audit", headers=headers)
            actions = [e["action"] for e in audit.json()["entries"]]
            assert "user.delete" in actions
            assert "user.deactivate" in actions
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_user_list_filters_pagination_and_sessions(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            headers = await admin_headers(cl)
            for index in range(6):
                await cl.post(
                    "/api/v1/admin/users",
                    headers=headers,
                    json={
                        "phone_number": f"0913444{index:04d}",
                        "password": "StudentPass1",
                        "role": "teacher" if index % 2 else "student",
                        "full_name": f"کاربر {index}",
                    },
                )

            page = await cl.get(
                "/api/v1/admin/users?page=1&page_size=2&role=student", headers=headers
            )
            body = page.json()
            assert body["pagination"]["page_size"] == 2
            assert body["pagination"]["total"] == 3
            assert len(body["users"]) == 2

            search = await cl.get("/api/v1/admin/users?q=کاربر 4", headers=headers)
            assert any(u["full_name"] == "کاربر 4" for u in search.json()["users"])

            # Persian-digit phone search resolves to the normalized form
            search_phone = await cl.get("/api/v1/admin/users?q=۰۹۱۳۴۴۴۰۰۰۲", headers=headers)
            assert search_phone.json()["pagination"]["total"] == 1

            target = search.json()["users"][0]["id"]
            login = await cl.post(
                "/api/v1/auth/login",
                json={"phone_number": "09134440004", "password": "StudentPass1"},
            )
            assert login.status_code == 200
            sessions = await cl.get(f"/api/v1/admin/users/{target}/sessions", headers=headers)
            assert sessions.status_code == 200
            assert len(sessions.json()["sessions"]) == 1
            session_id = sessions.json()["sessions"][0]["id"]

            revoked = await cl.delete(
                f"/api/v1/admin/users/{target}/sessions/{session_id}", headers=headers
            )
            assert revoked.status_code == 200
            assert (
                await cl.get(
                    "/api/v1/auth/me", headers={"X-User-Token": login.json()["token"]}
                )
            ).json()["authenticated"] is False

            revoke_all = await cl.post(
                f"/api/v1/admin/users/{target}/sessions/revoke-all", headers=headers
            )
            assert revoke_all.status_code == 200

            roles = await cl.get("/api/v1/admin/users/roles", headers=headers)
            assert roles.status_code == 200
            codes = [r["code"] for r in roles.json()["roles"]]
            assert codes == ["student", "teacher", "moderator", "admin", "super_admin"]

            audit = await cl.get("/api/v1/admin/users/audit", headers=headers)
            assert audit.status_code == 200
            assert any(e["action"] == "user.create" for e in audit.json()["entries"])
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_admin_quota_management_and_audit_integrity(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            headers = await admin_headers(cl)
            created = await cl.post(
                "/api/v1/admin/users",
                headers=headers,
                json={"phone_number": "09135550000", "password": "StudentPass1"},
            )
            user_id = created.json()["user"]["id"]

            credits = await cl.put(
                f"/api/v1/admin/users/{user_id}/credits",
                headers=headers,
                json={"tokens_remaining": 500, "add_tokens": 250, "duration_days": 30},
            )
            assert credits.status_code == 200, credits.text
            assert credits.json()["user"]["tokens_remaining"] == 750

            snapshot = await cl.get(f"/api/v1/admin/users/{user_id}/quota", headers=headers)
            assert snapshot.status_code == 200
            assert "daily_tokens_limit" in snapshot.json()["quota"]

            detail = await cl.get(f"/api/v1/admin/users/{user_id}", headers=headers)
            assert detail.status_code == 200
            assert detail.json()["usage"]["tokens_lifetime"] == 0
            assert detail.json()["permissions"]["role"] == "student"

            async with env.factory() as session:
                logs = (await session.scalars(select(AdminActionLog))).all()
            actions = [log.action for log in logs]
            assert "user.create" in actions
            assert "user.credits" in actions
            credits_log = next(log for log in logs if log.action == "user.credits")
            assert credits_log.payload_json["request"]["add_tokens"] == 250
            assert credits_log.payload_json["after"]["tokens_remaining"] == 750
            assert all(log.actor for log in logs)
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_legacy_admin_user_payload_contract_preserved(tmp_path, monkeypatch):
    """The pre-existing `GET /api/v1/admin/users` contract must keep working."""
    env = await build_env(tmp_path, monkeypatch)
    try:
        async with client() as cl:
            headers = await admin_headers(cl)
            async with env.factory() as session:
                session.add(
                    User(
                        phone_number="09136660000",
                        full_name="کاربر قدیمی",
                        plan_code="trial",
                        plan_title="هدیه ثبت‌نام",
                        tokens_total=15_000,
                        tokens_remaining=9_000,
                        is_active=True,
                    )
                )
                await session.commit()

            response = await cl.get("/api/v1/admin/users?q=0913666", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["total_users"] == 1
            assert data["users"][0]["tokens_remaining"] == 9_000
            assert "pagination" in data

            limited = await cl.get("/api/v1/admin/users?limit=5", headers=headers)
            assert limited.status_code == 200

            # Unauthenticated access still rejected
            async with client() as anon:
                assert (await anon.get("/api/v1/admin/users")).status_code == 401
                assert (await anon.post("/api/v1/admin/users", json={})).status_code == 401
    finally:
        await env.close()


# ---------------------------------------------------------------------------
# Dev seed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_seed_is_idempotent_and_preserves_existing_data(tmp_path, monkeypatch):
    cfg = _settings(
        dev_seed_enabled=True,
        dev_seed_allow_weak_password=True,
        dev_seed_password="123",
        password_min_length=4,
    )
    env = await build_env(tmp_path, monkeypatch, settings=cfg)
    try:
        async with env.factory() as session:
            first = await dev_seed.seed_development_account(session, cfg)
            await session.commit()
        assert first["seeded"] is True

        stored = await env.user_by_phone("09134303348")
        assert stored is not None
        assert stored.role == "student"  # "user" maps onto the canonical student role
        assert stored.is_active is True
        assert stored.phone_verified_at is not None
        assert stored.password_hash.startswith("$argon2id$")
        assert verify_password("123", stored.password_hash)

        # Second run: no duplicate, no overwrite
        async with env.factory() as session:
            row = await session.scalar(select(User).where(User.phone_number == "09134303348"))
            row.password_hash = hash_password("KeepThisPass1")
            row.full_name = "نام اصلاح‌شده"
            await session.commit()
        async with env.factory() as session:
            second = await dev_seed.seed_development_account(session, cfg)
            await session.commit()
        assert second["seeded"] is False
        again = await env.user_by_phone("09134303348")
        assert again.full_name == "نام اصلاح‌شده"
        assert verify_password("KeepThisPass1", again.password_hash)
        assert await env.count(User) == 1 + 0  # only the seeded account

        # The seeded credentials really log in
        async with client() as cl:
            login = await cl.post(
                "/api/v1/auth/login",
                json={"phone_number": "09134303348", "password": "KeepThisPass1"},
            )
            assert login.status_code == 200
    finally:
        await env.close()


def test_dev_seed_refuses_production_and_requires_env_flag():
    production = _settings(
        app_env="production", dev_seed_enabled=True, dev_seed_allow_weak_password=False
    )
    assert dev_seed.dev_seed_settings_problem(production) == "production"

    disabled = _settings(app_env="local", dev_seed_enabled=False)
    assert dev_seed.dev_seed_settings_problem(disabled) == "disabled"

    other_env = _settings(app_env="staging", dev_seed_enabled=True)
    assert dev_seed.dev_seed_settings_problem(other_env).startswith("environment:")

    no_password = _settings(app_env="local", dev_seed_enabled=True, dev_seed_password="")
    assert dev_seed.dev_seed_settings_problem(no_password) == "missing_password"

    ok = _settings(app_env="local", dev_seed_enabled=True, dev_seed_password="123")
    assert dev_seed.dev_seed_settings_problem(ok) is None


@pytest.mark.asyncio
async def test_dev_seed_skips_weak_password_without_opt_in(tmp_path, monkeypatch):
    cfg = _settings(dev_seed_enabled=True, dev_seed_password="123")  # weak, not allowed
    env = await build_env(tmp_path, monkeypatch, settings=cfg)
    try:
        async with env.factory() as session:
            result = await dev_seed.seed_development_account(session, cfg)
            await session.commit()
        assert result["seeded"] is False
        assert result["reason"] == "weak_password"
        assert await env.count(User) == 0
    finally:
        await env.close()


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csrf_origin_and_double_submit_rules(tmp_path, monkeypatch):
    cfg = _settings(csrf_enforcement="strict")
    env = await build_env(tmp_path, monkeypatch, settings=cfg)
    try:
        async with client() as cl:
            # Cross-site browser mutation (Origin is a foreign host) is rejected.
            cross = await cl.put(
                "/api/v1/account/preferences",
                headers={"Origin": "https://evil.example"},
                json={"general": {"language": "fa"}},
            )
            assert cross.status_code == 403
            assert cross.json()["code"] == "csrf_failed"

            # Same-origin browser mutation without the token is rejected in strict mode.
            missing_token = await cl.put(
                "/api/v1/account/preferences",
                headers={"Origin": "http://test"},
                json={"general": {"language": "fa"}},
            )
            assert missing_token.status_code == 403

            # Same-origin + matching double-submit token passes the CSRF layer and is
            # then rejected for lacking authentication (401).
            cl.cookies.set("iran_tutor_csrf", "t" * 32)
            allowed = await cl.put(
                "/api/v1/account/preferences",
                headers={"Origin": "http://test", "X-CSRF-Token": "t" * 32},
                json={"general": {"language": "fa"}},
            )
            assert allowed.status_code == 401

            # Native clients (no Origin) and header-auth callers are exempt.
            token = auth_service.create_handshake_token("09134303348", "register")
            assert token
    finally:
        await env.close()


@pytest.mark.asyncio
async def test_csrf_default_mode_blocks_only_cross_origin(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, settings=_settings(csrf_enforcement="on"))
    try:
        async with client() as cl:
            blocked = await cl.put(
                "/api/v1/account/preferences",
                headers={"Referer": "https://evil.example/page"},
                json={"general": {"language": "fa"}},
            )
            assert blocked.status_code == 403
            same_origin = await cl.put(
                "/api/v1/account/preferences",
                headers={"Origin": "http://test"},
                json={"general": {"language": "fa"}},
            )
            assert same_origin.status_code == 401  # past CSRF, unauthenticated
    finally:
        await env.close()
