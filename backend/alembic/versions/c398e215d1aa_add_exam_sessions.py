"""add persisted exam sessions

Revision ID: c398e215d1aa
Revises: 7562ccf427ce
Create Date: 2026-11-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c398e215d1aa"
down_revision: Union[str, Sequence[str], None] = "7562ccf427ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exam_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("grade_number", sa.Integer(), nullable=False),
        sa.Column("major_code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("exam_type", sa.String(length=32), nullable=False),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("submitted_answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report_card", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
    )
    op.create_index("ix_exam_sessions_book_id", "exam_sessions", ["book_id"])
    op.create_index("ix_exam_sessions_user_id", "exam_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_exam_sessions_user_id", table_name="exam_sessions")
    op.drop_index("ix_exam_sessions_book_id", table_name="exam_sessions")
    op.drop_table("exam_sessions")
