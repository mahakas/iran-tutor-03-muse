"""Phase 9 admin glass box for podcasts — quality/cost monitoring, no private content.

Shows production stats (counts, storage, real token consumption, processing time,
errors, feedback aggregates). Episode transcripts and private sources are never
exposed here; only operational metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.db.session import get_session
from app.models.governance import AiAuditLog
from app.models.podcast import PodcastEpisode, PodcastFeedback

router = APIRouter(prefix="/api/v1/admin/podcasts", tags=["podcast-admin"], dependencies=[Depends(require_admin)])

PODCAST_FEATURE_KEYS = ("audio_podcast_script", "audio_podcast_tts")


@router.get("/stats")
async def podcast_stats(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = (await session.scalars(select(PodcastEpisode))).all()
    by_status: dict[str, int] = {}
    total_bytes = 0
    total_duration = 0.0
    processing_seconds: list[float] = []
    model_usage: dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
        total_bytes += int(row.byte_size or 0)
        total_duration += float(row.duration_seconds or 0.0)
        if row.started_at and row.completed_at:
            processing_seconds.append((row.completed_at - row.started_at).total_seconds())
        if row.model_name:
            model_usage[row.model_name] = model_usage.get(row.model_name, 0) + 1

    audit = (
        await session.execute(
            select(
                func.coalesce(func.sum(AiAuditLog.tokens_in), 0),
                func.coalesce(func.sum(AiAuditLog.tokens_out), 0),
                func.count(),
            ).where(AiAuditLog.feature_key.in_(PODCAST_FEATURE_KEYS))
        )
    ).one()
    tokens_in, tokens_out, audit_calls = int(audit[0]), int(audit[1]), int(audit[2])

    feedback_rows = (await session.scalars(select(PodcastFeedback))).all()
    liked = sum(1 for row in feedback_rows if row.liked)
    disliked = len(feedback_rows) - liked
    reason_counts: dict[str, int] = {}
    for row in feedback_rows:
        for reason in row.reasons_json or []:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "total_episodes": len(rows),
        "by_status": by_status,
        "completed": by_status.get("completed", 0),
        "failed": by_status.get("failed", 0),
        "storage_bytes": total_bytes,
        "total_duration_seconds": round(total_duration, 1),
        "avg_processing_seconds": round(sum(processing_seconds) / len(processing_seconds), 1)
        if processing_seconds
        else None,
        "model_usage": model_usage,
        "ai_calls": audit_calls,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "regenerations": sum(
            1
            for row in rows
            if (row.generation_settings_json or {}).get("regenerated_from") is not None
        ),
        "feedback": {"liked": liked, "disliked": disliked, "reason_counts": reason_counts},
    }


@router.get("/episodes")
async def list_podcast_episodes(
    status: str | None = Query(default=None, max_length=24),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    query = select(PodcastEpisode).order_by(PodcastEpisode.created_at.desc()).limit(limit)
    if status:
        query = query.where(PodcastEpisode.status == status)
    rows = (await session.scalars(query)).all()
    return {
        "items": [
            {
                "id": row.id,
                "title": row.title,
                "book_id": row.book_id,
                "format": row.format,
                "language": row.language,
                "length": row.length,
                "status": row.status,
                "progress": row.progress,
                "duration_seconds": row.duration_seconds,
                "byte_size": row.byte_size,
                "model_name": row.model_name,
                "error_code": row.error_code,
                "single_speaker_mode": bool((row.generation_settings_json or {}).get("single_speaker_mode")),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }
