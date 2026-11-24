"""Student authentication: SMS OTP, phone + password login, recovery, profile.

Flow (hotfix 2026-11-22):

1. `POST /api/v1/auth/register/request-otp`  — Iranian mobile, sends a 6-digit code.
2. `POST /api/v1/auth/register/verify-otp`   — validates code + expiry, returns a short
   lived signed handshake token (never a login session).
3. `POST /api/v1/auth/register/complete`     — password + confirmation, creates the account.
4. `POST /api/v1/auth/login`                 — mobile + password, no SMS.
5. `POST /api/v1/auth/password/recover/*`    — OTP-gated password reset.
6. `POST /api/v1/auth/password/change`       — authenticated change with current password.

The legacy single-step `request-otp` / `verify-otp` endpoints are preserved unchanged for
OTP-only logins (existing clients, demo mode and the test suite).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import extract_user_token, get_optional_student, require_student
from app.core.config import get_settings
from app.db.session import get_session
from app.models.auth import OtpCode, User, UserSession
from app.services.account_service import get_user_storage_quota_bytes
from app.services import auth_service
from app.services.auth_billing_service import (
    USER_COOKIE_NAME,
    apply_plan_to_user,
    create_user_session_token,
    get_or_init_billing_settings,
    get_user_today_tokens,
    hash_otp_code,
    normalize_iranian_phone,
    parse_user_session_token,
    serialize_user,
    verify_otp_hash,
)
from app.services.sms_provider import get_sms_provider
from app.core.client_ip import client_ip
from app.services.rate_limiter import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RequestOtpBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)
    purpose: Literal["login", "register", "recover"] = "login"


class VerifyOtpBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)
    code: str = Field(min_length=4, max_length=10)
    full_name: str | None = Field(default=None, max_length=120)
    purpose: Literal["login", "register", "recover"] = "login"


class LoginBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)
    password: str = Field(min_length=1, max_length=128)


class CompleteRegistrationBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)
    otp_token: str = Field(min_length=10, max_length=512)
    password: str = Field(min_length=1, max_length=128)
    password_confirm: str = Field(min_length=1, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)


class RecoverPasswordBody(BaseModel):
    phone_number: str = Field(min_length=9, max_length=24)
    otp_token: str = Field(min_length=10, max_length=512)
    password: str = Field(min_length=1, max_length=128)
    password_confirm: str = Field(min_length=1, max_length=128)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)
    password_confirm: str = Field(min_length=1, max_length=128)


class UpdateProfileBody(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)


def _is_https(request: Request) -> bool:
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    )


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


OTP_REQUEST_IP_LIMIT = 20
OTP_REQUEST_IP_WINDOW_SECONDS = 3600
OTP_VERIFY_IP_LIMIT = 30
OTP_VERIFY_IP_WINDOW_SECONDS = 900


def _is_ascii_digits(value: str, length: int) -> bool:
    return len(value) == length and value.isascii() and value.isdigit()


async def _enforce_ip_limit(request: Request, *, bucket: str, limit: int, window: int) -> None:
    decision = await check_rate_limit(
        identity=f"{bucket}:{client_ip(request)}",
        bucket=bucket,
        limit=limit,
        window_seconds=window,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="تعداد درخواست‌ها بیش از حد مجاز است. کمی بعد دوباره تلاش کنید.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(key=USER_COOKIE_NAME, value=token, **auth_service.session_cookie_kwargs(request))


async def _user_payload(session: AsyncSession, user: User) -> dict[str, object]:
    billing = await get_or_init_billing_settings(session)
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    return serialize_user(
        user,
        today_tokens=today_tokens,
        token_price_per_1k_toman=billing.token_price_per_1k_toman,
        storage_quota_bytes=storage_quota,
    )


# ---------------------------------------------------------------------------
# OTP (legacy OTP-only login + purpose-aware request/verify)
# ---------------------------------------------------------------------------


@router.post("/request-otp")
async def request_otp(
    body: RequestOtpBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    # Per-IP budget first (historical behaviour), then per-phone limits in the service.
    await _enforce_ip_limit(
        request, bucket="otp_request", limit=OTP_REQUEST_IP_LIMIT, window=OTP_REQUEST_IP_WINDOW_SECONDS
    )
    challenge = await auth_service.request_otp(
        session,
        request,
        raw_phone=body.phone_number,
        purpose=body.purpose,
        settings=get_settings(),
    )
    payload: dict[str, object] = {
        "sent": True,
        "phone_number": challenge.phone_number,
        "purpose": challenge.purpose,
        "provider": challenge.provider,
        "expires_in_seconds": challenge.expires_in_seconds,
        "resend_after_seconds": challenge.resend_after_seconds,
    }
    if challenge.demo_code and get_settings().demo_mode:
        payload["demo_code"] = challenge.demo_code
    return payload


@router.post("/verify-otp")
async def verify_otp(
    body: VerifyOtpBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Verify an SMS code.

    * `purpose=login` (default): signs the user in — the historical behaviour.
    * `purpose=register`: returns a handshake token for `/register/complete`.
    * `purpose=recover`: returns a handshake token for `/password/recover/complete`.
    """
    await _enforce_ip_limit(
        request, bucket="otp_verify", limit=OTP_VERIFY_IP_LIMIT, window=OTP_VERIFY_IP_WINDOW_SECONDS
    )
    if body.purpose in {"register", "recover"}:
        phone, _otp = await auth_service.consume_otp(
            session,
            request,
            raw_phone=body.phone_number,
            raw_code=body.code,
            purpose=body.purpose,
        )
        await session.commit()
        token = auth_service.create_handshake_token(phone, body.purpose)
        return {
            "verified": True,
            "purpose": body.purpose,
            "phone_number": phone,
            "otp_token": token,
            "expires_in_seconds": get_settings().auth_handshake_ttl_seconds,
        }

    # --- purpose=login: preserved behaviour ---------------------------------
    try:
        phone = normalize_iranian_phone(body.phone_number)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    # The per-phone window is enforced here as well, so brute force against a single
    # number is throttled without waiting for the IP budget to run out.
    await auth_service.enforce_rate_limit(
        request,
        bucket="otp_verify_phone",
        identity=phone,
        limit=10,
        window_seconds=900,
    )
    code_clean = body.code.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    if not _is_ascii_digits(code_clean, 6):
        raise HTTPException(status_code=422, detail="کد تأیید باید ۶ رقم باشد.")

    now = datetime.now(timezone.utc)
    # Lock the active OTP row so parallel verify requests cannot each read the same
    # attempt counter and bypass max_attempts (SELECT ... FOR UPDATE on PostgreSQL).
    otp = await session.scalar(
        select(OtpCode)
        .where(OtpCode.phone_number == phone, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if otp is None:
        raise HTTPException(status_code=401, detail="کد فعالی برای این شماره یافت نشد. ابتدا درخواست کد بدهید.")

    if _utc(otp.expires_at) <= now:
        otp.consumed_at = now
        await session.commit()
        raise HTTPException(status_code=401, detail="کد تأیید منقضی شده است. لطفاً کد جدید دریافت کنید.")

    if otp.attempts >= otp.max_attempts:
        otp.consumed_at = now
        await session.commit()
        raise HTTPException(status_code=429, detail="تعداد تلاش‌های اشتباه بیش از حد مجاز است. کد جدید بگیرید.")

    if not verify_otp_hash(otp.id, phone, code_clean, otp.code_hash):
        otp.attempts += 1
        if otp.attempts >= otp.max_attempts:
            otp.consumed_at = now
        await session.commit()
        remaining = max(0, otp.max_attempts - otp.attempts)
        raise HTTPException(
            status_code=401,
            detail=f"کد واردشده نادرست است. ({remaining} تلاش باقی‌مانده)" if remaining else "کد باطل شد. کد جدید دریافت کنید.",
        )

    otp.consumed_at = now

    billing = await get_or_init_billing_settings(session)
    user = await session.scalar(select(User).where(User.phone_number == phone))
    is_new_user = user is None
    if user is None:
        user = User(
            phone_number=phone,
            full_name=body.full_name.strip() if body.full_name and body.full_name.strip() else None,
            is_active=True,
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
        if getattr(user, "deleted_at", None) is not None:
            await session.commit()
            raise HTTPException(status_code=403, detail="این حساب حذف شده است.")
        if not user.is_active:
            await session.commit()
            raise HTTPException(status_code=403, detail="حساب کاربری شما غیرفعال شده است.")
        if body.full_name and body.full_name.strip() and not user.full_name:
            user.full_name = body.full_name.strip()

    user.last_login_at = now
    user.phone_verified_at = user.phone_verified_at or now
    await session.flush()

    settings = get_settings()
    token_nonce = secrets.token_hex(12)
    token = create_user_session_token(user.id, nonce=token_nonce)
    user_agent = (request.headers.get("user-agent") or "")[:512] or None
    forwarded_for = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    request_ip = (forwarded_for or (request.client.host if request.client else ""))[:64] or None
    session.add(
        UserSession(
            user_id=user.id,
            token_nonce=token_nonce,
            user_agent=user_agent,
            ip_address=request_ip,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=settings.user_session_ttl_seconds),
            created_at=now,
        )
    )
    await session.commit()
    await session.refresh(user)

    _set_session_cookie(response, request, token)
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    return {
        "authenticated": True,
        "is_new_user": is_new_user,
        "needs_password": not bool(getattr(user, "password_hash", None)),
        "token": token,
        "user": serialize_user(
            user,
            today_tokens=today_tokens,
            token_price_per_1k_toman=billing.token_price_per_1k_toman,
            storage_quota_bytes=storage_quota,
            now=now,
        ),
    }


# ---------------------------------------------------------------------------
# Registration (OTP -> password)
# ---------------------------------------------------------------------------


@router.post("/register/request-otp")
async def register_request_otp(
    body: RequestOtpBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    await _enforce_ip_limit(
        request, bucket="otp_request", limit=OTP_REQUEST_IP_LIMIT, window=OTP_REQUEST_IP_WINDOW_SECONDS
    )
    challenge = await auth_service.request_otp(
        session, request, raw_phone=body.phone_number, purpose="register", settings=get_settings()
    )
    payload: dict[str, object] = {
        "sent": True,
        "phone_number": challenge.phone_number,
        "purpose": "register",
        "provider": challenge.provider,
        "expires_in_seconds": challenge.expires_in_seconds,
        "resend_after_seconds": challenge.resend_after_seconds,
    }
    if challenge.demo_code and get_settings().demo_mode:
        payload["demo_code"] = challenge.demo_code
    return payload


@router.post("/register/verify-otp")
async def register_verify_otp(
    body: VerifyOtpBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    phone, _otp = await auth_service.consume_otp(
        session, request, raw_phone=body.phone_number, raw_code=body.code, purpose="register"
    )
    await session.commit()
    return {
        "verified": True,
        "purpose": "register",
        "phone_number": phone,
        "otp_token": auth_service.create_handshake_token(phone, "register"),
        "expires_in_seconds": get_settings().auth_handshake_ttl_seconds,
    }


@router.post("/register/complete")
async def register_complete(
    body: CompleteRegistrationBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    issued, is_new = await auth_service.complete_registration(
        session,
        request,
        raw_phone=body.phone_number,
        handshake_token=body.otp_token,
        password=body.password,
        password_confirm=body.password_confirm,
        full_name=body.full_name,
    )
    _set_session_cookie(response, request, issued.token)
    return {
        "authenticated": True,
        "registered": True,
        "is_new_user": is_new,
        "token": issued.token,
        "user": await _user_payload(session, issued.user),
    }


# ---------------------------------------------------------------------------
# Password login / change / recovery
# ---------------------------------------------------------------------------


@router.post("/login")
async def password_login(
    body: LoginBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    previous_nonce = getattr(request.state, "user_session_nonce", None)
    if previous_nonce is None:
        parsed = parse_user_session_token(extract_user_token(request))
        previous_nonce = parsed[1] if parsed else None
    issued = await auth_service.password_login(
        session,
        request,
        raw_phone=body.phone_number,
        password=body.password,
        previous_nonce=previous_nonce,
    )
    _set_session_cookie(response, request, issued.token)
    return {
        "authenticated": True,
        "token": issued.token,
        "user": await _user_payload(session, issued.user),
    }


@router.post("/password/change")
async def change_password(
    body: ChangePasswordBody,
    request: Request,
    response: Response,
    user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    issued, revoked = await auth_service.change_password(
        session,
        request,
        user=user,
        current_password=body.current_password,
        new_password=body.password,
        new_password_confirm=body.password_confirm,
        current_nonce=getattr(request.state, "user_session_nonce", None),
    )
    _set_session_cookie(response, request, issued.token)
    return {
        "changed": True,
        "revoked_other_sessions": revoked,
        "token": issued.token,
        "user": await _user_payload(session, issued.user),
    }


@router.post("/password/recover/request-otp")
async def recover_request_otp(
    body: RequestOtpBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    await _enforce_ip_limit(
        request, bucket="otp_request", limit=OTP_REQUEST_IP_LIMIT, window=OTP_REQUEST_IP_WINDOW_SECONDS
    )
    challenge = await auth_service.request_otp(
        session, request, raw_phone=body.phone_number, purpose="recover", settings=get_settings()
    )
    payload: dict[str, object] = {
        "sent": True,
        "phone_number": challenge.phone_number,
        "purpose": "recover",
        "provider": challenge.provider,
        "expires_in_seconds": challenge.expires_in_seconds,
        "resend_after_seconds": challenge.resend_after_seconds,
    }
    if challenge.demo_code and get_settings().demo_mode:
        payload["demo_code"] = challenge.demo_code
    return payload


@router.post("/password/recover/verify-otp")
async def recover_verify_otp(
    body: VerifyOtpBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    phone, _otp = await auth_service.consume_otp(
        session, request, raw_phone=body.phone_number, raw_code=body.code, purpose="recover"
    )
    await session.commit()
    return {
        "verified": True,
        "purpose": "recover",
        "phone_number": phone,
        "otp_token": auth_service.create_handshake_token(phone, "recover"),
        "expires_in_seconds": get_settings().auth_handshake_ttl_seconds,
    }


@router.post("/password/recover/complete")
async def recover_complete(
    body: RecoverPasswordBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    issued = await auth_service.reset_password_with_handshake(
        session,
        request,
        raw_phone=body.phone_number,
        handshake_token=body.otp_token,
        new_password=body.password,
        new_password_confirm=body.password_confirm,
    )
    _set_session_cookie(response, request, issued.token)
    return {
        "authenticated": True,
        "reset": True,
        "token": issued.token,
        "user": await _user_payload(session, issued.user),
    }


# ---------------------------------------------------------------------------
# Profile / session
# ---------------------------------------------------------------------------


@router.get("/csrf")
async def issue_csrf_token(request: Request, response: Response) -> dict[str, str]:
    """Issue (and cookie) a CSRF token for the browser client."""
    from app.core.csrf import ensure_csrf_cookie

    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": ensure_csrf_cookie(request, response)}


@router.get("/me")
async def get_me(
    request: Request,
    response: Response,
    user: User | None = Depends(get_optional_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    from app.core.csrf import ensure_csrf_cookie

    response.headers["Cache-Control"] = "no-store"
    if request.cookies.get(USER_COOKIE_NAME):
        # The browser holds an HttpOnly session cookie: hand it the double-submit token
        # (header) so the client can echo it on the next mutation.
        from app.core.csrf import csrf_cookie_kwargs, new_csrf_token

        csrf_token = request.cookies.get("iran_tutor_csrf") or new_csrf_token()
        response.set_cookie(key="iran_tutor_csrf", value=csrf_token, **csrf_cookie_kwargs(request))
        response.headers["X-CSRF-Token"] = csrf_token
    else:
        csrf_token = ""
    if user is None or not user.is_active:
        payload: dict[str, object] = {"authenticated": False, "user": None}
    else:
        payload = {
            "authenticated": True,
            "has_password": bool(getattr(user, "password_hash", None)),
            "user": await _user_payload(session, user),
        }
    if csrf_token:
        # Only present for cookie-based browser sessions that must echo it on mutations.
        payload["csrf_token"] = csrf_token
    return payload


@router.put("/me")
async def update_me(
    body: UpdateProfileBody,
    user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    user.full_name = body.full_name.strip()[:120]
    await session.commit()
    await session.refresh(user)
    return {"user": await _user_payload(session, user)}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    token = extract_user_token(request)
    parsed = parse_user_session_token(token)
    if parsed is not None:
        user_id, nonce, _ = parsed
        session_row = await session.scalar(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.token_nonce == nonce,
                UserSession.revoked_at.is_(None),
            )
        )
        if session_row is not None:
            session_row.revoked_at = datetime.now(timezone.utc)
            await session.commit()

    https = _is_https(request)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        key=USER_COOKIE_NAME,
        path="/",
        samesite="none" if https else "lax",
        secure=https,
    )
    return {"authenticated": False}
