"""Student tutoring APIs: text, image, and voice questions (OTP-authenticated & token-metered)."""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import asyncio
import json
from dataclasses import dataclass

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import enforce_student_grade_level, require_student, resolve_book_scope
from app.core.llm_client import track_token_usage
from app.db.session import get_session
from app.models.auth import User, UserFile
from app.models.chat import ChatSession
from app.models.curriculum import Book, BookCurriculumLink, Grade
from app.services.account_service import (
    ensure_user_file_path,
    normalize_preferences,
    save_user_file,
    serialize_user_file,
)
from app.services.auth_billing_service import (
    get_or_init_billing_settings,
    record_and_deduct_usage,
)
from app.services.capability_service import check_capability_access
from app.services.quota_service import enforce_ai_quota
from app.services.search_normalize import search_key
from app.services.upload_guard import verify_audio
from app.services.multimodal_service import answer_audio_question, answer_image_question
from app.services.tutor_service import TutorMode, answer_from_textbook
from app.services.chat_stream import (
    StreamParams,
    get_stream_store,
    serialize_stream_event,
    start_stream,
    stop_stream,
)
from app.services.intent_router import route_intent
from app.services.multi_grade_rag import ScopeError, resolve_curriculum_book_ids
from app.services.tutor_turns import finish_turn_success

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tutor", tags=["tutor"])

# Feature keys so admins can route a different model per tutor mode (Phase 1).
TUTOR_MODE_FEATURES = {
    "tutor": "chat",
    "problem_solver": "solve",
    "question_designer": "quiz",
}

# Capability registry keys (Phase 2) for the same modes.
TUTOR_MODE_CAPABILITIES = {
    "tutor": "chat",
    "problem_solver": "solve",
    "question_designer": "quiz",
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_IMAGE_EDGE = 3000
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
AUDIO_MIME_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/webm",
    "audio/ogg",
    "audio/flac",
    "application/ogg",
}
AUDIO_MIME_BY_SUFFIX = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/m4a",
    ".mp4": "audio/mp4",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    # Single-book scope (Phase 1-3). Required unless `grade_numbers` is set.
    grade_number: int | None = Field(default=None, ge=1, le=12)
    major_code: str | None = Field(default=None, max_length=64)
    branch_code: str | None = Field(default=None, max_length=64)
    book_id: int | None = Field(default=None, gt=0)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: TutorMode = "tutor"
    chat_session_id: str | None = Field(default=None, max_length=64)
    # Phase 4: multi-grade Konkoor scope and Auto-Mode router.
    grade_numbers: list[int] | None = Field(default=None, max_length=3)
    book_ids: list[int] | None = Field(default=None, max_length=12)
    auto_mode: bool = False


class StreamRequest(AskRequest):
    regenerate_of: str | None = Field(default=None, max_length=64)


class ChatMessageItem(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)
    sources: list[dict[str, Any]] | None = None
    attachment: str | None = None


class CreateChatSessionRequest(BaseModel):
    book_id: int = Field(gt=0)
    grade_number: int = Field(ge=1, le=12)
    major_code: str | None = Field(default=None, max_length=64)
    branch_code: str | None = Field(default=None, max_length=64)
    mode: TutorMode = "tutor"
    title: str = Field(min_length=1, max_length=255)
    messages: list[ChatMessageItem] = Field(min_length=1, max_length=200)


class UpdateChatSessionRequest(BaseModel):
    mode: TutorMode | None = None
    branch_code: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    messages: list[ChatMessageItem] = Field(min_length=1, max_length=200)


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _serialize_chat_summary(
    chat: ChatSession, *, book_title: str | None = None
) -> dict[str, object]:
    return {
        "deleted_at": _utc_iso(chat.deleted_at),
        "id": chat.id,
        "title": chat.title,
        "book_id": chat.book_id,
        "book_title": book_title,
        "grade_number": chat.grade_number,
        "major_code": chat.major_code,
        "branch_code": getattr(chat, "branch_code", None),
        "mode": chat.mode,
        "message_count": len(chat.messages or []),
        "created_at": _utc_iso(chat.created_at),
        "updated_at": _utc_iso(chat.updated_at),
    }


async def _read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"file exceeds {max_bytes // (1024 * 1024)} MiB limit")
    if not data:
        raise HTTPException(status_code=422, detail="uploaded file is empty")
    return data


def _normalize_image(data: bytes, content_type: str) -> bytes:
    if content_type not in IMAGE_MIME_TYPES:
        raise HTTPException(status_code=415, detail="image must be JPEG, PNG, or WebP")
    try:
        with Image.open(io.BytesIO(data)) as image:
            expected_formats = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
            if image.format != expected_formats[content_type]:
                raise HTTPException(status_code=415, detail="image content does not match its media type")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise HTTPException(status_code=422, detail="uploaded image is invalid or unsafe") from error


def _provider_failure(error: Exception, *, operation: str) -> HTTPException:
    if isinstance(error, RuntimeError) and "SPEECH_TO_TEXT_MODEL" in str(error):
        return HTTPException(status_code=503, detail="speech-to-text model is not configured")
    if isinstance(error, RuntimeError) and "TUTOR_MODEL" in str(error):
        return HTTPException(status_code=503, detail="tutor model is not configured")
    logger.error(
        "%s request failed: %s",
        operation,
        type(error).__name__,
        exc_info=(type(error), error, error.__traceback__),
    )
    return HTTPException(status_code=503, detail=f"{operation} service is temporarily unavailable")


async def _maybe_store_tutor_attachment(
    session: AsyncSession,
    *,
    user: User,
    filename: str,
    content_bytes: bytes,
    mime_type: str,
    source_context: str,
    chat_session_id: str | None = None,
) -> UserFile | None:
    if not isinstance(user, User) or not isinstance(session, AsyncSession):
        return None
    prefs = normalize_preferences(getattr(user, "preferences", None))
    if not prefs["privacy"].get("store_uploaded_attachments", True):
        return None
    billing = await get_or_init_billing_settings(session)
    return await save_user_file(
        session,
        user=user,
        billing=billing,
        filename=filename,
        content_bytes=content_bytes,
        mime_type=mime_type,
        source_context=source_context,
        chat_session_id=chat_session_id,
        enforce_quota=True,
    )


async def _finalize_usage(
    session: AsyncSession,
    *,
    user: User,
    action: str,
    book_id: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    result: dict[str, Any],
) -> None:
    if total_tokens > 0:
        usage_payload = await record_and_deduct_usage(
            session,
            user=user,
            action=action,
            book_id=book_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        result["usage"] = usage_payload
    else:
        if isinstance(session, AsyncSession):
            await session.commit()
        result["usage"] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_toman": 0,
            "tokens_remaining": user.tokens_remaining,
        }


async def _resolve_request_scope(
    session: AsyncSession,
    body: AskRequest,
    *,
    current_user: User,
) -> tuple[Any, int | None, str | None, list[int] | None, list[int] | None]:
    """Return (book, grade_number, major_code, grade_numbers, book_ids).

    Single-book requests keep the strict Phase 1-3 checks. Multi-grade requests
    validate the grade/book combination up front so bad input is a 422.
    """
    if body.grade_numbers:
        grades = sorted(set(body.grade_numbers))
        if body.book_id is None or not body.branch_code:
            raise HTTPException(
                status_code=422,
                detail="multi-grade retrieval requires an anchor book and an explicit education branch",
            )
        anchor_book = await session.get(Book, body.book_id)
        anchor_grade = (
            await session.get(Grade, anchor_book.grade_id) if anchor_book is not None else None
        )
        if anchor_book is None or anchor_grade is None:
            raise HTTPException(status_code=404, detail="anchor textbook not found")
        if anchor_grade.number not in grades:
            raise HTTPException(
                status_code=422,
                detail="the anchor textbook grade must be included in grade_numbers",
            )
        # The anchor book and every cross-grade citation must stay at or below
        # the learner's current grade. When no grade is on the profile, the
        # selected anchor textbook is the conservative upper bound.
        enforce_student_grade_level(current_user, anchor_grade.number)
        learner_grade = getattr(current_user, "grade_level", None) or anchor_grade.number
        if any(grade > learner_grade for grade in grades):
            raise HTTPException(
                status_code=422,
                detail="multi-grade retrieval cannot include textbooks above the student's current grade",
            )
        _resolved_book, _resolved_grade, field_code = await resolve_book_scope(
            session,
            book_id=anchor_book.id,
            grade_number=anchor_grade.number,
            major_code=body.major_code,
            branch_code=body.branch_code,
        )
        subject_ids = list(
            (
                await session.scalars(
                    select(BookCurriculumLink.subject_id).where(
                        BookCurriculumLink.book_id == anchor_book.id,
                        BookCurriculumLink.subject_id.is_not(None),
                    )
                )
            ).all()
        )
        if not subject_ids:
            raise HTTPException(
                status_code=422,
                detail=(
                    "the anchor textbook must be mapped to an official subject before "
                    "multi-grade retrieval can be used"
                ),
            )
        if body.book_ids is not None and anchor_book.id not in body.book_ids:
            raise HTTPException(
                status_code=422,
                detail="book_ids must include the selected anchor textbook",
            )
        try:
            authorized_book_ids = await resolve_curriculum_book_ids(
                session,
                grade_numbers=grades,
                branch_code=body.branch_code,
                field_code=field_code,
                academic_year_id=anchor_book.academic_year_id,
                subject_ids=subject_ids,
                requested_book_ids=body.book_ids,
            )
        except ScopeError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if anchor_book.id not in authorized_book_ids:
            raise HTTPException(
                status_code=422,
                detail="the anchor textbook is outside the selected curriculum scope",
            )
        return None, None, field_code, grades, authorized_book_ids
    if body.grade_number is None or body.book_id is None:
        raise HTTPException(
            status_code=422,
            detail="grade_number and book_id are required unless grade_numbers is set",
        )
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=body.book_id,
        grade_number=body.grade_number,
        major_code=body.major_code,
        branch_code=body.branch_code,
    )
    enforce_student_grade_level(current_user, grade.number)
    return book, grade.number, major_code, None, None


@router.post("/ask")
async def ask_tutor(
    body: AskRequest,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    book, grade_number, major_code, grade_numbers, book_ids = await _resolve_request_scope(
        session, body, current_user=current_user
    )
    mode: TutorMode = body.mode
    decision = None
    if body.auto_mode:
        # Gate quota before any router model call, then route, then check the chosen mode.
        await check_capability_access(session, "chat", current_user)
        await enforce_ai_quota(session, user=current_user, feature_key="chat")
        decision = await route_intent(
            query=body.query,
            user_id=current_user.id,
            session_id=body.chat_session_id,
            db_session=session,
        )
        mode = decision.mode  # type: ignore[assignment]
        await check_capability_access(session, TUTOR_MODE_CAPABILITIES.get(mode, "chat"), current_user)
    else:
        await check_capability_access(
            session, TUTOR_MODE_CAPABILITIES.get(body.mode, "chat"), current_user
        )
        await enforce_ai_quota(
            session,
            user=current_user,
            feature_key=TUTOR_MODE_FEATURES.get(body.mode, "chat"),
        )
    try:
        with track_token_usage() as usage:
            result = await answer_from_textbook(
                query=body.query,
                grade_number=grade_number,
                major_code=major_code,
                book_id=book.id if book is not None else None,
                top_k=body.top_k,
                mode=mode,
                user_id=current_user.id,
                session_id=body.chat_session_id,
                db_session=session,
                grade_numbers=grade_numbers,
                book_ids=book_ids,
            )
    except Exception as error:  # noqa: BLE001 - do not expose provider details
        raise _provider_failure(error, operation="tutor") from error

    result["mode"] = mode
    if decision is not None:
        result["router"] = decision.to_payload()
    await finish_turn_success(
        session,
        user_id=current_user.id,
        params=_TurnParams(
            query=body.query,
            book_id=book.id if book is not None else None,
            chat_session_id=body.chat_session_id,
        ),
        mode=mode,
        result=result,
        usage=usage,
    )
    return result


@dataclass(frozen=True)
class _TurnParams:
    query: str
    book_id: int | None
    chat_session_id: str | None


@router.post("/ask-image")
async def ask_tutor_with_image(
    image: UploadFile = File(...),
    grade_number: int = Form(...),
    book_id: int = Form(...),
    major_code: str | None = Form(None),
    branch_code: str | None = Form(None),
    top_k: int = Form(5),
    mode: TutorMode = Form("tutor"),
    chat_session_id: str | None = Form(None),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    if not 1 <= grade_number <= 12 or book_id <= 0 or not 1 <= top_k <= 20:
        raise HTTPException(status_code=422, detail="invalid grade, book, or result limit")
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=book_id,
        grade_number=grade_number,
        major_code=major_code,
        branch_code=branch_code,
    )
    enforce_student_grade_level(current_user, grade.number)
    await check_capability_access(session, "multimodal", current_user)
    await enforce_ai_quota(session, user=current_user, feature_key="vision_ocr")
    image_bytes = await _read_upload_limited(image, MAX_IMAGE_BYTES)
    image_bytes = _normalize_image(image_bytes, image.content_type or "")
    saved_file = await _maybe_store_tutor_attachment(
        session,
        user=current_user,
        filename=Path(image.filename or "question.png").stem + ".png",
        content_bytes=image_bytes,
        mime_type="image/png",
        source_context="tutor_image",
        chat_session_id=chat_session_id,
    )
    try:
        with track_token_usage() as usage:
            result = await answer_image_question(
                image_bytes=image_bytes,
                image_mime_type="image/png",
                grade_number=grade.number,
                major_code=major_code,
                book_id=book.id,
                top_k=top_k,
                mode=mode,
                user_id=current_user.id,
                session_id=chat_session_id,
                db_session=session,
            )
    except Exception as error:  # noqa: BLE001 - do not expose provider details
        if saved_file is not None:
            try:
                ensure_user_file_path(current_user.id, saved_file.storage_path).unlink(missing_ok=True)
            except HTTPException:
                pass
            await session.rollback()
        raise _provider_failure(error, operation="image tutor") from error

    await _finalize_usage(
        session,
        user=current_user,
        action="tutor_image",
        book_id=book.id,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        result=result,
    )
    if saved_file is not None:
        result["saved_file"] = serialize_user_file(saved_file)
    return result


@router.post("/ask-audio")
async def ask_tutor_with_audio(
    audio: UploadFile = File(...),
    grade_number: int = Form(...),
    book_id: int = Form(...),
    major_code: str | None = Form(None),
    branch_code: str | None = Form(None),
    top_k: int = Form(5),
    mode: TutorMode = Form("tutor"),
    chat_session_id: str | None = Form(None),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    if not 1 <= grade_number <= 12 or book_id <= 0 or not 1 <= top_k <= 20:
        raise HTTPException(status_code=422, detail="invalid grade, book, or result limit")
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=book_id,
        grade_number=grade_number,
        major_code=major_code,
        branch_code=branch_code,
    )
    enforce_student_grade_level(current_user, grade.number)
    await check_capability_access(session, "multimodal", current_user)
    await enforce_ai_quota(session, user=current_user, feature_key="stt")
    filename = Path(audio.filename or "question.webm").name
    content_type = (audio.content_type or "").lower()
    if content_type in {"", "application/octet-stream"}:
        content_type = AUDIO_MIME_BY_SUFFIX.get(Path(filename).suffix.lower(), "")
    if content_type not in AUDIO_MIME_TYPES:
        raise HTTPException(status_code=415, detail="unsupported audio format")
    audio_bytes = await _read_upload_limited(audio, MAX_AUDIO_BYTES)
    verify_audio(content_type, audio_bytes)
    saved_file = await _maybe_store_tutor_attachment(
        session,
        user=current_user,
        filename=filename,
        content_bytes=audio_bytes,
        mime_type=content_type,
        source_context="tutor_audio",
        chat_session_id=chat_session_id,
    )
    try:
        with track_token_usage() as usage:
            result = await answer_audio_question(
                audio_bytes=audio_bytes,
                filename=filename,
                content_type=content_type,
                grade_number=grade.number,
                major_code=major_code,
                book_id=book.id,
                top_k=top_k,
                mode=mode,
                user_id=current_user.id,
                session_id=chat_session_id,
                db_session=session,
            )
    except Exception as error:  # noqa: BLE001 - do not expose provider details
        if saved_file is not None:
            try:
                ensure_user_file_path(current_user.id, saved_file.storage_path).unlink(missing_ok=True)
            except HTTPException:
                pass
            await session.rollback()
        raise _provider_failure(error, operation="voice tutor") from error

    await _finalize_usage(
        session,
        user=current_user,
        action="tutor_audio",
        book_id=book.id,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        result=result,
    )
    if saved_file is not None:
        result["saved_file"] = serialize_user_file(saved_file)
    return result


def _active_chat_filter(current_user: User):
    return (ChatSession.user_id == current_user.id, ChatSession.deleted_at.is_(None))


@router.get("/sessions")
async def list_chat_sessions(
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    rows = (
        await session.execute(
            select(ChatSession, Book.title)
            .outerjoin(Book, ChatSession.book_id == Book.id)
            .where(*_active_chat_filter(current_user))
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [_serialize_chat_summary(chat, book_title=book_title) for chat, book_title in rows]


def _snippet(text: str, needle: str, radius: int = 60) -> str:
    index = text.casefold().find(needle.casefold())
    if index < 0:
        return text[: radius * 2]
    start = max(0, index - radius)
    return ("…" if start > 0 else "") + text[start : index + len(needle) + radius] + "…"


@router.get("/sessions/search")
async def search_chat_sessions(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Search titles and message bodies of active (not deleted) chats."""
    needle = q.strip()
    if not needle:
        raise HTTPException(status_code=422, detail="q must not be blank")
    rows = (
        await session.execute(
            select(ChatSession, Book.title)
            .outerjoin(Book, ChatSession.book_id == Book.id)
            .where(*_active_chat_filter(current_user))
            .order_by(ChatSession.updated_at.desc())
            .limit(300)
        )
    ).all()
    results: list[dict[str, object]] = []
    for chat, book_title in rows:
        messages = chat.messages or []
        hit = None
        if search_key(needle) in search_key(chat.title):
            hit = {"message_id": None, "role": None, "snippet": chat.title}
        else:
            for message in messages:
                content = str(message.get("content") or "")
                if search_key(needle) in search_key(content):
                    hit = {
                        "message_id": message.get("id"),
                        "role": message.get("role"),
                        "snippet": _snippet(content, needle),
                    }
                    break
        if hit is not None:
            results.append({**_serialize_chat_summary(chat, book_title=book_title), "match": hit})
        if len(results) >= limit:
            break
    return {"query": needle, "count": len(results), "results": results}


@router.get("/sessions/trash")
async def list_trashed_chat_sessions(
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    rows = (
        await session.execute(
            select(ChatSession, Book.title)
            .outerjoin(Book, ChatSession.book_id == Book.id)
            .where(ChatSession.user_id == current_user.id, ChatSession.deleted_at.is_not(None))
            .order_by(ChatSession.deleted_at.desc())
            .limit(100)
        )
    ).all()
    return [_serialize_chat_summary(chat, book_title=book_title) for chat, book_title in rows]


@router.post("/sessions")
async def create_chat_session(
    body: CreateChatSessionRequest,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    book, grade, major_code = await resolve_book_scope(
        session,
        book_id=body.book_id,
        grade_number=body.grade_number,
        major_code=body.major_code,
        branch_code=body.branch_code,
    )
    enforce_student_grade_level(current_user, grade.number)
    now = datetime.now(timezone.utc)
    chat = ChatSession(
        book_id=book.id,
        user_id=current_user.id,
        grade_number=grade.number,
        major_code=major_code or "general",
        branch_code=body.branch_code,
        mode=body.mode,
        title=body.title.strip()[:255] or "گفت‌وگو با معلم",
        messages=[item.model_dump() for item in body.messages],
        created_at=now,
        updated_at=now,
    )
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    return {**_serialize_chat_summary(chat, book_title=book.title), "messages": chat.messages}


async def _owned_chat(
    session: AsyncSession, user: User, session_id: str, *, trashed: bool | None
) -> ChatSession:
    """Load a chat owned by `user`. trashed=False: active only; True: trash only; None: any."""
    chat = await session.scalar(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
    )
    if chat is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    if trashed is False and chat.deleted_at is not None:
        raise HTTPException(status_code=404, detail="chat session not found")
    if trashed is True and chat.deleted_at is None:
        raise HTTPException(status_code=409, detail="chat session is not in the recycle bin")
    return chat


@router.get("/sessions/{session_id}")
async def get_chat_session(
    session_id: str,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    row = (
        await session.execute(
            select(ChatSession, Book.title)
            .outerjoin(Book, ChatSession.book_id == Book.id)
            .where(
                ChatSession.id == session_id,
                ChatSession.user_id == current_user.id,
                ChatSession.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    chat, book_title = row
    return {**_serialize_chat_summary(chat, book_title=book_title), "messages": chat.messages}


@router.put("/sessions/{session_id}")
async def update_chat_session(
    session_id: str,
    body: UpdateChatSessionRequest,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    chat = await _owned_chat(session, current_user, session_id, trashed=False)
    if body.title is not None:
        chat.title = body.title.strip()[:255] or chat.title
    if body.mode is not None:
        chat.mode = body.mode
    if body.branch_code is not None:
        _book, chat_grade, resolved_major = await resolve_book_scope(
            session,
            book_id=chat.book_id,
            grade_number=chat.grade_number,
            major_code=chat.major_code,
            branch_code=body.branch_code,
        )
        enforce_student_grade_level(current_user, chat_grade.number)
        chat.branch_code = body.branch_code
        chat.major_code = resolved_major or "general"
    chat.messages = [item.model_dump() for item in body.messages]
    chat.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(chat)
    book = await session.get(Book, chat.book_id)
    return {
        **_serialize_chat_summary(chat, book_title=book.title if book else None),
        "messages": chat.messages,
    }


@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Soft delete: the chat moves to the Recycle Bin and can be restored."""
    chat = await _owned_chat(session, current_user, session_id, trashed=False)
    chat.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    return {"deleted": True, "soft": True, "id": session_id}


@router.post("/sessions/{session_id}/restore")
async def restore_chat_session(
    session_id: str,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    chat = await _owned_chat(session, current_user, session_id, trashed=True)
    chat.deleted_at = None
    chat.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(chat)
    book = await session.get(Book, chat.book_id)
    return {
        **_serialize_chat_summary(chat, book_title=book.title if book else None),
        "messages": chat.messages,
    }


@router.delete("/sessions/{session_id}/permanent")
async def purge_chat_session(
    session_id: str,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Hard delete, allowed only for chats already in the Recycle Bin."""
    chat = await _owned_chat(session, current_user, session_id, trashed=True)
    await session.delete(chat)
    await session.commit()
    return {"deleted": True, "soft": False, "id": session_id}


# ---------------------------------------------------------------------------
# Phase 4: recoverable streaming (SSE with stream_id + cursor, Stop, Regenerate)
# ---------------------------------------------------------------------------
_STREAM_POLL_SECONDS = 0.1


@router.post("/stream")
async def start_tutor_stream(
    body: StreamRequest,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Start a generation. Regenerate = call again with `regenerate_of` set."""
    book, grade_number, major_code, grade_numbers, book_ids = await _resolve_request_scope(
        session, body, current_user=current_user
    )
    if body.auto_mode:
        await check_capability_access(session, "chat", current_user)
        await enforce_ai_quota(session, user=current_user, feature_key="chat")
    else:
        await check_capability_access(
            session, TUTOR_MODE_CAPABILITIES.get(body.mode, "chat"), current_user
        )
        await enforce_ai_quota(
            session, user=current_user, feature_key=TUTOR_MODE_FEATURES.get(body.mode, "chat")
        )
    # Release the request transaction; the background run owns its own session.
    await session.commit()
    stream_id = await start_stream(
        StreamParams(
            user_id=current_user.id,
            query=body.query,
            mode=body.mode,
            auto_mode=body.auto_mode,
            grade_number=grade_number,
            major_code=major_code,
            book_id=book.id if book is not None else None,
            top_k=body.top_k,
            chat_session_id=body.chat_session_id,
            grade_numbers=grade_numbers,
            book_ids=book_ids,
            regenerate_of=body.regenerate_of,
        )
    )
    return {"stream_id": stream_id, "status": "running", "cursor": 0}


async def _owned_stream_meta(stream_id: str, user: User) -> dict[str, Any]:
    store = await get_stream_store()
    meta = await store.get_meta(stream_id)
    if meta is None or meta.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="stream not found")
    return meta


@router.get("/stream/{stream_id}")
async def read_tutor_stream(
    stream_id: str,
    cursor: int = Query(default=0, ge=0),
    current_user: User = Depends(require_student),
) -> StreamingResponse:
    """SSE: `chunk` events (id = next cursor) then one `end` event.

    Reconnect with `?cursor=<last id>` to resume without duplicating text.
    """
    await _owned_stream_meta(stream_id, current_user)
    store = await get_stream_store()

    async def events():
        position = cursor
        while True:
            status, meta, chunks = await store.read(stream_id, position)
            if status is None:
                yield serialize_stream_event("error", {"detail": "stream expired"})
                return
            for text in chunks:
                position += 1
                yield serialize_stream_event("chunk", {"index": position - 1, "text": text}, position)
            if status in ("done", "stopped", "error") and not chunks:
                payload: dict[str, Any] = {"status": status, "cursor": position}
                if status == "done":
                    payload["final"] = meta.get("final")
                yield serialize_stream_event("end", payload)
                return
            await asyncio.sleep(_STREAM_POLL_SECONDS)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/stream/{stream_id}/stop")
async def stop_tutor_stream(
    stream_id: str,
    current_user: User = Depends(require_student),
) -> dict[str, object]:
    meta = await _owned_stream_meta(stream_id, current_user)
    if meta.get("status") != "running":
        return {"stream_id": stream_id, "status": meta.get("status")}
    await stop_stream(stream_id)
    return {"stream_id": stream_id, "status": "stop_requested"}
