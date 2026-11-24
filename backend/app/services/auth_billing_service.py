"""Shared helpers for Iranian mobile OTP, student tokens, plans, and token accounting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.seed import seed_billing_settings, seed_plans
from app.models.auth import BillingSettings, Plan, TokenUsageLog, User, UserSession
from app.services.account_service import compose_full_name, normalize_preferences
from app.core.client_ip import constant_time_equal
from app.core.signing import derive_session_key

USER_COOKIE_NAME = "iran_tutor_user"

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PHONE_CLEAN_RE = re.compile(r"[\s\-\(\)]+")
_IRAN_MOBILE_RE = re.compile(r"^09\d{9}$")


def normalize_iranian_phone(raw: str) -> str:
    """Convert Iranian mobile numbers (+98 / 0098 / 98 / 09 / Persian digits) to 09XXXXXXXXX."""
    cleaned = _PHONE_CLEAN_RE.sub("", (raw or "").translate(_PERSIAN_DIGITS).strip())
    if cleaned.startswith("+98"):
        cleaned = "0" + cleaned[3:]
    elif cleaned.startswith("0098"):
        cleaned = "0" + cleaned[4:]
    elif cleaned.startswith("98") and len(cleaned) == 12:
        cleaned = "0" + cleaned[2:]
    elif cleaned.startswith("9") and len(cleaned) == 10:
        cleaned = "0" + cleaned
    if not _IRAN_MOBILE_RE.match(cleaned):
        raise ValueError("شماره موبایل معتبر نیست. لطفاً شمارهٔ ۱۱ رقمی با ۰۹ وارد کنید.")
    return cleaned


def mask_phone_number(phone: str) -> str:
    if len(phone) < 8:
        return phone
    return f"{phone[:4]}***{phone[-4:]}"


def _user_signing_key() -> bytes:
    # Derived from AUTH_SECRET / SECRET_KEY only (never the LLM key or admin password).
    return derive_session_key("iran-tutor-user-v2")


def create_user_session_token(
    user_id: str,
    *,
    ttl_seconds: int | None = None,
    nonce: str | None = None,
) -> str:
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.user_session_ttl_seconds
    expires_at = int(datetime.now(timezone.utc).timestamp()) + ttl
    token_nonce = nonce or secrets.token_hex(12)
    payload = f"{user_id}.{expires_at}.{token_nonce}"
    signature = hmac.new(_user_signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def parse_user_session_token(token: str | None) -> tuple[str, str, int] | None:
    if not token or token.count(".") != 3:
        return None
    user_id, expires_raw, nonce, signature = token.split(".", 3)
    if not user_id or not (expires_raw.isascii() and expires_raw.isdigit()) or not nonce or not signature:
        return None
    expires_ts = int(expires_raw)
    if expires_ts <= int(datetime.now(timezone.utc).timestamp()):
        return None
    expected = hmac.new(
        _user_signing_key(),
        f"{user_id}.{expires_raw}.{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not constant_time_equal(signature, expected):
        return None
    return user_id, nonce, expires_ts


def verify_user_session_token(token: str | None) -> str | None:
    parsed = parse_user_session_token(token)
    return parsed[0] if parsed is not None else None


def hash_otp_code(otp_id: str, phone_number: str, code: str) -> str:
    message = f"{otp_id}:{phone_number}:{code}".encode("utf-8")
    return hmac.new(_user_signing_key(), message, hashlib.sha256).hexdigest()


def verify_otp_hash(otp_id: str, phone_number: str, code: str, expected_hash: str) -> bool:
    actual = hash_otp_code(otp_id, phone_number, code)
    return constant_time_equal(actual, expected_hash)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def utc_iso(value: datetime | None) -> str | None:
    dt = _utc(value)
    return dt.isoformat() if dt is not None else None


def is_user_plan_expired(user: User, *, now: datetime | None = None) -> bool:
    expires = _utc(user.plan_expires_at)
    if expires is None:
        return True
    current = now or datetime.now(timezone.utc)
    return expires <= current


def calculate_token_cost_toman(tokens: int, *, token_price_per_1k_toman: int) -> int:
    if tokens <= 0 or token_price_per_1k_toman <= 0:
        return 0
    return max(1, round(tokens * token_price_per_1k_toman / 1000))


async def get_or_init_billing_settings(session: AsyncSession) -> BillingSettings:
    billing = await session.get(BillingSettings, 1)
    if billing is None:
        await seed_billing_settings(session)
        await session.flush()
        billing = await session.get(BillingSettings, 1)
    assert billing is not None
    return billing


async def get_or_init_plans(session: AsyncSession) -> list[Plan]:
    plans = list((await session.scalars(select(Plan).order_by(Plan.sort_order, Plan.id))).all())
    if not plans:
        await seed_plans(session)
        await session.flush()
        plans = list((await session.scalars(select(Plan).order_by(Plan.sort_order, Plan.id))).all())
    return plans


async def get_user_today_tokens(session: AsyncSession, user_id: str) -> int:
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total = await session.scalar(
        select(func.coalesce(func.sum(TokenUsageLog.total_tokens), 0)).where(
            TokenUsageLog.user_id == user_id,
            TokenUsageLog.created_at >= start_of_day,
        )
    )
    return int(total or 0)


def serialize_plan(plan: Plan) -> dict[str, object]:
    effective_per_1k = (
        round(plan.price_toman * 1000 / plan.token_quota) if plan.token_quota > 0 else 0
    )
    return {
        "id": plan.id,
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "price_toman": plan.price_toman,
        "token_quota": plan.token_quota,
        "storage_quota_bytes": int(getattr(plan, "storage_quota_bytes", 104_857_600) or 104_857_600),
        "duration_days": plan.duration_days,
        "effective_toman_per_1k": effective_per_1k,
        "is_active": bool(plan.is_active),
        "sort_order": plan.sort_order,
    }


def serialize_user(
    user: User,
    *,
    today_tokens: int = 0,
    token_price_per_1k_toman: int = 1000,
    storage_quota_bytes: int | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or datetime.now(timezone.utc)
    expires = _utc(user.plan_expires_at)
    expired = is_user_plan_expired(user, now=current)
    days_remaining = (
        max(0, (expires - current).days + (1 if (expires - current).seconds > 0 else 0))
        if expires is not None and not expired
        else 0
    )
    first_name = getattr(user, "first_name", None)
    last_name = getattr(user, "last_name", None)
    full_name = compose_full_name(first_name, last_name, getattr(user, "full_name", None))
    avatar_path = getattr(user, "avatar_path", None)
    has_avatar = bool(avatar_path)
    return {
        "id": user.id,
        "phone_number": user.phone_number,
        "masked_phone": mask_phone_number(user.phone_number),
        "full_name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "email": getattr(user, "email", None),
        "role": getattr(user, "role", "student") or "student",
        "has_avatar": has_avatar,
        "avatar_url": f"/api/v1/account/profile/avatar?v={int(_utc(user.updated_at).timestamp()) if getattr(user, 'updated_at', None) else 1}"
        if has_avatar
        else None,
        "preferences": normalize_preferences(getattr(user, "preferences", None)),
        "storage_quota_bytes": storage_quota_bytes,
        "plan_code": user.plan_code,
        "plan_title": user.plan_title,
        "tokens_total": user.tokens_total,
        "tokens_remaining": user.tokens_remaining,
        "tokens_used_total": user.tokens_used_total,
        "tokens_used_today": today_tokens,
        "used_value_toman": calculate_token_cost_toman(
            user.tokens_used_total, token_price_per_1k_toman=token_price_per_1k_toman
        ),
        "plan_started_at": utc_iso(user.plan_started_at),
        "plan_expires_at": utc_iso(user.plan_expires_at),
        "days_remaining": days_remaining,
        "is_expired": expired,
        "is_active": bool(user.is_active),
        "last_login_at": utc_iso(user.last_login_at),
        "created_at": utc_iso(user.created_at),
    }


def ensure_user_can_consume(user: User, *, now: datetime | None = None) -> None:
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="حساب کاربری شما غیرفعال شده است. لطفاً با پشتیبانی تماس بگیرید.",
        )
    if is_user_plan_expired(user, now=now):
        raise HTTPException(
            status_code=402,
            detail="مدت اعتبار پلن شما به پایان رسیده است. لطفاً یکی از پلن‌ها را فعال کنید.",
        )
    if user.tokens_remaining <= 0:
        raise HTTPException(
            status_code=402,
            detail="سهمیهٔ توکن شما به پایان رسیده است. لطفاً پلن خود را شارژ یا ارتقا دهید.",
        )


def apply_plan_to_user(
    user: User,
    *,
    plan_code: str,
    plan_name: str,
    tokens_granted: int,
    duration_days: int,
    carry_over_valid: bool = True,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(timezone.utc)
    target_expiry = current + timedelta(days=duration_days)
    existing_expiry = _utc(user.plan_expires_at)

    if (
        carry_over_valid
        and user.plan_code != "trial"
        and existing_expiry is not None
        and existing_expiry > current
        and user.tokens_remaining > 0
    ):
        user.tokens_remaining = user.tokens_remaining + tokens_granted
        user.tokens_total = user.tokens_remaining
        user.plan_expires_at = max(existing_expiry, target_expiry)
    else:
        user.tokens_remaining = tokens_granted
        user.tokens_total = tokens_granted
        user.plan_expires_at = target_expiry

    user.plan_code = plan_code
    user.plan_title = plan_name
    user.plan_started_at = current


async def record_and_deduct_usage(
    session: AsyncSession,
    *,
    user: User,
    action: str,
    book_id: int | None,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> dict[str, int]:
    """Persist token consumption, deduct from user balance, and return usage metrics."""
    effective_total = max(0, total_tokens or (prompt_tokens + completion_tokens))
    if effective_total == 0:
        effective_total = 1
        prompt_tokens = 1

    billing = await get_or_init_billing_settings(session)
    cost_toman = calculate_token_cost_toman(
        effective_total, token_price_per_1k_toman=billing.token_price_per_1k_toman
    )

    user.tokens_remaining = max(0, user.tokens_remaining - effective_total)
    user.tokens_used_total = user.tokens_used_total + effective_total

    log_entry = TokenUsageLog(
        user_id=user.id,
        action=action,
        book_id=book_id,
        prompt_tokens=max(0, prompt_tokens),
        completion_tokens=max(0, completion_tokens),
        total_tokens=effective_total,
        cost_toman=cost_toman,
    )
    session.add(log_entry)
    await session.commit()
    return {
        "prompt_tokens": max(0, prompt_tokens),
        "completion_tokens": max(0, completion_tokens),
        "total_tokens": effective_total,
        "cost_toman": cost_toman,
        "tokens_remaining": user.tokens_remaining,
    }
