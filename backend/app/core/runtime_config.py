"""DB-backed runtime configuration overlay for AI APIs, models, vector search, SMS & payment gateways."""

from __future__ import annotations

import logging
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

RUNTIME_PUBLIC_FIELDS: tuple[str, ...] = (
    "demo_mode",
    "llm_base_url",
    "llm_timeout",
    "max_concurrency",
    "vision_model_a",
    "vision_model_b",
    "vision_model_primary",
    "vision_model_escalation",
    "tutor_model",
    "speech_to_text_model",
    "audio_base_url",
    "escalate_figures",
    "vector_backend",
    "qdrant_url",
    "qdrant_collection",
    "embedding_base_url",
    "embedding_model",
    "embedding_dimension",
    "sms_provider",
    "sms_sender",
    "sms_template",
    "sms_webhook_url",
    "otp_ttl_seconds",
    "otp_resend_seconds",
    "otp_max_attempts",
    "user_session_ttl_seconds",
    "admin_session_ttl_seconds",
    "payment_provider",
    "zarinpal_sandbox",
    "public_app_url",
)

RUNTIME_SECRET_FIELDS: tuple[str, ...] = (
    "llm_api_key",
    "audio_api_key",
    "embedding_api_key",
    "sms_api_key",
    "zarinpal_merchant_id",
)

ALL_RUNTIME_FIELDS: frozenset[str] = frozenset(RUNTIME_PUBLIC_FIELDS) | frozenset(RUNTIME_SECRET_FIELDS)

RESET_SECTION_FIELDS: dict[str, frozenset[str]] = {
    "all": ALL_RUNTIME_FIELDS,
    "ai": frozenset(
        {
            "demo_mode",
            "llm_base_url",
            "llm_api_key",
            "llm_timeout",
            "max_concurrency",
            "vision_model_a",
            "vision_model_b",
            "vision_model_primary",
            "vision_model_escalation",
            "tutor_model",
            "speech_to_text_model",
            "audio_base_url",
            "audio_api_key",
            "escalate_figures",
            "embedding_base_url",
            "embedding_api_key",
            "embedding_model",
            "embedding_dimension",
        }
    ),
    "vector": frozenset(
        {
            "vector_backend",
            "qdrant_url",
            "qdrant_collection",
            "embedding_base_url",
            "embedding_api_key",
            "embedding_model",
            "embedding_dimension",
        }
    ),
    "sms": frozenset(
        {
            "sms_provider",
            "sms_api_key",
            "sms_sender",
            "sms_template",
            "sms_webhook_url",
            "otp_ttl_seconds",
            "otp_resend_seconds",
            "otp_max_attempts",
            "user_session_ttl_seconds",
            "admin_session_ttl_seconds",
        }
    ),
    "payment": frozenset(
        {
            "payment_provider",
            "zarinpal_merchant_id",
            "zarinpal_sandbox",
            "public_app_url",
        }
    ),
}

PROVIDER_PRESETS: list[dict[str, object]] = [
    {
        "id": "openai",
        "label": "OpenAI (رسمی)",
        "llm_base_url": "https://api.openai.com/v1",
        "suggested_tutor_model": "gpt-4o",
        "suggested_vision_model": "gpt-4o",
        "suggested_stt_model": "whisper-1",
        "suggested_embedding_model": "text-embedding-3-small",
    },
    {
        "id": "openrouter",
        "label": "OpenRouter (چندمدلی)",
        "llm_base_url": "https://openrouter.ai/api/v1",
        "suggested_tutor_model": "openai/gpt-4o-mini",
        "suggested_vision_model": "google/gemini-2.5-flash",
        "suggested_stt_model": "openai/whisper-1",
        "suggested_embedding_model": "openai/text-embedding-3-small",
    },
    {
        "id": "groq",
        "label": "Groq (سرعت بالا)",
        "llm_base_url": "https://api.groq.com/openai/v1",
        "suggested_tutor_model": "llama-3.3-70b-versatile",
        "suggested_vision_model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "suggested_stt_model": "whisper-large-v3",
        "suggested_embedding_model": "text-embedding-3-small",
    },
    {
        "id": "together",
        "label": "Together AI",
        "llm_base_url": "https://api.together.xyz/v1",
        "suggested_tutor_model": "Qwen/Qwen2.5-72B-Instruct-Turbo",
        "suggested_vision_model": "Qwen/Qwen2.5-VL-72B-Instruct",
        "suggested_stt_model": "whisper-1",
        "suggested_embedding_model": "BAAI/bge-base-en-v1.5",
    },
    {
        "id": "ollama",
        "label": "Ollama (لوکال / سرور اختصاصی)",
        "llm_base_url": "http://127.0.0.1:11434/v1",
        "suggested_tutor_model": "qwen2.5:14b",
        "suggested_vision_model": "qwen2.5vl:7b",
        "suggested_stt_model": "whisper-1",
        "suggested_embedding_model": "nomic-embed-text",
    },
]

_NON_EMPTY_STRINGS = frozenset(
    {
        "llm_base_url",
        "vision_model_a",
        "vision_model_b",
        "vision_model_primary",
        "qdrant_url",
        "qdrant_collection",
        "embedding_model",
    }
)

_URL_FIELDS = frozenset(
    {
        "llm_base_url",
        "audio_base_url",
        "embedding_base_url",
        "qdrant_url",
        "sms_webhook_url",
        "public_app_url",
    }
)


class RuntimeSettingsPatchSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    demo_mode: bool | None = None
    llm_base_url: str | None = Field(default=None, max_length=512)
    llm_api_key: str | None = Field(default=None, max_length=512)
    llm_timeout: float | None = Field(default=None, ge=1, le=600)
    max_concurrency: int | None = Field(default=None, ge=1, le=64)

    vision_model_a: str | None = Field(default=None, max_length=255)
    vision_model_b: str | None = Field(default=None, max_length=255)
    vision_model_primary: str | None = Field(default=None, max_length=255)
    vision_model_escalation: str | None = Field(default=None, max_length=255)
    tutor_model: str | None = Field(default=None, max_length=255)
    speech_to_text_model: str | None = Field(default=None, max_length=255)
    audio_base_url: str | None = Field(default=None, max_length=512)
    audio_api_key: str | None = Field(default=None, max_length=512)
    escalate_figures: bool | None = None

    vector_backend: Literal["qdrant", "pgvector"] | None = None
    qdrant_url: str | None = Field(default=None, max_length=512)
    qdrant_collection: str | None = Field(default=None, max_length=128)
    embedding_base_url: str | None = Field(default=None, max_length=512)
    embedding_api_key: str | None = Field(default=None, max_length=512)
    embedding_model: str | None = Field(default=None, max_length=255)
    embedding_dimension: int | None = Field(default=None, ge=1, le=16384)

    sms_provider: Literal["demo", "kavenegar", "sms_ir", "webhook"] | None = None
    sms_api_key: str | None = Field(default=None, max_length=512)
    sms_sender: str | None = Field(default=None, max_length=128)
    sms_template: str | None = Field(default=None, max_length=128)
    sms_webhook_url: str | None = Field(default=None, max_length=512)

    otp_ttl_seconds: int | None = Field(default=None, ge=30, le=3600)
    otp_resend_seconds: int | None = Field(default=None, ge=0, le=600)
    otp_max_attempts: int | None = Field(default=None, ge=1, le=20)
    user_session_ttl_seconds: int | None = Field(default=None, ge=300, le=31_536_000)
    admin_session_ttl_seconds: int | None = Field(default=None, ge=300, le=2_592_000)

    payment_provider: Literal["demo", "zarinpal"] | None = None
    zarinpal_merchant_id: str | None = Field(default=None, max_length=128)
    zarinpal_sandbox: bool | None = None
    public_app_url: str | None = Field(default=None, max_length=512)


_runtime_overrides: dict[str, Any] = {}


def get_runtime_overrides() -> dict[str, Any]:
    return _runtime_overrides


def clear_runtime_overrides() -> None:
    _runtime_overrides.clear()


def _validate_http_url(url: str, field_name: str) -> str:
    cleaned = url.strip()
    if any(ch in cleaned for ch in ("\r", "\n", "\x00")):
        raise ValueError(f"مقدار {field_name} نامعتبر است.")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"نشانی {field_name} باید با http:// یا https:// شروع شود.")
    return cleaned.rstrip("/") if field_name in {"llm_base_url", "audio_base_url", "embedding_base_url", "qdrant_url", "public_app_url"} else cleaned


def _clean_secret(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if any(ch in cleaned for ch in ("\r", "\n", "\x00")):
        raise ValueError(f"مقدار {field_name} شامل کاراکترهای غیرمجاز است.")
    return cleaned


def normalize_persisted_overrides(raw: Any) -> dict[str, Any]:
    """Safely validate raw JSON dict stored in DB into clean runtime overrides."""
    if not isinstance(raw, dict):
        return {}
    filtered = {k: v for k, v in raw.items() if k in ALL_RUNTIME_FIELDS}
    try:
        parsed = RuntimeSettingsPatchSchema.model_validate(filtered)
    except ValidationError:
        return {}
    out: dict[str, Any] = {}
    for key in filtered:
        val = getattr(parsed, key)
        if key in RUNTIME_SECRET_FIELDS:
            if isinstance(val, str) and val.strip():
                try:
                    out[key] = _clean_secret(val, key)
                except ValueError:
                    continue
            continue
        if val is None:
            if key not in _NON_EMPTY_STRINGS and key in filtered and raw.get(key) is None:
                out[key] = None
            continue
        if isinstance(val, str):
            val = val.strip()
            if key in _NON_EMPTY_STRINGS and not val:
                continue
            if not val:
                out[key] = None
                continue
            if key in _URL_FIELDS:
                try:
                    val = _validate_http_url(val, key)
                except ValueError:
                    continue
        out[key] = val
    return out


def set_runtime_overrides(raw: Any) -> dict[str, Any]:
    cleaned = normalize_persisted_overrides(raw)
    _runtime_overrides.clear()
    _runtime_overrides.update(cleaned)
    return dict(_runtime_overrides)


def apply_runtime_patch(
    existing_raw: Any,
    patch_raw: dict[str, Any],
    *,
    clear_secrets: list[str] | None = None,
    clear_overrides: list[str] | None = None,
) -> dict[str, Any]:
    """Merge an admin settings update into persisted runtime overrides with strict validation."""
    try:
        validated = RuntimeSettingsPatchSchema.model_validate(patch_raw)
    except ValidationError as exc:
        raise ValueError(f"تنظیمات ارسالی معتبر نیست: {exc.errors()[0]['msg']}") from exc

    merged = normalize_persisted_overrides(existing_raw)

    for key in validated.model_fields_set:
        val = getattr(validated, key)
        if key in RUNTIME_SECRET_FIELDS:
            # Blank or omitted secret leaves existing value intact; use clear_secrets to wipe.
            if isinstance(val, str) and val.strip():
                merged[key] = _clean_secret(val, key)
            continue

        if val is None:
            if key in _NON_EMPTY_STRINGS or isinstance(val, bool) or key in {
                "demo_mode",
                "escalate_figures",
                "zarinpal_sandbox",
                "llm_timeout",
                "max_concurrency",
                "vector_backend",
                "embedding_dimension",
                "sms_provider",
                "otp_ttl_seconds",
                "otp_resend_seconds",
                "otp_max_attempts",
                "user_session_ttl_seconds",
                "admin_session_ttl_seconds",
                "payment_provider",
            }:
                raise ValueError(f"فیلد {key} نمی‌تواند خالی باشد.")
            merged[key] = None
            continue

        if isinstance(val, str):
            cleaned = val.strip()
            if any(ch in cleaned for ch in ("\r", "\n", "\x00")):
                raise ValueError(f"مقدار {key} شامل کاراکتر غیرمجاز است.")
            if not cleaned:
                if key in _NON_EMPTY_STRINGS:
                    raise ValueError(f"مقدار {key} نمی‌تواند خالی باشد.")
                merged[key] = None
                continue
            if key in _URL_FIELDS:
                cleaned = _validate_http_url(cleaned, key)
            merged[key] = cleaned
            continue

        merged[key] = val

    for secret_key in clear_secrets or ():
        if secret_key in RUNTIME_SECRET_FIELDS:
            merged.pop(secret_key, None)

    for override_key in clear_overrides or ():
        if override_key in ALL_RUNTIME_FIELDS:
            merged.pop(override_key, None)

    return merged


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    stripped = value.strip()
    if not stripped:
        return ""
    if len(stripped) <= 6:
        return "•" * len(stripped)
    if len(stripped) <= 12:
        return f"{stripped[:2]}••••{stripped[-2:]}"
    return f"{stripped[:4]}••••{stripped[-4:]}"


def serialize_admin_settings(base: Any, effective: Any, overrides: dict[str, Any]) -> dict[str, Any]:
    """Serialize effective settings without ever exposing plaintext secret keys."""
    config_payload = {field: getattr(effective, field, None) for field in RUNTIME_PUBLIC_FIELDS}
    env_defaults = {field: getattr(base, field, None) for field in RUNTIME_PUBLIC_FIELDS}

    secrets_payload: dict[str, dict[str, object]] = {}
    for secret_field in RUNTIME_SECRET_FIELDS:
        eff_val = getattr(effective, secret_field, None)
        base_val = getattr(base, secret_field, None)
        if secret_field in overrides and overrides[secret_field]:
            source = "admin"
        elif base_val:
            source = "env"
        else:
            source = "unset"
        secrets_payload[secret_field] = {
            "configured": bool(eff_val and str(eff_val).strip()),
            "masked": mask_secret(eff_val),
            "source": source,
        }

    return {
        "config": config_payload,
        "secrets": secrets_payload,
        "env_defaults": env_defaults,
        "overridden_keys": sorted(overrides.keys()),
        "auth_info": {
            "admin_username": getattr(base, "admin_username", "admin"),
            "has_custom_auth_secret": bool(getattr(base, "auth_secret", None)),
        },
        "provider_presets": PROVIDER_PRESETS,
    }


async def load_runtime_overrides_from_db() -> None:
    """Hydrate process runtime overrides from BillingSettings.system_config at startup."""
    from app.db.session import async_session_factory
    from app.models.auth import BillingSettings

    try:
        async with async_session_factory() as session:
            billing = await session.get(BillingSettings, 1)
            if billing is not None and isinstance(getattr(billing, "system_config", None), dict):
                loaded = set_runtime_overrides(billing.system_config)
                if loaded:
                    logger.info("Loaded %d runtime system overrides from database", len(loaded))
    except Exception:  # noqa: BLE001
        logger.exception("Failed loading runtime system overrides from database")


async def refresh_runtime_clients() -> None:
    """Drop cached OpenAI & Qdrant client pools so saved runtime overrides take effect immediately."""
    from app.core.llm_client import close_llm_clients
    from app.services.retrieval_service import close_qdrant

    await close_llm_clients()
    await close_qdrant()
