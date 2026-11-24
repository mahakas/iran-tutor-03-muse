"""Phase 04C: quota accounting integrity — dedupe user_quotas and enforce one
row per (user_id, feature_key).

Why (evidence from the Phase 04C PostgreSQL QA, darsyar_qa04c):
* `user_quotas` had no uniqueness on (user_id, feature_key). Concurrent
  first-touch quota writes (worker session + API sessions) each INSERTed their
  own row, splitting the counters across duplicates so `enforce_ai_quota`
  read an arbitrary one.
* `record_ai_usage` incremented ORM attributes and wrote absolute values, so
  overlapping writers lost updates (final counter 200/3 instead of 1200/12 in
  the repro).

This migration only restores the invariant "one row per (user_id,
feature_key)": duplicates are merged by SUMMING their counters (usage already
accounted must not disappear). The write-path fix (atomic increments) lives in
`app/services/quota_service.py`.

Reversible: dropping the index restores the old (unsafe) shape; merged rows
cannot be un-merged, so downgrade restores the index only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f9"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "sqlite":
        # Merge duplicate (user_id, feature_key) rows onto the newest row and
        # drop the rest. PostgreSQL-only SQL (DISTINCT ON); SQLite test DBs
        # never contain duplicates (single-connection suite).
        conn.execute(sa.text(
            """
            WITH keep AS (
                SELECT DISTINCT ON (user_id, feature_key) id, user_id, feature_key
                FROM user_quotas
                ORDER BY user_id, feature_key, updated_at DESC NULLS LAST, id DESC
            ),
            sums AS (
                SELECT user_id, feature_key,
                       SUM(daily_tokens_used)   AS d_tokens,
                       SUM(monthly_tokens_used) AS m_tokens,
                       SUM(daily_requests_used) AS d_requests
                FROM user_quotas
                GROUP BY user_id, feature_key
            )
            UPDATE user_quotas q
            SET daily_tokens_used   = s.d_tokens,
                monthly_tokens_used = s.m_tokens,
                daily_requests_used = s.d_requests
            FROM keep k
            JOIN sums s ON s.user_id = k.user_id AND s.feature_key = k.feature_key
            WHERE q.id = k.id
            """
        ))
        conn.execute(sa.text(
            """
            WITH keep AS (
                SELECT DISTINCT ON (user_id, feature_key) id, user_id, feature_key
                FROM user_quotas
                ORDER BY user_id, feature_key, updated_at DESC NULLS LAST, id DESC
            )
            DELETE FROM user_quotas q
            USING keep k
            WHERE q.user_id = k.user_id
              AND q.feature_key = k.feature_key
              AND q.id <> k.id
            """
        ))
    op.create_index(
        "ux_user_quotas_user_feature",
        "user_quotas",
        ["user_id", "feature_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_user_quotas_user_feature", table_name="user_quotas")
