"""Phase 3 redesign: student issue reports on flashcards.

Adds ``flashcard_reports`` — one open report per (card, user), reasons aligned
with the shared feedback vocabulary. No change to cards, decks, reviews or the
SM-2 state. Fully reversible: downgrade drops the table (reports are triage
data, not learning history).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f9"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "flashcard_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("flashcards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("note", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_flashcard_reports_card_id", "flashcard_reports", ["card_id"])
    op.create_index("ix_flashcard_reports_user_id", "flashcard_reports", ["user_id"])
    op.create_index(
        "ix_flashcard_reports_status_created", "flashcard_reports", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_flashcard_reports_status_created", table_name="flashcard_reports")
    op.drop_index("ix_flashcard_reports_user_id", table_name="flashcard_reports")
    op.drop_index("ix_flashcard_reports_card_id", table_name="flashcard_reports")
    op.drop_table("flashcard_reports")
