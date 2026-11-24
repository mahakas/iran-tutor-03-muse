"""Capability Registry API (Phase 2).

Student: ``GET /api/v1/capabilities/me`` — the enabled, role/plan-filtered
capability list the student menu is rendered from.

Admin (``/api/v1/admin/capabilities``): full registry CRUD behind
``require_admin`` — toggle feature flags, allow-lists and routing defaults.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.api.rbac_deps import get_current_user
from app.db.session import get_session
from app.models.auth import User
from app.models.capabilities import Capability
from app.services import capability_service

router = APIRouter(prefix="/api/v1/capabilities", tags=["capabilities"])
admin_router = APIRouter(
    prefix="/api/v1/admin/capabilities",
    tags=["admin-capabilities"],
    dependencies=[Depends(require_admin)],
)


@router.get("/me")
async def my_capabilities(
    session: AsyncSession = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Enabled capabilities for the current user (anonymous = public defaults)."""
    caps = await capability_service.capabilities_for_user(session, current_user)
    return {
        "capabilities": [capability_service.serialize_capability(cap) for cap in caps],
        "role": getattr(current_user, "role", None) or "student",
        "plan_code": getattr(current_user, "plan_code", None),
    }


@admin_router.get("")
async def list_admin_capabilities(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    caps = await capability_service.list_capabilities(session)
    return {"capabilities": [capability_service.serialize_capability(cap) for cap in caps]}


@admin_router.get("/{key}")
async def get_admin_capability(
    key: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cap = await capability_service.get_capability(session, key)
    if cap is None:
        raise HTTPException(status_code=404, detail=f"قابلیت «{key}» یافت نشد.")
    return capability_service.serialize_capability(cap)


class CapabilityCreateBody(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    title_fa: str = Field(min_length=1, max_length=120)
    description_fa: str = ""
    icon: str | None = None
    is_enabled: bool = True
    allowed_roles: list[str] = Field(default_factory=list)
    allowed_plans: list[str] = Field(default_factory=list)
    default_route_key: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0


class CapabilityUpdateBody(BaseModel):
    title_fa: str | None = None
    description_fa: str | None = None
    icon: str | None = None
    is_enabled: bool | None = None
    allowed_roles: list[str] | None = None
    allowed_plans: list[str] | None = None
    default_route_key: str | None = None
    config: dict[str, Any] | None = None
    sort_order: int | None = None


def _validate_roles(roles: list[str]) -> list[str]:
    unknown = [role for role in roles if role not in capability_service.KNOWN_ROLES]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"نقش‌های ناشناخته: {', '.join(unknown)}. نقش‌های معتبر: {', '.join(capability_service.KNOWN_ROLES)}",
        )
    return roles


@admin_router.post("", status_code=201)
async def create_admin_capability(
    body: CapabilityCreateBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    existing = await capability_service.get_capability(session, body.key)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"قابلیت «{body.key}» از قبل وجود دارد.")
    cap = Capability(
        key=body.key,
        title_fa=body.title_fa,
        description_fa=body.description_fa,
        icon=body.icon,
        is_enabled=body.is_enabled,
        allowed_roles_json=_validate_roles(body.allowed_roles),
        allowed_plans_json=list(body.allowed_plans),
        default_route_key=body.default_route_key,
        config_json=dict(body.config),
        sort_order=body.sort_order,
    )
    session.add(cap)
    await session.commit()
    await session.refresh(cap)
    return capability_service.serialize_capability(cap)


@admin_router.put("/{key}")
async def update_admin_capability(
    key: str,
    body: CapabilityUpdateBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cap = await capability_service.get_capability(session, key)
    if cap is None:
        raise HTTPException(status_code=404, detail=f"قابلیت «{key}» یافت نشد.")
    if body.title_fa is not None:
        cap.title_fa = body.title_fa
    if body.description_fa is not None:
        cap.description_fa = body.description_fa
    if body.icon is not None:
        cap.icon = body.icon
    if body.is_enabled is not None:
        cap.is_enabled = body.is_enabled
    if body.allowed_roles is not None:
        cap.allowed_roles_json = _validate_roles(body.allowed_roles)
    if body.allowed_plans is not None:
        cap.allowed_plans_json = list(body.allowed_plans)
    if body.default_route_key is not None:
        cap.default_route_key = body.default_route_key
    if body.config is not None:
        cap.config_json = dict(body.config)
    if body.sort_order is not None:
        cap.sort_order = body.sort_order
    # Phase 5 glass box: every admin capability edit (enable/disable, roles, routes) is logged.
    from app.models.phase5 import AdminActionLog

    session.add(
        AdminActionLog(
            actor="admin",
            action="capability.update",
            target=f"capability:{key}",
            payload_json=body.model_dump(exclude_none=True),
        )
    )
    await session.commit()
    await session.refresh(cap)
    return capability_service.serialize_capability(cap)


@admin_router.delete("/{key}")
async def delete_admin_capability(
    key: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cap = await capability_service.get_capability(session, key)
    if cap is None:
        raise HTTPException(status_code=404, detail=f"قابلیت «{key}» یافت نشد.")
    await session.delete(cap)
    await session.commit()
    return {"ok": True, "deleted": key}
