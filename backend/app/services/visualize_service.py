"""Phase 6 browser-native visuals: generate Mermaid, sanitized SVG or comparison tables.

The model output is textbook-grounded (RAG + `textbook_strict`) and then validated on
the server: SVG goes through the allowlist sanitizer, Mermaid through the diagram-type
guard, tables through a shape check. Anything that fails is rejected and audited; the
rejected output never reaches the client.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.services import capability_runtime
from app.services.ai_gateway import record_decision_audit
from app.services.book_scope import book_scope, require_grade, source_citation
from app.services.retrieval_service import search_textbook
from app.services.visual_safety import UnsafeVisualError, sanitize_svg, validate_mermaid

CAPABILITY_KEY = "web_visualize"
VISUAL_KINDS = ("mermaid", "svg", "table")
MAX_PROMPT_CHARS = 500
MAX_TABLE_COLUMNS = 8
MAX_TABLE_ROWS = 12
MAX_CELL_CHARS = 120


def validate_table(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise UnsafeVisualError("table payload must be an object")
    headers = payload.get("headers")
    rows = payload.get("rows")
    if not isinstance(headers, list) or not headers or len(headers) > MAX_TABLE_COLUMNS:
        raise UnsafeVisualError("table headers are invalid")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_TABLE_ROWS:
        raise UnsafeVisualError("table rows are invalid")
    clean_headers = [str(h)[:MAX_CELL_CHARS] for h in headers]
    clean_rows: list[list[str]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(clean_headers):
            raise UnsafeVisualError("table row width does not match headers")
        clean_rows.append([str(cell)[:MAX_CELL_CHARS] for cell in row])
    return {"headers": clean_headers, "rows": clean_rows}


def build_visual_block(payload: Any, *, kind_hint: str, citation: str | None) -> dict[str, Any]:
    """Turn a model payload into one safe learning block (raises UnsafeVisualError)."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as error:
            raise UnsafeVisualError("visual payload is not JSON") from error
    if not isinstance(payload, dict):
        raise UnsafeVisualError("visual payload must be an object")
    kind = str(payload.get("kind") or kind_hint)
    title = str(payload.get("title") or "")[:200]
    caption = str(payload.get("caption") or "")[:300]
    metadata: dict[str, Any] = {"title": title, "caption": caption}
    if citation:
        metadata["citation"] = citation
    if kind == "mermaid":
        return {"type": "diagram_mermaid", "content": validate_mermaid(payload.get("source")), "metadata": metadata}
    if kind == "svg":
        source = payload.get("source")
        if not isinstance(source, str):
            raise UnsafeVisualError("svg source must be text")
        return {"type": "diagram_svg", "content": sanitize_svg(source), "metadata": metadata}
    if kind == "table":
        table = validate_table(payload.get("source"))
        return {
            "type": "comparison_table",
            "content": json.dumps(table, ensure_ascii=False),
            "metadata": {**metadata, **table},
        }
    raise UnsafeVisualError("visual kind is not allowed")


async def generate_visual(
    session: AsyncSession,
    user: User,
    *,
    kind: str,
    prompt: str,
    book_id: int,
) -> dict[str, Any]:
    if kind not in VISUAL_KINDS:
        raise HTTPException(status_code=422, detail="نوع نمودار باید mermaid، svg یا table باشد.")
    text = " ".join((prompt or "").split())
    if not text or len(text) > MAX_PROMPT_CHARS:
        raise HTTPException(status_code=422, detail="متن درخواست نمودار معتبر نیست.")
    scope = await book_scope(session, book_id)
    sources = await search_textbook(
        text, grade_number=require_grade(scope), major_code=scope.major_code, book_id=book_id, top_k=4
    )
    sources = [source_citation(source, scope.title) for source in sources]
    if not sources:
        await record_decision_audit(
            feature_key=CAPABILITY_KEY,
            user_id=user.id,
            session_id=None,
            request_text=text,
            decision={"verdict": "no_source", "kind": kind},
            flag_reason="rag_miss",
            session=session,
        )
        await session.commit()
        raise HTTPException(status_code=422, detail="برای این درخواست در کتاب منبعی پیدا نشد؛ نمودار ساخته نشد.")

    citations = [dict(source) for source in sources]
    user_text = (
        f"درخواست نمودار: {text}\nنوع: {kind}\n\nمنابع کتاب:\n"
        + "\n\n".join(f"[{index}] {source.get('citation', '')}\n{source.get('full_text', '')[:1200]}" for index, source in enumerate(sources))
    )
    result, _skill = await capability_runtime.run_capability_json(
        session=session,
        capability_key=CAPABILITY_KEY,
        feature_key=CAPABILITY_KEY,
        user_text=user_text,
        user_id=user.id,
        book_id=book_id,
        textbook_strict=True,
        citations=citations,
        rag_hit_count=len(sources),
        user=user,
        enforce=True,
    )
    try:
        block = build_visual_block(result.content, kind_hint=kind, citation=str(sources[0]["citation"]))
    except UnsafeVisualError as error:
        await record_decision_audit(
            feature_key=CAPABILITY_KEY,
            user_id=user.id,
            session_id=None,
            request_text=text,
            decision={"verdict": "rejected", "reason": str(error), "kind": kind},
            flag_reason="visual_rejected",
            session=session,
        )
        await session.commit()
        raise HTTPException(status_code=422, detail="نمودار تولیدشده از بررسی ایمنی یا ساختار نگذشت؛ دوباره تلاش کنید.") from error
    await session.commit()
    return {
        "block": block,
        "audit_id": result.audit_id,
        "citations": [str(source["citation"]) for source in sources],
    }
