"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.llm_client import close_llm_clients
from app.core.runtime_config import load_runtime_overrides_from_db
from app.db.seed import seed_database
from app.db.session import engine, get_session
from app.services.retrieval_service import close_qdrant


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.core.config import get_settings
    from app.core.production_guard import enforce_production_settings

    enforce_production_settings(get_settings())  # raises in production with weak secrets
    _warn_insecure_admin_defaults()
    await seed_database()
    await load_runtime_overrides_from_db()
    await _recover_stale_podcast_jobs()
    try:
        yield
    finally:
        await close_qdrant()
        await close_llm_clients()
        await engine.dispose()


async def _recover_stale_podcast_jobs() -> None:
    """Mark podcast jobs whose worker died (server restart) as recognizable failures.

    The standalone worker (`backend/scripts/podcast_worker.py`) can then pick up
    queued episodes; unfinished ones become retryable instead of hanging forever.
    """
    import logging

    from app.db.session import async_session_factory
    from app.services.podcast_service import recover_stale_episodes

    try:
        async with async_session_factory() as session:
            recovered = await recover_stale_episodes(session)
        if recovered:
            logging.getLogger("app.podcast").warning(
                "podcast.recovered_stale_jobs count=%s", recovered
            )
    except Exception:  # noqa: BLE001 - startup must never fail because of recovery
        logging.getLogger("app.podcast").exception("podcast.recovery_failed")


_INSECURE_ADMIN_PASSWORDS = {"", "123", "admin", "password", "change_me", "changeme"}


def _warn_insecure_admin_defaults() -> None:
    """Log loudly when the admin login still uses a known-weak default (never blocks startup)."""
    import logging

    from app.core.config import get_settings

    settings = get_settings()
    if (settings.admin_password or "").strip().lower() in _INSECURE_ADMIN_PASSWORDS:
        logging.getLogger("app.security").warning(
            "ADMIN_PASSWORD is a known-weak default; set a strong value in .env before any real use."
        )


app = FastAPI(title="Iran AI Tutor", version="0.1.0", lifespan=lifespan)


# Baseline security headers for every API response. The frontend sets the same headers
# in next.config.ts. Microphone is allowed for same-origin voice input only.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(self)",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@app.middleware("http")
async def add_security_headers(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@app.middleware("http")
async def csrf_protection(request, call_next):  # type: ignore[no-untyped-def]
    """Double-submit CSRF check for cookie-authenticated mutations (see app.core.csrf)."""
    from app.core.csrf import TOKEN_EXPOSING_PATHS, csrf_protection_middleware, ensure_csrf_cookie

    response = await csrf_protection_middleware(request, call_next)
    if request.method.upper() in {"GET", "HEAD"} and any(
        request.url.path.endswith(path) for path in TOKEN_EXPOSING_PATHS
    ):
        token = ensure_csrf_cookie(request, response)
        response.headers["X-CSRF-Token"] = token
    return response


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "mode": "demo" if get_settings().demo_mode else "production"}


@app.get("/api/v1/system/status")
async def system_status(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    """Expose non-secret diagnostics useful for the local test harness."""
    await session.execute(text("SELECT 1"))
    settings = get_settings()
    return {
        "status": "ok",
        "mode": "demo" if settings.demo_mode else "production",
        "database": "sqlite" if settings.database_url.startswith("sqlite") else "postgresql",
        "vector_backend": settings.vector_backend,
        "vector_search": not settings.demo_mode,
        "external_models": not settings.demo_mode,
    }


from app.api.account import router as account_router  # noqa: E402
from app.api.academic_profile import router as academic_profile_router  # noqa: E402
from app.api.admin import router as admin_router  # noqa: E402
from app.api.admin_users import router as admin_users_router  # noqa: E402
from app.api.admin_catalog import router as admin_catalog_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.capabilities import admin_router as capabilities_admin_router  # noqa: E402
from app.api.capabilities import router as capabilities_router  # noqa: E402
from app.api.curriculum import router as curriculum_router  # noqa: E402
from app.api.exams import router as exams_router  # noqa: E402
from app.api.flashcards import admin_router as flashcards_admin_router  # noqa: E402
from app.api.flashcards import router as flashcards_router  # noqa: E402
from app.api.phase4_admin import router as phase4_admin_router  # noqa: E402
from app.api.phase5 import router as phase5_router  # noqa: E402
from app.api.phase5_admin import router as phase5_admin_router  # noqa: E402
from app.api.phase6 import router as phase6_router  # noqa: E402
from app.api.phase6_admin import router as phase6_admin_router  # noqa: E402
from app.api.feedback import router as feedback_router  # noqa: E402
from app.api.kb import router as kb_router  # noqa: E402
from app.api.plans import router as plans_router  # noqa: E402
from app.api.podcast import router as podcast_router  # noqa: E402
from app.api.podcast_admin import router as podcast_admin_router  # noqa: E402
from app.api.skills import router as skills_router  # noqa: E402
from app.api.tutor import router as tutor_router  # noqa: E402

app.include_router(account_router)
app.include_router(academic_profile_router)
app.include_router(admin_router)
app.include_router(admin_users_router)
app.include_router(admin_catalog_router)
app.include_router(auth_router)
app.include_router(curriculum_router)
app.include_router(plans_router)
app.include_router(tutor_router)
app.include_router(exams_router)
app.include_router(feedback_router)
app.include_router(capabilities_router)
app.include_router(capabilities_admin_router)
app.include_router(skills_router)
app.include_router(kb_router)
app.include_router(flashcards_router)
app.include_router(flashcards_admin_router)
app.include_router(phase4_admin_router)
app.include_router(phase5_router)
app.include_router(phase5_admin_router)
app.include_router(phase6_router)
app.include_router(phase6_admin_router)
app.include_router(podcast_router)
app.include_router(podcast_admin_router)
