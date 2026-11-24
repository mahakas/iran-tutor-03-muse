"""Pure tests for exact curriculum filters and grounded tutor prompts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import retrieval_service, tutor_service


def test_page_embedding_text_includes_scientific_visual_description():
    text = retrieval_service.page_embedding_text(
        "رابطهٔ مکان و زمان",
        [
            {
                "label": "شکل ۱-۲",
                "type": "نمودار مکان-زمان",
                "scientific_description": "محور افقی زمان و محور عمودی مکان است.",
            }
        ],
    )
    assert "رابطهٔ مکان و زمان" in text
    assert "نمودار مکان-زمان" in text
    assert "محور افقی زمان" in text


def test_curriculum_filter_uses_exact_book_edition_as_the_hard_scope():
    query_filter = retrieval_service.make_textbook_filter(
        grade_number=12, major_code="electronics", book_id=7
    )
    conditions = {condition.key: condition.match.value for condition in query_filter.must}
    assert conditions == {"grade_number": 12, "book_id": 7}


def test_general_grade_filter_uses_exact_book_edition_without_legacy_major():
    query_filter = retrieval_service.make_textbook_filter(
        grade_number=5, major_code=None, book_id=3
    )
    conditions = {condition.key: condition.match.value for condition in query_filter.must}
    assert conditions == {"grade_number": 5, "book_id": 3}


def test_major_filter_remains_available_only_for_legacy_unbound_search():
    query_filter = retrieval_service.make_textbook_filter(
        grade_number=12, major_code="math_physics", book_id=None
    )
    conditions = {condition.key: condition.match.value for condition in query_filter.must}
    assert conditions == {"grade_number": 12, "major_code": "math_physics"}


def test_tutor_prompt_includes_grade_and_source_context():
    messages = tutor_service.build_tutor_messages(
        query="چرا شیب نمودار سرعت-زمان شتاب است؟",
        grade_number=12,
        context="فیزیک ۳، فصل حرکت بر خط راست، صفحه چاپی ۱۴",
    )
    assert messages[0]["role"] == "system"
    assert "فقط از متن منابع" in messages[0]["content"]
    assert "پایهٔ دانش‌آموز: 12" in messages[1]["content"]
    assert "صفحه چاپی ۱۴" in messages[1]["content"]
    assert "شیب نمودار سرعت-زمان" in messages[1]["content"]


def test_source_reference_discloses_missing_printed_page_number():
    reference = tutor_service._source_reference(
        {
            "book_title": "فیزیک ۳",
            "chapter_number": 1,
            "chapter_title": "حرکت بر خط راست",
            "pdf_page_index": 8,
            "printed_page_number": None,
        }
    )
    assert "فیزیک ۳" in reference
    assert "فصل 1: حرکت بر خط راست" in reference
    assert "شمارهٔ چاپی نامشخص" in reference
    assert "صفحهٔ PDF 8" in reference


def test_source_reference_includes_edition_scope_and_publisher():
    reference = tutor_service._source_reference(
        {
            "book_title": "فیزیک ۳",
            "grade_number": 12,
            "branch_titles": ["نظری"],
            "field_titles": ["ریاضی‌فیزیک"],
            "academic_year_code": "1405",
            "edition_label": "چاپ سوم",
            "print_year": 1405,
            "publisher": "شرکت چاپ و نشر کتاب‌های درسی",
            "chapter_number": 1,
            "chapter_title": "حرکت بر خط راست",
            "pdf_page_index": 8,
            "printed_page_number": 14,
        }
    )
    assert "شاخه نظری" in reference
    assert "رشته ریاضی‌فیزیک" in reference
    assert "سال تحصیلی 1405" in reference
    assert "چاپ سوم" in reference
    assert "چاپ 1405" in reference
    assert "ناشر شرکت چاپ و نشر کتاب‌های درسی" in reference
    assert "صفحهٔ 14" in reference


@pytest.mark.asyncio
async def test_tutor_returns_no_guess_when_no_textbook_matches(monkeypatch):
    async def no_pages(*args, **kwargs):
        return []

    async def should_not_call_llm(*args, **kwargs):
        raise AssertionError("LLM must not be called without retrieved evidence")

    async def should_not_reach_gateway(*args, **kwargs):
        raise AssertionError("AI gateway must not be called without retrieved evidence")

    monkeypatch.setattr(tutor_service, "search_textbook", no_pages)
    monkeypatch.setattr(
        tutor_service, "complete_text_via_gateway", should_not_reach_gateway
    )

    response = await tutor_service.answer_from_textbook(
        query="سوال ناموجود", grade_number=12, major_code="math_physics", book_id=1
    )

    assert response["sources"] == []
    assert response["retrieved_count"] == 0
    assert "منبع کافی" in response["answer"]


@pytest.mark.asyncio
async def test_tutor_adds_sources_from_retrieved_pages(monkeypatch):
    pages = [
        {
            "book_id": 4,
            "book_title": "فیزیک ۳",
            "grade_number": 12,
            "major_code": "math_physics",
            "chapter_number": 1,
            "chapter_title": "حرکت بر خط راست",
            "pdf_page_index": 15,
            "printed_page_number": 14,
            "full_text": "شیب نمودار مکان-زمان برابر سرعت است.",
            "score": 0.87,
        }
    ]

    async def matching_pages(*args, **kwargs):
        return pages

    async def fake_gateway(*, ctx, messages, model=None, session=None, **kwargs):
        assert model == "tutor-test-model"
        assert "شیب نمودار مکان-زمان" in messages[1]["content"]
        assert ctx.feature_key == "chat"
        assert ctx.rag_hit_count == 1
        return SimpleNamespace(
            content="شیب نمودار مکان-زمان نشان‌دهندهٔ سرعت است.", audit_id="audit-test"
        )

    monkeypatch.setattr(tutor_service, "search_textbook", matching_pages)
    monkeypatch.setattr(tutor_service, "complete_text_via_gateway", fake_gateway)
    monkeypatch.setattr(
        tutor_service, "get_settings", lambda: SimpleNamespace(tutor_model="tutor-test-model")
    )

    response = await tutor_service.answer_from_textbook(
        query="شیب چه چیزی را نشان می‌دهد؟",
        grade_number=12,
        major_code="math_physics",
        book_id=4,
    )

    assert len(response["sources"]) == 1
    assert "صفحهٔ 14" in response["sources"][0]["citation"]
    assert "منابع:" in response["answer"]


@pytest.mark.asyncio
async def test_qdrant_search_applies_curriculum_filter_without_external_services(monkeypatch):
    from qdrant_client import AsyncQdrantClient, models

    client = AsyncQdrantClient(":memory:")
    old_client = retrieval_service._qdrant
    retrieval_service._qdrant = client
    settings = retrieval_service.get_settings()
    try:
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
        )
        await client.upsert(
            collection_name=settings.qdrant_collection,
            points=[
                models.PointStruct(
                    id=1,
                    vector=[1.0, 0.0],
                    payload={
                        "book_id": 8,
                        "grade_number": 12,
                        "major_code": "general",
                        "book_title": "کتاب فنی",
                        "pdf_page_index": 1,
                        "embedding_model": settings.embedding_model,
                    },
                ),
                models.PointStruct(
                    id=2,
                    vector=[0.99, 0.01],
                    payload={
                        "book_id": 8,
                        "grade_number": 12,
                        "major_code": "experimental",
                        "book_title": "فیزیک ۳",
                        "pdf_page_index": 2,
                        "embedding_model": settings.embedding_model,
                    },
                ),
                models.PointStruct(
                    id=3,
                    vector=[0.98, 0.02],
                    payload={
                        "book_id": 9,
                        "grade_number": 11,
                        "major_code": "math_physics",
                        "book_title": "فیزیک ۲",
                        "pdf_page_index": 3,
                        "embedding_model": settings.embedding_model,
                    },
                ),
                # A closer vector from an older embedding model must not
                # occupy the top-k slot for a query using the current model.
                models.PointStruct(
                    id=4,
                    vector=[1.0, 0.0],
                    payload={
                        "book_id": 8,
                        "grade_number": 12,
                        "major_code": "math_physics",
                        "book_title": "فیزیک ۳",
                        "pdf_page_index": 4,
                        "embedding_model": "old-embedding-model",
                    },
                ),
            ],
            wait=True,
        )

        async def fake_embed_gateway(*, ctx, texts, model=None, session=None, **kwargs):
            return SimpleNamespace(content=[[1.0, 0.0] for _ in texts], audit_id=None)

        async def no_lexical_results(*args, **kwargs):
            return []

        async def passthrough_verified(points, *, scopes, expected_embedding_model=None):
            return [
                {**(point.payload or {}), "score": float(point.score)}
                for point in points
            ]

        monkeypatch.setattr(retrieval_service, "embed_via_gateway", fake_embed_gateway)
        monkeypatch.setattr(retrieval_service, "_search_postgres", no_lexical_results)
        # This test isolates Qdrant's exact curriculum filter. Current-page
        # approval/snapshot reconciliation is covered by the DB-backed tests.
        monkeypatch.setattr(retrieval_service, "_filter_qdrant_points", passthrough_verified)
        results = await retrieval_service.search_textbook(
            "شتاب چیست؟",
            grade_number=12,
            major_code="electronics",
            book_id=8,
            top_k=1,
        )
        assert len(results) == 1
        assert results[0]["book_id"] == 8
        assert results[0]["major_code"] == "general"
        assert results[0]["pdf_page_index"] == 1
    finally:
        await client.close()
        retrieval_service._qdrant = old_client
