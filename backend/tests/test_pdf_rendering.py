"""PDF page-range validation and rendering smoke tests (no LLM or DB required)."""

from __future__ import annotations

import pytest
import pymupdf

from app.services import ingestion_service


def _make_pdf(path, pages: int = 3) -> None:
    document = pymupdf.open()
    try:
        for number in range(1, pages + 1):
            page = document.new_page()
            page.insert_text((72, 72), f"Synthetic page {number}")
        document.save(path)
    finally:
        document.close()


def test_render_pdf_pages_uses_one_based_inclusive_range(tmp_path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    _make_pdf(pdf_path)
    output_root = tmp_path / "storage"
    monkeypatch.setattr(ingestion_service, "STORAGE_DIR", output_root)

    images = ingestion_service.render_pdf_pages(pdf_path, "book-1", 2, 3)

    assert sorted(images) == [2, 3]
    assert all(path.is_file() and path.stat().st_size > 0 for path in images.values())
    assert images[2].name == "page_0002.png"


def test_render_pdf_pages_rejects_out_of_bounds_range(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    _make_pdf(pdf_path, pages=2)

    with pytest.raises(ValueError, match="contains only 2 pages"):
        ingestion_service.render_pdf_pages(pdf_path, "book-1", 1, 3)


@pytest.mark.parametrize(("start_page", "end_page"), [(0, 1), (2, 1)])
def test_render_pdf_pages_rejects_invalid_ranges(tmp_path, start_page, end_page):
    pdf_path = tmp_path / "sample.pdf"
    _make_pdf(pdf_path)

    with pytest.raises(ValueError, match="invalid page range"):
        ingestion_service.render_pdf_pages(pdf_path, "book-1", start_page, end_page)
