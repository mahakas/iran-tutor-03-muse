"""Three-layer inspectable learner memory (Phase 4).

- L1 (`layer="L1"`): short-term trace of the current chat session (sliding window).
- L2 (`layer="L2"`): mastered topics / weak spots / notes, scoped by `book_id` and `chapter_number`.
- L3 (`layer="L3"`): longitudinal profile (strengths, recurring error patterns, pace, style).

Every row records who produced it (`created_by`: system or admin) and whether an admin
edited it, so the Memory Inspector can show the full provenance of each entry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_json_type = JSON().with_variant(JSONB, "postgresql")

MEMORY_LAYERS: tuple[str, ...] = ("L1", "L2", "L3")


class LearnerMemory(Base):
    __tablename__ = "learner_memories"
    __table_args__ = (Index("ix_learner_memories_user_layer", "user_id", "layer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    layer: Mapped[str] = mapped_column(String(4), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"), nullable=True, index=True)
    chapter_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    topic_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_fa: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    edited_by_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    data_json: Mapped[dict[str, Any]] = mapped_column(_json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
