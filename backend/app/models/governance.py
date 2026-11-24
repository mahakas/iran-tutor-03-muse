"""Phase 1 admin-governance domain models.

Covers the encrypted AI-provider vault, per-feature model routing, quota/rate-limit
policy, and the glass-box AI audit trail described in
`docs/DARSYAR_AGENT_PACK.md` (Rules 2 & 3).
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# `text[]`-like capability lists are stored as JSON arrays so the same code runs on
# SQLite (demo) and PostgreSQL (production).
_json_type = JSON().with_variant(JSONB, "postgresql")


class AiProvider(Base):
    """An admin-configured AI provider. The API key is stored encrypted only."""

    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    capabilities: Mapped[list[str]] = mapped_column(_json_type, default=list, nullable=False)
    extra_config: Mapped[dict] = mapped_column(
        _json_type, default=dict, server_default="{}", nullable=False
    )
    last_test_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FeatureModelRoute(Base):
    """Maps a product feature (chat/solve/quiz/...) to a provider + model."""

    __tablename__ = "feature_model_routes"
    __table_args__ = (Index("ix_feature_model_routes_feature_key", "feature_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[int] = mapped_column(ForeignKey("ai_providers.id"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    temperature: Mapped[float] = mapped_column(
        Float, default=0.2, server_default="0.2", nullable=False
    )
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fallback_provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_providers.id"), nullable=True
    )
    fallback_model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fallback_chain_json: Mapped[list[dict]] = mapped_column(
        _json_type, default=list, server_default="[]", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserQuota(Base):
    """Per-user, per-window quota counters enforced before every AI call."""

    __tablename__ = "user_quotas"
    # Phase 04C: one row per (user_id, feature_key) — duplicates split the
    # counters and silently bypassed the gate. Guarded by the upsert in
    # quota_service.increment_quota_counters and migration b5c6d7e8f9a0.
    __table_args__ = (
        Index("ux_user_quotas_user_feature", "user_id", "feature_key", unique=True),
        Index("ix_user_quotas_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(64), default="*", nullable=False)
    daily_tokens_used: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    monthly_tokens_used: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    daily_requests_used: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    window_date: Mapped[str] = mapped_column(String(10), nullable=False)
    window_month: Mapped[str] = mapped_column(String(7), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AiAuditLog(Base):
    """One row per AI call: prompt, response, citations, tokens, cost, latency, status."""

    __tablename__ = "ai_audit_logs"
    __table_args__ = (
        Index("ix_ai_audit_logs_user_id", "user_id"),
        Index("ix_ai_audit_logs_created_at", "created_at"),
        Index("ix_ai_audit_logs_feature_key", "feature_key"),
        Index("ix_ai_audit_logs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_messages_json: Mapped[list] = mapped_column(_json_type, default=list, nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rag_citations_json: Mapped[list] = mapped_column(_json_type, default=list, nullable=False)
    rag_hit_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
    )
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="success", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    flag_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    flagged_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
