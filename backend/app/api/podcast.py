"""Phase 9 podcast student API — Audio-Overview-style educational episodes.

Every route is gated by the `audio_podcast` capability and strict episode
ownership. Audio files live in the private storage dir and are streamed only
through authenticated endpoints (with HTTP Range/seek support via FileResponse).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_student
from app.db.session import get_session
from app.models.auth import User
from app.models.curriculum import Book
from app.services import podcast_service as ps
from app.services.capability_service import require_capability_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/podcasts", tags=["podcast"])

_job_tasks: set[asyncio.Task] = set()


def schedule_job(episode_id: int) -> None:
    """Fire the in-process worker for this episode (idempotent via DB claim)."""
    task = asyncio.get_running_loop().create_task(ps.process_episode(episode_id))
    _job_tasks.add(task)
    task.add_done_callback(_job_tasks.discard)


class PodcastCreateBody(BaseModel):
    book_id: int = Field(gt=0)
    format: Literal["deep_dive", "brief", "critique", "debate"] = "deep_dive"
    language: str = Field(default="fa", min_length=2, max_length=8)
    length: Literal["short", "standard", "long"] = "standard"
    custom_prompt: str = Field(default="", max_length=ps.MAX_CUSTOM_PROMPT_CHARS)
    chapter_numbers: list[int] = Field(default_factory=list, max_length=12)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    include_notebook: bool = False
    include_living_book: bool = False


class PodcastRenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class AskHostsBody(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class FeedbackBody(BaseModel):
    liked: bool
    reasons: list[str] = Field(default_factory=list, max_length=8)


class RegenerateBody(BaseModel):
    format: Literal["deep_dive", "brief", "critique", "debate"] | None = None
    language: str | None = Field(default=None, min_length=2, max_length=8)
    length: Literal["short", "standard", "long"] | None = None
    custom_prompt: str | None = Field(default=None, max_length=ps.MAX_CUSTOM_PROMPT_CHARS)


@router.get("/config")
async def get_podcast_config(
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ps.require_podcast_enabled(session, current_user)
    audio = await ps.resolve_voices_and_model(session, "deep_dive")
    return {
        "formats": [
            {"key": key, "label": label}
            for key, label in ps.FORMAT_LABELS.items()
        ],
        "languages": [
            {"code": code, "label": label}
            for code, label in ps.SUPPORTED_LANGUAGES.items()
            if code in audio["languages"]
        ],
        "lengths": [
            {"key": key, "label": ps.LENGTH_LABELS[key], "target_minutes": audio["length_targets"][key]}
            for key in ("short", "standard", "long")
        ],
        "dual_voice_available": not audio["single_speaker_mode"],
        "single_speaker_mode": audio["single_speaker_mode"],
        "max_custom_prompt_chars": ps.MAX_CUSTOM_PROMPT_CHARS,
        "supported_languages_note": "فقط زبان‌هایی که مدل صوتی واقعاً پشتیبانی کند نمایش داده می‌شوند.",
    }


@router.post("", status_code=202)
async def create_podcast(
    body: PodcastCreateBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ps.require_podcast_enabled(session, current_user)
    book = await session.get(Book, body.book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="کتاب یافت نشد.")
    episode = await ps.create_episode(
        session,
        current_user,
        book=book,
        format=body.format,
        language=body.language,
        length=body.length,
        custom_prompt=body.custom_prompt,
        chapter_numbers=body.chapter_numbers,
        page_start=body.page_start,
        page_end=body.page_end,
        include_notebook=body.include_notebook,
        include_living_book=body.include_living_book,
    )
    await session.commit()
    schedule_job(episode.id)
    return {"episode_id": episode.id, "status": episode.status, "progress": episode.progress}


@router.get("")
async def list_podcasts(
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ps.require_podcast_enabled(session, current_user)
    return {"items": await ps.list_episodes(session, current_user)}


@router.get("/{episode_id}")
async def get_podcast(
    episode_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    detail = await ps.episode_detail(session, current_user, episode)
    await session.commit()
    return detail


@router.get("/{episode_id}/status")
async def get_podcast_status(
    episode_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    await session.commit()
    return {
        "episode_id": episode.id,
        "status": episode.status,
        "progress": episode.progress,
        "progress_stage": episode.progress_stage,
        "error_code": episode.error_code,
        "error_detail": episode.error_detail if episode.status == "failed" else None,
        "has_audio": bool(episode.audio_file_path),
        "duration_seconds": episode.duration_seconds,
    }


def _episode_media_type(path: Path) -> str:
    return "audio/wav" if path.suffix == ".wav" else "audio/mpeg"


@router.get("/{episode_id}/audio")
async def stream_podcast_audio(
    episode_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    if not episode.audio_file_path or not Path(episode.audio_file_path).is_file():
        raise HTTPException(status_code=404, detail="فایل صوتی این پادکست هنوز آماده نیست.")
    path = Path(episode.audio_file_path)
    # Starlette's FileResponse serves HTTP Range requests for seeking.
    return FileResponse(path, media_type=_episode_media_type(path), filename=f"podcast-{episode.id}{path.suffix}")


@router.get("/{episode_id}/download")
async def download_podcast(
    episode_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    if not episode.audio_file_path or not Path(episode.audio_file_path).is_file():
        raise HTTPException(status_code=404, detail="فایل صوتی این پادکست هنوز آماده نیست.")
    path = Path(episode.audio_file_path)
    filename = f"darsyar-podcast-{episode.id}{path.suffix}"
    return FileResponse(
        path,
        media_type=_episode_media_type(path),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{episode_id}/transcript")
async def get_transcript(
    episode_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    await session.commit()
    return {
        "episode_id": episode.id,
        "title": episode.title,
        "transcript": episode.transcript or "",
        "status": episode.status,
    }


@router.post("/{episode_id}/questions", status_code=201)
async def ask_hosts(
    episode_id: int,
    body: AskHostsBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    if episode.status != "completed":
        raise HTTPException(status_code=422, detail="پرسش از گویندگان پس از تکمیل پادکست فعال می‌شود.")
    question = await ps.ask_hosts(session, current_user, episode, question=body.question)
    await session.commit()
    return {
        "id": question.id,
        "question": question.question,
        "answer_md": question.answer_md,
        "citations": list(question.citations_json or []),
    }


@router.post("/{episode_id}/feedback")
async def set_feedback(
    episode_id: int,
    body: FeedbackBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    feedback = await ps.set_feedback(
        session, current_user, episode, liked=body.liked, reasons=body.reasons
    )
    await session.commit()
    return {"liked": feedback.liked, "reasons": list(feedback.reasons_json or [])}


@router.patch("/{episode_id}")
async def rename_podcast(
    episode_id: int,
    body: PodcastRenameBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    await ps.rename_episode(session, current_user, episode, body.title)
    await session.commit()
    return {"id": episode.id, "title": episode.title}


@router.delete("/{episode_id}", status_code=204)
async def delete_podcast(
    episode_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    await ps.delete_episode(session, current_user, episode)
    await session.commit()
    return Response(status_code=204)


@router.post("/{episode_id}/cancel")
async def cancel_podcast(
    episode_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    await ps.cancel_episode(session, current_user, episode)
    await session.commit()
    return {"id": episode.id, "status": episode.status}


@router.post("/{episode_id}/retry")
async def retry_podcast(
    episode_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Resume a failed/cancelled job; finished audio segments are reused as-is."""
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    if episode.status not in ("failed", "cancelled"):
        raise HTTPException(status_code=422, detail="فقط پادکست ناموفق یا لغوشده قابل تلاش مجدد است.")
    episode.status = "queued"
    episode.progress = 0
    episode.progress_stage = "در صف تولید"
    episode.error_code = None
    episode.error_detail = None
    episode.heartbeat_at = None
    await session.commit()
    schedule_job(episode.id)
    return {"episode_id": episode.id, "status": episode.status, "progress": episode.progress}


@router.post("/{episode_id}/regenerate", status_code=202)
async def regenerate_podcast(
    episode_id: int,
    body: RegenerateBody | None = None,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a NEW episode with (optionally adjusted) same settings; the old one stays."""
    await ps.require_podcast_enabled(session, current_user)
    episode = await ps.get_owned_episode(session, current_user, episode_id)
    body = body or RegenerateBody()
    snapshot = dict(episode.source_snapshot_json or {})
    book = await session.get(Book, episode.book_id) if episode.book_id else None
    if book is None:
        raise HTTPException(status_code=422, detail="منبع این پادکست دیگر در دسترس نیست.")
    new_episode = await ps.create_episode(
        session,
        current_user,
        book=book,
        format=body.format or episode.format,
        language=body.language or episode.language,
        length=body.length or episode.length,
        custom_prompt=body.custom_prompt if body.custom_prompt is not None else episode.custom_prompt,
        chapter_numbers=list(snapshot.get("chapters") or []),
        page_start=snapshot.get("page_start"),
        page_end=snapshot.get("page_end"),
        include_notebook=bool(snapshot.get("include_notebook")),
        include_living_book=bool(snapshot.get("include_living_book")),
    )
    settings = dict(new_episode.generation_settings_json or {})
    settings["regenerated_from"] = episode.id
    new_episode.generation_settings_json = settings
    await session.commit()
    schedule_job(new_episode.id)
    return {"episode_id": new_episode.id, "status": new_episode.status, "progress": new_episode.progress}
