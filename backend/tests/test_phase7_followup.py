"""Phase 7 follow-up: student figure access (ready books only), feedback ownership, production guards."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models.auth import User
from app.models.capabilities import SourceFigure
from app.models.curriculum import Book, BookStatus, Grade
from app.models.governance import AiAuditLog
from app.services import rate_limiter
from tests.test_phase1_governance import ADMIN_HEADERS, _build_env, _login_student

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


async def _seed_figure(factory, tmp_path, *, status: BookStatus, name: str = "fig.png"):
    """Create one book with one figure file under tmp_path/figures. Returns (book_id, figure_id)."""
    figures = tmp_path / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    image = figures / name
    image.write_bytes(PNG)
    async with factory() as session:
        grade = await session.scalar(select(Grade).where(Grade.number == 7))
        book = Book(
            title="کتاب تصویر",
            grade_id=grade.id,
            pdf_file_path=str(tmp_path / "book.pdf"),
            total_pdf_pages=3,
            status=status,
            catalog_status="approved" if status == BookStatus.ready else "legacy_unverified",
        )
        session.add(book)
        await session.flush()
        figure = SourceFigure(
            book_id=book.id,
            pdf_page_index=1,
            figure_label="شکل ۱",
            caption="نمونه",
            image_path=str(image),
        )
        session.add(figure)
        await session.commit()
        return book.id, figure.id


@pytest.mark.asyncio
async def test_student_figure_image_only_for_ready_books(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    from app.api import curriculum as curriculum_api

    monkeypatch.setattr(curriculum_api, "figures_dir", lambda book_id: tmp_path / "figures")
    try:
        ready_id, ready_fig = await _seed_figure(factory, tmp_path, status=BookStatus.ready)
        draft_id, draft_fig = await _seed_figure(
            factory, tmp_path, status=BookStatus.created, name="draft.png"
        )
        url = "/api/v1/curriculum/books/{b}/figures/{f}/image"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Anonymous: rejected.
            anon = await client.get(url.format(b=ready_id, f=ready_fig))
            assert anon.status_code == 401

            token, _user = await _login_student(client, "09120000040")
            auth = {"Authorization": f"Bearer {token}"}

            ok = await client.get(url.format(b=ready_id, f=ready_fig), headers=auth)
            assert ok.status_code == 200, ok.text
            assert ok.headers["content-type"] == "image/png"
            assert ok.headers["x-content-type-options"] == "nosniff"

            # Book not ready: no access even with a valid figure id.
            draft = await client.get(url.format(b=draft_id, f=draft_fig), headers=auth)
            assert draft.status_code == 404

            # Figure exists but belongs to another book: no cross-book access.
            wrong_book = await client.get(url.format(b=ready_id + 999, f=ready_fig), headers=auth)
            assert wrong_book.status_code == 404

            # Admin route stays admin-only, even with a valid student session.
            admin_route = await client.get(
                f"/api/v1/admin/kb/figures/{ready_fig}/image", headers=auth
            )
            assert admin_route.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_student_figure_image_refuses_paths_outside_book_folder(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    from app.api import curriculum as curriculum_api

    monkeypatch.setattr(curriculum_api, "figures_dir", lambda book_id: tmp_path / "figures")
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG)
    try:
        book_id, figure_id = await _seed_figure(factory, tmp_path, status=BookStatus.ready)
        async with factory() as session:
            figure = await session.get(SourceFigure, figure_id)
            figure.image_path = str(outside)  # corrupted/malicious stored path
            await session.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token, _user = await _login_student(client, "09120000041")
            resp = await client.get(
                f"/api/v1/curriculum/books/{book_id}/figures/{figure_id}/image",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_student_cannot_flag_another_users_audit_row(tmp_path, monkeypatch):
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            owner_user = User(phone_number="09120000050", full_name="owner", role="student")
            session.add(owner_user)
            await session.flush()
            session.add(
                AiAuditLog(
                    user_id=owner_user.id,
                    feature_key="chat",
                    model_name="m",
                    request_messages_json=[],
                    response_text="پاسخ خصوصی",
                    rag_citations_json=[],
                    rag_hit_count=0,
                    status="success",
                )
            )
            await session.commit()
            foreign_id = await session.scalar(select(AiAuditLog.id))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token, _user = await _login_student(client, "09120000051")
            resp = await client.post(
                "/api/v1/feedback/flag",
                json={"audit_id": foreign_id, "note": "تلاش برای flag ردیف دیگران"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403, resp.text

            async with factory() as session:
                row = await session.get(AiAuditLog, foreign_id)
                assert row.status == "success"
                assert row.flagged_by is None
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Production startup guard
# ---------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from app.core.production_guard import (  # noqa: E402
    enforce_production_settings,
    is_production,
    production_violations,
)

STRONG_PASSWORD = "Tutor-Prod-2026-xyz"
STRONG_SECRET = "k7Qp2mZr9VbX4nLw8TcY1sHj6GdF3aEu0RoPiMlK"


def _cfg(**overrides):
    base = {"app_env": "production", "admin_password": STRONG_PASSWORD, "secret_key": STRONG_SECRET}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_production_rejects_default_admin_password():
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        enforce_production_settings(_cfg(admin_password="123"))


def test_production_rejects_short_admin_password():
    assert production_violations(_cfg(admin_password="short-1")) != []


def test_production_rejects_placeholder_admin_password_from_env_example():
    assert production_violations(_cfg(admin_password="change_me_to_a_long_random_value")) != []


def test_production_rejects_missing_or_placeholder_secret_key():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        enforce_production_settings(_cfg(secret_key=None))
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        enforce_production_settings(_cfg(secret_key="replace_with_long_random_secret"))


def test_production_accepts_strong_secrets():
    enforce_production_settings(_cfg())  # no exception
    assert production_violations(_cfg()) == []


def test_local_environment_never_blocks_weak_secrets():
    weak = _cfg(app_env="local", admin_password="123", secret_key=None)
    enforce_production_settings(weak)  # warning only outside production
    assert is_production(weak) is False


def test_settings_read_environment_alias(monkeypatch):
    from app.core.config import Settings

    # Phase 04C-A: this test must be hermetic — a QA/backend .env file on disk
    # (e.g. APP_ENV=local for the browser-QA stack) must not override the
    # process environment the alias behaviour is testing.
    monkeypatch.setattr(
        Settings, "model_config", {**Settings.model_config, "env_file": None}
    )
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert Settings().app_env == "production"
    monkeypatch.delenv("ENVIRONMENT")
    monkeypatch.setenv("APP_ENV", "staging")
    assert Settings().app_env == "staging"


# ---------------------------------------------------------------------------
# Per-capability quota (admin-tunable, isolated per feature_key)
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from tests.test_phase1_governance import ADMIN_HEADERS as ADMIN  # noqa: E402


@pytest.mark.asyncio
async def test_per_capability_quota_override_is_isolated_and_admin_managed(tmp_path, monkeypatch):
    from app.models.auth import User
    from app.services import quota_service

    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Writes need admin credentials.
            anon = await client.put("/api/v1/admin/quotas/features/quiz", json={"daily_requests": 1})
            assert anon.status_code == 401

            # Invalid capability key is rejected.
            bad_key = await client.put(
                "/api/v1/admin/quotas/features/Quiz%20Bad", json={"daily_requests": 1}, headers=ADMIN
            )
            assert bad_key.status_code == 422

            # Set a tight daily request cap for `quiz` only.
            set_resp = await client.put(
                "/api/v1/admin/quotas/features/quiz", json={"daily_requests": 1}, headers=ADMIN
            )
            assert set_resp.status_code == 200, set_resp.text
            assert set_resp.json()["override"] == {"daily_requests": 1}

            listed = await client.get("/api/v1/admin/quotas", headers=ADMIN)
            assert listed.json()["feature_overrides"] == {"quiz": {"daily_requests": 1}}

            # A later global save must not wipe the per-capability override.
            await client.put("/api/v1/admin/quotas", json={"daily_tokens": 123_456}, headers=ADMIN)
            listed = await client.get("/api/v1/admin/quotas", headers=ADMIN)
            assert listed.json()["feature_overrides"] == {"quiz": {"daily_requests": 1}}
            assert listed.json()["policy"]["daily_tokens"] == 123_456

        async with factory() as session:
            user = User(
                phone_number="09120000060",
                role="student",
                tokens_remaining=10_000,
                plan_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
            session.add(user)
            await session.commit()

            quiz_limits = await quota_service.get_feature_limits(session, "quiz")
            chat_limits = await quota_service.get_feature_limits(session, "chat")
            assert quiz_limits["daily_requests"] == 1
            assert chat_limits["daily_requests"] == 400  # global default untouched
            assert quiz_limits["daily_tokens"] == 123_456  # inherited from global

            # First quiz call is allowed; the second hits the per-capability cap.
            await quota_service.enforce_ai_quota(session, user=user, feature_key="quiz")
            quiz_quota = await quota_service.get_or_create_quota(
                session, user_id=user.id, feature_key="quiz"
            )
            quiz_quota.daily_requests_used = 1
            await session.commit()
            with pytest.raises(HTTPException) as blocked:
                await quota_service.enforce_ai_quota(session, user=user, feature_key="quiz")
            assert blocked.value.status_code == 429

            # Chat is not affected by the quiz cap.
            decision = await quota_service.enforce_ai_quota(session, user=user, feature_key="chat")
            assert decision.allowed is True

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            deleted = await client.delete("/api/v1/admin/quotas/features/quiz", headers=ADMIN)
            assert deleted.status_code == 200
            missing = await client.delete("/api/v1/admin/quotas/features/quiz", headers=ADMIN)
            assert missing.status_code == 404
            listed = await client.get("/api/v1/admin/quotas", headers=ADMIN)
            assert listed.json()["feature_overrides"] == {}
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Text-to-book grounding guard
# ---------------------------------------------------------------------------

from app.models.curriculum import BookPage, PageStatus  # noqa: E402
from app.models.governance import AiAuditLog as _Audit  # noqa: E402


async def _seed_grounded_book(factory, *, status: BookStatus):
    async with factory() as session:
        grade = await session.scalar(select(Grade).where(Grade.number == 7))
        book = Book(
            title="ریاضی هفتم",
            grade_id=grade.id,
            pdf_file_path="x.pdf",
            total_pdf_pages=10,
            status=status,
            catalog_status="approved" if status == BookStatus.ready else "legacy_unverified",
        )
        session.add(book)
        await session.flush()
        session.add(
            BookPage(
                book_id=book.id,
                pdf_page_index=4,
                printed_page_number=12,
                chapter_number=2,
                chapter_title="کسرها",
                markdown_content="کسر",
                page_image_path="page-4.png",
                status=PageStatus.done,
            )
        )
        await session.commit()
        return book.id


def _citation(book_id: int, **overrides) -> dict:
    base = {"book_id": book_id, "pdf_page_index": 4, "printed_page_number": 12, "chapter_number": 2}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_grounding_guard_accepts_correct_citations_and_flags_bad_ones(tmp_path, monkeypatch):
    from app.services import ai_gateway
    from app.services.grounding_guard import check_textbook_grounding

    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_gateway, "async_session_factory", factory)
    try:
        book_id = await _seed_grounded_book(factory, status=BookStatus.ready)
        async with factory() as session:
            good = await check_textbook_grounding(
                session, capability_key="tutor", feature_key="chat", book_id=book_id,
                citations=[_citation(book_id)],
            )
            assert good == {"checked": True, "ok": True, "issues": []}

            wrong_page = await check_textbook_grounding(
                session, capability_key="tutor", feature_key="chat", book_id=book_id,
                citations=[_citation(book_id, printed_page_number=99)],
            )
            assert wrong_page["ok"] is False
            assert wrong_page["issues"][0]["code"] == "printed_page_mismatch"

            cross = await check_textbook_grounding(
                session, capability_key="tutor", feature_key="chat", book_id=book_id,
                citations=[_citation(book_id + 1)],
            )
            assert cross["issues"][0]["code"] == "cross_book"

            missing_page = await check_textbook_grounding(
                session, capability_key="tutor", feature_key="chat", book_id=book_id,
                citations=[_citation(book_id, pdf_page_index=77)],
            )
            assert missing_page["issues"][0]["code"] == "page_missing"

        async with factory() as session:
            flagged = (
                await session.scalars(select(_Audit).where(_Audit.flag_reason == "grounding_mismatch"))
            ).all()
            # Three bad checks above -> three flagged decision rows; the good one writes nothing.
            assert len(flagged) == 3
            assert all(row.status == "flagged" for row in flagged)
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_grounding_guard_flags_book_that_is_not_ready(tmp_path, monkeypatch):
    from app.services import ai_gateway
    from app.services.grounding_guard import check_textbook_grounding

    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_gateway, "async_session_factory", factory)
    try:
        book_id = await _seed_grounded_book(factory, status=BookStatus.created)
        async with factory() as session:
            result = await check_textbook_grounding(
                session, capability_key="tutor", feature_key="chat", book_id=book_id,
                citations=[_citation(book_id)],
            )
            assert result["issues"][0]["code"] == "book_not_ready"
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_text_call_runs_grounding_guard(tmp_path, monkeypatch):
    """Wiring: run_capability_text must invoke the guard and flag a bad citation."""
    from app.services import ai_gateway, capability_runtime
    from app.services.ai_gateway import GatewayResult

    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_gateway, "async_session_factory", factory)

    async def fake_complete_text(**kwargs):
        return GatewayResult(content="پاسخ آزمایشی", status="success")

    monkeypatch.setattr(capability_runtime, "complete_text_via_gateway", fake_complete_text)
    try:
        book_id = await _seed_grounded_book(factory, status=BookStatus.ready)
        async with factory() as session:
            await capability_runtime.run_capability_text(
                session=session,
                capability_key="tutor",
                user_text="سؤال",
                book_id=book_id,
                citations=[_citation(book_id, printed_page_number=500)],
                enforce=False,
            )
        async with factory() as session:
            rows = (
                await session.scalars(select(_Audit).where(_Audit.flag_reason == "grounding_mismatch"))
            ).all()
            assert len(rows) == 1
            assert rows[0].status == "flagged"
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.asyncio
async def test_audit_logs_filter_by_flag_reason(tmp_path, monkeypatch):
    """flag_reason is an exact-match filter; flagged_only keeps working alongside it."""
    engine, factory, _settings = await _build_env(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            session.add(
                _Audit(
                    feature_key="chat",
                    model_name="m",
                    request_messages_json=[{"role": "user", "content": "q1"}],
                    response_text="answer 1",
                    rag_citations_json=[],
                    status="flagged",
                    flag_reason="grounding_mismatch",
                )
            )
            session.add(
                _Audit(
                    feature_key="chat",
                    model_name="m",
                    request_messages_json=[{"role": "user", "content": "q2"}],
                    response_text="answer 2",
                    rag_citations_json=[],
                    status="flagged",
                    flag_reason="rag_miss",
                )
            )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            grounded = await client.get(
                "/api/v1/admin/audit-logs?flag_reason=grounding_mismatch",
                headers=ADMIN_HEADERS,
            )
            assert grounded.status_code == 200, grounded.text
            assert grounded.json()["total"] == 1
            assert grounded.json()["items"][0]["flag_reason"] == "grounding_mismatch"

            other = await client.get(
                "/api/v1/admin/audit-logs?flag_reason=rag_miss", headers=ADMIN_HEADERS
            )
            assert other.json()["total"] == 1
            assert other.json()["items"][0]["flag_reason"] == "rag_miss"

            # A different (known) reason must not return the grounding row.
            assert all(
                item["flag_reason"] != "grounding_mismatch"
                for item in other.json()["items"]
            )

            # flagged_only composes with the reason filter.
            both = await client.get(
                "/api/v1/admin/audit-logs?flag_reason=grounding_mismatch&flagged_only=true",
                headers=ADMIN_HEADERS,
            )
            assert both.json()["total"] == 1

            # Unknown reasons are rejected by the allowlist, not silently ignored.
            unknown = await client.get(
                "/api/v1/admin/audit-logs?flag_reason=nope", headers=ADMIN_HEADERS
            )
            assert unknown.status_code == 422
    finally:
        app.dependency_overrides.clear()
        await rate_limiter.close_rate_limiter()
        await engine.dispose()
