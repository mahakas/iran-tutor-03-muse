"""Phase 6 selected-text TTS with a content-addressed audio cache.

Flow: capability access check -> cache lookup by `sha256(model | voice | text)` ->
on hit: no provider call, no quota charge, audited as `tts_cache_hit` ->
on miss: `capability_runtime.run_capability_speech` (capability + quota gate ->
ai_gateway -> ai_audit_logs) and the file is stored under `storage/tts_cache/`.
Students never choose the voice or model; both come from admin configuration.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.auth import User
from app.models.curriculum import Book
from app.models.phase6 import AudioCacheEntry
from app.services import capability_runtime
from app.services.ai_gateway import record_decision_audit
from app.services.ai_provider_service import resolve_feature_route
from app.services.capability_service import require_capability_enabled

CAPABILITY_KEY = "audio_tts"
MAX_TTS_CHARS = 4000
MIN_TTS_CHARS = 2
TTS_ROOT = Path(__file__).resolve().parents[2] / "storage" / "tts_cache"


@dataclass(frozen=True)
class SpeechResult:
    path: Path
    media_type: str
    cache_key: str
    cache_hit: bool


def clean_text(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) < MIN_TTS_CHARS:
        raise HTTPException(status_code=422, detail="متن برای روخوانی خیلی کوتاه است.")
    if len(cleaned) > MAX_TTS_CHARS:
        raise HTTPException(status_code=422, detail=f"متن برای روخوانی بیش از {MAX_TTS_CHARS} نویسه است.")
    return cleaned


def cache_key(model: str, voice: str, text: str) -> str:
    return hashlib.sha256(f"{model}\x1f{voice}\x1f{text}".encode("utf-8")).hexdigest()


def media_type_for(path: Path) -> str:
    return "audio/wav" if path.suffix == ".wav" else "audio/mpeg"


async def _voice_and_model(session: AsyncSession) -> tuple[str, str]:
    settings = get_settings()
    from app.services.capability_service import get_capability

    capability = await get_capability(session, CAPABILITY_KEY)
    config = dict(capability.config_json or {}) if capability is not None else {}
    voice = str(config.get("voice") or settings.speech_default_voice or "").strip()
    route = await resolve_feature_route(session, CAPABILITY_KEY)
    model = (route.model_name if route and route.configured else None) or settings.speech_synthesis_model or ""
    if not voice and not settings.demo_mode:
        raise HTTPException(status_code=503, detail="صدای روخوانی توسط مدیر تنظیم نشده است.")
    return voice or "demo", model


async def speak(
    session: AsyncSession,
    user: User,
    *,
    text: str,
    book_id: int | None = None,
) -> SpeechResult:
    cleaned = clean_text(text)
    if book_id is not None and await session.get(Book, book_id) is None:
        raise HTTPException(status_code=404, detail="کتاب یافت نشد.")
    await require_capability_enabled(session, CAPABILITY_KEY, user)
    voice, model = await _voice_and_model(session)
    key = cache_key(model, voice, cleaned)

    entry = await session.scalar(select(AudioCacheEntry).where(AudioCacheEntry.cache_key == key))
    if entry is not None and Path(entry.file_path).is_file():
        entry.hit_count = (entry.hit_count or 0) + 1
        entry.last_used_at = datetime.now(timezone.utc)
        await record_decision_audit(
            feature_key=CAPABILITY_KEY,
            user_id=user.id,
            session_id=None,
            request_text=f"tts cache hit chars={len(cleaned)}",
            decision={"cache": "hit", "cache_key": key[:16], "chars": len(cleaned), "voice": voice},
            flag_reason="tts_cache_hit",
            session=session,
        )
        await session.commit()
        path = Path(entry.file_path)
        return SpeechResult(path=path, media_type=media_type_for(path), cache_key=key, cache_hit=True)

    audio, result = await capability_runtime.run_capability_speech(
        session=session,
        capability_key=CAPABILITY_KEY,
        text=cleaned,
        voice=voice,
        user_id=user.id,
        book_id=book_id,
        user=user,
        enforce=True,
    )
    extension = ".wav" if audio[:4] == b"RIFF" else ".mp3"
    path = TTS_ROOT / key[:2] / f"{key}{extension}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    session.add(
        AudioCacheEntry(
            cache_key=key,
            user_id=user.id,
            book_id=book_id,
            voice=voice,
            model_name=result.model_name or model or "",
            text_chars=len(cleaned),
            byte_size=len(audio),
            file_path=str(path),
            hit_count=0,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent request stored the same text first. Both wrote the same
        # content-addressed path, so the file stays; only the duplicate row is dropped.
        await session.rollback()
    return SpeechResult(path=path, media_type=media_type_for(path), cache_key=key, cache_hit=False)
