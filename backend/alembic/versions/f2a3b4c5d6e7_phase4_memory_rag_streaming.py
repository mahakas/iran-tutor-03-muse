"""Phase 4: 3-layer learner memory, concept graph, chat soft-delete.

Revision ID: f2a3b4c5d6e7
Revises: e9f0a1b2c3d4
Create Date: 2026-11-21 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "learner_memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("layer", sa.String(length=4), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chapter_number", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("topic_key", sa.String(length=255), nullable=True),
        sa.Column("content_fa", sa.Text(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("created_by", sa.String(length=16), nullable=False, server_default="system"),
        sa.Column("edited_by_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("data_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_learner_memories_user_id", "learner_memories", ["user_id"])
    op.create_index("ix_learner_memories_user_layer", "learner_memories", ["user_id", "layer"])
    op.create_index("ix_learner_memories_book_id", "learner_memories", ["book_id"])
    op.create_index("ix_learner_memories_session_id", "learner_memories", ["session_id"])

    op.create_table(
        "concept_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_chapter", sa.Integer(), nullable=False),
        sa.Column("target_book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_chapter", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("label_fa", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "source_book_id", "source_chapter", "target_book_id", "target_chapter",
            name="uq_concept_links_pair",
        ),
    )
    op.create_index("ix_concept_links_source_book_id", "concept_links", ["source_book_id"])
    op.create_index("ix_concept_links_target_book_id", "concept_links", ["target_book_id"])

    op.add_column("chat_sessions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_chat_sessions_deleted_at", "chat_sessions", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_deleted_at", table_name="chat_sessions")
    op.drop_column("chat_sessions", "deleted_at")
    op.drop_index("ix_concept_links_target_book_id", table_name="concept_links")
    op.drop_index("ix_concept_links_source_book_id", table_name="concept_links")
    op.drop_table("concept_links")
    op.drop_index("ix_learner_memories_session_id", table_name="learner_memories")
    op.drop_index("ix_learner_memories_book_id", table_name="learner_memories")
    op.drop_index("ix_learner_memories_user_layer", table_name="learner_memories")
    op.drop_index("ix_learner_memories_user_id", table_name="learner_memories")
    op.drop_table("learner_memories")
