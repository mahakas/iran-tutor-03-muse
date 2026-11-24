"""Recoverable SSE streaming for tutor answers (Phase 4).

Design
- A generation runs as a background asyncio task that appends text chunks to a
  per-`stream_id` buffer. Clients read the buffer over SSE and can reconnect with
  `cursor` (the number of chunks already received), so a dropped connection never
  loses text.
- Buffer backend: Redis when `REDIS_URL` is reachable (works across workers),
  otherwise an in-process store (single worker, tests, demo).
- The model provider streams deltas into the buffer while it generates. The runner
  coalesces small deltas for efficient SSE delivery. Stop cancels the live provider
  request and sets a flag.
- No orphan rows: the generation runs in one DB transaction. Gateway audit rows
  and quota counters are flushed inside it, but committed only after the stream
  finishes. A stopped or failed run is rolled back and writes nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.llm_client import track_token_usage
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("done", "stopped", "error")
CHUNK_CHARS = 24
CHUNK_DELAY_SECONDS = 0.02
STREAM_TTL_SECONDS = 3600


class StreamStore:
    """Interface shared by the Redis and in-memory backends."""

    backend = "abstract"

    async def create(self, stream_id: str, user_id: str, meta: dict[str, Any]) -> None: ...
    async def append(self, stream_id: str, text: str) -> None: ...
    async def read(self, stream_id: str, cursor: int) -> tuple[str | None, dict[str, Any], list[str]]:
        """Return (status, meta, chunks[cursor:]). Status is read before chunks."""
        raise NotImplementedError
    async def set_status(self, stream_id: str, status: str, final: dict[str, Any] | None = None) -> None: ...
    async def request_stop(self, stream_id: str) -> None: ...
    async def stop_requested(self, stream_id: str) -> bool: ...
    async def get_meta(self, stream_id: str) -> dict[str, Any] | None: ...


class MemoryStreamStore(StreamStore):
    backend = "memory"

    def __init__(self) -> None:
        self._streams: dict[str, dict[str, Any]] = {}

    def _purge(self) -> None:
        now = time.time()
        for key in [k for k, v in self._streams.items() if v["expires_at"] < now]:
            self._streams.pop(key, None)

    async def create(self, stream_id: str, user_id: str, meta: dict[str, Any]) -> None:
        self._purge()
        self._streams[stream_id] = {
            "user_id": user_id,
            "status": "running",
            "meta": meta,
            "final": None,
            "stop": False,
            "chunks": [],
            "expires_at": time.time() + STREAM_TTL_SECONDS,
        }

    async def append(self, stream_id: str, text: str) -> None:
        stream = self._streams.get(stream_id)
        if stream is not None:
            stream["chunks"].append(text)

    async def read(self, stream_id: str, cursor: int) -> tuple[str | None, dict[str, Any], list[str]]:
        stream = self._streams.get(stream_id)
        if stream is None:
            return None, {}, []
        status = stream["status"]
        return status, {"user_id": stream["user_id"], "final": stream["final"], **stream["meta"]}, stream["chunks"][cursor:]

    async def set_status(self, stream_id: str, status: str, final: dict[str, Any] | None = None) -> None:
        stream = self._streams.get(stream_id)
        if stream is not None:
            stream["status"] = status
            if final is not None:
                stream["final"] = final

    async def request_stop(self, stream_id: str) -> None:
        stream = self._streams.get(stream_id)
        if stream is not None:
            stream["stop"] = True

    async def stop_requested(self, stream_id: str) -> bool:
        stream = self._streams.get(stream_id)
        return bool(stream and stream["stop"])

    async def get_meta(self, stream_id: str) -> dict[str, Any] | None:
        stream = self._streams.get(stream_id)
        if stream is None:
            return None
        return {"user_id": stream["user_id"], "status": stream["status"], "final": stream["final"], **stream["meta"]}


class RedisStreamStore(StreamStore):
    backend = "redis"
    PREFIX = "iran_tutor:stream:"

    def __init__(self, client: Any) -> None:
        self._redis = client

    def _meta_key(self, stream_id: str) -> str:
        return f"{self.PREFIX}{stream_id}:meta"

    def _chunks_key(self, stream_id: str) -> str:
        return f"{self.PREFIX}{stream_id}:chunks"

    async def create(self, stream_id: str, user_id: str, meta: dict[str, Any]) -> None:
        mapping = {
            "user_id": user_id,
            "status": "running",
            "stop": "0",
            "final": "",
            "meta": json.dumps(meta, ensure_ascii=False),
        }
        await self._redis.hset(self._meta_key(stream_id), mapping=mapping)
        await self._redis.expire(self._meta_key(stream_id), STREAM_TTL_SECONDS)

    async def append(self, stream_id: str, text: str) -> None:
        await self._redis.rpush(self._chunks_key(stream_id), json.dumps(text, ensure_ascii=False))
        await self._redis.expire(self._chunks_key(stream_id), STREAM_TTL_SECONDS)

    async def read(self, stream_id: str, cursor: int) -> tuple[str | None, dict[str, Any], list[str]]:
        raw = await self._redis.hgetall(self._meta_key(stream_id))
        if not raw:
            return None, {}, []
        status = raw.get("status", "running")
        raw_chunks = await self._redis.lrange(self._chunks_key(stream_id), cursor, -1)
        chunks = [json.loads(item) for item in raw_chunks]
        return status, self._decode_meta(raw), chunks

    def _decode_meta(self, raw: dict[str, Any]) -> dict[str, Any]:
        meta = json.loads(raw.get("meta") or "{}")
        final = json.loads(raw["final"]) if raw.get("final") else None
        return {"user_id": raw.get("user_id"), "final": final, **meta}

    async def set_status(self, stream_id: str, status: str, final: dict[str, Any] | None = None) -> None:
        mapping: dict[str, str] = {"status": status}
        if final is not None:
            mapping["final"] = json.dumps(final, ensure_ascii=False)
        await self._redis.hset(self._meta_key(stream_id), mapping=mapping)

    async def request_stop(self, stream_id: str) -> None:
        await self._redis.hset(self._meta_key(stream_id), "stop", "1")

    async def stop_requested(self, stream_id: str) -> bool:
        return (await self._redis.hget(self._meta_key(stream_id), "stop")) == "1"

    async def get_meta(self, stream_id: str) -> dict[str, Any] | None:
        raw = await self._redis.hgetall(self._meta_key(stream_id))
        if not raw:
            return None
        return {**self._decode_meta(raw), "status": raw.get("status", "running")}


_store: StreamStore | None = None
_store_lock = asyncio.Lock()


async def get_stream_store() -> StreamStore:
    """Redis when configured and reachable, otherwise the in-process fallback."""
    global _store
    if _store is not None:
        return _store
    async with _store_lock:
        if _store is not None:
            return _store
        url = get_settings().redis_url
        if url:
            try:
                from redis.asyncio import Redis

                client = Redis.from_url(url, encoding="utf-8", decode_responses=True)
                await client.ping()
                _store = RedisStreamStore(client)
                return _store
            except Exception:  # noqa: BLE001 - fall back, never fail the chat
                logger.warning("chat_stream.redis_unavailable; using in-process buffer")
        _store = MemoryStreamStore()
        return _store


def reset_stream_store_for_tests(store: StreamStore | None = None) -> None:
    global _store
    _store = store


# ---------------------------------------------------------------------------
# Generation runner
# ---------------------------------------------------------------------------
_TASKS: dict[str, asyncio.Task] = {}


class GenerationStopped(Exception):
    pass


@dataclass
class StreamParams:
    user_id: str
    query: str
    mode: str
    auto_mode: bool
    grade_number: int | None
    major_code: str | None
    book_id: int | None
    top_k: int
    chat_session_id: str | None
    grade_numbers: list[int] | None = None
    book_ids: list[int] | None = None
    regenerate_of: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def new_stream_id() -> str:
    return uuid.uuid4().hex


async def start_stream(params: StreamParams) -> str:
    stream_id = new_stream_id()
    store = await get_stream_store()
    await store.create(
        stream_id,
        params.user_id,
        {
            "mode": params.mode,
            "auto_mode": params.auto_mode,
            "book_id": params.book_id,
            "grade_numbers": params.grade_numbers,
            "chat_session_id": params.chat_session_id,
            "regenerate_of": params.regenerate_of,
        },
    )
    task = asyncio.create_task(_run_generation(stream_id, params))
    _TASKS[stream_id] = task
    task.add_done_callback(lambda _t, sid=stream_id: _TASKS.pop(sid, None))
    return stream_id


async def stop_stream(stream_id: str) -> None:
    store = await get_stream_store()
    await store.request_stop(stream_id)
    task = _TASKS.get(stream_id)
    if task is not None and not task.done():
        task.cancel()


async def _check_stop(store: StreamStore, stream_id: str) -> None:
    if await store.stop_requested(stream_id):
        raise GenerationStopped()


async def _run_generation(stream_id: str, params: StreamParams) -> None:
    from app.models.auth import User
    from app.services.capability_service import check_capability_access
    from app.services.intent_router import route_intent
    from app.services.quota_service import enforce_ai_quota
    from app.services.tutor_service import (
        MODE_CAPABILITY_KEYS,
        MODE_FEATURE_KEYS,
        answer_from_textbook,
    )
    from app.services.tutor_turns import finish_turn_success

    store = await get_stream_store()
    try:
        async with async_session_factory() as db:
            try:
                mode = params.mode
                decision = None
                if params.auto_mode:
                    decision = await route_intent(
                        query=params.query,
                        user_id=params.user_id,
                        session_id=params.chat_session_id,
                        db_session=db,
                    )
                    mode = decision.mode
                    # The HTTP entrypoint can only pre-check Chat before routing.
                    # Re-check the selected non-chat capability and its own quota
                    # before any Solve/Quiz work is allowed to run in the background.
                    if mode != "tutor":
                        user = await db.get(User, params.user_id)
                        if user is None:
                            raise RuntimeError("student account is no longer available")
                        await check_capability_access(
                            db, MODE_CAPABILITY_KEYS.get(mode, "chat"), user
                        )
                        await enforce_ai_quota(
                            db,
                            user=user,
                            feature_key=MODE_FEATURE_KEYS.get(mode, "chat"),
                        )
                await _check_stop(store, stream_id)

                pending_text = ""

                async def publish_delta(delta: str) -> None:
                    nonlocal pending_text
                    if not delta:
                        return
                    await _check_stop(store, stream_id)
                    pending_text += delta
                    while len(pending_text) >= CHUNK_CHARS:
                        chunk = pending_text[:CHUNK_CHARS]
                        pending_text = pending_text[CHUNK_CHARS:]
                        await store.append(stream_id, chunk)
                        if CHUNK_DELAY_SECONDS > 0:
                            await asyncio.sleep(CHUNK_DELAY_SECONDS)

                with track_token_usage() as usage:
                    result = await answer_from_textbook(
                        query=params.query,
                        grade_number=params.grade_number,
                        major_code=params.major_code,
                        book_id=params.book_id,
                        top_k=params.top_k,
                        mode=mode,  # type: ignore[arg-type]
                        user_id=params.user_id,
                        session_id=params.chat_session_id,
                        db_session=db,
                        grade_numbers=params.grade_numbers,
                        book_ids=params.book_ids,
                        on_chunk=publish_delta,
                    )
                result["mode"] = mode
                if decision is not None:
                    result["router"] = decision.to_payload()

                # Flush the final partial chunk only after generation completed.
                await _check_stop(store, stream_id)
                if pending_text:
                    await store.append(stream_id, pending_text)
                await _check_stop(store, stream_id)

                # Persist: usage + audit (already flushed) + L1 trace, then mark done.
                await finish_turn_success(
                    db,
                    user_id=params.user_id,
                    params=params,
                    mode=mode,
                    result=result,
                    usage=usage,
                )
            except BaseException:
                await db.rollback()
                raise
        final = {k: v for k, v in result.items() if k != "answer"}
        await store.set_status(stream_id, "done", final=final)
    except GenerationStopped:
        await store.set_status(stream_id, "stopped")
    except asyncio.CancelledError:
        await store.set_status(stream_id, "stopped")
    except Exception:  # noqa: BLE001 - never leak provider details
        logger.exception("chat_stream.generation_failed stream=%s", stream_id)
        await store.set_status(stream_id, "error")


def serialize_stream_event(kind: str, data: dict[str, Any], event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {kind}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"
