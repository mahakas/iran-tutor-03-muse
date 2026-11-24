"""Phase 2: capability registry, skills & skill versions, KB ingestion jobs,
and source figures (web KB pipeline).

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-11-21 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    # --- capability registry -------------------------------------------------
    op.create_table(
        "capabilities",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("title_fa", sa.String(length=120), nullable=False),
        sa.Column("description_fa", sa.Text(), nullable=False),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("allowed_roles_json", JSON_TYPE, nullable=False),
        sa.Column("allowed_plans_json", JSON_TYPE, nullable=False),
        sa.Column("default_route_key", sa.String(length=64), nullable=True),
        sa.Column("config_json", JSON_TYPE, nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- skills (active prompt packs) ----------------------------------------
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=96), nullable=False),
        sa.UniqueConstraint("slug", name="uq_skills_slug"),
        sa.Column("capability_key", sa.String(length=64), sa.ForeignKey("capabilities.key"), nullable=False),
        sa.Column("title_fa", sa.String(length=160), nullable=False),
        sa.Column("subject_scope", sa.String(length=64), nullable=True),
        sa.Column("grade_scope", sa.String(length=64), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("pedagogy_rules_md", sa.Text(), nullable=False),
        sa.Column("output_schema_json", JSON_TYPE, nullable=False),
        sa.Column("safety_gate_rules", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_skills_capability_key", "skills", ["capability_key"])

    # --- skill versions (immutable history for rollback) ----------------------
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("pedagogy_rules_md", sa.Text(), nullable=False),
        sa.Column("output_schema_json", JSON_TYPE, nullable=False),
        sa.Column("safety_gate_rules", sa.Text(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
    )
    op.create_index("ix_skill_versions_skill_id", "skill_versions", ["skill_id"])

    # --- KB ingestion jobs (web pipeline progress) ----------------------------
    op.create_table(
        "kb_ingestion_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("total_pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processed_pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("start_page", sa.Integer(), nullable=True),
        sa.Column("end_page", sa.Integer(), nullable=True),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_kb_ingestion_jobs_book_id", "kb_ingestion_jobs", ["book_id"])
    op.create_index("ix_kb_ingestion_jobs_status", "kb_ingestion_jobs", ["status"])

    # --- source figures (extracted textbook diagrams/images) ------------------
    op.create_table(
        "source_figures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("book_page_id", sa.Integer(), sa.ForeignKey("book_pages.id"), nullable=True),
        sa.Column("pdf_page_index", sa.Integer(), nullable=False),
        sa.Column("printed_page_number", sa.Integer(), nullable=True),
        sa.Column("chapter_number", sa.Integer(), nullable=True),
        sa.Column("image_path", sa.String(length=1024), nullable=False),
        sa.Column("figure_label", sa.String(length=120), nullable=True),
        sa.Column("figure_type", sa.String(length=64), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("bbox_json", JSON_TYPE, nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_source_figures_book_id", "source_figures", ["book_id"])
    op.create_index("ix_source_figures_book_page_id", "source_figures", ["book_page_id"])


def downgrade() -> None:
    op.drop_table("source_figures")
    op.drop_table("kb_ingestion_jobs")
    op.drop_table("skill_versions")
    op.drop_table("skills")
    op.drop_table("capabilities")
