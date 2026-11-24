"""Iranian K-12 curriculum taxonomy and versioned textbook models."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Float,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BookStatus(str, enum.Enum):
    created = "created"
    ingesting = "ingesting"
    ready = "ready"
    failed = "failed"


class PageStatus(str, enum.Enum):
    pending = "pending"
    done = "done"
    failed = "failed"
    needs_review = "needs_review"


class EducationCycle(Base):
    __tablename__ = "education_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EducationBranch(Base):
    __tablename__ = "education_branches"
    __table_args__ = (
        CheckConstraint("min_grade >= 1 AND max_grade <= 12 AND min_grade <= max_grade", name="ck_branch_grade_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    min_grade: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_grade: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FieldOfStudy(Base):
    __tablename__ = "fields_of_study"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("education_branches.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    # Vocational ground (زمینه) — set only for فنی‌وحرفه‌ای/کاردانش programs;
    # theoretical programs go Track -> Program directly.
    ground_id: Mapped[int | None] = mapped_column(ForeignKey("education_grounds.id"), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AcademicYear(Base):
    __tablename__ = "academic_years"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Admin catalog management: course type (general/specialized/skill/workshop/
    # elective/supplementary), weekly hours and mandatory flag.
    course_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="general", server_default="general")
    weekly_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Grade(Base):
    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    # Kept for older clients. New code determines the cycle/branch from curriculum tables.
    has_major: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("education_cycles.id"), nullable=True)


class Major(Base):
    """Legacy alias retained while clients and user records migrate to FieldOfStudy."""

    __tablename__ = "majors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class Book(Base):
    """A single textbook edition; a new print/year is always a new Book row."""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    grade_id: Mapped[int] = mapped_column(ForeignKey("grades.id"), nullable=False)
    # Title-level catalog identity (Iran Education Catalog 1405–1406). NULL for
    # editions imported before the catalog existed.
    catalog_textbook_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_textbooks.id"), nullable=True, index=True
    )
    # Deprecated compatibility link; do not use it as the full curriculum model.
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True)
    academic_year_id: Mapped[int | None] = mapped_column(ForeignKey("academic_years.id"), nullable=True, index=True)
    edition_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    print_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(180), nullable=True)
    # Deprecated since the auto-publish hotfix: kept only for backward compatibility
    # with existing rows (no destructive migration). Nothing reads these fields to
    # decide student visibility — that is `Book.status == ready` alone.
    official_source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    catalog_status: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy_unverified", server_default="legacy_unverified")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pdf_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    total_pdf_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[BookStatus] = mapped_column(
        Enum(BookStatus, name="book_status"), default=BookStatus.created, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BookCurriculumLink(Base):
    """Many-to-many applicability: one edition can serve multiple fields/subjects."""

    __tablename__ = "book_curriculum_links"
    __table_args__ = (
        UniqueConstraint("book_id", "scope_code", name="uq_book_curriculum_scope"),
        CheckConstraint(
            "field_of_study_id IS NULL OR branch_id IS NOT NULL",
            name="ck_book_curriculum_field_requires_branch",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("education_branches.id"), nullable=True, index=True)
    field_of_study_id: Mapped[int | None] = mapped_column(ForeignKey("fields_of_study.id"), nullable=True, index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    # Stable key handles SQL NULL uniqueness consistently across PostgreSQL and SQLite.
    scope_code: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BookPage(Base):
    __tablename__ = "book_pages"
    __table_args__ = (UniqueConstraint("book_id", "pdf_page_index", name="uq_bookpage_book_page"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    pdf_page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    markdown_content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    original_markdown_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    visual_elements: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False
    )
    page_image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[PageStatus] = mapped_column(
        Enum(PageStatus, name="page_status"), default=PageStatus.pending, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warnings: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    edited_by_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CurriculumUnit(Base):
    """Canonical chapter/lesson tree, independent from the PDF page layout."""

    __tablename__ = "curriculum_units"
    __table_args__ = (
        Index(
            "uq_curriculum_unit_code_scope",
            "grade_id",
            "subject_id",
            "scope_code",
            text("COALESCE(branch_id, 0)"),
            text("COALESCE(field_of_study_id, 0)"),
            "code",
            unique=True,
        ),
        CheckConstraint(
            "field_of_study_id IS NULL OR branch_id IS NOT NULL",
            name="ck_curriculum_unit_field_requires_branch",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grade_id: Mapped[int] = mapped_column(ForeignKey("grades.id"), nullable=False, index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("education_branches.id"), nullable=True, index=True)
    field_of_study_id: Mapped[int | None] = mapped_column(ForeignKey("fields_of_study.id"), nullable=True, index=True)
    academic_year_id: Mapped[int | None] = mapped_column(ForeignKey("academic_years.id"), nullable=True, index=True)
    scope_code: Mapped[str] = mapped_column(String(24), nullable=False, default="unspecified", server_default="unspecified")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("curriculum_units.id"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(24), nullable=False, default="chapter")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class LearningObjective(Base):
    """An observable learning objective/competency used by tutoring and mastery."""

    __tablename__ = "learning_objectives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("curriculum_units.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    competency_type: Mapped[str] = mapped_column(String(32), nullable=False, default="knowledge")
    assessment_profile: Mapped[str] = mapped_column(String(32), nullable=False, default="mixed")
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ObjectivePrerequisite(Base):
    __tablename__ = "objective_prerequisites"
    __table_args__ = (
        UniqueConstraint("objective_id", "prerequisite_id", name="uq_objective_prerequisite"),
        CheckConstraint("objective_id <> prerequisite_id", name="ck_objective_not_own_prerequisite"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    objective_id: Mapped[int] = mapped_column(ForeignKey("learning_objectives.id", ondelete="CASCADE"), nullable=False, index=True)
    prerequisite_id: Mapped[int] = mapped_column(ForeignKey("learning_objectives.id", ondelete="CASCADE"), nullable=False, index=True)


class BookPageObjective(Base):
    __tablename__ = "book_page_objectives"
    __table_args__ = (UniqueConstraint("book_page_id", "objective_id", name="uq_book_page_objective"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_page_id: Mapped[int] = mapped_column(ForeignKey("book_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    objective_id: Mapped[int] = mapped_column(ForeignKey("learning_objectives.id", ondelete="CASCADE"), nullable=False, index=True)
    relevance: Mapped[int] = mapped_column(Integer, nullable=False, default=100)



class LearningEvidence(Base):
    """Student evidence against one curriculum objective, including qualitative and practical work."""

    __tablename__ = "learning_evidence"
    __table_args__ = (
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_learning_evidence_score_range",
        ),
        UniqueConstraint(
            "user_id",
            "objective_id",
            "book_id",
            "source_type",
            "source_ref",
            name="uq_learning_evidence_book_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    objective_id: Mapped[int] = mapped_column(
        ForeignKey("learning_objectives.id", ondelete="CASCADE"), nullable=False, index=True
    )
    book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id", ondelete="SET NULL"), nullable=True, index=True
    )
    book_page_id: Mapped[int | None] = mapped_column(
        ForeignKey("book_pages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    qualitative_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rubric_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False
    )
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unverified", server_default="unverified"
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
