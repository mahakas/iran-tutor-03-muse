"""The PostgreSQL lexical query can be compiled without a running database."""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.services import retrieval_service


@pytest.mark.asyncio
async def test_postgres_search_query_is_scoped_and_uses_full_text_search(monkeypatch):
    class FakeResult:
        @staticmethod
        def all():
            return []

    class FakeSession:
        statement = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            self.statement = statement
            return FakeResult()

    fake_session = FakeSession()
    monkeypatch.setattr(retrieval_service, "async_session_factory", lambda: fake_session)

    result = await retrieval_service._search_postgres(
        "شتاب",
        grade_number=12,
        major_code="math_physics",
        book_id=5,
        limit=20,
    )

    compiled = str(fake_session.statement.compile(dialect=postgresql.dialect()))
    assert result == []
    assert "to_tsvector" in compiled
    assert "websearch_to_tsquery" in compiled
    assert "book_pages.status" in compiled
    assert "books.id" in compiled
    assert "grades.number" in compiled
    assert "books.id =" in compiled
    assert "majors.code =" not in compiled


def test_persian_lexical_query_strips_stopwords_and_normalizes_arabic_letters():
    expr = retrieval_service.build_lexical_query("شيب نمودار مکان‌زمان چه مفهومي دارد؟")
    assert expr == "شیب OR نمودار OR مکان OR زمان"
    assert "چه" not in expr
    assert "دارد" not in expr


@pytest.mark.asyncio
async def test_pgvector_search_compiles_scoped_cosine_query_and_routes_when_enabled(monkeypatch):
    from types import SimpleNamespace

    observed = {}

    class FakeMappingResult:
        @staticmethod
        def mappings():
            class _Rows:
                @staticmethod
                def all():
                    return [
                        {
                            "book_id": 2,
                            "book_title": "فیزیک ۳",
                            "grade_number": 12,
                            "major_code": "math_physics",
                            "pdf_page_index": 15,
                            "printed_page_number": 4,
                            "chapter_number": 1,
                            "chapter_title": "حرکت بر خط راست",
                            "markdown_content": "سرعت متوسط برابر تغییر مکان تقسیم بر زمان است.",
                            "visual_elements": [],
                            "score": 0.91,
                        }
                    ]

            return _Rows()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement, params):
            observed["sql"] = str(statement.compile(dialect=postgresql.dialect()))
            observed["params"] = params
            return FakeMappingResult()

    async def fake_embed_gateway(*, ctx, texts, model=None, session=None, **kwargs):
        return SimpleNamespace(content=[[0.5, 0.5] for _ in texts], audit_id=None)

    async def no_lexical(*args, **kwargs):
        return []

    monkeypatch.setattr(retrieval_service, "async_session_factory", lambda: FakeSession())
    monkeypatch.setattr(retrieval_service, "embed_via_gateway", fake_embed_gateway)
    monkeypatch.setattr(retrieval_service, "_search_postgres", no_lexical)
    monkeypatch.setattr(
        retrieval_service,
        "get_settings",
        lambda: SimpleNamespace(demo_mode=False, vector_backend="pgvector", embedding_model="test-embedding"),
    )

    results = await retrieval_service.search_textbook(
        "سرعت متوسط چیست؟",
        grade_number=12,
        major_code="electronics",
        book_id=2,
        top_k=5,
    )

    assert "book_page_embeddings" in observed["sql"]
    assert "<=>" in observed["sql"]
    # Auto-publish hotfix: the catalog gate is gone; the ready-status filter stays.
    assert "catalog_status" not in observed["sql"]
    assert "b.status = 'ready'" in observed["sql"]
    assert observed["params"]["book_id"] == 2
    assert observed["params"]["grade_number"] == 12
    assert "major_code" not in observed["params"]
    assert "AND e.major_code =" not in observed["sql"]
    assert len(results) == 1
    assert results[0]["pdf_page_index"] == 15
