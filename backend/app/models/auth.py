"""Student accounts, SMS OTP codes, plans, billing settings, and token usage models."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    price_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    token_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_quota_bytes: Mapped[int] = mapped_column(
        BigInteger, default=104_857_600, server_default="104857600", nullable=False
    )
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BillingSettings(Base):
    __tablename__ = "billing_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    token_price_per_1k_toman: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    starter_tokens: Mapped[int] = mapped_column(Integer, default=15000, nullable=False)
    starter_duration_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    starter_storage_bytes: Mapped[int] = mapped_column(
        BigInteger, default=26_214_400, server_default="26214400", nullable=False
    )
    _json_type = JSON().with_variant(JSONB, "postgresql")
    admin_preferences: Mapped[dict] = mapped_column(
        _json_type, default=dict, server_default="{}", nullable=False
    )
    system_config: Mapped[dict] = mapped_column(
        _json_type, default=dict, server_default="{}", nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[str] = mapped_column(
        String(32), default="student", server_default="student", nullable=False, index=True
    )
    # Argon2id digest only; NULL means the account has no password yet (OTP-only login).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set the first time an OTP confirms ownership of the number. Uniqueness of the
    # verified number is enforced by normalize-before-check plus the unique index on
    # phone_number; this column records provenance for the "unique verified phone" rule.
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_password_change_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Soft delete: financial/audit rows keep referencing the account, so hard deletion is
    # refused for accounts with history. A deleted account cannot authenticate.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Phase 1 RBAC metadata: grade level (1-12, null = unspecified), study major,
    # and an optional reference to the plans table alongside the legacy plan_code.
    grade_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    major: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    _json_type = JSON().with_variant(JSONB, "postgresql")
    preferences: Mapped[dict] = mapped_column(_json_type, default=dict, server_default="{}", nullable=False)
    plan_code: Mapped[str] = mapped_column(String(32), default="trial", nullable=False, index=True)
    plan_title: Mapped[str] = mapped_column(String(120), default="هدیه ثبت‌نام", nullable=False)
    tokens_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_remaining: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_used_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    plan_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # What the code is allowed to unlock: login, registration or password recovery.
    purpose: Mapped[str] = mapped_column(
        String(24), default="login", server_default="login", nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    plan_code: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_granted: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    authority: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    ref_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TokenUsageLog(Base):
    __tablename__ = "token_usage_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    book_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_toman: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_nonce: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserFile(Base):
    __tablename__ = "user_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    # Mutually exclusive category ("image" | "audio" | "file") so storage bytes are never double-counted.
    category: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_context: Mapped[str] = mapped_column(String(48), default="personal_upload", nullable=False)
    chat_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    book_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
