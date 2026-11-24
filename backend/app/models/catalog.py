"""Iran Education Catalog 1405–1406: title-level textbooks, grounds, program
availability, student academic profile and catalog provenance.

Entity mapping to the requested conceptual architecture (see
docs/EDUCATION_DATABASE_SCHEMA.md):
- AcademicYear        -> existing academic_years (curriculum.py)
- EducationStage      -> existing education_cycles (curriculum.py)
- Grade               -> existing grades (curriculum.py)
- Track               -> existing education_branches (curriculum.py)
- Field (زمینه)        -> EducationGround (this file), scoped to a هنرستانی track
- Program             -> existing fields_of_study rows; هنرستانی programs carry
                         ground_id, نظری programs stay ground-less
- Course              -> existing subjects (curriculum.py)
- Textbook            -> CatalogTextbook (this file): title-level record, no PDF
- TextbookEdition     -> existing books (curriculum.py); nullable
                         catalog_textbook_id connects a future PDF edition to its
                         catalog title
- CourseTextbook      -> CatalogCourseTextbook (this file) + existing
                         book_curriculum_links for edition-level scoping
- ProgramAvailability -> ProgramAvailability (this file), versioned per year
- StudentAcademicProfile / CatalogSource / CatalogImportRun -> this file
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EducationGround(Base):
    """A vocational ground (زمینه) between a هنرستانی track and its programs.

    Theoretical programs never reference a ground: Track -> Program directly.
    """

    __tablename__ = "education_grounds"
    __table_args__ = (UniqueConstraint("branch_id", "code", name="uq_ground_branch_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("education_branches.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CatalogTextbook(Base):
    """A title-level catalog record — the canonical textbook identity.

    Deliberately PDF-less: actual uploaded editions live in `books`. A title is
    created once and shared across programs through offering links, so a common
    book is never duplicated per field. No national code is invented: when the
    owner has not supplied one, `national_code` stays NULL and the title is
    flagged for verification instead.
    """

    __tablename__ = "catalog_textbooks"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_catalog_textbook_slug"),
        CheckConstraint(
            "textbook_kind IN ('student_book','workbook','supplementary','periodical','teacher_guide')",
            name="ck_catalog_textbook_kind",
        ),
        CheckConstraint(
            "audience_variant IN ('general','girls','boys','religious_minority')",
            name="ck_catalog_textbook_audience",
        ),
        CheckConstraint(
            "implementation_status IN ('confirmed','experimental','regional_pilot','needs_verification')",
            name="ck_catalog_textbook_impl_status",
        ),
        CheckConstraint(
            "validity_status IN ('active','needs_verification','unknown')",
            name="ck_catalog_textbook_validity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(255), nullable=False)
    title_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Official national textbook code — only when the owner supplied it; NULL is
    # honest "unknown", never a fabricated value.
    national_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # NULL grade = the exact grade placement is not verified yet (kept for review,
    # never guessed — e.g. the periodic «از ایرانمان دفاع می‌کنیم» booklet).
    grade_id: Mapped[int | None] = mapped_column(ForeignKey("grades.id"), nullable=True, index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    academic_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id"), nullable=True, index=True
    )
    textbook_kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default="student_book", server_default="student_book"
    )
    audience_variant: Mapped[str] = mapped_column(
        String(24), nullable=False, default="general", server_default="general"
    )
    audience_scope: Mapped[str] = mapped_column(
        String(24), nullable=False, default="national", server_default="national"
    )
    implementation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="confirmed", server_default="confirmed"
    )
    geographic_scope: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # Alternative titles for the same school slot (e.g. پیام‌های آسمان vs
    # از من تا خدا in grade 9) must never be treated as two mandatory books.
    alternative_group: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    validity_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="needs_verification", server_default="needs_verification"
    )
    verification_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Official source link for this title, when the owner publishes one.
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    catalog_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_sources.id"), nullable=True, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Soft-archive: archived titles stop appearing in student selection but keep
    # history, editions and links intact (admin catalog management).
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CatalogCourseTextbook(Base):
    """Offering link: which grade/branch/program a catalog title serves in a year.

    A common book has exactly one CatalogTextbook row and one link row per scope,
    so «کتاب مشترک میان چند رشته یک رکورد» holds at the data level.
    """

    __tablename__ = "catalog_course_textbooks"
    __table_args__ = (
        UniqueConstraint("textbook_id", "scope_code", name="uq_catalog_course_textbook_scope"),
        CheckConstraint(
            "field_of_study_id IS NULL OR branch_id IS NOT NULL",
            name="ck_catalog_ct_field_requires_branch",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    textbook_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_textbooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.id"), nullable=False, index=True)
    grade_id: Mapped[int | None] = mapped_column(ForeignKey("grades.id"), nullable=True, index=True)
    branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("education_branches.id"), nullable=True, index=True
    )
    field_of_study_id: Mapped[int | None] = mapped_column(
        ForeignKey("fields_of_study.id"), nullable=True, index=True
    )
    # Stable scope key handles SQL NULL uniqueness across PostgreSQL and SQLite,
    # same pattern as book_curriculum_links.scope_code.
    scope_code: Mapped[str] = mapped_column(String(200), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProgramAvailability(Base):
    """Per-year validity status of a program (رشته) — never silently confirmed.

    The owner's working list alone is not evidence that every program accepts
    registration in every school; unverified programs keep needs_verification.
    """

    __tablename__ = "program_availability"
    __table_args__ = (
        UniqueConstraint("field_of_study_id", "academic_year_id", name="uq_program_availability_year"),
        CheckConstraint(
            "validity_status IN ('active','stopped_development','redesigned','needs_verification','unknown')",
            name="ck_program_availability_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    field_of_study_id: Mapped[int] = mapped_column(
        ForeignKey("fields_of_study.id", ondelete="CASCADE"), nullable=False, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.id"), nullable=False, index=True)
    validity_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="needs_verification", server_default="needs_verification"
    )
    # Optional official validity window (academic-year codes).
    valid_from_year: Mapped[str | None] = mapped_column(String(24), nullable=True)
    valid_to_year: Mapped[str | None] = mapped_column(String(24), nullable=True)
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    catalog_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_sources.id"), nullable=True, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StudentAcademicProfile(Base):
    """The student's self-owned academic placement (base/track/ground/program).

    Product policy: the student alone owns and edits this profile; there is no
    admin approval step anywhere in this flow. Legacy user columns
    (users.grade_level / users.major) stay mirrored for existing queries.
    """

    __tablename__ = "student_academic_profiles"
    __table_args__ = (
        CheckConstraint(
            "field_of_study_id IS NULL OR branch_id IS NOT NULL",
            name="ck_student_profile_field_requires_branch",
        ),
        CheckConstraint(
            "ground_id IS NULL OR branch_id IS NOT NULL",
            name="ck_student_profile_ground_requires_branch",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    grade_id: Mapped[int | None] = mapped_column(ForeignKey("grades.id"), nullable=True, index=True)
    branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("education_branches.id"), nullable=True, index=True
    )
    ground_id: Mapped[int | None] = mapped_column(
        ForeignKey("education_grounds.id"), nullable=True, index=True
    )
    field_of_study_id: Mapped[int | None] = mapped_column(
        ForeignKey("fields_of_study.id"), nullable=True, index=True
    )
    academic_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CatalogSource(Base):
    """Provenance of the catalog data (owner-provided reference, official site…)."""

    __tablename__ = "catalog_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    authority: Mapped[str | None] = mapped_column(String(180), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CatalogImportRun(Base):
    """Audit trail of one catalog import (structure, books, counts, status)."""

    __tablename__ = "catalog_import_runs"
    _json_type = JSON().with_variant(JSONB, "postgresql")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    academic_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    stats: Mapped[dict] = mapped_column(_json_type, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
