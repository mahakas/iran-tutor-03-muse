"""Admin education-catalog management: soft-archive, activity flags and
course metadata columns. Reversible; no data is touched.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-23

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "education_cycles",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "grades",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("catalog_textbooks", sa.Column("source_url", sa.String(length=1024), nullable=True))
    op.add_column("catalog_textbooks", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "subjects",
        sa.Column("course_kind", sa.String(length=24), nullable=False, server_default="general"),
    )
    op.add_column("subjects", sa.Column("weekly_hours", sa.Integer(), nullable=True))
    op.add_column(
        "subjects",
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("program_availability", sa.Column("valid_from_year", sa.String(length=24), nullable=True))
    op.add_column("program_availability", sa.Column("valid_to_year", sa.String(length=24), nullable=True))


def downgrade() -> None:
    op.drop_column("program_availability", "valid_to_year")
    op.drop_column("program_availability", "valid_from_year")
    op.drop_column("subjects", "is_mandatory")
    op.drop_column("subjects", "weekly_hours")
    op.drop_column("subjects", "course_kind")
    op.drop_column("catalog_textbooks", "archived_at")
    op.drop_column("catalog_textbooks", "source_url")
    op.drop_column("grades", "is_active")
    op.drop_column("education_cycles", "is_active")
