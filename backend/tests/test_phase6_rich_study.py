"""Phase 6 tests: sanitizer, Mermaid guard, notebook Inline AI diff + audit, capability lock,
TTS cache, Living Book grounding and cache, visualize rejection paths.

Real pipeline is used (capability_runtime -> ai_gateway -> ai_audit_logs) with only the
external model calls faked. Runs on SQLite like the Phase 5 suite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import require_student
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.auth import User
from app.models.capabilities import Capability
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.models.governance import AiAuditLog
from app.models.phase6 import LivingBookCache, Notebook, NotebookBlock
from app.services import (
    ai_gateway,
    capability_runtime,
    capability_service,
    chat_stream,
    learner_memory_service as lms,
    living_book_service as lbs,
    notebook_service as nb,
    retrieval_service,
    skill_seed,
    tts_service,
    visualize_service,
)
from app.services.ai_gateway import GatewayResult
from app.services.visual_safety import UnsafeVisualError, sanitize_svg, validate_mermaid

NOW = datetime.now(timezone.utc)
HIT = {
    "book_id": 1,
    "chapter_number": 2,
    "chapter_title": "فصل ۲",
    "printed_page_number": 14,
    "full_text": "نیرو کمیت برداری است و با کشش یا هل دادن ایجاد می‌شود",
}


# ---------------------------------------------------------------------------
# Pure: sanitizer and Mermaid guard
# ---------------------------------------------------------------------------
SVG_NS = 'xmlns="http://www.w3.org/2000/svg"'
HOSTILE_SVGS = [
    f"<svg {SVG_NS}><script>alert(1)</script></svg>",
    f'<svg {SVG_NS}><circle r="5" onload="alert(1)"/></svg>',
    f'<svg {SVG_NS}><a href="javascript:alert(1)"><text>x</text></a></svg>',
    f"<svg {SVG_NS}><foreignObject><div>hi</div></foreignObject></svg>",
    f'<svg {SVG_NS}><image href="data:image/svg+xml;base64,AAA"/></svg>',
    f'<svg {SVG_NS}><rect style="fill:url(http://evil/x)"/></svg>',
    f'<svg {SVG_NS}><use href="http://evil/x.svg#a"/></svg>',
    f'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg {SVG_NS}>&x;</svg>',
    f'<svg {SVG_NS}><animate attributeName="href" values="javascript:alert(1)"/></svg>',
    f'<svg {SVG_NS}><set attributeName="onmouseover" to="alert(1)"/></svg>',
    f"<svg {SVG_NS}><style>@import \"http://evil/x.css\";</style></svg>",
    "<html><svg></svg></html>",
]


@pytest.mark.parametrize("payload", HOSTILE_SVGS)
def test_hostile_svg_is_rejected_or_stripped_of_active_content(payload):
    try:
        out = sanitize_svg(payload)
    except UnsafeVisualError:
        return
    lowered = out.lower().replace('xmlns="http://www.w3.org/2000/svg"', "")
    for token in ("<script", "onload", "onmouseover", "javascript:", "foreignobject", "data:", "http://", "<!doctype", "<!entity", "<style", "<image", "<use", "<animate", "<set", "style="):
        assert token not in lowered, token


def test_svg_allowlist_keeps_drawing_and_local_marker_refs():
    good = f'<svg {SVG_NS} viewBox="0 0 100 100"><defs><marker id="m"/></defs><g fill="#333"><circle cx="50" cy="50" r="20"/><text x="10" y="90">نیرو</text><path d="M0 0 L10 10" marker-end="url(#m)"/></g></svg>'
    out = sanitize_svg(good)
    assert "<circle" in out and "نیرو" in out and 'url(#m)' in out


@pytest.mark.parametrize(
    "source",
    [
        'graph TD\nA-->B\nclick A "javascript:alert(1)"',
        'flowchart LR\nA["<img src=x onerror=alert(1)>"]',
        '%%{init: {"securityLevel":"loose"}}%%\ngraph TD\nA-->B',
        "graph TD\nA-->B\ncall foo()",
        'graph TD\nA-->B\nhref A "http://x"',
        "graph TD\nA-->B\n<script>x</script>",
        "sequenceDiagram\nA->>B: hi",
    ],
)
def test_mermaid_guard_rejects_active_or_unsupported_sources(source):
    with pytest.raises(UnsafeVisualError):
        validate_mermaid(source)


def test_mermaid_guard_accepts_plain_persian_flowchart():
    assert validate_mermaid("graph TD\nA[نیرو] --> B[شتاب]").startswith("graph TD")


def test_seeded_phase6_capabilities_have_unique_sort_and_skill_mapping():
    keys = ["learning_notebook", "web_visualize", "living_book", "audio_tts"]
    caps = {c["key"]: c for c in capability_service.SEED_CAPABILITIES}
    sorts = [c.get("sort_order", c.get("sort")) for c in capability_service.SEED_CAPABILITIES]
    assert len(set(sorts)) == len(sorts)
    for key in keys:
        assert key in caps
    skill_caps = {s["capability_key"] for s in skill_seed.SEED_SKILLS}
    assert set(keys) <= skill_caps


# ---------------------------------------------------------------------------
# Fixture: real DB, seeded registry, one ready book with chapter 2 pages
# ---------------------------------------------------------------------------
@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase6.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    ids: dict[str, object] = {}

    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await seed_plans(session)
        await seed_billing_settings(session)
        await capability_service.seed_capabilities(session)
        await skill_seed.seed_skills(session)
        major = await session.scalar(select(Major).where(Major.code == "math_physics"))
        grade = await session.scalar(select(Grade).where(Grade.number == 10))
        book = Book(title="فیزیک دهم", grade_id=grade.id, major_id=major.id, pdf_file_path="/tmp/none.pdf",
                    total_pdf_pages=5, status=BookStatus.ready, catalog_status="approved")
        session.add(book)
        await session.flush()
        for index, chapter, printed, text in (
            (1, 1, 10, "حرکت بر خط راست و سرعت متوسط"),
            (2, 2, 14, "نیرو کمیت برداری است و با کشش یا هل دادن ایجاد می‌شود"),
            (3, 2, 15, "قانون دوم نیوتون: نیروی خالص برابر جرم ضربدر شتاب است"),
        ):
            session.add(BookPage(book_id=book.id, pdf_page_index=index, printed_page_number=printed,
                                 chapter_number=chapter, chapter_title=f"فصل {chapter}",
                                 markdown_content=text, page_image_path="/tmp/none.png", status=PageStatus.done))
        owner = User(phone_number="09121000001", full_name="دانش‌آموز", role="student",
                     tokens_remaining=1_000_000, plan_expires_at=NOW + timedelta(days=30), is_active=True)
        other = User(phone_number="09121000002", full_name="دیگری", role="student",
                     tokens_remaining=1_000_000, plan_expires_at=NOW + timedelta(days=30), is_active=True)
        session.add_all([owner, other])
        await session.flush()
        ids.update(student_id=owner.id, other_id=other.id, book_id=book.id)
        await session.commit()

    async def override_get_session():
        async with factory() as session:
            yield session

    current = {"id": ids["student_id"]}

    async def override_student():
        async with factory() as session:
            return await session.get(User, current["id"])

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_student] = override_student
    from app.db import session as db_session_mod

    monkeypatch.setattr(db_session_mod, "async_session_factory", factory)
    monkeypatch.setattr(ai_gateway, "async_session_factory", factory)
    monkeypatch.setattr(chat_stream, "async_session_factory", factory)
    monkeypatch.setattr(lms, "async_session_factory", factory)
    monkeypatch.setattr(retrieval_service, "async_session_factory", factory)
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: SimpleNamespace(tutor_model="test-model", llm_timeout=5))

    fake = SimpleNamespace(json_calls=[], text_calls=[], json_reply=None, text_reply="پاسخ نمونه")

    async def fake_complete_json(model, messages):
        fake.json_calls.append(messages)
        return fake.json_reply(messages) if callable(fake.json_reply) else (fake.json_reply or {})

    async def fake_complete_text(model, messages):
        fake.text_calls.append(messages)
        return fake.text_reply(messages) if callable(fake.text_reply) else fake.text_reply

    monkeypatch.setattr(ai_gateway, "complete_json", fake_complete_json)
    monkeypatch.setattr(ai_gateway, "complete_text", fake_complete_text)

    async def fake_search(query, **kwargs):
        return [dict(HIT)] if fake.hits else []

    fake.hits = True
    monkeypatch.setattr(nb, "search_textbook", fake_search)
    monkeypatch.setattr(visualize_service, "search_textbook", fake_search)
    monkeypatch.setattr(lbs, "capability_runtime", capability_runtime)

    yield SimpleNamespace(factory=factory, ids=ids, fake=fake, current=current)

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_student, None)
    await engine.dispose()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _count(factory, model, *where) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


async def _new_notebook(client, book_id: int, title="دفترچه") -> int:
    res = await client.post("/api/v1/notebooks", json={"title": title, "book_id": book_id})
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _add_text_block(client, nb_id: int, content: str) -> int:
    res = await client.post(f"/api/v1/notebooks/{nb_id}/blocks", json={"block_type": "text_markdown", "content": content})
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ---------------------------------------------------------------------------
# Notebook: CRUD, block validation, Inline AI diff with audit
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_notebook_blocks_reject_unsafe_svg_and_mermaid(env):
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        svg = await client.post(f"/api/v1/notebooks/{nb_id}/blocks", json={
            "block_type": "diagram_svg", "content": f"<svg {SVG_NS}><script>alert(1)</script></svg>"})
        mermaid = await client.post(f"/api/v1/notebooks/{nb_id}/blocks", json={
            "block_type": "diagram_mermaid", "content": 'graph TD\nA-->B\nclick A "javascript:alert(1)"'})
        ok = await client.post(f"/api/v1/notebooks/{nb_id}/blocks", json={
            "block_type": "diagram_svg", "content": f'<svg {SVG_NS}><circle r="4"/></svg>'})
    assert svg.status_code == 422 and mermaid.status_code == 422
    assert ok.status_code == 201 and "<circle" in ok.json()["content"]
    assert await _count(env.factory, NotebookBlock, NotebookBlock.notebook_id == nb_id) == 1


@pytest.mark.asyncio
async def test_inline_propose_accept_writes_audit_and_applies_only_selected_text(env):
    env.fake.text_reply = "نیرو یعنی کشش یا هل‌دادن که جسم را حرکت می‌دهد."
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        block_id = await _add_text_block(client, nb_id, "مقدمه. نیرو کمیت برداری است. پایان.")
        prop = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/propose",
            json={"action": "simplify", "selection": "نیرو کمیت برداری است."},
        )
        assert prop.status_code == 200, prop.text
        payload = prop.json()
        assert payload["proposed"] == env.fake.text_reply
        assert payload["citations"] and "صفحه چاپی 14" in payload["citations"][0]
        acc = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/accept",
            json={"audit_id": payload["audit_id"], "action": "simplify",
                  "selection": "نیرو کمیت برداری است.", "proposed": "<script>evil</script>"},
        )
        assert acc.status_code == 200, acc.text
        assert acc.json()["block"]["content"] == f"مقدمه. {env.fake.text_reply} پایان."
        again = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/accept",
            json={"audit_id": payload["audit_id"], "action": "simplify", "selection": "x"},
        )
    assert again.status_code == 409
    assert await _count(env.factory, AiAuditLog, AiAuditLog.flag_reason == "notebook_inline_accept",
                        AiAuditLog.response_text.like(f'%"audit_id": "{payload["audit_id"]}"%')) == 1
    assert await _count(env.factory, AiAuditLog, AiAuditLog.feature_key == "learning_notebook") >= 2


@pytest.mark.asyncio
async def test_inline_accept_rejects_tampered_selection_and_foreign_audit(env):
    env.fake.text_reply = "پیشنهاد"
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        block_id = await _add_text_block(client, nb_id, "نیرو کمیت برداری است.")
        prop = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/propose",
            json={"action": "summarize", "selection": "نیرو کمیت برداری است."},
        )
        audit_id = prop.json()["audit_id"]
        tampered = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/accept",
            json={"audit_id": audit_id, "action": "summarize", "selection": "متنی که وجود ندارد"},
        )
        env.current["id"] = env.ids["other_id"]
        foreign = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/accept",
            json={"audit_id": audit_id, "action": "summarize", "selection": "نیرو کمیت برداری است."},
        )
    assert tampered.status_code == 422
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_inline_rag_miss_creates_no_proposal_and_is_audited(env):
    env.fake.hits = False
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        block_id = await _add_text_block(client, nb_id, "نیرو کمیت برداری است.")
        res = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/propose",
            json={"action": "example", "selection": "نیرو کمیت برداری است."},
        )
    assert res.status_code == 422
    assert await _count(env.factory, AiAuditLog, AiAuditLog.flag_reason == "rag_miss") >= 1
    assert env.fake.text_calls == []


@pytest.mark.asyncio
async def test_notebook_export_markdown_and_ownership(env):
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"], title="جزوه")
        await _add_text_block(client, nb_id, "متن نمونه")
        export = await client.get(f"/api/v1/notebooks/{nb_id}/export.md")
        env.current["id"] = env.ids["other_id"]
        foreign = await client.get(f"/api/v1/notebooks/{nb_id}")
    assert export.status_code == 200 and export.text.startswith("# جزوه") and "متن نمونه" in export.text
    assert foreign.status_code == 404


# ---------------------------------------------------------------------------
# Capability lock: disabled capabilities block students fail-closed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["learning_notebook", "web_visualize", "living_book", "audio_tts"])
async def test_disabled_phase6_capability_blocks_student(env, key):
    async with env.factory() as session:
        cap = await session.scalar(select(Capability).where(Capability.key == key))
        cap.is_enabled = False
        await session.commit()
    async with _client() as client:
        if key == "learning_notebook":
            res = await client.get("/api/v1/notebooks")
        elif key == "web_visualize":
            res = await client.post("/api/v1/visualize", json={"kind": "table", "prompt": "مقایسه", "book_id": env.ids["book_id"]})
        elif key == "living_book":
            res = await client.get(f"/api/v1/living-book/{env.ids['book_id']}/chapters/2")
        else:
            res = await client.post("/api/v1/tts", json={"text": "سلام دوست"})
    assert res.status_code == 403, res.text
    assert env.fake.json_calls == [] and env.fake.text_calls == []


# ---------------------------------------------------------------------------
# TTS: cache miss then hit, no provider call on hit
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tts_cache_miss_then_hit_skips_provider(env, monkeypatch, tmp_path):
    calls: list[str] = []

    async def fake_speech(**kwargs):
        calls.append(kwargs["text"])
        return b"RIFF\x00\x00\x00\x00WAVEfmt demo", GatewayResult(content="", model_name="tts-test")

    monkeypatch.setattr(capability_runtime, "run_capability_speech", fake_speech)
    monkeypatch.setattr(tts_service, "TTS_ROOT", tmp_path / "tts_cache")
    async with env.factory() as session:
        cap = await session.scalar(select(Capability).where(Capability.key == "audio_tts"))
        cap.config_json = {"voice": "test-voice"}
        await session.commit()
    async with _client() as client:
        first = await client.post("/api/v1/tts", json={"text": "نیرو کمیت برداری است"})
        second = await client.post("/api/v1/tts", json={"text": "نیرو   کمیت برداری است"})
    assert first.status_code == 200 and first.headers["x-tts-cache"] == "miss"
    assert second.status_code == 200 and second.headers["x-tts-cache"] == "hit"
    assert len(calls) == 1
    assert first.headers["content-type"].startswith("audio/")
    assert await _count(env.factory, AiAuditLog, AiAuditLog.flag_reason == "tts_cache_hit") == 1


def test_tts_cache_key_depends_on_model_voice_and_text():
    base = tts_service.cache_key("m", "v", "متن")
    assert base == tts_service.cache_key("m", "v", "متن")
    assert base != tts_service.cache_key("m2", "v", "متن")
    assert base != tts_service.cache_key("m", "v2", "متن")
    assert base != tts_service.cache_key("m", "v", "متن دیگر")


@pytest.mark.asyncio
async def test_tts_rejects_empty_and_oversize_text(env):
    async with _client() as client:
        empty = await client.post("/api/v1/tts", json={"text": "  "})
        huge = await client.post("/api/v1/tts", json={"text": "الف " * 3000})
    assert empty.status_code == 422 and huge.status_code == 422


# ---------------------------------------------------------------------------
# Visualize: table shape, RAG miss, unsafe output rejected and audited
# ---------------------------------------------------------------------------
def test_table_validation_enforces_shape():
    good = visualize_service.validate_table({"headers": ["الف", "ب"], "rows": [["1", "2"]]})
    assert good["rows"] == [["1", "2"]]
    with pytest.raises(UnsafeVisualError):
        visualize_service.validate_table({"headers": ["الف"], "rows": [["1", "2"]]})


@pytest.mark.asyncio
async def test_visualize_rejects_unsafe_model_svg_and_audits(env):
    env.fake.json_reply = lambda messages: {
        "kind": "svg", "title": "t", "source": f"<svg {SVG_NS}><script>alert(1)</script></svg>"}
    async with _client() as client:
        res = await client.post("/api/v1/visualize", json={"kind": "svg", "prompt": "نیرو", "book_id": env.ids["book_id"]})
    assert res.status_code == 422
    assert await _count(env.factory, AiAuditLog, AiAuditLog.flag_reason == "visual_rejected") == 1


@pytest.mark.asyncio
async def test_visualize_accepts_safe_mermaid_with_citation(env):
    env.fake.json_reply = lambda messages: {
        "kind": "mermaid", "title": "مفهوم نیرو", "source": "graph TD\nA[نیرو] --> B[شتاب]"}
    async with _client() as client:
        res = await client.post("/api/v1/visualize", json={"kind": "mermaid", "prompt": "نیرو و شتاب", "book_id": env.ids["book_id"]})
    assert res.status_code == 200, res.text
    block = res.json()["block"]
    assert block["type"] == "diagram_mermaid" and "نیرو" in block["content"]
    assert "صفحه چاپی 14" in block["metadata"]["citation"]


# ---------------------------------------------------------------------------
# Living Book: grounding, validator, shared cache keyed by content hash
# ---------------------------------------------------------------------------
GOOD_LIVING = {
    "concepts": [{"title": "نیرو", "text": "نیرو کمیت برداری است.", "page": 14}],
    "callouts": [{"tone": "warning", "text": "نیرو را با جرم اشتباه نگیرید.", "page": 15}],
    "flashcards": [{"front": "نیرو چیست؟", "back": "کمیت برداری", "page": 14}],
    "diagrams": [{"title": "مفهوم", "kind": "mermaid", "source": "graph TD\nA[نیرو] --> B[شتاب]", "page": 15}],
    "quiz": [],
}


def test_assemble_drops_items_outside_chapter_and_unsafe_diagrams(env=None):
    from app.models.curriculum import Book as B

    book = B(id=1, title="فیزیک دهم", grade_id=1, major_id=1, pdf_file_path="x", total_pdf_pages=1, status=BookStatus.ready)
    pages = [BookPage(book_id=1, pdf_page_index=2, printed_page_number=14, chapter_number=2, chapter_title="فصل ۲",
                      markdown_content="x", page_image_path="x", status=PageStatus.done)]
    raw = {
        "concepts": [{"title": "الف", "text": "ب", "page": 99}, {"title": "نیرو", "text": "کمیت", "page": 14}],
        "callouts": [],
        "flashcards": [],
        "diagrams": [{"source": 'graph TD\nA-->B\nclick A "javascript:alert(1)"', "page": 14}],
    }
    accepted, rejected = lbs.assemble_living_book(raw, pages=pages, book=book)
    kinds = [b["type"] for b in accepted]
    assert kinds == ["text_markdown"]
    assert "صفحه چاپی 14" in accepted[0]["metadata"]["citation"]
    reasons = {r["reason"] for r in rejected}
    assert "page_not_in_chapter" in reasons


@pytest.mark.asyncio
async def test_living_book_generates_once_then_serves_shared_cache(env, monkeypatch):
    seen: list[str] = []
    real = capability_runtime.run_capability_json

    async def spy(**kwargs):
        seen.append(kwargs["capability_key"])
        return await real(**kwargs)

    monkeypatch.setattr(lbs.capability_runtime, "run_capability_json", spy)
    env.fake.json_reply = lambda messages: GOOD_LIVING
    async with _client() as client:
        first = await client.get(f"/api/v1/living-book/{env.ids['book_id']}/chapters/2")
        env.current["id"] = env.ids["other_id"]
        second = await client.get(f"/api/v1/living-book/{env.ids['book_id']}/chapters/2")
    assert first.status_code == 200, first.text
    body1, body2 = first.json(), second.json()
    assert body1["cache_hit"] is False and body2["cache_hit"] is True
    assert body1["content_hash"] == body2["content_hash"]
    assert seen == ["living_book"]
    types = {b["type"] for b in body1["blocks"]}
    assert {"text_markdown", "callout_tip", "flashcard_item", "diagram_mermaid"} <= types
    assert len(env.fake.json_calls) == 1
    assert await _count(env.factory, LivingBookCache, LivingBookCache.book_id == env.ids["book_id"]) == 1


@pytest.mark.asyncio
async def test_living_book_regenerates_when_chapter_content_changes(env):
    env.fake.json_reply = lambda messages: GOOD_LIVING
    async with _client() as client:
        first = await client.get(f"/api/v1/living-book/{env.ids['book_id']}/chapters/2")
        async with env.factory() as session:
            page = await session.scalar(select(BookPage).where(BookPage.pdf_page_index == 2))
            page.markdown_content = "نیرو کمیت برداری است و تغییر یافته است"
            await session.commit()
        second = await client.get(f"/api/v1/living-book/{env.ids['book_id']}/chapters/2")
    assert first.json()["content_hash"] != second.json()["content_hash"]
    assert second.json()["cache_hit"] is False
    assert await _count(env.factory, LivingBookCache) == 2


@pytest.mark.asyncio
async def test_living_book_unknown_chapter_is_404(env):
    async with _client() as client:
        res = await client.get(f"/api/v1/living-book/{env.ids['book_id']}/chapters/7")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_admin_views_expose_phase6_caches_and_rejections(env):
    from app.api.admin import require_admin  # noqa: F401  (route dependency)

    env.fake.json_reply = lambda messages: {**GOOD_LIVING, "concepts": GOOD_LIVING["concepts"] + [
        {"title": "ساختگی", "text": "x", "page": 999}]}
    async with _client() as client:
        await client.get(f"/api/v1/living-book/{env.ids['book_id']}/chapters/2")
        res = await client.get("/api/v1/admin/phase6/living-book",
                               headers={"X-Admin-Username": "admin", "X-Admin-Password": "123"})
        anon = await client.get("/api/v1/admin/phase6/living-book")
    assert anon.status_code in (401, 403)
    assert res.status_code == 200
    items = res.json()["items"]
    assert items and any(r["reason"] == "page_not_in_chapter" for r in items[0]["rejected"])


@pytest.mark.asyncio
async def test_inline_flashcard_accept_creates_card_and_reject_is_idempotent(env):
    from app.models.flashcards import Flashcard

    env.fake.text_reply = '{"front": "نیرو چیست؟", "back": "کمیت برداری"}'
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        block_id = await _add_text_block(client, nb_id, "نیرو کمیت برداری است.")
        prop = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/propose",
            json={"action": "to_flashcard", "selection": "نیرو کمیت برداری است."},
        )
        assert prop.status_code == 200, prop.text
        audit_id = prop.json()["audit_id"]
        acc = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/accept",
            json={"audit_id": audit_id, "action": "to_flashcard", "selection": "نیرو کمیت برداری است."},
        )
        assert acc.status_code == 200, acc.text
        assert acc.json()["applied"] == "flashcard"
        rej1 = await client.post(f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/reject",
                                 json={"audit_id": audit_id})
        rej2 = await client.post(f"/api/v1/notebooks/{nb_id}/blocks/{block_id}/inline/reject",
                                 json={"audit_id": audit_id})
    assert rej1.status_code == 204 and rej2.status_code == 204
    assert await _count(env.factory, Flashcard, Flashcard.front_md == "نیرو چیست؟") == 1
    assert await _count(env.factory, AiAuditLog, AiAuditLog.flag_reason == "notebook_inline_reject") == 1


# ---------------------------------------------------------------------------
# Phase 02-B: notebook handoff idempotency (stable conversation/message identity)
# ---------------------------------------------------------------------------
HANDOFF_META = {
    "title": "فیزیک دهم",
    "citation": "فیزیک دهم — فصل ۲ — صفحهٔ ۱۴",
    "conversation_id": "conv-1",
    "message_id": "msg-1",
}


@pytest.mark.asyncio
async def test_handoff_same_message_twice_replays_existing_block(env):
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        first = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks",
            json={"block_type": "text_markdown", "content": "پاسخ معلم", "metadata": HANDOFF_META},
        )
        second = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks",
            json={"block_type": "text_markdown", "content": "پاسخ معلم", "metadata": HANDOFF_META},
        )
    assert first.status_code == 201
    assert second.status_code == 201 and second.json().get("idempotent_replay") is True
    assert second.json()["id"] == first.json()["id"]
    assert await _count(env.factory, NotebookBlock, NotebookBlock.notebook_id == nb_id) == 1


@pytest.mark.asyncio
async def test_handoff_parallel_posts_create_single_block(env):
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        body = {"block_type": "text_markdown", "content": "پاسخ هم‌زمان", "metadata": HANDOFF_META}
        first, second = await asyncio.gather(
            client.post(f"/api/v1/notebooks/{nb_id}/blocks", json=body),
            client.post(f"/api/v1/notebooks/{nb_id}/blocks", json=body),
        )
    assert first.status_code == 201 and second.status_code == 201
    assert await _count(env.factory, NotebookBlock, NotebookBlock.notebook_id == nb_id) == 1


@pytest.mark.asyncio
async def test_handoff_retry_after_timeout_does_not_duplicate(env):
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        payload = {"block_type": "text_markdown", "content": "پاسخ پس از timeout", "metadata": HANDOFF_META}
        await client.post(f"/api/v1/notebooks/{nb_id}/blocks", json=payload)
        # client never saw the response (timeout) -> retries with the same identity
        retry = await client.post(f"/api/v1/notebooks/{nb_id}/blocks", json=payload)
    assert retry.status_code == 201 and retry.json().get("idempotent_replay") is True
    assert await _count(env.factory, NotebookBlock, NotebookBlock.notebook_id == nb_id) == 1


@pytest.mark.asyncio
async def test_handoff_two_messages_same_conversation_create_two_blocks(env):
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        one = await client.post(f"/api/v1/notebooks/{nb_id}/blocks", json={
            "block_type": "text_markdown", "content": "پاسخ اول",
            "metadata": {**HANDOFF_META, "message_id": "msg-1"}})
        two = await client.post(f"/api/v1/notebooks/{nb_id}/blocks", json={
            "block_type": "text_markdown", "content": "پاسخ دوم",
            "metadata": {**HANDOFF_META, "message_id": "msg-2"}})
    assert one.status_code == 201 and two.status_code == 201
    assert one.json()["id"] != two.json()["id"]
    assert await _count(env.factory, NotebookBlock, NotebookBlock.notebook_id == nb_id) == 2


@pytest.mark.asyncio
async def test_handoff_metadata_ids_persisted_with_provenance(env):
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        res = await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks",
            json={"block_type": "text_markdown", "content": "متن", "metadata": HANDOFF_META},
        )
    meta = res.json()["metadata"]
    assert meta["conversation_id"] == "conv-1" and meta["message_id"] == "msg-1"
    assert meta["citation"] == "فیزیک دهم — فصل ۲ — صفحهٔ ۱۴" and meta["title"] == "فیزیک دهم"


@pytest.mark.asyncio
async def test_handoff_users_are_isolated(env):
    async with _client() as client:
        nb_id = await _new_notebook(client, env.ids["book_id"])
        await client.post(
            f"/api/v1/notebooks/{nb_id}/blocks",
            json={"block_type": "text_markdown", "content": "مال کاربر اول", "metadata": HANDOFF_META},
        )
    # switch the authenticated student to the second user
    env.current["id"] = env.ids["other_id"]
    async with _client() as client2:
        # a second user cannot see or reuse the first user's notebook
        listing = await client2.get("/api/v1/notebooks")
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert all(item["id"] != nb_id for item in items)
        foreign = await client2.get(f"/api/v1/notebooks/{nb_id}")
        assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_handoff_notebook_create_dedupes_per_book(env):
    async with _client() as client:
        first = await client.post(
            "/api/v1/notebooks?dedupe_book=1",
            json={"title": "دفترچهٔ فیزیک", "book_id": env.ids["book_id"]},
        )
        second = await client.post(
            "/api/v1/notebooks?dedupe_book=1",
            json={"title": "دفترچهٔ فیزیک (دوباره)", "book_id": env.ids["book_id"]},
        )
        assert first.status_code == 201 and second.status_code == 201
        assert second.json()["id"] == first.json()["id"]
        # generic creation (no dedupe flag) keeps its current behaviour
        third = await client.post("/api/v1/notebooks", json={"title": "دفترچهٔ عادی", "book_id": env.ids["book_id"]})
        assert third.status_code == 201 and third.json()["id"] != first.json()["id"]
    assert await _count(env.factory, Notebook, Notebook.book_id == env.ids["book_id"]) == 2


