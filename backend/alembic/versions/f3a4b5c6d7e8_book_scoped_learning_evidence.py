"""Scope learning evidence source identity to a specific book edition."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_learning_evidence_source",
        "learning_evidence",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_learning_evidence_book_source",
        "learning_evidence",
        ["user_id", "objective_id", "book_id", "source_type", "source_ref"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM learning_evidence
            GROUP BY user_id, objective_id, source_type, source_ref
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade evidence source uniqueness: cross-book duplicate source "
            "references exist. Resolve those rows before retrying the downgrade."
        )
    op.drop_constraint(
        "uq_learning_evidence_book_source",
        "learning_evidence",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_learning_evidence_source",
        "learning_evidence",
        ["user_id", "objective_id", "source_type", "source_ref"],
    )
