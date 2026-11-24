"""Typed Learning Blocks standard (Phase 2).

Every learning feature may emit structured blocks alongside plain streaming
text. The frontend renders them through ``LearningBlockRenderer`` (RTL +
KaTeX). Block types:

- ``text_markdown`` — Markdown paragraph (may contain inline LaTeX).
- ``formula_latex`` — display-math formula.
- ``callout_tip`` — highlighted tip / warning / note box.
- ``citation_ref`` — clickable textbook citation badge (book/chapter/page).
- ``quiz_item`` — a single question with options and (optionally) the answer.
- ``flashcard_item`` — front/back flashcard.
- ``diagram_mermaid`` — Mermaid diagram source.
- ``diagram_svg`` — sanitized SVG markup.

The runtime can also convert a plain tutor answer + its server-owned sources
into blocks via :func:`blocks_from_answer`, so existing chat responses gain
structured rendering without changing the model prompts.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

BlockType = Literal[
    "text_markdown",
    "formula_latex",
    "callout_tip",
    "citation_ref",
    "quiz_item",
    "flashcard_item",
    "diagram_mermaid",
    "diagram_svg",
]

BLOCK_TYPES: tuple[str, ...] = (
    "text_markdown",
    "formula_latex",
    "callout_tip",
    "citation_ref",
    "quiz_item",
    "flashcard_item",
    "diagram_mermaid",
    "diagram_svg",
)


class LearningBlock(BaseModel):
    """One typed unit of learning content."""

    type: BlockType
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def validate_blocks(raw: Any) -> list[LearningBlock]:
    """Validate an untrusted payload into typed blocks (invalid rows dropped)."""
    if not isinstance(raw, list):
        return []
    blocks: list[LearningBlock] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            blocks.append(LearningBlock.model_validate(item))
        except Exception:  # noqa: BLE001 - untrusted model output; drop bad rows
            continue
    return blocks


def parse_blocks_json(text: str) -> list[LearningBlock]:
    """Parse a JSON array of blocks from model output (fences tolerated)."""
    if not text or not text.strip():
        return []
    candidate = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return []
    return validate_blocks(parsed)


def blocks_from_answer(answer: str, sources: list[dict[str, Any]] | None) -> list[LearningBlock]:
    """Convert a plain tutor answer + server-owned sources into blocks.

    The answer text stays one ``text_markdown`` block (KaTeX-safe); each source
    becomes a ``citation_ref`` block so the UI can render clickable badges.
    """
    blocks: list[LearningBlock] = []
    if answer and answer.strip():
        blocks.append(LearningBlock(type="text_markdown", content=answer.strip()))
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        blocks.append(
            LearningBlock(
                type="citation_ref",
                content=str(source.get("citation") or ""),
                metadata={
                    key: source.get(key)
                    for key in (
                        "book_id",
                        "book_title",
                        "chapter_number",
                        "chapter_title",
                        "pdf_page_index",
                        "printed_page_number",
                    )
                    if source.get(key) is not None
                },
            )
        )
    return blocks


def blocks_to_payload(blocks: list[LearningBlock]) -> list[dict[str, Any]]:
    return [block.model_dump() for block in blocks]
