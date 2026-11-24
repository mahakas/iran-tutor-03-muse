"""Phase 9: smart podcast episodes (NotebookLM Audio Overview style).

Adds four purely additive tables:

- ``podcast_episodes``   — source snapshot, validated script, transcript, private
                          audio path, background-job status/progress/heartbeat.
- ``podcast_segments``   — dialogue turns with speaker + per-segment audio + timing.
- ``podcast_feedbacks``  — thumbs up/down with anonymized quality reasons.
- ``podcast_questions``  — "Ask the hosts" grounded Q&A history.

No existing table or row is touched (``audio_cache`` is reused read/write by
content-addressed keys and stays as-is). Downgrade drops only the new tables.

Revision ID: d0e1f2a3b4c5
Revises: c8d9e0f1a2b3
Create Date: 2026-11-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "podcast_episodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="deep_dive"),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="fa"),
        sa.Column("length", sa.String(length=8), nullable=False, server_default="standard"),
        sa.Column("custom_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_snapshot_json", JSON_TYPE, nullable=False),
        sa.Column("script_json", JSON_TYPE, nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False, server_default=""),
        sa.Column("audio_file_path", sa.String(length=512), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_stage", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("generation_settings_json", JSON_TYPE, nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_podcast_episodes_user_id", "podcast_episodes", ["user_id"])
    op.create_index("ix_podcast_episodes_book_id", "podcast_episodes", ["book_id"])
    op.create_index("ix_podcast_episodes_user_status", "podcast_episodes", ["user_id", "status"])
    op.create_index("ix_podcast_episodes_status", "podcast_episodes", ["status"])

    op.create_table(
        "podcast_segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "episode_id",
            sa.Integer(),
            sa.ForeignKey("podcast_episodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("speaker", sa.String(length=16), nullable=False, server_default="host_a"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_refs_json", JSON_TYPE, nullable=False),
        sa.Column("audio_file_path", sa.String(length=512), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("start_time", sa.Float(), nullable=True),
        sa.Column("end_time", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_podcast_segments_episode_id", "podcast_segments", ["episode_id"])
    op.create_index("ix_podcast_segments_episode_position", "podcast_segments", ["episode_id", "position"])

    op.create_table(
        "podcast_feedbacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "episode_id",
            sa.Integer(),
            sa.ForeignKey("podcast_episodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("liked", sa.Boolean(), nullable=False),
        sa.Column("reasons_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("episode_id", "user_id", name="uq_podcast_feedback_episode_user"),
    )
    op.create_index("ix_podcast_feedbacks_episode_id", "podcast_feedbacks", ["episode_id"])
    op.create_index("ix_podcast_feedbacks_user_id", "podcast_feedbacks", ["user_id"])

    op.create_table(
        "podcast_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "episode_id",
            sa.Integer(),
            sa.ForeignKey("podcast_episodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("citations_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_podcast_questions_episode_id", "podcast_questions", ["episode_id"])
    op.create_index("ix_podcast_questions_episode_created", "podcast_questions", ["episode_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_podcast_questions_episode_created", table_name="podcast_questions")
    op.drop_index("ix_podcast_questions_episode_id", table_name="podcast_questions")
    op.drop_table("podcast_questions")
    op.drop_index("ix_podcast_feedbacks_user_id", table_name="podcast_feedbacks")
    op.drop_index("ix_podcast_feedbacks_episode_id", table_name="podcast_feedbacks")
    op.drop_table("podcast_feedbacks")
    op.drop_index("ix_podcast_segments_episode_position", table_name="podcast_segments")
    op.drop_index("ix_podcast_segments_episode_id", table_name="podcast_segments")
    op.drop_table("podcast_segments")
    op.drop_index("ix_podcast_episodes_status", table_name="podcast_episodes")
    op.drop_index("ix_podcast_episodes_user_status", table_name="podcast_episodes")
    op.drop_index("ix_podcast_episodes_book_id", table_name="podcast_episodes")
    op.drop_index("ix_podcast_episodes_user_id", table_name="podcast_episodes")
    op.drop_table("podcast_episodes")
