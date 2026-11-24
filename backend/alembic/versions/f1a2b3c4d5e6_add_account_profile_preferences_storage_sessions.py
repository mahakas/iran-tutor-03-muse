"""add account profile fields, preferences, user sessions, user files, and plan storage quotas

Revision ID: f1a2b3c4d5e6
Revises: e5a7c1d39b2f
Create Date: 2026-11-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e5a7c1d39b2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("storage_quota_bytes", sa.BigInteger(), server_default="104857600", nullable=False),
    )
    op.execute("UPDATE plans SET storage_quota_bytes = 104857600 WHERE code = 'normal'")
    op.execute("UPDATE plans SET storage_quota_bytes = 262144000 WHERE code = 'pro'")
    op.execute("UPDATE plans SET storage_quota_bytes = 1073741824 WHERE code = 'vip'")

    op.add_column(
        "billing_settings",
        sa.Column("starter_storage_bytes", sa.BigInteger(), server_default="26214400", nullable=False),
    )

    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column("users", sa.Column("first_name", sa.String(length=80), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=80), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("avatar_path", sa.String(length=512), nullable=True))
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=32), server_default="student", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("preferences", json_type, server_default="{}", nullable=False),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_nonce", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("token_nonce", name="uq_user_sessions_token_nonce"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_token_nonce", "user_sessions", ["token_nonce"])

    op.create_table(
        "user_files",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source_context", sa.String(length=48), server_default="personal_upload", nullable=False),
        sa.Column("chat_session_id", sa.String(length=36), nullable=True),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_user_files_user_id", "user_files", ["user_id"])
    op.create_index("ix_user_files_category", "user_files", ["category"])
    op.create_index("ix_user_files_chat_session_id", "user_files", ["chat_session_id"])
    op.create_index("ix_user_files_created_at", "user_files", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_user_files_created_at", table_name="user_files")
    op.drop_index("ix_user_files_chat_session_id", table_name="user_files")
    op.drop_index("ix_user_files_category", table_name="user_files")
    op.drop_index("ix_user_files_user_id", table_name="user_files")
    op.drop_table("user_files")

    op.drop_index("ix_user_sessions_token_nonce", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_column("users", "preferences")
    op.drop_column("users", "role")
    op.drop_column("users", "avatar_path")
    op.drop_column("users", "email")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")

    op.drop_column("billing_settings", "starter_storage_bytes")
    op.drop_column("plans", "storage_quota_bytes")
