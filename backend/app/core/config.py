"""Application settings, loaded only from environment / `backend/.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.runtime_config import get_runtime_overrides

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Typed settings. Provider URL, key and model names have no defaults on purpose."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Deployment environment. `production` turns weak secrets into a startup error
    # (see app.core.production_guard). Reads APP_ENV, falling back to ENVIRONMENT.
    app_env: str = Field(default="local", validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT"))

    demo_mode: bool = False
    llm_base_url: str = Field(min_length=1)
    llm_api_key: str = Field(min_length=1)

    # Compare-mode only (test_ingest.py): A/B
    vision_model_a: str = Field(min_length=1)
    vision_model_b: str = Field(min_length=1)

    # Production ingestion: primary + optional escalation
    vision_model_primary: str = Field(min_length=1)
    vision_model_escalation: str | None = None
    tutor_model: str | None = None
    speech_to_text_model: str | None = None
    speech_synthesis_model: str | None = None
    speech_default_voice: str | None = None
    audio_base_url: str | None = None
    audio_api_key: str | None = None
    escalate_figures: bool = False

    llm_timeout: float = Field(default=120, gt=0)
    max_concurrency: int = Field(default=3, ge=1)

    database_url: str = Field(min_length=1)

    # Admin authentication. There is deliberately NO usable default password:
    # ADMIN_PASSWORD must be set explicitly in the environment / backend/.env
    # (the test suite forces it via tests/conftest.py). An empty value disables
    # the legacy shared-password admin login entirely (`_is_admin_authenticated`
    # returns False) and production_guard refuses to start in production with it.
    # Note: the provider-vault fallback key in app.core.crypto is derived from
    # the admin credentials when SECRET_KEY is unset, so changing a previously
    # set admin password also rotates that fallback key (production requires
    # SECRET_KEY, so this only affects local/demo databases).
    admin_username: str = Field(default="admin", min_length=1)
    admin_password: str = ""
    admin_session_ttl_seconds: int = Field(default=43200, gt=0)

    # Phase 1: master key material for the encrypted AI-provider vault (Fernet).
    # Never returned by any API. Falls back to a derived value in non-production.
    secret_key: str | None = None

    # Phase 1: quota / rate-limit engine. Redis is optional; without it the limiter
    # degrades to an in-process sliding window (single-worker only).
    redis_url: str | None = None
    rate_limit_enabled: bool = True

    # Phase 6: Student SMS OTP authentication, plans, and payment providers
    auth_secret: str | None = None
    # Number of reverse proxies in front of the API (0 = ignore X-Forwarded-For).
    trusted_proxy_hops: int = Field(default=0, ge=0, le=10)
    user_session_ttl_seconds: int = Field(default=2592000, gt=0)
    # Production textbook access fails closed until an administrator assigns
    # the learner's current grade. Demo environments can still use unprofiled users.
    require_student_grade_profile: bool = True
    otp_ttl_seconds: int = Field(default=180, gt=0)
    otp_resend_seconds: int = Field(default=60, ge=0)
    otp_max_attempts: int = Field(default=5, ge=1)

    # Phone + password authentication (hotfix 2026-11-22).
    # Minimum password length for user-set passwords. The dev seed may opt in to a weaker
    # value through DEV_SEED_PASSWORD, which is refused in production by the guard.
    password_min_length: int = Field(default=8, ge=4, le=64)
    # Rate limits for password login and OTP flows (per IP and per normalized phone).
    login_ip_limit: int = Field(default=20, ge=1)
    login_ip_window_seconds: int = Field(default=900, gt=0)
    login_phone_limit: int = Field(default=8, ge=1)
    login_phone_window_seconds: int = Field(default=900, gt=0)
    otp_phone_limit: int = Field(default=5, ge=1)
    otp_phone_window_seconds: int = Field(default=3600, gt=0)
    # Short-lived handshake token issued after OTP verification for registration/recovery.
    auth_handshake_ttl_seconds: int = Field(default=900, gt=0)
    # Lifetime of the "re-authenticate before a sensitive admin action" grant.
    reauth_ttl_seconds: int = Field(default=300, gt=0)

    # Persistent development test account (Phase 4). Never enabled in production.
    dev_seed_enabled: bool = False
    dev_seed_apply_env: Literal["local", "development", "dev", "test", ""] = "local"
    dev_seed_name: str = "mahdi"
    dev_seed_phone: str = "09134303348"
    dev_seed_password: str = ""
    dev_seed_role: str = "user"
    # Only for the documented local test account (password "123"); never in production.
    dev_seed_allow_weak_password: bool = False

    # CSRF enforcement for cookie-authenticated mutations: "on" (origin check),
    # "strict" (origin check + double-submit token), or "off" (unsafe; tooling only).
    csrf_enforcement: Literal["on", "strict", "off"] = "on"

    sms_provider: Literal["demo", "kavenegar", "sms_ir", "webhook"] = "demo"
    sms_api_key: str | None = None
    sms_sender: str | None = None
    sms_template: str | None = None
    sms_webhook_url: str | None = None
    payment_provider: Literal["demo", "zarinpal"] = "demo"
    zarinpal_merchant_id: str | None = None
    zarinpal_sandbox: bool = False
    public_app_url: str | None = None

    # Phase 2: textbook vector search. Use "pgvector" for Supabase PostgreSQL,
    # or "qdrant" for a Qdrant server.
    vector_backend: Literal["qdrant", "pgvector"] = "qdrant"
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "iran_textbooks"
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = Field(default=1536, gt=0)


@lru_cache
def _get_base_settings() -> Settings:
    """Return cached settings loaded purely from environment / .env."""
    return Settings()  # type: ignore[call-arg]


def get_base_settings() -> Settings:
    """Return un-overridden base settings from environment / .env."""
    return _get_base_settings()


def get_settings() -> Settings:
    """Return effective settings (base .env settings overlaid with admin runtime overrides)."""
    base = _get_base_settings()
    overrides = get_runtime_overrides()
    if not overrides:
        return base
    valid_updates = {k: v for k, v in overrides.items() if k in Settings.model_fields}
    return base.model_copy(update=valid_updates) if valid_updates else base


get_settings.cache_clear = _get_base_settings.cache_clear  # type: ignore[attr-defined]
