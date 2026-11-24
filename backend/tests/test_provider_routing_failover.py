from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import dependencies
from app.core import llm_client
from app.services import ai_gateway
from app.services.ai_provider_service import ResolvedRoute


def _route(provider_id: int, base_url: str, api_key: str, source: str) -> ResolvedRoute:
    return ResolvedRoute(
        feature_key="chat",
        provider_id=provider_id,
        provider_name=f"provider-{provider_id}",
        provider_type="openai_compatible",
        base_url=base_url,
        model_name=f"model-{provider_id}",
        temperature=0.25,
        max_tokens=512,
        api_key=api_key,
        source=source,
    )


class ProviderUnavailable(Exception):
    status_code = 503


@pytest.mark.asyncio
async def test_gateway_uses_provider_url_and_key_and_fails_over(monkeypatch):
    primary = _route(1, "https://primary.example/v1", "primary-secret", "route")
    fallback = _route(2, "https://fallback.example/v1", "fallback-secret", "fallback")
    calls: list[tuple[str, dict[str, object]]] = []

    async def candidates(_feature_key, _session):
        return [primary, fallback]

    async def fake_complete(model, _messages, **kwargs):
        calls.append((model, kwargs))
        if kwargs["base_url"] == primary.base_url:
            raise ProviderUnavailable("primary is unavailable")
        return "پاسخ از ارائه‌دهندهٔ جایگزین"

    audit_calls: list[dict[str, object]] = []

    async def fake_audit(**kwargs):
        audit_calls.append(kwargs)
        return "audit-id"

    monkeypatch.setattr(ai_gateway, "_resolve_candidates", candidates)
    monkeypatch.setattr(ai_gateway, "complete_text", fake_complete)
    monkeypatch.setattr(ai_gateway, "_write_audit", fake_audit)

    result = await ai_gateway.complete_text_via_gateway(
        ctx=ai_gateway.CallContext(feature_key="chat", user_id="student-1"),
        messages=[{"role": "user", "content": "سلام"}],
        model="legacy-model",
        session=object(),
    )

    assert result.content == "پاسخ از ارائه‌دهندهٔ جایگزین"
    assert result.provider_id == fallback.provider_id
    assert [call[1]["base_url"] for call in calls] == [
        primary.base_url,
        fallback.base_url,
    ]
    assert [call[1]["api_key"] for call in calls] == [
        primary.api_key,
        fallback.api_key,
    ]
    assert calls[1][1]["max_tokens"] == fallback.max_tokens
    assert result.model_name == fallback.model_name
    assert audit_calls[0]["record_quota"] is False  # failed primary is audited, not double-counted



@pytest.mark.asyncio
async def test_streaming_never_splices_fallback_after_visible_output(monkeypatch):
    primary = _route(1, "https://primary.example/v1", "primary-secret", "route")
    fallback = _route(2, "https://fallback.example/v1", "fallback-secret", "fallback")
    calls: list[str] = []

    async def candidates(_feature_key, _session):
        return [primary, fallback]

    async def fake_stream(_model, _messages, on_chunk, **kwargs):
        calls.append(kwargs["base_url"])
        await on_chunk("بخش اول پاسخ")
        raise ProviderUnavailable("stream failed after visible output")

    async def fake_audit(**_kwargs):
        return "audit-id"

    monkeypatch.setattr(ai_gateway, "_resolve_candidates", candidates)
    monkeypatch.setattr(ai_gateway, "stream_text", fake_stream)
    monkeypatch.setattr(ai_gateway, "_write_audit", fake_audit)

    emitted: list[str] = []

    async def collect(chunk: str) -> None:
        emitted.append(chunk)

    with pytest.raises(ProviderUnavailable):
        await ai_gateway.stream_text_via_gateway(
            ctx=ai_gateway.CallContext(feature_key="chat"),
            messages=[{"role": "user", "content": "سلام"}],
            on_chunk=collect,
            model="legacy-model",
            session=object(),
        )

    assert emitted == ["بخش اول پاسخ"]
    assert calls == [primary.base_url]


@pytest.mark.asyncio
async def test_provider_route_lookup_failure_fails_closed(monkeypatch):
    async def broken_lookup(_session, _feature_key):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(ai_gateway, "resolve_feature_route_candidates", broken_lookup)
    with pytest.raises(RuntimeError, match="routing is temporarily unavailable"):
        await ai_gateway._resolve_candidates("chat", object())


@pytest.mark.asyncio
async def test_configured_route_without_usable_provider_does_not_use_env(monkeypatch):
    async def no_usable_provider(_session, _feature_key):
        return []

    monkeypatch.setattr(ai_gateway, "resolve_feature_route_candidates", no_usable_provider)
    with pytest.raises(RuntimeError, match="no active, usable provider"):
        await ai_gateway._resolve_candidates("chat", object())


def test_routed_client_never_inherits_legacy_environment_key(monkeypatch):
    created: list[dict[str, object]] = []

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(kwargs)

    monkeypatch.setattr(llm_client, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(
        llm_client,
        "get_settings",
        lambda: SimpleNamespace(llm_timeout=7),
    )
    llm_client._route_clients.clear()

    first = llm_client._get_route_client("https://local.example/v1", None)
    again = llm_client._get_route_client("https://local.example/v1/", None)
    authenticated = llm_client._get_route_client("https://local.example/v1", "provider-secret")

    assert first is again
    assert first is not authenticated
    assert created[0]["api_key"] == "no-auth"
    assert created[0]["base_url"] == "https://local.example/v1"
    assert created[1]["api_key"] == "provider-secret"


def test_missing_student_grade_fails_closed_in_production(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(demo_mode=False),
    )
    with pytest.raises(HTTPException) as blocked:
        dependencies.enforce_student_grade_level(SimpleNamespace(grade_level=None), 12)
    assert getattr(blocked.value, "status_code", None) == 409


def test_demo_student_may_use_demo_grade_selection(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(demo_mode=True),
    )
    dependencies.enforce_student_grade_level(SimpleNamespace(grade_level=None), 12)


@pytest.mark.asyncio
async def test_provider_route_resolves_ordered_multi_fallback_chain(monkeypatch):
    from app.services import ai_provider_service

    route = SimpleNamespace(
        provider_id=1,
        model_name="main-model",
        temperature=0.3,
        max_tokens=700,
        fallback_chain_json=[
            {"provider_id": 2, "model_name": "backup-two"},
            {"provider_id": 3, "model_name": None},
            {"provider_id": 2, "model_name": "duplicate"},
        ],
        fallback_provider_id=3,
        fallback_model_name="legacy-backup-three",
    )
    providers = {
        1: SimpleNamespace(id=1, name="primary", provider_type="openai_compatible",
                           base_url="https://primary.example/v1", encrypted_api_key="p",
                           is_active=True, capabilities=["chat"]),
        2: SimpleNamespace(id=2, name="backup-2", provider_type="openai_compatible",
                           base_url="https://backup2.example/v1", encrypted_api_key="b2",
                           is_active=True, capabilities=["chat"]),
        3: SimpleNamespace(id=3, name="backup-3", provider_type="openai_compatible",
                           base_url="https://backup3.example/v1", encrypted_api_key="b3",
                           is_active=True, capabilities=["chat"]),
    }

    class FakeSession:
        async def get(self, model, provider_id):
            return providers.get(provider_id)

    async def active_route(_session, _feature):
        return route

    monkeypatch.setattr(ai_provider_service, "get_active_route", active_route)
    monkeypatch.setattr(ai_provider_service, "decrypt_secret", lambda secret: f"key:{secret}")

    resolved = await ai_provider_service.resolve_feature_route_candidates(
        FakeSession(), "chat"
    )

    assert [(item.provider_id, item.model_name) for item in resolved] == [
        (1, "main-model"),
        (2, "backup-two"),
        (3, "main-model"),
    ]
    assert [item.api_key for item in resolved] == ["key:p", "key:b2", "key:b3"]


@pytest.mark.asyncio
async def test_embedding_query_route_requires_embedding_capability(monkeypatch):
    from app.services import ai_provider_service

    route = SimpleNamespace(
        provider_id=1,
        model_name="embedding-model",
        temperature=0,
        max_tokens=256,
        fallback_chain_json=[],
        fallback_provider_id=None,
        fallback_model_name=None,
    )
    providers = {
        1: SimpleNamespace(id=1, name="wrong-capability", provider_type="openai_compatible",
                           base_url="https://wrong.example/v1", encrypted_api_key="wrong",
                           is_active=True, capabilities=["chat"]),
    }

    class FakeSession:
        async def get(self, model, provider_id):
            return providers.get(provider_id)

    async def active_route(_session, feature):
        assert feature == "embedding_query"
        return route

    monkeypatch.setattr(ai_provider_service, "get_active_route", active_route)
    resolved = await ai_provider_service.resolve_feature_route_candidates(
        FakeSession(), "embedding_query"
    )
    assert resolved == []


@pytest.mark.asyncio
async def test_gateway_without_request_session_still_resolves_admin_route(monkeypatch):
    route = _route(7, "https://routed.example/v1", "routed-secret", "route")
    sentinel_session = object()
    opened: list[object] = []

    class FakeSessionContext:
        async def __aenter__(self):
            opened.append(sentinel_session)
            return sentinel_session

        async def __aexit__(self, *_args):
            return None

    async def resolve(session, feature_key):
        assert session is sentinel_session
        assert feature_key == "chat"
        return [route]

    monkeypatch.setattr(ai_gateway, "async_session_factory", lambda: FakeSessionContext())
    monkeypatch.setattr(ai_gateway, "resolve_feature_route_candidates", resolve)

    resolved = await ai_gateway._resolve_candidates("chat", None)

    assert resolved == [route]
    assert opened == [sentinel_session]


def test_fallback_eligibility_includes_httpx_transport_errors():
    import httpx

    assert ai_gateway._fallback_eligible(httpx.ConnectTimeout("provider timed out"))
    assert ai_gateway._fallback_eligible(httpx.ReadError("provider connection was interrupted"))
    assert ai_gateway._fallback_eligible(ProviderUnavailable("upstream unavailable"))
    assert not ai_gateway._fallback_eligible(ValueError("invalid application state"))
