"""Admin user & role administration (`/api/v1/admin/users*`, hotfix 2026-11-22).

Every route is guarded by `require_admin` (legacy shared-password console **or** an
`admin`/`super_admin` user session). Least-privilege decisions and audit logging live in
`app.services.admin_user_service`; this module only translates HTTP.

Existing endpoints (`GET /api/v1/admin/users`, `PUT /api/v1/admin/users/{id}`) stay in
`app.api.admin` and keep their behaviour; the richer endpoints below are additive.
Sensitive operations (delete, create, privilege changes) require a fresh password proof
through the `X-Reauth-Password` header.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.db.session import get_session
from app.services import admin_user_service as service
from app.services import permissions
from app.services.admin_user_service import actor_for_request, require_reauth
from app.services.auth_billing_service import normalize_iranian_phone, utc_iso

router = APIRouter(
    prefix="/api/v1/admin/users",
    tags=["admin-users"],
    dependencies=[Depends(require_admin)],
)

RoleLiteral = Literal["student", "guardian", "teacher", "moderator", "admin", "super_admin"]
StatusLiteral = Literal["active", "inactive", "deleted", "all"]


class CreateUserBody(BaseModel):
    # Academic placement (grade/major/track/field) is student-owned self-service
    # data; admins can view it but can no longer set it here.
    model_config = ConfigDict(extra="forbid")

    model_config = ConfigDict(extra="forbid")

    phone_number: str = Field(min_length=9, max_length=24)
    password: str | None = Field(default=None, min_length=1, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=255)
    role: RoleLiteral = "student"
    is_active: bool = True


class UpdateProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=120)
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, min_length=9, max_length=24)


class RoleBody(BaseModel):
    """Role and plan assignment. Academic placement is student-owned and is
    intentionally absent here: admins cannot edit grade/major anymore."""

    model_config = ConfigDict(extra="forbid")

    role: RoleLiteral
    plan_id: int | None = Field(default=None, gt=0)


class ActivationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=1, max_length=128)
    require_change_on_next_login: bool = True


class DeleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hard_delete: bool = False


class CreditsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: str | None = Field(default=None, min_length=1, max_length=32)
    apply_plan_defaults: bool = False
    tokens_remaining: int | None = Field(default=None, ge=0, le=1_000_000_000)
    add_tokens: int | None = Field(default=None, ge=-1_000_000_000, le=1_000_000_000)
    duration_days: int | None = Field(default=None, ge=1, le=3650)


async def _actor(request: Request, session: AsyncSession):
    return await actor_for_request(request, session)


def _current_actor(request: Request) -> permissions.AdminActor:
    return service.actor_from_request(request)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


@router.get("/roles")
async def list_roles(request: Request, session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    actor = await _actor(request, session)
    return {
        "roles": [
            {
                "code": role,
                "rank": permissions.ROLE_RANKS[role],
                "assignable": permissions.can_assign_role(actor, role),
            }
            for role in permissions.ASSIGNABLE_ROLES
        ],
        "actor": {"role": actor.role, "rank": actor.rank, "legacy": actor.legacy},
    }


@router.get("/audit")
async def list_mutations(
    request: Request,
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _actor(request, session)
    if not permissions.can_read_audit(actor):
        raise HTTPException(status_code=403, detail="دسترسی به تاریخچهٔ مدیریت مجاز نیست.")
    return await service.list_mutations(session, limit=limit)


# NOTE: `GET /api/v1/admin/users` remains the single list endpoint and lives in
# `app.api.admin` (it now delegates to `admin_user_service.list_users`, gaining
# pagination/role/status filters without changing its payload contract).


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_user(
    body: CreateUserBody,
    request: Request,
    x_reauth_password: str | None = Header(default=None, alias="X-Reauth-Password"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _actor(request, session)
    if not permissions.can_create_user_with_role(actor, body.role):
        raise HTTPException(status_code=403, detail="شما اجازهٔ ساخت کاربر با این نقش را ندارید.")
    # Creating staff accounts (or any privileged role) needs a fresh password proof.
    if permissions.role_rank(body.role) >= permissions.ROLE_RANKS["admin"]:
        await require_reauth(
            request, session, actor=actor, password=x_reauth_password, action="ساخت مدیر جدید"
        )
    user = await service.create_user(
        session,
        actor=actor,
        phone_number=body.phone_number,
        password=body.password,
        full_name=body.full_name,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        role=body.role,
        is_active=body.is_active,
    )
    return {"user": service.serialize_admin_user(user)}


# ---------------------------------------------------------------------------
# Detail & sub-resources
# ---------------------------------------------------------------------------


@router.get("/{user_id}")
async def get_user(
    user_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    actor = await _actor(request, session)
    if not permissions.can_read_users(actor):
        raise HTTPException(status_code=403, detail="دسترسی به پروندهٔ کاربران مجاز نیست.")
    return await service.get_user_detail(session, user_id)


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateProfileBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _actor(request, session)
    user, previous_phone = await service.update_user(
        session,
        actor=actor,
        user_id=user_id,
        full_name=body.full_name,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        phone_number=body.phone_number,
        changed_fields=body.model_fields_set,
    )
    return {
        "user": service.serialize_admin_user(user),
        "phone_changed": previous_phone is not None,
        "phone_verified": user.phone_verified_at is not None,
    }


@router.put("/{user_id}/role")
async def update_role(
    user_id: str,
    body: RoleBody,
    request: Request,
    x_reauth_password: str | None = Header(default=None, alias="X-Reauth-Password"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _actor(request, session)
    target = await service.get_user_or_404(session, user_id)
    if not permissions.can_assign_role(actor, body.role, target.role):
        raise HTTPException(status_code=403, detail="تغییر نقش این کاربر مجاز نیست.")
    if permissions.requires_reauth_for_role_change(actor, body.role) or permissions.is_admin_role(
        target.role
    ):
        await require_reauth(
            request, session, actor=actor, password=x_reauth_password, action="تغییر نقش"
        )
    user = await service.set_role(
        session,
        actor=actor,
        user_id=user_id,
        new_role=body.role,
        keep_session_nonce=getattr(request.state, "user_session_nonce", None),
    )
    profile_changed = False
    # Academic placement is intentionally NOT editable here (student self-service
    # policy): no grade/major write path exists on the role endpoint anymore.
    if body.plan_id is not None:
        user.plan_id = body.plan_id
        profile_changed = True
    if profile_changed:
        await session.commit()
        await session.refresh(user)
    serialized = service.serialize_admin_user(user)
    return {"user": serialized, "sessions_revoked": True}


@router.put("/{user_id}/activation")
async def update_activation(
    user_id: str,
    body: ActivationBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _actor(request, session)
    user, revoked = await service.set_activation(
        session, actor=actor, user_id=user_id, active=body.is_active
    )
    return {
        "user": service.serialize_admin_user(user),
        "sessions_revoked": revoked,
    }


@router.post("/{user_id}/password")
async def reset_password(
    user_id: str,
    body: PasswordBody,
    request: Request,
    x_reauth_password: str | None = Header(default=None, alias="X-Reauth-Password"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _actor(request, session)
    target = await service.get_user_or_404(session, user_id)
    await require_reauth(
        request, session, actor=actor, password=x_reauth_password, action="تغییر رمز کاربر"
    )
    del target
    user, revoked = await service.reset_password(
        session,
        actor=actor,
        user_id=user_id,
        new_password=body.new_password,
        require_change_on_next_login=body.require_change_on_next_login,
    )
    return {
        "user": service.serialize_admin_user(user),
        "sessions_revoked": revoked,
        "must_change_on_next_login": body.require_change_on_next_login,
    }


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    hard_delete: bool = Query(default=False),
    x_reauth_password: str | None = Header(default=None, alias="X-Reauth-Password"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _actor(request, session)
    await require_reauth(request, session, actor=actor, password=x_reauth_password, action="حذف حساب")
    return await service.delete_user(
        session, actor=actor, user_id=user_id, hard_delete=hard_delete
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.get("/{user_id}/sessions")
async def list_sessions(
    user_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    actor = await _actor(request, session)
    if not permissions.can_read_users(actor):
        raise HTTPException(status_code=403, detail="دسترسی به نشست‌های کاربران مجاز نیست.")
    await service.get_user_or_404(session, user_id)
    result = await service.list_sessions(session, user_id)
    await session.commit()
    return result


@router.delete("/{user_id}/sessions/{session_id}")
async def revoke_session(
    user_id: str, session_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    actor = await _actor(request, session)
    return await service.revoke_session(
        session, actor=actor, user_id=user_id, session_id=session_id
    )


@router.post("/{user_id}/sessions/revoke-all")
async def revoke_all_sessions(
    user_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    actor = await _actor(request, session)
    revoked = await service.revoke_all_sessions(session, actor=actor, user_id=user_id)
    return {"user_id": user_id, "revoked_count": revoked}


# ---------------------------------------------------------------------------
# Quotas / credits / audit
# ---------------------------------------------------------------------------


@router.get("/{user_id}/credits")
async def get_credits(
    user_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    actor = await _actor(request, session)
    if not permissions.can_read_users(actor):
        raise HTTPException(status_code=403, detail="دسترسی به سهمیهٔ کاربران مجاز نیست.")
    user = await service.get_user_or_404(session, user_id)
    return {
        "user_id": user_id,
        "plan_code": user.plan_code,
        "plan_title": user.plan_title,
        "tokens_total": user.tokens_total,
        "tokens_remaining": user.tokens_remaining,
        "tokens_used_total": user.tokens_used_total,
        "plan_expires_at": utc_iso(user.plan_expires_at),
    }


@router.put("/{user_id}/credits")
async def update_credits(
    user_id: str,
    body: CreditsBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _actor(request, session)
    user = await service.adjust_credits(
        session,
        actor=actor,
        user_id=user_id,
        plan_code=body.plan_code,
        apply_plan_defaults=body.apply_plan_defaults,
        tokens_remaining=body.tokens_remaining,
        add_tokens=body.add_tokens,
        duration_days=body.duration_days,
    )
    return {"user": service.serialize_admin_user(user)}


@router.get("/{user_id}/audit")
async def get_user_audit(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _actor(request, session)
    if not permissions.can_read_audit(actor):
        raise HTTPException(status_code=403, detail="دسترسی به تاریخچهٔ کاربران مجاز نیست.")
    await service.get_user_or_404(session, user_id)
    return await service.list_user_audit(session, user_id, limit=limit)


@router.post("/preview-normalize")
async def preview_normalize(body: dict[str, Any]) -> dict[str, str]:
    """Helper for the admin form: show the canonical 09XXXXXXXXX form of a typed number."""
    raw = str(body.get("phone_number") or "")
    try:
        return {"phone_number": normalize_iranian_phone(raw)}
    except ValueError:
        return {"phone_number": ""}
