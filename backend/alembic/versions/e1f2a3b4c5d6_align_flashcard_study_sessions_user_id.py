"""Align flashcard_study_sessions.user_id width with the models (PostgreSQL).

``c8d9e0f1a2b3`` created the column as ``String(64)``, re-introducing the same drift
that Phase 7 (``d4e5f6a7b8c9``) already fixed for ``flashcard_decks`` and
``flashcard_reviews``. The ORM derives ``String(36)`` from ``users.id``, so on a
fresh PostgreSQL ``alembic check`` reported a pending ``modify_type`` on this column.
Purely a type-width alignment: no row, index or capability changes; the FK to
``users.id`` (String(36)) guarantees no value can exceed 36 characters.

SQLite demo never runs Alembic (see docs/REDESIGN_DECISIONS_LOG.md, D-002); the
``_is_postgres()`` guard mirrors ``d4e5f6a7b8c9_phase7_schema_drift_fix.py``.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.alter_column(
        "flashcard_study_sessions",
        "user_id",
        existing_type=sa.String(length=64),
        type_=sa.String(length=36),
        existing_nullable=False,
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.alter_column(
        "flashcard_study_sessions",
        "user_id",
        existing_type=sa.String(length=36),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
