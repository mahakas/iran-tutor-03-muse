"""Idempotent development-only test account seed (hotfix 2026-11-22).

The persistent dev login (`mahdi` / `09134303348`) is **never** hardcoded here: the phone,
display name, role and password all come from the environment (`.env.demo.example`
documents the conventional values). The seed:

* is skipped entirely unless `DEV_SEED_ENABLED=true`;
* refuses to run when `APP_ENV` is production;
* refuses a weak password unless `DEV_SEED_ALLOW_WEAK_PASSWORD=true` (dev/demo only);
* stores only an Argon2id digest — never the plaintext;
* is insert-only: an existing account keeps its name, password and role, and only has a
  missing password filled in so the documented dev login still works;
* never deletes or resurrects an account (`deleted_at` rows are left untouched).

Removal before a real deployment: either delete the row

    DELETE FROM users WHERE phone_number = '09134303348';

or (preferred, keeps financial history) soft-delete it from
`/admin` → کاربران → حذف, and set `DEV_SEED_ENABLED=false` so it is never recreated.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.passwords import hash_password, password_policy_error
from app.core.production_guard import is_production
from app.models.auth import User
from app.services.auth_billing_service import (
    apply_plan_to_user,
    get_or_init_billing_settings,
    normalize_iranian_phone,
)
from app.services.permissions import normalize_role

logger = logging.getLogger(__name__)

DEV_SEED_ENVS = frozenset({"local", "development", "dev", "test", ""})


def dev_seed_settings_problem(settings) -> str | None:
    """Return a reason to skip/fail the dev seed, or `None` when it may run."""
    if not bool(getattr(settings, "dev_seed_enabled", False)):
        return "disabled"
    if is_production(settings):
        return "production"
    env = str(getattr(settings, "app_env", "") or "").strip().lower()
    allowed_env = str(getattr(settings, "dev_seed_apply_env", "local") or "").strip().lower()
    if env not in DEV_SEED_ENVS or env != allowed_env:
        return f"environment:{env or 'unset'}!={allowed_env}"
    if not str(getattr(settings, "dev_seed_password", "") or "").strip():
        return "missing_password"
    return None


async def seed_development_account(session: AsyncSession, settings=None) -> dict[str, object]:
    """Create the dev test account once. Safe to call on every startup."""
    cfg = settings or get_settings()
    problem = dev_seed_settings_problem(cfg)
    if problem is not None:
        logger.info("dev_seed.skipped reason=%s", problem)
        return {"seeded": False, "reason": problem}

    try:
        phone = normalize_iranian_phone(str(cfg.dev_seed_phone))
    except ValueError:
        logger.warning("dev_seed.invalid_phone")
        return {"seeded": False, "reason": "invalid_phone"}

    password = str(cfg.dev_seed_password)
    weak_allowed = bool(getattr(cfg, "dev_seed_allow_weak_password", False))
    policy_error = password_policy_error(password, min_length=cfg.password_min_length)
    if policy_error and not weak_allowed:
        logger.warning(
            "dev_seed.skipped reason=weak_password (set DEV_SEED_ALLOW_WEAK_PASSWORD=true for local dev)"
        )
        return {"seeded": False, "reason": "weak_password"}

    role = normalize_role(str(getattr(cfg, "dev_seed_role", "user") or "user"), default="student")
    display_name = str(getattr(cfg, "dev_seed_name", "mahdi") or "mahdi").strip()[:120] or "mahdi"

    billing = await get_or_init_billing_settings(session)
    tokens_granted = max(1, int(getattr(billing, "starter_tokens", 15_000)))
    days = max(1, int(getattr(billing, "starter_duration_days", 7)))

    existing = await session.scalar(select(User).where(User.phone_number == phone))
    if existing is not None:
        if existing.deleted_at is not None:
            logger.info("dev_seed.skipped reason=deleted_account")
            return {"seeded": False, "reason": "deleted_account", "user_id": existing.id}
        # Never overwrite existing account data; only make an unusable account usable.
        if not existing.password_hash:
            existing.password_hash = hash_password(password)
            existing.phone_verified_at = existing.phone_verified_at or datetime.now(timezone.utc)
            logger.info("dev_seed.password_filled user_id=%s", existing.id)
            return {"seeded": False, "reason": "password_filled", "user_id": existing.id}
        logger.info("dev_seed.present user_id=%s", existing.id)
        return {"seeded": False, "reason": "exists", "user_id": existing.id}

    user = User(
        phone_number=phone,
        full_name=display_name,
        first_name=display_name,
        role=role,
        is_active=True,
        password_hash=hash_password(password),
    )
    apply_plan_to_user(
        user,
        plan_code="trial",
        plan_name="هدیه ثبت‌نام",
        tokens_granted=tokens_granted,
        duration_days=days,
        carry_over_valid=False,
    )
    session.add(user)
    await session.flush()
    # Mark the phone as verified for the seeded account without inventing a login.
    now = datetime.now(timezone.utc)
    user.phone_verified_at = now
    user.last_password_change_at = now
    logger.info("dev_seed.created user_id=%s phone=%s", user.id, phone)
    return {"seeded": True, "reason": "created", "user_id": user.id}


# Mirrors the signup gift so the dev account behaves like a fresh registration.
