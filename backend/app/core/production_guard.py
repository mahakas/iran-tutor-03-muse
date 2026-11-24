"""Startup guard for production deployments.

In `APP_ENV=production` (or `ENVIRONMENT=production`) the app refuses to start when
secrets still have their development values:

* `ADMIN_PASSWORD` is a known-weak value, shorter than 12 characters, or a placeholder.
* `SECRET_KEY` is missing, shorter than 32 characters, or a placeholder.
* `DEMO_MODE` is enabled. Demo mode returns the SMS OTP code in API responses.
* `DEV_SEED_ENABLED` / `DEV_SEED_ALLOW_WEAK_PASSWORD` are enabled. Those create and keep
  the documented weak development test account.

Outside production nothing is blocked; the admin password still logs a warning.
"""

from __future__ import annotations

from typing import Any

PRODUCTION_ENVS = frozenset({"production", "prod"})
WEAK_ADMIN_PASSWORDS = frozenset(
    {
        "",
        "123",
        "1234",
        "12345",
        "123456",
        "12345678",
        "123456789",
        "111111",
        "123123",
        "admin",
        "admin123",
        "password",
        "password1",
        "qwerty",
        "letmein",
        "change_me",
        "changeme",
    }
)
MIN_ADMIN_PASSWORD_LEN = 12
MIN_SECRET_KEY_LEN = 32
PLACEHOLDER_PREFIXES = ("change_me", "replace_with")


def is_production(settings: Any) -> bool:
    return str(getattr(settings, "app_env", "") or "").strip().lower() in PRODUCTION_ENVS


def is_weak_admin_password(value: str | None) -> bool:
    cleaned = (value or "").strip()
    lowered = cleaned.lower()
    return (
        lowered in WEAK_ADMIN_PASSWORDS
        or len(cleaned) < MIN_ADMIN_PASSWORD_LEN
        or lowered.startswith(PLACEHOLDER_PREFIXES)
    )


def is_weak_secret_key(value: str | None) -> bool:
    cleaned = (value or "").strip()
    return len(cleaned) < MIN_SECRET_KEY_LEN or cleaned.lower().startswith(PLACEHOLDER_PREFIXES)


def production_violations(settings: Any) -> list[str]:
    problems: list[str] = []
    if bool(getattr(settings, "dev_seed_enabled", False)):
        problems.append(
            "DEV_SEED_ENABLED must be false in production (it creates a known test account)"
        )
    if bool(getattr(settings, "dev_seed_allow_weak_password", False)):
        problems.append("DEV_SEED_ALLOW_WEAK_PASSWORD must be false in production")
    if bool(getattr(settings, "demo_mode", False)):
        problems.append("DEMO_MODE must be false in production (it exposes OTP codes in API responses)")
    if is_weak_admin_password(getattr(settings, "admin_password", None)):
        problems.append(
            f"ADMIN_PASSWORD is weak or default (must be at least {MIN_ADMIN_PASSWORD_LEN} characters and not a placeholder)"
        )
    if is_weak_secret_key(getattr(settings, "secret_key", None)):
        problems.append(
            f"SECRET_KEY is missing, a placeholder, or shorter than {MIN_SECRET_KEY_LEN} characters"
        )
    return problems


def enforce_production_settings(settings: Any) -> None:
    """Raise RuntimeError in production when a development secret is still in use."""
    if not is_production(settings):
        return
    problems = production_violations(settings)
    if problems:
        raise RuntimeError(
            "Refusing to start in production with insecure settings: " + "; ".join(problems)
        )
