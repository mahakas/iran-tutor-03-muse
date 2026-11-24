"""Phase 5 domain models: mistake bank, Deep Solve sessions, mastery path, validator log.

Implements `docs/DARSYAR_AGENT_PACK.md` PHASE 5. All JSON columns use the same
SQLite/PostgreSQL-compatible variant as the other phase models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_json_type = JSON().with_variant(JSONB, "postgresql")

MISTAKE_STATUSES = ("unresolved", "practiced", "mastered")


class MistakeBankItem(Base):
    """A wrong or skipped exam question, kept until the student masters it."""

    __tablename__ = "mistake_bank_items"
    __table_args__ = (
        UniqueConstraint("user_id", "exam_id", "question_id", name="uq_mistake_user_exam_question"),
        Index("ix_mistake_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exam_id: Mapped[str] = mapped_column(String(36), nullable=False)
    question_id: Mapped[str] = mapped_column(String(32), nullable=False)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=True, index=True)
    chapter_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    printed_page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topic_tag: Mapped[str] = mapped_column(String(255), nullable=False, default="عمومی")
    error_tag: Mapped[str] = mapped_column(String(32), nullable=False, default="wrong")  # wrong | skipped
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    choices_json: Mapped[dict] = mapped_column(_json_type, nullable=False, default=dict)
    correct_option: Mapped[str] = mapped_column(String(1), nullable=False)
    student_answer: Mapped[str | None] = mapped_column(String(1), nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_json: Mapped[dict] = mapped_column(_json_type, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unresolved")
    correct_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flashcard_card_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DeepSolveSession(Base):
    """A stepwise solving session. Full steps stay server-side until revealed."""

    __tablename__ = "deep_solve_sessions"
    __table_args__ = (Index("ix_deep_solve_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"), nullable=True)
    problem_text: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    steps_json: Mapped[list] = mapped_column(_json_type, nullable=False, default=list)
    final_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Ladder state: per-step hint levels and whether the tutor revealed the step.
    state_json: Mapped[dict] = mapped_column(_json_type, nullable=False, default=dict)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active | completed
    mastery_recorded: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MasteryChapterProgress(Base):
    """Per-user, per-chapter evidence counters feeding the mastery score."""

    __tablename__ = "mastery_chapter_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", "chapter_number", name="uq_mastery_progress_user_book_chapter"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    exam_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exam_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flash_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flash_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    solve_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    solve_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MasteryBookSettings(Base):
    """Admin-controlled mastery rules per book (threshold, unlock mode, chapter overrides)."""

    __tablename__ = "mastery_book_settings"

    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), primary_key=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    unlock_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="sequential")  # sequential | open
    # {"<chapter_number>": "locked" | "open"} overrides set by admin.
    chapter_overrides_json: Mapped[dict] = mapped_column(_json_type, nullable=False, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QuizValidationLog(Base):
    """Validator Gate verdict for one generated question (approved, fixed, or rejected)."""

    __tablename__ = "quiz_validation_logs"
    __table_args__ = (Index("ix_quiz_validation_user", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    exam_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    book_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_index: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)  # approved | fixed | rejected
    reasons_json: Mapped[list] = mapped_column(_json_type, nullable=False, default=list)
    question_json: Mapped[dict] = mapped_column(_json_type, nullable=False, default=dict)
    audit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AdminActionLog(Base):
    """Glass-box trail for admin edits to Phase 5 governance settings."""

    __tablename__ = "admin_action_logs"
    __table_args__ = (Index("ix_admin_action_target", "target"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(_json_type, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
