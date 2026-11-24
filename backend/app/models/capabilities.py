"""Phase 2 domain models: capability registry, skills, KB ingestion jobs, source figures.

Implements `docs/DARSYAR_AGENT_PACK.md` PHASE 2 (Rule 4 — modular extensibility):

- ``capabilities`` — the registry of pluggable learning features (chat, solve,
  quiz, multimodal, flashcards, ...) with admin-controlled feature flags,
  role/plan allow-lists and a default model-route key.
- ``skills`` / ``skill_versions`` — database-backed, versioned teaching prompts
  (DeepTutor ``SKILL.md`` style) that the Shared Capability Runtime loads
  dynamically; admins can edit, test and roll back without a deploy.
- ``kb_ingestion_jobs`` — async background jobs that drive the web KB pipeline
  (PDF upload -> page extraction -> vector index) with live progress.
- ``source_figures`` — images/diagrams extracted from textbook pages so Vision
  chat can reference the actual figures.

All JSON-ish columns use the same SQLite/PostgreSQL-compatible variant as the
Phase 1 governance models.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
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

_json_type = JSON().with_variant(JSONB, "postgresql")


class Capability(Base):
    """One pluggable learning feature in the registry.

    ``is_enabled`` is the admin feature flag; ``allowed_roles_json`` /
    ``allowed_plans_json`` are allow-lists (empty list = everyone). The student
    menu is rendered from ``GET /api/v1/capabilities/me`` which applies these
    rules, and every feature endpoint re-checks them server-side.
    """

    __tablename__ = "capabilities"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    description_fa: Mapped[str] = mapped_column(Text, default="", nullable=False)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    allowed_roles_json: Mapped[list[str]] = mapped_column(_json_type, default=list, nullable=False)
    allowed_plans_json: Mapped[list[str]] = mapped_column(_json_type, default=list, nullable=False)
    default_route_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_json: Mapped[dict] = mapped_column(_json_type, default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Skill(Base):
    """An active, editable teaching skill (prompt pack) for a capability."""

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_skills_slug"),
        Index("ix_skills_capability_key", "capability_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(96), nullable=False)
    capability_key: Mapped[str] = mapped_column(
        ForeignKey("capabilities.key"), nullable=False
    )
    title_fa: Mapped[str] = mapped_column(String(160), nullable=False)
    subject_scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grade_scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pedagogy_rules_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    output_schema_json: Mapped[dict] = mapped_column(_json_type, default=dict, nullable=False)
    safety_gate_rules: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SkillVersion(Base):
    """Immutable snapshot of a skill's prompt pack at one version."""

    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
        Index("ix_skill_versions_skill_id", "skill_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pedagogy_rules_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    output_schema_json: Mapped[dict] = mapped_column(_json_type, default=dict, nullable=False)
    safety_gate_rules: Mapped[str] = mapped_column(Text, default="", nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KbIngestionJob(Base):
    """One background KB ingestion run for a book, with live progress."""

    __tablename__ = "kb_ingestion_jobs"
    __table_args__ = (
        Index("ix_kb_ingestion_jobs_book_id", "book_id"),
        Index("ix_kb_ingestion_jobs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    total_pages: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    processed_pages: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    failed_pages: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    start_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SourceFigure(Base):
    """An image/diagram extracted from a textbook page (embedded or rendered)."""

    __tablename__ = "source_figures"
    __table_args__ = (
        Index("ix_source_figures_book_id", "book_id"),
        Index("ix_source_figures_book_page_id", "book_page_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), nullable=False)
    book_page_id: Mapped[int | None] = mapped_column(ForeignKey("book_pages.id"), nullable=True)
    pdf_page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    figure_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    figure_type: Mapped[str] = mapped_column(String(64), default="embedded_image", nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    bbox_json: Mapped[dict | None] = mapped_column(_json_type, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
