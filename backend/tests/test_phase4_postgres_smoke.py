"""Opt-in PostgreSQL smoke test for Phase 4 retrieval (real `to_tsvector` path).

Runs only when PHASE4_PG_URL is set, e.g.
  PHASE4_PG_URL=postgresql+asyncpg://user:pass@host/db pytest tests/test_phase4_postgres_smoke.py

It creates and drops its own schema objects via `create_all`/`drop_all` on the
given database, so point it at a disposable database only.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.seed import seed_curriculum_taxonomy, seed_grades, seed_majors
from app.models.concepts import ConceptLink
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major, PageStatus
from app.services import multi_grade_rag, retrieval_service

PG_URL = os.environ.get("PHASE4_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set PHASE4_PG_URL to run the PostgreSQL smoke test")


@pytest.mark.asyncio
async def test_multi_grade_lexical_search_on_postgres(monkeypatch):
    engine = create_async_engine(PG_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            await seed_grades(session)
            await seed_majors(session)
            await seed_curriculum_taxonomy(session)
            major = await session.scalar(select(Major).where(Major.code == "math_physics"))
            books = {}
            for number, chapter, text in (
                (10, 3, "نیرو و حرکت، نیرو کشش یا هل دادن است"),
                (11, 2, "نیرو در فیزیک یازدهم با شتاب رابطه دارد"),
                (12, 1, "قانون دوم نیوتون: نیروی خالص برابر جرم ضربدر شتاب است"),
            ):
                grade = await session.scalar(select(Grade).where(Grade.number == number))
                book = Book(title=f"فیزیک {number}", grade_id=grade.id, major_id=major.id,
                            pdf_file_path="/tmp/x.pdf", total_pdf_pages=3, status=BookStatus.ready, catalog_status="approved")
                session.add(book)
                await session.flush()
                session.add(BookPage(book_id=book.id, pdf_page_index=1, printed_page_number=40 + number,
                                     chapter_number=chapter, chapter_title=f"فصل {chapter}",
                                     markdown_content=text, page_image_path="/tmp/x.png",
                                     status=PageStatus.done))
                books[number] = book
            session.add(ConceptLink(source_book_id=books[10].id, source_chapter=3,
                                    target_book_id=books[12].id, target_chapter=1,
                                    relation="same_concept", label_fa="نیرو"))
            await session.commit()
            ids = {n: b.id for n, b in books.items()}

        monkeypatch.setattr(retrieval_service, "async_session_factory", factory)
        monkeypatch.setattr(
            retrieval_service, "get_settings",
            lambda: SimpleNamespace(demo_mode=False, vector_backend="qdrant",
                                    qdrant_collection="smoke", qdrant_url="http://127.0.0.1:9"),
        )

        async def no_vectors(*args, **kwargs):
            raise RuntimeError("vector backend intentionally unavailable")

        monkeypatch.setattr(retrieval_service, "_search_qdrant_scopes", no_vectors)

        async with factory() as session:
            # Phase 10 contract: the caller passes server-authorized book_ids only
            # (locked by test_phase10_auto_publish.py); the seeded ready books are
            # exactly that authorized scope here.
            result = await multi_grade_rag.search_multi_grade(
                session, "نیرو", grade_numbers=[10, 11, 12],
                book_ids=[ids[10], ids[11], ids[12]], top_k=6, expand_links=False,
            )
            grades = {item["grade_number"] for item in result["results"]}
            assert len(grades) >= 2, grades
            strict = await multi_grade_rag.search_multi_grade(
                session, "نیرو", grade_numbers=[11], book_ids=[ids[11]], expand_links=False
            )
            assert {item["grade_number"] for item in strict["results"]} == {11}
            expanded = await multi_grade_rag.search_multi_grade(
                session, "قانون", grade_numbers=[10, 12],
                book_ids=[ids[10], ids[12]], top_k=4, expand_links=True
            )
            assert any(item["grade_number"] == 12 for item in expanded["results"])
            assert ids[10] and ids[12]
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
