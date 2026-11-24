"""The offline demo stack seeds a useful, searchable synthetic textbook."""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import seed as seed_module
from app.db.base import Base
from app.models.curriculum import Book, BookPage
from app.services import retrieval_service


@pytest.mark.asyncio
async def test_demo_seed_is_repeatable_and_supports_scoped_retrieval(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(seed_module, "engine", engine)
    monkeypatch.setattr(seed_module, "async_session_factory", factory)
    monkeypatch.setattr(seed_module, "get_settings", lambda: SimpleNamespace(demo_mode=True))
    monkeypatch.setattr(retrieval_service, "async_session_factory", factory)
    monkeypatch.setattr(retrieval_service, "get_settings", lambda: SimpleNamespace(demo_mode=True))
    # Auto-publish hotfix: catalog approval is gone, so there is no catalog
    # visibility setting left to patch in curriculum_access.

    try:
        await seed_module.seed_database()
        await seed_module.seed_database()
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(Book)) == 1
            assert await session.scalar(select(func.count()).select_from(BookPage)) == 3

        pages = await retrieval_service.search_textbook(
            "شیب نمودار مکان زمان",
            grade_number=12,
            major_code="math_physics",
            book_id=1,
        )
        assert pages
        assert pages[0]["printed_page_number"] == 10
        assert "سرعت" in pages[0]["full_text"]

        arabic_keyboard_pages = await retrieval_service.search_textbook(
            "شيب نمودار مكان",
            grade_number=12,
            major_code="math_physics",
            book_id=1,
        )
        assert arabic_keyboard_pages
        assert arabic_keyboard_pages[0]["printed_page_number"] == 10
    finally:
        await engine.dispose()
