"""Phase 7: align PostgreSQL unique indexes and flashcard user_id width with the models.

Earlier migrations created `uq_*` unique constraints beside plain `ix_*` indexes, while the
models declare `unique=True, index=True` (a single unique `ix_*` index). Uniqueness was already
enforced by the `uq_*` objects, so this only renames the enforcement to the model's names.
`flashcard_decks.user_id` / `flashcard_reviews.user_id` were VARCHAR(64) in the database and
VARCHAR(36) in the models (user ids are UUIDs, 36 characters), so the width is aligned.

PostgreSQL only: the SQLite development schema already matched the models.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None

# (table, column, legacy unique constraint name)
_UNIQUE = (
    ("plans", "code", "uq_plans_code"),
    ("users", "phone_number", "uq_users_phone_number"),
    ("user_sessions", "token_nonce", "uq_user_sessions_token_nonce"),
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    for table, column, legacy in _UNIQUE:
        op.drop_constraint(legacy, table, type_="unique")
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.create_index(f"ix_{table}_{column}", table, [column], unique=True)
    for table in ("flashcard_decks", "flashcard_reviews"):
        op.alter_column(
            table,
            "user_id",
            existing_type=sa.String(length=64),
            type_=sa.String(length=36),
            existing_nullable=False,
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    for table in ("flashcard_reviews", "flashcard_decks"):
        op.alter_column(
            table,
            "user_id",
            existing_type=sa.String(length=36),
            type_=sa.String(length=64),
            existing_nullable=False,
        )
    for table, column, legacy in _UNIQUE:
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)
        op.create_unique_constraint(legacy, table, [column])
