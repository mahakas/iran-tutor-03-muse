"""Symmetric encryption for admin-managed provider secrets (Phase 1 key vault).

API keys are stored encrypted at rest and are **never** returned in plaintext by
any API response. The key material is derived from `SECRET_KEY` (see
`app.core.config.Settings.secret_key`); when that is absent a deterministic
fallback is derived from the admin credentials so local/demo databases keep
working across restarts.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_PREFIX = "enc:v1:"


def _key_material() -> bytes:
    """Return 32 bytes of key material derived from the configured secret."""
    settings = get_settings()
    secret = getattr(settings, "secret_key", None)
    if not secret:
        # Deterministic fallback: does not change between restarts, so previously
        # encrypted values stay readable. Operators must set SECRET_KEY in production.
        secret = (
            f"{getattr(settings, 'admin_username', 'admin')}:"
            f"{getattr(settings, 'admin_password', '')}:"
            f"{getattr(settings, 'llm_api_key', '')}"
        )
    return hashlib.sha256(f"iran-tutor-ai-vault-v1:{secret}".encode("utf-8")).digest()


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_key_material()))


def encrypt_secret(plaintext: str | None) -> str | None:
    """Encrypt a secret for storage. Blank input stays `None`."""
    if plaintext is None:
        return None
    cleaned = plaintext.strip()
    if not cleaned:
        return None
    token = _fernet().encrypt(cleaned.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_secret(stored: str | None) -> str | None:
    """Decrypt a stored secret, tolerating legacy plaintext rows."""
    if not stored:
        return None
    if not stored.startswith(_PREFIX):
        # Legacy / hand-inserted row: treat as plaintext so nothing breaks.
        return stored
    try:
        return _fernet().decrypt(stored[len(_PREFIX) :].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.warning("ai_vault.decrypt_failed: SECRET_KEY may have changed; key needs re-entry")
        return None


def is_encrypted(stored: str | None) -> bool:
    return bool(stored and stored.startswith(_PREFIX))


def mask_api_key(value: str | None) -> str:
    """Mask a provider key for display, e.g. `sk-...a1b2`."""
    if not value:
        return ""
    stripped = value.strip()
    if len(stripped) <= 8:
        return "•" * len(stripped)
    return f"{stripped[:3]}...{stripped[-4:]}"
