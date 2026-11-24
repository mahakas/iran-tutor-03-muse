"""Persian-aware search keys shared by Python-side and SQL-side matching.

Arabic `ي`/`ك`/`ة` and zero-width non-joiner characters are folded to the Persian forms
used in textbooks, so `كتاب` finds `کتاب`. Keep this in sync with
`retrieval_service.normalize_persian_text` (which it delegates to).
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

_FOLD = (("ي", "ی"), ("ك", "ک"), ("ة", "ه"), ("\u200c", " "), ("\u0640", ""))


def search_key(text: str | None) -> str:
    """Normalize one string for case-insensitive Persian matching."""
    value = text or ""
    for src, dst in _FOLD:
        value = value.replace(src, dst)
    return value.casefold()


def sql_search_key(column: ColumnElement) -> ColumnElement:
    """SQL equivalent of `search_key` applied to a text column."""
    expr = column
    for src, dst in _FOLD:
        expr = func.replace(expr, src, dst)
    return func.lower(expr)
