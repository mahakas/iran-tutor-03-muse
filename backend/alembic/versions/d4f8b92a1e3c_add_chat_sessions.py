"""add persisted chat sessions

Revision ID: d4f8b92a1e3c
Revises: c398e215d1aa
Create Date: 2026-11-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4f8b92a1e3c"
down_revision: Union[str, Sequence[str], None] = "c398e215d1aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("grade_number", sa.Integer(), nullable=False),
        sa.Column("major_code", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), server_default="tutor", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("messages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
    )
    op.create_index("ix_chat_sessions_book_id", "chat_sessions", ["book_id"])
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_book_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
