"""Shared text-to-book grounding guard for every textbook-bound capability call.

Runs inside `capability_runtime` after a call that is scoped to one book. It checks
the citations that will be shown to the student against the database truth:

* the book exists and is `ready`;
* each citation names that same `book_id` (no cross-book references);
* each `pdf_page_index` exists in that book;
* the citation's `printed_page_number` equals the stored printed page.

Suspicious results never block the answer. They are written to `ai_audit_logs` as a
`flagged` decision row (`flag_reason=grounding_mismatch`) so admins can inspect them.
Check failures are logged and never raise into the request path.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import Book, BookPage, BookStatus

logger = logging.getLogger(__name__)

FLAG_REASON = "grounding_mismatch"
MAX_REPORTED_ISSUES = 20


async def check_textbook_grounding(
    session: AsyncSession | None,
    *,
    capability_key: str,
    feature_key: str,
    book_id: int | None,
    citations: list[dict[str, Any]] | None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Return `{checked, ok, issues}`. Flags `ai_audit_logs` when issues are found."""
    if book_id is None or session is None:
        return {"checked": False, "ok": True, "issues": []}
    issues: list[dict[str, Any]] = []
    try:
        book = await session.get(Book, book_id)
        if book is None:
            issues.append({"code": "book_missing", "book_id": book_id})
        elif book.status != BookStatus.ready:
            issues.append({"code": "book_not_ready", "book_id": book_id})

        pages: dict[int, BookPage] = {}
        if book is not None:
            rows = (
                await session.scalars(select(BookPage).where(BookPage.book_id == book_id))
            ).all()
            pages = {row.pdf_page_index: row for row in rows}

        for index, citation in enumerate(citations or []):
            if not isinstance(citation, dict):
                issues.append({"code": "malformed", "index": index})
                continue
            if citation.get("book_id") != book_id:
                issues.append(
                    {"code": "cross_book", "index": index, "book_id": citation.get("book_id")}
                )
                continue
            page = pages.get(citation.get("pdf_page_index"))
            if page is None:
                issues.append(
                    {"code": "page_missing", "index": index, "pdf_page_index": citation.get("pdf_page_index")}
                )
                continue
            if citation.get("printed_page_number") != page.printed_page_number:
                issues.append(
                    {
                        "code": "printed_page_mismatch",
                        "index": index,
                        "pdf_page_index": page.pdf_page_index,
                        "claimed": citation.get("printed_page_number"),
                        "stored": page.printed_page_number,
                    }
                )
    except Exception:  # noqa: BLE001 - the guard must never break an answer
        logger.exception("grounding_guard.check_failed capability=%s", capability_key)
        return {"checked": False, "ok": True, "issues": [], "error": "check_failed"}

    result = {"checked": True, "ok": not issues, "issues": issues[:MAX_REPORTED_ISSUES]}
    if issues:
        await _flag(
            capability_key=capability_key,
            feature_key=feature_key,
            book_id=book_id,
            user_id=user_id,
            session_id=session_id,
            citations_checked=len(citations or []),
            issues=result["issues"],
        )
    return result


async def _flag(
    *,
    capability_key: str,
    feature_key: str,
    book_id: int,
    user_id: str | None,
    session_id: str | None,
    citations_checked: int,
    issues: list[dict[str, Any]],
) -> None:
    from app.services.ai_gateway import STATUS_FLAGGED, record_decision_audit

    try:
        await record_decision_audit(
            feature_key=feature_key,
            user_id=user_id,
            session_id=session_id,
            request_text=f"grounding check: capability={capability_key} book_id={book_id}",
            decision={
                "guard": "textbook_grounding",
                "capability_key": capability_key,
                "book_id": book_id,
                "citations_checked": citations_checked,
                "issues": issues,
            },
            flag_reason=FLAG_REASON,
            status=STATUS_FLAGGED,
        )
    except Exception:  # noqa: BLE001
        logger.exception("grounding_guard.flag_failed capability=%s", capability_key)
