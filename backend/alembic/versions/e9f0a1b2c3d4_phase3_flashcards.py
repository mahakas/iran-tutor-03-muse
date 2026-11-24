"""Phase 3: flashcard decks, cards, and SM-2 review state.

Also enables the `flashcards` capability and activates the seeded
`flashcard_generator` skill. The skill is activated only while it is still the
untouched seed (updated_by='seed', version=1) so admin edits are never overwritten.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-11-21 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "flashcard_decks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=True),
        sa.Column("chapter_number", sa.Integer(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("admin_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_flashcard_decks_user_id", "flashcard_decks", ["user_id"])
    op.create_index("ix_flashcard_decks_book_id", "flashcard_decks", ["book_id"])

    op.create_table(
        "flashcards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deck_id", sa.Integer(), sa.ForeignKey("flashcard_decks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("front_md", sa.Text(), nullable=False),
        sa.Column("back_md", sa.Text(), nullable=False),
        sa.Column("hint_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("citations_json", JSON_TYPE, nullable=False),
        sa.Column("tags_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_flashcards_deck_id", "flashcards", ["deck_id"])

    op.create_table(
        "flashcard_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("flashcards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ease_factor", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repetitions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_rating", sa.Integer(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("card_id", "user_id", name="uq_flashcard_reviews_card_user"),
    )
    op.create_index("ix_flashcard_reviews_card_id", "flashcard_reviews", ["card_id"])
    op.create_index("ix_flashcard_reviews_user_id", "flashcard_reviews", ["user_id"])
    op.create_index("ix_flashcard_reviews_user_next", "flashcard_reviews", ["user_id", "next_review_at"])

    # Data: enable the Phase 2 placeholder capability and activate the untouched seed skill.
    op.execute("UPDATE capabilities SET is_enabled = true WHERE key = 'flashcards'")
    op.execute(
        "UPDATE skills SET is_active = true "
        "WHERE slug = 'flashcard_generator' AND updated_by = 'seed' AND version = 1"
    )


def downgrade() -> None:
    op.execute("UPDATE capabilities SET is_enabled = false WHERE key = 'flashcards'")
    op.drop_index("ix_flashcard_reviews_user_next", table_name="flashcard_reviews")
    op.drop_index("ix_flashcard_reviews_user_id", table_name="flashcard_reviews")
    op.drop_index("ix_flashcard_reviews_card_id", table_name="flashcard_reviews")
    op.drop_table("flashcard_reviews")
    op.drop_index("ix_flashcards_deck_id", table_name="flashcards")
    op.drop_table("flashcards")
    op.drop_index("ix_flashcard_decks_book_id", table_name="flashcard_decks")
    op.drop_index("ix_flashcard_decks_user_id", table_name="flashcard_decks")
    op.drop_table("flashcard_decks")
