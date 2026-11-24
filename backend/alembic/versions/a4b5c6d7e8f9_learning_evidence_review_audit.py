"""Persist reviewer identity and review note separately from student feedback."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "learning_evidence",
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "learning_evidence",
        sa.Column("review_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("learning_evidence", "review_note")
    op.drop_column("learning_evidence", "reviewed_by")
