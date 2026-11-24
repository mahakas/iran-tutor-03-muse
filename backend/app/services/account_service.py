"""Account profile, user preferences, active sessions, and personal storage management."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BACKEND_DIR
from app.models.auth import BillingSettings, Plan, User, UserFile, UserSession
from app.models.chat import ChatSession

logger = logging.getLogger(__name__)

USER_FILES_DIR = BACKEND_DIR / "storage" / "user_files"
MAX_SINGLE_USER_UPLOAD_BYTES = 25 * 1024 * 1024

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ALLOWED_LANGUAGES = {"fa", "en", "ar"}
ALLOWED_TUTOR_MODES = {"tutor", "problem_solver", "question_designer"}
ALLOWED_VISUAL_STYLES = {
    "standard",
    "modern",
    "compact",
    "darsyar",
    "minimal",
    "soft",
    "contrast",
}
ALLOWED_COLOR_MODES = {"light", "dark", "system"}
ALLOWED_REDUCE_MOTION = {"off", "on", "system"}
ALLOWED_FONTS = {"vazir", "system", "sahel", "mono", "tahoma", "vazirmatn"}
_SHARED_THEME_IDS = {
    "darsyar",
    "emerald",
    "slate",
    "ocean",
    "warm",
    "violet",
    "graphite",
    "midnight",
    "custom",
}
ALLOWED_LIGHT_THEMES = _SHARED_THEME_IDS | {
    "darsyar-teal",
    "ocean-blue",
    "forest-emerald",
    "royal-indigo",
    "warm-amber",
}
ALLOWED_DARK_THEMES = _SHARED_THEME_IDS | {
    "darsyar-midnight",
    "slate-blue",
    "emerald-night",
    "obsidian-violet",
    "charcoal-amber",
}

ALLOWED_PERSONAL_FILE_EXTS: dict[str, tuple[str, str]] = {
    ".png": ("image/png", "image"),
    ".jpg": ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".webp": ("image/webp", "image"),
    ".mp3": ("audio/mpeg", "audio"),
    ".wav": ("audio/wav", "audio"),
    ".m4a": ("audio/mp4", "audio"),
    ".webm": ("audio/webm", "audio"),
    ".ogg": ("audio/ogg", "audio"),
    ".pdf": ("application/pdf", "file"),
    ".md": ("text/markdown", "file"),
    ".markdown": ("text/markdown", "file"),
    ".txt": ("text/plain", "file"),
    ".json": ("application/json", "file"),
    ".html": ("text/html", "file"),
}

DEFAULT_PREFERENCES: dict[str, Any] = {
    "general": {
        "language": "fa",
        "timezone": "Asia/Tehran",
        "default_tutor_mode": "tutor",
    },
    "appearance": {
        "visual_style": "standard",
        "color_mode": "light",
        "separate_mode_themes": True,
        "light": {
            "theme": "darsyar",
            "accent": "#177e77",
            "background": "#f7f9f8",
            "foreground": "#202b35",
            "font_family": "vazir",
        },
        "dark": {
            "theme": "darsyar",
            "accent": "#2dd4bf",
            "background": "#0f171a",
            "foreground": "#e8f1ef",
            "font_family": "vazir",
        },
        "ui_font_size": 14,
        "code_font_size": 13,
        "reduce_motion": "system",
        "contrast": 50,
        "diff_markers": True,
    },
    "notifications": {
        "email_updates": False,
        "usage_alerts": True,
        "plan_expiry_reminders": True,
        "exam_reminders": True,
        "security_alerts": True,
    },
    "privacy": {
        "save_chat_history": True,
        "store_uploaded_attachments": True,
        "show_phone_masked": True,
    },
}


def default_preferences() -> dict[str, Any]:
    return deepcopy(DEFAULT_PREFERENCES)


def _validate_hex(value: Any, *, field_name: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not _HEX_COLOR_RE.match(value.strip()):
        raise ValueError(f"مقدار رنگ برای {field_name} باید در قالب #RRGGBB باشد.")
    return value.strip().lower()


def _normalize_mode_theme(raw: Any, defaults: dict[str, str], allowed_themes: set[str], *, strict: bool) -> dict[str, str]:
    result = dict(defaults)
    if not isinstance(raw, dict):
        return result
    if "theme" in raw and raw["theme"] is not None:
        val = str(raw["theme"]).strip()
        if val in allowed_themes:
            result["theme"] = val
        elif strict:
            raise ValueError(f"تم انتخاب‌شده معتبر نیست: {val}")
    for color_key in ("accent", "background", "foreground"):
        if color_key in raw and raw[color_key] is not None:
            if strict:
                result[color_key] = _validate_hex(raw[color_key], field_name=color_key, default=defaults[color_key])
            elif isinstance(raw[color_key], str) and _HEX_COLOR_RE.match(raw[color_key].strip()):
                result[color_key] = raw[color_key].strip().lower()
    if "font_family" in raw and raw["font_family"] is not None:
        val = str(raw["font_family"]).strip()
        if val in ALLOWED_FONTS:
            result["font_family"] = val
        elif strict:
            raise ValueError(f"فونت انتخاب‌شده معتبر نیست: {val}")
    return result


def normalize_preferences(raw: Any, *, strict: bool = False) -> dict[str, Any]:
    """Merge stored or incoming preference dicts onto `DEFAULT_PREFERENCES`."""
    prefs = default_preferences()
    if not isinstance(raw, dict):
        return prefs

    # General
    gen_in = raw.get("general")
    if isinstance(gen_in, dict):
        if "language" in gen_in and gen_in["language"] is not None:
            lang = str(gen_in["language"]).strip().lower()
            if lang in ALLOWED_LANGUAGES:
                prefs["general"]["language"] = lang
            elif strict:
                raise ValueError("زبان انتخاب‌شده پشتیبانی نمی‌شود.")
        if "timezone" in gen_in and gen_in["timezone"] is not None:
            tz = str(gen_in["timezone"]).strip()
            try:
                ZoneInfo(tz)
                prefs["general"]["timezone"] = tz
            except ZoneInfoNotFoundError as exc:
                if strict:
                    raise ValueError("منطقه زمانی انتخاب‌شده معتبر نیست.") from exc
        if "default_tutor_mode" in gen_in and gen_in["default_tutor_mode"] is not None:
            mode = str(gen_in["default_tutor_mode"]).strip()
            if mode in ALLOWED_TUTOR_MODES:
                prefs["general"]["default_tutor_mode"] = mode
            elif strict:
                raise ValueError("حالت پیش‌فرض معلم معتبر نیست.")

    # Appearance
    app_in = raw.get("appearance")
    if isinstance(app_in, dict):
        if "visual_style" in app_in and app_in["visual_style"] is not None:
            style = str(app_in["visual_style"]).strip()
            if style in ALLOWED_VISUAL_STYLES:
                prefs["appearance"]["visual_style"] = style
            elif strict:
                raise ValueError("سبک بصری انتخاب‌شده معتبر نیست.")
        if "color_mode" in app_in and app_in["color_mode"] is not None:
            cm = str(app_in["color_mode"]).strip()
            if cm in ALLOWED_COLOR_MODES:
                prefs["appearance"]["color_mode"] = cm
            elif strict:
                raise ValueError("حالت رنگ انتخاب‌شده معتبر نیست.")
        if "separate_mode_themes" in app_in and app_in["separate_mode_themes"] is not None:
            prefs["appearance"]["separate_mode_themes"] = bool(app_in["separate_mode_themes"])
        if "light" in app_in:
            prefs["appearance"]["light"] = _normalize_mode_theme(
                app_in.get("light"), prefs["appearance"]["light"], ALLOWED_LIGHT_THEMES, strict=strict
            )
        if "dark" in app_in:
            prefs["appearance"]["dark"] = _normalize_mode_theme(
                app_in.get("dark"), prefs["appearance"]["dark"], ALLOWED_DARK_THEMES, strict=strict
            )
        if "ui_font_size" in app_in and app_in["ui_font_size"] is not None:
            try:
                sz = int(app_in["ui_font_size"])
                if 12 <= sz <= 20:
                    prefs["appearance"]["ui_font_size"] = sz
                elif strict:
                    raise ValueError("اندازه فونت رابط کاربری باید بین ۱۲ تا ۲۰ پیکسل باشد.")
            except (TypeError, ValueError) as exc:
                if strict:
                    raise ValueError("اندازه فونت رابط کاربری باید بین ۱۲ تا ۲۰ پیکسل باشد.") from exc
        if "code_font_size" in app_in and app_in["code_font_size"] is not None:
            try:
                csz = int(app_in["code_font_size"])
                if 11 <= csz <= 20:
                    prefs["appearance"]["code_font_size"] = csz
                elif strict:
                    raise ValueError("اندازه فونت کد باید بین ۱۱ تا ۲۰ پیکسل باشد.")
            except (TypeError, ValueError) as exc:
                if strict:
                    raise ValueError("اندازه فونت کد باید بین ۱۱ تا ۲۰ پیکسل باشد.") from exc
        if "reduce_motion" in app_in and app_in["reduce_motion"] is not None:
            rm = str(app_in["reduce_motion"]).strip()
            if rm in ALLOWED_REDUCE_MOTION:
                prefs["appearance"]["reduce_motion"] = rm
            elif strict:
                raise ValueError("تنظیم کاهش حرکت معتبر نیست.")
        if "contrast" in app_in and app_in["contrast"] is not None:
            try:
                ct = int(app_in["contrast"])
                if 0 <= ct <= 100:
                    prefs["appearance"]["contrast"] = ct
                elif strict:
                    raise ValueError("مقدار کنتراست باید بین ۰ تا ۱۰۰ باشد.")
            except (TypeError, ValueError) as exc:
                if strict:
                    raise ValueError("مقدار کنتراست باید بین ۰ تا ۱۰۰ باشد.") from exc
        if "diff_markers" in app_in and app_in["diff_markers"] is not None:
            prefs["appearance"]["diff_markers"] = bool(app_in["diff_markers"])

    # Notifications
    notif_in = raw.get("notifications")
    if isinstance(notif_in, dict):
        for key in (
            "email_updates",
            "usage_alerts",
            "plan_expiry_reminders",
            "exam_reminders",
            "security_alerts",
        ):
            if key in notif_in and notif_in[key] is not None:
                prefs["notifications"][key] = bool(notif_in[key])

    # Privacy
    priv_in = raw.get("privacy")
    if isinstance(priv_in, dict):
        for key in ("save_chat_history", "store_uploaded_attachments", "show_phone_masked"):
            if key in priv_in and priv_in[key] is not None:
                prefs["privacy"][key] = bool(priv_in[key])

    return prefs


def merge_preferences(existing: Any, patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge validated partial preference updates onto existing user preferences."""
    base = normalize_preferences(existing, strict=False)
    candidate = deepcopy(base)
    for section in ("general", "notifications", "privacy"):
        if section in patch and isinstance(patch[section], dict):
            candidate[section].update(patch[section])
    if "appearance" in patch and isinstance(patch["appearance"], dict):
        app_patch = patch["appearance"]
        for key, val in app_patch.items():
            if key in ("light", "dark") and isinstance(val, dict):
                candidate["appearance"][key].update(val)
            else:
                candidate["appearance"][key] = val
    return normalize_preferences(candidate, strict=True)


def validate_email_optional(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned:
        return None
    if len(cleaned) > 255 or not _EMAIL_RE.match(cleaned):
        raise ValueError("آدرس ایمیل واردشده معتبر نیست.")
    return cleaned


def compose_full_name(first_name: str | None, last_name: str | None, fallback: str | None = None) -> str | None:
    parts = [p.strip() for p in (first_name or "", last_name or "") if p and p.strip()]
    if parts:
        return " ".join(parts)[:120]
    return fallback.strip()[:120] if fallback and fallback.strip() else None


def user_storage_root(user_id: str) -> Path:
    root = (USER_FILES_DIR / user_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_user_file_path(user_id: str, path_str: str) -> Path:
    root = (USER_FILES_DIR / user_id).resolve()
    resolved = Path(path_str).resolve()
    if not resolved.is_relative_to(root):
        raise HTTPException(status_code=403, detail="دسترسی به مسیر فایل مجاز نیست.")
    return resolved


def categorize_mime(mime_type: str, filename: str) -> str:
    mime = (mime_type or "").split(";")[0].strip().lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/") or mime == "application/ogg":
        return "audio"
    ext = Path(filename or "").suffix.lower()
    if ext in ALLOWED_PERSONAL_FILE_EXTS:
        return ALLOWED_PERSONAL_FILE_EXTS[ext][1]
    return "file"


async def get_user_storage_quota_bytes(
    session: AsyncSession,
    user: User,
    billing: BillingSettings,
) -> int:
    if user.plan_code == "trial":
        return int(getattr(billing, "starter_storage_bytes", 26_214_400) or 26_214_400)
    plan = await session.scalar(select(Plan).where(Plan.code == user.plan_code))
    if plan is not None:
        return int(getattr(plan, "storage_quota_bytes", 104_857_600) or 104_857_600)
    return int(getattr(billing, "starter_storage_bytes", 26_214_400) or 26_214_400)


async def get_user_storage_summary(
    session: AsyncSession,
    *,
    user: User,
    billing: BillingSettings,
) -> dict[str, object]:
    quota_bytes = await get_user_storage_quota_bytes(session, user, billing)
    rows = (
        await session.execute(
            select(
                UserFile.category,
                func.count(UserFile.id),
                func.coalesce(func.sum(UserFile.size_bytes), 0),
            )
            .where(UserFile.user_id == user.id, UserFile.status == "active")
            .group_by(UserFile.category)
        )
    ).all()

    categories: dict[str, dict[str, int]] = {
        "files": {"count": 0, "bytes": 0},
        "images": {"count": 0, "bytes": 0},
        "audio": {"count": 0, "bytes": 0},
    }
    total_count = 0
    used_bytes = 0
    for cat, cnt, size_sum in rows:
        c = int(cnt or 0)
        b = int(size_sum or 0)
        total_count += c
        used_bytes += b
        if cat == "image":
            categories["images"]["count"] += c
            categories["images"]["bytes"] += b
        elif cat == "audio":
            categories["audio"]["count"] += c
            categories["audio"]["bytes"] += b
        else:
            categories["files"]["count"] += c
            categories["files"]["bytes"] += b

    remaining_bytes = max(0, quota_bytes - used_bytes)
    usage_percent = min(100, round((used_bytes * 100) / quota_bytes)) if quota_bytes > 0 else 100
    if used_bytes >= quota_bytes and quota_bytes > 0:
        status = "full"
    elif usage_percent >= 80:
        status = "warning"
    else:
        status = "normal"

    return {
        "used_bytes": used_bytes,
        "quota_bytes": quota_bytes,
        "remaining_bytes": remaining_bytes,
        "over_quota": used_bytes > quota_bytes,
        "usage_percent": usage_percent,
        "status": status,
        "total_files": total_count,
        "categories": categories,
        "plan_code": user.plan_code,
        "plan_title": user.plan_title,
    }


async def save_user_file(
    session: AsyncSession,
    *,
    user: User,
    billing: BillingSettings,
    filename: str,
    content_bytes: bytes,
    mime_type: str,
    source_context: str,
    book_id: int | None = None,
    chat_session_id: str | None = None,
    enforce_quota: bool = True,
) -> UserFile:
    size = len(content_bytes)
    if size <= 0:
        raise HTTPException(status_code=422, detail="فایل انتخاب‌شده خالی است.")
    if size > MAX_SINGLE_USER_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="حجم هر فایل نمی‌تواند بیشتر از ۲۵ مگابایت باشد.")

    if enforce_quota:
        summary = await get_user_storage_summary(session, user=user, billing=billing)
        used = int(summary["used_bytes"])  # type: ignore[arg-type]
        quota = int(summary["quota_bytes"])  # type: ignore[arg-type]
        if used + size > quota:
            raise HTTPException(
                status_code=413,
                detail="فضای ذخیره‌سازی حساب شما کافی نیست. لطفاً بخشی از فایل‌ها را حذف کنید یا پلن خود را ارتقا دهید.",
            )

    file_id = str(uuid4())
    clean_name = Path(filename or "file").name[:255] or "file"
    ext = Path(clean_name).suffix.lower()
    if not ext or len(ext) > 12:
        ext = ".bin"
    category = categorize_mime(mime_type, clean_name)

    root = user_storage_root(user.id)
    dest = (root / f"{file_id}{ext}").resolve()
    if not dest.is_relative_to(root):
        raise HTTPException(status_code=400, detail="نام فایل معتبر نیست.")
    dest.write_bytes(content_bytes)

    row = UserFile(
        id=file_id,
        user_id=user.id,
        original_filename=clean_name,
        storage_path=str(dest),
        mime_type=(mime_type or "application/octet-stream").split(";")[0].strip().lower(),
        category=category,
        size_bytes=size,
        source_context=source_context,
        chat_session_id=chat_session_id,
        book_id=book_id,
        status="active",
    )
    session.add(row)
    await session.flush()
    return row


async def find_file_dependencies(
    session: AsyncSession,
    *,
    user: User,
    file_row: UserFile,
) -> list[dict[str, str]]:
    dependencies: list[dict[str, str]] = []
    if file_row.source_context == "profile_avatar" or (
        user.avatar_path and user.avatar_path == file_row.storage_path
    ):
        dependencies.append(
            {
                "type": "profile_avatar",
                "title": "تصویر پروفایل فعلی حساب شما",
                "label": "تصویر پروفایل فعلی حساب شما",
            }
        )
    if file_row.chat_session_id:
        chat = await session.scalar(
            select(ChatSession).where(
                ChatSession.id == file_row.chat_session_id,
                ChatSession.user_id == user.id,
            )
        )
        if chat is not None:
            dependencies.append(
                {
                    "type": "chat_session",
                    "id": chat.id,
                    "title": chat.title,
                    "label": f"گفت‌وگوی «{chat.title}»",
                }
            )
    elif file_row.source_context in {"tutor_image", "tutor_audio"}:
        # Match by attachment filename in user's chat sessions if not explicitly linked
        chats = list(
            (
                await session.scalars(
                    select(ChatSession).where(ChatSession.user_id == user.id).limit(50)
                )
            ).all()
        )
        for chat in chats:
            if any(
                isinstance(msg, dict) and msg.get("attachment") == file_row.original_filename
                for msg in (chat.messages or [])
            ):
                dependencies.append(
                    {
                        "type": "chat_session",
                        "id": chat.id,
                        "title": chat.title,
                        "label": f"گفت‌وگوی «{chat.title}»",
                    }
                )
    return dependencies


def serialize_user_file(
    row: UserFile,
    *,
    dependencies: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {
        "id": row.id,
        "filename": row.original_filename,
        "mime_type": row.mime_type,
        "category": row.category,
        "size_bytes": int(row.size_bytes),
        "source_context": row.source_context,
        "chat_session_id": row.chat_session_id,
        "book_id": row.book_id,
        "status": row.status,
        "preview_url": f"/api/v1/account/storage/files/{row.id}/content",
        "download_url": f"/api/v1/account/storage/files/{row.id}/content?download=1",
        "dependencies": dependencies or [],
        "created_at": created.isoformat(),
    }


def serialize_session(
    row: UserSession,
    *,
    current_nonce: str | None = None,
) -> dict[str, object]:
    def _iso(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return (dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)).isoformat()

    now = datetime.now(timezone.utc)
    expires = row.expires_at if row.expires_at.tzinfo is not None else row.expires_at.replace(tzinfo=timezone.utc)
    is_current = bool(current_nonce and row.token_nonce == current_nonce)
    is_active = row.revoked_at is None and expires > now
    return {
        "id": row.id,
        "is_current": is_current,
        "is_active": is_active,
        "user_agent": row.user_agent or "مرورگر ناشناس",
        "ip_address": row.ip_address or "—",
        "created_at": _iso(row.created_at),
        "last_seen_at": _iso(row.last_seen_at),
        "expires_at": _iso(row.expires_at),
        "revoked_at": _iso(row.revoked_at),
    }
