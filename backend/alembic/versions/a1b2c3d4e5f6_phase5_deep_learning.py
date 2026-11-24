"""Phase 5: mistake bank, Deep Solve sessions, mastery path, validator log, admin action log.

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-11-21 18:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "mistake_bank_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exam_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=32), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=True),
        sa.Column("chapter_number", sa.Integer(), nullable=True),
        sa.Column("chapter_title", sa.String(length=255), nullable=True),
        sa.Column("printed_page_number", sa.Integer(), nullable=True),
        sa.Column("topic_tag", sa.String(length=255), nullable=False),
        sa.Column("error_tag", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("choices_json", JSON_TYPE, nullable=False),
        sa.Column("correct_option", sa.String(length=1), nullable=False),
        sa.Column("student_answer", sa.String(length=1), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("source_json", JSON_TYPE, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("correct_streak", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("flashcard_card_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "exam_id", "question_id", name="uq_mistake_user_exam_question"),
    )
    op.create_index("ix_mistake_bank_items_user_id", "mistake_bank_items", ["user_id"])
    op.create_index("ix_mistake_bank_items_book_id", "mistake_bank_items", ["book_id"])
    op.create_index("ix_mistake_user_status", "mistake_bank_items", ["user_id", "status"])

    op.create_table(
        "deep_solve_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="SET NULL"), nullable=True),
        sa.Column("problem_text", sa.Text(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=False),
        sa.Column("steps_json", JSON_TYPE, nullable=False),
        sa.Column("final_answer", sa.Text(), nullable=False),
        sa.Column("state_json", JSON_TYPE, nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mastery_recorded", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_deep_solve_user", "deep_solve_sessions", ["user_id"])

    op.create_table(
        "mastery_chapter_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("exam_correct", sa.Integer(), nullable=False),
        sa.Column("exam_total", sa.Integer(), nullable=False),
        sa.Column("flash_correct", sa.Integer(), nullable=False),
        sa.Column("flash_total", sa.Integer(), nullable=False),
        sa.Column("solve_correct", sa.Integer(), nullable=False),
        sa.Column("solve_total", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "book_id", "chapter_number", name="uq_mastery_progress_user_book_chapter"),
    )
    op.create_index("ix_mastery_chapter_progress_user_id", "mastery_chapter_progress", ["user_id"])

    op.create_table(
        "mastery_book_settings",
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("unlock_mode", sa.String(length=16), nullable=False),
        sa.Column("chapter_overrides_json", JSON_TYPE, nullable=False),
        sa.Column("updated_by", sa.String(length=120), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "quiz_validation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("exam_id", sa.String(length=36), nullable=True),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.Column("question_index", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("reasons_json", JSON_TYPE, nullable=False),
        sa.Column("question_json", JSON_TYPE, nullable=False),
        sa.Column("audit_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_quiz_validation_user", "quiz_validation_logs", ["user_id"])

    op.create_table(
        "admin_action_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=128), nullable=False),
        sa.Column("payload_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admin_action_target", "admin_action_logs", ["target"])


def downgrade() -> None:
    op.drop_index("ix_admin_action_target", table_name="admin_action_logs")
    op.drop_table("admin_action_logs")
    op.drop_index("ix_quiz_validation_user", table_name="quiz_validation_logs")
    op.drop_table("quiz_validation_logs")
    op.drop_table("mastery_book_settings")
    op.drop_index("ix_mastery_chapter_progress_user_id", table_name="mastery_chapter_progress")
    op.drop_table("mastery_chapter_progress")
    op.drop_index("ix_deep_solve_user", table_name="deep_solve_sessions")
    op.drop_table("deep_solve_sessions")
    op.drop_index("ix_mistake_user_status", table_name="mistake_bank_items")
    op.drop_index("ix_mistake_bank_items_book_id", table_name="mistake_bank_items")
    op.drop_index("ix_mistake_bank_items_user_id", table_name="mistake_bank_items")
    op.drop_table("mistake_bank_items")
