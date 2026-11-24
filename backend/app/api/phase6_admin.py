"""Phase 6 admin glass box: Living Book cache (with rejections) and TTS audio cache."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.db.session import get_session
from app.models.phase6 import AudioCacheEntry, LivingBookCache

router = APIRouter(prefix="/api/v1/admin/phase6", tags=["phase6-admin"], dependencies=[Depends(require_admin)])


@router.get("/living-book")
async def list_living_book_cache(
    book_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(LivingBookCache).order_by(LivingBookCache.created_at.desc(), LivingBookCache.id.desc()).limit(limit)
    if book_id is not None:
        stmt = stmt.where(LivingBookCache.book_id == book_id)
    rows = (await session.scalars(stmt)).all()
    return {
        "items": [
            {
                "id": row.id,
                "book_id": row.book_id,
                "chapter_number": row.chapter_number,
                "chapter_title": row.chapter_title,
                "content_hash": row.content_hash,
                "model_name": row.model_name,
                "hit_count": row.hit_count,
                "block_count": len(row.blocks_json or []),
                "rejected": row.rejected_json or [],
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.get("/audio-cache")
async def list_audio_cache(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = (
        await session.scalars(
            select(AudioCacheEntry).order_by(AudioCacheEntry.created_at.desc(), AudioCacheEntry.id.desc()).limit(limit)
        )
    ).all()
    total_bytes = await session.scalar(select(func.coalesce(func.sum(AudioCacheEntry.byte_size), 0)))
    return {
        "total_bytes": int(total_bytes or 0),
        "items": [
            {
                "id": row.id,
                "cache_key": row.cache_key[:16],
                "voice": row.voice,
                "model_name": row.model_name,
                "text_chars": row.text_chars,
                "byte_size": row.byte_size,
                "hit_count": row.hit_count,
                "book_id": row.book_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }
