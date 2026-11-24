"""Phase 1: RBAC user fields, encrypted AI provider vault, feature model routes,
user quotas, and the glass-box AI audit log.

Revision ID: c7d8e9f0a1b2
Revises: b3c4d5e6f7a8
Create Date: 2026-11-21 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    # --- users: RBAC metadata ------------------------------------------------
    op.add_column("users", sa.Column("grade_level", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("major", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("plan_id", sa.Integer(), nullable=True))

    # --- encrypted AI provider vault ----------------------------------------
    op.create_table(
        "ai_providers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("capabilities", JSON_TYPE, nullable=False),
        sa.Column("extra_config", JSON_TYPE, nullable=False),
        sa.Column("last_test_status", sa.String(length=24), nullable=True),
        sa.Column("last_test_latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "feature_model_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("ai_providers.id"), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("temperature", sa.Float(), server_default="0.2", nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "fallback_provider_id", sa.Integer(), sa.ForeignKey("ai_providers.id"), nullable=True
        ),
        sa.Column("fallback_model_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_feature_model_routes_feature_key", "feature_model_routes", ["feature_key"]
    )

    # --- quotas -------------------------------------------------------------
    op.create_table(
        "user_quotas",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("feature_key", sa.String(length=64), nullable=False, server_default="*"),
        sa.Column("daily_tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("monthly_tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("daily_requests_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("window_date", sa.String(length=10), nullable=False),
        sa.Column("window_month", sa.String(length=7), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_quotas_user_id", "user_quotas", ["user_id"])

    # --- audit trail --------------------------------------------------------
    op.create_table(
        "ai_audit_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("skill_id", sa.String(length=64), nullable=True),
        sa.Column("provider_id", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("request_messages_json", JSON_TYPE, nullable=False),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("rag_citations_json", JSON_TYPE, nullable=False),
        sa.Column("rag_hit_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("flag_reason", sa.String(length=255), nullable=True),
        sa.Column("flagged_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for index_name, columns in (
        ("ix_ai_audit_logs_user_id", ["user_id"]),
        ("ix_ai_audit_logs_created_at", ["created_at"]),
        ("ix_ai_audit_logs_feature_key", ["feature_key"]),
        ("ix_ai_audit_logs_status", ["status"]),
    ):
        op.create_index(index_name, "ai_audit_logs", columns)


def downgrade() -> None:
    for index_name in (
        "ix_ai_audit_logs_status",
        "ix_ai_audit_logs_feature_key",
        "ix_ai_audit_logs_created_at",
        "ix_ai_audit_logs_user_id",
    ):
        op.drop_index(index_name, table_name="ai_audit_logs")
    op.drop_table("ai_audit_logs")

    op.drop_index("ix_user_quotas_user_id", table_name="user_quotas")
    op.drop_table("user_quotas")

    op.drop_index("ix_feature_model_routes_feature_key", table_name="feature_model_routes")
    op.drop_table("feature_model_routes")
    op.drop_table("ai_providers")

    op.drop_column("users", "plan_id")
    op.drop_column("users", "major")
    op.drop_column("users", "grade_level")
