"""Persisted student tutor conversation sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    # Nullable until phase 6 introduces student accounts.
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    grade_number: Mapped[int] = mapped_column(Integer, nullable=False)
    major_code: Mapped[str] = mapped_column(String(64), nullable=False)
    branch_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="tutor", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    _json_type = JSON().with_variant(JSONB, "postgresql")
    messages: Mapped[list[dict[str, Any]]] = mapped_column(_json_type, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    # Soft delete (Recycle Bin): hidden from students when set; admins still see it.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
