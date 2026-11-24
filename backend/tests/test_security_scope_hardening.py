"""Regression tests for fail-closed student sessions and grade profiles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.api import dependencies
from app.db.base import Base
from app.models.auth import User, UserSession


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-user-token", b"signed-test-token")],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
        }
    )


@pytest.fixture
async def auth_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth-hardening.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=[User.__table__, UserSession.__table__],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        user = User(
            id="student-hardening-1",
            phone_number="09120000001",
            role="student",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        yield session, user
    await engine.dispose()


def _patch_token(monkeypatch, user_id: str, nonce: str = "test-nonce") -> None:
    monkeypatch.setattr(
        dependencies,
        "parse_user_session_token",
        lambda _token: (user_id, nonce, int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())),
    )


@pytest.mark.asyncio
async def test_signed_token_without_database_session_is_rejected(auth_session, monkeypatch):
    session, user = auth_session
    _patch_token(monkeypatch, user.id)

    resolved = await dependencies._resolve_user_from_request(_request(), session)

    assert resolved is None


@pytest.mark.asyncio
async def test_revoked_database_session_is_rejected(auth_session, monkeypatch):
    session, user = auth_session
    session.add(
        UserSession(
            user_id=user.id,
            token_nonce="test-nonce",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            revoked_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    _patch_token(monkeypatch, user.id)

    resolved = await dependencies._resolve_user_from_request(_request(), session)

    assert resolved is None


@pytest.mark.asyncio
async def test_expired_database_session_is_rejected_even_with_valid_signed_token(auth_session, monkeypatch):
    session, user = auth_session
    session.add(
        UserSession(
            user_id=user.id,
            token_nonce="test-nonce",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )
    await session.commit()
    _patch_token(monkeypatch, user.id)

    resolved = await dependencies._resolve_user_from_request(_request(), session)

    assert resolved is None


@pytest.mark.asyncio
async def test_live_database_session_resolves_user(auth_session, monkeypatch):
    session, user = auth_session
    now = datetime.now(timezone.utc)
    session.add(
        UserSession(
            user_id=user.id,
            token_nonce="test-nonce",
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()
    _patch_token(monkeypatch, user.id)

    resolved = await dependencies._resolve_user_from_request(_request(), session)

    assert resolved is not None
    assert resolved.id == user.id


def test_grade_scope_fails_closed_when_production_profile_is_missing(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: type("Settings", (), {"demo_mode": False, "require_student_grade_profile": True})(),
    )
    user = type("UserStub", (), {"grade_level": None})()

    with pytest.raises(HTTPException) as error:
        dependencies.enforce_student_grade_level(user, 10)

    assert error.value.status_code == 409


def test_grade_scope_allows_unprofiled_demo_user(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: type("Settings", (), {"demo_mode": True, "require_student_grade_profile": True})(),
    )
    user = type("UserStub", (), {"grade_level": None})()

    dependencies.enforce_student_grade_level(user, 10)


def test_grade_scope_rejects_invalid_or_higher_grade(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: type("Settings", (), {"demo_mode": False, "require_student_grade_profile": True})(),
    )

    with pytest.raises(HTTPException) as invalid:
        dependencies.enforce_student_grade_level(type("UserStub", (), {"grade_level": 13})(), 10)
    assert invalid.value.status_code == 409

    with pytest.raises(HTTPException) as higher:
        dependencies.enforce_student_grade_level(type("UserStub", (), {"grade_level": 9})(), 10)
    assert higher.value.status_code == 422


@pytest.mark.asyncio
async def test_guardian_role_cannot_use_student_dependency(auth_session, monkeypatch):
    session, user = auth_session
    user.role = "guardian"
    await session.commit()
    monkeypatch.setattr(dependencies, "_resolve_user_from_request", lambda *_args: _return_user(user))

    with pytest.raises(HTTPException) as error:
        await dependencies.require_student(_request(), session)

    assert error.value.status_code == 403


async def _return_user(user):
    return user


@pytest.mark.parametrize("role", ["teacher", "admin"])
def test_teacher_admin_preview_does_not_require_student_grade_profile(monkeypatch, role):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: type("Settings", (), {"demo_mode": False, "require_student_grade_profile": True})(),
    )
    user = type("UserStub", (), {"role": role, "grade_level": None})()

    # Preview access still relies on the normal book/branch/capability checks.
    # This helper only avoids treating a teacher/admin as an unprofiled student.
    dependencies.enforce_student_grade_level(user, 12)
