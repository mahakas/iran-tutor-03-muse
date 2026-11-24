"""Phase 06 tests: previously-unaudited admin mutations now write AdminActionLog rows.

The Phase 05/earlier contract already audited user management and the education
catalog via their own services. This file closes the audit hole on the legacy
admin surface (books lifecycle, providers, model routes, quotas, billing,
runtime settings) through the shared `admin_action_log` helper, and asserts
secret values never leak into audit payloads.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import admin as admin_api
from app.core import runtime_config
from app.db import session as db_session_mod
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.main import app
from app.models.curriculum import Book, BookStatus, Grade, Major
from app.models.governance import AiProvider, FeatureModelRoute
from app.models.phase5 import AdminActionLog
from app.services import ingestion_service


async def _setup_env(tmp_path: Path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase06_audit.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(admin_api, "async_session_factory", factory)
    monkeypatch.setattr(db_session_mod, "async_session_factory", factory)
    monkeypatch.setattr(ingestion_service, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(admin_api, "STORAGE_DIR", storage_dir)
    monkeypatch.setattr(runtime_config, "_runtime_overrides", {})

    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        await session.commit()

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[admin_api.get_session] = override_get_session
    return engine, factory, storage_dir


async def _login_admin(client: AsyncClient) -> None:
    login = await client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "123"},
    )
    assert login.status_code == 200, login.text


async def _actions(factory, *actions: str) -> list[AdminActionLog]:
    async with factory() as session:
        rows = (
            await session.scalars(
                select(AdminActionLog).where(AdminActionLog.action.in_(list(actions))).order_by(AdminActionLog.id)
            )
        ).all()
        return list(rows)


@pytest.mark.asyncio
async def test_book_lifecycle_mutations_are_audited(tmp_path, monkeypatch):
    engine, factory, _ = await _setup_env(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            grade12 = await session.scalar(select(Grade).where(Grade.number == 12))
            major = await session.scalar(select(Major).where(Major.code == "math_physics"))
            book = Book(
                title="ریاضی دوازدهم",
                grade_id=grade12.id,
                major_id=major.id,
                pdf_file_path="/tmp/phase06-none.pdf",
                total_pdf_pages=1,
                status=BookStatus.ready,
                catalog_status="approved",
            )
            session.add(book)
            await session.commit()
            book_id = book.id

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _login_admin(client)
            patch = await client.patch(
                f"/api/v1/admin/books/{book_id}",
                json={"status": "ingesting"},
            )
            assert patch.status_code == 200, patch.text
            delete = await client.delete(f"/api/v1/admin/books/{book_id}?force=true")
            assert delete.status_code == 200, delete.text

        rows = await _actions(factory, "book.update", "book.delete")
        assert [row.action for row in rows] == ["book.update", "book.delete"]
        assert all(row.actor == "admin-console" for row in rows)
        update_payload = rows[0].payload_json
        assert "status" in update_payload["changed_fields"]
        assert update_payload["status_after"] == "ingesting"
        assert rows[0].target == f"book:{book_id}"
        delete_payload = rows[1].payload_json
        assert delete_payload["title"] == "ریاضی دوازدهم" and delete_payload["force"] is True
    finally:
        app.dependency_overrides.pop(admin_api.get_session, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_provider_and_route_mutations_are_audited_without_secrets(tmp_path, monkeypatch):
    engine, factory, _ = await _setup_env(tmp_path, monkeypatch)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _login_admin(client)
            create = await client.post(
                "/api/v1/admin/providers",
                json={
                    "name": "QA Provider",
                    "provider_type": "openai_compatible",
                    "base_url": "https://api.example.com/v1",
                    "capabilities": ["text"],
                    "api_key": "sk-super-secret-31337",
                },
            )
            assert create.status_code == 200, create.text
            provider_id = create.json()["provider"]["id"]

            route = await client.put(
                "/api/v1/admin/routes",
                json={
                    "feature_key": "chat",
                    "provider_id": provider_id,
                    "model_name": "test-model",
                    "temperature": 0.2,
                    "max_tokens": 1024,
                },
            )
            assert route.status_code == 200, route.text

            update = await client.put(
                f"/api/v1/admin/providers/{provider_id}",
                json={"is_active": False, "clear_api_key": True},
            )
            assert update.status_code == 200, update.text

            route_delete = await client.delete("/api/v1/admin/routes/chat")
            assert route_delete.status_code == 200, route_delete.text

            provider_delete = await client.delete(f"/api/v1/admin/providers/{provider_id}")
            assert provider_delete.status_code == 200, provider_delete.text

        rows = await _actions(
            factory, "provider.create", "provider.update", "provider.delete", "route.set", "route.delete"
        )
        assert [row.action for row in rows] == [
            "provider.create",
            "route.set",
            "provider.update",
            "route.delete",
            "provider.delete",
        ]
        assert all(row.actor == "admin-console" for row in rows)
        create_payload = rows[0].payload_json
        assert create_payload["name"] == "QA Provider"
        # The API key itself must never appear anywhere in the audit trail.
        assert "sk-super-secret-31337" not in str(create_payload)
        update_payload = rows[2].payload_json
        assert "is_active" in update_payload["changed_fields"]
        assert update_payload["clear_api_key"] is True
        assert rows[1].target == "route:chat"
        async with factory() as session:
            assert await session.get(AiProvider, provider_id) is None
            assert (
                await session.scalar(select(FeatureModelRoute).where(FeatureModelRoute.feature_key == "chat"))
                is None
            )
    finally:
        app.dependency_overrides.pop(admin_api.get_session, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_quota_billing_and_settings_are_audited(tmp_path, monkeypatch):
    engine, factory, _ = await _setup_env(tmp_path, monkeypatch)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await _login_admin(client)

            feature = await client.put(
                "/api/v1/admin/quotas/features/tutor",
                json={"daily_requests": 40},
            )
            assert feature.status_code == 200, feature.text

            policy = await client.put(
                "/api/v1/admin/quotas",
                json={"daily_requests": 500, "daily_tokens": 90000},
            )
            assert policy.status_code == 200, policy.text

            billing = await client.put(
                "/api/v1/admin/billing/settings",
                json={"token_price_per_1k_toman": 1200, "starter_tokens": 18000, "starter_duration_days": 35},
            )
            assert billing.status_code == 200, billing.text

            plan = await client.put(
                "/api/v1/admin/billing/plans/pro",
                json={"price_toman": 390000},
            )
            assert plan.status_code == 200, plan.text

            settings = await client.put(
                "/api/v1/admin/settings",
                json={"config": {"llm_api_key": "sk-settings-secret-777", "tutor_model": "gpt-4o-mini"}},
            )
            assert settings.status_code == 200, settings.text

        rows = await _actions(
            factory, "quota.feature.set", "quota.policy.update", "billing.settings.update", "billing.plan.update", "settings.update"
        )
        by_action = {row.action: row for row in rows}
        assert set(by_action) == {
            "quota.feature.set",
            "quota.policy.update",
            "billing.settings.update",
            "billing.plan.update",
            "settings.update",
        }
        assert by_action["quota.feature.set"].payload_json["override"]["daily_requests"] == 40
        assert by_action["quota.policy.update"].payload_json["policy"]["daily_tokens"] == 90000
        assert by_action["billing.settings.update"].payload_json["starter_tokens"] == 18000
        assert by_action["billing.plan.update"].target == "plan:pro"
        # Settings audit stores field NAMES only; the secret value never leaks.
        settings_payload = by_action["settings.update"].payload_json
        assert "llm_api_key" in settings_payload["changed_fields"]
        assert "sk-settings-secret-777" not in str(settings_payload)
    finally:
        app.dependency_overrides.pop(admin_api.get_session, None)
        await engine.dispose()
