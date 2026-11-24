"""CSV export for flashcard decks (NotebookLM-style "download as CSV").

- UTF-8 with BOM so Persian text opens correctly in Excel.
- Proper quoting via the stdlib csv writer (commas, quotes, newlines survive).
- Formula-injection guard: values starting with ``=``, ``+``, ``-``, ``@`` or a
  tab/CR are prefixed with a single quote so Excel does not execute them.
"""

from __future__ import annotations

import csv
import io
from typing import Any

_HEADER = ["Front", "Back", "Hint", "Tags", "Citations"]
_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str) -> str:
    """Neutralize CSV formula injection for one cell value."""
    text = value or ""
    if text.startswith(_INJECTION_PREFIXES):
        return "'" + text
    return text


def citations_text(citations: list[dict[str, Any]]) -> str:
    parts = [str(c.get("citation") or "") for c in (citations or []) if isinstance(c, dict)]
    return " | ".join(part for part in parts if part)


def build_deck_csv(cards: list[dict[str, Any]]) -> bytes:
    """Serialize ``serialize_card`` payloads into CSV bytes (UTF-8 BOM, CRLF rows)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(_HEADER)
    for card in cards or []:
        writer.writerow(
            [
                csv_safe(str(card.get("front_md", ""))),
                csv_safe(str(card.get("back_md", ""))),
                csv_safe(str(card.get("hint_md", ""))),
                " ".join(str(tag) for tag in card.get("tags", []) if str(tag).strip()),
                csv_safe(citations_text(card.get("citations", []))),
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")


__all__ = ["build_deck_csv", "csv_safe", "citations_text"]
