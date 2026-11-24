"""Student account APIs: profile, OTP-verified phone change, preferences, storage, and sessions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import logging
from pathlib import Path
import secrets
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_student
from app.core.config import get_settings
from app.db.session import get_session
from app.models.auth import OtpCode, User, UserFile, UserSession
from app.models.chat import ChatSession
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.models.exam import ExamSession
from app.services.upload_guard import verify_extension
from app.services.account_service import (
    ALLOWED_PERSONAL_FILE_EXTS,
    MAX_SINGLE_USER_UPLOAD_BYTES,
    compose_full_name,
    default_preferences,
    ensure_user_file_path,
    find_file_dependencies,
    get_user_storage_quota_bytes,
    get_user_storage_summary,
    merge_preferences,
    normalize_preferences,
    save_user_file,
    serialize_session,
    serialize_user_file,
    validate_email_optional,
)
from app.services.auth_billing_service import (
    get_or_init_billing_settings,
    get_user_today_tokens,
    hash_otp_code,
    normalize_iranian_phone,
    serialize_user,
    verify_otp_hash,
)
from app.services.sms_provider import get_sms_provider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/account", tags=["account"])

AVATAR_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024


class ProfileUpdateBody(BaseModel):
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    full_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=255)


class PhoneChangeRequestBody(BaseModel):
    new_phone_number: str = Field(min_length=9, max_length=24)


class PhoneChangeVerifyBody(BaseModel):
    new_phone_number: str = Field(min_length=9, max_length=24)
    code: str = Field(min_length=4, max_length=10)


class PreferencesPatchBody(BaseModel):
    general: dict[str, Any] | None = None
    appearance: dict[str, Any] | None = None
    notifications: dict[str, Any] | None = None
    privacy: dict[str, Any] | None = None


class PreferencesResetBody(BaseModel):
    section: Literal["all", "general", "appearance", "notifications", "privacy"] = "appearance"


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


async def _serialize_account_user(session: AsyncSession, user: User) -> dict[str, object]:
    billing = await get_or_init_billing_settings(session)
    today_tokens = await get_user_today_tokens(session, user.id)
    storage_quota = await get_user_storage_quota_bytes(session, user, billing)
    return serialize_user(
        user,
        today_tokens=today_tokens,
        token_price_per_1k_toman=billing.token_price_per_1k_toman,
        storage_quota_bytes=storage_quota,
    )


def _normalize_avatar_png(data: bytes, content_type: str) -> bytes:
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime not in AVATAR_MIME_TYPES:
        raise HTTPException(status_code=415, detail="فرمت تصویر پروفایل باید PNG، JPEG یا WebP باشد.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
            if image.format != expected[mime]:
                raise HTTPException(status_code=415, detail="محتوای تصویر با فرمت اعلام‌شده مطابقت ندارد.")
            img = ImageOps.exif_transpose(image).convert("RGBA")
            img.thumbnail((512, 512))
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=422, detail="فایل تصویر معتبر نیست.") from exc


@router.get("/profile")
async def get_profile(
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    return {"user": await _serialize_account_user(session, current_user)}


@router.put("/profile")
async def update_profile(
    body: ProfileUpdateBody,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    fields = body.model_fields_set

    if "first_name" in fields:
        current_user.first_name = body.first_name.strip()[:80] if body.first_name and body.first_name.strip() else None
    if "last_name" in fields:
        current_user.last_name = body.last_name.strip()[:80] if body.last_name and body.last_name.strip() else None

    if "first_name" in fields or "last_name" in fields:
        composed = compose_full_name(current_user.first_name, current_user.last_name)
        if composed:
            current_user.full_name = composed
        elif "full_name" in fields:
            current_user.full_name = body.full_name.strip()[:120] if body.full_name and body.full_name.strip() else None
        else:
            current_user.full_name = None
    elif "full_name" in fields:
        current_user.full_name = body.full_name.strip()[:120] if body.full_name and body.full_name.strip() else None

    if "email" in fields:
        try:
            current_user.email = validate_email_optional(body.email)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    current_user.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(current_user)
    return {"user": await _serialize_account_user(session, current_user)}


@router.post("/profile/avatar")
async def upload_profile_avatar(
    response: Response,
    avatar: UploadFile = File(...),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    raw = await avatar.read(MAX_AVATAR_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=422, detail="فایل تصویر خالی است.")
    if len(raw) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="حجم تصویر پروفایل نباید بیشتر از ۵ مگابایت باشد.")

    png_bytes = _normalize_avatar_png(raw, avatar.content_type or "")
    billing = await get_or_init_billing_settings(session)

    # Remove previous profile avatar file first so quota tracks the replacement accurately
    old_avatars = list(
        (
            await session.scalars(
                select(UserFile).where(
                    UserFile.user_id == current_user.id,
                    UserFile.source_context == "profile_avatar",
                )
            )
        ).all()
    )
    for old_file in old_avatars:
        try:
            ensure_user_file_path(current_user.id, old_file.storage_path).unlink(missing_ok=True)
        except HTTPException:
            pass
        await session.delete(old_file)
    await session.flush()

    saved = await save_user_file(
        session,
        user=current_user,
        billing=billing,
        filename="avatar.png",
        content_bytes=png_bytes,
        mime_type="image/png",
        source_context="profile_avatar",
        enforce_quota=True,
    )
    current_user.avatar_path = saved.storage_path
    current_user.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(current_user)
    return {"user": await _serialize_account_user(session, current_user)}


@router.delete("/profile/avatar")
async def delete_profile_avatar(
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    if current_user.avatar_path:
        try:
            ensure_user_file_path(current_user.id, current_user.avatar_path).unlink(missing_ok=True)
        except HTTPException:
            pass
        current_user.avatar_path = None

    avatar_files = list(
        (
            await session.scalars(
                select(UserFile).where(
                    UserFile.user_id == current_user.id,
                    UserFile.source_context == "profile_avatar",
                )
            )
        ).all()
    )
    for f in avatar_files:
        try:
            ensure_user_file_path(current_user.id, f.storage_path).unlink(missing_ok=True)
        except HTTPException:
            pass
        await session.delete(f)

    current_user.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(current_user)
    return {"user": await _serialize_account_user(session, current_user)}


@router.get("/profile/avatar")
async def get_profile_avatar(
    current_user: User = Depends(require_student),
) -> FileResponse:
    if not current_user.avatar_path:
        raise HTTPException(status_code=404, detail="تصویر پروفایل ثبت نشده است.")
    path = ensure_user_file_path(current_user.id, current_user.avatar_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="فایل تصویر پروفایل یافت نشد.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/profile/phone/request-otp")
async def request_phone_change_otp(
    body: PhoneChangeRequestBody,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    try:
        new_phone = normalize_iranian_phone(body.new_phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if new_phone == current_user.phone_number:
        raise HTTPException(status_code=422, detail="شماره جدید با شماره فعلی یکسان است.")

    existing = await session.scalar(select(User).where(User.phone_number == new_phone))
    if existing is not None:
        raise HTTPException(status_code=409, detail="این شماره موبایل قبلاً در حساب دیگری ثبت شده است.")

    settings = get_settings()
    now = datetime.now(timezone.utc)
    latest = await session.scalar(
        select(OtpCode)
        .where(OtpCode.phone_number == new_phone)
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if latest is not None and settings.otp_resend_seconds > 0:
        created = latest.created_at if latest.created_at.tzinfo is not None else latest.created_at.replace(tzinfo=timezone.utc)
        elapsed = (now - created).total_seconds()
        if elapsed < settings.otp_resend_seconds and latest.consumed_at is None:
            wait_s = max(1, int(settings.otp_resend_seconds - elapsed))
            raise HTTPException(status_code=429, detail=f"لطفاً {wait_s} ثانیه دیگر برای ارسال مجدد صبر کنید.")

    await session.execute(
        update(OtpCode)
        .where(OtpCode.phone_number == new_phone, OtpCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )

    code = f"{secrets.randbelow(900000) + 100000}"
    otp_id = str(uuid4())
    session.add(
        OtpCode(
            id=otp_id,
            phone_number=new_phone,
            code_hash=hash_otp_code(otp_id, new_phone, code),
            attempts=0,
            max_attempts=settings.otp_max_attempts,
            expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
            created_at=now,
        )
    )
    await session.commit()

    provider = get_sms_provider(settings)
    try:
        delivery = await provider.send_otp(phone_number=new_phone, code=code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Phone change OTP SMS failed")
        raise HTTPException(status_code=503, detail="ارسال پیامک با خطا مواجه شد.") from exc

    payload: dict[str, object] = {
        "sent": True,
        "phone_number": new_phone,
        "provider": delivery.provider,
        "resend_after_seconds": settings.otp_resend_seconds,
    }
    if settings.demo_mode:
        payload["demo_code"] = code
    return payload


@router.post("/profile/phone/verify")
async def verify_phone_change(
    body: PhoneChangeVerifyBody,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    try:
        new_phone = normalize_iranian_phone(body.new_phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    code_clean = body.code.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    if not (code_clean.isascii() and code_clean.isdigit()) or len(code_clean) != 6:
        raise HTTPException(status_code=422, detail="کد تأیید باید ۶ رقم باشد.")

    existing = await session.scalar(select(User).where(User.phone_number == new_phone))
    if existing is not None and existing.id != current_user.id:
        raise HTTPException(status_code=409, detail="این شماره موبایل قبلاً ثبت شده است.")

    now = datetime.now(timezone.utc)
    otp = await session.scalar(
        select(OtpCode)
        .where(OtpCode.phone_number == new_phone, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    if otp is None:
        raise HTTPException(status_code=401, detail="کد فعالی یافت نشد؛ ابتدا کد را دریافت کنید.")

    expires = otp.expires_at if otp.expires_at.tzinfo is not None else otp.expires_at.replace(tzinfo=timezone.utc)
    if expires <= now:
        otp.consumed_at = now
        await session.commit()
        raise HTTPException(status_code=401, detail="کد تأیید منقضی شده است.")

    if otp.attempts >= otp.max_attempts:
        otp.consumed_at = now
        await session.commit()
        raise HTTPException(status_code=429, detail="تعداد تلاش‌های اشتباه بیش از حد مجاز است.")

    if not verify_otp_hash(otp.id, new_phone, code_clean, otp.code_hash):
        otp.attempts += 1
        if otp.attempts >= otp.max_attempts:
            otp.consumed_at = now
        await session.commit()
        raise HTTPException(status_code=401, detail="کد تأیید نادرست است.")

    otp.consumed_at = now
    current_user.phone_number = new_phone
    current_user.updated_at = now
    await session.commit()
    await session.refresh(current_user)
    return {"user": await _serialize_account_user(session, current_user)}


@router.get("/preferences")
async def get_preferences(
    response: Response,
    current_user: User = Depends(require_student),
) -> dict[str, object]:
    _no_store(response)
    return {"preferences": normalize_preferences(current_user.preferences)}


@router.put("/preferences")
async def update_preferences(
    body: PreferencesPatchBody,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    patch = body.model_dump(exclude_none=True)
    try:
        merged = merge_preferences(current_user.preferences, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    current_user.preferences = merged
    current_user.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(current_user)
    return {
        "preferences": merged,
        "user": await _serialize_account_user(session, current_user),
    }


@router.post("/preferences/reset")
async def reset_preferences(
    body: PreferencesResetBody,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    defaults = default_preferences()
    if body.section == "all":
        updated = defaults
    else:
        updated = normalize_preferences(current_user.preferences)
        updated[body.section] = defaults[body.section]

    current_user.preferences = updated
    current_user.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(current_user)
    return {
        "preferences": updated,
        "user": await _serialize_account_user(session, current_user),
    }


@router.get("/storage")
async def get_storage_overview(
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    billing = await get_or_init_billing_settings(session)
    return await get_user_storage_summary(session, user=current_user, billing=billing)


@router.get("/storage/files")
async def list_storage_files(
    response: Response,
    q: str | None = Query(default=None, max_length=120),
    category: Literal["all", "image", "audio", "file"] = Query(default="all"),
    sort_by: Literal["date", "size", "name"] = Query(default="date"),
    sort_dir: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1, le=500),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    billing = await get_or_init_billing_settings(session)
    summary = await get_user_storage_summary(session, user=current_user, billing=billing)

    base_filter = [UserFile.user_id == current_user.id, UserFile.status == "active"]
    if category != "all":
        base_filter.append(UserFile.category == category)
    if q and q.strip():
        base_filter.append(UserFile.original_filename.ilike(f"%{q.strip()}%"))

    total = int(await session.scalar(select(func.count()).select_from(UserFile).where(*base_filter)) or 0)
    sort_col = {
        "date": UserFile.created_at,
        "size": UserFile.size_bytes,
        "name": UserFile.original_filename,
    }[sort_by]
    order_expr = asc(sort_col) if sort_dir == "asc" else desc(sort_col)

    rows = list(
        (
            await session.scalars(
                select(UserFile)
                .where(*base_filter)
                .order_by(order_expr)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )

    items = []
    for row in rows:
        deps = await find_file_dependencies(session, user=current_user, file_row=row)
        items.append(serialize_user_file(row, dependencies=deps))

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "storage": summary,
    }


@router.post("/storage/files")
async def upload_personal_file(
    response: Response,
    file: UploadFile = File(...),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    filename = Path(file.filename or "").name
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_PERSONAL_FILE_EXTS:
        raise HTTPException(
            status_code=415,
            detail="فرمت فایل پشتیبانی نمی‌شود. فرمت‌های مجاز: تصویر (PNG/JPG/WebP)، صوت (MP3/WAV/OGG/WebM)، PDF، Markdown، TXT، JSON و HTML.",
        )

    expected_mime, _ = ALLOWED_PERSONAL_FILE_EXTS[ext]
    data = await file.read(MAX_SINGLE_USER_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="فایل انتخاب‌شده خالی است.")
    if len(data) > MAX_SINGLE_USER_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="حجم فایل نباید بیشتر از ۲۵ مگابایت باشد.")

    verify_extension(filename, data)
    if expected_mime.startswith("image/"):
        try:
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise HTTPException(status_code=422, detail="فایل تصویر معتبر نیست.") from exc

    billing = await get_or_init_billing_settings(session)
    saved = await save_user_file(
        session,
        user=current_user,
        billing=billing,
        filename=filename,
        content_bytes=data,
        mime_type=expected_mime,
        source_context="personal_upload",
        enforce_quota=True,
    )
    await session.commit()
    await session.refresh(saved)
    summary = await get_user_storage_summary(session, user=current_user, billing=billing)
    return {
        "file": serialize_user_file(saved),
        "storage": summary,
    }


@router.get("/storage/files/{file_id}")
async def get_storage_file_detail(
    file_id: str,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    row = await session.scalar(
        select(UserFile).where(
            UserFile.id == file_id,
            UserFile.user_id == current_user.id,
            UserFile.status == "active",
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="فایل مورد نظر یافت نشد.")
    deps = await find_file_dependencies(session, user=current_user, file_row=row)
    return {"file": serialize_user_file(row, dependencies=deps)}


@router.get("/storage/files/{file_id}/content")
async def download_or_preview_storage_file(
    file_id: str,
    download: bool = Query(default=False),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    row = await session.scalar(
        select(UserFile).where(
            UserFile.id == file_id,
            UserFile.user_id == current_user.id,
            UserFile.status == "active",
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="فایل مورد نظر یافت نشد.")
    path = ensure_user_file_path(current_user.id, row.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="فایل روی سرور یافت نشد.")

    # Never execute user-uploaded HTML inline as text/html
    safe_media_type = "text/plain; charset=utf-8" if row.mime_type == "text/html" and not download else row.mime_type
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        media_type=safe_media_type,
        filename=row.original_filename if download else None,
        content_disposition_type=disposition,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/storage/files/{file_id}")
async def delete_storage_file(
    file_id: str,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    row = await session.scalar(
        select(UserFile).where(
            UserFile.id == file_id,
            UserFile.user_id == current_user.id,
            UserFile.status == "active",
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="فایل مورد نظر یافت نشد یا قبلاً حذف شده است.")

    try:
        ensure_user_file_path(current_user.id, row.storage_path).unlink(missing_ok=True)
    except HTTPException:
        pass

    if row.source_context == "profile_avatar" or (
        current_user.avatar_path and current_user.avatar_path == row.storage_path
    ):
        current_user.avatar_path = None
        current_user.updated_at = datetime.now(timezone.utc)

    await session.delete(row)
    await session.commit()

    billing = await get_or_init_billing_settings(session)
    summary = await get_user_storage_summary(session, user=current_user, billing=billing)
    return {"deleted": True, "file_id": file_id, "storage": summary}


@router.get("/sessions")
async def list_user_sessions(
    request: Request,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    current_nonce = getattr(request.state, "user_session_nonce", None)
    rows = list(
        (
            await session.scalars(
                select(UserSession)
                .where(UserSession.user_id == current_user.id)
                .order_by(UserSession.last_seen_at.desc(), UserSession.created_at.desc())
                .limit(30)
            )
        ).all()
    )
    return {
        "sessions": [serialize_session(r, current_nonce=current_nonce) for r in rows]
    }


@router.delete("/sessions/{session_id}")
async def revoke_single_session(
    session_id: str,
    request: Request,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    row = await session.scalar(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == current_user.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="نشست مورد نظر یافت نشد.")
    current_nonce = getattr(request.state, "user_session_nonce", None)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await session.commit()
    return {
        "revoked": True,
        "revoked_current": bool(current_nonce and row.token_nonce == current_nonce),
    }


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(
    request: Request,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    current_nonce = getattr(request.state, "user_session_nonce", None)
    now = datetime.now(timezone.utc)
    stmt = (
        update(UserSession)
        .where(
            UserSession.user_id == current_user.id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    if current_nonce:
        stmt = stmt.where(UserSession.token_nonce != current_nonce)
    result = await session.execute(stmt)
    await session.commit()
    return {"revoked_count": int(result.rowcount or 0)}


@router.get("/search")
async def search_account_workspace(
    response: Response,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=10, ge=1, le=25),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _no_store(response)
    term = q.strip()
    pattern = f"%{term}%" if term else None

    book_stmt = (
        select(Book, Grade.number, Grade.title, Major.code, Major.title)
        .join(Grade, Book.grade_id == Grade.id)
        .outerjoin(Major, Book.major_id == Major.id)
        .where(Book.status == BookStatus.ready)
    )
    if pattern is not None:
        book_stmt = book_stmt.where(
            or_(Book.title.ilike(pattern), Grade.title.ilike(pattern), Major.title.ilike(pattern))
        )
    book_rows = (await session.execute(book_stmt.order_by(Book.title).limit(limit))).all()

    topic_stmt = (
        select(BookPage, Book.title, Grade.number, Major.code)
        .join(Book, BookPage.book_id == Book.id)
        .join(Grade, Book.grade_id == Grade.id)
        .outerjoin(Major, Book.major_id == Major.id)
        .where(Book.status == BookStatus.ready, BookPage.status == PageStatus.done)
    )
    if pattern is not None:
        topic_stmt = topic_stmt.where(
            or_(
                BookPage.chapter_title.ilike(pattern),
                BookPage.markdown_content.ilike(pattern),
                Book.title.ilike(pattern),
            )
        )
    topic_rows = (
        await session.execute(topic_stmt.order_by(Book.id.desc(), BookPage.pdf_page_index.asc()).limit(limit))
    ).all()

    chat_stmt = (
        select(ChatSession, Book.title)
        .join(Book, ChatSession.book_id == Book.id)
        .where(ChatSession.user_id == current_user.id)
    )
    if pattern is not None:
        chat_stmt = chat_stmt.where(
            or_(ChatSession.title.ilike(pattern), Book.title.ilike(pattern))
        )
    chat_rows = (
        await session.execute(chat_stmt.order_by(ChatSession.updated_at.desc()).limit(limit))
    ).all()

    exam_stmt = (
        select(ExamSession, Book.title)
        .join(Book, ExamSession.book_id == Book.id)
        .where(ExamSession.user_id == current_user.id)
    )
    if pattern is not None:
        exam_stmt = exam_stmt.where(
            or_(ExamSession.title.ilike(pattern), Book.title.ilike(pattern))
        )
    exam_rows = (
        await session.execute(exam_stmt.order_by(ExamSession.created_at.desc()).limit(limit))
    ).all()

    file_stmt = select(UserFile).where(
        UserFile.user_id == current_user.id,
        UserFile.status == "active",
    )
    if pattern is not None:
        file_stmt = file_stmt.where(
            or_(UserFile.original_filename.ilike(pattern), UserFile.category.ilike(pattern))
        )
    file_rows = (await session.scalars(file_stmt.order_by(UserFile.created_at.desc()).limit(limit))).all()

    return {
        "query": term,
        "books": [
            {
                "id": book.id,
                "title": book.title,
                "grade_number": grade_num,
                "grade_title": grade_title,
                "major_code": major_code or "general",
                "major_title": major_title,
            }
            for book, grade_num, grade_title, major_code, major_title in book_rows
        ],
        "topics": [
            {
                "book_id": page.book_id,
                "book_title": book_title,
                "grade_number": grade_num,
                "major_code": major_code or "general",
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title,
                "printed_page_number": page.printed_page_number,
                "pdf_page_index": page.pdf_page_index,
            }
            for page, book_title, grade_num, major_code in topic_rows
        ],
        "chats": [
            {
                "id": chat.id,
                "title": chat.title,
                "mode": chat.mode,
                "book_id": chat.book_id,
                "book_title": book_title,
                "grade_number": chat.grade_number,
                "major_code": chat.major_code,
            }
            for chat, book_title in chat_rows
        ],
        "exams": [
            {
                "id": exam.id,
                "title": exam.title,
                "exam_type": exam.exam_type,
                "status": exam.status.value if hasattr(exam.status, "value") else str(exam.status),
                "book_id": exam.book_id,
                "book_title": book_title,
            }
            for exam, book_title in exam_rows
        ],
        "files": [
            {
                "id": f.id,
                "filename": f.original_filename,
                "category": f.category,
                "size_bytes": f.size_bytes,
                "source_context": f.source_context,
            }
            for f in file_rows
        ],
    }
