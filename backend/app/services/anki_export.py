"""Anki (.apkg) export for flashcard decks, built with genanki.

Math: `$...$` / `$$...$$` are converted to Anki's MathJax delimiters so formulas
render in Anki. Text is HTML-escaped first, so student/model content cannot inject markup.
"""

from __future__ import annotations

import html
import os
import re
import tempfile
from typing import Any

import genanki

# Stable identifiers so re-importing the same deck updates the existing Anki deck/model.
_MODEL_ID = 1_907_310_001
_DECK_ID_BASE = 1_907_320_000

ANKI_MODEL = genanki.Model(
    _MODEL_ID,
    "دارسیار — فلش‌کارت",
    fields=[
        {"name": "Front"},
        {"name": "Back"},
        {"name": "Hint"},
        {"name": "Citations"},
        {"name": "Tags"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": '<div dir="rtl" class="front">{{Front}}</div>'
            '{{#Hint}}<div class="hint">راهنما: {{Hint}}</div>{{/Hint}}',
            "afmt": '{{FrontSide}}<hr id="answer"><div dir="rtl" class="back">{{Back}}</div>'
            '{{#Citations}}<div class="cite">{{Citations}}</div>{{/Citations}}',
        }
    ],
    css=".card{font-family:Vazirmatn,Tahoma,sans-serif;font-size:20px;text-align:right;}"
    ".hint{color:#888;font-size:16px;margin-top:8px;}.cite{color:#2a6;font-size:14px;margin-top:10px;}",
)

_DISPLAY_MATH = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_INLINE_MATH = re.compile(r"\$(.+?)\$", re.DOTALL)


def to_anki_html(markdown_text: str) -> str:
    escaped = html.escape(markdown_text or "", quote=False)
    escaped = _DISPLAY_MATH.sub(lambda m: "\\[" + m.group(1) + "\\]", escaped)
    escaped = _INLINE_MATH.sub(lambda m: "\\(" + m.group(1) + "\\)", escaped)
    return escaped.replace("\n", "<br>")


def citations_text(citations: list[dict[str, Any]]) -> str:
    return "<br>".join(html.escape(str(c.get("citation") or "")) for c in citations)


def build_apkg_bytes(deck_id: int, deck_title: str, cards: list[dict[str, Any]]) -> bytes:
    """Serialize a deck to .apkg bytes. `cards` items use the `serialize_card` shape."""
    if not cards:
        raise ValueError("deck has no cards")
    deck = genanki.Deck(_DECK_ID_BASE + int(deck_id), deck_title or "دارسیار")
    for card in cards:
        tags = [re.sub(r"\s+", "_", str(t)).strip("_") for t in card.get("tags", []) if str(t).strip()]
        deck.add_note(
            genanki.Note(
                model=ANKI_MODEL,
                fields=[
                    to_anki_html(card.get("front_md", "")),
                    to_anki_html(card.get("back_md", "")),
                    to_anki_html(card.get("hint_md", "")),
                    citations_text(card.get("citations", [])),
                    " ".join(tags),
                ],
                tags=tags,
            )
        )
    fd, path = tempfile.mkstemp(suffix=".apkg")
    os.close(fd)
    try:
        genanki.Package(deck).write_to_file(path)
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        os.unlink(path)


__all__ = ["ANKI_MODEL", "build_apkg_bytes", "citations_text", "to_anki_html"]
