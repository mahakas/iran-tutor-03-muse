"""Administrative user management (hotfix 2026-11-22).

Every function in this module is called *after* `require_admin` has authenticated the
request; the module re-checks least-privilege rules through `services.permissions` so a
router bug can never turn into a privilege escalation. Each mutation writes one
`AdminActionLog` row inside the same transaction as the data change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Literal
from uuid import uuid4

from fastapi import HTTPException, Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import client_ip, constant_time_equal
from app.core.config import get_settings
from app.core.passwords import hash_password, password_policy_error, verify_password
from app.models.auth import PaymentTransaction, TokenUsageLog, User, UserFile, UserSession
from app.models.phase5 import AdminActionLog
from app.services.academic_profile_service import serialize_profile as serialize_academic_profile, load_profile as load_academic_profile
from app.services import permissions
from app.services.auth_billing_service import (
    apply_plan_to_user,
    get_or_init_billing_settings,
    get_or_init_plans,
    get_user_today_tokens,
    normalize_iranian_phone,
    serialize_user,
    utc_iso,
)
from app.services.permissions import AdminActor
from app.services.quota_service import get_quota_snapshot
from app.services.rate_limiter import check_rate_limit

logger = logging.getLogger(__name__)

UserStatus = Literal["active", "inactive", "deleted", "all"]


@dataclass(frozen=True)
class UserListQuery:
    q: str | None = None
    role: str | None = None
    status: UserStatus = "all"
    plan: str | None = None
    page: int = 1
    page_size: int = 25


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log(
    session: AsyncSession,
    *,
    actor: AdminActor,
    action: str,
    target: str,
    payload: dict[str, Any],
) -> None:
    session.add(
        AdminActionLog(
            actor=actor.label,
            action=action,
            target=target[:128],
            payload_json=payload,
        )
    )


def serialize_admin_user(user: User, *, today_tokens: int = 0) -> dict[str, object]:
    """Admin view of an account: authentication state plus the shared student fields."""
    payload = serialize_user(user, today_tokens=today_tokens)
    payload.update(
        {
            "has_password": bool(getattr(user, "password_hash", None)),
            "phone_verified_at": utc_iso(getattr(user, "phone_verified_at", None)),
            "last_password_change_at": utc_iso(getattr(user, "last_password_change_at", None)),
            "deleted_at": utc_iso(getattr(user, "deleted_at", None)),
            "is_deleted": getattr(user, "deleted_at", None) is not None,
            "grade_level": getattr(user, "grade_level", None),
            "major": getattr(user, "major", None),
        }
    )
    return payload


async def get_user_or_404(session: AsyncSession, user_id: str, *, include_deleted: bool = True) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    if not include_deleted and user.deleted_at is not None:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    return user


# ---------------------------------------------------------------------------
# Listing & detail
# ---------------------------------------------------------------------------


async def list_users(session: AsyncSession, query: UserListQuery) -> dict[str, object]:
    billing = await get_or_init_billing_settings(session)
    plans = await get_or_init_plans(session)
    plan_storage = {p.code: int(p.storage_quota_bytes) for p in plans}

    conditions = []
    statement = select(User)
    count_statement = select(func.count()).select_from(User)

    if query.status == "active":
        conditions.append(User.is_active.is_(True))
        conditions.append(User.deleted_at.is_(None))
    elif query.status == "inactive":
        conditions.append(User.is_active.is_(False))
        conditions.append(User.deleted_at.is_(None))
    elif query.status == "deleted":
        conditions.append(User.deleted_at.is_not(None))

    if query.role and query.role.strip() and query.role != "all":
        conditions.append(User.role == permissions.normalize_role(query.role.strip()))

    if query.plan and query.plan.strip() and query.plan != "all":
        conditions.append(User.plan_code == query.plan.strip())

    if query.q and query.q.strip():
        term = f"%{query.q.strip()}%"
        normalized_phone_guess = None
        try:
            normalized_phone_guess = normalize_iranian_phone(query.q)
        except ValueError:
            normalized_phone_guess = None
        matchers = [User.full_name.ilike(term), User.phone_number.ilike(term)]
        if normalized_phone_guess:
            matchers.append(User.phone_number == normalized_phone_guess)
        conditions.append(or_(*matchers))

    for condition in conditions:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    total = int(await session.scalar(count_statement) or 0)
    page_size = max(1, min(int(query.page_size), 100))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(query.page), total_pages))

    rows = list(
        (
            await session.scalars(
                statement.order_by(User.created_at.desc(), User.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).all()
    )
    user_ids = [row.id for row in rows]
    today_by_user: dict[str, int] = {}
    if user_ids:
        start_of_day = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_rows = (
            await session.execute(
                select(TokenUsageLog.user_id, func.coalesce(func.sum(TokenUsageLog.total_tokens), 0))
                .where(TokenUsageLog.created_at >= start_of_day, TokenUsageLog.user_id.in_(user_ids))
                .group_by(TokenUsageLog.user_id)
            )
        ).all()
        today_by_user = {uid: int(total) for uid, total in today_rows}

    await session.commit()

    items = []
    for row in rows:
        item = serialize_user(
            row,
            today_tokens=today_by_user.get(row.id, 0),
            token_price_per_1k_toman=billing.token_price_per_1k_toman,
            storage_quota_bytes=(
                int(billing.starter_storage_bytes)
                if row.plan_code == "trial"
                else plan_storage.get(row.plan_code, int(billing.starter_storage_bytes))
            ),
        )
        item.update(
            {
                "has_password": bool(row.password_hash),
                "phone_verified_at": utc_iso(row.phone_verified_at),
                "deleted_at": utc_iso(row.deleted_at),
                "is_deleted": row.deleted_at is not None,
                "grade_level": row.grade_level,
                "major": row.major,
            }
        )
        items.append(item)

    total_tokens_used = int(
        await session.scalar(select(func.coalesce(func.sum(User.tokens_used_total), 0))) or 0
    )
    total_revenue_toman = int(
        await session.scalar(
            select(func.coalesce(func.sum(PaymentTransaction.amount_toman), 0)).where(
                PaymentTransaction.status == "paid",
                PaymentTransaction.provider != "admin_grant",
            )
        )
        or 0
    )
    paid_users = int(
        await session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.plan_code.in_(["normal", "pro", "vip"]),
                User.deleted_at.is_(None),
            )
        )
        or 0
    )

    return {
        "users": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
        "filters": {
            "q": query.q or "",
            "role": query.role or "all",
            "status": query.status,
            "plan": query.plan or "all",
        },
        "summary": {
            # Legacy keys (kept for the existing billing/dashboard payload contract).
            "paid_users": paid_users,
            "total_tokens_used": total_tokens_used,
            "total_used_value_toman": round(
                total_tokens_used * billing.token_price_per_1k_toman / 1000
            ),
            "total_revenue_toman": total_revenue_toman,
            "total_users": int(
                await session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.deleted_at.is_(None))
                )
                or 0
            ),
            "active_users": int(
                await session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.deleted_at.is_(None), User.is_active.is_(True))
                )
                or 0
            ),
            "deleted_users": int(
                await session.scalar(
                    select(func.count()).select_from(User).where(User.deleted_at.is_not(None))
                )
                or 0
            ),
            "roles": await _role_counts(session),
        },
    }


async def _role_counts(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            select(User.role, func.count())
            .where(User.deleted_at.is_(None), User.is_active.is_(True))
            .group_by(User.role)
        )
    ).all()
    counts = {role: 0 for role in permissions.ROLE_RANKS}
    for role, count in rows:
        counts[permissions.normalize_role(role)] = counts.get(permissions.normalize_role(role), 0) + int(count)
    return counts


async def get_user_detail(session: AsyncSession, user_id: str) -> dict[str, object]:
    user = await get_user_or_404(session, user_id)
    billing = await get_or_init_billing_settings(session)
    today_tokens = await get_user_today_tokens(session, user.id)
    sessions = await list_sessions(session, user_id)
    audit = await list_user_audit(session, user_id, limit=20)
    usage_today = today_tokens
    lifetime_tokens = int(
        await session.scalar(
            select(func.coalesce(func.sum(TokenUsageLog.total_tokens), 0)).where(
                TokenUsageLog.user_id == user_id
            )
        )
        or 0
    )
    payments = int(
        await session.scalar(
            select(func.count())
            .select_from(PaymentTransaction)
            .where(PaymentTransaction.user_id == user_id)
        )
        or 0
    )
    files = int(
        await session.scalar(
            select(func.count()).select_from(UserFile).where(UserFile.user_id == user_id)
        )
        or 0
    )
    # Read-only academic placement (Phase: Iran Education Catalog 1405-1406).
    # Display/reporting/support only — this payload intentionally carries no
    # approval action and no admin-editable grade field.
    academic_profile = await serialize_academic_profile(session, await load_academic_profile(session, user))
    await session.commit()
    return {
        "user": serialize_admin_user(user, today_tokens=usage_today),
        "academic_profile": academic_profile,
        "usage": {"tokens_today": usage_today, "tokens_lifetime": lifetime_tokens},
        "history": {"payments": payments, "files": files, "sessions": len(sessions["sessions"])},
        "sessions": sessions["sessions"],
        "audit": audit["entries"],
        "pricing": {"token_price_per_1k_toman": billing.token_price_per_1k_toman},
        "permissions": {
            "role": permissions.normalize_role(user.role),
            "role_rank": permissions.role_rank(user.role),
        },
    }


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------


async def create_user(
    session: AsyncSession,
    *,
    actor: AdminActor,
    phone_number: str,
    password: str | None,
    full_name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    role: str = "student",
    is_active: bool = True,
) -> User:
    target_role = permissions.normalize_role(role)
    if not permissions.can_create_user_with_role(actor, target_role):
        raise HTTPException(status_code=403, detail="شما اجازهٔ ساخت کاربر با این نقش را ندارید.")

    try:
        phone = normalize_iranian_phone(phone_number)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    existing = await session.scalar(select(User).where(User.phone_number == phone))
    if existing is not None:
        raise HTTPException(status_code=409, detail="این شماره موبایل قبلاً ثبت شده است.")

    settings = get_settings()
    if password:
        error = password_policy_error(password, min_length=settings.password_min_length)
        if error:
            raise HTTPException(status_code=422, detail=error)

    now = _utcnow()
    billing = await get_or_init_billing_settings(session)
    user = User(
        phone_number=phone,
        full_name=(full_name or "").strip()[:120] or None,
        first_name=(first_name or "").strip()[:80] or None,
        last_name=(last_name or "").strip()[:80] or None,
        email=(email or "").strip()[:255] or None,
        role=target_role,
        is_active=is_active,
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
    if password:
        user.password_hash = hash_password(password)
        user.last_password_change_at = now
        user.phone_verified_at = now  # admin-created credentials are verified out of band
    session.add(user)
    _log(
        session,
        actor=actor,
        action="user.create",
        target=f"user:{phone}",
        payload={"role": target_role, "is_active": is_active, "has_password": bool(password)},
    )
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="این شماره موبایل قبلاً ثبت شده است.") from error
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession,
    *,
    actor: AdminActor,
    user_id: str,
    full_name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    changed_fields: set[str] | None = None,
) -> tuple[User, str | None]:
    """Edit profile fields. Returns (user, previous_phone_if_changed)."""
    user = await get_user_or_404(session, user_id)
    if not permissions.can_manage_user(actor, user.role):
        raise HTTPException(status_code=403, detail="اجازهٔ ویرایش این حساب را ندارید.")
    fields = changed_fields or {
        name
        for name, value in {
            "full_name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone_number": phone_number,
        }.items()
        if value is not None
    }

    now = _utcnow()
    previous_phone: str | None = None
    changes: dict[str, object] = {}

    if "phone_number" in fields and phone_number:
        try:
            new_phone = normalize_iranian_phone(phone_number)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if new_phone != user.phone_number:
            clash = await session.scalar(select(User).where(User.phone_number == new_phone))
            if clash is not None and clash.id != user.id:
                raise HTTPException(status_code=409, detail="این شماره موبایل قبلاً ثبت شده است.")
            previous_phone = user.phone_number
            changes["phone_number"] = {"from": previous_phone, "to": new_phone}
            user.phone_number = new_phone
            # A changed number must be re-verified by the owner, not assumed.
            user.phone_verified_at = None

    if "first_name" in fields:
        user.first_name = (first_name or "").strip()[:80] or None
        changes["first_name"] = user.first_name
    if "last_name" in fields:
        user.last_name = (last_name or "").strip()[:80] or None
        changes["last_name"] = user.last_name
    if "full_name" in fields:
        user.full_name = (full_name or "").strip()[:120] or None
        changes["full_name"] = user.full_name
    elif "first_name" in fields or "last_name" in fields:
        composed = " ".join(p for p in [user.first_name or "", user.last_name or ""] if p).strip()
        if composed:
            user.full_name = composed[:120]
    if "email" in fields:
        user.email = (email or "").strip()[:255] or None
        changes["email"] = user.email
    # Academic placement (grade_level/major) is student-owned self-service data:
    # the admin edit path is closed and stays out of the audit change set.

    user.updated_at = now
    _log(
        session,
        actor=actor,
        action="user.update",
        target=f"user:{user.id}",
        payload={"changes": changes},
    )
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="این شماره موبایل قبلاً ثبت شده است.") from error
    await session.refresh(user)
    return user, previous_phone


async def set_role(
    session: AsyncSession,
    *,
    actor: AdminActor,
    user_id: str,
    new_role: str,
    keep_session_nonce: str | None = None,
) -> User:
    user = await get_user_or_404(session, user_id)
    normalized = permissions.normalize_role(new_role)
    if normalized not in permissions.ROLE_RANKS:
        raise HTTPException(status_code=422, detail="نقش انتخاب‌شده معتبر نیست.")
    if permissions.normalize_role(user.role) == normalized:
        return user
    if not permissions.can_assign_role(actor, normalized, user.role):
        raise HTTPException(status_code=403, detail="تغییر نقش این کاربر مجاز نیست.")
    await _ensure_not_last_super_admin(session, user, action="تغییر نقش")

    previous = user.role
    user.role = normalized
    user.updated_at = _utcnow()
    # A privilege change must not keep pre-change sessions alive. The actor's own session
    # is kept when promoting/demoting itself so the console does not lock out mid-flight.
    keep_nonce = keep_session_nonce if (actor.user_id and actor.user_id == user.id) else None
    if keep_nonce:
        await session.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
                UserSession.token_nonce != keep_nonce,
            )
            .values(revoked_at=user.updated_at)
        )
    else:
        await _revoke_all_sessions(session, user.id)
    _log(
        session,
        actor=actor,
        action="user.role_change",
        target=f"user:{user.id}",
        payload={"from": previous, "to": normalized},
    )
    await session.commit()
    await session.refresh(user)
    return user


async def set_activation(
    session: AsyncSession,
    *,
    actor: AdminActor,
    user_id: str,
    active: bool,
) -> tuple[User, int]:
    user = await get_user_or_404(session, user_id)
    if not permissions.can_manage_user(actor, user.role):
        raise HTTPException(status_code=403, detail="اجازهٔ تغییر وضعیت این حساب را ندارید.")
    if not active:
        await _ensure_not_last_super_admin(session, user, action="غیرفعال‌سازی")
        if actor.user_id and actor.user_id == user.id:
            raise HTTPException(status_code=409, detail="نمی‌توانید حساب خودتان را غیرفعال کنید.")
    revoked = 0
    if user.is_active != active:
        user.is_active = active
        user.updated_at = _utcnow()
        if not active:
            revoked = await _revoke_all_sessions(session, user.id)
        _log(
            session,
            actor=actor,
            action="user.activate" if active else "user.deactivate",
            target=f"user:{user.id}",
            payload={"revoked_sessions": revoked},
        )
        await session.commit()
        await session.refresh(user)
    return user, revoked


async def reset_password(
    session: AsyncSession,
    *,
    actor: AdminActor,
    user_id: str,
    new_password: str,
    require_change_on_next_login: bool = True,
) -> tuple[User, int]:
    user = await get_user_or_404(session, user_id)
    if not permissions.can_reset_password(actor, user.role):
        raise HTTPException(status_code=403, detail="اجازهٔ تغییر رمز این حساب را ندارید.")
    settings = get_settings()
    error = password_policy_error(new_password, min_length=settings.password_min_length)
    if error:
        raise HTTPException(status_code=422, detail=error)

    now = _utcnow()
    user.password_hash = hash_password(new_password)
    user.last_password_change_at = now
    user.updated_at = now
    if user.phone_verified_at is None:
        user.phone_verified_at = now
    revoked = await _revoke_all_sessions(session, user.id)
    _log(
        session,
        actor=actor,
        action="user.password_reset",
        target=f"user:{user.id}",
        payload={
            "revoked_sessions": revoked,
            "must_change": bool(require_change_on_next_login),
        },
    )
    await session.commit()
    await session.refresh(user)
    return user, revoked


async def delete_user(
    session: AsyncSession,
    *,
    actor: AdminActor,
    user_id: str,
    hard_delete: bool = False,
) -> dict[str, object]:
    """Delete an account.

    Financial/audit rows reference `users.id`, so a hard delete is refused when any
    history exists (integrity + legal retention). Soft delete keeps rows, clears the
    credentials, and blocks every future login.
    """
    user = await get_user_or_404(session, user_id)
    if not permissions.can_delete_user(actor, user.role):
        raise HTTPException(status_code=403, detail="اجازهٔ حذف این حساب را ندارید.")
    if actor.user_id and actor.user_id == user.id:
        raise HTTPException(status_code=409, detail="نمی‌توانید حساب خودتان را حذف کنید.")
    await _ensure_not_last_super_admin(session, user, action="حذف")

    history = {
        "payments": int(
            await session.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(PaymentTransaction.user_id == user_id)
            )
            or 0
        ),
        "usage_logs": int(
            await session.scalar(
                select(func.count()).select_from(TokenUsageLog).where(TokenUsageLog.user_id == user_id)
            )
            or 0
        ),
        "files": int(
            await session.scalar(
                select(func.count()).select_from(UserFile).where(UserFile.user_id == user_id)
            )
            or 0
        ),
    }
    has_history = any(history.values())
    now = _utcnow()
    revoked = await _revoke_all_sessions(session, user.id)

    if hard_delete and not has_history:
        _log(
            session,
            actor=actor,
            action="user.delete",
            target=f"user:{user.id}",
            payload={"mode": "hard", "phone": user.phone_number, "history": history},
        )
        await session.delete(user)
        await session.commit()
        return {"deleted": True, "mode": "hard", "user_id": user_id, "revoked_sessions": revoked}

    if user.deleted_at is None:
        user.deleted_at = now
        user.deleted_by = actor.label
        user.is_active = False
        user.password_hash = None
        user.updated_at = now
    _log(
        session,
        actor=actor,
        action="user.delete",
        target=f"user:{user.id}",
        payload={
            "mode": "soft" if hard_delete else "soft_requested",
            "phone": user.phone_number,
            "history": history,
            "hard_delete_denied": bool(hard_delete and has_history),
            "revoked_sessions": revoked,
        },
    )
    await session.commit()
    await session.refresh(user)
    return {
        "deleted": True,
        "mode": "soft",
        "user_id": user_id,
        "revoked_sessions": revoked,
        "retained_history": history,
        "hard_delete_denied": bool(hard_delete and has_history),
    }


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


async def list_sessions(session: AsyncSession, user_id: str) -> dict[str, object]:
    now = _utcnow()
    rows = (
        await session.scalars(
            select(UserSession)
            .where(UserSession.user_id == user_id)
            .order_by(UserSession.created_at.desc())
            .limit(50)
        )
    ).all()
    items = []
    for row in rows:
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        items.append(
            {
                "id": row.id,
                "user_agent": row.user_agent,
                "ip_address": row.ip_address,
                "is_active": row.revoked_at is None and expires > now,
                "last_seen_at": utc_iso(row.last_seen_at),
                "expires_at": utc_iso(row.expires_at),
                "revoked_at": utc_iso(row.revoked_at),
                "created_at": utc_iso(row.created_at),
            }
        )
    return {"user_id": user_id, "sessions": items}


async def revoke_session(
    session: AsyncSession, *, actor: AdminActor, user_id: str, session_id: str
) -> dict[str, object]:
    user = await get_user_or_404(session, user_id)
    if not permissions.can_manage_sessions(actor, user.role):
        raise HTTPException(status_code=403, detail="اجازهٔ مدیریت نشست‌های این حساب را ندارید.")
    row = await session.scalar(
        select(UserSession).where(UserSession.id == session_id, UserSession.user_id == user_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="نشست مورد نظر یافت نشد.")
    if row.revoked_at is None:
        row.revoked_at = _utcnow()
        _log(
            session,
            actor=actor,
            action="session.revoke",
            target=f"user:{user_id}",
            payload={"session_id": session_id},
        )
        await session.commit()
    return {"revoked": True, "session_id": session_id}


async def _revoke_all_sessions(session: AsyncSession, user_id: str) -> int:
    result = await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )
    return int(result.rowcount or 0)


async def revoke_all_sessions(session: AsyncSession, *, actor: AdminActor, user_id: str) -> int:
    user = await get_user_or_404(session, user_id)
    if not permissions.can_manage_sessions(actor, user.role):
        raise HTTPException(status_code=403, detail="اجازهٔ مدیریت نشست‌های این حساب را ندارید.")
    revoked = await _revoke_all_sessions(session, user_id)
    _log(
        session,
        actor=actor,
        action="session.revoke_all",
        target=f"user:{user_id}",
        payload={"revoked": revoked},
    )
    await session.commit()
    return revoked


# ---------------------------------------------------------------------------
# Quotas / credits
# ---------------------------------------------------------------------------


async def user_quota(session: AsyncSession, user_id: str) -> dict[str, object]:
    await get_user_or_404(session, user_id)
    snapshot = await get_quota_snapshot(session, user_id=user_id)
    await session.commit()
    return {"user_id": user_id, "quota": snapshot}


async def adjust_credits(
    session: AsyncSession,
    *,
    actor: AdminActor,
    user_id: str,
    plan_code: str | None = None,
    apply_plan_defaults: bool = False,
    tokens_remaining: int | None = None,
    add_tokens: int | None = None,
    duration_days: int | None = None,
) -> User:
    user = await get_user_or_404(session, user_id)
    if not permissions.can_manage_user(actor, user.role):
        raise HTTPException(status_code=403, detail="اجازهٔ تغییر سهمیهٔ این حساب را ندارید.")
    billing = await get_or_init_billing_settings(session)
    plans = await get_or_init_plans(session)
    now = _utcnow()
    before = {
        "plan_code": user.plan_code,
        "tokens_remaining": user.tokens_remaining,
        "plan_expires_at": utc_iso(user.plan_expires_at),
    }

    if plan_code:
        code = plan_code.strip()
        plan = next((p for p in plans if p.code == code), None)
        if code == "trial":
            if apply_plan_defaults:
                apply_plan_to_user(
                    user,
                    plan_code="trial",
                    plan_name="هدیه ثبت‌نام",
                    tokens_granted=billing.starter_tokens,
                    duration_days=duration_days or billing.starter_duration_days,
                    carry_over_valid=False,
                    now=now,
                )
            else:
                user.plan_code = "trial"
                user.plan_title = "هدیه ثبت‌نام"
        elif plan is None:
            raise HTTPException(status_code=404, detail="پلن انتخاب‌شده یافت نشد.")
        elif apply_plan_defaults:
            days = duration_days or plan.duration_days
            apply_plan_to_user(
                user,
                plan_code=plan.code,
                plan_name=plan.name,
                tokens_granted=plan.token_quota,
                duration_days=days,
                carry_over_valid=True,
                now=now,
            )
            session.add(
                PaymentTransaction(
                    user_id=user.id,
                    plan_code=plan.code,
                    plan_name=plan.name,
                    amount_toman=0,
                    tokens_granted=plan.token_quota,
                    duration_days=days,
                    provider="admin_grant",
                    authority=f"ADMIN-{uuid4().hex[:10].upper()}",
                    ref_id="ADMIN",
                    status="paid",
                    paid_at=now,
                )
            )
        else:
            user.plan_code = plan.code
            user.plan_title = plan.name

    if tokens_remaining is not None:
        user.tokens_remaining = max(0, tokens_remaining)
        if user.tokens_total < user.tokens_remaining:
            user.tokens_total = user.tokens_remaining
    if add_tokens:
        user.tokens_remaining = max(0, user.tokens_remaining + add_tokens)
        if add_tokens > 0:
            user.tokens_total = max(user.tokens_total, user.tokens_remaining)
    if duration_days is not None and plan_code is None:
        user.plan_expires_at = now + timedelta(days=duration_days)

    user.updated_at = now
    _log(
        session,
        actor=actor,
        action="user.credits",
        target=f"user:{user.id}",
        payload={
            "before": before,
            "after": {
                "plan_code": user.plan_code,
                "tokens_remaining": user.tokens_remaining,
                "plan_expires_at": utc_iso(user.plan_expires_at),
            },
            "request": {
                "plan_code": plan_code,
                "apply_plan_defaults": apply_plan_defaults,
                "tokens_remaining": tokens_remaining,
                "add_tokens": add_tokens,
                "duration_days": duration_days,
            },
        },
    )
    await session.commit()
    await session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


async def list_user_audit(session: AsyncSession, user_id: str, *, limit: int = 50) -> dict[str, object]:
    rows = (
        await session.scalars(
            select(AdminActionLog)
            .where(AdminActionLog.target == f"user:{user_id}")
            .order_by(AdminActionLog.id.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    return {
        "entries": [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "target": row.target,
                "payload": row.payload_json,
                "created_at": utc_iso(row.created_at),
            }
            for row in rows
        ]
    }


async def list_mutations(session: AsyncSession, *, limit: int = 100) -> dict[str, object]:
    rows = (
        await session.scalars(
            select(AdminActionLog)
            .where(AdminActionLog.action.like("user.%"))
            .order_by(AdminActionLog.id.desc())
            .limit(max(1, min(limit, 300)))
        )
    ).all()
    return {
        "entries": [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "target": row.target,
                "payload": row.payload_json,
                "created_at": utc_iso(row.created_at),
            }
            for row in rows
        ]
    }


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------


async def count_active_super_admins(session: AsyncSession, *, exclude_id: str | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(User)
        .where(
            User.role == "super_admin",
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    if exclude_id:
        stmt = stmt.where(User.id != exclude_id)
    return int(await session.scalar(stmt) or 0)


async def _ensure_not_last_super_admin(session: AsyncSession, user: User, *, action: str) -> None:
    if permissions.normalize_role(user.role) != "super_admin":
        return
    if user.deleted_at is not None or not user.is_active:
        return
    remaining = await count_active_super_admins(session, exclude_id=user.id)
    if remaining == 0:
        raise HTTPException(
            status_code=409,
            detail=f"{action} آخرین مدیر ارشد فعال مجاز نیست؛ ابتدا مدیر ارشد دیگری تعیین کنید.",
        )


# ---------------------------------------------------------------------------
# Re-authentication for sensitive admin operations
# ---------------------------------------------------------------------------

SENSITIVE_ACTION_LIMIT = 20
SENSITIVE_ACTION_WINDOW_SECONDS = 900


async def require_reauth(
    request: Request,
    session: AsyncSession,
    *,
    actor: AdminActor,
    password: str | None,
    action: str,
) -> None:
    """Re-prove the actor's own credentials before a destructive/privileged mutation.

    The legacy shared-password session re-proves `ADMIN_PASSWORD`; a user-backed admin
    session re-proves its own Argon2id password. The grant is per-request (no long-lived
    elevation window), and failed attempts are rate limited.
    """
    decision = await check_rate_limit(
        identity=f"admin_reauth:{client_ip(request)}",
        bucket="admin_reauth",
        limit=SENSITIVE_ACTION_LIMIT,
        window_seconds=SENSITIVE_ACTION_WINDOW_SECONDS,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="تعداد تلاش‌های تأیید هویت بیش از حد مجاز است.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    if not password:
        raise HTTPException(
            status_code=428,
            detail=f"برای «{action}» باید رمز عبور خود را دوباره وارد کنید.",
            headers={"X-Reauth-Required": "1"},
        )

    if actor.legacy:
        settings = get_settings()
        if not constant_time_equal(password, settings.admin_password or ""):
            raise HTTPException(status_code=401, detail="تأیید هویت مدیر ناموفق بود.")
        return

    if not actor.user_id:
        raise HTTPException(status_code=401, detail="تأیید هویت مدیر ناموفق بود.")
    user = await session.get(User, actor.user_id)
    if user is None or not user.is_active or not user.password_hash:
        raise HTTPException(status_code=401, detail="تأیید هویت مدیر ناموفق بود.")
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="تأیید هویت مدیر ناموفق بود.")


def actor_from_request(request: Request) -> AdminActor:
    from app.services.permissions import normalize_role

    identity = getattr(request.state, "admin_identity", None) or {}
    role = normalize_role(identity.get("role") or "admin")
    user_id = identity.get("user_id")
    return AdminActor(role=role, user_id=user_id, legacy=identity.get("kind") == "admin_session")


async def actor_for_request(request: Request, session: AsyncSession) -> AdminActor:
    """Build the actor, widening the legacy shared-password session to `super_admin` only
    when there is exactly zero user-backed super_admin (bootstrap) — otherwise `admin`."""
    actor = actor_from_request(request)
    if not actor.legacy:
        return actor
    supers = await count_active_super_admins(session)
    if supers == 0:
        # Bootstrap state: no super_admin exists yet, so the legacy console can mint one.
        return AdminActor(role="super_admin", user_id=None, legacy=True)
    return actor
