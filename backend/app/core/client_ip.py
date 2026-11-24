"""Resolve the real client IP for rate limiting behind reverse proxies.

`X-Forwarded-For` is honored only when `TRUSTED_PROXY_HOPS` > 0. With N trusted
proxies in front of the app, the client is the N-th entry from the right.
With the default (0) the direct peer address is used and the header is ignored,
so clients cannot spoof their way out of a limit.
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import get_settings


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    hops = int(getattr(get_settings(), "trusted_proxy_hops", 0) or 0)
    if hops <= 0:
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    entries = [item.strip() for item in forwarded.split(",") if item.strip()]
    if len(entries) >= hops:
        candidate = entries[-hops]
        if candidate:
            return candidate[:64]
    return peer


def constant_time_equal(a: str, b: str) -> bool:
    """`hmac.compare_digest` for str inputs that may contain non-ASCII characters.

    compare_digest raises TypeError on non-ASCII str; comparing UTF-8 bytes avoids that.
    """
    import hmac

    return hmac.compare_digest(a.encode("utf-8", "surrogatepass"), b.encode("utf-8", "surrogatepass"))
