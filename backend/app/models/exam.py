"""Persisted exam sessions. Private answer keys stay in the database payload."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExamStatus(str, enum.Enum):
    active = "active"
    submitted = "submitted"
    expired = "expired"


class ExamSession(Base):
    __tablename__ = "exam_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    # Nullable until phase 6 introduces student accounts.
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    grade_number: Mapped[int] = mapped_column(Integer, nullable=False)
    major_code: Mapped[str] = mapped_column(String(64), nullable=False)
    branch_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    exam_type: Mapped[str] = mapped_column(String(32), nullable=False)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ExamStatus] = mapped_column(
        String(20), default=ExamStatus.active, nullable=False
    )
    _json_type = JSON().with_variant(JSONB, "postgresql")
    questions: Mapped[list[dict[str, Any]]] = mapped_column(_json_type, nullable=False)
    submitted_answers: Mapped[dict[str, Any] | None] = mapped_column(_json_type, nullable=True)
    report_card: Mapped[dict[str, Any] | None] = mapped_column(_json_type, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
