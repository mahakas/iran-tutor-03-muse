"""Role-based access control (Phase 1, Rule 2).

Roles: `admin`, `teacher`, `student`, `guardian`.

`/api/v1/admin/*` is protected by `require_admin`, which accepts **two** independent
credentials:

1. the legacy admin session cookie / `X-Admin-Token` (the shared admin password —
   still supported so existing tooling and tests keep working), and
2. a real user session whose `User.role == "admin"`.

A `student` session token can never satisfy an admin dependency, and a non-admin
role is rejected with 403 rather than 401 so the distinction is observable.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.auth import User
from app.services import rbac
from app.services.permissions import MAINTAINABLE_ROLES, ROLE_RANKS

logger = logging.getLogger(__name__)

# Canonical role taxonomy lives in `app.services.permissions` so the API surface, the
# admin service and the tests cannot drift apart.
VALID_ROLES: tuple[str, ...] = MAINTAINABLE_ROLES


def normalize_role(raw: str | None) -> str:
    role = (raw or "student").strip().lower()
    return role if role in ROLE_RANKS else "student"


def has_role(user: User | None, *roles: str) -> bool:
    if user is None:
        return False
    return normalize_role(getattr(user, "role", None)) in roles


async def get_current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User | None:
    """Resolve a student/user session without raising (re-exported for routers)."""
    return await rbac.get_optional_user(request, session)


def require_roles(
    *roles: str,
) -> Callable[[Request, AsyncSession], Awaitable[User]]:
    """Build a dependency that requires the current user to hold one of `roles`."""

    async def dependency(
        request: Request, session: AsyncSession = Depends(get_session)
    ) -> User:
        user = await rbac.get_optional_user(request, session)
        if user is None:
            raise HTTPException(status_code=401, detail="برای دسترسی به این بخش باید وارد شوید.")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="حساب کاربری شما غیرفعال شده است.")
        if normalize_role(user.role) not in roles:
            raise HTTPException(
                status_code=403,
                detail="این عملیات فقط برای نقش‌های مجاز در دسترس است.",
            )
        request.state.current_user = user
        return user

    return dependency


require_admin_role = require_roles("admin", "super_admin")
require_teacher_role = require_roles("admin", "super_admin", "teacher")
require_student_role = require_roles("student", "admin", "super_admin", "teacher")


def require_moderator_role() -> Callable[[Request, AsyncSession], Awaitable[User]]:
    """Moderator and above may read user/session/audit data (writes re-checked in service)."""
    return require_roles("moderator", "admin", "super_admin")
