"""Phase 7 hardening: upload content verification, Persian normalization, provider probe audit."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.upload_guard import verify_audio, verify_extension, verify_pdf, safe_suffix
from app.services.retrieval_service import normalize_persian_text


def _rejects(fn, *args) -> bool:
    try:
        fn(*args)
    except HTTPException as exc:
        return exc.status_code == 415
    return False


def test_pdf_extension_requires_pdf_magic():
    assert verify_extension("book.pdf", b"%PDF-1.7 body") == "pdf"
    assert _rejects(verify_extension, "book.pdf", b"<html><script>alert(1)</script>")


def test_text_extensions_reject_binary_content():
    assert verify_extension("notes.md", "# سلام".encode()) == "text"
    assert _rejects(verify_extension, "notes.txt", b"\x7fELF\x00\x00binary")


def test_image_extension_requires_matching_signature():
    assert verify_extension("p.png", b"\x89PNG\r\n\x1a\n0000") == "png"
    assert _rejects(verify_extension, "p.png", b"MZ\x90\x00")


def test_unknown_extension_rejected():
    assert _rejects(verify_extension, "run.exe", b"MZ\x90\x00")


def test_audio_must_match_declared_mime():
    assert verify_audio("audio/mpeg", b"ID3\x03\x00") == "mp3"
    assert verify_audio("audio/wav", b"RIFF\x00\x00\x00\x00WAVEfmt ") == "wav"
    assert _rejects(verify_audio, "audio/mpeg", b"RIFF\x00\x00\x00\x00WAVEfmt ")
    assert _rejects(verify_audio, "audio/ogg", b"<html>")


def test_pdf_magic_guard():
    verify_pdf(b"%PDF-1.4")
    with pytest.raises(HTTPException) as exc:
        verify_pdf(b"not a pdf")
    assert exc.value.status_code == 422
    assert "not a valid PDF" in exc.value.detail


def test_stored_suffix_is_server_chosen():
    assert safe_suffix("pdf") == ".pdf"
    assert safe_suffix("unknown-kind") == ".bin"


def test_persian_normalization_unifies_arabic_variants():
    # Arabic ي/ك and ة must match the Persian forms used in textbooks.
    assert normalize_persian_text("كتاب دانش‌آموز") == normalize_persian_text("کتاب دانش\u200cآموز")
    assert normalize_persian_text("مدرسة") == "مدرسه"
    assert normalize_persian_text("ريشه") == "ریشه"


@pytest.mark.asyncio
async def test_provider_probe_writes_audit_row_without_key(tmp_path, monkeypatch):
    """Admin connectivity probes must be inspectable in ai_audit_logs and never store the key."""
    import httpx
    import app.db.session as db_session_mod
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.base import Base
    from app.models.governance import AiAuditLog
    from app.services import ai_gateway

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'probe.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(db_session_mod, "async_session_factory", factory)
    monkeypatch.setattr(ai_gateway, "async_session_factory", factory)
    async_session_factory = factory

    secret = "sk-test-SECRET-1234"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "m1"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "سلام"}}]})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    result = await ai_gateway.probe_endpoint(
        base_url="https://llm.example.test/v1", api_key=secret, model="m1", run_prompt=True
    )
    assert result["ok"] is True

    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(AiAuditLog).where(AiAuditLog.feature_key == "provider_probe")
            )
        ).all()
        assert rows, "provider_probe audit row was not written"
        row = rows[-1]
        assert row.flag_reason == "provider_probe"
        assert secret not in (row.response_text or "")
        assert secret not in str(row.request_messages_json or "")
        await session.delete(row)
        await session.commit()


@pytest.mark.asyncio
async def test_sql_search_key_matches_arabic_variants_in_database(tmp_path):
    """Real SQL: an Arabic-variant query must match a Persian-spelled title (ilike replacement)."""
    from sqlalchemy import Column, Integer, String, select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.orm import declarative_base

    from app.services.search_normalize import search_key, sql_search_key

    Base = declarative_base()

    class Row(Base):
        __tablename__ = "rows"
        id = Column(Integer, primary_key=True)
        title = Column(String)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'search.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine) as session:
        session.add_all([Row(id=1, title="کتاب فیزیک"), Row(id=2, title="ریاضیات")])
        await session.commit()
        needle = f"%{search_key('كتاب')}%"
        hits = (
            await session.scalars(select(Row.id).where(sql_search_key(Row.title).like(needle)))
        ).all()
        assert hits == [1]
    await engine.dispose()
