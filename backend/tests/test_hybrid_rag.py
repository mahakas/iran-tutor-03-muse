"""Hybrid rank fusion tests do not require Postgres, Qdrant, or API access."""

from __future__ import annotations

from app.services.retrieval_service import merge_hybrid_results


def _page(page_number: int, score: float) -> dict:
    return {
        "book_id": 1,
        "pdf_page_index": page_number,
        "printed_page_number": page_number - 1,
        "score": score,
        "full_text": f"صفحهٔ {page_number}",
    }


def test_reciprocal_rank_fusion_promotes_pages_ranked_by_both_channels():
    vector = [_page(2, 0.91), _page(1, 0.72)]
    lexical = [_page(3, 0.38), _page(2, 0.27), _page(1, 0.11)]

    results = merge_hybrid_results(vector, lexical, top_k=3)

    assert [page["pdf_page_index"] for page in results] == [2, 1, 3]
    assert results[0]["vector_rank"] == 1
    assert results[0]["lexical_rank"] == 2
    assert results[0]["vector_score"] == 0.91
    assert results[0]["lexical_score"] == 0.27


def test_hybrid_fusion_keeps_lexical_only_matches():
    lexical = [_page(7, 0.25)]

    results = merge_hybrid_results([], lexical, top_k=5)

    assert len(results) == 1
    assert results[0]["pdf_page_index"] == 7
    assert results[0]["lexical_rank"] == 1
    assert "vector_rank" not in results[0]
