"""Capability Registry & Feature Flags (Phase 2).

The registry is the single source of truth for which learning features exist,
whether they are enabled, and which roles/plans may use them. The student menu
is rendered from ``GET /api/v1/capabilities/me`` and every feature endpoint
re-checks the registry server-side via :func:`require_capability_enabled`.

Seeding is idempotent: existing rows are left untouched so admin edits survive
restarts.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.capabilities import Capability

logger = logging.getLogger(__name__)

# Roles recognised by the RBAC layer (see app.services.rbac).
KNOWN_ROLES = ("admin", "teacher", "student", "guardian")

# Seed catalogue: key -> (title_fa, description_fa, icon, is_enabled,
# default_route_key, sort_order). `flashcards` ships enabled from Phase 3 (admins can disable it).
SEED_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "key": "chat",
        "title_fa": "معلم خصوصی",
        "description_fa": "پرسش و پاسخ گام‌به‌گام بر اساس کتاب‌های درسی رسمی با ارجاع به فصل و صفحهٔ چاپی.",
        "icon": "BookOpen",
        "is_enabled": True,
        "default_route_key": "chat",
        "sort_order": 1,
    },
    {
        "key": "solve",
        "title_fa": "حل تمرین",
        "description_fa": "حل مرحله‌به‌مرحلهٔ تمرین‌ها با داده‌ها، رابطهٔ مناسب و پاسخ نهایی.",
        "icon": "Calculator",
        "is_enabled": True,
        "default_route_key": "solve",
        "sort_order": 2,
    },
    {
        "key": "quiz",
        "title_fa": "آزمون و سؤال",
        "description_fa": "طراحی سؤال و آزمون واقعی با زمان‌بندی و کارنامه، فقط از منابع کتاب درسی.",
        "icon": "GraduationCap",
        "is_enabled": True,
        "default_route_key": "quiz",
        "sort_order": 3,
    },
    {
        "key": "multimodal",
        "title_fa": "پرسش تصویری و صوتی",
        "description_fa": "ارسال عکس از تمرین یا فایل صوتی و دریافت پاسخ بر اساس کتاب درسی.",
        "icon": "ImagePlus",
        "is_enabled": True,
        "default_route_key": "vision_ocr",
        "sort_order": 4,
    },
    {
        "key": "flashcards",
        "title_fa": "فلش‌کارت هوشمند",
        "description_fa": "فلش‌کارت‌های تکرار فاصله‌دار (SM-2) ساخته‌شده از فصل‌های کتاب. در فاز ۳ فعال می‌شود.",
        "icon": "Layers",
        "is_enabled": True,
        "default_route_key": "flashcards",
        "sort_order": 5,
    },
    {
        "key": "immersive_reader",
        "title_fa": "مطالعهٔ غوطه‌ور کتاب",
        "description_fa": "کتاب درسی صفحه‌به‌صفحه کنار معلم مستند؛ کلیک روی ارجاع، پرش مستقیم به صفحهٔ چاپی.",
        "icon": "BookOpen",
        "is_enabled": True,
        "default_route_key": "immersive_reader",
        "sort_order": 6,
    },
    {
        "key": "deep_solve",
        "title_fa": "حل گام‌به‌گام تعاملی",
        "description_fa": "شکستن مسئله به گام‌ها با نردبان راهنمایی؛ جواب نهایی فقط با درخواست صریح.",
        "icon": "Route",
        "is_enabled": True,
        "default_route_key": "deep_solve",
        "sort_order": 7,
    },
    {
        "key": "quiz_validator",
        "title_fa": "بازبینی سؤال آزمون",
        "description_fa": "مرحلهٔ دوم تولید آزمون: بررسی صحت علمی، LaTeX و یکتایی پاسخ بر اساس کتاب درسی.",
        "icon": "ShieldCheck",
        "is_enabled": True,
        "default_route_key": "quiz_validator",
        "sort_order": 10,
    },
    {
        "key": "mistake_bank",
        "title_fa": "بانک اشتباهات",
        "description_fa": "سؤال‌های غلط یا نزده در آزمون‌ها، تمرین مجدد و تبدیل به فلش‌کارت.",
        "icon": "ListX",
        "is_enabled": True,
        "default_route_key": None,
        "sort_order": 8,
    },
    {
        "key": "mastery_path",
        "title_fa": "مسیر تسلط فصل‌به‌فصل",
        "description_fa": "امتیاز تسلط هر فصل از آزمون، فلش‌کارت و حل تمرین؛ باز شدن مرحله‌ای فصل‌ها.",
        "icon": "Milestone",
        "is_enabled": True,
        "default_route_key": None,
        "sort_order": 9,
    },
    {
        "key": "learning_notebook",
        "title_fa": "دفترچه یادداشت هوشمند",
        "description_fa": "یادداشت Markdown و فرمول با ویرایش هوشمند متن انتخاب‌شده؛ پیشنهاد AI فقط با تأیید شما اعمال می‌شود.",
        "icon": "NotebookPen",
        "is_enabled": True,
        "default_route_key": "learning_notebook",
        "sort_order": 11,
    },
    {
        "key": "web_visualize",
        "title_fa": "نمودار و تصویر تعاملی",
        "description_fa": "نقشهٔ مفاهیم، فلوچارت، خط زمانی، جدول مقایسه و SVG امن؛ همه پاک‌سازی‌شده قبل از نمایش.",
        "icon": "Network",
        "is_enabled": True,
        "default_route_key": "web_visualize",
        "sort_order": 12,
    },
    {
        "key": "living_book",
        "title_fa": "کتابچهٔ شب امتحان",
        "description_fa": "مرور یکپارچهٔ هر فصل: خلاصه، نکات کلیدی، نمودار، آزمونک اعتبارسنجی‌شده و فلش‌کارت.",
        "icon": "BookMarked",
        "is_enabled": True,
        "default_route_key": "living_book",
        "sort_order": 13,
    },
    {
        "key": "audio_tts",
        "title_fa": "روخوانی صوتی",
        "description_fa": "پخش صوتی متن انتخاب‌شده و خلاصهٔ صوتی فصل؛ هر متن یک‌بار ساخته و کش می‌شود.",
        "icon": "Volume2",
        "is_enabled": True,
        "default_route_key": "audio_tts",
        "sort_order": 14,
    },
    {
        "key": "audio_podcast",
        "title_fa": "پادکست آموزشی",
        "description_fa": "ساخت گفت‌وگوی صوتی آموزشی از فصل کتاب با دو گویندهٔ هوش مصنوعی، متن و پخش‌کنندهٔ اختصاصی.",
        "icon": "Podcast",
        "is_enabled": True,
        "default_route_key": "audio_podcast_tts",
        "sort_order": 15,
        "config_json": {
            "host_a_voice": "",
            "host_b_voice": "",
            "narrator_voice": "",
            "max_source_chars": 12000,
            "max_concurrent_jobs": 2,
            "supported_languages": ["fa"],
            "length_minutes_short": "3-5",
            "length_minutes_standard": "8-12",
            "length_minutes_long": "15-20",
        },
    },
)


def serialize_capability(capability: Capability) -> dict[str, Any]:
    return {
        "key": capability.key,
        "title_fa": capability.title_fa,
        "description_fa": capability.description_fa,
        "icon": capability.icon,
        "is_enabled": bool(capability.is_enabled),
        "allowed_roles": list(capability.allowed_roles_json or []),
        "allowed_plans": list(capability.allowed_plans_json or []),
        "default_route_key": capability.default_route_key,
        "config": dict(capability.config_json or {}),
        "sort_order": capability.sort_order,
    }


async def seed_capabilities(session: AsyncSession) -> None:
    """Insert the seed catalogue; never overwrite admin edits."""
    for spec in SEED_CAPABILITIES:
        existing = await session.get(Capability, spec["key"])
        if existing is not None:
            continue
        session.add(
            Capability(
                key=spec["key"],
                title_fa=spec["title_fa"],
                description_fa=spec["description_fa"],
                icon=spec["icon"],
                is_enabled=spec["is_enabled"],
                allowed_roles_json=[],
                allowed_plans_json=[],
                default_route_key=spec["default_route_key"],
                config_json=dict(spec.get("config_json") or {}),
                sort_order=spec["sort_order"],
            )
        )
    await session.flush()


async def get_capability(session: AsyncSession, key: str) -> Capability | None:
    return await session.get(Capability, key)


async def list_capabilities(session: AsyncSession) -> list[Capability]:
    rows = await session.scalars(
        select(Capability).order_by(Capability.sort_order.asc(), Capability.key.asc())
    )
    return list(rows)


def is_capability_allowed(
    capability: Capability, *, role: str | None, plan_code: str | None
) -> bool:
    """Pure allow-list check: empty allow-list means "everyone"."""
    if not capability.is_enabled:
        return False
    roles = list(capability.allowed_roles_json or [])
    if roles and role not in roles:
        return False
    plans = list(capability.allowed_plans_json or [])
    if plans and plan_code not in plans:
        return False
    return True


def _user_role(user: Any) -> str | None:
    if user is None:
        return None
    role = getattr(user, "role", None)
    return str(role) if role else "student"


def _user_plan_code(user: Any) -> str | None:
    if user is None:
        return None
    plan_code = getattr(user, "plan_code", None)
    if plan_code:
        return str(plan_code)
    plan = getattr(user, "plan", None)
    if plan is not None:
        code = getattr(plan, "code", None)
        if code:
            return str(code)
    plan_id = getattr(user, "plan_id", None)
    return str(plan_id) if plan_id is not None else None


async def capabilities_for_user(
    session: AsyncSession, user: Any
) -> list[Capability]:
    """Enabled capabilities visible to this user (role + plan filtered)."""
    role = _user_role(user)
    plan_code = _user_plan_code(user)
    all_caps = await list_capabilities(session)
    return [
        cap
        for cap in all_caps
        if is_capability_allowed(cap, role=role, plan_code=plan_code)
    ]


async def require_capability_enabled(
    session: AsyncSession, key: str, user: Any = None
) -> Capability:
    """Raise 403 when the capability is unknown, disabled, or not allowed."""
    capability = await get_capability(session, key)
    if capability is None:
        raise HTTPException(status_code=404, detail=f"قابلیت «{key}» یافت نشد.")
    role = _user_role(user)
    plan_code = _user_plan_code(user)
    if not is_capability_allowed(capability, role=role, plan_code=plan_code):
        raise HTTPException(
            status_code=403,
            detail="این قابلیت در حال حاضر برای حساب شما فعال نیست.",
        )
    return capability


async def check_capability_access(
    session: AsyncSession, key: str, user: Any = None
) -> Capability | None:
    """Gate a feature endpoint against the registry (fail-open pre-seed).

    When the capability row exists, disabled / not-allowed states raise 403.
    When the row is absent (registry not seeded yet — e.g. legacy test DBs),
    the call is allowed so existing behaviour never breaks.
    """
    capability = await get_capability(session, key)
    if capability is None:
        return None
    role = _user_role(user)
    plan_code = _user_plan_code(user)
    if not is_capability_allowed(capability, role=role, plan_code=plan_code):
        raise HTTPException(
            status_code=403,
            detail="این قابلیت در حال حاضر برای حساب شما فعال نیست.",
        )
    return capability
