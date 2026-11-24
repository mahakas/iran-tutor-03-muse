"""Index approved pages of a book into Qdrant.

Run from backend/ after Postgres, Qdrant, and .env are ready:
    python scripts/index_book.py --book-id 1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.retrieval_service import close_qdrant, index_book  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Index accepted textbook pages in Qdrant.")
    parser.add_argument("--book-id", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    async def run() -> dict[str, int]:
        try:
            return await index_book(args.book_id, batch_size=args.batch_size)
        finally:
            await close_qdrant()

    result = asyncio.run(run())
    print(
        f"book_id={result['book_id']} indexed_pages={result['indexed_pages']} "
        f"skipped_empty_pages={result['skipped_empty_pages']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
