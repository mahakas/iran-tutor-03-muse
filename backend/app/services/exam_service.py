"""MCQ exam creation, timed persistence, and server-side report cards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.curriculum import Book, BookPage, Grade, Major, PageStatus
from app.models.exam import ExamSession, ExamStatus
from app.services.retrieval_service import page_embedding_text, search_textbook


class GeneratedQuestion(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    choices: dict[str, str]
    correct_option: Literal["A", "B", "C", "D"]
    explanation: str = Field(min_length=1, max_length=3000)
    source_index: int = Field(ge=0)

    @field_validator("choices")
    @classmethod
    def require_four_options(cls, choices: dict[str, str]) -> dict[str, str]:
        if set(choices) != {"A", "B", "C", "D"} or any(not value.strip() for value in choices.values()):
            raise ValueError("each question must have exactly four non-empty options A-D")
        return choices


class GeneratedQuestionSet(BaseModel):
    questions: list[GeneratedQuestion]


def _source_payload(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": page.get("book_id"),
        "book_title": page.get("book_title"),
        "chapter_number": page.get("chapter_number"),
        "chapter_title": page.get("chapter_title"),
        "pdf_page_index": page.get("pdf_page_index"),
        "printed_page_number": page.get("printed_page_number"),
    }


def validate_questions(
    generated: dict[str, Any], *, expected_count: int, source_count: int
) -> list[GeneratedQuestion]:
    """Validate model output and prevent fabricated source indexes."""
    try:
        question_set = GeneratedQuestionSet.model_validate(generated)
    except ValidationError as error:
        raise ValueError("question generator returned invalid structured data") from error
    if len(question_set.questions) != expected_count:
        raise ValueError(
            f"question generator returned {len(question_set.questions)} items; expected {expected_count}"
        )
    if source_count == 0 or any(question.source_index >= source_count for question in question_set.questions):
        raise ValueError("question generator referenced a source that was not provided")
    return question_set.questions


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def effective_exam_status(session: ExamSession, *, now: datetime | None = None) -> str:
    status = session.status.value if hasattr(session.status, "value") else str(session.status)
    if status == ExamStatus.active.value:
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if current > expires_at:
            return ExamStatus.expired.value
    return status


def public_exam(session: ExamSession, *, include_report: bool = False) -> dict[str, Any]:
    """Return questions without answer keys or explanations before submission."""
    status = effective_exam_status(session)
    payload: dict[str, Any] = {
        "id": session.id,
        "book_id": session.book_id,
        "grade_number": session.grade_number,
        "major_code": session.major_code,
        "branch_code": getattr(session, "branch_code", None),
        "title": session.title,
        "exam_type": session.exam_type,
        "time_limit_seconds": session.time_limit_seconds,
        "expires_at": _utc_iso(session.expires_at),
        "status": status,
        "questions": [
            {
                "id": question["id"],
                "prompt": question["prompt"],
                "choices": question["choices"],
                "points": question["points"],
                "source": question["source"],
            }
            for question in session.questions
        ],
    }
    if include_report and status == ExamStatus.submitted.value:
        report_card = getattr(session, "report_card", None)
        if report_card is not None:
            payload["report_card"] = report_card
            payload["submitted_answers"] = getattr(session, "submitted_answers", None) or {}
    return payload


def exam_summary(session: ExamSession, *, book_title: str | None = None) -> dict[str, Any]:
    """Return compact metadata and score summary for the student's exam history list."""
    status = effective_exam_status(session)
    report_card = getattr(session, "report_card", None)
    summary: dict[str, Any] | None = None
    if status == ExamStatus.submitted.value and isinstance(report_card, dict):
        summary = {
            "score": report_card.get("score"),
            "scale": report_card.get("scale"),
            "correct": report_card.get("correct"),
            "wrong": report_card.get("wrong"),
            "unanswered": report_card.get("unanswered"),
            "total_questions": report_card.get("total_questions"),
        }
    return {
        "id": session.id,
        "title": session.title,
        "book_id": session.book_id,
        "book_title": book_title,
        "grade_number": session.grade_number,
        "major_code": session.major_code,
        "branch_code": getattr(session, "branch_code", None),
        "exam_type": session.exam_type,
        "status": status,
        "question_count": len(session.questions or []),
        "time_limit_seconds": session.time_limit_seconds,
        "expires_at": _utc_iso(session.expires_at),
        "created_at": _utc_iso(getattr(session, "created_at", None)),
        "submitted_at": _utc_iso(getattr(session, "submitted_at", None)),
        "report_summary": summary,
    }


def grade_exam(
    questions: list[dict[str, Any]],
    answers: dict[str, str | None],
    *,
    exam_type: Literal["konkoor", "final"],
) -> dict[str, Any]:
    """Grade MCQ answers; entrance exams use correct +3 / wrong -1 scoring."""
    per_question: list[dict[str, Any]] = []
    correct = wrong = unanswered = 0
    for question in questions:
        answer = answers.get(question["id"])
        expected = question["correct_option"]
        is_correct = answer == expected
        if is_correct:
            correct += 1
        elif answer in {"A", "B", "C", "D"}:
            wrong += 1
        else:
            unanswered += 1
        per_question.append(
            {
                "id": question["id"],
                "answer": answer if answer in {"A", "B", "C", "D"} else None,
                "correct": is_correct,
                "correct_option": expected,
                "explanation": question["explanation"],
                "source": question["source"],
            }
        )

    total = len(questions)
    if exam_type == "konkoor":
        score = round((correct - wrong / 3) / total * 100, 2) if total else 0.0
        scale = "percent"
    else:
        score = round(correct / total * 20, 2) if total else 0.0
        scale = "out_of_20"
    return {
        "score": score,
        "scale": scale,
        "correct": correct,
        "wrong": wrong,
        "unanswered": unanswered,
        "total_questions": total,
        "by_question": per_question,
    }


async def create_exam(
    session: AsyncSession,
    *,
    book_id: int,
    grade_number: int,
    major_code: str | None,
    question_count: int,
    time_limit_minutes: int,
    exam_type: Literal["konkoor", "final"],
    branch_code: str | None = None,
    chapter_title: str | None = None,
    user_id: str | None = None,
) -> ExamSession:
    if not 3 <= question_count <= 20:
        raise ValueError("question_count must be between 3 and 20")
    if not 5 <= time_limit_minutes <= 120:
        raise ValueError("time_limit_minutes must be between 5 and 120")

    top_k = min(20, max(question_count, 8))
    query = f"مفاهیم، تعریف‌ها، فرمول‌ها و تمرین‌های فصل {chapter_title}" if chapter_title else "مفاهیم و فرمول‌های کلیدی کتاب"
    sources = await search_textbook(
        query,
        grade_number=grade_number,
        major_code=major_code,
        book_id=book_id,
        top_k=top_k,
    )
    if not sources:
        # Fallback for lexical/demo environments where generic query terms are absent from pages.
        selected_major = major_code or "general"
        stmt = (
            select(BookPage, Book.title, Grade.number, func.coalesce(Major.code, "general"))
            .join(Book, BookPage.book_id == Book.id)
            .join(Grade, Book.grade_id == Grade.id)
            .outerjoin(Major, Book.major_id == Major.id)
            .where(
                Book.id == book_id,
                Grade.number == grade_number,
                func.coalesce(Major.code, "general") == selected_major,
                BookPage.status == PageStatus.done,
            )
            .order_by(BookPage.pdf_page_index.asc())
            .limit(top_k)
        )
        if chapter_title and chapter_title.strip():
            stmt = stmt.where(BookPage.chapter_title.ilike(f"%{chapter_title.strip()}%"))
        rows = (await session.execute(stmt)).all()
        sources = [
            {
                "book_id": page.book_id,
                "book_title": book_title,
                "grade_number": grade_num,
                "major_code": maj_code,
                "pdf_page_index": page.pdf_page_index,
                "printed_page_number": page.printed_page_number,
                "chapter_number": page.chapter_number,
                "chapter_title": page.chapter_title,
                "full_text": page_embedding_text(page.markdown_content, page.visual_elements),
                "markdown_content": page.markdown_content,
                "visual_elements": page.visual_elements or [],
            }
            for page, book_title, grade_num, maj_code in rows
        ]
    if not sources:
        raise LookupError("no approved textbook pages found for the requested exam")

    context_parts = []
    for index, source in enumerate(sources):
        context_parts.append(
            f"[منبع {index}: {source.get('book_title')}، {source.get('chapter_title') or 'فصل نامشخص'}، "
            f"صفحه چاپی {source.get('printed_page_number')}]\n{source.get('full_text', '')}"
        )
    settings = get_settings()
    if not settings.tutor_model:
        raise RuntimeError("TUTOR_MODEL must be configured before generating an exam")

    system_prompt = (
        "تو طراح آزمون چهارگزینه‌ای برای دانش‌آموزان ایرانی هستی. فقط از محتوای منبع‌های ارائه‌شده سؤال بساز. "
        "هیچ نکته یا عددی را از بیرون اضافه نکن. هر سؤال دقیقاً چهار گزینه A,B,C,D داشته باشد، "
        "یک پاسخ قطعی داشته باشد و توضیح کوتاه مستند ارائه کند. برای هر سؤال source_index را برابر شمارهٔ "
        "یکی از منبع‌های داده‌شده قرار بده. متن سؤال و گزینه‌ها فارسی باشند و فرمول‌ها LaTeX باشند. "
        f"دقیقاً {question_count} سؤال تولید کن و فقط JSON با ساختار {{\"questions\":[{{"
        "\"prompt\":\"...\",\"choices\":{\"A\":\"...\",\"B\":\"...\",\"C\":\"...\",\"D\":\"...\"},"
        "\"correct_option\":\"A|B|C|D\",\"explanation\":\"...\",\"source_index\":0}}]}} برگردان."
    )
    from app.services.capability_runtime import run_capability_json
    from app.services.quiz_validator import validate_questions as validate_generated_questions

    generation_context = "\n\n---\n\n".join(context_parts)[:28_000]
    gateway_result, _skill = await run_capability_json(
        session=session,
        capability_key="quiz",
        feature_key="quiz",
        user_text=generation_context,
        user_id=user_id,
        book_id=book_id,
        textbook_strict=True,
        citations=sources,
        rag_hit_count=len(sources),
        model=settings.tutor_model,
        # The exam endpoint already enforced capability + quota; avoid charging twice.
        enforce=False,
        extra_system=system_prompt,
    )
    generated = gateway_result.content
    try:
        parsed_questions = validate_questions(
            generated, expected_count=question_count, source_count=len(sources)
        )
    except ValueError:
        # One schema-repair pass before the scientific Validator Gate. The repair
        # stays grounded in the same approved pages and is still gateway-audited.
        invalid_output = json.dumps(generated, ensure_ascii=False, default=str)[:12_000]
        try:
            repaired_result, _skill = await run_capability_json(
                session=session,
                capability_key="quiz",
                feature_key="quiz",
                user_text=(
                    f"{generation_context}\n\n"
                    f"خروجی JSON نامعتبر قبلی:\n{invalid_output}\n\n"
                    "خروجی قبلی را اصلاح کن. تعداد سؤال‌ها باید دقیقاً "
                    f"{question_count} باشد. source_index فقط می‌تواند یکی از "
                    f"اعداد 0 تا {len(sources) - 1} باشد. همهٔ سؤال‌ها باید چهار گزینه "
                    "غیرخالی A,B,C,D، یک correct_option از همین چهار گزینه و explanation "
                    "داشته باشند. فقط JSON معتبر با کلید questions برگردان."
                ),
                user_id=user_id,
                book_id=book_id,
                textbook_strict=True,
                citations=sources,
                rag_hit_count=len(sources),
                model=settings.tutor_model,
                enforce=False,
                extra_system=system_prompt,
            )
            generated = repaired_result.content
            parsed_questions = validate_questions(
                generated, expected_count=question_count, source_count=len(sources)
            )
        except Exception:
            # Keep both generation audits and the consumed quota even when repair fails.
            await session.commit()
            raise

    # Stage 2 (Validator Gate): grounding, LaTeX validity, unambiguous key.
    exam_id = str(uuid4())
    candidates = [
        {
            "question": {
                "prompt": question.prompt,
                "choices": question.choices,
                "correct_option": question.correct_option,
                "explanation": question.explanation,
                "source": _source_payload(sources[question.source_index]),
            },
            "source_text": sources[question.source_index].get("full_text", ""),
        }
        for question in parsed_questions
    ]
    outcome = await validate_generated_questions(
        session, items=candidates, user_id=user_id, book_id=book_id, exam_id=exam_id
    )
    if not outcome.accepted:
        raise ValueError("بازبین آزمون هیچ سؤالی را تأیید نکرد؛ آزمون دیگری بسازید.")

    questions: list[dict[str, Any]] = []
    for index, question in enumerate(outcome.accepted, start=1):
        questions.append(
            {
                "id": f"q{index}",
                "prompt": question["prompt"],
                "choices": question["choices"],
                "correct_option": question["correct_option"],
                "explanation": question["explanation"],
                "points": 1.0,
                "source": question["source"],
            }
        )
    now = datetime.now(timezone.utc)
    exam = ExamSession(
        id=exam_id,
        book_id=book_id,
        user_id=user_id,
        grade_number=grade_number,
        major_code=major_code or "general",
        branch_code=branch_code,
        title=f"آزمون {chapter_title or 'مروری'}",
        exam_type=exam_type,
        time_limit_seconds=time_limit_minutes * 60,
        status=ExamStatus.active,
        questions=questions,
        expires_at=now + timedelta(minutes=time_limit_minutes),
    )
    session.add(exam)
    from app.models.phase5 import QuizValidationLog

    for decision in outcome.decisions:
        original = candidates[decision.index]["question"]
        session.add(
            QuizValidationLog(
                user_id=user_id,
                exam_id=exam_id,
                book_id=book_id,
                question_index=decision.index,
                verdict=decision.verdict,
                reasons_json=list(decision.reasons),
                question_json={"original": original, "repaired": decision.question},
                audit_id=decision.audit_id,
            )
        )
    await session.commit()
    await session.refresh(exam)
    return exam


def submit_exam(
    session: ExamSession, answers: dict[str, str | None], *, now: datetime | None = None
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    status = session.status.value if hasattr(session.status, "value") else session.status
    if status != ExamStatus.active.value:
        raise ValueError("exam is not active")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if current > expires_at:
        session.status = ExamStatus.expired
        raise TimeoutError("exam time has expired")

    allowed_ids = {question["id"] for question in session.questions}
    if any(question_id not in allowed_ids for question_id in answers):
        raise ValueError("answers include an unknown question id")
    normalized = {
        question_id: answer if answer in {"A", "B", "C", "D"} else None
        for question_id, answer in answers.items()
    }
    report = grade_exam(session.questions, normalized, exam_type=session.exam_type)
    session.status = ExamStatus.submitted
    session.submitted_answers = normalized
    session.report_card = report
    session.submitted_at = current
    return report
