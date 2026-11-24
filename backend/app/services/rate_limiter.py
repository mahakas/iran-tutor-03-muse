"""Redis-backed sliding-window rate limiting with an in-process fallback.

Redis is optional: when `REDIS_URL` is missing or unreachable the limiter keeps
per-process counters so local/demo environments and the test suite never need a
Redis server. Production deployments should set `REDIS_URL` (docker-compose
already ships a `redis` service).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_redis_client = None
_redis_unavailable = False
_local_windows: dict[str, deque[float]] = defaultdict(deque)
_local_lock = asyncio.Lock()
# Bound on in-process fallback buckets: without it, an attacker that varies
# the identity (IP/phone/user) per request grows this dict without limit
# (memory exhaustion). Oldest buckets are evicted first; Redis deployments
# never touch this path.
_MAX_LOCAL_BUCKETS = 10_000


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


def _bucket_key(identity: str, bucket: str) -> str:
    return f"iran-tutor:rl:{bucket}:{identity}"


async def _get_redis():
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    settings = get_settings()
    url = getattr(settings, "redis_url", None)
    if not url:
        return None
    if _redis_client is None:
        try:
            from redis.asyncio import Redis  # imported lazily: redis is optional

            client = Redis.from_url(url, encoding="utf-8", decode_responses=True)
            await client.ping()
            _redis_client = client
            logger.info("rate_limiter.redis_connected")
        except Exception as error:  # noqa: BLE001 - degrade gracefully
            _redis_unavailable = True
            logger.warning("rate_limiter.redis_unavailable: %s", type(error).__name__)
            return None
    return _redis_client


async def _check_local(identity: str, bucket: str, limit: int, window_seconds: int) -> RateLimitDecision:
    now = time.monotonic()
    key = _bucket_key(identity, bucket)
    async with _local_lock:
        window = _local_windows[key]
        cutoff = now - window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        # Evict the oldest buckets when the cap is reached so the dict cannot
        # grow without bound under identity-varying traffic. Expired entries
        # are pruned lazily here because their deque is already empty.
        while len(_local_windows) > _MAX_LOCAL_BUCKETS:
            oldest = next(iter(_local_windows))
            if oldest == key:
                break
            _local_windows.pop(oldest)
        if len(window) >= limit:
            retry_after = int(max(1, window_seconds - (now - window[0])))
            return RateLimitDecision(False, limit, 0, retry_after)
        window.append(now)
        return RateLimitDecision(True, limit, max(0, limit - len(window)), 0)


async def check_rate_limit(
    *,
    identity: str,
    bucket: str,
    limit: int,
    window_seconds: int,
) -> RateLimitDecision:
    """Record one hit for `identity` and report whether it is within the window."""
    settings = get_settings()
    if not getattr(settings, "rate_limit_enabled", True) or limit <= 0:
        return RateLimitDecision(True, limit, limit, 0)

    client = await _get_redis()
    if client is None:
        return await _check_local(identity, bucket, limit, window_seconds)

    key = _bucket_key(identity, bucket)
    try:
        async with client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            count, _ = await pipe.execute()
        ttl = await client.ttl(key)
        if int(count) > limit:
            return RateLimitDecision(False, limit, 0, max(1, int(ttl or window_seconds)))
        return RateLimitDecision(True, limit, max(0, limit - int(count)), 0)
    except Exception as error:  # noqa: BLE001 - fall back instead of failing the request
        logger.warning("rate_limiter.redis_error: %s", type(error).__name__)
        return await _check_local(identity, bucket, limit, window_seconds)


async def close_rate_limiter() -> None:
    """Release the Redis connection and in-process windows on shutdown/tests."""
    global _redis_client, _redis_unavailable
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:  # noqa: BLE001
            pass
    _redis_client = None
    _redis_unavailable = False
    _local_windows.clear()
