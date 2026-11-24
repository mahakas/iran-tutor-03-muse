"""Encrypted AI-provider vault and per-feature model routing (Phase 1, Rule 2).

Only admins touch these records. Secrets are encrypted with
`app.core.crypto` and are never serialized in plaintext.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret, mask_api_key
from app.models.governance import AiProvider, FeatureModelRoute

logger = logging.getLogger(__name__)

PROVIDER_TYPES: tuple[str, ...] = (
    "openai",
    "anthropic",
    "gemini",
    "openai_compatible",
    "local",
)

PROVIDER_CAPABILITIES: tuple[str, ...] = ("chat", "vision", "stt", "tts", "embedding")

# Feature keys the admin can route models for (Phase 1 scope; extended in later phases).
ROUTABLE_FEATURE_KEYS: tuple[str, ...] = (
    "chat",
    "solve",
    "quiz",
    "vision_ocr",
    "stt",
    "embedding",
    "flashcards",
    "ingest_ocr",
    "memory",
    "intent_router",
    "immersive_reader",
    "deep_solve",
    "quiz_validator",
    "learning_notebook",
    "web_visualize",
    "living_book",
    "audio_tts",
)


@dataclass(frozen=True)
class ResolvedRoute:
    """An effective provider+model binding for one feature."""

    feature_key: str
    provider_id: int | None
    provider_name: str | None
    provider_type: str | None
    base_url: str | None
    model_name: str | None
    temperature: float
    max_tokens: int | None
    api_key: str | None
    source: str  # "route" | "fallback" | "unset"

    @property
    def configured(self) -> bool:
        return bool(self.model_name and self.base_url)


def validate_provider_type(provider_type: str) -> str:
    if provider_type not in PROVIDER_TYPES:
        raise ValueError(f"provider_type must be one of {', '.join(PROVIDER_TYPES)}")
    return provider_type


def normalize_capabilities(raw: list[str] | None) -> list[str]:
    """Keep only known capability names, preserving order and dropping duplicates."""
    out: list[str] = []
    for item in raw or []:
        cleaned = str(item).strip().lower()
        if cleaned in PROVIDER_CAPABILITIES and cleaned not in out:
            out.append(cleaned)
    return out


def serialize_provider(provider: AiProvider) -> dict[str, Any]:
    """Serialize a provider for the API.

    The stored secret is decrypted only to produce the mask, and is never returned:
    `api_key` is always `None` and exists solely so the UI can tell "unchanged" apart
    from "cleared". There is deliberately no `reveal` option — no endpoint may ever
    echo a plaintext key back to a client.
    """
    return {
        "id": provider.id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "capabilities": list(provider.capabilities or []),
        "is_active": provider.is_active,
        "has_api_key": bool(provider.encrypted_api_key),
        "api_key_masked": mask_api_key(decrypt_secret(provider.encrypted_api_key)),
        "api_key": None,
        "last_test_status": provider.last_test_status,
        "last_test_latency_ms": provider.last_test_latency_ms,
        "last_test_at": provider.last_test_at.isoformat() if provider.last_test_at else None,
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


def set_provider_api_key(provider: AiProvider, raw_key: str | None) -> None:
    """Encrypt and store, or clear, a provider key. Blank input keeps the old key."""
    if raw_key is None:
        return
    if not raw_key.strip():
        return
    provider.encrypted_api_key = encrypt_secret(raw_key)


def serialize_route(route: FeatureModelRoute) -> dict[str, Any]:
    return {
        "id": route.id,
        "feature_key": route.feature_key,
        "provider_id": route.provider_id,
        "model_name": route.model_name,
        "temperature": route.temperature,
        "max_tokens": route.max_tokens,
        "fallback_provider_id": route.fallback_provider_id,
        "fallback_model_name": route.fallback_model_name,
        "fallback_chain": list(route.fallback_chain_json or []),
        "is_active": route.is_active,
    }


async def get_active_route(session: AsyncSession, feature_key: str) -> FeatureModelRoute | None:
    return await session.scalar(
        select(FeatureModelRoute)
        .where(
            FeatureModelRoute.feature_key == feature_key,
            FeatureModelRoute.is_active.is_(True),
        )
        .order_by(FeatureModelRoute.id.desc())
    )


async def resolve_feature_route_candidates(
    session: AsyncSession,
    feature_key: str,
) -> list[ResolvedRoute] | None:
    """Resolve a primary provider followed by all configured fallbacks.

    None means no DB route exists and legacy .env configuration may be used.
    An empty list means the route exists but no provider is usable; callers must
    fail closed rather than silently switch to an unrelated environment key.
    """
    route = await get_active_route(session, feature_key)
    if route is None:
        return None

    if feature_key in {"vision_ocr", "ingest_ocr", "immersive_reader_vision"}:
        required_capability = "vision"
    elif feature_key in {"stt", "audio_stt", "speech_to_text"}:
        required_capability = "stt"
    elif feature_key in {"tts", "audio_tts", "speech_synthesis", "audio_podcast_tts"}:
        required_capability = "tts"
    elif feature_key in {"embedding", "embeddings", "embedding_query"}:
        required_capability = "embedding"
    else:
        required_capability = "chat"

    fallbacks = [
        item for item in (getattr(route, "fallback_chain_json", None) or [])
        if isinstance(item, dict)
    ]
    if not fallbacks and route.fallback_provider_id is not None:
        fallbacks = [{
            "provider_id": route.fallback_provider_id,
            "model_name": route.fallback_model_name,
        }]
    ordered = [(route.provider_id, route.model_name, "route")]
    ordered.extend(
        (item.get("provider_id"), item.get("model_name") or route.model_name, "fallback")
        for item in fallbacks
    )
    if route.fallback_provider_id is not None and all(
        item[0] != route.fallback_provider_id for item in ordered
    ):
        ordered.append((
            route.fallback_provider_id,
            route.fallback_model_name or route.model_name,
            "fallback",
        ))

    candidates: list[ResolvedRoute] = []
    seen: set[int] = set()
    for provider_id, model_name, source in ordered:
        if provider_id is None or provider_id in seen or not model_name:
            continue
        seen.add(provider_id)
        provider = await session.get(AiProvider, provider_id)
        if provider is None or not provider.is_active or not (provider.base_url or "").strip():
            continue
        declared = set(provider.capabilities or [])
        if declared and required_capability not in declared:
            logger.warning(
                "ai_route.provider_capability_mismatch feature=%s provider=%s required=%s",
                feature_key,
                provider.id,
                required_capability,
            )
            continue
        candidates.append(
            ResolvedRoute(
                feature_key=feature_key,
                provider_id=provider.id,
                provider_name=provider.name,
                provider_type=provider.provider_type,
                base_url=provider.base_url,
                model_name=model_name,
                temperature=route.temperature,
                max_tokens=route.max_tokens,
                api_key=decrypt_secret(provider.encrypted_api_key),
                source=source,
            )
        )
    return candidates


async def resolve_feature_route(session: AsyncSession, feature_key: str) -> ResolvedRoute | None:
    """Resolve the effective provider+model for a feature, applying fallbacks.

    Returns `None` when no active route exists, so callers can keep using the
    legacy `.env`-based provider configuration.
    """
    route = await get_active_route(session, feature_key)
    if route is None:
        return None

    provider = await session.get(AiProvider, route.provider_id)
    if provider is not None and provider.is_active:
        return ResolvedRoute(
            feature_key=feature_key,
            provider_id=provider.id,
            provider_name=provider.name,
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            model_name=route.model_name,
            temperature=route.temperature,
            max_tokens=route.max_tokens,
            api_key=decrypt_secret(provider.encrypted_api_key),
            source="route",
        )

    if route.fallback_provider_id is not None:
        fallback = await session.get(AiProvider, route.fallback_provider_id)
        if fallback is not None and fallback.is_active:
            return ResolvedRoute(
                feature_key=feature_key,
                provider_id=fallback.id,
                provider_name=fallback.name,
                provider_type=fallback.provider_type,
                base_url=fallback.base_url,
                model_name=route.fallback_model_name or route.model_name,
                temperature=route.temperature,
                max_tokens=route.max_tokens,
                api_key=decrypt_secret(fallback.encrypted_api_key),
                source="fallback",
            )

    logger.warning("ai_route.unavailable feature=%s provider=%s", feature_key, route.provider_id)
    return ResolvedRoute(
        feature_key=feature_key,
        provider_id=route.provider_id,
        provider_name=provider.name if provider else None,
        provider_type=provider.provider_type if provider else None,
        base_url=None,
        model_name=None,
        temperature=route.temperature,
        max_tokens=route.max_tokens,
        api_key=None,
        source="unset",
    )
