"""Iran Education Catalog 1405-1406: grounds, catalog textbooks, offerings,
program availability, student academic profiles and catalog provenance.

Reversible: downgrade drops the new tables/columns. No user data is touched.

Revision ID: b8c9d0e1f2a3
Revises: e1f2a3b4c5d6
Create Date: 2026-11-23

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8c9d0e1f2a3"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "education_grounds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("education_branches.id"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("branch_id", "code", name="uq_ground_branch_code"),
    )
    op.create_index("ix_education_grounds_branch_id", "education_grounds", ["branch_id"])

    op.create_table(
        "catalog_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("authority", sa.String(length=180), nullable=True),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("key", name="uq_catalog_source_key"),
    )

    op.create_table(
        "catalog_textbooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title_fa", sa.String(length=255), nullable=False),
        sa.Column("title_en", sa.String(length=255), nullable=True),
        sa.Column("national_code", sa.String(length=64), nullable=True),
        sa.Column("grade_id", sa.Integer(), sa.ForeignKey("grades.id"), nullable=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=True),
        sa.Column(
            "academic_year_id", sa.Integer(), sa.ForeignKey("academic_years.id"), nullable=True
        ),
        sa.Column("textbook_kind", sa.String(length=24), nullable=False, server_default="student_book"),
        sa.Column("audience_variant", sa.String(length=24), nullable=False, server_default="general"),
        sa.Column("audience_scope", sa.String(length=24), nullable=False, server_default="national"),
        sa.Column(
            "implementation_status", sa.String(length=24), nullable=False, server_default="confirmed"
        ),
        sa.Column("geographic_scope", sa.String(length=24), nullable=True),
        sa.Column("alternative_group", sa.String(length=64), nullable=True),
        sa.Column(
            "validity_status", sa.String(length=24), nullable=False, server_default="needs_verification"
        ),
        sa.Column("verification_note", sa.Text(), nullable=True),
        sa.Column("catalog_source_id", sa.Integer(), sa.ForeignKey("catalog_sources.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_catalog_textbook_slug"),
        sa.CheckConstraint(
            "textbook_kind IN ('student_book','workbook','supplementary','periodical','teacher_guide')",
            name="ck_catalog_textbook_kind",
        ),
        sa.CheckConstraint(
            "audience_variant IN ('general','girls','boys','religious_minority')",
            name="ck_catalog_textbook_audience",
        ),
        sa.CheckConstraint(
            "implementation_status IN ('confirmed','experimental','regional_pilot','needs_verification')",
            name="ck_catalog_textbook_impl_status",
        ),
        sa.CheckConstraint(
            "validity_status IN ('active','needs_verification','unknown')",
            name="ck_catalog_textbook_validity",
        ),
    )
    op.create_index("ix_catalog_textbooks_grade_id", "catalog_textbooks", ["grade_id"])
    op.create_index("ix_catalog_textbooks_subject_id", "catalog_textbooks", ["subject_id"])
    op.create_index("ix_catalog_textbooks_academic_year_id", "catalog_textbooks", ["academic_year_id"])
    op.create_index("ix_catalog_textbooks_alternative_group", "catalog_textbooks", ["alternative_group"])
    op.create_index("ix_catalog_textbooks_catalog_source_id", "catalog_textbooks", ["catalog_source_id"])

    op.create_table(
        "catalog_course_textbooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "textbook_id",
            sa.Integer(),
            sa.ForeignKey("catalog_textbooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("academic_year_id", sa.Integer(), sa.ForeignKey("academic_years.id"), nullable=False),
        sa.Column("grade_id", sa.Integer(), sa.ForeignKey("grades.id"), nullable=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("education_branches.id"), nullable=True),
        sa.Column("field_of_study_id", sa.Integer(), sa.ForeignKey("fields_of_study.id"), nullable=True),
        sa.Column("scope_code", sa.String(length=200), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(length=400), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("textbook_id", "scope_code", name="uq_catalog_course_textbook_scope"),
        sa.CheckConstraint(
            "field_of_study_id IS NULL OR branch_id IS NOT NULL",
            name="ck_catalog_ct_field_requires_branch",
        ),
    )
    op.create_index("ix_catalog_course_textbooks_textbook_id", "catalog_course_textbooks", ["textbook_id"])
    op.create_index("ix_catalog_course_textbooks_academic_year_id", "catalog_course_textbooks", ["academic_year_id"])
    op.create_index("ix_catalog_course_textbooks_grade_id", "catalog_course_textbooks", ["grade_id"])
    op.create_index("ix_catalog_course_textbooks_branch_id", "catalog_course_textbooks", ["branch_id"])
    op.create_index("ix_catalog_course_textbooks_field_of_study_id", "catalog_course_textbooks", ["field_of_study_id"])

    op.create_table(
        "program_availability",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "field_of_study_id",
            sa.Integer(),
            sa.ForeignKey("fields_of_study.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("academic_year_id", sa.Integer(), sa.ForeignKey("academic_years.id"), nullable=False),
        sa.Column(
            "validity_status", sa.String(length=32), nullable=False, server_default="needs_verification"
        ),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("catalog_source_id", sa.Integer(), sa.ForeignKey("catalog_sources.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("field_of_study_id", "academic_year_id", name="uq_program_availability_year"),
        sa.CheckConstraint(
            "validity_status IN ('active','stopped_development','redesigned','needs_verification','unknown')",
            name="ck_program_availability_status",
        ),
    )
    op.create_index("ix_program_availability_field_of_study_id", "program_availability", ["field_of_study_id"])
    op.create_index("ix_program_availability_academic_year_id", "program_availability", ["academic_year_id"])
    op.create_index("ix_program_availability_catalog_source_id", "program_availability", ["catalog_source_id"])

    op.create_table(
        "student_academic_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grade_id", sa.Integer(), sa.ForeignKey("grades.id"), nullable=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("education_branches.id"), nullable=True),
        sa.Column("ground_id", sa.Integer(), sa.ForeignKey("education_grounds.id"), nullable=True),
        sa.Column("field_of_study_id", sa.Integer(), sa.ForeignKey("fields_of_study.id"), nullable=True),
        sa.Column("academic_year_id", sa.Integer(), sa.ForeignKey("academic_years.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "field_of_study_id IS NULL OR branch_id IS NOT NULL",
            name="ck_student_profile_field_requires_branch",
        ),
        sa.CheckConstraint(
            "ground_id IS NULL OR branch_id IS NOT NULL",
            name="ck_student_profile_ground_requires_branch",
        ),
    )
    op.create_index(
        "ix_student_academic_profiles_user_id", "student_academic_profiles", ["user_id"], unique=True
    )
    op.create_index("ix_student_academic_profiles_grade_id", "student_academic_profiles", ["grade_id"])
    op.create_index("ix_student_academic_profiles_branch_id", "student_academic_profiles", ["branch_id"])
    op.create_index("ix_student_academic_profiles_ground_id", "student_academic_profiles", ["ground_id"])
    op.create_index("ix_student_academic_profiles_field_of_study_id", "student_academic_profiles", ["field_of_study_id"])
    op.create_index("ix_student_academic_profiles_academic_year_id", "student_academic_profiles", ["academic_year_id"])

    op.create_table(
        "catalog_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("catalog_key", sa.String(length=160), nullable=False),
        sa.Column("academic_year_id", sa.Integer(), sa.ForeignKey("academic_years.id"), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="running"),
        sa.Column("stats", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_catalog_import_runs_catalog_key", "catalog_import_runs", ["catalog_key"])
    op.create_index("ix_catalog_import_runs_academic_year_id", "catalog_import_runs", ["academic_year_id"])

    op.add_column(
        "fields_of_study",
        sa.Column("ground_id", sa.Integer(), sa.ForeignKey("education_grounds.id"), nullable=True),
    )
    op.create_index("ix_fields_of_study_ground_id", "fields_of_study", ["ground_id"])

    op.add_column(
        "books",
        sa.Column(
            "catalog_textbook_id",
            sa.Integer(),
            sa.ForeignKey("catalog_textbooks.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_books_catalog_textbook_id", "books", ["catalog_textbook_id"])


def downgrade() -> None:
    op.drop_index("ix_books_catalog_textbook_id", table_name="books")
    op.drop_column("books", "catalog_textbook_id")
    op.drop_index("ix_fields_of_study_ground_id", table_name="fields_of_study")
    op.drop_column("fields_of_study", "ground_id")
    op.drop_index("ix_catalog_import_runs_academic_year_id", table_name="catalog_import_runs")
    op.drop_index("ix_catalog_import_runs_catalog_key", table_name="catalog_import_runs")
    op.drop_table("catalog_import_runs")
    op.drop_index("ix_student_academic_profiles_user_id", table_name="student_academic_profiles")
    op.drop_index("ix_student_academic_profiles_academic_year_id", table_name="student_academic_profiles")
    op.drop_index("ix_student_academic_profiles_field_of_study_id", table_name="student_academic_profiles")
    op.drop_index("ix_student_academic_profiles_ground_id", table_name="student_academic_profiles")
    op.drop_index("ix_student_academic_profiles_branch_id", table_name="student_academic_profiles")
    op.drop_index("ix_student_academic_profiles_grade_id", table_name="student_academic_profiles")
    op.drop_table("student_academic_profiles")
    op.drop_index("ix_program_availability_catalog_source_id", table_name="program_availability")
    op.drop_index("ix_program_availability_academic_year_id", table_name="program_availability")
    op.drop_index("ix_program_availability_field_of_study_id", table_name="program_availability")
    op.drop_table("program_availability")
    op.drop_index("ix_catalog_course_textbooks_field_of_study_id", table_name="catalog_course_textbooks")
    op.drop_index("ix_catalog_course_textbooks_branch_id", table_name="catalog_course_textbooks")
    op.drop_index("ix_catalog_course_textbooks_grade_id", table_name="catalog_course_textbooks")
    op.drop_index("ix_catalog_course_textbooks_academic_year_id", table_name="catalog_course_textbooks")
    op.drop_index("ix_catalog_course_textbooks_textbook_id", table_name="catalog_course_textbooks")
    op.drop_table("catalog_course_textbooks")
    op.drop_index("ix_catalog_textbooks_catalog_source_id", table_name="catalog_textbooks")
    op.drop_index("ix_catalog_textbooks_alternative_group", table_name="catalog_textbooks")
    op.drop_index("ix_catalog_textbooks_academic_year_id", table_name="catalog_textbooks")
    op.drop_index("ix_catalog_textbooks_subject_id", table_name="catalog_textbooks")
    op.drop_index("ix_catalog_textbooks_grade_id", table_name="catalog_textbooks")
    op.drop_table("catalog_textbooks")
    op.drop_table("catalog_sources")
    op.drop_index("ix_education_grounds_branch_id", table_name="education_grounds")
    op.drop_table("education_grounds")
