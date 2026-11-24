"""Phase 04C-A regression tests: the AI-quota pre-call gate must never leave a
pending ``user_quotas`` INSERT inside the caller's transaction.

Root cause of the PostgreSQL UI stall (episode stuck at progress 15):
``enforce_ai_quota`` -> ``get_or_create_quota`` flushed a brand-new quota row
inside the podcast worker's long-lived transaction. The Phase 04C detached
accounting session then ran ``increment_quota_counters`` (INSERT .. ON CONFLICT
DO UPDATE) for the same (user_id, feature_key) and waited forever on that
uncommitted unique-index entry, while the worker waited on the accounting
session -> permanent self-deadlock, no TTS call, no progress.

Test 1 (any dialect): after ``enforce_ai_quota`` the session must have no
pending quota writes.
Test 2 (opt-in PostgreSQL, PODCAST_PG_URL): while a caller session holds the
gate open (uncommitted), the accounting upsert from a second session must
still commit within a timeout. Before the fix this times out (blocked on the
pending unique-index entry); after the fix the gate is read-only and the
upsert commits immediately.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.seed import seed_billing_settings, seed_plans
from app.models.auth import User
from app.services import quota_service, rate_limiter

PODCAST_PG_URL = os.environ.get("PODCAST_PG_URL")


async def _make_env(tmp_path, pg_url: str | None = None):
    if pg_url:
        engine = create_async_engine(pg_url)
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'quota_gate.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        await seed_plans(session)
        await seed_billing_settings(session)
        user = User(
            phone_number="09120000090",
            role="student",
            tokens_remaining=10_000,
            plan_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        session.add(user)
        await session.commit()
    return engine, factory


@pytest.mark.asyncio
async def test_enforce_ai_quota_leaves_no_pending_quota_writes(tmp_path):
    engine, factory = await _make_env(tmp_path)
    try:
        async with factory() as session:
            user = await session.scalar(select(User).where(User.phone_number == "09120000090"))
            decision = await quota_service.enforce_ai_quota(session, user=user, feature_key="chat")
            assert decision.allowed is True
            # Phase 04C-A: the gate must be read-only. A pending user_quotas
            # INSERT here deadlocks the detached accounting upsert on PostgreSQL.
            assert not session.new, f"pending inserts: {session.new}"
            assert not session.dirty, f"pending updates: {session.dirty}"
    finally:
        await rate_limiter.close_rate_limiter()
        await engine.dispose()


@pytest.mark.skipif(not PODCAST_PG_URL, reason="set PODCAST_PG_URL to run the PostgreSQL gate-deadlock regression")
@pytest.mark.asyncio
async def test_accounting_upsert_not_blocked_by_gate_session(tmp_path):
    engine, factory = await _make_env(tmp_path, pg_url=PODCAST_PG_URL)
    try:
        async with factory() as caller:
            user = await caller.scalar(select(User).where(User.phone_number == "09120000090"))
            # Pre-fix: this call leaves an uncommitted user_quotas INSERT in the
            # caller's transaction (exactly what the podcast worker did).
            await quota_service.enforce_ai_quota(caller, user=user, feature_key="chat")

            async with factory() as accountant:
                # The detached accounting write must not wait on the gate's
                # transaction. Wait forever == the Phase 04C-A stall.
                await asyncio.wait_for(
                    quota_service.increment_quota_counters(
                        accountant, user_id=user.id, feature_key="chat", tokens=123
                    ),
                    timeout=10,
                )
                await asyncio.wait_for(accountant.commit(), timeout=10)
    finally:
        await rate_limiter.close_rate_limiter()
        await engine.dispose()
