"""Podcast domain models (Audio-Overview-style educational podcasts).

- ``podcast_episodes``   — one generated episode: source snapshot, validated script,
                          transcript, private audio file path, status/progress for the
                          background job, generation settings and error info.
- ``podcast_segments``   — one dialogue turn: speaker, text, source refs, per-segment
                          audio file and (when measurable) start/end timestamps for the
                          transcript highlight.
- ``podcast_feedbacks``  — thumbs up/down plus anonymized quality reasons.
- ``podcast_questions``  — "Ask the hosts" Q&A history, grounded in the episode sources.

Audio files live under the server's private ``storage/podcast_audio/`` directory and
are only served through authenticated, ownership-checked API routes — never by a
direct public path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_json_type = JSON().with_variant(JSONB, "postgresql")

PODCAST_FORMATS: tuple[str, ...] = ("deep_dive", "brief", "critique", "debate")
PODCAST_LENGTHS: tuple[str, ...] = ("short", "standard", "long")
PODCAST_STATUSES: tuple[str, ...] = (
    "queued",
    "generating_script",
    "generating_audio",
    "assembling_audio",
    "completed",
    "failed",
    "cancelled",
)
SPEAKERS: tuple[str, ...] = ("host_a", "host_b", "narrator")
SEGMENT_STATUSES: tuple[str, ...] = ("pending", "ready", "failed")


class PodcastEpisode(Base):
    __tablename__ = "podcast_episodes"
    __table_args__ = (
        Index("ix_podcast_episodes_user_status", "user_id", "status"),
        Index("ix_podcast_episodes_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="deep_dive")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="fa")
    length: Mapped[str] = mapped_column(String(8), nullable=False, default="standard")
    custom_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_snapshot_json: Mapped[dict[str, Any]] = mapped_column(_json_type, nullable=False, default=dict)
    script_json: Mapped[dict[str, Any]] = mapped_column(_json_type, nullable=False, default=dict)
    transcript: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audio_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_stage: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    generation_settings_json: Mapped[dict[str, Any]] = mapped_column(_json_type, nullable=False, default=dict)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PodcastSegment(Base):
    __tablename__ = "podcast_segments"
    __table_args__ = (Index("ix_podcast_segments_episode_position", "episode_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("podcast_episodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    speaker: Mapped[str] = mapped_column(String(16), nullable=False, default="host_a")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs_json: Mapped[list[int]] = mapped_column(_json_type, nullable=False, default=list)
    audio_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PodcastFeedback(Base):
    __tablename__ = "podcast_feedbacks"
    __table_args__ = (
        UniqueConstraint("episode_id", "user_id", name="uq_podcast_feedback_episode_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("podcast_episodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    liked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reasons_json: Mapped[list[str]] = mapped_column(_json_type, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PodcastQuestion(Base):
    """One "Ask the hosts" exchange. Stored so the student can revisit past answers."""

    __tablename__ = "podcast_questions"
    __table_args__ = (Index("ix_podcast_questions_episode_created", "episode_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("podcast_episodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(_json_type, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
