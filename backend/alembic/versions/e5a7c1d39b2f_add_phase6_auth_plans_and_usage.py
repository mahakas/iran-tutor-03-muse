"""add phase 6 student auth, plans, payments, and token usage

Revision ID: e5a7c1d39b2f
Revises: d4f8b92a1e3c
Create Date: 2026-11-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5a7c1d39b2f"
down_revision: Union[str, Sequence[str], None] = "d4f8b92a1e3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("price_toman", sa.Integer(), nullable=False),
        sa.Column("token_quota", sa.Integer(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("code", name="uq_plans_code"),
    )
    op.create_index("ix_plans_code", "plans", ["code"])

    op.create_table(
        "billing_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_price_per_1k_toman", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("starter_tokens", sa.Integer(), server_default="15000", nullable=False),
        sa.Column("starter_duration_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("plan_code", sa.String(length=32), server_default="trial", nullable=False),
        sa.Column("plan_title", sa.String(length=120), server_default="هدیه ثبت‌نام", nullable=False),
        sa.Column("tokens_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_remaining", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_used_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("plan_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("phone_number", name="uq_users_phone_number"),
    )
    op.create_index("ix_users_phone_number", "users", ["phone_number"])
    op.create_index("ix_users_plan_code", "users", ["plan_code"])

    op.create_table(
        "otp_codes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_otp_codes_phone_number", "otp_codes", ["phone_number"])

    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plan_code", sa.String(length=32), nullable=False),
        sa.Column("plan_name", sa.String(length=120), nullable=False),
        sa.Column("amount_toman", sa.Integer(), nullable=False),
        sa.Column("tokens_granted", sa.Integer(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("authority", sa.String(length=128), nullable=True),
        sa.Column("ref_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_payment_transactions_user_id", "payment_transactions", ["user_id"])
    op.create_index("ix_payment_transactions_authority", "payment_transactions", ["authority"])

    op.create_table(
        "token_usage_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_toman", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_token_usage_logs_user_id", "token_usage_logs", ["user_id"])
    op.create_index("ix_token_usage_logs_created_at", "token_usage_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_token_usage_logs_created_at", table_name="token_usage_logs")
    op.drop_index("ix_token_usage_logs_user_id", table_name="token_usage_logs")
    op.drop_table("token_usage_logs")
    op.drop_index("ix_payment_transactions_authority", table_name="payment_transactions")
    op.drop_index("ix_payment_transactions_user_id", table_name="payment_transactions")
    op.drop_table("payment_transactions")
    op.drop_index("ix_otp_codes_phone_number", table_name="otp_codes")
    op.drop_table("otp_codes")
    op.drop_index("ix_users_plan_code", table_name="users")
    op.drop_index("ix_users_phone_number", table_name="users")
    op.drop_table("users")
    op.drop_table("billing_settings")
    op.drop_index("ix_plans_code", table_name="plans")
    op.drop_table("plans")
