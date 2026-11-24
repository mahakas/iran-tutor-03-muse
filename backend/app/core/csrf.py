"""CSRF protection for cookie-authenticated mutations (double-submit token).

The session cookie is HttpOnly, so the browser cannot expose it to JavaScript. A second,
readable cookie holds a random token; every state-changing request must echo it in
`X-CSRF-Token`. An attacker's cross-site page can *send* cookies but cannot read the
token cookie (same-origin policy) nor set the custom header on a simple request, so
forged state changes fail.

Rules:

* `CSRF_ENFORCEMENT=off` disables the middleware (non-browser tooling only).
* `on` (default): reject state-changing requests whose `Origin`/`Referer` host does not
  match the serving host. Browsers always send one of these on a cross-site mutation,
  which is exactly the CSRF signature.
* `strict`: the same origin check **plus** the double-submit token for browser requests.
  Native clients and tests send no `Origin`, so they are unaffected (and not CSRF-able).
* Token-authenticated requests (`X-User-Token` / `Authorization: Bearer`, `X-Admin-Token`)
  are exempt: they are not sent automatically by browsers.
* Exempt paths: login/registration/OTP entry points (no session yet) and `/logout`.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.client_ip import constant_time_equal

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "iran_tutor_csrf"
CSRF_HEADER_NAME = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "PROPFIND"})
# Read-only convenience endpoints that publish the CSRF token to the client.
TOKEN_EXPOSING_PATHS: tuple[str, ...] = (
    "/api/v1/auth/me",
    "/api/v1/auth/csrf",
    "/api/v1/admin/auth/session",
)

# Paths that must work without a CSRF token (they establish (or tear down) the session).
EXEMPT_PATH_SUFFIXES: tuple[str, ...] = (
    "/api/v1/auth/request-otp",
    "/api/v1/auth/verify-otp",
    "/api/v1/auth/login",
    "/api/v1/auth/register/request-otp",
    "/api/v1/auth/register/verify-otp",
    "/api/v1/auth/register/complete",
    "/api/v1/auth/password/recover/request-otp",
    "/api/v1/auth/password/recover/verify-otp",
    "/api/v1/auth/password/recover/complete",
    "/api/v1/auth/logout",
    "/api/v1/admin/auth/login",
    "/api/v1/admin/auth/logout",
)

COOKIE_AUTH_MARKERS = (
    "iran_tutor_user",
    "iran_tutor_admin",
)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_cookie_kwargs(request: Request) -> dict[str, object]:
    https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    )
    return {
        "httponly": False,  # must be readable by the same-origin client
        "samesite": "none" if https else "lax",
        "secure": https,
        "path": "/",
    }


def ensure_csrf_cookie(request: Request, response) -> str:
    """Return the request's CSRF token, minting and setting one when absent."""
    existing = request.cookies.get(CSRF_COOKIE_NAME)
    # A double-submit token is only meaningful next to a session cookie. Anonymous
    # visitors (and non-browser clients) get none, keeping sessions un-CSRF-able until
    # the browser actually holds a session.
    if not any(request.cookies.get(name) for name in COOKIE_AUTH_MARKERS):
        return ""
    token = existing if existing and len(existing) >= 24 else new_csrf_token()
    if token != existing:
        response.set_cookie(key=CSRF_COOKIE_NAME, value=token, **csrf_cookie_kwargs(request))
    return token


def _uses_header_auth(request: Request) -> bool:
    if request.headers.get("x-user-token", "").strip():
        return True
    if request.headers.get("x-admin-token", "").strip():
        return True
    auth = request.headers.get("authorization", "")
    return auth.lower().startswith("bearer ") and bool(auth[7:].strip())


def _is_exempt(path: str) -> bool:
    return any(path.endswith(suffix) for suffix in EXEMPT_PATH_SUFFIXES)


async def csrf_protection_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.method.upper() in SAFE_METHODS:
        return await call_next(request)

    settings = get_settings()
    mode = str(getattr(settings, "csrf_enforcement", "on")).strip().lower()
    if mode == "off":
        return await call_next(request)
    if _is_exempt(request.url.path) or _uses_header_auth(request):
        return await call_next(request)

    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    origin_host = _host_of(origin)
    same_origin = not origin or origin_host is None or origin_host == _request_host(request)

    if not same_origin:
        logger.warning(
            "csrf.origin_rejected path=%s method=%s origin=%s", request.url.path, request.method, origin
        )
        return _reject("منبع درخواست معتبر نیست. صفحه را دوباره باز کنید.")

    # Browser requests carry Origin. In `strict` mode the double-submit token is also
    # required; non-browser clients (no Origin/Referer) are not CSRF-able.
    if mode == "strict" and origin:
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        header_token = request.headers.get(CSRF_HEADER_NAME, "")
        if not cookie_token or not header_token or not constant_time_equal(cookie_token, header_token):
            logger.warning("csrf.token_rejected path=%s method=%s", request.url.path, request.method)
            return _reject("درخواست نامعتبر است (نشانهٔ امنیتی CSRF موجود نیست). صفحه را تازه کنید.")

    return await call_next(request)


def _host_of(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    return (parsed.hostname or "").lower() or None


def _request_host(request: Request) -> str:
    host = request.headers.get("host") or (request.url.hostname or "")
    if ":" in host and not host.startswith("["):
        host = host.split(":")[0]
    forwarded = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    if forwarded:
        candidate = forwarded.split(":")[0]
        if candidate:
            host = candidate
    return host.lower()


def _reject(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": detail, "code": "csrf_failed"},
        headers={"Cache-Control": "no-store"},
    )


def hmac_tokens_equal(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except TypeError:
        return False
