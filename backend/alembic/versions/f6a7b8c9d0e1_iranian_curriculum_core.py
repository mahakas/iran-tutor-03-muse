"""Iranian curriculum core, textbook edition metadata and objective graph."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "education_cycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "education_branches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("min_grade", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("max_grade", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("min_grade >= 1 AND max_grade <= 12 AND min_grade <= max_grade", name="ck_branch_grade_range"),
    )
    op.create_table(
        "fields_of_study",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("education_branches.id"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_fields_of_study_branch_id", "fields_of_study", ["branch_id"])
    op.create_table(
        "academic_years",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(24), nullable=False, unique=True),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    with op.batch_alter_table("grades") as batch:
        batch.add_column(sa.Column("cycle_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_grades_cycle_id", "education_cycles", ["cycle_id"], ["id"])

    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("academic_year_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("edition_label", sa.String(80), nullable=True))
        batch.add_column(sa.Column("print_year", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("publisher", sa.String(180), nullable=True))
        batch.add_column(sa.Column("official_source_url", sa.String(1024), nullable=True))
        batch.add_column(sa.Column("source_checksum", sa.String(128), nullable=True))
        batch.add_column(sa.Column("catalog_status", sa.String(32), nullable=False, server_default="legacy_unverified"))
        batch.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_books_academic_year_id", "academic_years", ["academic_year_id"], ["id"])
    op.create_index("ix_books_academic_year_id", "books", ["academic_year_id"])

    with op.batch_alter_table("chat_sessions") as batch:
        batch.add_column(sa.Column("branch_code", sa.String(64), nullable=True))
    with op.batch_alter_table("exam_sessions") as batch:
        batch.add_column(sa.Column("branch_code", sa.String(64), nullable=True))

    op.create_table(
        "book_curriculum_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("education_branches.id"), nullable=True),
        sa.Column("field_of_study_id", sa.Integer(), sa.ForeignKey("fields_of_study.id"), nullable=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=True),
        sa.Column("scope_code", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("book_id", "scope_code", name="uq_book_curriculum_scope"),
        sa.CheckConstraint("field_of_study_id IS NULL OR branch_id IS NOT NULL", name="ck_book_curriculum_field_requires_branch"),
    )
    for name, column in (
        ("ix_book_curriculum_links_book_id", "book_id"),
        ("ix_book_curriculum_links_branch_id", "branch_id"),
        ("ix_book_curriculum_links_field_of_study_id", "field_of_study_id"),
        ("ix_book_curriculum_links_subject_id", "subject_id"),
    ):
        op.create_index(name, "book_curriculum_links", [column])

    op.create_table(
        "curriculum_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("grade_id", sa.Integer(), sa.ForeignKey("grades.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("academic_year_id", sa.Integer(), sa.ForeignKey("academic_years.id"), nullable=True),
        sa.Column("scope_code", sa.String(24), nullable=False, server_default="unspecified"),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("curriculum_units.id"), nullable=True),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("unit_type", sa.String(24), nullable=False, server_default="chapter"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("grade_id", "subject_id", "scope_code", "code", name="uq_curriculum_unit_code"),
    )
    op.create_index("ix_curriculum_units_grade_id", "curriculum_units", ["grade_id"])
    op.create_index("ix_curriculum_units_subject_id", "curriculum_units", ["subject_id"])
    op.create_index("ix_curriculum_units_parent_id", "curriculum_units", ["parent_id"])
    op.create_index("ix_curriculum_units_academic_year_id", "curriculum_units", ["academic_year_id"])

    op.create_table(
        "learning_objectives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("curriculum_units.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(160), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("competency_type", sa.String(32), nullable=False, server_default="knowledge"),
        sa.Column("assessment_profile", sa.String(32), nullable=False, server_default="mixed"),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_learning_objectives_unit_id", "learning_objectives", ["unit_id"])

    op.create_table(
        "objective_prerequisites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("objective_id", sa.Integer(), sa.ForeignKey("learning_objectives.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prerequisite_id", sa.Integer(), sa.ForeignKey("learning_objectives.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("objective_id", "prerequisite_id", name="uq_objective_prerequisite"),
        sa.CheckConstraint("objective_id <> prerequisite_id", name="ck_objective_not_own_prerequisite"),
    )
    op.create_index("ix_objective_prerequisites_objective_id", "objective_prerequisites", ["objective_id"])
    op.create_index("ix_objective_prerequisites_prerequisite_id", "objective_prerequisites", ["prerequisite_id"])

    op.create_table(
        "book_page_objectives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_page_id", sa.Integer(), sa.ForeignKey("book_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("objective_id", sa.Integer(), sa.ForeignKey("learning_objectives.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relevance", sa.Integer(), nullable=False, server_default="100"),
        sa.UniqueConstraint("book_page_id", "objective_id", name="uq_book_page_objective"),
    )
    op.create_index("ix_book_page_objectives_book_page_id", "book_page_objectives", ["book_page_id"])
    op.create_index("ix_book_page_objectives_objective_id", "book_page_objectives", ["objective_id"])

    op.create_table(
        "learning_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("objective_id", sa.Integer(), sa.ForeignKey("learning_objectives.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="SET NULL"), nullable=True),
        sa.Column("book_page_id", sa.Integer(), sa.ForeignKey("book_pages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_ref", sa.String(128), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("qualitative_level", sa.String(32), nullable=True),
        sa.Column("rubric_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("verification_status", sa.String(24), nullable=False, server_default="unverified"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_learning_evidence_score_range"),
        sa.UniqueConstraint("user_id", "objective_id", "source_type", "source_ref", name="uq_learning_evidence_source"),
    )
    op.create_index("ix_learning_evidence_user_id", "learning_evidence", ["user_id"])
    op.create_index("ix_learning_evidence_objective_id", "learning_evidence", ["objective_id"])
    op.create_index("ix_learning_evidence_book_id", "learning_evidence", ["book_id"])
    op.create_index("ix_learning_evidence_book_page_id", "learning_evidence", ["book_page_id"])


    # Stable cycle and branch taxonomy. Field catalogue is migrated from the legacy
    # Major table to preserve every existing code rather than guessing a new list.
    cycles = sa.table(
        "education_cycles",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    branches = sa.table(
        "education_branches",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("min_grade", sa.Integer),
        sa.column("max_grade", sa.Integer),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(cycles, [
        {"code": "primary", "title": "ابتدایی", "sort_order": 1},
        {"code": "lower_secondary", "title": "متوسطهٔ اول", "sort_order": 2},
        {"code": "upper_secondary", "title": "متوسطهٔ دوم", "sort_order": 3},
    ])
    op.bulk_insert(branches, [
        {"code": "theoretical", "title": "نظری", "min_grade": 10, "max_grade": 12, "sort_order": 1, "is_active": True},
        {"code": "technical_vocational", "title": "فنی‌وحرفه‌ای", "min_grade": 10, "max_grade": 12, "sort_order": 2, "is_active": True},
        {"code": "kar_danesh", "title": "کاردانش", "min_grade": 10, "max_grade": 12, "sort_order": 3, "is_active": True},
    ])

    connection = op.get_bind()
    cycle_ids = dict(connection.execute(sa.text("SELECT code, id FROM education_cycles")).all())
    branch_ids = dict(connection.execute(sa.text("SELECT code, id FROM education_branches")).all())
    for number, code in ((1, "primary"), (2, "primary"), (3, "primary"), (4, "primary"), (5, "primary"), (6, "primary"),
                         (7, "lower_secondary"), (8, "lower_secondary"), (9, "lower_secondary"),
                         (10, "upper_secondary"), (11, "upper_secondary"), (12, "upper_secondary")):
        connection.execute(
            sa.text("UPDATE grades SET cycle_id = :cycle_id WHERE number = :number"),
            {"cycle_id": cycle_ids[code], "number": number},
        )

    fields = sa.table(
        "fields_of_study",
        sa.column("branch_id", sa.Integer),
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    legacy_majors = connection.execute(sa.text("SELECT code, title FROM majors ORDER BY id")).all()
    sort_order = 1
    for code, title in legacy_majors:
        connection.execute(
            sa.text(
                "INSERT INTO fields_of_study (branch_id, code, title, sort_order, is_active) "
                "VALUES (:branch_id, :code, :title, :sort_order, TRUE)"
            ),
            {"branch_id": branch_ids["theoretical"], "code": code, "title": title, "sort_order": sort_order},
        )
        sort_order += 1
    connection.execute(
        sa.text(
            "INSERT INTO fields_of_study (branch_id, code, title, sort_order, is_active) "
            "VALUES (:branch_id, 'islamic_studies', 'علوم و معارف اسلامی', :sort_order, TRUE)"
        ),
        {"branch_id": branch_ids["theoretical"], "sort_order": sort_order},
    )

    field_ids = dict(connection.execute(sa.text("SELECT code, id FROM fields_of_study")).all())
    links = sa.table(
        "book_curriculum_links",
        sa.column("book_id", sa.Integer),
        sa.column("branch_id", sa.Integer),
        sa.column("field_of_study_id", sa.Integer),
        sa.column("subject_id", sa.Integer),
        sa.column("scope_code", sa.String),
    )
    books = connection.execute(
        sa.text(
            "SELECT books.id, books.major_id, grades.number "
            "FROM books JOIN grades ON grades.id = books.grade_id ORDER BY books.id"
        )
    ).all()
    for book_id, major_id, grade_number in books:
        if major_id is None:
            # Do not assume an unclassified upper-secondary book is shared by every
            # branch. Only primary/lower-secondary books are safely general by default.
            if grade_number <= 9:
                connection.execute(
                    sa.text(
                        "INSERT INTO book_curriculum_links (book_id, branch_id, field_of_study_id, subject_id, scope_code) "
                        "VALUES (:book_id, NULL, NULL, NULL, 'general')"
                    ),
                    {"book_id": book_id},
                )
            continue
        major_code = connection.execute(
            sa.text("SELECT code FROM majors WHERE id = :major_id"), {"major_id": major_id}
        ).scalar_one_or_none()
        if major_code and major_code in field_ids:
            connection.execute(
                sa.text(
                    "INSERT INTO book_curriculum_links (book_id, branch_id, field_of_study_id, subject_id, scope_code) "
                    "VALUES (:book_id, :branch_id, :field_id, NULL, :scope_code)"
                ),
                {
                    "book_id": book_id,
                    "branch_id": branch_ids["theoretical"],
                    "field_id": field_ids[major_code],
                    "scope_code": "field:" + major_code,
                },
            )


def downgrade() -> None:
    with op.batch_alter_table("exam_sessions") as batch:
        batch.drop_column("branch_code")
    with op.batch_alter_table("chat_sessions") as batch:
        batch.drop_column("branch_code")
    op.drop_index("ix_learning_evidence_book_page_id", table_name="learning_evidence")
    op.drop_index("ix_learning_evidence_book_id", table_name="learning_evidence")
    op.drop_index("ix_learning_evidence_objective_id", table_name="learning_evidence")
    op.drop_index("ix_learning_evidence_user_id", table_name="learning_evidence")
    op.drop_table("learning_evidence")
    op.drop_table("book_page_objectives")
    op.drop_table("objective_prerequisites")
    op.drop_table("learning_objectives")
    op.drop_table("curriculum_units")
    op.drop_table("book_curriculum_links")
    op.drop_index("ix_books_academic_year_id", table_name="books")
    with op.batch_alter_table("books") as batch:
        batch.drop_constraint("fk_books_academic_year_id", type_="foreignkey")
        batch.drop_column("approved_at")
        batch.drop_column("catalog_status")
        batch.drop_column("source_checksum")
        batch.drop_column("official_source_url")
        batch.drop_column("publisher")
        batch.drop_column("print_year")
        batch.drop_column("edition_label")
        batch.drop_column("academic_year_id")
    with op.batch_alter_table("grades") as batch:
        batch.drop_constraint("fk_grades_cycle_id", type_="foreignkey")
        batch.drop_column("cycle_id")
    op.drop_table("subjects")
    op.drop_table("academic_years")
    op.drop_index("ix_fields_of_study_branch_id", table_name="fields_of_study")
    op.drop_table("fields_of_study")
    op.drop_table("education_branches")
    op.drop_table("education_cycles")
