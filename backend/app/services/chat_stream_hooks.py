"""Background-task registry so fire-and-forget memory jobs are not garbage collected."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_PENDING: set[asyncio.Task[Any]] = set()


def schedule_l2_extraction(coro: Coroutine[Any, Any, Any]) -> None:
    task = asyncio.create_task(coro)
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
