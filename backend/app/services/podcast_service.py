"""Smart podcast service (NotebookLM Audio Overview style) — Phase 9.

Pipeline: resolve server-owned textbook sources → generate a structured dialogue
script through the Central AI Runtime (`audio_podcast_script` route, JSON validated
with Pydantic + one controlled repair retry) → synthesize each turn with the
speaker's configured voice through the TTS runtime (`audio_podcast_tts` route,
reusing the shared content-addressed audio cache so cache hits are never re-billed)
→ assemble the pieces into one playable file (ffmpeg, stdlib fallback) → store in
the private storage dir and expose it only through authenticated owner-checked API
routes.

Long-running work runs as a database-backed job: the row carries status/progress
and a heartbeat, an in-process task processes it, an optional standalone worker
(`backend/scripts/podcast_worker.py`) can take over, and a startup sweep moves
stale jobs (dead worker/server restart) into a recognizable failed state so the
student can retry. FastAPI BackgroundTasks alone are not trusted for this.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.auth import User
from app.models.curriculum import Book, BookPage, PageStatus
from app.models.phase6 import AudioCacheEntry, LivingBookCache, Notebook, NotebookBlock
from app.models.podcast import (
    PODCAST_FORMATS,
    PODCAST_LENGTHS,
    SEGMENT_STATUSES,
    SPEAKERS,
    PodcastEpisode,
    PodcastFeedback,
    PodcastQuestion,
    PodcastSegment,
)
from app.services import audio_assembly
from app.services import capability_runtime
from app.services.ai_provider_service import resolve_feature_route
from app.services.capability_service import get_capability
from app.services.curriculum_access import is_student_visible_book
from app.services.learner_memory_service import build_memory_context

logger = logging.getLogger(__name__)

CAPABILITY_KEY = "audio_podcast"
SCRIPT_FEATURE_KEY = "audio_podcast_script"
TTS_FEATURE_KEY = "audio_podcast_tts"

PODCAST_ROOT = Path(__file__).resolve().parents[2] / "storage" / "podcast_audio"

MAX_CUSTOM_PROMPT_CHARS = 800
MAX_TTS_PIECE_CHARS = 3800          # stays under the 4000-char TTS provider limit
MAX_SOURCE_ITEMS = 24
DEFAULT_MAX_SOURCE_CHARS = 12000
DEFAULT_MAX_CONCURRENT_JOBS = 2
STALE_AFTER_SECONDS = 900           # no heartbeat for 15 minutes → worker considered lost
PAGE_CHUNK_CHARS = 1000
_CHARS_PER_SECOND = 13              # rough Persian speech pace for duration estimates

FORMAT_LABELS: dict[str, str] = {
    "deep_dive": "گفت‌وگوی عمیق (Deep Dive)",
    "brief": "پادکست کوتاه (Brief)",
    "critique": "نقد و بررسی آموزشی (Critique)",
    "debate": "مناظرهٔ آموزشی (Debate)",
}
LENGTH_LABELS: dict[str, str] = {
    "short": "کوتاه",
    "standard": "استاندارد",
    "long": "طولانی",
}
SPEAKER_LABELS: dict[str, str] = {
    "host_a": "گویندهٔ اول (مدرس)",
    "host_b": "گویندهٔ دوم (هم‌صحبت)",
    "narrator": "راوی",
}
FEEDBACK_REASONS: tuple[str, ...] = (
    "bad_voice",
    "bad_pronunciation",
    "unclear_explanations",
    "repetitive",
    "bad_length",
    "unnatural_dialogue",
    "wrong_information",
)
SUPPORTED_LANGUAGES: dict[str, str] = {"fa": "فارسی"}

FORMAT_RULES: dict[str, str] = {
    "deep_dive": (
        "قالب Deep Dive: دو گوینده با یکدیگر گفت‌وگوی عمیق آموزشی داشته باشند؛ معرفی موضوع، توضیح مفاهیم اصلی، "
        "باز کردن موضوعات دشوار، ارتباط مفاهیم با هم، مثال مناسب و پرسش‌وپاسخ بین دو گوینده و در پایان جمع‌بندی نکات مهم. "
        "گویندهٔ اول نقش مدرس و گویندهٔ دوم نقش دانش‌آموز کنجکاو را دارد؛ لحن طبیعی و جذاب باشد و اصلاً حالت رباتیک نداشته باشد."
    ),
    "brief": (
        "قالب Brief: فقط یک گوینده (narrator) یک چکیدهٔ آموزشی ارائه کند: مقدمهٔ کوتاه، مهم‌ترین مفاهیم، نکات کلیدی و نتیجه‌گیری. "
        "مناسب مرور سریع قبل از امتحان؛ هدف انتقال نکات مهم در زمان کوتاه است."
    ),
    "critique": (
        "قالب Critique: دو گوینده محتوای انتخاب‌شده را بررسی و نقد آموزشی کنند: بررسی صحت و انسجام توضیحات در محدودهٔ منابع، "
        "تشخیص مفاهیم دشوار، اشاره به سوءبرداشت‌های رایج دانش‌آموزان و پیشنهاد روش بهتر برای فهم مطالب. "
        "نقد بهانه‌ای برای اطلاعات خارج از منابع نیست."
    ),
    "debate": (
        "قالب Debate: دو گوینده جنبه‌های مختلف موضوع را مقایسه کنند (مثلاً دو روش حل مسئله یا دو مفهوم مرتبط در چارچوب کتاب) و مزایا و محدودیت هر روش را توضیح دهند. "
        "مناظره هدف آموزشی دارد؛ هرگز اختلاف علمی ساختگی یا اطلاعات نادرست تولید نکن — اگر موضوع در منابع فقط یک پاسخ معتبر دارد، "
        "مناظره روی روش‌های توضیح، یادگیری یا حل تمرین بماند."
    ),
}

LENGTH_RULES: dict[str, str] = {
    "short": "مدت هدف پادکست کوتاه است (حدود ۳ تا ۵ دقیقه؛ حدود ۵۰۰ تا ۷۰۰ کلمه).",
    "standard": "مدت هدف پادکست استاندارد است (حدود ۸ تا ۱۲ دقیقه؛ حدود ۱۲۰۰ تا ۱۷۰۰ کلمه).",
    "long": "مدت هدف پادکست طولانی است (حدود ۱۵ تا ۲۰ دقیقه؛ حدود ۲۲۰۰ تا ۳۰۰۰ کلمه).",
}


# ---------------------------------------------------------------------------
# Pydantic contract for the model's script output
# ---------------------------------------------------------------------------


class ScriptSegmentDraft(BaseModel):
    speaker: str = Field(min_length=1, max_length=16)
    text: str = Field(min_length=2, max_length=1600)
    source_refs: list[int] = Field(default_factory=list, max_length=8)


class PodcastScriptDraft(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=600)
    segments: list[ScriptSegmentDraft] = Field(min_length=2, max_length=80)
    suggested_questions: list[str] = Field(default_factory=list, max_length=8)


# ---------------------------------------------------------------------------
# Admin-configurable settings (capability.config_json)
# ---------------------------------------------------------------------------


def podcast_config(capability) -> dict[str, Any]:
    config = dict(capability.config_json or {}) if capability is not None else {}
    config.setdefault("max_source_chars", DEFAULT_MAX_SOURCE_CHARS)
    config.setdefault("max_concurrent_jobs", DEFAULT_MAX_CONCURRENT_JOBS)
    config.setdefault("host_a_voice", "")
    config.setdefault("host_b_voice", "")
    config.setdefault("narrator_voice", "")
    config.setdefault("supported_languages", ["fa"])
    return config


async def load_podcast_config(session: AsyncSession) -> dict[str, Any]:
    return podcast_config(await get_capability(session, CAPABILITY_KEY))


async def resolve_voices_and_model(session: AsyncSession, format: str) -> dict[str, Any]:
    """Voices per speaker + routed TTS model; honest about single-voice setups."""
    settings = get_settings()
    config = await load_podcast_config(session)
    default_voice = str(settings.speech_default_voice or "").strip()
    host_a = str(config["host_a_voice"] or "").strip() or default_voice
    host_b = str(config["host_b_voice"] or "").strip() or default_voice
    narrator = str(config["narrator_voice"] or "").strip() or default_voice
    if not host_a and not settings.demo_mode:
        raise HTTPException(status_code=503, detail="صدای پادکست توسط مدیر تنظیم نشده است.")
    host_a = host_a or "demo"
    host_b = host_b or "demo"
    narrator = narrator or "demo"
    two_speaker = format != "brief"
    single_speaker_mode = two_speaker and host_a == host_b
    route = await resolve_feature_route(session, TTS_FEATURE_KEY)
    model = (route.model_name if route and route.configured else None) or settings.speech_synthesis_model or ""
    if not model and not settings.demo_mode:
        raise HTTPException(status_code=503, detail="مدل صوتی پادکست تنظیم نشده است.")
    return {
        "voices": {"host_a": host_a, "host_b": host_b, "narrator": narrator},
        "model": model or "demo",
        "single_speaker_mode": single_speaker_mode,
        "languages": [code for code in list(config["supported_languages"]) if code in SUPPORTED_LANGUAGES] or ["fa"],
        "max_source_chars": int(config["max_source_chars"]),
        "max_concurrent_jobs": int(config["max_concurrent_jobs"]),
        "length_targets": {
            "short": str(config.get("length_minutes_short", "3-5")),
            "standard": str(config.get("length_minutes_standard", "8-12")),
            "long": str(config.get("length_minutes_long", "15-20")),
        },
    }


# ---------------------------------------------------------------------------
# Source resolution (server-owned, textbook-strict, grade-limited)
# ---------------------------------------------------------------------------


def _page_chunks(text: str, *, limit: int = PAGE_CHUNK_CHARS) -> list[str]:
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(current) + len(paragraph) + 1 <= limit:
            current = f"{current}\n{paragraph}".strip()
        else:
            if current:
                chunks.append(current)
            while len(paragraph) > limit:
                cut = paragraph.rfind(" ", 0, limit)
                cut = cut if cut > limit // 2 else limit
                chunks.append(paragraph[:cut].strip())
                paragraph = paragraph[cut:].strip()
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


async def resolve_podcast_sources(
    session: AsyncSession,
    user: User,
    *,
    book: Book,
    chapter_numbers: list[int],
    page_start: int | None = None,
    page_end: int | None = None,
    include_notebook: bool = False,
    include_living_book: bool = False,
    max_chars: int = DEFAULT_MAX_SOURCE_CHARS,
) -> dict[str, Any]:
    """Collect only validated, official textbook material (plus optional notebook
    / living-book extras of the same book). Only `done` pages feed the podcast —
    `needs_review` pages never enter educational audio without an explicit owner
    decision; books of a higher grade than the student's are rejected."""
    if not is_student_visible_book(book):
        raise HTTPException(status_code=422, detail="این کتاب برای دانش‌آموزان در دسترس نیست.")
    scope_grade = None
    if book.grade_id:
        from app.models.curriculum import Grade

        grade_row = await session.get(Grade, book.grade_id)
        scope_grade = grade_row.number if grade_row else None
    student_grade = user.grade_level
    if scope_grade is not None and student_grade is not None and scope_grade > student_grade:
        raise HTTPException(
            status_code=422,
            detail="محتوای پایه‌های بالاتر برای دانش‌آموز این پایه مجاز نیست.",
        )

    chapters = sorted({int(c) for c in chapter_numbers if 1 <= int(c) <= 99})
    if not chapters and page_start is None:
        raise HTTPException(status_code=422, detail="حداقل یک فصل یا بازهٔ صفحه را انتخاب کنید.")
    if page_start is not None and page_end is not None and page_end < page_start:
        raise HTTPException(status_code=422, detail="بازهٔ صفحه نامعتبر است.")

    query = select(BookPage).where(
        BookPage.book_id == book.id,
        # Phase 04A source integrity: only fully validated pages. needs_review
        # content never reaches generated audio without an explicit owner decision.
        BookPage.status == PageStatus.done,
    )
    if chapters:
        query = query.where(BookPage.chapter_number.in_(chapters))
    if page_start is not None:
        query = query.where(BookPage.pdf_page_index >= page_start)
    if page_end is not None:
        query = query.where(BookPage.pdf_page_index <= page_end)
    rows = list(
        (await session.scalars(query.order_by(BookPage.pdf_page_index.asc()))).all()
    )
    rows = [row for row in rows if (row.markdown_content or "").strip()]
    if not rows:
        raise HTTPException(
            status_code=422,
            detail="برای این انتخاب، صفحه‌ای با متن معتبر پیدا نشد. صفحات تأییدنشده به‌عنوان منبع استفاده نمی‌شوند.",
        )

    sources: list[dict[str, Any]] = []
    total = 0
    book_title = book.title
    for row in rows:
        for chunk_index, chunk in enumerate(_page_chunks(row.markdown_content or ""), start=1):
            if total + len(chunk) > max_chars or len(sources) >= MAX_SOURCE_ITEMS:
                break
            citation = (
                f"[کتاب: {book_title} | پایه {scope_grade if scope_grade else '—'} "
                f"| صفحه {row.printed_page_number if row.printed_page_number is not None else row.pdf_page_index} "
                f"| قطعه {len(sources) + 1}]"
            )
            sources.append({
                "index": len(sources) + 1,
                "kind": "book",
                "text": chunk,
                "citation": citation,
                "book_id": book.id,
                "chapter_number": row.chapter_number,
                "chapter_title": row.chapter_title or (f"فصل {row.chapter_number}" if row.chapter_number else None),
                "pdf_page_index": row.pdf_page_index,
                "printed_page_number": row.printed_page_number,
            })
            total += len(chunk)
        if total >= max_chars or len(sources) >= MAX_SOURCE_ITEMS:
            break

    if include_notebook:
        notebook_rows = list(
            (
                await session.scalars(
                    select(NotebookBlock)
                    .join(Notebook, NotebookBlock.notebook_id == Notebook.id)
                    .where(
                        Notebook.user_id == user.id,
                        Notebook.book_id == book.id,
                        NotebookBlock.block_type.in_(["text_markdown", "callout_tip"]),
                    )
                    .order_by(NotebookBlock.id.asc())
                    .limit(6)
                )
            ).all()
        )
        for block in notebook_rows:
            text = (block.content or "").strip()[:1500]
            if not text or total + len(text) > max_chars:
                continue
            sources.append({
                "index": len(sources) + 1,
                "kind": "notebook",
                "text": text,
                "citation": f"[دفترچهٔ یادداشت: {book_title} | بلوک {block.id}]",
                "book_id": book.id,
            })
            total += len(text)

    if include_living_book:
        living_rows = list(
            (
                await session.scalars(
                    select(LivingBookCache).where(
                        LivingBookCache.book_id == book.id,
                        LivingBookCache.chapter_number.in_(chapters or [0]),
                    )
                )
            ).all()
        )
        for cache_row in living_rows:
            for block in (cache_row.blocks_json or [])[:4]:
                if not isinstance(block, dict):
                    continue
                text = str(block.get("content") or "").strip()[:1200]
                if not text or total + len(text) > max_chars:
                    continue
                sources.append({
                    "index": len(sources) + 1,
                    "kind": "living_book",
                    "text": text,
                    "citation": (
                        f"[کتاب زنده: {book_title} | فصل {cache_row.chapter_number}]"
                    ),
                    "book_id": book.id,
                    "chapter_number": cache_row.chapter_number,
                })
                total += len(text)

    if not sources:
        raise HTTPException(status_code=422, detail="متن معتبری برای تولید پادکست یافت نشد.")

    source_hash = hashlib.sha256(
        "\x1e".join(item["text"] for item in sources).encode("utf-8")
    ).hexdigest()
    return {
        "book_id": book.id,
        "book_title": book_title,
        "grade_number": scope_grade,
        "chapters": chapters,
        "page_start": page_start,
        "page_end": page_end,
        "max_chars": max_chars,
        "sources": sources,
        "citations": [{"citation": item["citation"]} for item in sources],
        "source_hash": source_hash,
    }


def build_script_prompt(snapshot: dict[str, Any], *, format: str, language: str, length: str, custom_prompt: str, single_speaker_mode: bool) -> str:
    lines = [
        f"قالب پادکست: {FORMAT_LABELS[format]}",
        FORMAT_RULES[format],
        LENGTH_RULES[length],
        f"زبان گفت‌وگو: {'فارسی' if language == 'fa' else language}",
    ]
    if single_speaker_mode:
        lines.append("توجه: صدای دو گوینده یکسان است؛ باز هم متن را به‌صورت گفت‌وگوی دو نفره بنویس (نقش‌ها متفاوت است).")
    lines.append("منابع معتبر (فقط از همین‌ها مطلب بیاور؛ دانش بیرونی ممنوع):")
    for item in snapshot["sources"]:
        lines.append(f"\n[منبع {item['index']}] ({item['citation']})\n{item['text']}")
    if custom_prompt.strip():
        lines.append(
            "\nتمرکز درخواستی دانش‌آموز (دقیقاً رعایت کن، اما فقط بر پایهٔ منابع بالا):\n"
            f"{custom_prompt.strip()}"
        )
    allowed_speakers = ["narrator"] if format == "brief" else ["host_a", "host_b"]
    lines.append(
        "\nخروجی فقط یک JSON معتبر با این ساختار باشد:\n"
        '{"title":"عنوان","description":"توضیح یک‌دو جمله‌ای","segments":[{"speaker":"host_a",'
        '"text":"متن گفتار","source_refs":[1]}],"suggested_questions":["سؤال ۱","سؤال ۲"]}\n'
        f"قواعد: speaker فقط یکی از {allowed_speakers} باشد؛ هر segment یک نوبت گفتار طبیعی و کوتاه (حداکثر ۲ تا ۳ جمله) باشد؛ "
        "source_refs شمارهٔ منابع استفاده‌شده در همان نوبت است؛ "
        "عبارت‌های ریاضی و فرمول‌ها را با معادل گفتاری ساده بنویس تا TTS درست بخواند (مثلاً «a مساوی v تقسیم بر t» به‌جای نماد ریاضی)؛ "
        "اعداد را با حروف فارسی بنویس تا تلفظ درست باشد؛ "
        "مکالمه تکراری نباشد؛ ابتدا معرفی و در پایان جمع‌بندی و دعوت به ادامهٔ یادگیری داشته باشد؛ "
        "۳ تا ۵ سؤال پیشنهادی برای ادامهٔ بحث از دل همین منابع بنویس."
    )
    return "\n".join(lines)


def validate_script(raw: str, *, format: str) -> PodcastScriptDraft:
    """Parse + validate the model output against the format contract."""
    payload = _extract_json(raw)
    if payload is None:
        raise HTTPException(status_code=502, detail="خروجی اسکریپت پادکست قابل تفسیر نبود.")
    try:
        script = PodcastScriptDraft.model_validate(payload)
    except ValidationError as error:
        raise HTTPException(
            status_code=502,
            detail="ساختار اسکریپت پادکست نامعتبر بود: " + str(error.errors()[:2]),
        ) from error
    allowed = {"narrator"} if format == "brief" else {"host_a", "host_b"}
    for segment in script.segments:
        if segment.speaker not in allowed:
            raise HTTPException(
                status_code=502,
                detail=f"گویندهٔ نامعتبر «{segment.speaker}» در اسکریپت پادکست.",
            )
    return script


def _extract_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        payload = _json_loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:  # noqa: BLE001 - fall through to brace scan
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = _json_loads(text[start:end + 1])
        return payload if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _json_loads(text: str) -> Any:
    import json

    return json.loads(text)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_episode(
    episode: PodcastEpisode,
    *,
    segments: list[PodcastSegment] | None = None,
    questions: list[PodcastQuestion] | None = None,
    feedback: PodcastFeedback | None = None,
) -> dict[str, Any]:
    settings = dict(episode.generation_settings_json or {})
    payload: dict[str, Any] = {
        "id": episode.id,
        "title": episode.title,
        "description": episode.description,
        "format": episode.format,
        "format_label": FORMAT_LABELS.get(episode.format, episode.format),
        "language": episode.language,
        "length": episode.length,
        "book_id": episode.book_id,
        "book_title": (episode.source_snapshot_json or {}).get("book_title"),
        "chapters": (episode.source_snapshot_json or {}).get("chapters") or [],
        "status": episode.status,
        "progress": episode.progress,
        "progress_stage": episode.progress_stage,
        "error_code": episode.error_code,
        "error_detail": episode.error_detail if episode.status == "failed" else None,
        "duration_seconds": episode.duration_seconds,
        "byte_size": episode.byte_size,
        "has_audio": bool(episode.audio_file_path),
        "single_speaker_mode": bool(settings.get("single_speaker_mode")),
        "speakers": settings.get("voices") or {},
        "suggested_questions": list((episode.script_json or {}).get("suggested_questions") or []),
        "created_at": episode.created_at.isoformat() if episode.created_at else None,
        "completed_at": episode.completed_at.isoformat() if episode.completed_at else None,
    }
    if segments is not None:
        payload["segments"] = [serialize_segment(segment) for segment in segments]
        payload["transcript"] = episode.transcript or ""
        payload["sources"] = [
            {"index": item["index"], "citation": item["citation"], "kind": item.get("kind", "book")}
            for item in (episode.source_snapshot_json or {}).get("sources", [])
        ]
    if questions is not None:
        payload["questions"] = [
            {
                "id": question.id,
                "question": question.question,
                "answer_md": question.answer_md,
                "citations": list(question.citations_json or []),
                "created_at": question.created_at.isoformat() if question.created_at else None,
            }
            for question in questions
        ]
    if feedback is not None:
        payload["feedback"] = {
            "liked": feedback.liked,
            "reasons": list(feedback.reasons_json or []),
        }
    return payload


def serialize_segment(segment: PodcastSegment) -> dict[str, Any]:
    timed = segment.start_time is not None and segment.end_time is not None
    return {
        "id": segment.id,
        "position": segment.position,
        "speaker": segment.speaker,
        "speaker_label": SPEAKER_LABELS.get(segment.speaker, segment.speaker),
        "text": segment.text,
        "source_refs": list(segment.source_refs_json or []),
        "start_time": segment.start_time if timed else None,
        "end_time": segment.end_time if timed else None,
        "duration_seconds": segment.duration_seconds,
        "estimated_seconds": round(len(segment.text) / _CHARS_PER_SECOND, 1),
        "status": segment.status,
    }


async def get_owned_episode(session: AsyncSession, user: User, episode_id: int) -> PodcastEpisode:
    episode = await session.get(PodcastEpisode, episode_id)
    if episode is None or episode.user_id != user.id:
        raise HTTPException(status_code=404, detail="پادکست یافت نشد.")
    return episode


async def require_podcast_enabled(session: AsyncSession, user: User) -> None:
    from app.services.capability_service import require_capability_enabled

    await require_capability_enabled(session, CAPABILITY_KEY, user)


# ---------------------------------------------------------------------------
# Create / list / update / delete
# ---------------------------------------------------------------------------


async def count_active_jobs(session: AsyncSession, user_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(PodcastEpisode)
            .where(
                PodcastEpisode.user_id == user_id,
                PodcastEpisode.status.in_(["queued", "generating_script", "generating_audio", "assembling_audio"]),
            )
        )
        or 0
    )


async def create_episode(
    session: AsyncSession,
    user: User,
    *,
    book: Book,
    format: str,
    language: str,
    length: str,
    custom_prompt: str = "",
    chapter_numbers: list[int],
    page_start: int | None = None,
    page_end: int | None = None,
    include_notebook: bool = False,
    include_living_book: bool = False,
) -> PodcastEpisode:
    if format not in PODCAST_FORMATS:
        raise HTTPException(status_code=422, detail="قالب پادکست نامعتبر است.")
    if length not in PODCAST_LENGTHS:
        raise HTTPException(status_code=422, detail="مدت پادکست نامعتبر است.")
    config = await load_podcast_config(session)
    if language not in [str(code) for code in config["supported_languages"]]:
        raise HTTPException(
            status_code=422,
            detail="این زبان توسط سرویس صوتی فعلی پشتیبانی نمی‌شود.",
        )
    audio = await resolve_voices_and_model(session, format)
    active = await count_active_jobs(session, user.id)
    if active >= int(config["max_concurrent_jobs"]):
        raise HTTPException(
            status_code=429,
            detail="در حال حاضر چند پادکست در حال تولید دارید؛ پس از پایان آن‌ها دوباره تلاش کنید.",
        )
    snapshot = await resolve_podcast_sources(
        session,
        user,
        book=book,
        chapter_numbers=chapter_numbers,
        page_start=page_start,
        page_end=page_end,
        include_notebook=include_notebook,
        include_living_book=include_living_book,
        max_chars=audio["max_source_chars"],
    )
    episode = PodcastEpisode(
        user_id=user.id,
        book_id=book.id,
        title=f"پادکست {FORMAT_LABELS[format]}",
        format=format,
        language=language,
        length=length,
        custom_prompt=custom_prompt.strip()[:MAX_CUSTOM_PROMPT_CHARS],
        source_snapshot_json=snapshot,
        status="queued",
        progress=0,
        progress_stage="در صف تولید",
        source_hash=snapshot["source_hash"],
        generation_settings_json={
            "voices": audio["voices"],
            "model": audio["model"],
            "single_speaker_mode": audio["single_speaker_mode"],
            "length_targets": audio["length_targets"],
        },
        heartbeat_at=datetime.now(timezone.utc),
    )
    session.add(episode)
    await session.flush()
    return episode


async def list_episodes(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(PodcastEpisode)
                .where(PodcastEpisode.user_id == user.id)
                .order_by(PodcastEpisode.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    return [serialize_episode(row) for row in rows]


async def episode_detail(
    session: AsyncSession, user: User, episode: PodcastEpisode
) -> dict[str, Any]:
    segments = list(
        (
            await session.scalars(
                select(PodcastSegment)
                .where(PodcastSegment.episode_id == episode.id)
                .order_by(PodcastSegment.position.asc())
            )
        ).all()
    )
    questions = list(
        (
            await session.scalars(
                select(PodcastQuestion)
                .where(PodcastQuestion.episode_id == episode.id)
                .order_by(PodcastQuestion.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    feedback = await session.scalar(
        select(PodcastFeedback).where(
            PodcastFeedback.episode_id == episode.id, PodcastFeedback.user_id == user.id
        )
    )
    return serialize_episode(episode, segments=segments, questions=questions, feedback=feedback)


async def rename_episode(session: AsyncSession, user: User, episode: PodcastEpisode, title: str) -> PodcastEpisode:
    episode.title = title.strip()[:255] or episode.title
    await session.flush()
    return episode


async def delete_episode(session: AsyncSession, user: User, episode: PodcastEpisode) -> None:
    if episode.audio_file_path:
        audio_path = Path(episode.audio_file_path)
        if audio_path.is_file():
            audio_path.unlink(missing_ok=True)
        episode_dir = audio_path.parent
        if episode_dir.is_dir() and episode_dir.name == f"ep-{episode.id}":
            for leftover in episode_dir.iterdir():
                leftover.unlink(missing_ok=True)
            episode_dir.rmdir()
    # Explicit child cleanup (SQLite does not enforce FK cascade by default).
    for rows in (
        select(PodcastSegment).where(PodcastSegment.episode_id == episode.id),
        select(PodcastFeedback).where(PodcastFeedback.episode_id == episode.id),
        select(PodcastQuestion).where(PodcastQuestion.episode_id == episode.id),
    ):
        for row in (await session.scalars(rows)).all():
            await session.delete(row)
    await session.delete(episode)
    await session.flush()


# ---------------------------------------------------------------------------
# Generation job (script → TTS → assembly) with recovery
# ---------------------------------------------------------------------------


async def _claim_episode(session: AsyncSession, episode_id: int) -> bool:
    """Atomically move queued → generating_script; False when another worker won."""
    result = await session.execute(
        update(PodcastEpisode)
        .where(PodcastEpisode.id == episode_id, PodcastEpisode.status == "queued")
        .values(
            status="generating_script",
            progress=10,
            progress_stage="آماده‌سازی منابع",
            started_at=datetime.now(timezone.utc),
            heartbeat_at=datetime.now(timezone.utc),
            error_code=None,
            error_detail=None,
        )
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)


async def _touch(session: AsyncSession, episode: PodcastEpisode, *, progress: int, stage: str, status: str | None = None) -> None:
    episode.progress = max(episode.progress, int(progress))
    episode.progress_stage = stage
    episode.heartbeat_at = datetime.now(timezone.utc)
    if status:
        episode.status = status
    await session.flush()
    await session.commit()


async def _fail(session: AsyncSession, episode: PodcastEpisode, code: str, detail: str) -> None:
    episode.status = "failed"
    episode.error_code = code
    episode.error_detail = detail[:2000]
    episode.heartbeat_at = datetime.now(timezone.utc)
    await session.flush()
    await session.commit()


def _split_for_tts(text: str, *, limit: int = MAX_TTS_PIECE_CHARS) -> list[str]:
    """Split long speech at sentence boundaries; never reorder, never cut mid-formula."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return [text] if text else []
    pieces: list[str] = []
    buffer = ""
    # Sentence enders for Persian: period, ؟, !, … ; the formula-safe split never
    # happens inside $...$ because we only cut directly after a terminator.
    for sentence in re.findall(r"[^.!?؟…]+[.!?؟…]?", text):
        candidate = f"{buffer} {sentence}".strip()
        if len(candidate) <= limit:
            buffer = candidate
            continue
        if buffer:
            pieces.append(buffer)
        if len(sentence) <= limit:
            buffer = sentence
        else:
            # One enormous sentence: hard-split without breaking dollar math pairs.
            start = 0
            while start < len(sentence):
                piece = sentence[start:start + limit]
                if piece.count("$") % 2 == 1 and start + limit < len(sentence):
                    # extend to the closing dollar sign when possible
                    closing = sentence.find("$", start + limit)
                    if closing != -1:
                        piece = sentence[start:closing + 1]
                pieces.append(piece.strip())
                start += len(piece)
            buffer = ""
    if buffer:
        pieces.append(buffer)
    return [piece for piece in pieces if piece.strip()]


async def _speech_for_piece(
    session: AsyncSession,
    user: User,
    episode: PodcastEpisode,
    *,
    voice: str,
    text: str,
) -> Path:
    """Synthesize one TTS piece, reusing the shared content-addressed audio cache.

    Cache hits cost the student nothing (no provider call, no quota charge) and
    are audited like the TTS read-aloud path does.
    """
    settings = dict(episode.generation_settings_json or {})
    model = str(settings.get("model") or "")
    key = hashlib.sha256(f"{model}\x1f{voice}\x1f{text}".encode("utf-8")).hexdigest()
    entry = await session.scalar(select(AudioCacheEntry).where(AudioCacheEntry.cache_key == key))
    if entry is not None and Path(entry.file_path).is_file():
        entry.hit_count = (entry.hit_count or 0) + 1
        entry.last_used_at = datetime.now(timezone.utc)
        return Path(entry.file_path)

    audio, _result = await capability_runtime.run_capability_speech(
        session=session,
        capability_key=CAPABILITY_KEY,
        feature_key=TTS_FEATURE_KEY,
        text=text,
        voice=voice,
        user_id=user.id,
        book_id=episode.book_id,
        user=user,
        enforce=True,
        audit_in_own_transaction=True,
    )
    extension = ".wav" if audio_assembly.is_wav(audio) else ".mp3"
    path = Path(__file__).resolve().parents[2] / "storage" / "tts_cache" / key[:2] / f"{key}{extension}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    session.add(
        AudioCacheEntry(
            cache_key=key,
            user_id=user.id,
            book_id=episode.book_id,
            voice=voice,
            model_name=model,
            text_chars=len(text),
            byte_size=len(audio),
            file_path=str(path),
            hit_count=0,
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        # Phase 04C (PostgreSQL QA): the cache row can already exist — a stale
        # row whose file was pruned from disk, or a concurrent worker that
        # synthesised the same text first. Reuse that row and make sure its
        # file is actually present; never fail the episode over the cache.
        await session.rollback()
        entry = await session.scalar(
            select(AudioCacheEntry).where(AudioCacheEntry.cache_key == key)
        )
        if entry is None:
            raise
        existing_path = Path(entry.file_path)
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        if not existing_path.is_file():
            existing_path.write_bytes(audio)
        return existing_path
    return path


def _voice_for(episode: PodcastEpisode, speaker: str) -> str:
    voices = dict((episode.generation_settings_json or {}).get("voices") or {})
    return str(voices.get(speaker) or voices.get("narrator") or "demo")


async def process_episode(episode_id: int) -> None:
    """Run one podcast job to completion in its own DB session (worker entrypoint)."""
    async with async_session_factory() as session:
        episode = await session.get(PodcastEpisode, episode_id)
        if episode is None:
            return
        if not await _claim_episode(session, episode_id):
            return
        await session.commit()
        await session.refresh(episode)
        from app.models.auth import User

        user = await session.get(User, episode.user_id)
        if user is None:
            await _fail(session, episode, "user_missing", "کاربر مالک یافت نشد.")
            return
        try:
            await _run_generation(session, user, episode)
        except HTTPException as error:
            code = "script_invalid" if error.status_code == 502 else f"http_{error.status_code}"
            await _fail(session, episode, code, str(error.detail))
        except asyncio.CancelledError:
            await session.rollback()
            raise
        except Exception as error:  # noqa: BLE001 - job must record its own failure
            logger.exception("podcast.job_failed episode=%s", episode_id)
            await session.rollback()
            await _fail(session, episode, "generation_error", f"{type(error).__name__}: {error}")


async def _run_generation(session: AsyncSession, user: User, episode: PodcastEpisode) -> None:
    snapshot = dict(episode.source_snapshot_json or {})
    sources = list(snapshot.get("sources") or [])
    if not sources:
        await _fail(session, episode, "sources_missing", "منابع پادکست در دسترس نیست.")
        return

    # 1) Script generation through the central runtime. On a retry after an audio
    # failure the validated script is reused and finished segments are not re-made.
    await _touch(session, episode, progress=15, stage="تولید متن گفت‌وگو", status="generating_script")
    memory_context = await build_memory_context(session, user.id, episode.book_id)
    existing_script = dict(episode.script_json or {})
    if not existing_script.get("segments"):
        prompt = build_script_prompt(
            snapshot,
            format=episode.format,
            language=episode.language,
            length=episode.length,
            custom_prompt=episode.custom_prompt or "",
            single_speaker_mode=bool((episode.generation_settings_json or {}).get("single_speaker_mode")),
        )
        result, _blocks, _skill = await capability_runtime.run_capability_text(
            session=session,
            capability_key=CAPABILITY_KEY,
            feature_key=SCRIPT_FEATURE_KEY,
            user_text=prompt,
            user_id=user.id,
            user=user,
            book_id=episode.book_id,
            textbook_strict=True,
            citations=list(snapshot.get("citations") or []),
            rag_hit_count=len(sources),
            extra_system=memory_context or None,
            audit_in_own_transaction=True,
        )
        try:
            script = validate_script(result.content if isinstance(result.content, str) else "", format=episode.format)
        except HTTPException:
            # One controlled repair attempt before failing the job.
            repair_prompt = (
                "خروجی قبلی شما ساختار نامعتبر داشت. فقط یک JSON معتبر با ساختار خواسته‌شده برگردان:\n"
                '{"title":"...","description":"...","segments":[{"speaker":"host_a","text":"...","source_refs":[1]}],'
                '"suggested_questions":["..."]}\n'
                "بدون هیچ متن اضافه و بدون بلوک کد.\n\n"
                "خروجی قبلی:\n" + (result.content if isinstance(result.content, str) else "")[:2000]
            )
            retry, _b2, _s2 = await capability_runtime.run_capability_text(
                session=session,
                capability_key=CAPABILITY_KEY,
                feature_key=SCRIPT_FEATURE_KEY,
                user_text=prompt + "\n\n" + repair_prompt,
                user_id=user.id,
                user=user,
                book_id=episode.book_id,
                textbook_strict=True,
                citations=list(snapshot.get("citations") or []),
                rag_hit_count=len(sources),
                audit_in_own_transaction=True,
            )
            script = validate_script(retry.content if isinstance(retry.content, str) else "", format=episode.format)

        episode.title = script.title.strip()[:255]
        episode.description = script.description.strip()[:600]
        episode.script_json = {
            "title": script.title,
            "description": script.description,
            "segments": [segment.model_dump() for segment in script.segments],
            "suggested_questions": script.suggested_questions,
            "model_name": result.model_name,
            "estimated_seconds": round(
                sum(len(segment.text) for segment in script.segments) / _CHARS_PER_SECOND, 1
            ),
        }
        episode.model_name = result.model_name
        for old in (await session.scalars(select(PodcastSegment).where(PodcastSegment.episode_id == episode.id))).all():
            await session.delete(old)
        for position, segment in enumerate(script.segments):
            session.add(
                PodcastSegment(
                    episode_id=episode.id,
                    position=position,
                    speaker=segment.speaker,
                    text=segment.text,
                    source_refs_json=segment.source_refs,
                    status="pending",
                )
            )
    await _touch(session, episode, progress=25, stage="متن پادکست آماده شد", status="generating_audio")

    # 2) Per-turn TTS with per-speaker voices (resumable: only pending segments).
    segments = list(
        (
            await session.scalars(
                select(PodcastSegment)
                .where(PodcastSegment.episode_id == episode.id)
                .order_by(PodcastSegment.position.asc())
            )
        ).all()
    )
    if not segments:
        await _fail(session, episode, "segments_missing", "هیچ نوبت گفتاری برای تولید صدا وجود ندارد.")
        return
    total = len(segments)
    for index, segment in enumerate(segments):
        fresh = await session.get(PodcastEpisode, episode.id)
        if fresh is None or fresh.status == "cancelled":
            episode.status = "cancelled"
            await session.flush()
            await session.commit()
            return
        if segment.status == "ready" and segment.audio_file_path and Path(segment.audio_file_path).is_file():
            continue
        episode_dir = PODCAST_ROOT / f"ep-{episode.id}"
        episode_dir.mkdir(parents=True, exist_ok=True)
        voice = _voice_for(episode, segment.speaker)
        try:
            piece_paths: list[Path] = []
            for piece_index, piece in enumerate(_split_for_tts(segment.text)):
                path = await _speech_for_piece(
                    session, user, episode, voice=voice, text=piece
                )
                piece_paths.append(path)
            segment_paths: list[Path] = []
            for piece_index, piece_path in enumerate(piece_paths):
                target = episode_dir / f"seg-{segment.position:04d}-{piece_index:03d}{piece_path.suffix}"
                if piece_path.resolve() != target.resolve():
                    shutil_copy(piece_path, target)
                segment_paths.append(target)
            if len(segment_paths) == 1:
                segment.audio_file_path = str(segment_paths[0])
            else:
                merged = episode_dir / f"seg-{segment.position:04d}-full.mp3"
                merged.parent.mkdir(parents=True, exist_ok=True)
                final_path, duration, _media = audio_assembly.assemble(
                    segment_paths, merged, workdir=episode_dir
                )
                segment.audio_file_path = str(final_path)
            segment.status = "ready"
            segment.duration_seconds = audio_assembly.measure_duration(Path(segment.audio_file_path))
        except HTTPException as error:
            segment.status = "failed"
            raise HTTPException(
                status_code=502,
                detail=f"تولید صوت نوبت {index + 1} ناموفق بود: {error.detail}",
            ) from error
        await _touch(
            session,
            episode,
            progress=30 + int(50 * (index + 1) / total),
            stage=f"تولید صوت: نوبت {index + 1} از {total}",
        )

    # 3) Assembly.
    await _touch(session, episode, progress=85, stage="ترکیب فایل‌های صوتی", status="assembling_audio")
    ready = [s for s in segments if s.status == "ready" and s.audio_file_path and Path(s.audio_file_path).is_file()]
    if not ready:
        await _fail(session, episode, "audio_missing", "هیچ قطعهٔ صوتی معتبری تولید نشد.")
        return
    episode_dir = PODCAST_ROOT / f"ep-{episode.id}"
    episode_dir.mkdir(parents=True, exist_ok=True)
    final_path, duration, media_type = await asyncio.to_thread(
        audio_assembly.assemble,
        [Path(s.audio_file_path) for s in ready],
        episode_dir / "episode.mp3",
    )
    episode.audio_file_path = str(final_path)
    episode.duration_seconds = duration
    episode.byte_size = final_path.stat().st_size

    # 4) Real transcript timestamps (measured, never invented).
    cursor = 0.0
    for segment in ready:
        seg_duration = segment.duration_seconds or 0.0
        segment.start_time = round(cursor, 2)
        segment.end_time = round(cursor + seg_duration, 2)
        cursor += seg_duration
    episode.transcript = build_transcript_text(ready)

    await _touch(session, episode, progress=100, stage="تکمیل", status="completed")
    episode.completed_at = datetime.now(timezone.utc)
    await session.flush()
    await session.commit()


def shutil_copy(source: Path, target: Path) -> None:
    import shutil

    shutil.copyfile(source, target)


def build_transcript_text(segments: list[PodcastSegment]) -> str:
    lines: list[str] = []
    for segment in segments:
        label = SPEAKER_LABELS.get(segment.speaker, segment.speaker)
        lines.append(f"**{label}:**\n{segment.text.strip()}")
    return "\n\n".join(lines)


async def cancel_episode(session: AsyncSession, user: User, episode: PodcastEpisode) -> None:
    if episode.status not in ("queued", "generating_script", "generating_audio", "assembling_audio"):
        raise HTTPException(status_code=422, detail="این پادکست قابل لغو نیست.")
    episode.status = "cancelled"
    episode.progress_stage = "لغو شد"
    episode.heartbeat_at = datetime.now(timezone.utc)
    await session.flush()


async def recover_stale_episodes(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Startup sweep: jobs whose worker died (no heartbeat) become retryable failures."""
    now = now or datetime.now(timezone.utc)
    threshold = now - timedelta(seconds=STALE_AFTER_SECONDS)
    rows = list(
        (
            await session.scalars(
                select(PodcastEpisode).where(
                    PodcastEpisode.status.in_(["generating_script", "generating_audio", "assembling_audio"]),
                    PodcastEpisode.heartbeat_at.is_not(None),
                    PodcastEpisode.heartbeat_at < threshold,
                )
            )
        ).all()
    )
    for episode in rows:
        episode.status = "failed"
        episode.error_code = "worker_lost"
        episode.error_detail = "پردازش پادکست نیمه‌کاره ماند (قطع Worker یا ری‌استارت سرور). می‌توانید دوباره تلاش کنید."
        episode.heartbeat_at = now
    if rows:
        await session.flush()
        await session.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Ask the hosts (grounded Q&A) + feedback
# ---------------------------------------------------------------------------


async def ask_hosts(
    session: AsyncSession,
    user: User,
    episode: PodcastEpisode,
    *,
    question: str,
) -> PodcastQuestion:
    snapshot = dict(episode.source_snapshot_json or {})
    sources = list(snapshot.get("sources") or [])
    script_segments = list((episode.script_json or {}).get("segments") or [])
    lines = [
        "شما گویندگان یک پادکست آموزشی هستید (بر اساس کتاب درسی رسمی ایران).",
        "به سؤال دانش‌آموز فقط بر اساس منابع و محتوای همین پادکست پاسخ بده؛ دانش بیرونی ممنوع است؛ "
        "اگر پاسخ در منابع نیست صادقانه بگو و راهنمایی مناسبی در چارچوب منابع بده.",
        "",
        "محتوای پادکست:",
    ]
    for segment in script_segments[:40]:
        speaker = SPEAKER_LABELS.get(str(segment.get("speaker")), str(segment.get("speaker")))
        lines.append(f"{speaker}: {str(segment.get('text', ''))[:600]}")
    lines.append("")
    lines.append("منابع معتبر:")
    for item in sources[:MAX_SOURCE_ITEMS]:
        lines.append(f"[منبع {item['index']}] ({item['citation']})\n{item['text']}")
    lines.append("")
    lines.append(f"سؤال دانش‌آموز: {question.strip()}")
    lines.append(
        "پاسخ را با لحن گفتاری دوستانه بنویس (حداکثر حدود ۱۵۰ کلمه) و اگر از منبع خاصی استفاده کردی "
        "شمارهٔ همان منبع را در پاسخ ذکر کن."
    )
    memory_context = await build_memory_context(session, user.id, episode.book_id)
    result, _blocks, _skill = await capability_runtime.run_capability_text(
        session=session,
        capability_key=CAPABILITY_KEY,
        feature_key=SCRIPT_FEATURE_KEY,
        user_text="\n".join(lines),
        user_id=user.id,
        user=user,
        book_id=episode.book_id,
        textbook_strict=True,
        citations=list(snapshot.get("citations") or []),
        rag_hit_count=len(sources),
        extra_system=memory_context or None,
    )
    answer = (result.content if isinstance(result.content, str) else str(result.content)).strip()[:4000]
    cited_indexes = sorted({int(match) for match in re.findall(r"\[منبع\s*(\d+)\]", answer) if int(match) <= len(sources)})
    citations = [
        {"index": item["index"], "citation": item["citation"]}
        for item in sources
        if item["index"] in cited_indexes
    ]
    question_row = PodcastQuestion(
        episode_id=episode.id,
        user_id=user.id,
        question=question.strip()[:1000],
        answer_md=answer,
        citations_json=citations,
    )
    session.add(question_row)
    await session.flush()
    return question_row


async def set_feedback(
    session: AsyncSession, user: User, episode: PodcastEpisode, *, liked: bool, reasons: list[str]
) -> PodcastFeedback:
    cleaned = [reason for reason in reasons if reason in FEEDBACK_REASONS]
    if not liked and not cleaned:
        raise HTTPException(status_code=422, detail="برای نپسندیدن، انتخاب علت لازم است.")
    if liked:
        cleaned = []
    existing = await session.scalar(
        select(PodcastFeedback).where(
            PodcastFeedback.episode_id == episode.id, PodcastFeedback.user_id == user.id
        )
    )
    if existing is None:
        existing = PodcastFeedback(
            episode_id=episode.id,
            user_id=user.id,
            liked=liked,
            reasons_json=cleaned,
        )
        session.add(existing)
    else:
        existing.liked = liked
        existing.reasons_json = cleaned
    await session.flush()
    return existing


__all__ = [
    "CAPABILITY_KEY",
    "FEEDBACK_REASONS",
    "FORMAT_LABELS",
    "LENGTH_LABELS",
    "MAX_CUSTOM_PROMPT_CHARS",
    "SCRIPT_FEATURE_KEY",
    "SPEAKER_LABELS",
    "SUPPORTED_LANGUAGES",
    "TTS_FEATURE_KEY",
    "ask_hosts",
    "build_script_prompt",
    "build_transcript_text",
    "cancel_episode",
    "create_episode",
    "delete_episode",
    "episode_detail",
    "get_owned_episode",
    "list_episodes",
    "load_podcast_config",
    "podcast_config",
    "process_episode",
    "recover_stale_episodes",
    "rename_episode",
    "require_podcast_enabled",
    "resolve_podcast_sources",
    "resolve_voices_and_model",
    "serialize_episode",
    "serialize_segment",
    "set_feedback",
    "validate_script",
]
