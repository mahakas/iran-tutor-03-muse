"""Shared AdminActionLog writer for admin mutations (Phase 06 audit closure).

Single implementation reused by every admin mutation that previously had no
audit trail (books, providers, model routes, quotas, billing, runtime
settings) — no parallel audit logic. The actor is resolved from
`request.state.admin_identity`, which `require_admin` always sets:

  * legacy console session  -> "admin-console"
  * real user session       -> "user:<user_id>"

Payloads are written by the callers and MUST stay secret-free (names, ids,
field-name lists, counts — never API keys, passwords or secret values).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phase5 import AdminActionLog

logger = logging.getLogger(__name__)


def actor_from_request(request: Request | None) -> str:
    identity = getattr(request.state, "admin_identity", None) if request is not None else None
    if not identity:
        return "admin-console"
    if identity.get("kind") == "user_session" and identity.get("user_id"):
        return f"user:{identity['user_id']}"
    return "admin-console"


async def log_admin_action(
    session: AsyncSession,
    request: Request | None,
    *,
    action: str,
    target: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append one audit row and commit it. Failure to write the audit entry is
    logged but does not fail an already-successful mutation."""
    row = AdminActionLog(
        actor=actor_from_request(request),
        action=action[:64],
        target=target[:128],
        payload_json=payload or {},
    )
    session.add(row)
    try:
        await session.commit()
    except Exception:  # noqa: BLE001 - audit must not turn a done mutation into a 500
        await session.rollback()
        logger.exception(
            "admin_action_log.write_failed action=%s target=%s", action, target
        )
