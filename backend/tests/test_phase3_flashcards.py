"""Phase 3 tests: SM-2 scheduling, flashcard generation through the runtime
(quota, capability flag, ai_audit_logs, server-owned citations), student/admin
routes, and Anki (.apkg) export validity.

No network I/O: the model call (`ai_gateway.complete_json`) is replaced by a
deterministic fake; the gateway still writes real `ai_audit_logs` rows.
"""

from __future__ import annotations

import io
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import require_student
from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_curriculum_taxonomy, seed_grades, seed_majors, seed_plans
from app.db.session import get_session
from app.main import app
from app.models.auth import User
from app.models.capabilities import Capability
from app.models.chat import ChatSession
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.models.exam import ExamSession
from app.models.flashcards import Flashcard, FlashcardDeck, FlashcardReview
from app.models.governance import AiAuditLog, UserQuota
from app.services import capability_service, flashcard_service, skill_seed
from app.services import ai_gateway
from app.services.anki_export import build_apkg_bytes, to_anki_html
from app.services.sm2 import SchedulerState, schedule_review

ADMIN_HEADERS = {"X-Admin-Username": "admin", "X-Admin-Password": "123"}
NOW = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# SM-2 (pure)
# ---------------------------------------------------------------------------


def test_sm2_rating_3_builds_standard_intervals():
    state = SchedulerState()
    intervals = []
    for _ in range(4):
        result = schedule_review(state, 3, NOW)
        intervals.append(result.interval_days)
        state = SchedulerState(result.ease_factor, result.interval_days, result.repetitions)
    assert intervals == [1, 6, 15, 38]
    assert state.ease_factor == 2.5
    assert result.next_review_at == NOW + timedelta(days=38)


def test_sm2_rating_1_forgot_resets_repetitions_and_drops_ease():
    result = schedule_review(SchedulerState(2.5, 38, 4), 1, NOW)
    assert result.repetitions == 0
    assert result.interval_days == 1
    assert result.ease_factor == 1.7
    assert result.last_rating == 1
    assert result.next_review_at == NOW + timedelta(days=1)


def test_sm2_rating_2_hard_keeps_card_but_lowers_ease():
    result = schedule_review(SchedulerState(2.5, 38, 3), 2, NOW)
    assert result.repetitions == 4  # q=3 still counts as a successful recall
    assert result.ease_factor == 2.36
    assert result.interval_days == round(38 * 2.36)


def test_sm2_rating_4_easy_raises_ease_and_grows_interval():
    result = schedule_review(SchedulerState(2.5, 6, 2), 4, NOW)
    assert result.ease_factor == 2.6
    assert result.repetitions == 3
    assert result.interval_days == round(6 * 2.6)


def test_sm2_ease_never_falls_below_floor_and_bad_rating_rejected():
    state = SchedulerState(1.5, 1, 1)
    for _ in range(5):
        state = SchedulerState(**{
            "ease_factor": schedule_review(state, 1, NOW).ease_factor,
            "interval_days": 1,
            "repetitions": 0,
        })
    assert state.ease_factor == 1.3
    with pytest.raises(ValueError):
        schedule_review(SchedulerState(), 5, NOW)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase3.sqlite3'}")
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
        grade = await session.scalar(select(Grade).where(Grade.number == 10))
        major = await session.scalar(select(Major).limit(1))
        book = Book(
            title="ریاضی دهم",
            grade_id=grade.id,
            major_id=major.id if major else None,
            pdf_file_path="/tmp/none.pdf",
            total_pdf_pages=10,
            status=BookStatus.ready,
            catalog_status="approved",
        )
        session.add(book)
        await session.flush()
        for index, printed in ((1, 10), (2, 11), (3, 12)):
            session.add(
                BookPage(
                    book_id=book.id,
                    pdf_page_index=index,
                    printed_page_number=printed,
                    chapter_number=3,
                    chapter_title="توان",
                    markdown_content=f"متن صفحهٔ {printed} با فرمول $x^2$",
                    page_image_path="/tmp/none.png",
                    status=PageStatus.done,
                )
            )
        student = User(
            phone_number="09120000001",
            full_name="دانش‌آموز",
            role="student",
            tokens_remaining=1_000_000,
            plan_expires_at=NOW + timedelta(days=30),
            is_active=True,
        )
        other = User(
            phone_number="09120000002",
            full_name="دیگری",
            role="student",
            tokens_remaining=1_000_000,
            plan_expires_at=NOW + timedelta(days=30),
            is_active=True,
        )
        session.add_all([student, other])
        await session.flush()
        chat = ChatSession(
            book_id=book.id,
            user_id=student.id,
            grade_number=10,
            major_code="general",
            mode="tutor",
            title="گفت‌وگوی تست",
            messages=[
                {
                    "id": "m-grounded",
                    "role": "assistant",
                    "content": "توان دوم عددی است که در خودش ضرب می‌شود.",
                    # Client-written citation claims a different printed page: must be ignored.
                    "sources": [{"book_id": book.id, "pdf_page_index": 1, "printed_page_number": 999}],
                },
                {
                    "id": "m-fake",
                    "role": "assistant",
                    "content": "پاسخ بدون منبع واقعی",
                    "sources": [{"book_id": book.id, "pdf_page_index": 77}],
                },
            ],
        )
        session.add(chat)
        exam = ExamSession(
            book_id=book.id,
            user_id=student.id,
            grade_number=10,
            major_code="general",
            title="آزمون تست",
            exam_type="final",
            time_limit_seconds=600,
            status="submitted",
            questions=[
                {
                    "id": "q1",
                    "prompt": "حاصل ۲ به توان ۲ چیست؟",
                    "choices": {"A": "۲", "B": "۴", "C": "۶", "D": "۸"},
                    "correct_option": "B",
                    "explanation": "۲×۲=۴",
                    "points": 1,
                    "source": {
                        "book_id": book.id,
                        "book_title": "ریاضی دهم",
                        "chapter_number": 3,
                        "chapter_title": "توان",
                        "pdf_page_index": 2,
                        "printed_page_number": 11,
                    },
                },
            ],
            submitted_answers={"q1": "A"},
            report_card={
                "score": 0,
                "by_question": [
                    {"id": "q1", "answer": "A", "correct": False, "correct_option": "B",
                     "explanation": "۲×۲=۴", "source": {}},
                ],
            },
            expires_at=NOW + timedelta(hours=1),
        )
        session.add(exam)
        await session.commit()
        ids.update(book_id=book.id, student_id=student.id, other_id=other.id,
                   chat_id=chat.id, exam_id=exam.id)

    async def override_get_session():
        async with factory() as session:
            yield session

    async def override_student():
        async with factory() as session:
            return await session.get(User, ids["student_id"])

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_student] = override_student
    from app.db import session as db_session_mod

    monkeypatch.setattr(db_session_mod, "async_session_factory", factory)
    monkeypatch.setattr(ai_gateway, "async_session_factory", factory)
    monkeypatch.setattr(ai_gateway, "get_settings",
                        lambda: SimpleNamespace(tutor_model="test-model", llm_timeout=5))

    calls: list[list[dict[str, str]]] = []

    async def fake_complete_json(model, messages):
        calls.append(messages)
        return {
            "cards": [
                {"front_md": "توان دوم یعنی چه؟", "back_md": "ضرب عدد در خودش، مثل $x^2$",
                 "hint_md": "به ضرب فکر کنید", "source_index": 0, "tags": ["توان"]},
                {"front_md": "کارت بدون منبع معتبر", "back_md": "x", "hint_md": "",
                 "source_index": 99, "tags": []},
            ]
        }

    monkeypatch.setattr(ai_gateway, "complete_json", fake_complete_json)

    env_obj = SimpleNamespace(factory=factory, ids=ids, calls=calls)
    yield env_obj
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_student, None)
    await engine.dispose()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Capability flag enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabling_flashcards_capability_closes_api_and_restores_on_enable(env):
    async with _client() as client:
        assert (await client.get("/api/v1/flashcards/decks")).status_code == 200
        off = await client.put("/api/v1/admin/capabilities/flashcards", headers=ADMIN_HEADERS,
                               json={"is_enabled": False})
        assert off.status_code == 200
        assert (await client.get("/api/v1/flashcards/decks")).status_code == 403
        assert (await client.get("/api/v1/flashcards/due")).status_code == 403
        gen = await client.post("/api/v1/flashcards/generate",
                                json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3})
        assert gen.status_code == 403
        assert env.calls == []  # no model call while the flag is off
        on = await client.put("/api/v1/admin/capabilities/flashcards", headers=ADMIN_HEADERS,
                              json={"is_enabled": True})
        assert on.status_code == 200
        assert (await client.get("/api/v1/flashcards/decks")).status_code == 200


# ---------------------------------------------------------------------------
# Generation: book chapter via RAG-style page source, audit, citations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_from_book_chapter_writes_audit_quota_and_citations(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3, "count": 5},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created_count"] == 1  # the card with out-of-range source_index is dropped
    card = body["cards"][0]
    assert card["front_md"] == "توان دوم یعنی چه؟"
    assert card["hint_md"] == "به ضرب فکر کنید"
    assert card["citations"], "every generated card must carry textbook citations"
    cited = {c["printed_page_number"] for c in card["citations"]}
    assert cited <= {10, 11, 12}
    assert all("ریاضی دهم" in c["citation"] for c in card["citations"])
    assert "صفحهٔ" in card["citations"][0]["citation"]

    # The prompt was grounded in the book text, not in client input.
    user_msg = env.calls[0][-1]["content"]
    assert "متن صفحهٔ 10" in user_msg

    async with env.factory() as session:
        audit = await session.get(AiAuditLog, body["audit_id"])
        quota = await session.scalar(
            select(UserQuota).where(UserQuota.user_id == env.ids["student_id"],
                                    UserQuota.feature_key == "flashcards")
        )
        assert audit is not None and audit.feature_key == "flashcards"
        assert audit.user_id == env.ids["student_id"]
        assert audit.status == "success"
        assert quota is not None and quota.daily_tokens_used > 0


@pytest.mark.asyncio
async def test_generate_from_book_rejects_non_ready_book_without_model_call(env):
    """A book that is still ingesting must not leak its done pages to flashcard
    generation: the ready-only gate 404s before any model call."""
    async with env.factory() as session:
        book = await session.get(Book, env.ids["book_id"])
        book.status = BookStatus.ingesting
        await session.commit()
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3},
        )
    assert resp.status_code == 404, resp.text
    assert env.calls == []


@pytest.mark.asyncio
async def test_generate_rejects_empty_chapter_range_without_model_call(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 9},
        )
    assert resp.status_code == 422
    assert env.calls == []


@pytest.mark.asyncio
async def test_generate_respects_quota_before_model_call(env):
    async with env.factory() as session:
        user = await session.get(User, env.ids["student_id"])
        user.tokens_remaining = 0
        await session.commit()
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3},
        )
    assert resp.status_code == 402
    assert env.calls == []
    async with env.factory() as session:
        count = len(list((await session.scalars(select(Flashcard))).all()))
    assert count == 0


# ---------------------------------------------------------------------------
# Generation: chat & mistake sources, server-owned citations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_source_uses_only_verified_citations_rebuilt_from_db(env):
    async with _client() as client:
        ok = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "chat", "chat_session_id": env.ids["chat_id"],
                  "message_ids": ["m-grounded"], "count": 3},
        )
        assert ok.status_code == 201, ok.text
        cite = ok.json()["cards"][0]["citations"][0]
        # The client claimed printed page 999; the server rebuilt it from book_pages.
        assert cite["printed_page_number"] == 10
        assert cite["pdf_page_index"] == 1

        ungrounded = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "chat", "chat_session_id": env.ids["chat_id"],
                  "message_ids": ["m-fake"], "count": 3},
        )
    assert ungrounded.status_code == 422
    assert len(env.calls) == 1  # the rejected request never reached the model


@pytest.mark.asyncio
async def test_chat_session_of_another_user_is_not_visible(env):
    async with _client() as client:
        async with env.factory() as session:
            chat = await session.get(ChatSession, env.ids["chat_id"])
            chat.user_id = env.ids["other_id"]
            await session.commit()
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "chat", "chat_session_id": env.ids["chat_id"],
                  "message_ids": ["m-grounded"]},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mistake_source_builds_cards_from_wrong_answers_with_citation(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "mistake", "exam_id": env.ids["exam_id"], "count": 3},
        )
    assert resp.status_code == 201, resp.text
    card = resp.json()["cards"][0]
    assert card["citations"][0]["printed_page_number"] == 11
    user_msg = env.calls[-1][-1]["content"]
    assert "حاصل ۲ به توان ۲" in user_msg


# ---------------------------------------------------------------------------
# Decks, due queue, SM-2 reviews, ownership
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_due_queue_and_review_flow_uses_sm2(env):
    async with _client() as client:
        deck = (await client.post("/api/v1/flashcards/decks", json={"title": "دستهٔ من"})).json()
        card = (await client.post(
            f"/api/v1/flashcards/decks/{deck['id']}/cards",
            json={"front_md": "$a^2$ چیست؟", "back_md": "مربع a", "hint_md": "", "tags": ["جبر"]},
        )).json()
        due = (await client.get("/api/v1/flashcards/due")).json()
        assert due["due_count"] == 1 and due["cards"][0]["id"] == card["id"]

        reviewed = await client.post(f"/api/v1/flashcards/{card['id']}/review", json={"rating": 1})
        assert reviewed.status_code == 200
        review = reviewed.json()["review"]
        assert review["repetitions"] == 0 and review["interval_days"] == 1
        assert review["last_rating"] == 1
        assert (await client.get("/api/v1/flashcards/due")).json()["due_count"] == 0

        second = await client.post(f"/api/v1/flashcards/{card['id']}/review", json={"rating": 4})
        assert second.json()["review"]["repetitions"] == 1
        bad = await client.post(f"/api/v1/flashcards/{card['id']}/review", json={"rating": 7})
        assert bad.status_code == 422

        detail = (await client.get(f"/api/v1/flashcards/decks/{deck['id']}")).json()
        assert detail["stats"]["total"] == 1
        assert detail["cards"][0]["review"]["review_count"] == 2


@pytest.mark.asyncio
async def test_student_cannot_touch_another_users_deck(env):
    async with env.factory() as session:
        other_deck = FlashcardDeck(user_id=env.ids["other_id"], title="خصوصی", source_type="manual")
        session.add(other_deck)
        await session.commit()
        deck_id = other_deck.id
    async with _client() as client:
        assert (await client.get(f"/api/v1/flashcards/decks/{deck_id}")).status_code == 404
        assert (await client.delete(f"/api/v1/flashcards/decks/{deck_id}")).status_code == 404


# ---------------------------------------------------------------------------
# Anki export validity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anki_export_is_valid_non_empty_apkg(env):
    async with _client() as client:
        gen = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3},
        )
        deck_id = gen.json()["deck_id"]
        resp = await client.get(f"/api/v1/flashcards/decks/{deck_id}/export/anki")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    data = resp.content
    assert len(data) > 0 and data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert "collection.anki2" in names or "collection.anki21" in names
        db_name = "collection.anki2" if "collection.anki2" in names else "collection.anki21"
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            tmp.write(archive.read(db_name))
            tmp.flush()
            conn = sqlite3.connect(tmp.name)
            try:
                notes = conn.execute("select flds from notes").fetchall()
                decks = conn.execute("select count(*) from cards").fetchone()[0]
            finally:
                conn.close()
    assert len(notes) == 1 and decks == 1
    assert "\\(x^2\\)" in notes[0][0]  # KaTeX → Anki MathJax delimiters


def test_anki_helpers_escape_html_and_convert_math():
    assert to_anki_html("<script>$x$</script>") == "&lt;script&gt;\\(x\\)&lt;/script&gt;"
    assert to_anki_html("$$a+b$$\nخط") == "\\[a+b\\]<br>خط"
    with pytest.raises(ValueError):
        build_apkg_bytes(1, "خالی", [])


# ---------------------------------------------------------------------------
# Admin oversight & moderation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_routes_require_admin_and_moderate_public_decks(env):
    async with env.factory() as session:
        deck = FlashcardDeck(user_id=env.ids["student_id"], title="عمومی", source_type="manual")
        session.add(deck)
        await session.flush()
        session.add(Flashcard(deck_id=deck.id, front_md="الف", back_md="ب", hint_md="",
                              citations_json=[], tags_json=[]))
        await session.commit()
        deck_id = deck.id

    async with _client() as client:
        anon = await client.get("/api/v1/admin/flashcards/decks")
        assert anon.status_code == 401
        listing = await client.get("/api/v1/admin/flashcards/decks", headers=ADMIN_HEADERS)
        assert listing.status_code == 200
        row = next(item for item in listing.json() if item["id"] == deck_id)
        assert row["card_count"] == 1 and row["owner"]["id"] == env.ids["student_id"]
        stats = (await client.get("/api/v1/admin/flashcards/stats", headers=ADMIN_HEADERS)).json()
        assert stats["decks"] >= 1 and stats["cards"] >= 1

        # Publishing requires approval first.
        bad = await client.patch(f"/api/v1/admin/flashcards/decks/{deck_id}/moderation",
                                 headers=ADMIN_HEADERS, json={"is_public": True, "admin_approved": False})
        assert bad.status_code == 422
        approved = await client.patch(f"/api/v1/admin/flashcards/decks/{deck_id}/moderation",
                                      headers=ADMIN_HEADERS, json={"is_public": True, "admin_approved": True})
        assert approved.status_code == 200

        library = (await client.get("/api/v1/flashcards/library")).json()
        assert any(item["id"] == deck_id for item in library)
        copied = await client.post(f"/api/v1/flashcards/library/{deck_id}/copy")
        assert copied.status_code == 201
        assert copied.json()["id"] != deck_id
        assert copied.json()["stats"]["total"] == 1  # the copy owns its own card

        removed = await client.delete(f"/api/v1/admin/flashcards/decks/{deck_id}", headers=ADMIN_HEADERS)
        assert removed.status_code == 204


@pytest.mark.asyncio
async def test_unapproved_deck_is_not_in_public_library(env):
    async with env.factory() as session:
        deck = FlashcardDeck(user_id=env.ids["other_id"], title="در انتظار", source_type="manual",
                             is_public=True, admin_approved=False)
        session.add(deck)
        await session.commit()
        deck_id = deck.id
    async with _client() as client:
        library = (await client.get("/api/v1/flashcards/library")).json()
        assert all(item["id"] != deck_id for item in library)
        assert (await client.post(f"/api/v1/flashcards/library/{deck_id}/copy")).status_code == 404


@pytest.mark.asyncio
async def test_flashcard_generator_skill_is_seeded_active_and_capability_enabled(env):
    async with env.factory() as session:
        cap = await session.get(Capability, "flashcards")
        from app.services.capability_runtime import get_skill_by_slug
        skill = await get_skill_by_slug(session, "flashcard_generator")
    assert cap is not None and cap.is_enabled is True
    assert skill is not None and skill.is_active is True
    assert skill.capability_key == "flashcards"


def test_migration_revises_phase2_head():
    source = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
              / "e9f0a1b2c3d4_phase3_flashcards.py").read_text(encoding="utf-8")
    assert 'down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"' in source
    assert "flashcard_decks" in source and "flashcard_reviews" in source


# ---------------------------------------------------------------------------
# Phase 03 redesign: card issue reports + real last_review stat
# ---------------------------------------------------------------------------


async def _deck_with_card(client, title="دستهٔ گزارش"):
    created = await client.post("/api/v1/flashcards/decks", json={"title": title})
    assert created.status_code == 201, created.text
    deck = created.json()
    card = await client.post(
        f"/api/v1/flashcards/decks/{deck['id']}/cards",
        json={"front_md": "سؤال کارت", "back_md": "پاسخ کارت"},
    )
    assert card.status_code == 201, card.text
    return deck, card.json()


@pytest.mark.asyncio
async def test_card_report_lifecycle_and_duplicate_guard(env):
    async with _client() as client:
        deck, card = await _deck_with_card(client)

        first = await client.post(
            f"/api/v1/flashcards/cards/{card['id']}/report",
            json={"reason": "not_from_book", "note": "این پاسخ از کتاب نیست"},
        )
        assert first.status_code == 201, first.text
        assert first.json()["status"] == "open" and first.json()["reason"] == "not_from_book"

        # a second open report for the same card by the same student is rejected
        duplicate = await client.post(
            f"/api/v1/flashcards/cards/{card['id']}/report", json={"reason": "unclear"}
        )
        assert duplicate.status_code == 409

        # invalid reason is rejected before touching the table
        invalid = await client.post(
            f"/api/v1/flashcards/cards/{card['id']}/report", json={"reason": "whatever"}
        )
        assert invalid.status_code == 422

        # admin sees the report and resolves it
        listing = await client.get("/api/v1/admin/flashcards/reports", headers=ADMIN_HEADERS)
        assert listing.status_code == 200
        rows = [row for row in listing.json() if row["card_id"] == card["id"]]
        assert rows and rows[0]["user_name"] and rows[0]["card_front"].startswith("سؤال کارت")

        resolved = await client.patch(
            f"/api/v1/admin/flashcards/reports/{rows[0]['id']}",
            headers=ADMIN_HEADERS,
            json={"status": "resolved"},
        )
        assert resolved.status_code == 200 and resolved.json()["status"] == "resolved"

        # after triage the student can report the same card again
        again = await client.post(
            f"/api/v1/flashcards/cards/{card['id']}/report", json={"reason": "unclear"}
        )
        assert again.status_code == 201


@pytest.mark.asyncio
async def test_card_report_rejects_foreign_card(env):
    async with _client() as client:
        # a deck owned by the other user (not the authenticated student)
        async with env.factory() as session:
            foreign_deck = FlashcardDeck(user_id=env.ids["other_id"], title="دستهٔ دیگری")
            session.add(foreign_deck)
            await session.flush()
            foreign_card = Flashcard(deck_id=foreign_deck.id, front_md="سؤال", back_md="پاسخ")
            session.add(foreign_card)
            await session.commit()
            card_id = foreign_card.id
        res = await client.post(
            f"/api/v1/flashcards/cards/{card_id}/report", json={"reason": "unclear"}
        )
        assert res.status_code == 404
        listed = await client.get("/api/v1/admin/flashcards/reports", headers=ADMIN_HEADERS)
        assert all(row["card_id"] != card_id for row in listed.json())


@pytest.mark.asyncio
async def test_deck_last_review_is_real_and_null_before_first_study(env):
    async with _client() as client:
        deck, card = await _deck_with_card(client, title="دستهٔ آمار")
        decks = (await client.get("/api/v1/flashcards/decks")).json()
        mine = next(row for row in decks if row["id"] == deck["id"])
        assert mine["stats"]["last_review"] is None  # never studied yet

        first = await client.post(f"/api/v1/flashcards/{card['id']}/review", json={"rating": 3})
        assert first.status_code == 200, first.text

        decks = (await client.get("/api/v1/flashcards/decks")).json()
        mine = next(row for row in decks if row["id"] == deck["id"])
        assert mine["stats"]["last_review"] is not None
        assert mine["stats"]["due"] == 0  # rating 3 schedules the next review in the future
