"""Phase 1 step D: production book ingestion CLI.

Usage (from backend/):
    .venv\\Scripts\\python scripts\\ingest_book.py --pdf data\\physics12.pdf --grade 12 \\
        --major math_physics --title "فیزیک ۳" --start 1 --end 9 \\
        [--force] [--only-failed] [--overwrite-human] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tqdm import tqdm  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.ingestion_service import ingest_book_pages  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest a book into the curriculum DB.")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--grade", type=int, required=True)
    parser.add_argument("--major", default=None, help="required for grades 10-12")
    parser.add_argument("--title", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--force", action="store_true", help="reprocess every page")
    parser.add_argument("--only-failed", action="store_true", help="reprocess failed pages only")
    parser.add_argument(
        "--overwrite-human",
        action="store_true",
        help="allow overwriting pages already edited by a human",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="only show the plan: no rendering, no LLM calls, no writes",
    )
    return parser


def _print_report(result: dict[str, Any]) -> None:
    totals = result["totals"]
    done = sum(t["done"] for t in totals.values())
    failed = sum(t["failed"] for t in totals.values())
    needs_review = sum(t["needs_review"] for t in totals.values())
    book_id = result["book_id"]

    print("\n=== REPORT ===")
    print(f"book_id            : {book_id}")
    print(f"pages processed    : {result.get('processed', 0)}")
    print(f"pages skipped      : {result.get('skipped', 0)}")
    print(f"pages done         : {done}")
    print(f"pages failed       : {failed}")
    print(f"pages needs_review : {needs_review}")
    print(f"total tokens       : {result['total_tokens']}")
    print(f"total time         : {sum(t['latency'] for t in totals.values()):.2f}s")
    print(f"escalated pages    : {result['escalated_pages']}")
    print(f"printed_page_offset: {result.get('printed_page_offset')}")

    review_pages = result.get("needs_review_pages") or []
    failed_pages = result.get("failed_pages") or []
    if review_pages:
        print(f"needs_review pages : {review_pages}")
    if failed_pages:
        print(f"failed pages       : {failed_pages}")

    warnings_by_page = result.get("warnings_by_page") or {}
    for idx in sorted(warnings_by_page):
        for warning in warnings_by_page[idx]:
            print(f"WARNING page {idx}: {warning}")

    deviations = result.get("printed_page_deviations") or []
    for deviation in deviations:
        print(f"OFFSET page {deviation['pdf_page_index']}: {deviation['message']}")

    print(f"exported           : storage/books/{result.get('storage_book_id', book_id)}/book.md and book.json")


def main() -> int:
    settings = get_settings()
    args = build_parser().parse_args()

    pdf = Path(args.pdf).resolve()
    if not pdf.exists():
        print(f"ERROR: PDF not found: {pdf}")
        return 2
    if args.start < 1 or args.end < args.start:
        print("ERROR: invalid page range")
        return 2

    total_pages = args.end - args.start + 1
    pbar = tqdm(total=total_pages, desc="ingesting", unit="page")

    def tick(info: dict[str, Any]) -> None:
        pbar.set_postfix(
            status=info.get("status", ""), tokens=info.get("tokens", 0), refresh=False
        )
        pbar.update(1)

    try:
        result = asyncio.run(
            ingest_book_pages(
                pdf_path=pdf,
                book_id=args.title,
                grade_number=args.grade,
                major_code=args.major,
                book_title=args.title,
                start_page=args.start,
                end_page=args.end,
                model_primary=settings.vision_model_primary,
                model_escalation=settings.vision_model_escalation,
                escalate_figures=settings.escalate_figures,
                use_db=True,
                force=args.force,
                only_failed=args.only_failed,
                overwrite_human=args.overwrite_human,
                dry_run=args.dry_run,
                progress_callback=tick,
            )
        )
    except KeyboardInterrupt:
        pbar.close()
        print("\nInterrupted — partial progress is saved; re-run to resume.")
        return 130
    finally:
        pbar.close()

    if result.get("dry_run"):
        print("\n=== DRY RUN ===")
        print(f"pages to process : {result.get('processed', 0)}")
        print(f"pages to skip    : {result.get('skipped', 0)}")
        for item in result.get("plan", []):
            print(f"  page {item['pdf_page_index']}: {item['decision']} ({item['reason']})")
        return 0

    _print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
