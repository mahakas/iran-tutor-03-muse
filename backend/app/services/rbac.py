"""Session/user resolution helpers shared by RBAC dependencies and admin guards.

Kept separate from `app/api/rbac_deps.py` to avoid an import cycle with
`app.api.admin` (which owns the legacy admin session cookie).
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User


async def get_optional_user(request: Request, session: AsyncSession) -> User | None:
    """Return the authenticated user for this request, or `None`."""
    from app.api.dependencies import get_optional_student

    return await get_optional_student(request, session)
