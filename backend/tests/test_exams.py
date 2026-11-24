"""Exam generation validation, answer-key privacy, and scoring tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.exam import ExamStatus
from app.services.exam_service import grade_exam, public_exam, submit_exam, validate_questions


def _question(question_id: str, correct: str = "A") -> dict:
    return {
        "id": question_id,
        "prompt": "کدام گزینه درست است؟",
        "choices": {"A": "گزینه الف", "B": "گزینه ب", "C": "گزینه پ", "D": "گزینه ت"},
        "correct_option": correct,
        "explanation": "این توضیح از متن کتاب است.",
        "points": 1.0,
        "source": {"book_title": "فیزیک ۳", "printed_page_number": 14},
    }


def test_questions_require_exact_count_and_source_indexes():
    raw = {
        "questions": [
            {
                "prompt": "پرسش",
                "choices": {"A": "الف", "B": "ب", "C": "پ", "D": "ت"},
                "correct_option": "B",
                "explanation": "توضیح",
                "source_index": 0,
            }
        ]
    }
    assert len(validate_questions(raw, expected_count=1, source_count=1)) == 1
    with pytest.raises(ValueError, match="expected 2"):
        validate_questions(raw, expected_count=2, source_count=1)
    raw["questions"][0]["source_index"] = 2
    with pytest.raises(ValueError, match="source"):
        validate_questions(raw, expected_count=1, source_count=1)


def test_public_exam_never_leaks_answer_key_or_explanation():
    exam = SimpleNamespace(
        id="uuid",
        book_id=1,
        grade_number=12,
        major_code="math_physics",
        title="آزمون فصل ۱",
        exam_type="konkoor",
        time_limit_seconds=900,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        status=ExamStatus.active,
        questions=[_question("q1")],
    )

    result = public_exam(exam)

    assert "correct_option" not in result["questions"][0]
    assert "explanation" not in result["questions"][0]
    assert result["questions"][0]["choices"]["A"] == "گزینه الف"


def test_konkoor_scoring_applies_one_third_negative_marking():
    questions = [_question("q1"), _question("q2"), _question("q3"), _question("q4")]

    report = grade_exam(
        questions,
        {"q1": "A", "q2": "A", "q3": "B"},
        exam_type="konkoor",
    )

    assert report["correct"] == 2
    assert report["wrong"] == 1
    assert report["unanswered"] == 1
    assert report["scale"] == "percent"
    assert report["score"] == 41.67


def test_final_exam_score_is_scaled_to_twenty():
    questions = [_question("q1"), _question("q2"), _question("q3"), _question("q4")]
    report = grade_exam(questions, {"q1": "A", "q2": "B"}, exam_type="final")
    assert report["scale"] == "out_of_20"
    assert report["score"] == 5.0


def test_submit_exam_persists_answers_report_and_status():
    exam = SimpleNamespace(
        status=ExamStatus.active,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        questions=[_question("q1")],
        exam_type="final",
        submitted_at=None,
        submitted_answers=None,
        report_card=None,
    )

    report = submit_exam(exam, {"q1": "A"})

    assert exam.status == ExamStatus.submitted
    assert exam.submitted_answers == {"q1": "A"}
    assert exam.report_card == report
    assert report["score"] == 20.0


def test_submit_exam_rejects_unknown_question_ids():
    exam = SimpleNamespace(
        status=ExamStatus.active,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        questions=[_question("q1")],
        exam_type="final",
    )
    with pytest.raises(ValueError, match="unknown question"):
        submit_exam(exam, {"q99": "A"})


def test_expired_exam_is_marked_expired_and_rejected():
    exam = SimpleNamespace(
        status=ExamStatus.active,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        questions=[_question("q1")],
        exam_type="final",
    )
    with pytest.raises(TimeoutError):
        submit_exam(exam, {"q1": "A"})
    assert exam.status == ExamStatus.expired


def test_public_exam_always_includes_utc_offset_for_naive_datetimes():
    naive_expires = datetime(2026, 11, 14, 22, 30, 0)
    exam = SimpleNamespace(
        id="uuid",
        book_id=1,
        grade_number=12,
        major_code="math_physics",
        title="آزمون فصل ۱",
        exam_type="konkoor",
        time_limit_seconds=900,
        expires_at=naive_expires,
        status=ExamStatus.active,
        questions=[_question("q1")],
    )

    result = public_exam(exam)

    assert result["expires_at"].endswith("+00:00")
    assert datetime.fromisoformat(result["expires_at"]).tzinfo == timezone.utc


def test_public_exam_includes_report_only_when_submitted():
    active_exam = SimpleNamespace(
        id="e-active",
        book_id=1,
        grade_number=12,
        major_code="math_physics",
        title="آزمون فعال",
        exam_type="konkoor",
        time_limit_seconds=600,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        status=ExamStatus.active,
        questions=[_question("q1")],
        report_card={"score": 100.0},
        submitted_answers={"q1": "A"},
    )
    active_payload = public_exam(active_exam, include_report=True)
    assert "report_card" not in active_payload

    submitted_exam = SimpleNamespace(
        id="e-done",
        book_id=1,
        grade_number=12,
        major_code="math_physics",
        title="آزمون ثبت‌شده",
        exam_type="konkoor",
        time_limit_seconds=600,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        status=ExamStatus.submitted,
        questions=[_question("q1")],
        report_card={"score": 100.0, "scale": "percent"},
        submitted_answers={"q1": "A"},
    )
    done_payload = public_exam(submitted_exam, include_report=True)
    assert done_payload["report_card"]["score"] == 100.0
    assert done_payload["submitted_answers"] == {"q1": "A"}


@pytest.mark.asyncio
async def test_list_exams_returns_history_summaries(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.api.dependencies import require_student
    from app.db.session import get_session
    from app.main import app

    now = datetime.now(timezone.utc)
    exam_row = SimpleNamespace(
        id="exam-1",
        user_id="student-1",
        title="آزمون مروری",
        book_id=2,
        grade_number=12,
        major_code="math_physics",
        exam_type="konkoor",
        status=ExamStatus.submitted,
        questions=[_question("q1")],
        time_limit_seconds=300,
        expires_at=now + timedelta(minutes=5),
        created_at=now,
        submitted_at=now,
        report_card={
            "score": 100.0,
            "scale": "percent",
            "correct": 1,
            "wrong": 0,
            "unanswered": 0,
            "total_questions": 1,
            "by_question": [],
        },
    )

    class FakeExec:
        def all(self):
            return [(exam_row, "فیزیک ۳")]

    class FakeSession:
        async def execute(self, stmt):
            return FakeExec()

    async def fake_session():
        yield FakeSession()

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[require_student] = lambda: SimpleNamespace(
        id="student-1",
        is_active=True,
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/exams")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "exam-1"
    assert data[0]["book_title"] == "فیزیک ۳"
    assert data[0]["report_summary"]["score"] == 100.0


@pytest.mark.asyncio
async def test_create_exam_falls_back_to_approved_book_pages_when_search_is_empty(monkeypatch):
    from app.services import exam_service

    async def empty_search(*args, **kwargs):
        return []

    async def fake_complete_json(*args, **kwargs):
        return {
            "questions": [
                {
                    "prompt": f"پرسش {i}",
                    "choices": {"A": "الف", "B": "ب", "C": "پ", "D": "ت"},
                    "correct_option": "A",
                    "explanation": "توضیح",
                    "source_index": 0,
                }
                for i in range(1, 4)
            ]
        }

    quiz_generation_calls = 0

    async def fake_complete_json_gateway(*, ctx, messages, model=None, session=None, **kwargs):
        # Generation and the Validator Gate both route through the shared gateway.
        if ctx.feature_key == "quiz_validator":
            return SimpleNamespace(
                content={
                    "verdicts": [
                        {"index": i, "grounded": True, "unambiguous": True, "latex_ok": True,
                         "confirmed_option": "A", "reasons": [], "fix": None}
                        for i in range(3)
                    ]
                },
                audit_id="audit-validator",
            )
        assert ctx.feature_key == "quiz"
        assert ctx.textbook_strict is True
        nonlocal quiz_generation_calls
        quiz_generation_calls += 1
        if quiz_generation_calls == 1:
            return SimpleNamespace(content={"questions": "malformed"}, audit_id="audit-quiz-invalid")
        return SimpleNamespace(
            content=await fake_complete_json(model, messages),
            audit_id="audit-quiz-repaired",
        )

    from app.services import capability_runtime, quiz_validator

    async def no_skill(*args, **kwargs):
        return None

    async def fake_validator(**kwargs):
        verdicts = {
            "verdicts": [
                {"index": i, "grounded": True, "unambiguous": True, "latex_ok": True,
                 "confirmed_option": "A", "reasons": [], "fix": None}
                for i in range(3)
            ]
        }
        return SimpleNamespace(content=verdicts, audit_id="audit-validator"), None

    monkeypatch.setattr(capability_runtime, "load_active_skill", no_skill)
    monkeypatch.setattr(quiz_validator, "run_capability_json", fake_validator)
    monkeypatch.setattr(exam_service, "search_textbook", empty_search)
    monkeypatch.setattr(capability_runtime, "complete_json_via_gateway", fake_complete_json_gateway)
    monkeypatch.setattr(exam_service, "get_settings", lambda: SimpleNamespace(tutor_model="demo-tutor"))

    page = SimpleNamespace(
        book_id=1,
        pdf_page_index=1,
        printed_page_number=8,
        chapter_number=1,
        chapter_title="حرکت بر خط راست",
        markdown_content="متن آزمایشی فیزیک",
        visual_elements=[],
    )

    class FakeExec:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeSession:
        def __init__(self, rows):
            self._rows = rows
            self.added = []

        async def execute(self, stmt):
            return FakeExec(self._rows)

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            return None

        async def refresh(self, obj):
            return None

    session = FakeSession([(page, "فیزیک ۳", 12, "math_physics")])
    exam = await exam_service.create_exam(
        session,  # type: ignore[arg-type]
        book_id=1,
        grade_number=12,
        major_code="math_physics",
        question_count=3,
        time_limit_minutes=10,
        exam_type="konkoor",
        user_id="student-1",
    )
    assert len(exam.questions) == 3
    assert exam.questions[0]["source"]["book_title"] == "فیزیک ۳"
    assert quiz_generation_calls == 2  # one malformed response plus one repair pass

    empty_session = FakeSession([])
    with pytest.raises(LookupError, match="no approved textbook pages"):
        await exam_service.create_exam(
            empty_session,  # type: ignore[arg-type]
            book_id=1,
            grade_number=12,
            major_code="math_physics",
            question_count=3,
            time_limit_minutes=10,
            exam_type="konkoor",
            user_id="student-1",
        )

