"""Student-facing access policy for the textbook catalogue.

Hotfix (auto-publish): manual catalog approval and the official-source URL are no
longer publication gates. A book is student-visible as soon as its processing
pipeline reached `Book.status == ready` — nothing else. All grade/branch/field/
subject curriculum filters, `BookCurriculumLink` mappings and the RAG page-status
filters are unchanged and remain enforced at their call sites.

Deprecated legacy columns (`catalog_status`, `official_source_url`, `approved_at`)
still exist in the database for backward compatibility, but no runtime path
depends on them for visibility.
"""

from __future__ import annotations

from app.models.curriculum import Book, BookStatus


def is_student_visible_book(book: Book | None) -> bool:
    """A book is visible the moment processing reached `ready` — no manual approval."""
    return bool(book is not None and book.status == BookStatus.ready)
