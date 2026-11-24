"""Phase 8: persistent flashcard study sessions (NotebookLM-style progress).

Adds ``flashcard_study_sessions`` — one row per study run so a student can close
the browser and resume exactly where they stopped (card order, current position,
per-card got/missed results, session status). Purely additive: no existing table,
row or SM-2 state is touched, and downgrade only drops the new table.

Revision ID: c8d9e0f1a2b3
Revises: b7c1d2e3f4a5
Create Date: 2026-11-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b7c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "flashcard_study_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "deck_id",
            sa.Integer(),
            sa.ForeignKey("flashcard_decks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="full"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flipped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("card_order_json", JSON_TYPE, nullable=False),
        sa.Column("results_json", JSON_TYPE, nullable=False),
        sa.Column("total_cards", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_flashcard_study_sessions_user_id", "flashcard_study_sessions", ["user_id"])
    op.create_index("ix_flashcard_study_sessions_deck_id", "flashcard_study_sessions", ["deck_id"])
    op.create_index(
        "ix_flashcard_study_sessions_user_deck", "flashcard_study_sessions", ["user_id", "deck_id"]
    )
    op.create_index(
        "ix_flashcard_study_sessions_user_status", "flashcard_study_sessions", ["user_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_flashcard_study_sessions_user_status", table_name="flashcard_study_sessions")
    op.drop_index("ix_flashcard_study_sessions_user_deck", table_name="flashcard_study_sessions")
    op.drop_index("ix_flashcard_study_sessions_deck_id", table_name="flashcard_study_sessions")
    op.drop_index("ix_flashcard_study_sessions_user_id", table_name="flashcard_study_sessions")
    op.drop_table("flashcard_study_sessions")
