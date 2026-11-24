"""Signing secrets for admin and user session tokens.

The session key is derived from `AUTH_SECRET` (preferred) or `SECRET_KEY` only.
It must never be derived from the LLM provider key or the admin password, so a
rotation of one of those does not silently change every session key and does
not couple provider credentials to login cookies.
"""

from __future__ import annotations

import hashlib
import logging
import secrets

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_DEV_FALLBACK_SECRET: str | None = None


def _session_root_secret() -> str:
    global _DEV_FALLBACK_SECRET
    settings = get_settings()
    secret = (getattr(settings, "auth_secret", None) or "").strip() or (
        getattr(settings, "secret_key", None) or ""
    ).strip()
    if secret:
        return secret
    # Local/demo only: production_guard refuses to start without SECRET_KEY.
    # A per-process random value keeps sessions unforgeable; they reset on restart.
    if _DEV_FALLBACK_SECRET is None:
        _DEV_FALLBACK_SECRET = secrets.token_urlsafe(48)
        logger.warning("AUTH_SECRET/SECRET_KEY not set; using a per-process session key (dev only)")
    return _DEV_FALLBACK_SECRET


def derive_session_key(purpose: str) -> bytes:
    return hashlib.sha256(f"{purpose}:{_session_root_secret()}".encode("utf-8")).digest()
