"""add admin_preferences to billing_settings and original_markdown_content to book_pages

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-11-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column(
        "billing_settings",
        sa.Column("admin_preferences", json_type, server_default="{}", nullable=False),
    )
    op.add_column(
        "book_pages",
        sa.Column("original_markdown_content", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("book_pages", "original_markdown_content")
    op.drop_column("billing_settings", "admin_preferences")
