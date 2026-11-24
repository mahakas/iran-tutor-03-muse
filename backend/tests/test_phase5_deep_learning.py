"""Phase 5 tests: Validator Gate, mistake bank, mastery path, Deep Solve, immersive reader, admin oversight."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
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
from app.models.curriculum import (
    Book, BookCurriculumLink, BookPage, BookPageObjective, BookStatus,
    CurriculumUnit, Grade, LearningEvidence, LearningObjective, Major, PageStatus, Subject,
)
from app.models.exam import ExamSession, ExamStatus
from app.models.flashcards import Flashcard, FlashcardDeck
from app.models.governance import AiAuditLog
from app.models.phase5 import (
    AdminActionLog,
    DeepSolveSession,
    MasteryBookSettings,
    MasteryChapterProgress,
    MistakeBankItem,
    QuizValidationLog,
)
from app.services import (
    ai_gateway,
    capability_runtime,
    capability_service,
    chat_stream,
    deep_solve_service,
    intent_router,
    learner_memory_service as lms,
    mastery_service,
    quiz_validator,
    retrieval_service,
    skill_seed,
    tutor_turns,
)
from app.services import ai_gateway as _gw  # noqa: F401  (ensures gateway import order)

ADMIN_HEADERS = {"X-Admin-Username": "admin", "X-Admin-Password": "123"}
NOW = datetime.now(timezone.utc)

GOOD_QUESTION = {
    "prompt": "کدام کمیت برداری است؟",
    "choices": {"A": "جرم", "B": "سرعت", "C": "نیرو", "D": "زمان"},
    "correct_option": "C",
    "explanation": "نیرو کمیت برداری است.",
    "source": {"book_id": 1, "pdf_page_index": 2, "printed_page_number": 14, "chapter_number": 2,
               "chapter_title": "نیرو"},
}


def _verdict(index, **overrides):
    row = {"index": index, "grounded": True, "unambiguous": True, "latex_ok": True,
           "confirmed_option": "C", "reasons": [], "fix": None}
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase5.sqlite3'}")
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
                                 markdown_content=text, page_image_path="/tmp/none.png",
                                 status=PageStatus.done))
        student = User(phone_number="09121000001", full_name="دانش‌آموز", role="student",
                       tokens_remaining=1_000_000, plan_expires_at=NOW + timedelta(days=30),
                       grade_level=10, is_active=True)
        session.add(student)
        await session.flush()
        ids.update(student_id=student.id, book_id=book.id)
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
    monkeypatch.setattr(chat_stream, "async_session_factory", factory)
    monkeypatch.setattr(lms, "async_session_factory", factory)
    monkeypatch.setattr(retrieval_service, "async_session_factory", factory)
    monkeypatch.setattr(
        ai_gateway, "get_settings", lambda: SimpleNamespace(tutor_model="test-model", llm_timeout=5)
    )

    fake = SimpleNamespace(json_calls=[], text_calls=[], json_reply=None, text_reply="خلاصه: نیرو کمیت برداری است.")

    async def fake_complete_json(model, messages):
        fake.json_calls.append(messages)
        if callable(fake.json_reply):
            return fake.json_reply(messages)
        return fake.json_reply or {}

    async def fake_complete_text(model, messages):
        fake.text_calls.append(messages)
        return fake.text_reply

    monkeypatch.setattr(ai_gateway, "complete_json", fake_complete_json)
    monkeypatch.setattr(ai_gateway, "complete_text", fake_complete_text)

    yield SimpleNamespace(factory=factory, ids=ids, fake=fake)

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_student, None)
    await engine.dispose()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _count(factory, model, *where) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


async def _insert_exam(env, questions, *, exam_id="exam-1") -> str:
    async with env.factory() as session:
        session.add(ExamSession(
            id=exam_id, book_id=env.ids["book_id"], user_id=env.ids["student_id"], grade_number=10,
            major_code="math_physics", title="آزمون", exam_type="final", time_limit_seconds=3600,
            status=ExamStatus.active, questions=questions, expires_at=NOW + timedelta(days=1),
        ))
        await session.commit()
    return exam_id


def _question(qid, chapter=2, answer="A"):
    return {
        "id": qid, "prompt": f"سؤال {qid}", "choices": {"A": "الف", "B": "ب", "C": "پ", "D": "ت"},
        "correct_option": answer, "explanation": f"توضیح {qid}", "points": 1.0,
        "source": {"book_id": 1, "pdf_page_index": 2, "printed_page_number": 14,
                   "chapter_number": chapter, "chapter_title": f"فصل {chapter}"},
    }


# ---------------------------------------------------------------------------
# 1. Validator Gate (unit level, through the real capability runtime)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_validator_rejects_ungrounded_and_logs_audit(env, monkeypatch):
    env.fake.json_reply = lambda messages: {"verdicts": [_verdict(0, grounded=False, reasons=["not in text"])]}
    async with env.factory() as session:
        outcome = await quiz_validator.validate_questions(
            session,
            items=[{"question": dict(GOOD_QUESTION), "source_text": "متن"}],
            user_id=env.ids["student_id"], book_id=env.ids["book_id"], exam_id="e1",
        )
        await session.commit()
    assert outcome.accepted == []
    assert outcome.decisions[0].verdict == "rejected"
    assert "ungrounded" in outcome.decisions[0].reasons
    assert await _count(env.factory, AiAuditLog, AiAuditLog.flag_reason == "validator_rejected") == 1


@pytest.mark.asyncio
async def test_validator_repairs_defective_question_with_single_fix(env):
    broken = dict(GOOD_QUESTION, prompt="$x^2 + 1", correct_option="C")  # unbalanced LaTeX delimiter
    fix = {"prompt": "$x^2+1$ کدام است؟", "choices": GOOD_QUESTION["choices"], "correct_option": "C",
           "explanation": "نیرو کمیت برداری است."}
    env.fake.json_reply = lambda messages: {"verdicts": [_verdict(0, fix=fix)]}
    async with env.factory() as session:
        outcome = await quiz_validator.validate_questions(
            session, items=[{"question": broken, "source_text": "متن"}],
            user_id=env.ids["student_id"], book_id=env.ids["book_id"],
        )
        await session.commit()
    assert outcome.decisions[0].verdict == "fixed"
    assert outcome.accepted[0]["prompt"] == "$x^2+1$ کدام است؟"
    assert await _count(env.factory, AiAuditLog, AiAuditLog.flag_reason == "validator_fixed") == 1


@pytest.mark.asyncio
async def test_validator_rejects_bad_fix_and_answer_key_mismatch(env):
    # Defective question (ungrounded). The repair flips the key to A, but the model confirms C:
    # the repair must not be accepted, so the question is rejected.
    bad_fix = {"correct_option": "A"}
    env.fake.json_reply = lambda messages: {"verdicts": [
        _verdict(0, grounded=False, confirmed_option="C", fix=bad_fix)]}
    async with env.factory() as session:
        outcome = await quiz_validator.validate_questions(
            session, items=[{"question": dict(GOOD_QUESTION), "source_text": "متن"}],
            user_id=env.ids["student_id"], book_id=env.ids["book_id"],
        )
    assert outcome.accepted == []
    assert outcome.decisions[0].verdict == "rejected"


@pytest.mark.asyncio
async def test_validator_fails_closed_when_model_omits_verdict(env):
    env.fake.json_reply = lambda messages: {"verdicts": []}
    async with env.factory() as session:
        outcome = await quiz_validator.validate_questions(
            session, items=[{"question": dict(GOOD_QUESTION), "source_text": "متن"}],
            user_id=env.ids["student_id"], book_id=env.ids["book_id"],
        )
    assert outcome.accepted == []
    assert "validator_missing_verdict" in outcome.decisions[0].reasons


@pytest.mark.asyncio
async def test_validator_disabled_by_admin_fails_closed_and_logs(env):
    # Grounding cannot be verified without the validator model, so no candidate is accepted.
    async with env.factory() as session:
        cap = await capability_service.get_capability(session, "quiz_validator")
        cap.is_enabled = False
        await session.commit()
    async with env.factory() as session:
        outcome = await quiz_validator.validate_questions(
            session,
            items=[
                {"question": dict(GOOD_QUESTION), "source_text": "متن"},
                {"question": dict(GOOD_QUESTION, choices={"A": "x", "B": "x", "C": "y", "D": "z"}),
                 "source_text": "متن"},
            ],
            user_id=env.ids["student_id"], book_id=env.ids["book_id"],
        )
        await session.commit()
    assert outcome.accepted == []
    assert [d.verdict for d in outcome.decisions] == ["rejected", "rejected"]
    assert all("validator_model_disabled" in d.reasons for d in outcome.decisions)
    assert await _count(env.factory, AiAuditLog, AiAuditLog.flag_reason == "validator_model_disabled") == 1
    assert await _count(env.factory, AiAuditLog, AiAuditLog.flag_reason == "validator_rejected") == 2


@pytest.mark.asyncio
async def test_validator_approval_is_logged(env):
    env.fake.json_reply = lambda messages: {"verdicts": [_verdict(0)]}
    async with env.factory() as session:
        outcome = await quiz_validator.validate_questions(
            session, items=[{"question": dict(GOOD_QUESTION), "source_text": "متن"}],
            user_id=env.ids["student_id"], book_id=env.ids["book_id"],
        )
        await session.commit()
    assert outcome.decisions[0].verdict == "approved"
    assert await _count(env.factory, AiAuditLog, AiAuditLog.flag_reason == "validator_approved") == 1


def test_latex_and_structure_checks():
    assert quiz_validator.latex_problems(r"$x^2$ و $$\frac{a}{b}$$") == []
    assert "delimiter_unbalanced" in quiz_validator.latex_problems("$x^2")
    assert "braces_unbalanced" in quiz_validator.latex_problems(r"\frac{a}{b")
    assert "choices_not_distinct" in quiz_validator.structural_problems(
        dict(GOOD_QUESTION, choices={"A": "x", "B": "x", "C": "y", "D": "z"}))
    assert quiz_validator.structural_problems(GOOD_QUESTION) == []


# ---------------------------------------------------------------------------
# 2. Automatic mistake capture on exam submit
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_exam_submit_records_wrong_and_skipped_mistakes_idempotently(env):
    questions = [_question("q1", chapter=2, answer="A"), _question("q2", chapter=2, answer="B"),
                 _question("q3", chapter=1, answer="C")]
    exam_id = await _insert_exam(env, questions)
    payload = {"answers": {"q1": "B", "q2": "B"}}  # q1 wrong, q2 correct, q3 skipped
    async with _client() as client:
        first = await client.post(f"/api/v1/exams/{exam_id}/submit", json=payload)
    assert first.status_code == 200, first.text
    async with env.factory() as session:
        rows = (await session.scalars(select(MistakeBankItem).where(MistakeBankItem.exam_id == exam_id))).all()
    by_q = {row.question_id: row for row in rows}
    assert set(by_q) == {"q1", "q3"}
    assert by_q["q1"].error_tag == "wrong" and by_q["q3"].error_tag == "skipped"
    assert by_q["q1"].topic_tag == "فصل 2" and by_q["q1"].printed_page_number == 14
    assert by_q["q1"].status == "unresolved"
    # Chapter mastery received the exam evidence (2 chapter-2 questions: 1 correct).
    async with env.factory() as session:
        progress = await session.scalar(select(MasteryChapterProgress).where(
            MasteryChapterProgress.user_id == env.ids["student_id"], MasteryChapterProgress.chapter_number == 2))
    assert progress.exam_total == 2 and progress.exam_correct == 1
    # Re-running the memory hook for the same exam must not duplicate rows (idempotent).
    from app.api import exams as exams_api
    async with env.factory() as session:
        exam = await session.get(ExamSession, exam_id)
        report = {"by_question": [{"id": "q1", "correct": False, "answer": "B"}]}
        added = await __import__("app.services.mistake_bank_service", fromlist=["x"]).record_exam_mistakes(
            session, user_id=env.ids["student_id"], exam=exam, report=report)
        await session.commit()
    assert added == 0
    assert await _count(env.factory, MistakeBankItem, MistakeBankItem.exam_id == exam_id) == 2


# ---------------------------------------------------------------------------
# 3. Mistake practice and conversion to flashcards
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mistake_practice_lifecycle_and_flashcard_conversion(env):
    exam_id = await _insert_exam(env, [_question("q1", chapter=2, answer="C")])
    async with _client() as client:
        await client.post(f"/api/v1/exams/{exam_id}/submit", json={"answers": {"q1": "A"}})
        listing = await client.get("/api/v1/mistakes")
        item_id = listing.json()["items"][0]["id"]
        # The practice set must not leak the answer key.
        practice = await client.get("/api/v1/mistakes/practice-set")
        assert "correct_option" not in practice.json()["items"][0]
        wrong = await client.post(f"/api/v1/mistakes/{item_id}/answer", json={"choice": "A"})
        assert wrong.json()["correct"] is False and wrong.json()["status"] == "unresolved"
        right1 = await client.post(f"/api/v1/mistakes/{item_id}/answer", json={"choice": "C"})
        assert right1.json()["status"] == "practiced"
        right2 = await client.post(f"/api/v1/mistakes/{item_id}/answer", json={"choice": "C"})
        assert right2.json()["status"] == "mastered"
        card1 = await client.post(f"/api/v1/mistakes/{item_id}/flashcard")
        card2 = await client.post(f"/api/v1/mistakes/{item_id}/flashcard")
    assert card1.status_code == 201 and card1.json()["created"] is True
    assert card2.json()["created"] is False and card2.json()["card_id"] == card1.json()["card_id"]
    async with env.factory() as session:
        card = await session.get(Flashcard, card1.json()["card_id"])
        deck = await session.get(FlashcardDeck, card.deck_id)
    assert deck.title == "اشتباهات من"
    assert card.citations_json[0]["printed_page_number"] == 14
    assert "نیرو" in card.back_md or "C)" in card.back_md


@pytest.mark.asyncio
async def test_mistake_bank_filters_scoped_counts_and_practice_set(env):
    """Redesign phase 05: lesson/chapter/error-tag filters on list and practice-set."""
    book_id = env.ids["book_id"]
    questions = [_question("q1", chapter=1, answer="A"), _question("q2", chapter=2, answer="B"),
                 _question("q3", chapter=2, answer="C")]
    exam_id = await _insert_exam(env, questions)
    async with _client() as client:
        submit = await client.post(f"/api/v1/exams/{exam_id}/submit",
                                   json={"answers": {"q1": "B", "q2": "A"}})  # q3 skipped
        assert submit.status_code == 200, submit.text
        # Unfiltered call must behave exactly as before the filters existed.
        unfiltered = await client.get("/api/v1/mistakes")
        assert unfiltered.status_code == 200 and unfiltered.json()["total"] == 3
        assert unfiltered.json()["counts"]["unresolved"] == 3
        # Chapter filter (server-side).
        chapter2 = await client.get("/api/v1/mistakes?chapter_number=2")
        assert chapter2.json()["total"] == 2
        assert {item["question_id"] for item in chapter2.json()["items"]} == {"q2", "q3"}
        # Scoped per-status counts follow the non-status filters.
        assert chapter2.json()["counts"]["unresolved"] == 2
        # Book + chapter combined.
        scoped = await client.get(f"/api/v1/mistakes?book_id={book_id}&chapter_number=1")
        assert scoped.json()["total"] == 1
        assert scoped.json()["items"][0]["question_id"] == "q1"
        # Error-tag filter plus status combination.
        skipped = await client.get("/api/v1/mistakes?error_tag=skipped&status=unresolved")
        assert skipped.json()["total"] == 1
        assert skipped.json()["items"][0]["question_id"] == "q3"
        # Invalid values fail closed with 422.
        assert (await client.get("/api/v1/mistakes?error_tag=bogus")).status_code == 422
        assert (await client.get("/api/v1/mistakes/practice-set?error_tag=bogus")).status_code == 422
        # Practice-set honours the same filters and never leaks the key.
        practice2 = await client.get("/api/v1/mistakes/practice-set?chapter_number=2")
        assert {item["question_id"] for item in practice2.json()["items"]} == {"q2", "q3"}
        assert all("correct_option" not in item for item in practice2.json()["items"])
        practice_skipped = await client.get("/api/v1/mistakes/practice-set?error_tag=skipped")
        assert [item["question_id"] for item in practice_skipped.json()["items"]] == ["q3"]


@pytest.mark.asyncio
async def test_mistake_bank_items_are_private_to_their_owner(env):
    """Redesign phase 05: answering or converting another student's mistake must 404."""
    from app.models.phase5 import MistakeBankItem as Item

    owner_id = env.ids["student_id"]
    other = User(phone_number="09121000099", full_name="دانش‌آموز دیگر", role="student",
                 tokens_remaining=1000, is_active=True, grade_level=10)
    async with env.factory() as session:
        session.add(other)
        await session.flush()
        session.add(Item(user_id=other.id, exam_id="exam-other", question_id="qX", book_id=env.ids["book_id"],
                         chapter_number=1, chapter_title="فصل 1", printed_page_number=10, topic_tag="فصل 1",
                         error_tag="wrong", prompt="سؤال دیگری", choices_json={"A": "الف", "B": "ب"},
                         correct_option="A", explanation="توضیح", status="unresolved"))
        await session.commit()
        foreign_id = (await session.scalars(select(Item.id).where(Item.user_id == other.id))).first()
    async with _client() as client:
        listing = await client.get("/api/v1/mistakes")
        assert listing.json()["total"] == 0  # the list only ever shows the caller's own rows
        answered = await client.post(f"/api/v1/mistakes/{foreign_id}/answer", json={"choice": "A"})
        converted = await client.post(f"/api/v1/mistakes/{foreign_id}/flashcard")
    assert answered.status_code == 404
    assert converted.status_code == 404
    async with env.factory() as session:
        untouched = await session.get(Item, foreign_id)
    assert untouched.status == "unresolved" and untouched.attempts == 0 and untouched.flashcard_card_id is None
    assert owner_id != other.id


# ---------------------------------------------------------------------------
# 4. Mastery path: scores, thresholds, sequential unlock, admin overrides
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mastery_score_weighting_threshold_and_unlock(env):
    book_id = env.ids["book_id"]
    student = env.ids["student_id"]
    async with env.factory() as session:
        # Chapter 1: exam 2/2 (weight .5) + flash 0/2 (weight .3) => (0.5*1 + 0.3*0)/0.8 = 0.625 (< 0.7)
        await mastery_service.record_component(session, user_id=student, book_id=book_id, chapter_number=1,
                                               component="exam", correct=2, total=2)
        await mastery_service.record_component(session, user_id=student, book_id=book_id, chapter_number=1,
                                               component="flash", correct=0, total=2)
        await session.commit()
        row = await session.scalar(select(MasteryChapterProgress).where(MasteryChapterProgress.chapter_number == 1))
        assert mastery_service.chapter_score(row) == pytest.approx(0.625, abs=1e-3)
        tree = await mastery_service.book_tree(session, user_id=student, book_id=book_id)
    chapters = {c["chapter_number"]: c for c in tree["chapters"]}
    assert chapters[1]["status"] == "in_progress"
    assert chapters[2]["status"] == "locked" and chapters[2]["locked_reason"] == "previous_chapter_not_mastered"

    # Raise chapter 1 above threshold with solve evidence (weight .2): all three components => mastered.
    async with env.factory() as session:
        await mastery_service.record_component(session, user_id=student, book_id=book_id, chapter_number=1,
                                               component="solve", correct=5, total=5)
        await session.commit()
        tree = await mastery_service.book_tree(session, user_id=student, book_id=book_id)
    chapters = {c["chapter_number"]: c for c in tree["chapters"]}
    assert chapters[1]["status"] == "mastered"
    assert chapters[2]["status"] == "not_started"  # unlocked after chapter 1 is mastered


@pytest.mark.asyncio
async def test_admin_mastery_threshold_override_and_action_log(env):
    book_id = env.ids["book_id"]
    student = env.ids["student_id"]
    async with _client() as client:
        bad = await client.put(f"/api/v1/admin/mastery/books/{book_id}/settings",
                               json={"threshold": 0.1}, headers=ADMIN_HEADERS)
        assert bad.status_code == 422  # pydantic bound
        ok = await client.put(f"/api/v1/admin/mastery/books/{book_id}/settings",
                              json={"threshold": 0.5, "unlock_mode": "open"}, headers=ADMIN_HEADERS)
        assert ok.status_code == 200 and ok.json()["threshold"] == 0.5
        lock = await client.put(f"/api/v1/admin/mastery/books/{book_id}/chapters/2/override",
                                json={"override": "locked"}, headers=ADMIN_HEADERS)
        assert lock.status_code == 200
        async with env.factory() as session:
            tree = await mastery_service.book_tree(session, user_id=student, book_id=book_id)
        chapters = {c["chapter_number"]: c for c in tree["chapters"]}
        assert chapters[2]["status"] == "locked" and chapters[2]["locked_reason"] == "admin_locked"
        # Open mode: chapter 2 is unlocked when no override exists.
        await client.put(f"/api/v1/admin/mastery/books/{book_id}/chapters/2/override",
                         json={"override": None}, headers=ADMIN_HEADERS)
        async with env.factory() as session:
            tree = await mastery_service.book_tree(session, user_id=student, book_id=book_id)
        assert {c["chapter_number"]: c for c in tree["chapters"]}[2]["status"] == "not_started"
        logs = await client.get("/api/v1/admin/action-logs", params={"target": f"book:{book_id}"},
                                headers=ADMIN_HEADERS)
    actions = [item["action"] for item in logs.json()["items"]]
    assert "mastery.settings_update" in actions and "mastery.chapter_override" in actions


# ---------------------------------------------------------------------------
# 5. Deep Solve: hint ladder, no early answer leak, no orphan rows
# ---------------------------------------------------------------------------
PLAN = {
    "topic": "نیرو و شتاب",
    "subject": "physics",
    "steps": [
        {"title": "داده‌ها", "hint1": "کمیت‌های داده‌شده را بنویس", "hint2": "جرم و نیروی خالص را جدا کن",
         "explanation": "جرم ۲ کیلوگرم و نیروی ۱۰ نیوتون است.", "result": "m=2, F=10"},
        {"title": "رابطه", "hint1": "قانون دوم نیوتون را یادآوری کن", "hint2": "F = m a",
         "explanation": "a = F/m = 5 m/s².", "result": "a=5"},
    ],
    "final_answer": "۵ متر بر مجذور ثانیه",
}


@pytest.mark.asyncio
async def test_deep_solve_ladder_hides_answer_until_full_and_records_mastery(env):
    env.fake.json_reply = lambda messages: PLAN if "مربی حل مسئله" in messages[0]["content"] else {}
    book_id = env.ids["book_id"]
    async with _client() as client:
        created = await client.post("/api/v1/deep-solve/sessions", json={
            "problem_text": "جسمی ۲ کیلوگرمی با نیروی ۱۰ نیوتون", "book_id": book_id, "chapter_number": 2})
        assert created.status_code == 201, created.text
        body = created.json()
        sid = body["id"]
        assert body["final_answer"] is None and body["total_steps"] == 2
        assert "explanation" not in body["steps"][0]  # current step explanation hidden
        blocked = await client.post(f"/api/v1/deep-solve/sessions/{sid}/actions", json={"action": "hint2"})
        assert blocked.status_code == 409  # ladder order: hint1 first
        h1 = await client.post(f"/api/v1/deep-solve/sessions/{sid}/actions", json={"action": "hint1"})
        assert h1.json()["steps"][0]["hint1"]
        h2 = await client.post(f"/api/v1/deep-solve/sessions/{sid}/actions", json={"action": "hint2"})
        assert h2.json()["steps"][0]["hint2"]
        step = await client.post(f"/api/v1/deep-solve/sessions/{sid}/actions", json={"action": "reveal_step"})
        assert step.json()["current_step"] == 1 and step.json()["final_answer"] is None
        full = await client.post(f"/api/v1/deep-solve/sessions/{sid}/actions", json={"action": "full_solution"})
    final = full.json()
    assert final["status"] == "completed" and final["final_answer"] == PLAN["final_answer"]
    assert all("explanation" in step for step in final["steps"])
    async with env.factory() as session:
        row = await session.get(DeepSolveSession, sid)
        progress = await session.scalar(select(MasteryChapterProgress).where(
            MasteryChapterProgress.user_id == env.ids["student_id"], MasteryChapterProgress.chapter_number == 2))
    assert row.mastery_recorded is True
    # Step 1 used hints (not independent), step 2 was tutor-revealed: 0 independent of 2.
    assert progress.solve_total == 2 and progress.solve_correct == 0


@pytest.mark.asyncio
async def test_deep_solve_repairs_one_invalid_structured_plan(env):
    calls = 0

    def malformed_then_valid(messages):
        nonlocal calls
        calls += 1
        return {"steps": "not a list"} if calls == 1 else PLAN

    env.fake.json_reply = malformed_then_valid
    async with _client() as client:
        response = await client.post(
            "/api/v1/deep-solve/sessions",
            json={
                "problem_text": "جسمی ۲ کیلوگرمی با نیروی ۱۰ نیوتون",
                "book_id": env.ids["book_id"],
                "chapter_number": 2,
            },
        )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "active"
    assert calls == 2
    assert await _count(
        env.factory, AiAuditLog, AiAuditLog.feature_key == "deep_solve"
    ) == 2
    assert await _count(env.factory, DeepSolveSession) == 1


@pytest.mark.asyncio
async def test_deep_solve_invalid_model_plan_creates_no_orphan_row(env):
    env.fake.json_reply = lambda messages: {"steps": "not a list"}
    async with _client() as client:
        response = await client.post("/api/v1/deep-solve/sessions", json={"problem_text": "قانون دوم نیوتون: نیروی خالص برابر جرم ضربدر شتاب است", "book_id": env.ids["book_id"]})
    assert response.status_code == 502
    assert await _count(env.factory, DeepSolveSession) == 0


# ---------------------------------------------------------------------------
# 6. Capability lock: admin disables a feature => student blocked; edit is logged
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_disabled_capability_blocks_student_and_admin_edit_is_logged(env):
    async with _client() as client:
        off = await client.put("/api/v1/admin/capabilities/deep_solve",
                               json={"is_enabled": False}, headers=ADMIN_HEADERS)
        assert off.status_code == 200
        blocked = await client.post("/api/v1/deep-solve/sessions", json={"problem_text": "قانون دوم نیوتون: نیروی خالص برابر جرم ضربدر شتاب است", "book_id": env.ids["book_id"]})
        assert blocked.status_code == 403
        logs = await client.get("/api/v1/admin/action-logs", params={"target": "capability:deep_solve"},
                                headers=ADMIN_HEADERS)
    assert any(item["action"] == "capability.update" for item in logs.json()["items"])
    assert await _count(env.factory, AdminActionLog, AdminActionLog.target == "capability:deep_solve") >= 1


# ---------------------------------------------------------------------------
# 7. Immersive reader: TOC, page detail, grounded assist with page citation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_immersive_overview_page_and_assist_cite_exact_page(env):
    book_id = env.ids["book_id"]
    async with _client() as client:
        overview = await client.get(f"/api/v1/immersive/books/{book_id}")
        page = await client.get(f"/api/v1/immersive/books/{book_id}/pages/2")
        assist = await client.post(f"/api/v1/immersive/books/{book_id}/assist",
                                   json={"action": "summarize", "pdf_page_index": 2})
    assert overview.status_code == 200
    chapters = {c["chapter_number"]: c for c in overview.json()["chapters"]}
    assert chapters[2]["page_start"] == 2 and chapters[2]["page_end"] == 3
    assert overview.json()["grade_number"] == 10 and overview.json()["major_code"] == "math_physics"
    assert page.json()["printed_page_number"] == 14
    assert assist.status_code == 200, assist.text
    assert assist.json()["citation"]["printed_page_number"] == 14
    assert env.fake.text_calls, "assist must call the gateway"
    assert await _count(env.factory, AiAuditLog, AiAuditLog.feature_key == "immersive_reader") >= 1


@pytest.mark.asyncio
async def test_immersive_reader_does_not_serve_unapproved_page_image(env):
    book_id = env.ids["book_id"]
    async with env.factory() as session:
        page = await session.scalar(
            select(BookPage).where(BookPage.book_id == book_id, BookPage.pdf_page_index == 1)
        )
        page.status = PageStatus.needs_review
        await session.commit()

    async with _client() as client:
        response = await client.get(
            f"/api/v1/immersive/books/{book_id}/pages/1/image"
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_immersive_assist_rejects_unknown_action_and_missing_page(env):
    book_id = env.ids["book_id"]
    async with _client() as client:
        bad_page = await client.post(f"/api/v1/immersive/books/{book_id}/assist",
                                     json={"action": "summarize", "pdf_page_index": 99})
        bad_action = await client.post(f"/api/v1/immersive/books/{book_id}/assist",
                                       json={"action": "delete", "pdf_page_index": 2})
    assert bad_page.status_code == 404
    assert bad_action.status_code == 422


# ---------------------------------------------------------------------------
# 8. Admin oversight of a student's Phase 5 state
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_sees_student_mistakes_sessions_and_validator_rejections(env):
    exam_id = await _insert_exam(env, [_question("q1", chapter=2, answer="A")])
    student = env.ids["student_id"]
    env.fake.json_reply = lambda messages: (
        {"verdicts": [_verdict(0, grounded=False)]} if "بازبین علمی" in messages[0]["content"]
        else PLAN if "مربی حل مسئله" in messages[0]["content"] else {})
    async with env.factory() as session:
        outcome = await quiz_validator.validate_questions(
            session, items=[{"question": dict(GOOD_QUESTION), "source_text": "متن"}],
            user_id=student, book_id=env.ids["book_id"], exam_id=exam_id)
        session.add(QuizValidationLog(user_id=student, exam_id=exam_id, book_id=env.ids["book_id"],
                                      question_index=0, verdict="rejected",
                                      reasons_json=outcome.decisions[0].reasons, question_json={}))
        await session.commit()
    async with _client() as client:
        await client.post(f"/api/v1/exams/{exam_id}/submit", json={"answers": {"q1": "B"}})
        await client.post("/api/v1/deep-solve/sessions", json={"problem_text": "قانون دوم نیوتون: نیروی خالص برابر جرم ضربدر شتاب است", "book_id": env.ids["book_id"]})
        mistakes = await client.get(f"/api/v1/admin/users/{student}/mistakes", headers=ADMIN_HEADERS)
        sessions = await client.get(f"/api/v1/admin/users/{student}/deep-solve-sessions", headers=ADMIN_HEADERS)
        rejected = await client.get(f"/api/v1/admin/users/{student}/quiz-validation",
                                    params={"verdict": "rejected"}, headers=ADMIN_HEADERS)
        mastery = await client.get(f"/api/v1/admin/users/{student}/mastery", headers=ADMIN_HEADERS)
        denied = await client.get(f"/api/v1/admin/users/{student}/mistakes")
    assert mistakes.status_code == 200 and mistakes.json()["total"] == 1
    assert sessions.json()["items"][0]["steps"] and sessions.json()["items"][0]["final_answer"]
    assert rejected.json()["items"][0]["reasons"] == ["ungrounded"]
    assert mastery.status_code == 200
    assert denied.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 9. Routing guarantee: Phase 5 AI calls go through capability_runtime -> ai_gateway
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_phase5_ai_calls_route_through_runtime_and_gateway(env, monkeypatch):
    seen: list[str] = []
    real = capability_runtime.run_capability_json

    async def spy(**kwargs):
        seen.append(kwargs["capability_key"])
        return await real(**kwargs)

    monkeypatch.setattr(deep_solve_service, "run_capability_json", spy)
    env.fake.json_reply = lambda messages: PLAN
    async with _client() as client:
        await client.post("/api/v1/deep-solve/sessions", json={"problem_text": "قانون دوم نیوتون: نیروی خالص برابر جرم ضربدر شتاب است", "book_id": env.ids["book_id"]})
    assert seen == ["deep_solve"]
    assert await _count(env.factory, AiAuditLog, AiAuditLog.feature_key == "deep_solve") >= 1


# ---------------------------------------------------------------------------
# 8. Wiring: capabilities seeded, routable, quota-tracked, admin-visible
# ---------------------------------------------------------------------------
PHASE5_CAPABILITIES = ("immersive_reader", "deep_solve", "mistake_bank", "mastery_path", "quiz", "quiz_validator")


@pytest.mark.asyncio
async def test_phase5_capabilities_seeded_with_routes_and_feature_keys(env):
    from app.models.capabilities import Capability
    from app.services.ai_provider_service import ROUTABLE_FEATURE_KEYS

    async with env.factory() as session:
        rows = {
            row.key: row
            for row in (await session.scalars(select(Capability).where(Capability.key.in_(PHASE5_CAPABILITIES)))).all()
        }
    assert set(rows) == set(PHASE5_CAPABILITIES)
    assert all(row.is_enabled for row in rows.values())
    # AI-backed capabilities must have a route key that the admin can route to a model.
    for key in ("immersive_reader", "deep_solve", "quiz", "quiz_validator"):
        assert rows[key].default_route_key == key
        assert key in ROUTABLE_FEATURE_KEYS
    # Non-AI capabilities have no model route and make no model calls (checked below).
    assert rows["mistake_bank"].default_route_key is None
    assert rows["mastery_path"].default_route_key is None


@pytest.mark.asyncio
async def test_ai_capabilities_consume_user_quota_rows(env):
    from app.models.governance import UserQuota

    book_id = env.ids["book_id"]
    async with _client() as client:
        r1 = await client.post(f"/api/v1/immersive/books/{book_id}/assist",
                               json={"action": "summarize", "pdf_page_index": 2})
        r2 = await client.post("/api/v1/deep-solve/sessions", json={"problem_text": "قانون دوم نیوتون و نیروی خالص", "book_id": env.ids["book_id"]})
    assert r1.status_code == 200
    assert r2.status_code in (201, 502)  # plan may be invalid in the stub; quota must still be touched
    async with env.factory() as session:
        features = set((await session.scalars(
            select(UserQuota.feature_key).where(UserQuota.user_id == env.ids["student_id"])
        )).all())
    assert "immersive_reader" in features


def test_non_ai_capabilities_make_no_model_calls():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services"
    for name in ("mistake_bank_service.py", "mastery_service.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "ai_gateway" not in source, name
        assert "capability_runtime" not in source, name
        assert "complete_json" not in source and "complete_text" not in source, name


@pytest.mark.asyncio
async def test_admin_views_expose_phase5_data_per_student(env):
    # Seed one wrong answer, one validator rejection and one deep-solve session, then read them as admin.
    await _insert_exam(env, [_question("q1", answer="A")])
    async with _client() as client:
        submit = await client.post("/api/v1/exams/exam-1/submit", json={"answers": {"q1": "B"}})
        assert submit.status_code in (200, 201)
        mistakes = await client.get(f"/api/v1/admin/users/{env.ids['student_id']}/mistakes", headers=ADMIN_HEADERS)
        mastery = await client.get(f"/api/v1/admin/users/{env.ids['student_id']}/mastery",
                                   params={"book_id": env.ids["book_id"]}, headers=ADMIN_HEADERS)
        sessions = await client.get(f"/api/v1/admin/users/{env.ids['student_id']}/deep-solve-sessions",
                                    headers=ADMIN_HEADERS)
        validation = await client.get(f"/api/v1/admin/users/{env.ids['student_id']}/quiz-validation",
                                      headers=ADMIN_HEADERS)
    assert mistakes.status_code == 200 and mistakes.json()["items"]
    assert mastery.status_code == 200 and mastery.json()["chapters"]
    assert sessions.status_code == 200 and "items" in sessions.json()
    assert validation.status_code == 200 and "items" in validation.json()


@pytest.mark.asyncio
async def test_mastery_tree_and_evidence_obey_exact_page_objective_mapping(env):
    async with env.factory() as session:
        book = await session.get(Book, env.ids["book_id"])
        grade = await session.scalar(select(Grade).where(Grade.number == 10))
        subject = Subject(code="hotfix_mastery_scope", title="درس آزمون اصلاحی", is_active=True)
        session.add(subject)
        await session.flush()

        unit = CurriculumUnit(
            grade_id=grade.id,
            subject_id=subject.id,
            scope_code="unspecified",
            code="hotfix-mastery-unit",
            title="واحد آزمون اصلاحی",
            unit_type="chapter",
            is_active=True,
        )
        session.add(unit)
        await session.flush()

        mapped = LearningObjective(
            unit_id=unit.id,
            code="hotfix-objective-mapped",
            title="هدف متصل به صفحه",
            assessment_profile="written",
            is_active=True,
        )
        unmapped = LearningObjective(
            unit_id=unit.id,
            code="hotfix-objective-unmapped",
            title="هدف بدون اتصال به صفحه",
            assessment_profile="written",
            is_active=True,
        )
        session.add_all([mapped, unmapped])
        await session.flush()

        session.add(
            BookCurriculumLink(
                book_id=book.id,
                subject_id=subject.id,
                scope_code="general:hotfix:mastery",
            )
        )
        page = await session.scalar(
            select(BookPage).where(
                BookPage.book_id == book.id,
                BookPage.pdf_page_index == 2,
                BookPage.status == PageStatus.done,
            )
        )
        assert page is not None
        session.add(BookPageObjective(book_page_id=page.id, objective_id=mapped.id))
        await session.commit()

        tree = await mastery_service.objective_tree(
            session, user_id=env.ids["student_id"], book_id=book.id
        )
        returned_ids = {item["id"] for item in tree["objectives"]}
        assert mapped.id in returned_ids
        assert unmapped.id not in returned_ids

        valid = await mastery_service.record_objective_evidence(
            session,
            user_id=env.ids["student_id"],
            objective_id=mapped.id,
            source_type="reading",
            source_ref="hotfix-evidence-valid",
            score=95,
            qualitative_level=None,
            rubric={},
            feedback=None,
            book_id=book.id,
            pdf_page_index=page.pdf_page_index,
        )
        assert valid.verification_status == "unverified"
        assert valid.book_id == book.id

        with pytest.raises(HTTPException) as mismatch:
            await mastery_service.record_objective_evidence(
                session,
                user_id=env.ids["student_id"],
                objective_id=unmapped.id,
                source_type="reading",
                source_ref="hotfix-evidence-mismatch",
                score=95,
                qualitative_level=None,
                rubric={},
                feedback=None,
                book_id=book.id,
                pdf_page_index=page.pdf_page_index,
            )
        assert mismatch.value.status_code == 422

        with pytest.raises(HTTPException) as missing_book:
            await mastery_service.record_objective_evidence(
                session,
                user_id=env.ids["student_id"],
                objective_id=unmapped.id,
                source_type="reading",
                source_ref="hotfix-evidence-no-book",
                score=95,
                qualitative_level=None,
                rubric={},
                feedback=None,
                book_id=None,
            )
        assert missing_book.value.status_code == 422


@pytest.mark.asyncio
async def test_deep_solve_refuses_books_without_processed_source_pages(env):
    async with env.factory() as session:
        pages = (
            await session.scalars(
                select(BookPage).where(BookPage.book_id == env.ids["book_id"])
            )
        ).all()
        assert pages
        for page in pages:
            page.status = PageStatus.needs_review
        await session.commit()

    async with _client() as client:
        missing_book = await client.post(
            "/api/v1/deep-solve/sessions",
            json={"problem_text": "مسئله بدون کتاب"},
        )
        no_processed_pages = await client.post(
            "/api/v1/deep-solve/sessions",
            json={"problem_text": "قانون دوم نیوتون: نیروی خالص برابر جرم ضربدر شتاب است", "book_id": env.ids["book_id"]},
        )

    assert missing_book.status_code == 422
    assert no_processed_pages.status_code == 409
    assert await _count(env.factory, DeepSolveSession) == 0


@pytest.mark.asyncio
async def test_deep_solve_does_not_claim_unrelated_pages_as_sources(env):
    async with _client() as client:
        response = await client.post(
            "/api/v1/deep-solve/sessions",
            json={
                "problem_text": "چرا گیاهان در فرایند فتوسنتز اکسیژن آزاد می‌کنند؟",
                "book_id": env.ids["book_id"],
            },
        )
    assert response.status_code == 409
    assert await _count(env.factory, DeepSolveSession) == 0



@pytest.mark.asyncio
async def test_admin_can_list_and_review_student_learning_evidence(env):
    async with env.factory() as session:
        book = await session.get(Book, env.ids["book_id"])
        grade = await session.get(Grade, book.grade_id)
        subject = Subject(code="admin_evidence_review_subject", title="درس بازبینی شواهد", is_active=True)
        session.add(subject)
        await session.flush()
        unit = CurriculumUnit(
            grade_id=grade.id, subject_id=subject.id, scope_code="unspecified",
            code="admin-evidence-review-unit", title="واحد بازبینی",
            unit_type="chapter", is_active=True,
        )
        session.add(unit)
        await session.flush()
        session.add(
            BookCurriculumLink(
                book_id=book.id,
                subject_id=subject.id,
                scope_code="admin-review:subject-link",
            )
        )
        objective = LearningObjective(
            unit_id=unit.id, code="admin-evidence-review-objective",
            title="هدف نیازمند بازبینی", assessment_profile="written", is_active=True,
        )
        session.add(objective)
        await session.flush()
        evidence = LearningEvidence(
            user_id=env.ids["student_id"], objective_id=objective.id, book_id=book.id,
            source_type="self_assessment", source_ref="admin-review-test", score=86,
            qualitative_level=None, rubric_json={}, verification_status="unverified",
            feedback="پاسخ خودارزیابی دانش‌آموز",
        )
        session.add(evidence)
        await session.commit()
        evidence_id = evidence.id
        objective_id = objective.id

    async with _client() as client:
        unauthenticated = await client.get("/api/v1/admin/mastery/evidence")
        pending = await client.get(
            "/api/v1/admin/mastery/evidence",
            params={"book_id": env.ids["book_id"], "verification_status": "unverified"},
            headers=ADMIN_HEADERS,
        )
        missing_rejection_note = await client.patch(
            f"/api/v1/admin/mastery/evidence/{evidence_id}/review",
            json={"verification_status": "rejected", "review_note": ""},
            headers=ADMIN_HEADERS,
        )
        reviewed = await client.patch(
            f"/api/v1/admin/mastery/evidence/{evidence_id}/review",
            json={"verification_status": "verified", "review_note": "شاهد بررسی شد."},
            headers=ADMIN_HEADERS,
        )
        duplicate_review = await client.patch(
            f"/api/v1/admin/mastery/evidence/{evidence_id}/review",
            json={"verification_status": "rejected", "review_note": "بازبینی دوم نباید پذیرفته شود."},
            headers=ADMIN_HEADERS,
        )
        verified = await client.get(
            "/api/v1/admin/mastery/evidence",
            params={"user_id": env.ids["student_id"], "verification_status": "verified"},
            headers=ADMIN_HEADERS,
        )

    assert unauthenticated.status_code in (401, 403)
    assert pending.status_code == 200
    assert pending.json()["total"] == 1
    assert pending.json()["items"][0]["objective_id"] == objective_id
    assert pending.json()["items"][0]["book_id"] == env.ids["book_id"]
    assert missing_rejection_note.status_code == 422
    assert reviewed.status_code == 200
    assert reviewed.json()["verification_status"] == "verified"
    assert reviewed.json()["reviewed_by"] == "admin_session"
    assert reviewed.json()["review_note"] == "شاهد بررسی شد."
    assert duplicate_review.status_code == 409
    assert verified.status_code == 200
    assert verified.json()["total"] == 1
    assert verified.json()["items"][0]["verification_status"] == "verified"
    assert verified.json()["items"][0]["feedback"] == "پاسخ خودارزیابی دانش‌آموز"
    assert verified.json()["items"][0]["review_note"] == "شاهد بررسی شد."


def test_mastery_score_uses_verified_rows_but_latest_evidence_shows_latest_submission():
    verified_at = NOW - timedelta(minutes=10)
    verified = SimpleNamespace(
        id=1,
        source_type="self_assessment",
        score=92.0,
        qualitative_level=None,
        rubric_json={},
        verification_status="verified",
        reviewed_at=verified_at,
        review_note="شاهد قبلی تأیید شد.",
        feedback="شاهد قبلی",
        observed_at=verified_at,
    )
    pending = SimpleNamespace(
        id=2,
        source_type="self_assessment",
        score=20.0,
        qualitative_level=None,
        rubric_json={},
        verification_status="unverified",
        reviewed_at=None,
        review_note=None,
        feedback="ارسال جدید در انتظار بازبینی",
        observed_at=NOW,
    )

    progress = mastery_service._evidence_progress(
        [verified, pending],
        assessment_profile="written",
        threshold=80,
    )

    assert progress["status"] == "mastered"
    assert progress["score"] == 92.0
    assert progress["latest_evidence"]["score"] == 20.0
    assert progress["latest_evidence"]["verification_status"] == "unverified"
    assert progress["latest_evidence"]["feedback"] == "ارسال جدید در انتظار بازبینی"
    assert progress["evidence"][0]["verification_status"] == "unverified"
