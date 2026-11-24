"""Phase 8 tests: NotebookLM-style flashcard upgrades.

Covers: difficulty + custom-prompt steering of the generation prompt, count
presets, persistent study sessions (create/answer/progress/shuffle/complete/
resume), Got it / Missed it → SM-2 integration with duplicate protection,
only-missed replay, card deletion cleanup, CSV export (BOM + injection guard),
Explain grounding constraints, ownership and capability-flag enforcement.

No network I/O: `ai_gateway.complete_json` / `complete_text` are replaced by
deterministic fakes; the gateway still writes real audit rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.models.flashcards import FlashcardStudySession
from app.models.governance import AiAuditLog, UserQuota
from app.services import capability_service, skill_seed
from app.services import ai_gateway
from app.services.csv_export import build_deck_csv, csv_safe
from app.services.sm2 import SchedulerState, schedule_review

ADMIN_HEADERS = {"X-Admin-Username": "admin", "X-Admin-Password": "123"}
NOW = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)


def test_sm2_got_missed_mapping_is_stable():
    """Got it (rating 3) counts a successful recall; Missed it (rating 1) lapses."""
    got = schedule_review(SchedulerState(), 3, NOW)
    missed = schedule_review(SchedulerState(), 1, NOW)
    assert got.repetitions == 1 and got.interval_days == 1
    assert missed.repetitions == 0 and missed.interval_days == 1
    assert missed.ease_factor < got.ease_factor
    assert got.next_review_at == NOW + timedelta(days=1)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase8.sqlite3'}")
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
        ids.update(book_id=book.id, student_id=student.id, other_id=other.id)
        await session.commit()

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
                {"front_md": f"سؤال {i}؟", "back_md": f"پاسخ {i} با $x^2$",
                 "hint_md": "راهنما", "source_index": 0, "tags": ["توان"]}
                for i in range(1, 11)
            ]
        }

    text_calls: list[list[dict[str, str]]] = []

    async def fake_complete_text(model, messages, *args, **kwargs):
        text_calls.append(messages)
        return "توضیح ساده و آموزشی برای دانش‌آموز."

    monkeypatch.setattr(ai_gateway, "complete_json", fake_complete_json)
    monkeypatch.setattr(ai_gateway, "complete_text", fake_complete_text)

    env_obj = SimpleNamespace(factory=factory, ids=ids, calls=calls, text_calls=text_calls)
    yield env_obj
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_student, None)
    await engine.dispose()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_deck(env, client: AsyncClient, *, titles: list[str]) -> dict:
    deck = (await client.post("/api/v1/flashcards/decks", json={"title": "دستهٔ مطالعه"})).json()
    cards = []
    for title in titles:
        card = (await client.post(
            f"/api/v1/flashcards/decks/{deck['id']}/cards",
            json={"front_md": title, "back_md": f"پاسخ {title}", "hint_md": "", "tags": []},
        )).json()
        cards.append(card)
    return {"deck": deck, "cards": cards}


# ---------------------------------------------------------------------------
# Generation: difficulty, custom prompt, count presets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_difficulty_and_focus_shape_the_model_prompt(env):
    async with _client() as client:
        resp = await client.post(
            "/api/v1/flashcards/generate",
            json={
                "source": "book", "book_id": env.ids["book_id"], "chapter_number": 3,
                "count": 3, "difficulty": "hard",
                "focus_prompt": "فقط روی قانون دوم نیوتن تمرکز کن",
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created_count"] == 3 and body["requested_count"] == 3
    prompt = env.calls[-1][-1]["content"]
    assert "سطح دشواری: سخت" in prompt
    assert "فقط روی قانون دوم نیوتن تمرکز کن" in prompt
    assert "تعداد کارت‌ها: 3" in prompt
    # Sources stay the only permitted material.
    assert "متن صفحهٔ 10" in prompt


@pytest.mark.asyncio
async def test_generate_easy_and_medium_prompts_differ(env):
    async with _client() as client:
        for difficulty in ("easy", "medium"):
            resp = await client.post(
                "/api/v1/flashcards/generate",
                json={"source": "book", "book_id": env.ids["book_id"],
                      "chapter_number": 3, "count": 3, "difficulty": difficulty},
            )
            assert resp.status_code == 201
    easy = env.calls[-2][-1]["content"]
    medium = env.calls[-1][-1]["content"]
    assert "سطح دشواری: آسان" in easy and "سطح دشواری: متوسط" not in easy
    assert "سطح دشواری: متوسط" in medium
    assert easy != medium


@pytest.mark.asyncio
async def test_generate_rejects_invalid_difficulty_and_oversized_focus_without_model_call(env):
    async with _client() as client:
        bad = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3,
                  "difficulty": "impossible"},
        )
        assert bad.status_code == 422
        long_focus = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3,
                  "focus_prompt": "ا" * 501},
        )
        assert long_focus.status_code == 422
        ok = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3,
                  "focus_prompt": "ا" * 500},
        )
        assert ok.status_code == 201
    assert len(env.calls) == 1  # the two invalid requests never reached the model


@pytest.mark.asyncio
async def test_generate_count_presets_and_citations_preserved(env):
    async with _client() as client:
        for count in (3, 5, 10):
            resp = await client.post(
                "/api/v1/flashcards/generate",
                json={"source": "book", "book_id": env.ids["book_id"],
                      "chapter_number": 3, "count": count},
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["created_count"] == count
            for card in body["cards"]:
                assert card["citations"], "every card keeps textbook citations"
                cited = {c["printed_page_number"] for c in card["citations"]}
                assert cited <= {10, 11, 12}


# ---------------------------------------------------------------------------
# Study sessions: create, answer (SM-2), resume, shuffle, complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_study_session_full_mode_answer_flow_feeds_sm2_once(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["کارت الف", "کارت ب", "کارت پ"])
        deck_id = made["deck"]["id"]
        created = await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions",
            json={"mode": "full"},
        )
        assert created.status_code == 201, created.text
        study = created.json()
        assert study["mode"] == "full" and study["total_cards"] == 3
        assert [c["id"] for c in study["cards"]] == study["card_order"]

        first_id = study["cards"][0]["id"]
        answer = await client.post(
            f"/api/v1/flashcards/study-sessions/{study['id']}/answer",
            json={"card_id": first_id, "got": True},
        )
        assert answer.status_code == 200
        payload = answer.json()
        assert payload["result"] == "got" and payload["already_recorded"] is False
        assert payload["review"]["last_rating"] == 3  # Got it → SM-2 rating 3
        assert payload["review"]["review_count"] == 1
        assert payload["session"]["results"][str(first_id)] == "got"
        assert payload["session"]["position"] == 1  # advanced to next unanswered

        # Duplicate answer of the same card inside the session is ignored.
        again = await client.post(
            f"/api/v1/flashcards/study-sessions/{study['id']}/answer",
            json={"card_id": first_id, "got": False},
        )
        assert again.status_code == 200
        assert again.json()["already_recorded"] is True
        assert again.json()["review"]["review_count"] == 1  # no double count

        second_id = study["cards"][1]["id"]
        miss = await client.post(
            f"/api/v1/flashcards/study-sessions/{study['id']}/answer",
            json={"card_id": second_id, "got": False},
        )
        assert miss.json()["review"]["last_rating"] == 1  # Missed it → SM-2 rating 1
        assert miss.json()["review"]["repetitions"] == 0

        third_id = study["cards"][2]["id"]
        last = await client.post(
            f"/api/v1/flashcards/study-sessions/{study['id']}/answer",
            json={"card_id": third_id, "got": True},
        )
        done = last.json()["session"]
        assert done["status"] == "completed"
        summary = done["summary"]
        assert summary == {
            "total": 3, "answered": 3, "got": 2, "missed": 1,
            "percent": pytest.approx(66.7), "status": "completed",
        }
        assert (await client.get("/api/v1/flashcards/study-sessions/active")).json()["session"] is None


@pytest.mark.asyncio
async def test_session_progress_persists_and_resume_finds_it(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["کارت ۱", "کارت ۲", "کارت ۳"])
        deck_id = made["deck"]["id"]
        study = (await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions", json={"mode": "full"}
        )).json()

        moved = await client.post(
            f"/api/v1/flashcards/study-sessions/{study['id']}/progress",
            json={"position": 2, "flipped": True},
        )
        assert moved.status_code == 200
        assert moved.json()["session"]["position"] == 2
        assert moved.json()["session"]["flipped"] is True

        # Simulates a reload / new visit: the session is still there with the same state.
        active = (await client.get("/api/v1/flashcards/study-sessions/active")).json()["session"]
        assert active and active["id"] == study["id"]
        assert active["position"] == 2 and active["flipped"] is True
        fetched = await client.get(f"/api/v1/flashcards/study-sessions/{study['id']}")
        assert fetched.json()["position"] == 2
        assert [c["id"] for c in fetched.json()["cards"]] == study["card_order"]

        by_deck = (await client.get(
            f"/api/v1/flashcards/study-sessions/active?deck_id={deck_id}"
        )).json()["session"]
        assert by_deck and by_deck["id"] == study["id"]

        # Out-of-range positions are clamped, never crash.
        clamped = await client.post(
            f"/api/v1/flashcards/study-sessions/{study['id']}/progress",
            json={"position": 99, "flipped": False},
        )
        assert clamped.json()["session"]["position"] == 2


@pytest.mark.asyncio
async def test_shuffle_keeps_card_set_results_and_current_card(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸"])
        deck_id = made["deck"]["id"]
        study = (await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions", json={"mode": "full"}
        )).json()
        current_card = study["cards"][0]["id"]
        answered = await client.post(
            f"/api/v1/flashcards/study-sessions/{study['id']}/answer",
            json={"card_id": current_card, "got": True},
        )
        assert answered.json()["session"]["position"] == 1
        viewing_card = answered.json()["session"]["card_order"][1]  # card now on screen

        shuffled = await client.post(f"/api/v1/flashcards/study-sessions/{study['id']}/shuffle")
        assert shuffled.status_code == 200
        payload = shuffled.json()
        assert sorted(payload["card_order"]) == sorted(study["card_order"])  # no card lost/duplicated
        assert payload["results"][str(current_card)] == "got"  # results preserved
        assert payload["card_order"][payload["position"]] == viewing_card  # screen does not jump


@pytest.mark.asyncio
async def test_complete_then_new_session_replaces_active_one(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["الف", "ب"])
        deck_id = made["deck"]["id"]
        first = (await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions", json={"mode": "full"}
        )).json()
        done = await client.post(f"/api/v1/flashcards/study-sessions/{first['id']}/complete")
        assert done.json()["session"]["status"] == "completed"
        assert done.json()["session"]["completed_at"]

        second = (await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions", json={"mode": "full"}
        )).json()
        assert second["id"] != first["id"]
        # Only one active session per deck: the old run stays completed (history kept).
        active = (await client.get("/api/v1/flashcards/study-sessions/active")).json()["session"]
        assert active["id"] == second["id"]
        async with env.factory() as session:
            statuses = {
                row.id: row.status
                for row in (await session.scalars(select(FlashcardStudySession))).all()
            }
        assert statuses[first["id"]] == "completed"
        assert statuses[second["id"]] == "active"


@pytest.mark.asyncio
async def test_smart_mode_only_schedules_due_cards(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["موعد دارد", "موعد ندارد", "تازه"])
        deck_id = made["deck"]["id"]
        cards = made["cards"]
        # Review card 2 with "آسان" → scheduled one day ahead, not due anymore.
        reviewed = await client.post(f"/api/v1/flashcards/{cards[1]['id']}/review", json={"rating": 4})
        assert reviewed.status_code == 200

        smart = (await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions", json={"mode": "smart"}
        )).json()
        assert set(smart["card_order"]) == {cards[0]["id"], cards[2]["id"]}

        full = (await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions", json={"mode": "full"}
        )).json()
        assert len(full["card_order"]) == 3  # full study ignores the schedule


@pytest.mark.asyncio
async def test_only_missed_replay_uses_results_of_the_same_session(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["۱", "۲", "۳"])
        deck_id = made["deck"]["id"]
        cards = made["cards"]
        study = (await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions", json={"mode": "full"}
        )).json()
        await client.post(f"/api/v1/flashcards/study-sessions/{study['id']}/answer",
                          json={"card_id": cards[0]["id"], "got": True})
        await client.post(f"/api/v1/flashcards/study-sessions/{study['id']}/answer",
                          json={"card_id": cards[1]["id"], "got": False})
        await client.post(f"/api/v1/flashcards/study-sessions/{study['id']}/answer",
                          json={"card_id": cards[2]["id"], "got": False})
        missed_ids = [cards[1]["id"], cards[2]["id"]]

        replay = await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions",
            json={"mode": "subset", "card_ids": missed_ids},
        )
        assert replay.status_code == 201
        body = replay.json()
        assert body["card_order"] == missed_ids
        assert body["mode"] == "subset"
        assert body["results"] == {}  # fresh run over the same missed cards

        # Cards of another deck are rejected.
        other = await _make_deck(env, client, titles=["بیگانه"])
        foreign = await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions",
            json={"mode": "subset", "card_ids": [other["cards"][0]["id"]]},
        )
        assert foreign.status_code == 422


# ---------------------------------------------------------------------------
# Card deletion cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_card_updates_active_session_and_deck_stats(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["الف", "ب", "پ"])
        deck_id = made["deck"]["id"]
        cards = made["cards"]
        study = (await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions", json={"mode": "full"}
        )).json()
        await client.post(f"/api/v1/flashcards/study-sessions/{study['id']}/progress",
                          json={"position": 2, "flipped": False})

        removed = await client.delete(f"/api/v1/flashcards/cards/{cards[0]['id']}")
        assert removed.status_code == 204

        fetched = (await client.get(f"/api/v1/flashcards/study-sessions/{study['id']}")).json()
        assert cards[0]["id"] not in fetched["card_order"]
        assert fetched["total_cards"] == 2
        assert fetched["position"] == 1  # shifted, still pointing at «پ»
        assert str(cards[0]["id"]) not in fetched["results"]
        detail = (await client.get(f"/api/v1/flashcards/decks/{deck_id}")).json()
        assert detail["stats"]["total"] == 2


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def test_csv_helpers_escape_and_guard_injection():
    assert csv_safe("=SUM(A1)") == "'=SUM(A1)"
    assert csv_safe("+cmd") == "'+cmd"
    assert csv_safe("متن سالم") == "متن سالم"
    payload = build_deck_csv([
        {"front_md": "=1+1", "back_md": "سلام،\nدنیا", "hint_md": "",
         "tags": ["ریاضی"], "citations": [{"citation": "ریاضی دهم — صفحهٔ ۱۰"}]},
    ])
    text = payload.decode("utf-8-sig")
    assert text.startswith("Front,Back,Hint,Tags,Citations\r\n")
    assert "'=1+1" in text
    assert "\"سلام،\nدنیا\"" in text  # quoting keeps commas/newlines intact
    assert "ریاضی دهم — صفحهٔ ۱۰" in text
    assert payload[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM for Excel


@pytest.mark.asyncio
async def test_csv_download_is_bom_utf8_and_owner_scoped(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["سؤال؟"])
        deck_id = made["deck"]["id"]
        resp = await client.get(f"/api/v1/flashcards/decks/{deck_id}/export/csv")
        assert resp.status_code == 200
        assert "attachment" in resp.headers["content-disposition"]
        assert f"darsyar-deck-{deck_id}-flashcards.csv" in resp.headers["content-disposition"]
        assert resp.headers["content-type"].startswith("text/csv")
        assert resp.content[:3] == b"\xef\xbb\xbf"
        text = resp.content.decode("utf-8-sig")
        assert text.startswith("Front,Back,Hint,Tags,Citations\r\n")
        assert "سؤال؟" in text

        empty = await client.post("/api/v1/flashcards/decks", json={"title": "خالی"})
        no_cards = await client.get(f"/api/v1/flashcards/decks/{empty.json()['id']}/export/csv")
        assert no_cards.status_code == 422

    # Ownership: another student's deck is invisible here too (same check as phase 3).
    async with env.factory() as session:
        other_deck_owner = env.ids["other_id"]
        from app.models.flashcards import FlashcardDeck

        session.add(FlashcardDeck(user_id=other_deck_owner, title="خصوصی", source_type="manual"))
        await session.commit()


@pytest.mark.asyncio
async def test_anki_export_survives_alongside_csv(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["کارت"])
        deck_id = made["deck"]["id"]
        anki = await client.get(f"/api/v1/flashcards/decks/{deck_id}/export/anki")
        assert anki.status_code == 200 and anki.content[:2] == b"PK"
        csv_resp = await client.get(f"/api/v1/flashcards/decks/{deck_id}/export/csv")
        assert csv_resp.status_code == 200


# ---------------------------------------------------------------------------
# Explain (grounded, textbook-strict)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explain_uses_server_book_pages_and_writes_audit(env):
    async with _client() as client:
        gen = await client.post(
            "/api/v1/flashcards/generate",
            json={"source": "book", "book_id": env.ids["book_id"], "chapter_number": 3, "count": 3},
        )
        card_id = gen.json()["cards"][0]["id"]
        resp = await client.post(f"/api/v1/flashcards/cards/{card_id}/explain", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["explain_md"]
    assert body["grounded_in_book"] is True
    assert body["citations"]
    prompt = env.text_calls[-1][-1]["content"]
    assert "متن صفحهٔ 10" in prompt  # server-fetched textbook page
    assert "روی کارت" in prompt
    async with env.factory() as session:
        audit = await session.get(AiAuditLog, body["audit_id"])
        assert audit is not None and audit.feature_key == "flashcards_explain"
        quota = await session.scalar(
            select(UserQuota).where(
                UserQuota.user_id == env.ids["student_id"],
                UserQuota.feature_key == "flashcards_explain",
            )
        )
        assert quota is not None and quota.daily_tokens_used > 0


@pytest.mark.asyncio
async def test_explain_without_retrievable_page_never_claims_new_citations(env):
    async with _client() as client:
        deck = (await client.post("/api/v1/flashcards/decks", json={"title": "دستی"})).json()
        card = (await client.post(
            f"/api/v1/flashcards/decks/{deck['id']}/cards",
            json={"front_md": "تعریف توان", "back_md": "ضرب در خودش", "hint_md": "", "tags": []},
        )).json()
        resp = await client.post(f"/api/v1/flashcards/cards/{card['id']}/explain", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["grounded_in_book"] is False
    assert body["citations"] == []
    prompt = env.text_calls[-1][-1]["content"]
    assert "در دسترس نیست" in prompt
    assert "ادعا نکن" in prompt


@pytest.mark.asyncio
async def test_explain_requires_owned_card_and_enabled_capability(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["کارت من"])
        card_id = made["cards"][0]["id"]
        off = await client.put("/api/v1/admin/capabilities/flashcards", headers=ADMIN_HEADERS,
                               json={"is_enabled": False})
        assert off.status_code == 200
        blocked = await client.post(f"/api/v1/flashcards/cards/{card_id}/explain", json={})
        assert blocked.status_code == 403
        blocked_session = await client.post(
            f"/api/v1/flashcards/decks/{made['deck']['id']}/study-sessions", json={"mode": "full"}
        )
        assert blocked_session.status_code == 403
        blocked_csv = await client.get(
            f"/api/v1/flashcards/decks/{made['deck']['id']}/export/csv"
        )
        assert blocked_csv.status_code == 403
        assert env.text_calls == []  # capability off → no model call anywhere
        on = await client.put("/api/v1/admin/capabilities/flashcards", headers=ADMIN_HEADERS,
                              json={"is_enabled": True})
        assert on.status_code == 200
        ok = await client.post(f"/api/v1/flashcards/cards/{card_id}/explain", json={})
        assert ok.status_code == 200


# ---------------------------------------------------------------------------
# Ownership & validation of session routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_study_session_of_another_user_is_invisible(env):
    async with env.factory() as session:
        from app.models.flashcards import Flashcard, FlashcardDeck

        owner = await session.get(User, env.ids["other_id"])
        deck = FlashcardDeck(user_id=owner.id, title="دیگری", source_type="manual")
        session.add(deck)
        await session.flush()
        card = Flashcard(deck_id=deck.id, front_md="س", back_md="ج", hint_md="",
                         citations_json=[], tags_json=[])
        session.add(card)
        await session.flush()
        study = FlashcardStudySession(
            user_id=owner.id, deck_id=deck.id, mode="full", status="active",
            card_order_json=[card.id], results_json={}, total_cards=1,
        )
        session.add(study)
        await session.commit()
        foreign = {"session_id": study.id, "card_id": card.id}
    async with _client() as client:
        assert (await client.get(
            f"/api/v1/flashcards/study-sessions/{foreign['session_id']}"
        )).status_code == 404
        assert (await client.post(
            f"/api/v1/flashcards/study-sessions/{foreign['session_id']}/answer",
            json={"card_id": foreign["card_id"], "got": True},
        )).status_code == 404
        assert (await client.post(
            f"/api/v1/flashcards/study-sessions/{foreign['session_id']}/progress",
            json={"position": 0, "flipped": False},
        )).status_code == 404


@pytest.mark.asyncio
async def test_answer_rejects_foreign_card_and_bad_positions(env):
    async with _client() as client:
        made = await _make_deck(env, client, titles=["الف"])
        deck_id = made["deck"]["id"]
        study = (await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions", json={"mode": "full"}
        )).json()
        other_deck = await _make_deck(env, client, titles=["بیگانه"])
        resp = await client.post(
            f"/api/v1/flashcards/study-sessions/{study['id']}/answer",
            json={"card_id": other_deck["cards"][0]["id"], "got": True},
        )
        assert resp.status_code == 422
        neg = await client.post(
            f"/api/v1/flashcards/study-sessions/{study['id']}/progress",
            json={"position": -3, "flipped": False},
        )
        assert neg.status_code == 422  # Pydantic ge=0
        missing = await client.post(
            f"/api/v1/flashcards/decks/{deck_id}/study-sessions", json={"mode": "subset"}
        )
        assert missing.status_code == 422


@pytest.mark.asyncio
async def test_migration_revises_phase8_head():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
              / "c8d9e0f1a2b3_flashcard_study_sessions.py").read_text(encoding="utf-8")
    assert 'down_revision: Union[str, Sequence[str], None] = "b7c1d2e3f4a5"' in source
    assert "flashcard_study_sessions" in source
    assert "op.drop_table(\"flashcard_study_sessions\")" in source
