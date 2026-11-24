"""Phase 1 step C: ingestion compare/preview CLI.

Run from `backend/`, e.g.:
    .venv\\Scripts\\python scripts\\test_ingest.py --pdf data\\physics12.pdf --start 5 --end 9 --model both --no-db
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.ingestion_service import (  # noqa: E402
    STORAGE_DIR,
    ingest_book_pages,
    model_tag,
)
from app.services.preview import (  # noqa: E402
    render_compare_preview,
    render_single_preview,
)


def _status_value(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def build_pages(
    results: dict[str, dict[int, dict[str, Any]]],
    images: dict[int, str],
    idx_list: list[int],
    model: str,
) -> list[dict[str, Any]]:
    pages = []
    for idx in idx_list:
        r = results[model][idx]
        pages.append(
            {
                "pdf_page_index": idx,
                "image_path": images[idx],
                "printed_page_number": r.get("printed_page_number"),
                "chapter_number": r.get("chapter_number"),
                "chapter_title": r.get("chapter_title"),
                "status": _status_value(r.get("status", "unknown")),
                "warnings": r.get("warnings", []),
                "markdown": r.get("markdown", ""),
                "visual_elements": r.get("visual_elements", []),
            }
        )
    return pages


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Compare vision extraction models on a PDF range.")
    parser.add_argument("--pdf", required=True, help="path to the PDF")
    parser.add_argument("--start", type=int, required=True, help="first page, 1-based")
    parser.add_argument("--end", type=int, required=True, help="last page, 1-based (inclusive)")
    parser.add_argument("--model", choices=["A", "B", "both"], default="both")
    parser.add_argument("--book-id", default=None, help="storage folder id (default: pdf stem)")
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="no-op: compare mode never writes to the database",
    )
    args = parser.parse_args()

    pdf = Path(args.pdf).resolve()
    if not pdf.exists():
        print(f"ERROR: PDF not found: {pdf}")
        return 2

    book_id = args.book_id or pdf.stem
    model_map = {"A": settings.vision_model_a, "B": settings.vision_model_b}
    models = [model_map[m] for m in (["A", "B"] if args.model == "both" else [args.model])]

    result = asyncio.run(
        ingest_book_pages(
            pdf_path=pdf,
            book_id=book_id,
            grade_number=None,
            major_code=None,
            book_title=pdf.stem,
            start_page=args.start,
            end_page=args.end,
            models=models,
            use_db=False,
        )
    )

    idx_list = list(range(args.start, args.end + 1))
    images = result["images"]
    results = result["results"]
    totals = result["totals"]
    book_dir = STORAGE_DIR / "books" / str(book_id)
    outputs: dict[str, Path] = {}

    if len(models) == 2:
        model_a, model_b = models
        pages_a = build_pages(results, images, idx_list, model_a)
        pages_b = build_pages(results, images, idx_list, model_b)
        key_a, key_b = model_tag(model_a), model_tag(model_b)
        summary = {
            key_a: totals[model_a],
            key_b: totals[model_b],
        }
        compare_path = book_dir / "compare.html"
        render_compare_preview(book_id, model_a, model_b, pages_a, pages_b, summary, compare_path)
        outputs["compare"] = compare_path
    else:
        model = models[0]
        tag = model_tag(model)
        pages = build_pages(results, images, idx_list, model)
        preview_path = book_dir / f"preview_{tag}.html"
        render_single_preview(book_id, tag, pages, preview_path)
        outputs["preview"] = preview_path

    print("\n=== SUMMARY ===")
    for model in models:
        t = totals[model]
        print(
            f"{model}: tokens={t['tokens']} time={t['latency']:.2f}s "
            f"warnings={t['warnings']} pages={t['pages']} "
            f"done={t['done']} needs_review={t['needs_review']} failed={t['failed']}"
        )
    for kind, path in outputs.items():
        print(f"{kind} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
