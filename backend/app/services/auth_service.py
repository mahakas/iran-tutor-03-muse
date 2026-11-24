"""Phone + password authentication service (hotfix 2026-11-22).

This service owns every credential decision so routers stay thin and the rules are
testable in isolation:

* OTP issuance and verification with purpose (`login` | `register` | `recover`).
* Password login (no SMS), registration completion, password change and recovery.
* Session issuance with rotation: every new login revokes the presented session, and
  password/privilege changes revoke the account's other sessions.
* Uniform failure messages so responses never reveal whether a phone is registered.

Phone numbers are always normalized with `normalize_iranian_phone` before any lookup or
uniqueness check, so `+98 912…`, `0098912…` and Persian-digit input can never create a
second account for the same line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import logging
import secrets
from uuid import uuid4

from fastapi import HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import client_ip, constant_time_equal
from app.core.config import get_settings
from app.core.passwords import (
    hash_password,
    needs_rehash,
    password_policy_error,
    verify_password,
)
from app.core.signing import derive_session_key
from app.models.auth import OtpCode, User, UserSession
from app.services.auth_billing_service import (
    apply_plan_to_user,
    get_or_init_billing_settings,
    hash_otp_code,
    normalize_iranian_phone,
    verify_otp_hash,
)
from app.services.permissions import normalize_role
from app.services.rate_limiter import check_rate_limit
from app.services.sms_provider import get_sms_provider

logger = logging.getLogger(__name__)

OTP_PURPOSES: tuple[str, ...] = ("login", "register", "recover")

# One message for every credential failure. Never "no such phone" vs "wrong password".
GENERIC_LOGIN_ERROR = "شماره موبایل یا رمز عبور نادرست است."
GENERIC_OTP_ERROR = "کد تأیید نادرست یا منقضی شده است."
GENERIC_ACCOUNT_ERROR = "این شماره موبایل قابل استفاده نیست."

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def normalize_code(raw: str) -> str:
    return (raw or "").strip().translate(_PERSIAN_DIGITS)


@dataclass(frozen=True)
class OtpChallenge:
    phone_number: str
    purpose: str
    provider: str
    expires_in_seconds: int
    resend_after_seconds: int
    demo_code: str | None


@dataclass(frozen=True)
class OtpGrant:
    """Result of a verified OTP for register/recover flows.

    The handshake token is signed exactly like a session token but carries a distinct
    purpose prefix, so it can never be replayed as a login session.
    """

    phone_number: str
    purpose: str
    token: str
    expires_in_seconds: int


@dataclass(frozen=True)
class IssuedSession:
    token: str
    session_id: str
    user: User
    expires_in_seconds: int


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


async def enforce_rate_limit(
    request: Request,
    *,
    bucket: str,
    identity: str,
    limit: int,
    window_seconds: int,
    message: str = "تعداد درخواست‌ها بیش از حد مجاز است. کمی بعد دوباره تلاش کنید.",
) -> None:
    decision = await check_rate_limit(
        identity=f"{bucket}:{identity}",
        bucket=bucket,
        limit=limit,
        window_seconds=window_seconds,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=message,
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


async def enforce_login_limits(request: Request, phone: str) -> None:
    settings = get_settings()
    await enforce_rate_limit(
        request,
        bucket="password_login_ip",
        identity=client_ip(request),
        limit=settings.login_ip_limit,
        window_seconds=settings.login_ip_window_seconds,
        message="تعداد تلاش‌های ورود بیش از حد مجاز است. کمی بعد دوباره تلاش کنید.",
    )
    await enforce_rate_limit(
        request,
        bucket="password_login_phone",
        identity=phone,
        limit=settings.login_phone_limit,
        window_seconds=settings.login_phone_window_seconds,
        message="تعداد تلاش‌های ورود این شماره بیش از حد مجاز است. کمی بعد دوباره تلاش کنید.",
    )


async def enforce_otp_request_limits(request: Request, phone: str, *, settings=None) -> None:
    """Per-phone OTP request limit. The per-IP limit stays in the API layer (`_enforce_ip_limit`)."""
    cfg = settings or get_settings()
    await enforce_rate_limit(
        request,
        bucket="otp_request_phone",
        identity=phone,
        limit=int(getattr(cfg, "otp_phone_limit", 5) or 5),
        window_seconds=int(getattr(cfg, "otp_phone_window_seconds", 3600) or 3600),
    )


async def enforce_otp_verify_limits(request: Request, phone: str) -> None:
    """Per-phone verification limit (the per-IP limit is enforced by the router)."""
    await enforce_rate_limit(
        request,
        bucket="otp_verify_phone",
        identity=phone,
        limit=10,
        window_seconds=900,
    )


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _session_ttl_seconds() -> int:
    return int(get_settings().user_session_ttl_seconds)


def issue_session_row(
    session: AsyncSession,
    user: User,
    *,
    request: Request | None,
    now: datetime | None = None,
) -> tuple[str, UserSession]:
    """Create a `UserSession` row plus its signed token (caller commits)."""
    from app.services.auth_billing_service import create_user_session_token

    current = now or utcnow()
    nonce = secrets.token_hex(12)
    token = create_user_session_token(user.id, nonce=nonce)
    user_agent = None
    ip_address = None
    if request is not None:
        user_agent = (request.headers.get("user-agent") or "")[:512] or None
        ip_address = (client_ip(request) or "")[:64] or None
    row = UserSession(
        user_id=user.id,
        token_nonce=nonce,
        user_agent=user_agent,
        ip_address=ip_address,
        last_seen_at=current,
        expires_at=current + timedelta(seconds=_session_ttl_seconds()),
        created_at=current,
    )
    session.add(row)
    return token, row


async def revoke_user_sessions(
    session: AsyncSession,
    user_id: str,
    *,
    keep_nonce: str | None = None,
    now: datetime | None = None,
) -> int:
    """Revoke every live session for a user, optionally keeping the current one."""
    current = now or utcnow()
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=current)
    )
    if keep_nonce:
        stmt = stmt.where(UserSession.token_nonce != keep_nonce)
    result = await session.execute(stmt)
    return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# OTP
# ---------------------------------------------------------------------------


def _validate_purpose(purpose: str | None) -> str:
    value = (purpose or "login").strip().lower()
    return value if value in OTP_PURPOSES else "login"


async def find_user_by_phone(session: AsyncSession, phone: str) -> User | None:
    return await session.scalar(select(User).where(User.phone_number == phone))


def account_can_authenticate(user: User | None) -> bool:
    if user is None:
        return False
    if getattr(user, "deleted_at", None) is not None:
        return False
    return bool(user.is_active)


async def request_otp(
    session: AsyncSession,
    request: Request,
    *,
    raw_phone: str,
    purpose: str = "login",
    new_user_only: bool = False,
    settings=None,
) -> OtpChallenge:
    """Issue an OTP. `settings` lets the caller inject its effective settings object."""
    try:
        phone = normalize_iranian_phone(raw_phone)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    cfg = settings or get_settings()
    await enforce_otp_request_limits(request, phone, settings=cfg)
    resolved_purpose = _validate_purpose(purpose)
    now = utcnow()

    if new_user_only:
        existing = await find_user_by_phone(session, phone)
        if existing is not None and existing.deleted_at is None:
            raise HTTPException(status_code=409, detail="این شماره موبایل قبلاً ثبت شده است.")

    latest = await session.scalar(
        select(OtpCode)
        .where(OtpCode.phone_number == phone)
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    resend_seconds = int(getattr(cfg, "otp_resend_seconds", 60) or 0)
    if latest is not None and resend_seconds > 0 and latest.consumed_at is None:
        elapsed = (now - (_aware(latest.created_at) or now)).total_seconds()
        if elapsed < resend_seconds:
            wait_s = max(1, int(resend_seconds - elapsed))
            raise HTTPException(
                status_code=429,
                detail=f"لطفاً {wait_s} ثانیه دیگر برای ارسال مجدد کد صبر کنید.",
                headers={"Retry-After": str(wait_s)},
            )

    # Only the newest code may be redeemed.
    await session.execute(
        update(OtpCode)
        .where(OtpCode.phone_number == phone, OtpCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )

    code = f"{secrets.randbelow(900000) + 100000}"
    otp_id = str(uuid4())
    session.add(
        OtpCode(
            id=otp_id,
            phone_number=phone,
            purpose=resolved_purpose,
            code_hash=hash_otp_code(otp_id, phone, code),
            attempts=0,
            max_attempts=cfg.otp_max_attempts,
            expires_at=now + timedelta(seconds=cfg.otp_ttl_seconds),
            created_at=now,
        )
    )
    await session.commit()

    provider = get_sms_provider(cfg)
    try:
        delivery = await provider.send_otp(phone_number=phone, code=code)
    except Exception as error:  # noqa: BLE001
        logger.exception("SMS OTP delivery failed via %s", provider.provider_name)
        raise HTTPException(
            status_code=503,
            detail="ارسال پیامک در حال حاضر با خطا مواجه شد. لطفاً لحظاتی دیگر تلاش کنید.",
        ) from error

    # The raw code is returned so the API layer can decide whether to disclose it
    # (demo mode only). Nothing else reads `demo_code`.
    return OtpChallenge(
        phone_number=phone,
        purpose=resolved_purpose,
        provider=delivery.provider,
        expires_in_seconds=cfg.otp_ttl_seconds,
        resend_after_seconds=cfg.otp_resend_seconds,
        demo_code=code,
    )


async def consume_otp(
    session: AsyncSession,
    request: Request,
    *,
    raw_phone: str,
    raw_code: str,
    purpose: str = "login",
) -> tuple[str, OtpCode]:
    """Verify and consume the newest unconsumed code. Returns (phone, otp_row)."""
    try:
        phone = normalize_iranian_phone(raw_phone)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    await enforce_otp_verify_limits(request, phone)
    code = normalize_code(raw_code)
    if not (len(code) == 6 and code.isascii() and code.isdigit()):
        raise HTTPException(status_code=422, detail="کد تأیید باید ۶ رقم باشد.")

    now = utcnow()
    resolved_purpose = _validate_purpose(purpose)
    otp = await session.scalar(
        select(OtpCode)
        .where(OtpCode.phone_number == phone, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if otp is None:
        raise HTTPException(status_code=401, detail=GENERIC_OTP_ERROR)

    # A code minted for one purpose must not unlock another (e.g. login code -> reset).
    if (otp.purpose or "login") != resolved_purpose:
        raise HTTPException(status_code=401, detail=GENERIC_OTP_ERROR)

    if (_aware(otp.expires_at) or now) <= now:
        otp.consumed_at = now
        await session.commit()
        raise HTTPException(status_code=401, detail=GENERIC_OTP_ERROR)

    if otp.attempts >= otp.max_attempts:
        otp.consumed_at = now
        await session.commit()
        raise HTTPException(status_code=429, detail="تعداد تلاش‌های اشتباه بیش از حد مجاز است. کد جدید بگیرید.")

    if not verify_otp_hash(otp.id, phone, code, otp.code_hash):
        otp.attempts += 1
        if otp.attempts >= otp.max_attempts:
            otp.consumed_at = now
        await session.commit()
        raise HTTPException(status_code=401, detail=GENERIC_OTP_ERROR)

    otp.consumed_at = now
    return phone, otp


# ---------------------------------------------------------------------------
# Handshake tokens (OTP verified -> set password)
# ---------------------------------------------------------------------------


def _handshake_key(purpose: str) -> bytes:
    return derive_session_key(f"iran-tutor-otp-grant-{purpose}")


def create_handshake_token(phone: str, purpose: str, *, ttl_seconds: int | None = None) -> str:
    settings = get_settings()
    ttl = ttl_seconds if ttl_seconds is not None else settings.auth_handshake_ttl_seconds
    expires_at = int(utcnow().timestamp()) + ttl
    nonce = secrets.token_hex(8)
    payload = f"{phone}.{expires_at}.{nonce}"
    signature = hmac.new(_handshake_key(purpose), payload.encode("utf-8"), "sha256").hexdigest()
    return f"{payload}.{signature}"


def parse_handshake_token(token: str | None, purpose: str) -> str | None:
    if not token or token.count(".") != 3:
        return None
    phone, expires_raw, nonce, signature = token.split(".", 3)
    if not phone or not nonce or not (expires_raw.isascii() and expires_raw.isdigit()):
        return None
    if int(expires_raw) <= int(utcnow().timestamp()):
        return None
    expected = hmac.new(
        _handshake_key(purpose), f"{phone}.{expires_raw}.{nonce}".encode("utf-8"), "sha256"
    ).hexdigest()
    if not constant_time_equal(signature, expected):
        return None
    return phone


def _require_handshake(raw_phone: str, token: str | None, purpose: str) -> str:
    """Validate the grant and confirm it belongs to the phone in the same request."""
    try:
        phone = normalize_iranian_phone(raw_phone)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    granted_phone = parse_handshake_token(token, purpose)
    if granted_phone is None or not constant_time_equal(granted_phone, phone):
        raise HTTPException(
            status_code=401,
            detail="زمان تأیید کد به پایان رسیده است. لطفاً دوباره کد تأیید بگیرید.",
        )
    return phone


# ---------------------------------------------------------------------------
# Registration / password
# ---------------------------------------------------------------------------


def _check_password_policy(password: str) -> None:
    settings = get_settings()
    error = password_policy_error(password, min_length=settings.password_min_length)
    if error:
        raise HTTPException(status_code=422, detail=error)


def ensure_password_confirmed(password: str, confirm: str | None) -> None:
    if confirm is None or password != confirm:
        raise HTTPException(status_code=422, detail="رمز عبور و تکرار آن یکسان نیست.")


async def complete_registration(
    session: AsyncSession,
    request: Request,
    *,
    raw_phone: str,
    handshake_token: str | None,
    password: str,
    password_confirm: str | None,
    full_name: str | None = None,
) -> tuple[IssuedSession, bool]:
    """Finish the OTP-verified registration by storing the first password."""
    phone = _require_handshake(raw_phone, handshake_token, "register")
    ensure_password_confirmed(password, password_confirm)
    _check_password_policy(password)

    now = utcnow()
    existing = await find_user_by_phone(session, phone)
    is_new = existing is None or existing.deleted_at is not None
    billing = await get_or_init_billing_settings(session)

    if existing is not None and existing.deleted_at is not None:
        raise HTTPException(
            status_code=409,
            detail="این حساب حذف شده است. برای بازیابی با پشتیبانی تماس بگیرید.",
        )
    if existing is not None and existing.password_hash:
        # Already registered: registration must not silently overwrite a password.
        raise HTTPException(status_code=409, detail="این شماره موبایل قبلاً ثبت شده است.")

    if existing is None:
        user = User(
            phone_number=phone,
            full_name=(full_name or "").strip()[:120] or None,
            is_active=True,
            role="student",
            created_at=now,
            updated_at=now,
        )
        apply_plan_to_user(
            user,
            plan_code="trial",
            plan_name="هدیه ثبت‌نام",
            tokens_granted=billing.starter_tokens,
            duration_days=billing.starter_duration_days,
            carry_over_valid=False,
            now=now,
        )
        session.add(user)
    else:
        user = existing
        if not user.is_active:
            raise HTTPException(status_code=403, detail="حساب کاربری شما غیرفعال شده است.")
        if full_name and full_name.strip() and not user.full_name:
            user.full_name = full_name.strip()[:120]

    try:
        user.password_hash = hash_password(password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    user.phone_verified_at = user.phone_verified_at or now
    user.last_password_change_at = now
    user.last_login_at = now
    user.updated_at = now
    await session.flush()

    token, row = issue_session_row(session, user, request=request, now=now)
    try:
        await session.commit()
    except IntegrityError as error:  # concurrent registration for the same number
        await session.rollback()
        raise HTTPException(status_code=409, detail="این شماره موبایل قبلاً ثبت شده است.") from error
    await session.refresh(user)
    return (
        IssuedSession(
            token=token, session_id=row.id, user=user, expires_in_seconds=_session_ttl_seconds()
        ),
        is_new,
    )


async def password_login(
    session: AsyncSession,
    request: Request,
    *,
    raw_phone: str,
    password: str,
    previous_nonce: str | None = None,
) -> IssuedSession:
    """Mobile + password login. No SMS is sent for an ordinary login."""
    try:
        phone = normalize_iranian_phone(raw_phone)
    except ValueError as error:
        # Same shape as a wrong credential: do not confirm which part failed.
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR) from error

    await enforce_login_limits(request, phone)
    now = utcnow()
    user = await find_user_by_phone(session, phone)

    if not account_can_authenticate(user) or not getattr(user, "password_hash", None):
        # Still burn Argon2 time so unknown/deactivated accounts are not faster.
        verify_password(password, None)
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

    assert user is not None
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

    if needs_rehash(user.password_hash):
        try:
            user.password_hash = hash_password(password)
        except ValueError:
            logger.warning("password.rehash_skipped user=%s", user.id)

    user.last_login_at = now
    user.updated_at = now
    if user.phone_verified_at is None:
        # A password login on an account verified by legacy OTP still proves the phone
        # is controlled at registration time; mark it so "verified" has one meaning.
        user.phone_verified_at = now

    token, row = issue_session_row(session, user, request=request, now=now)
    # Rotation: the caller's previous session (if any) is revoked in the same transaction.
    if previous_nonce:
        await session.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user.id,
                UserSession.token_nonce == previous_nonce,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
    await session.commit()
    await session.refresh(user)
    return IssuedSession(
        token=token, session_id=row.id, user=user, expires_in_seconds=_session_ttl_seconds()
    )


async def change_password(
    session: AsyncSession,
    request: Request,
    *,
    user: User,
    current_password: str | None,
    new_password: str,
    new_password_confirm: str | None,
    current_nonce: str | None = None,
    require_current: bool = True,
) -> tuple[IssuedSession, int]:
    """Change a password, then revoke every other session and rotate the current one."""
    if require_current or user.password_hash:
        if not user.password_hash:
            raise HTTPException(
                status_code=409,
                detail="برای این حساب رمز عبوری تعیین نشده است؛ ابتدا از مسیر بازیابی رمز استفاده کنید.",
            )
        if not current_password:
            raise HTTPException(status_code=422, detail="رمز عبور فعلی را وارد کنید.")
        if not verify_password(current_password, user.password_hash):
            raise HTTPException(status_code=401, detail="رمز عبور فعلی نادرست است.")

    ensure_password_confirmed(new_password, new_password_confirm)
    _check_password_policy(new_password)
    if user.password_hash and verify_password(new_password, user.password_hash):
        raise HTTPException(status_code=422, detail="رمز عبور جدید باید با رمز فعلی متفاوت باشد.")

    now = utcnow()
    user.password_hash = hash_password(new_password)
    user.last_password_change_at = now
    user.updated_at = now
    revoked = await revoke_user_sessions(session, user.id, keep_nonce=None, now=now)
    token, row = issue_session_row(session, user, request=request, now=now)
    await session.commit()
    await session.refresh(user)
    return (
        IssuedSession(token=token, session_id=row.id, user=user, expires_in_seconds=_session_ttl_seconds()),
        revoked,
    )


async def reset_password_with_handshake(
    session: AsyncSession,
    request: Request,
    *,
    raw_phone: str,
    handshake_token: str | None,
    new_password: str,
    new_password_confirm: str | None,
) -> IssuedSession:
    """OTP-verified password recovery. Revokes all existing sessions."""
    phone = _require_handshake(raw_phone, handshake_token, "recover")
    ensure_password_confirmed(new_password, new_password_confirm)
    _check_password_policy(new_password)

    user = await find_user_by_phone(session, phone)
    if user is None or user.deleted_at is not None:
        # Uniform: a verified code for an unknown number still fails the same way.
        raise HTTPException(status_code=401, detail=GENERIC_ACCOUNT_ERROR)
    if not user.is_active:
        raise HTTPException(status_code=403, detail="حساب کاربری شما غیرفعال شده است.")

    now = utcnow()
    user.password_hash = hash_password(new_password)
    user.last_password_change_at = now
    user.phone_verified_at = user.phone_verified_at or now
    user.updated_at = now
    await revoke_user_sessions(session, user.id, now=now)
    token, row = issue_session_row(session, user, request=request, now=now)
    await session.commit()
    await session.refresh(user)
    return IssuedSession(
        token=token, session_id=row.id, user=user, expires_in_seconds=_session_ttl_seconds()
    )


async def set_password_directly(
    session: AsyncSession,
    *,
    user: User,
    new_password: str,
    revoke_sessions: bool = True,
) -> None:
    """Admin/seed path: set a password without the current one. Caller commits."""
    _check_password_policy(new_password)
    now = utcnow()
    user.password_hash = hash_password(new_password)
    user.last_password_change_at = now
    user.updated_at = now
    if revoke_sessions:
        await revoke_user_sessions(session, user.id, now=now)


def session_cookie_kwargs(request: Request) -> dict[str, object]:
    """Cookie attributes shared by every session-setting endpoint."""
    https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    )
    return {
        "max_age": _session_ttl_seconds(),
        "httponly": True,
        "samesite": "none" if https else "lax",
        "secure": https,
        "path": "/",
    }


def role_of(user: User) -> str:
    return normalize_role(getattr(user, "role", None))


def display_name(user: User) -> str | None:
    return (
        " ".join(p for p in [(user.first_name or "").strip(), (user.last_name or "").strip()] if p)
        or (user.full_name or None)
    )


async def count_active_users(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_active.is_(True), User.deleted_at.is_(None))
        )
        or 0
    )
