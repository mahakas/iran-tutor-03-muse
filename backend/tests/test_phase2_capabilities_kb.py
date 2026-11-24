"""Phase 2 tests: capability registry & feature flags, skills + shared capability
runtime (versioning / rollback), typed learning blocks, and the web KB pipeline
(background job tracking, source figures, single-page/chapter re-index hooks,
model benchmark) — with admin-only authorization and gateway isolation.

No test performs network I/O: gateway-bound paths are exercised only through
their pure helpers and the DB-level service functions.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.capabilities import Capability, KbIngestionJob, Skill, SkillVersion, SourceFigure
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.services import (
    capability_runtime,
    capability_service,
    kb_ingestion_service,
    learning_blocks,
    retrieval_service,
    skill_seed,
)

ADMIN_HEADERS = {"X-Admin-Username": "admin", "X-Admin-Password": "123"}
BACKEND_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


async def _build_db(tmp_path, monkeypatch, *, seed_phase2: bool = True):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase2.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        if seed_phase2:
            await capability_service.seed_capabilities(session)
            await skill_seed.seed_skills(session)
        await session.commit()

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    from app.db import session as db_session_mod

    monkeypatch.setattr(db_session_mod, "async_session_factory", factory)
    for module_name in (
        "app.api.admin",
        "app.api.kb",
        "app.api.capabilities",
        "app.api.skills",
        "app.services.kb_ingestion_service",
        "app.services.capability_runtime",
    ):
        module = __import__(module_name, fromlist=["x"])
        if hasattr(module, "async_session_factory"):
            monkeypatch.setattr(module, "async_session_factory", factory)

    settings = SimpleNamespace(
        demo_mode=True,
        admin_username="admin",
        admin_password="123",
        admin_session_ttl_seconds=3600,
        admin_session_secret=None,
        secret_key="phase2-test-secret-key",
        auth_secret="phase2-auth-secret",
        llm_api_key="phase2-llm-key",
        llm_base_url="https://example.invalid/v1",
        tutor_model="route-default-model",
        vision_model_primary="route-vision-model",
        vision_model_escalation=None,
        speech_to_text_model="route-stt-model",
        embedding_model="route-embed-model",
        otp_ttl_seconds=300,
        otp_resend_seconds=0,
        otp_max_attempts=5,
        user_session_ttl_seconds=86400,
        redis_url=None,
        rate_limit_enabled=False,
        sms_provider="demo",
        payment_provider="demo",
        qdrant_url="http://127.0.0.1:6333",
        qdrant_collection="test",
        zarinpal_merchant_id=None,
        zarinpal_sandbox=False,
        public_app_url=None,
        sms_api_key=None,
        sms_template=None,
        sms_sender=None,
        sms_webhook_url=None,
        vision_model_a="route-vision-a",
        vision_model_b="route-vision-b",
        vector_backend="qdrant",
        embedding_base_url=None,
        embedding_api_key=None,
        embedding_dimension=64,
        audio_base_url=None,
        audio_api_key=None,
        escalate_figures=False,
        llm_timeout=30,
        max_concurrency=2,
        storage_dir=str(tmp_path / "storage"),
    )
    for module_path in (
        "app.api.admin",
        "app.api.kb",
        "app.api.capabilities",
        "app.api.skills",
        "app.core.config",
        "app.core.crypto",
        "app.core.llm_client",
        "app.services.ai_gateway",
        "app.services.kb_ingestion_service",
        "app.services.ingestion_service",
        "app.services.quota_service",
        "app.services.rate_limiter",
    ):
        monkeypatch.setattr(f"{module_path}.get_settings", lambda: settings, raising=False)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr(kb_ingestion_service, "STORAGE_DIR", tmp_path / "storage")
    return engine, factory


@pytest.fixture
async def phase2_env(tmp_path, monkeypatch):
    engine, factory = await _build_db(tmp_path, monkeypatch)
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_session, None)
        await engine.dispose()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# 1. Capability registry & feature flags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_capabilities_is_idempotent_and_flashcards_enabled_phase3(phase2_env):
    async with phase2_env() as session:
        await capability_service.seed_capabilities(session)
        await session.commit()
        rows = list((await session.scalars(select(Capability))).all())
    keys = {row.key: row for row in rows}
    assert {"chat", "solve", "quiz", "multimodal", "flashcards"} <= set(keys)
    assert keys["flashcards"].is_enabled is True
    assert keys["chat"].is_enabled is True
    assert len(rows) == len(capability_service.SEED_CAPABILITIES)


@pytest.mark.asyncio
async def test_seed_capabilities_never_overwrites_admin_edits(phase2_env):
    async with phase2_env() as session:
        cap = await session.get(Capability, "chat")
        cap.is_enabled = False
        cap.title_fa = "ویرایش ادمین"
        await session.commit()
        await capability_service.seed_capabilities(session)
        await session.commit()
        await session.refresh(cap)
    assert cap.is_enabled is False
    assert cap.title_fa == "ویرایش ادمین"


def test_capability_role_and_plan_allow_list():
    cap = Capability(
        key="x",
        title_fa="x",
        is_enabled=True,
        allowed_roles_json=["admin"],
        allowed_plans_json=[],
    )
    assert capability_service.is_capability_allowed(cap, role="admin", plan_code=None)
    assert not capability_service.is_capability_allowed(cap, role="student", plan_code=None)
    cap.allowed_roles_json = []
    cap.allowed_plans_json = ["pro"]
    assert capability_service.is_capability_allowed(cap, role="student", plan_code="pro")
    assert not capability_service.is_capability_allowed(cap, role="student", plan_code="trial")
    cap.is_enabled = False
    assert not capability_service.is_capability_allowed(cap, role="admin", plan_code="pro")


@pytest.mark.asyncio
async def test_capabilities_me_lists_flashcards_when_enabled(phase2_env):
    async with _client() as client:
        resp = await client.get("/api/v1/capabilities/me")
    assert resp.status_code == 200
    body = resp.json()
    keys = {item["key"] for item in body["capabilities"]}
    assert "chat" in keys and "quiz" in keys
    assert "flashcards" in keys  # enabled by default from Phase 3
    # Serialized payload must describe the menu, not expose internal config.
    for item in body["capabilities"]:
        assert "config" not in item or isinstance(item["config"], dict)


@pytest.mark.asyncio
async def test_admin_capability_endpoints_require_admin_and_toggle_flag(phase2_env):
    async with _client() as client:
        anon = await client.get("/api/v1/admin/capabilities")
        assert anon.status_code == 401
        listing = await client.get("/api/v1/admin/capabilities", headers=ADMIN_HEADERS)
        assert listing.status_code == 200
        assert any(c["key"] == "flashcards" for c in listing.json()["capabilities"])
        toggled = await client.put(
            "/api/v1/admin/capabilities/flashcards",
            headers=ADMIN_HEADERS,
            json={"is_enabled": True},
        )
        assert toggled.status_code == 200
        assert toggled.json()["is_enabled"] is True
        bad_role = await client.put(
            "/api/v1/admin/capabilities/chat",
            headers=ADMIN_HEADERS,
            json={"allowed_roles": ["wizard"]},
        )
        assert bad_role.status_code == 422
        me = await client.get("/api/v1/capabilities/me")
    assert "flashcards" in {c["key"] for c in me.json()["capabilities"]}


# ---------------------------------------------------------------------------
# 2. Skills & shared capability runtime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_skills_reproduce_existing_prompts_verbatim(phase2_env):
    from app.services.tutor_service import SYSTEM_PROMPT

    async with phase2_env() as session:
        skill = await capability_runtime.get_skill_by_slug(session, "tutor_core")
        flash = await capability_runtime.get_skill_by_slug(session, "flashcard_generator")
    assert skill is not None and skill.system_prompt == SYSTEM_PROMPT
    assert skill.is_active is True and skill.version == 1
    assert flash is not None and flash.is_active is True  # activated in Phase 3


@pytest.mark.asyncio
async def test_skill_update_creates_immutable_versions_and_rollback(phase2_env):
    async with phase2_env() as session:
        original = (await capability_runtime.get_skill_by_slug(session, "tutor_core")).system_prompt
        updated = await capability_runtime.update_skill(
            session, "tutor_core", system_prompt="PROMPT V2", updated_by="admin", change_note="تست"
        )
        assert updated.version == 2
        rolled = await capability_runtime.rollback_skill(
            session, "tutor_core", to_version=1, updated_by="admin"
        )
        await session.commit()
        versions = await capability_runtime.list_skill_versions(session, updated.id)
    assert rolled.system_prompt == original
    assert rolled.version == 3  # rollback is recorded as a new version
    numbers = sorted(v.version for v in versions)
    assert numbers == [1, 2, 3]
    v1 = next(v for v in versions if v.version == 1)
    v2 = next(v for v in versions if v.version == 2)
    assert v1.system_prompt == original
    assert v2.system_prompt == "PROMPT V2"


@pytest.mark.asyncio
async def test_skill_update_rejects_unknown_skill(phase2_env):
    from fastapi import HTTPException

    async with phase2_env() as session:
        with pytest.raises(HTTPException) as info:
            await capability_runtime.update_skill(session, "nope", system_prompt="x")
    assert info.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_skill_api_is_admin_only_and_versioned(phase2_env):
    async with _client() as client:
        anon = await client.get("/api/v1/admin/skills")
        assert anon.status_code == 401
        listing = await client.get("/api/v1/admin/skills", headers=ADMIN_HEADERS)
        assert listing.status_code == 200
        slugs = {s["slug"] for s in listing.json()["skills"]}
        assert {"tutor_core", "solve_core", "quiz_generator", "vision_ocr"} <= slugs
        put = await client.put(
            "/api/v1/admin/skills/solve_core",
            headers=ADMIN_HEADERS,
            json={"pedagogy_rules_md": "قانون تازه"},
        )
        assert put.status_code == 200
        assert put.json()["version"] == 2
        rollback = await client.post(
            "/api/v1/admin/skills/solve_core/rollback",
            headers=ADMIN_HEADERS,
            json={"to_version": 1},
        )
        assert rollback.status_code == 200
        detail = await client.get("/api/v1/admin/skills/solve_core", headers=ADMIN_HEADERS)
    assert detail.status_code == 200
    assert len(detail.json()["versions"]) == 3


def test_compose_system_prompt_includes_rules_and_schema():
    skill = Skill(
        slug="s",
        capability_key="chat",
        title_fa="s",
        system_prompt="BASE",
        pedagogy_rules_md="RULE-A",
        output_schema_json={},
        safety_gate_rules="",
        version=1,
        is_active=True,
    )
    composed = capability_runtime.compose_system_prompt(skill)
    assert "BASE" in composed and "RULE-A" in composed


# ---------------------------------------------------------------------------
# 3. Typed learning blocks
# ---------------------------------------------------------------------------


def test_learning_block_types_match_spec():
    expected = {
        "text_markdown",
        "formula_latex",
        "callout_tip",
        "citation_ref",
        "quiz_item",
        "flashcard_item",
        "diagram_mermaid",
        "diagram_svg",
    }
    assert set(learning_blocks.BLOCK_TYPES) == expected


def test_validate_blocks_drops_unknown_type_and_keeps_valid():
    valid = learning_blocks.validate_blocks(
        [
            {"type": "text_markdown", "content": "سلام $x^2$"},
            {"type": "video_embed", "content": "x"},
            {"type": "formula_latex", "content": "x^2"},
        ]
    )
    assert [b.type for b in valid] == ["text_markdown", "formula_latex"]


def test_parse_blocks_json_and_payload_round_trip():
    raw = '[{"type":"callout_tip","content":"نکته"}]'
    blocks = learning_blocks.parse_blocks_json(raw)
    payload = learning_blocks.blocks_to_payload(blocks)
    assert payload[0]["type"] == "callout_tip"
    assert payload[0]["content"] == "نکته"


def test_blocks_from_answer_adds_one_citation_per_source():
    blocks = learning_blocks.blocks_from_answer(
        "پاسخ نمونه",
        [{"book_title": "ریاضی", "printed_page_number": 12, "chapter_number": 2}],
    )
    types = [b.type for b in blocks]
    assert types[0] == "text_markdown"
    assert types.count("citation_ref") == 1


def test_learning_block_ignores_unknown_extra_fields():
    blocks = learning_blocks.validate_blocks(
        [{"type": "quiz_item", "content": "q", "unknown_extra": 1}]
    )
    assert len(blocks) == 1 and blocks[0].type == "quiz_item"
    assert "unknown_extra" not in blocks[0].model_dump()


# ---------------------------------------------------------------------------
# 4. Web KB pipeline & source figures
# ---------------------------------------------------------------------------


def _make_pdf_with_image(path: Path, pages: int = 2) -> None:
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    pix.set_rect(pix.irect, (200, 30, 30))
    for idx in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"صفحه {idx + 1} متن آزمایشی")
        if idx == 0:
            page.insert_image(pymupdf.Rect(72, 100, 172, 200), pixmap=pix)
    doc.save(path)
    doc.close()


async def _seed_book(session: AsyncSession, pdf_path: Path, pages: int) -> Book:
    grade = await session.scalar(select(Grade).where(Grade.number == 12))
    major = await session.scalar(select(Major).where(Major.code == "math_physics"))
    book = Book(
        title="کتاب آزمایشی",
        grade_id=grade.id,
        major_id=major.id if major else None,
        pdf_file_path=str(pdf_path),
        total_pdf_pages=pages,
        status=BookStatus.ready,
        catalog_status="approved",
    )
    session.add(book)
    await session.flush()
    session.add(
        BookPage(
            book_id=book.id,
            pdf_page_index=1,
            printed_page_number=10,
            chapter_number=3,
            chapter_title="فصل سوم",
            markdown_content="متن",
            page_image_path=str(pdf_path),
            status=PageStatus.done,
        )
    )
    await session.commit()
    await session.refresh(book)
    return book


@pytest.mark.asyncio
async def test_qdrant_hits_must_match_current_approved_page_snapshot(phase2_env, tmp_path, monkeypatch):
    from app.services.retrieval_service import TextbookScope, page_embedding_text

    monkeypatch.setattr(retrieval_service, "async_session_factory", phase2_env)
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf)

    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=1)
        book_id = book.id
        grade = await session.get(Grade, book.grade_id)
        major = await session.get(Major, book.major_id) if book.major_id else None
        scope = TextbookScope(
            book_id=book.id,
            grade_number=grade.number,
            major_code=major.code if major else "general",
        )

    indexed_text = page_embedding_text("متن", [])
    point = SimpleNamespace(
        payload={
            "book_id": book_id,
            "pdf_page_index": 1,
            "full_text": indexed_text,
            "embedding_model": "test-embedding",
        },
        score=0.91,
    )
    accepted = await retrieval_service._filter_qdrant_points(
        [point], scopes=[scope], expected_embedding_model="test-embedding"
    )
    assert len(accepted) == 1
    assert accepted[0]["full_text"] == "متن"
    assert accepted[0]["printed_page_number"] == 10

    # An older vector payload must not serve content after a page edit.
    async with phase2_env() as session:
        page = await session.scalar(
            select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == 1)
        )
        page.markdown_content = "متن جدید"
        await session.commit()
    stale = await retrieval_service._filter_qdrant_points(
        [point], scopes=[scope], expected_embedding_model="test-embedding"
    )
    assert stale == []

    # Once re-indexed, the same page is usable again with current database content.
    point.payload["full_text"] = page_embedding_text("متن جدید", [])
    refreshed = await retrieval_service._filter_qdrant_points(
        [point], scopes=[scope], expected_embedding_model="test-embedding"
    )
    assert len(refreshed) == 1
    assert refreshed[0]["full_text"] == "متن جدید"

    # Vectors built by another embedding model are not compared with this query.
    wrong_model = await retrieval_service._filter_qdrant_points(
        [point], scopes=[scope], expected_embedding_model="different-model"
    )
    assert wrong_model == []

    # Approval status is checked independently from text equality.
    async with phase2_env() as session:
        page = await session.scalar(
            select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == 1)
        )
        page.status = PageStatus.needs_review
        await session.commit()
    unapproved = await retrieval_service._filter_qdrant_points(
        [point], scopes=[scope], expected_embedding_model="test-embedding"
    )
    assert unapproved == []


@pytest.mark.asyncio
async def test_kb_job_tracking_create_list_cancel(phase2_env, tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf)
    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=2)
        job = await kb_ingestion_service.create_ingestion_job(
            session, book_id=book.id, start_page=1, end_page=2
        )
        assert job.status == kb_ingestion_service.JOB_QUEUED
        assert job.total_pages == 2
        cancelled = await kb_ingestion_service.cancel_ingestion_job(session, job.id)
        assert cancelled.status == kb_ingestion_service.JOB_CANCELLED
        jobs = await kb_ingestion_service.list_jobs(session, book_id=book.id)
    assert [j.id for j in jobs] == [job.id]


@pytest.mark.asyncio
async def test_kb_admin_api_triggers_job_and_reports_progress(phase2_env, tmp_path, monkeypatch):
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf)
    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=2)
        book_id = book.id

    async def _fake_run(job_id: str):  # never call the model in tests
        async with phase2_env() as session:
            job = await session.get(KbIngestionJob, job_id)
            job.status = kb_ingestion_service.JOB_COMPLETED
            job.processed_pages = job.total_pages
            await session.commit()
        return {"ok": True}

    monkeypatch.setattr(kb_ingestion_service, "run_ingestion_job", _fake_run)
    async with _client() as client:
        anon = await client.post(f"/api/v1/admin/kb/books/{book_id}/ingest", json={})
        assert anon.status_code == 401
        resp = await client.post(
            f"/api/v1/admin/kb/books/{book_id}/ingest",
            headers=ADMIN_HEADERS,
            json={"start_page": 1, "end_page": 2},
        )
        assert resp.status_code == 202
        job_id = resp.json()["job"]["id"]
        status = await client.get(f"/api/v1/admin/kb/jobs/{job_id}", headers=ADMIN_HEADERS)
        assert status.status_code == 200
        listing = await client.get(
            f"/api/v1/admin/kb/jobs?book_id={book_id}", headers=ADMIN_HEADERS
        )
    assert listing.status_code == 200
    assert listing.json()["jobs"][0]["id"] == job_id
    assert status.json()["job"]["total_pages"] == 2


@pytest.mark.asyncio
async def test_extract_source_figures_saves_images_and_links_pages(phase2_env, tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf)
    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=2)
        result = await kb_ingestion_service.extract_source_figures(session, book_id=book.id)
        figures = await kb_ingestion_service.list_figures(session, book_id=book.id)
    assert result["figures_created"] == 1
    assert len(figures) == 1
    figure = figures[0]
    assert figure.pdf_page_index == 1
    assert figure.printed_page_number is None or figure.printed_page_number >= 0
    assert Path(figure.image_path).is_file()
    assert figure.width and figure.height


@pytest.mark.asyncio
async def test_extract_figures_replace_does_not_duplicate(phase2_env, tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf)
    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=2)
        await kb_ingestion_service.extract_source_figures(session, book_id=book.id)
        await kb_ingestion_service.extract_source_figures(session, book_id=book.id)
        figures = await kb_ingestion_service.list_figures(session, book_id=book.id)
    assert len(figures) == 1


@pytest.mark.asyncio
async def test_figures_endpoint_and_image_download(phase2_env, tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf)
    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=2)
        book_id = book.id
        await kb_ingestion_service.extract_source_figures(session, book_id=book_id)
        figure_id = (await kb_ingestion_service.list_figures(session, book_id=book_id))[0].id
    async with _client() as client:
        listing = await client.get(
            f"/api/v1/admin/kb/books/{book_id}/figures", headers=ADMIN_HEADERS
        )
        image = await client.get(
            f"/api/v1/admin/kb/figures/{figure_id}/image", headers=ADMIN_HEADERS
        )
        anon = await client.get(f"/api/v1/admin/kb/figures/{figure_id}/image")
    assert listing.status_code == 200 and len(listing.json()["figures"]) == 1
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert anon.status_code == 401


@pytest.mark.asyncio
async def test_reindex_chapter_rejects_unknown_chapter(phase2_env, tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf)
    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=2)
        with pytest.raises(ValueError):
            await kb_ingestion_service.reindex_chapter(session, book_id=book.id, chapter_number=99)


@pytest.mark.asyncio
async def test_benchmark_requires_models_and_pages(phase2_env, tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf)
    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=2)
        with pytest.raises(ValueError):
            await kb_ingestion_service.benchmark_models(
                session, book_id=book.id, models=[], pages=[1]
            )
        with pytest.raises(ValueError):
            await kb_ingestion_service.benchmark_models(
                session, book_id=book.id, models=["m"], pages=[]
            )


@pytest.mark.asyncio
async def test_kb_endpoints_reject_non_admin(phase2_env):
    async with _client() as client:
        assert (await client.get("/api/v1/admin/kb/jobs")).status_code == 401
        for url in (
            "/api/v1/admin/kb/books/1/reindex-page",
            "/api/v1/admin/kb/books/1/benchmark",
            "/api/v1/admin/kb/books/1/figures/extract",
        ):
            resp = await client.post(url, json={})
            assert resp.status_code == 401, url


# ---------------------------------------------------------------------------
# 5. Migration & gateway isolation
# ---------------------------------------------------------------------------


def test_phase2_migration_creates_expected_tables():
    import importlib.util

    path = BACKEND_ROOT / "alembic" / "versions" / "d8e9f0a1b2c3_phase2_capabilities_skills_kb.py"
    spec = importlib.util.spec_from_file_location("phase2_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "d8e9f0a1b2c3"
    assert module.down_revision == "c7d8e9f0a1b2"
    source = path.read_text(encoding="utf-8")
    for table in ("capabilities", "skills", "skill_versions", "kb_ingestion_jobs", "source_figures"):
        assert f'"{table}"' in source
    for table in ("capabilities", "skills", "skill_versions", "kb_ingestion_jobs", "source_figures"):
        assert table in Base.metadata.tables


def test_phase2_modules_do_not_call_providers_directly():
    forbidden = {"openai", "httpx", "anthropic", "requests"}
    files = [
        BACKEND_ROOT / "app" / "services" / "capability_runtime.py",
        BACKEND_ROOT / "app" / "services" / "kb_ingestion_service.py",
        BACKEND_ROOT / "app" / "api" / "kb.py",
        BACKEND_ROOT / "app" / "api" / "skills.py",
        BACKEND_ROOT / "app" / "api" / "capabilities.py",
    ]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            assert not (set(names) & forbidden), f"{path.name} imports a provider SDK directly"


def test_runtime_routes_model_calls_through_gateway():
    source = (BACKEND_ROOT / "app" / "services" / "capability_runtime.py").read_text(encoding="utf-8")
    assert "_via_gateway" in source
    assert "ai_gateway" in source or "_via_gateway" in source


@pytest.mark.asyncio
async def test_run_ingestion_job_tracks_progress_and_syncs_book_status(phase2_env, tmp_path, monkeypatch):
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf, pages=3)

    async def _fake_ingest(**kwargs):
        progress = kwargs.get("progress_callback")
        for _ in range(kwargs["end_page"] - kwargs["start_page"] + 1):
            progress({"status": "done", "tokens": 0})
        return {"failed_pages": [], "totals": {}}

    monkeypatch.setattr(kb_ingestion_service, "ingest_book_pages", _fake_ingest)
    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=3)
        job = await kb_ingestion_service.create_ingestion_job(
            session, book_id=book.id, start_page=1, end_page=3
        )
        job_id = job.id
    result = await kb_ingestion_service.run_ingestion_job(job_id)
    assert result["ok"] is True
    async with phase2_env() as session:
        job = await session.get(KbIngestionJob, job_id)
        book = await session.get(Book, job.book_id)
    assert job.status == kb_ingestion_service.JOB_COMPLETED
    assert job.processed_pages == 3
    assert job.finished_at is not None
    assert book.status == BookStatus.ready


@pytest.mark.asyncio
async def test_run_ingestion_job_marks_failure_and_book_failed(phase2_env, tmp_path, monkeypatch):
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf)

    async def _boom(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(kb_ingestion_service, "ingest_book_pages", _boom)
    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=2)
        job = await kb_ingestion_service.create_ingestion_job(
            session, book_id=book.id, start_page=1, end_page=2
        )
        job_id, book_id = job.id, book.id
    result = await kb_ingestion_service.run_ingestion_job(job_id)
    assert result["ok"] is False
    async with phase2_env() as session:
        job = await session.get(KbIngestionJob, job_id)
        book = await session.get(Book, book_id)
    assert job.status == kb_ingestion_service.JOB_FAILED
    assert "provider down" in (job.error_log or "")
    assert book.status == BookStatus.failed


@pytest.mark.asyncio
async def test_trigger_defaults_end_page_from_pdf_file(phase2_env, tmp_path, monkeypatch):
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_image(pdf, pages=3)
    async with phase2_env() as session:
        book = await _seed_book(session, pdf, pages=1)  # range-length value, not file pages
        book_id = book.id

    async def _noop(job_id: str):
        return {"ok": True}

    monkeypatch.setattr(kb_ingestion_service, "run_ingestion_job", _noop)
    async with _client() as client:
        resp = await client.post(
            f"/api/v1/admin/kb/books/{book_id}/ingest",
            headers=ADMIN_HEADERS,
            json={"start_page": 1},
        )
    assert resp.status_code == 202
    assert resp.json()["job"]["end_page"] == 3
    assert resp.json()["job"]["total_pages"] == 3


# ---------------------------------------------------------------------------
# Phase 2 review: runtime enforcement, web upload end-to-end, figure extraction
# ---------------------------------------------------------------------------


def _fake_gateway_result():
    from app.services.ai_gateway import GatewayResult

    return GatewayResult(
        content="پاسخ آزمایشی",
        model_name="fake-model",
        latency_ms=1,
        tokens_in=1,
        tokens_out=1,
        audit_id="audit-1",
        status="ok",
    )


@pytest.mark.asyncio
async def test_runtime_blocks_disabled_capability_before_gateway(phase2_env, monkeypatch):
    from fastapi import HTTPException

    from app.services import capability_runtime

    calls = []

    async def _gateway(**kwargs):
        calls.append(kwargs)
        return _fake_gateway_result()

    monkeypatch.setattr(capability_runtime, "complete_text_via_gateway", _gateway)
    async with phase2_env() as session:
        cap = await session.get(Capability, "chat")
        cap.is_enabled = False
        await session.commit()
        with pytest.raises(HTTPException) as info:
            await capability_runtime.run_capability_text(
                session=session, capability_key="chat", user_text="سلام"
            )
    assert info.value.status_code == 403
    assert calls == []  # the gateway was never reached


@pytest.mark.asyncio
async def test_runtime_enforces_quota_before_gateway(phase2_env, monkeypatch):
    from fastapi import HTTPException

    from app.models.auth import User
    from app.services import capability_runtime

    calls = []

    async def _gateway(**kwargs):
        calls.append(kwargs)
        return _fake_gateway_result()

    async def _quota_exceeded(session, *, user, feature_key, now=None):
        raise HTTPException(status_code=429, detail="quota")

    monkeypatch.setattr(capability_runtime, "complete_text_via_gateway", _gateway)
    monkeypatch.setattr(capability_runtime, "enforce_ai_quota", _quota_exceeded)
    async with phase2_env() as session:
        user = User(phone_number="09120000001", role="student", plan_code="trial")
        session.add(user)
        await session.commit()
        with pytest.raises(HTTPException) as info:
            await capability_runtime.run_capability_text(
                session=session, capability_key="chat", user_text="سلام", user=user
            )
    assert info.value.status_code == 429
    assert calls == []


@pytest.mark.asyncio
async def test_runtime_enabled_call_goes_through_gateway_with_skill(phase2_env, monkeypatch):
    from app.services import capability_runtime

    calls = []

    async def _gateway(**kwargs):
        calls.append(kwargs)
        return _fake_gateway_result()

    monkeypatch.setattr(capability_runtime, "complete_text_via_gateway", _gateway)
    async with phase2_env() as session:
        result, blocks, skill = await capability_runtime.run_capability_text(
            session=session, capability_key="chat", user_text="سلام"
        )
    assert len(calls) == 1
    assert calls[0]["ctx"].skill_id == "tutor_core"
    assert skill is not None and skill.slug == "tutor_core"
    assert result.content == "پاسخ آزمایشی"
    assert [b.type for b in blocks][0] == "text_markdown"


@pytest.mark.asyncio
async def test_admin_skill_test_may_run_disabled_capability(phase2_env, monkeypatch):
    from app.services import capability_runtime

    calls = []

    async def _gateway(**kwargs):
        calls.append(kwargs)
        return _fake_gateway_result()

    monkeypatch.setattr(capability_runtime, "complete_text_via_gateway", _gateway)
    async with phase2_env() as session:
        cap = await session.get(Capability, "chat")
        cap.is_enabled = False
        await session.commit()
        out = await capability_runtime.test_skill(
            session=session, slug="tutor_core", sample_input="آزمایش"
        )
    assert len(calls) == 1  # admin test still goes through the gateway
    assert out["answer"] == "پاسخ آزمایشی"


@pytest.mark.asyncio
async def test_web_upload_from_admin_ingests_and_extracts_figures_without_cli(
    phase2_env, tmp_path, monkeypatch
):
    """Upload a PDF via /api/v1/admin/books/upload-and-ingest (no CLI involved).

    The vision model is replaced by a stub so no network call happens; everything
    else (job tracking, book status, figure extraction and storage) is real.
    """
    from app.api import admin as admin_api

    monkeypatch.setattr(admin_api, "UPLOAD_DIR", tmp_path / "uploads")
    pdf_bytes_path = tmp_path / "upload.pdf"
    _make_pdf_with_image(pdf_bytes_path, pages=2)

    async def _stub_ingest(**kwargs):
        return {"failed_pages": [], "totals": {}}

    monkeypatch.setattr(kb_ingestion_service, "ingest_book_pages", _stub_ingest)
    async with _client() as client:
        with open(pdf_bytes_path, "rb") as handle:
            resp = await client.post(
                "/api/v1/admin/books/upload-and-ingest",
                headers=ADMIN_HEADERS,
                files={"file": ("book.pdf", handle, "application/pdf")},
                data={
                    "grade_number": "12",
                    "major_code": "math_physics",
                    "book_title": "کتاب وب",
                    "start_page": "1",
                    "end_page": "2",
                },
            )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        job_id, book_id = payload["job_id"], payload["book_id"]
        job_resp = await client.get(f"/api/v1/admin/kb/jobs/{job_id}", headers=ADMIN_HEADERS)
        figs = await client.get(f"/api/v1/admin/kb/books/{book_id}/figures", headers=ADMIN_HEADERS)
    job = job_resp.json()["job"]
    assert job["status"] == kb_ingestion_service.JOB_COMPLETED
    assert job["total_pages"] == 2
    figures = figs.json()["figures"]
    assert len(figures) >= 1
    assert Path(figures[0]["image_path"]).is_file()
    assert figures[0]["pdf_page_index"] == 1
    async with phase2_env() as session:
        book = await session.get(Book, book_id)
    assert book.status == BookStatus.ready
