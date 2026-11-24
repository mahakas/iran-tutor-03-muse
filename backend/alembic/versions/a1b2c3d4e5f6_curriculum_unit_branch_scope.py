"""Add branch/field applicability to curriculum units."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = ("d4e5f6a7b8c9", "f6a7b8c9d0e1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("curriculum_units") as batch:
        batch.add_column(sa.Column("branch_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("field_of_study_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_curriculum_units_branch_id",
            "education_branches",
            ["branch_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_curriculum_units_field_of_study_id",
            "fields_of_study",
            ["field_of_study_id"],
            ["id"],
        )
        batch.drop_constraint("uq_curriculum_unit_code", type_="unique")
        batch.create_check_constraint(
            "ck_curriculum_unit_field_requires_branch",
            "field_of_study_id IS NULL OR branch_id IS NOT NULL",
        )
    op.create_index(
        "uq_curriculum_unit_code_scope",
        "curriculum_units",
        [
            "grade_id",
            "subject_id",
            "scope_code",
            sa.text("COALESCE(branch_id, 0)"),
            sa.text("COALESCE(field_of_study_id, 0)"),
            "code",
        ],
        unique=True,
    )
    op.create_index("ix_curriculum_units_branch_id", "curriculum_units", ["branch_id"])
    op.create_index(
        "ix_curriculum_units_field_of_study_id",
        "curriculum_units",
        ["field_of_study_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_curriculum_units_field_of_study_id", table_name="curriculum_units")
    op.drop_index("ix_curriculum_units_branch_id", table_name="curriculum_units")
    op.drop_index("uq_curriculum_unit_code_scope", table_name="curriculum_units")
    with op.batch_alter_table("curriculum_units") as batch:
        batch.drop_constraint("ck_curriculum_unit_field_requires_branch", type_="check")
        batch.create_unique_constraint(
            "uq_curriculum_unit_code",
            ["grade_id", "subject_id", "scope_code", "code"],
        )
        batch.drop_constraint("fk_curriculum_units_field_of_study_id", type_="foreignkey")
        batch.drop_constraint("fk_curriculum_units_branch_id", type_="foreignkey")
        batch.drop_column("field_of_study_id")
        batch.drop_column("branch_id")
