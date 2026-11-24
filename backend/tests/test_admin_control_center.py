"""Tests for All-in-One Admin Control Center: runtime config/AI/gateways, overview, book lifecycle, and user sessions."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pymupdf
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import admin as admin_api
from app.core import config as config_mod
from app.core import runtime_config
from app.db import session as db_session_mod
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.main import app
from app.models.auth import (
    BillingSettings,
    PaymentTransaction,
    TokenUsageLog,
    User,
    UserSession,
)
from app.models.chat import ChatSession
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.models.exam import ExamSession, ExamStatus
from app.services import auth_billing_service, ingestion_service, retrieval_service


async def _setup_admin_control_db(tmp_path: Path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin_control.sqlite3'}")
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

    return engine, factory, storage_dir


@pytest.mark.asyncio
async def test_new_admin_endpoints_require_authentication():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for method, path in (
            ("GET", "/api/v1/admin/overview"),
            ("GET", "/api/v1/admin/settings"),
            ("PUT", "/api/v1/admin/settings"),
            ("POST", "/api/v1/admin/settings/reset"),
            ("POST", "/api/v1/admin/settings/test-ai"),
            ("POST", "/api/v1/admin/settings/test-vector"),
            ("POST", "/api/v1/admin/settings/test-sms"),
            ("PATCH", "/api/v1/admin/books/1"),
            ("DELETE", "/api/v1/admin/books/1"),
            ("POST", "/api/v1/admin/books/1/reindex"),
            ("POST", "/api/v1/admin/books/1/reprocess"),
            ("GET", "/api/v1/admin/users/fake-user/sessions"),
            ("POST", "/api/v1/admin/users/fake-user/revoke-sessions"),
        ):
            res = await client.request(method, path)
            assert res.status_code == 401, f"{method} {path} returned {res.status_code}"


@pytest.mark.asyncio
async def test_admin_runtime_settings_masking_reset_and_cookie_invariance(tmp_path, monkeypatch):
    engine, factory, _ = await _setup_admin_control_db(tmp_path, monkeypatch)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login_res = await client.post(
                "/api/v1/admin/auth/login",
                json={"username": "admin", "password": "123"},
            )
            assert login_res.status_code == 200

            user_key_before = auth_billing_service._user_signing_key()

            # 1. GET initial masked settings
            initial = await client.get("/api/v1/admin/settings")
            assert initial.status_code == 200
            body = initial.json()
            assert "admin_username" not in body["config"]
            assert "admin_password" not in body["config"]
            assert body["secrets"]["llm_api_key"]["configured"] is True
            assert body["secrets"]["llm_api_key"]["source"] == "env"
            assert "unit-test-key" not in str(body)

            # 2. Invalid URL scheme must fail with 422
            bad_url = await client.put(
                "/api/v1/admin/settings",
                json={"config": {"llm_base_url": "ftp://invalid.example.com/v1"}},
            )
            assert bad_url.status_code == 422

            # 3. Valid live update of base URL, secret API key, demo_mode, and tutor_model
            update = await client.put(
                "/api/v1/admin/settings",
                json={
                    "config": {
                        "demo_mode": False,
                        "llm_base_url": "https://api.avalai.ir/v1/",
                        "llm_api_key": "sk-secret-override-9999",
                        "tutor_model": "gpt-4o-mini",
                    }
                },
            )
            assert update.status_code == 200
            updated = update.json()
            assert updated["config"]["demo_mode"] is False
            assert updated["config"]["llm_base_url"] == "https://api.avalai.ir/v1"
            assert updated["config"]["tutor_model"] == "gpt-4o-mini"
            assert updated["secrets"]["llm_api_key"]["source"] == "admin"
            assert "sk-secret-override-9999" not in str(updated)

            live = config_mod.get_settings()
            assert live.demo_mode is False
            assert live.llm_base_url == "https://api.avalai.ir/v1"
            assert live.llm_api_key == "sk-secret-override-9999"
            assert live.tutor_model == "gpt-4o-mini"

            # Admin cookie and user signing key must stay invariant across llm_api_key changes
            assert auth_billing_service._user_signing_key() == user_key_before
            session_check = await client.get("/api/v1/admin/auth/session")
            assert session_check.status_code == 200
            assert session_check.json() == {"authenticated": True, "username": "admin"}

            # 4. Submitting blank secret leaves override intact; clear_secrets wipes it
            keep_secret = await client.put(
                "/api/v1/admin/settings",
                json={"config": {"llm_api_key": "", "tutor_model": "gpt-4.1-mini"}},
            )
            assert keep_secret.status_code == 200
            assert config_mod.get_settings().llm_api_key == "sk-secret-override-9999"

            # 5. Simulate restart by clearing memory and rehydrating from DB
            runtime_config.set_runtime_overrides({})
            assert config_mod.get_settings().llm_api_key == config_mod.get_base_settings().llm_api_key
            await runtime_config.load_runtime_overrides_from_db()
            assert config_mod.get_settings().llm_api_key == "sk-secret-override-9999"
            assert config_mod.get_settings().tutor_model == "gpt-4.1-mini"

            clear_secret = await client.put(
                "/api/v1/admin/settings",
                json={"config": {}, "clear_secrets": ["llm_api_key"]},
            )
            assert clear_secret.status_code == 200
            assert clear_secret.json()["secrets"]["llm_api_key"]["source"] == "env"
            assert config_mod.get_settings().llm_api_key == config_mod.get_base_settings().llm_api_key

            # 6. Section reset and full reset
            reset_ai = await client.post("/api/v1/admin/settings/reset", json={"section": "ai"})
            assert reset_ai.status_code == 200
            assert config_mod.get_settings().tutor_model == config_mod.get_base_settings().tutor_model
            assert config_mod.get_settings().demo_mode is False

            reset_all = await client.post("/api/v1/admin/settings/reset", json={"section": "all"})
            assert reset_all.status_code == 200
            async with factory() as session:
                bs = await session.get(BillingSettings, 1)
                assert bs is not None
                assert bs.system_config == {}
    finally:
        runtime_config.set_runtime_overrides({})
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_diagnostics_ai_vector_sms(tmp_path, monkeypatch):
    engine, _, _ = await _setup_admin_control_db(tmp_path, monkeypatch)
    try:
        # Outbound provider/Qdrant transport now lives behind the service seams:
        # ai_gateway.probe_endpoint (shared by /settings/test-ai and
        # /admin/providers/{id}/test) and retrieval_service.probe_qdrant.
        from app.services import ai_gateway

        probe_calls: list[dict[str, object]] = []

        async def _fake_probe_endpoint(
            *,
            base_url,
            api_key,
            provider_type=None,
            model=None,
            run_prompt=True,
            include_models=True,
        ):
            probe_calls.append({"base_url": base_url, "api_key": api_key, "model": model})
            if api_key == "sk-secret-leak":
                return {
                    "ok": False,
                    "base_url": base_url,
                    "status_code": 401,
                    "models": [],
                    "models_count": 0,
                    "latency_ms": 7,
                    "error": "HTTP 401",  # secret already scrubbed upstream
                    "prompt_test": None,
                }
            return {
                "ok": True,
                "base_url": base_url,
                "status_code": 200,
                "models": ["gemini-2.5-flash", "gpt-4o"],
                "models_count": 2,
                "latency_ms": 11,
                "error": None,
                "prompt_test": (
                    {
                        "ok": True,
                        "model": model,
                        "status_code": 200,
                        "latency_ms": 5,
                        "reply": "سلام",
                        "usage": {"total_tokens": 5},
                    }
                    if run_prompt
                    else None
                ),
            }

        async def _fake_probe_qdrant(url=None, collection=None):
            return {
                "ok": True,
                "backend": "qdrant",
                "latency_ms": 3,
                "detail": "اتصال به Qdrant برقرار شد.",
                "collection_info": {"collections": [], "target_exists": False},
            }

        monkeypatch.setattr(ai_gateway, "probe_endpoint", _fake_probe_endpoint)
        monkeypatch.setattr(retrieval_service, "probe_qdrant", _fake_probe_qdrant)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/v1/admin/auth/login", json={"username": "admin", "password": "123"})

            ai_ok = await client.post(
                "/api/v1/admin/settings/test-ai",
                json={
                    "llm_base_url": "https://api.avalai.ir/v1",
                    "llm_api_key": "sk-good-test",
                    "test_model": "gpt-4o",
                    "run_prompt": True,
                },
            )
            assert ai_ok.status_code == 200
            ai_data = ai_ok.json()
            assert ai_data["ok"] is True
            assert ai_data["models"] == ["gemini-2.5-flash", "gpt-4o"]
            assert ai_data["prompt_test"]["ok"] is True
            assert ai_data["prompt_test"]["reply"] == "سلام"

            # Secret must be redacted if upstream error reflects it
            ai_err = await client.post(
                "/api/v1/admin/settings/test-ai",
                json={"llm_base_url": "https://api.avalai.ir/v1", "llm_api_key": "sk-secret-leak"},
            )
            assert ai_err.status_code == 200
            err_data = ai_err.json()
            assert err_data["ok"] is False
            assert "sk-secret-leak" not in (err_data["error"] or "")

            vec_res = await client.post(
                "/api/v1/admin/settings/test-vector",
                json={"vector_backend": "qdrant", "qdrant_url": "http://qdrant.local:6333"},
            )
            assert vec_res.status_code == 200
            assert vec_res.json()["backend"] == "qdrant"
            assert vec_res.json()["ok"] is True

            sms_res = await client.post(
                "/api/v1/admin/settings/test-sms",
                json={"sms_provider": "demo", "test_phone": "09123456789"},
            )
            assert sms_res.status_code == 200
            assert sms_res.json()["ok"] is True
            assert sms_res.json()["provider"] == "demo"
    finally:
        runtime_config.set_runtime_overrides({})
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_overview_kpis_queues_and_infra(tmp_path, monkeypatch):
    engine, factory, _ = await _setup_admin_control_db(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            grade = await session.scalar(select(Grade).where(Grade.number == 12))
            major = await session.scalar(select(Major).where(Major.code == "math_physics"))

            book = Book(
                title="فیزیک دوازدهم آزمایشی",
                grade_id=grade.id,
                major_id=major.id,
                pdf_file_path="/tmp/phys.pdf",
                total_pdf_pages=2,
                status=BookStatus.ready,
                catalog_status="approved",
            )
            session.add(book)
            await session.flush()

            session.add_all(
                [
                    BookPage(
                        book_id=book.id,
                        pdf_page_index=1,
                        markdown_content="صفحه ۱",
                        page_image_path="/tmp/p1.png",
                        status=PageStatus.done,
                    ),
                    BookPage(
                        book_id=book.id,
                        pdf_page_index=2,
                        chapter_title="دینامیک",
                        markdown_content="صفحه نیازمند بررسی",
                        page_image_path="/tmp/p2.png",
                        status=PageStatus.needs_review,
                    ),
                ]
            )

            user = User(
                phone_number="09120001122",
                full_name="دانش‌آموز تست",
                plan_code="starter",
                plan_title="اقتصادی",
                tokens_remaining=5000,
                tokens_used_total=250,
                is_active=True,
            )
            session.add(user)
            await session.flush()

            session.add(
                UserSession(
                    user_id=user.id,
                    token_nonce="nonce-123",
                    ip_address="198.51.100.1",
                    user_agent="pytest-agent",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=2),
                )
            )
            session.add(
                PaymentTransaction(
                    user_id=user.id,
                    plan_code="starter",
                    plan_name="اقتصادی",
                    amount_toman=129000,
                    tokens_granted=100000,
                    duration_days=30,
                    provider="zarinpal",
                    authority="AUTH-001",
                    status="paid",
                )
            )
            session.add(
                TokenUsageLog(
                    user_id=user.id,
                    action="tutor_chat",
                    book_id=book.id,
                    prompt_tokens=150,
                    completion_tokens=100,
                    total_tokens=250,
                    cost_toman=15,
                )
            )
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/v1/admin/auth/login", json={"username": "admin", "password": "123"})
            res = await client.get("/api/v1/admin/overview")
            assert res.status_code == 200
            data = res.json()
            assert data["counts"]["books_total"] == 1
            assert data["counts"]["pages_total"] == 2
            assert data["counts"]["pages_needs_review"] == 1
            assert data["counts"]["users_total"] == 1
            assert data["counts"]["active_sessions"] == 1
            assert data["counts"]["revenue_toman"] == 129000
            assert data["counts"]["tokens_used_total"] == 250
            assert len(data["needs_review_pages"]) == 1
            assert data["needs_review_pages"][0]["pdf_page_index"] == 2
            assert len(data["recent_transactions"]) == 1
            assert data["recent_transactions"][0]["amount_toman"] == 129000
            assert len(data["recent_usage_logs"]) == 1
            assert data["recent_usage_logs"][0]["action"] == "tutor_chat"
            assert "unit-test-key" not in str(data)
    finally:
        runtime_config.set_runtime_overrides({})
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_book_lifecycle_patch_reindex_reprocess_delete(tmp_path, monkeypatch):
    engine, factory, storage_dir = await _setup_admin_control_db(tmp_path, monkeypatch)
    try:
        demo_dir = storage_dir / "demo"
        demo_dir.mkdir(parents=True, exist_ok=True)
        demo_pdf = demo_dir / "math.pdf"
        pdf_doc = pymupdf.open()
        pdf_doc.new_page()
        pdf_doc.save(str(demo_pdf))
        pdf_doc.close()

        async with factory() as session:
            grade12 = await session.scalar(select(Grade).where(Grade.number == 12))
            major = await session.scalar(select(Major).where(Major.code == "math_physics"))
            book = Book(
                title="ریاضی دوازدهم",
                grade_id=grade12.id,
                major_id=major.id,
                pdf_file_path=str(demo_pdf),
                total_pdf_pages=1,
                status=BookStatus.ready,
                catalog_status="approved",
            )
            session.add(book)
            await session.flush()

            book_dir = storage_dir / "books" / str(book.id)
            book_dir.mkdir(parents=True, exist_ok=True)
            (book_dir / "page_1.png").write_bytes(b"PNG")

            session.add(
                BookPage(
                    book_id=book.id,
                    pdf_page_index=1,
                    markdown_content="حد و پیوستگی",
                    page_image_path=str(book_dir / "page_1.png"),
                    status=PageStatus.done,
                )
            )
            chat = ChatSession(
                id=str(uuid.uuid4()),
                book_id=book.id,
                grade_number=12,
                major_code="math_physics",
                title="جلسه تست",
                mode="teacher",
            )
            exam = ExamSession(
                id=str(uuid.uuid4()),
                book_id=book.id,
                grade_number=12,
                major_code="math_physics",
                title="آزمون تست",
                exam_type="konkoor",
                status=ExamStatus.active,
                questions=[],
                time_limit_seconds=600,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            session.add_all([chat, exam])
            await session.commit()
            book_id = book.id

        reindexed_ids: list[int] = []

        async def _fake_index_book(bid: int):
            reindexed_ids.append(bid)
            return {"book_id": bid, "indexed_pages": 1, "total_chunks": 2}

        async def _fake_ingest_book_pages(**kwargs):
            return None

        monkeypatch.setattr(retrieval_service, "index_book", _fake_index_book)
        monkeypatch.setattr(admin_api, "index_book", _fake_index_book)
        monkeypatch.setattr(ingestion_service, "ingest_book_pages", _fake_ingest_book_pages)
        monkeypatch.setattr(admin_api, "_run_ingest_background", _fake_ingest_book_pages)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/v1/admin/auth/login", json={"username": "admin", "password": "123"})

            # 1. PATCH book metadata (invalid major -> 404/422; downgrade to grade 7 clears major)
            patch_bad = await client.patch(
                f"/api/v1/admin/books/{book_id}",
                json={"grade_number": 11, "major_code": "no_such_major"},
            )
            assert patch_bad.status_code in (400, 404, 422)

            patch_ok = await client.patch(
                f"/api/v1/admin/books/{book_id}",
                json={"title": "ریاضی هفتم ویرایش‌شده", "grade_number": 7},
            )
            assert patch_ok.status_code == 200
            assert patch_ok.json()["book"]["title"] == "ریاضی هفتم ویرایش‌شده"
            assert patch_ok.json()["book"]["grade_number"] == 7
            assert patch_ok.json()["book"]["major_code"] is None

            # 2. Reindex fails in demo_mode=True, succeeds in demo_mode=False
            runtime_config.set_runtime_overrides({"demo_mode": True})
            reindex_demo = await client.post(f"/api/v1/admin/books/{book_id}/reindex")
            assert reindex_demo.status_code == 400

            runtime_config.set_runtime_overrides({"demo_mode": False})
            reindex_live = await client.post(f"/api/v1/admin/books/{book_id}/reindex")
            assert reindex_live.status_code == 200
            assert reindex_live.json()["total_chunks"] == 2
            assert reindexed_ids == [book_id]

            # 3. Reprocess schedules background work cleanly and returns 200
            reprocess_res = await client.post(f"/api/v1/admin/books/{book_id}/reprocess")
            assert reprocess_res.status_code == 200
            assert reprocess_res.json()["status"] == "ingesting"

            # 4. Delete blocked with 409 because ChatSession & ExamSession depend on the book
            del_conflict = await client.delete(f"/api/v1/admin/books/{book_id}")
            assert del_conflict.status_code == 409

            # 5. Force delete cleans dependents, book, and books/{id} dir while preserving demo PDF
            del_force = await client.delete(f"/api/v1/admin/books/{book_id}?force=true")
            assert del_force.status_code == 200
            assert del_force.json()["deleted"] is True
            assert del_force.json()["book_id"] == book_id
            assert not (storage_dir / "books" / str(book_id)).exists()
            assert demo_pdf.exists()
    finally:
        runtime_config.set_runtime_overrides({})
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_user_sessions_and_revoke(tmp_path, monkeypatch):
    engine, factory, _ = await _setup_admin_control_db(tmp_path, monkeypatch)
    try:
        async with factory() as session:
            user = User(
                phone_number="09127778899",
                full_name="کاربر نشست‌ها",
                plan_code="starter",
                plan_title="اقتصادی",
                tokens_remaining=1000,
                is_active=True,
            )
            session.add(user)
            await session.flush()

            session.add_all(
                [
                    UserSession(
                        user_id=user.id,
                        token_nonce="tok-a",
                        ip_address="203.0.113.10",
                        user_agent="Mozilla/5.0",
                        expires_at=datetime.now(timezone.utc) + timedelta(days=5),
                    ),
                    UserSession(
                        user_id=user.id,
                        token_nonce="tok-b",
                        ip_address="203.0.113.11",
                        user_agent="Safari",
                        expires_at=datetime.now(timezone.utc) + timedelta(days=5),
                    ),
                ]
            )
            await session.commit()
            user_id = user.id

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/v1/admin/auth/login", json={"username": "admin", "password": "123"})

            sessions_res = await client.get(f"/api/v1/admin/users/{user_id}/sessions")
            assert sessions_res.status_code == 200
            sessions_list = sessions_res.json()["sessions"]
            assert len(sessions_list) == 2
            assert all(item["is_active"] is True for item in sessions_list)

            revoke_res = await client.post(f"/api/v1/admin/users/{user_id}/revoke-sessions")
            assert revoke_res.status_code == 200
            assert revoke_res.json()["revoked_count"] == 2

            after_res = await client.get(f"/api/v1/admin/users/{user_id}/sessions")
            assert after_res.status_code == 200
            assert all(item["is_active"] is False for item in after_res.json()["sessions"])
    finally:
        runtime_config.set_runtime_overrides({})
        await engine.dispose()
