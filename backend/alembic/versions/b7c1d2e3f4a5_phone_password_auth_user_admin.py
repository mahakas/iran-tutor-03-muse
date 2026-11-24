"""Phone + password authentication, soft-deleted users, OTP purposes.

Revision ID: b7c1d2e3f4a5
Revises: a4b5c6d7e8f9
Create Date: 2026-11-22

Additive and reversible: no existing row is deleted or rewritten. Existing OTP-only
accounts keep working (`password_hash` stays NULL until they set one) and
`otp_codes.purpose` defaults to `login` for historical codes.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("last_password_change_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("deleted_by", sa.String(length=128), nullable=True))
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])
    op.create_index("ix_users_role", "users", ["role"])

    op.add_column(
        "otp_codes",
        sa.Column(
            "purpose",
            sa.String(length=24),
            nullable=False,
            server_default="login",
        ),
    )
    op.create_index("ix_otp_codes_purpose", "otp_codes", ["purpose"])

    # Backfill provenance so "verified phone" is meaningful for accounts that already
    # completed an OTP login before this release.
    op.execute(
        "UPDATE users SET phone_verified_at = last_login_at "
        "WHERE phone_verified_at IS NULL AND last_login_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_otp_codes_purpose", table_name="otp_codes")
    op.drop_column("otp_codes", "purpose")

    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_column("users", "deleted_by")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "last_password_change_at")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "password_hash")
