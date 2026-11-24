"""Regression tests: TTS import, non-ASCII auth input, session keys, rate limits, headers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import admin as admin_api
from app.core import signing
from app.core.client_ip import client_ip, constant_time_equal
from app.core.production_guard import production_violations
from app.main import app
from app.services import capability_runtime
from app.services.rate_limiter import RateLimitDecision


@pytest.mark.asyncio
async def test_tts_runtime_resolves_speech_gateway(monkeypatch):
    """`run_capability_speech` used to raise NameError: speech_via_gateway was not imported."""
    calls: list[dict] = []

    async def fake_speech(**kwargs):
        calls.append(kwargs)
        return b"audio", SimpleNamespace(provider="test")

    monkeypatch.setattr(capability_runtime, "speech_via_gateway", fake_speech)
    audio, _ = await capability_runtime.run_capability_speech(
        session=None,
        capability_key="tts",
        user=None,
        user_id=None,
        book_id=None,
        text="سلام",
        voice="alloy",
        enforce=False,
    )
    assert audio == b"audio"
    assert calls and calls[0]["text"] == "سلام"


@pytest.mark.asyncio
async def test_admin_login_with_persian_credentials_returns_401_not_500():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/admin/auth/login", json={"username": "admin", "password": "رمز-فارسی-۱۲۳"}
        )
    assert res.status_code == 401


def test_constant_time_equal_handles_non_ascii_without_raising():
    assert constant_time_equal("پسورد", "پسورد") is True
    assert constant_time_equal("پسورد", "پسورک") is False
    assert constant_time_equal("abc", "abd") is False


def test_session_key_is_not_derived_from_llm_key_or_admin_password(monkeypatch):
    base = dict(secret_key="s" * 40, auth_secret=None)
    a = SimpleNamespace(**base, admin_password="one", llm_api_key="llm-A")
    b = SimpleNamespace(**base, admin_password="two", llm_api_key="llm-B")
    monkeypatch.setattr(signing, "get_settings", lambda: a)
    key_a = signing.derive_session_key("iran-tutor-admin-v3")
    monkeypatch.setattr(signing, "get_settings", lambda: b)
    key_b = signing.derive_session_key("iran-tutor-admin-v3")
    assert key_a == key_b


def test_auth_secret_takes_precedence_over_secret_key(monkeypatch):
    with_auth = SimpleNamespace(auth_secret="auth-x" * 8, secret_key="secret-y" * 6)
    only_secret = SimpleNamespace(auth_secret=None, secret_key="secret-y" * 6)
    monkeypatch.setattr(signing, "get_settings", lambda: with_auth)
    k1 = signing.derive_session_key("p")
    monkeypatch.setattr(signing, "get_settings", lambda: only_secret)
    k2 = signing.derive_session_key("p")
    assert k1 != k2


def test_client_ip_ignores_forwarded_header_by_default():
    req = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.5"),
        headers={"x-forwarded-for": "1.2.3.4"},
    )
    assert client_ip(req) == "10.0.0.5"


def test_client_ip_uses_trusted_hop_when_configured(monkeypatch):
    monkeypatch.setattr(
        "app.core.client_ip.get_settings", lambda: SimpleNamespace(trusted_proxy_hops=1)
    )
    req = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.5"),
        headers={"x-forwarded-for": "9.9.9.9"},
    )
    assert client_ip(req) == "9.9.9.9"


def test_production_refuses_demo_mode():
    settings = SimpleNamespace(
        app_env="production",
        admin_password="a-very-long-admin-password-123",
        secret_key="k" * 40,
        demo_mode=True,
    )
    problems = production_violations(settings)
    assert any("DEMO_MODE" in problem for problem in problems)


@pytest.mark.asyncio
async def test_admin_login_is_rate_limited_per_ip(monkeypatch):
    async def deny(**_kwargs):
        return RateLimitDecision(False, 10, 0, 42)

    monkeypatch.setattr(admin_api, "check_rate_limit", deny)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/admin/auth/login", json={"username": "admin", "password": "x"})
    assert res.status_code == 429
    assert res.headers.get("retry-after") == "42"


@pytest.mark.asyncio
async def test_otp_request_is_rate_limited_per_ip(monkeypatch):
    from app.api import auth as auth_api

    async def deny(**_kwargs):
        return RateLimitDecision(False, 20, 0, 7)

    monkeypatch.setattr(auth_api, "check_rate_limit", deny)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/auth/request-otp", json={"phone_number": "09121234567"})
    assert res.status_code == 429


def _fake_request(headers=None, cookies=None):
    return SimpleNamespace(headers=headers or {}, cookies=cookies or {}, client=SimpleNamespace(host="127.0.0.1"))


def test_admin_header_with_non_ascii_password_is_rejected_not_raised():
    req = _fake_request(headers={"x-admin-username": "admin", "x-admin-password": "پسورد"})
    assert admin_api._is_admin_authenticated(req) is False


def test_tampered_admin_cookie_with_superscript_digits_is_rejected_not_raised():
    req = _fake_request(cookies={admin_api.ADMIN_COOKIE_NAME: "²².x.y"})
    assert admin_api._is_admin_authenticated(req) is False
    assert admin_api.verify_admin_session_token("²².x.²") is False


@pytest.mark.asyncio
async def test_api_responses_carry_security_headers():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/admin/auth/session")
    assert res.status_code == 200
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert "microphone=(self)" in res.headers.get("permissions-policy", "")
