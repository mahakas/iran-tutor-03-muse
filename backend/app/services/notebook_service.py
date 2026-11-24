"""Phase 6 learning notebook: block workspace, Inline AI proposals, accept/reject, export.

Inline AI is textbook-grounded (RAG + `textbook_strict`). A proposal is never applied
directly: the client only sends an `audit_id`. On accept the server re-reads the
proposal from that audit row (owner, feature and success are checked), replaces the
exact selected text inside the block, and writes an accept decision to the audit log.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.flashcards import FlashcardDeck
from app.models.governance import AiAuditLog
from app.models.phase6 import NOTEBOOK_BLOCK_TYPES, Notebook, NotebookBlock
from app.services import capability_runtime, flashcard_service
from app.services.ai_gateway import record_decision_audit
from app.services.book_scope import book_scope, require_grade, source_citation
from app.services.retrieval_service import search_textbook
from app.services.visual_safety import UnsafeVisualError, sanitize_block_content
from app.services.visualize_service import validate_table

CAPABILITY_KEY = "learning_notebook"
MAX_BLOCK_CHARS = 8000
MAX_TITLE_CHARS = 255
MAX_PROPOSAL_CHARS = 4000
INLINE_TEXT_BLOCKS = ("text_markdown", "formula_latex", "callout_tip")
ALLOWED_METADATA_KEYS = frozenset({"title", "caption", "tone", "citation", "conversation_id", "message_id"})
# Stable handoff identity (Phase 02-B): a tutor answer saved into a notebook
# carries its conversation_id + message_id in the block metadata; a duplicate
# POST for the same pair must never create a second block.
HANDOFF_ID_KEYS = ("conversation_id", "message_id")
NOTEBOOK_CARD_DECK_TITLE = "دفترچهٔ یادداشت هوشمند"

# In-process serialization for add_block's check-and-insert. The row lock below
# (`with_for_update`) serializes concurrent handoffs on PostgreSQL, but it is a
# no-op on SQLite, so two parallel POSTs in the same process could both pass the
# duplicate check and insert a second block (flaky
# test_handoff_parallel_posts_create_single_block). This lock closes that gap for
# single-process deployments and tests; the row lock remains the cross-process
# guard for multi-worker deployments.
_ADD_BLOCK_LOCK = asyncio.Lock()

INLINE_ACTIONS: dict[str, str] = {
    "simplify": "متن انتخاب‌شده را ساده‌تر و کوتاه‌تر توضیح بده، با همان نمادهای کتاب.",
    "summarize": "متن انتخاب‌شده را در چند جمله خلاصه کن.",
    "example": "یک مثال حل‌شده در قالب کتاب بزن، فقط با داده‌های منبع.",
    "to_formula_or_table": "اگر متن رابطه است فرمول LaTeX بساز، اگر مقایسه است جدول Markdown بساز.",
    "to_flashcard": 'یک فلش‌کارت از متن بساز. فقط JSON با کلیدهای "front" و "back" برگردان.',
}


# ---------------------------------------------------------------------------
# Serialization & ownership
# ---------------------------------------------------------------------------
def serialize_block(block: NotebookBlock) -> dict[str, Any]:
    return {
        "id": block.id,
        "position": block.position,
        "block_type": block.block_type,
        "content": block.content,
        "metadata": dict(block.metadata_json or {}),
    }


def serialize_notebook(notebook: Notebook, blocks: list[NotebookBlock] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": notebook.id,
        "title": notebook.title,
        "book_id": notebook.book_id,
        "grade_number": notebook.grade_number,
        "major_code": notebook.major_code,
        "created_at": notebook.created_at.isoformat() if notebook.created_at else None,
        "updated_at": notebook.updated_at.isoformat() if notebook.updated_at else None,
    }
    if blocks is not None:
        payload["blocks"] = [serialize_block(block) for block in blocks]
    return payload


async def _owned_notebook(session: AsyncSession, user: User, notebook_id: int) -> Notebook:
    notebook = await session.get(Notebook, notebook_id)
    if notebook is None or notebook.user_id != user.id:
        raise HTTPException(status_code=404, detail="دفترچه یافت نشد.")
    return notebook


async def _owned_block(session: AsyncSession, notebook: Notebook, block_id: int) -> NotebookBlock:
    block = await session.get(NotebookBlock, block_id)
    if block is None or block.notebook_id != notebook.id:
        raise HTTPException(status_code=404, detail="بلوک یافت نشد.")
    return block


async def _blocks(session: AsyncSession, notebook_id: int) -> list[NotebookBlock]:
    rows = await session.scalars(
        select(NotebookBlock)
        .where(NotebookBlock.notebook_id == notebook_id)
        .order_by(NotebookBlock.position.asc(), NotebookBlock.id.asc())
    )
    return list(rows.all())


def _clean_title(title: str) -> str:
    cleaned = " ".join((title or "").split())[:MAX_TITLE_CHARS]
    if not cleaned:
        raise HTTPException(status_code=422, detail="عنوان دفترچه خالی است.")
    return cleaned


# ---------------------------------------------------------------------------
# Notebook CRUD
# ---------------------------------------------------------------------------
def _handoff_ref(meta: dict[str, Any]) -> tuple[str, str] | None:
    """Stable handoff identity from block metadata, or None when absent."""
    conversation_id = str(meta.get("conversation_id") or "").strip()
    message_id = str(meta.get("message_id") or "").strip()
    if conversation_id and message_id:
        return conversation_id, message_id
    return None


async def create_notebook(
    session: AsyncSession,
    user: User,
    *,
    title: str,
    book_id: int | None,
    dedupe_by_book: bool = False,
) -> dict[str, Any]:
    # Handoff-safe create (Phase 02-B): two parallel handoffs for the same book
    # must not spawn two notebooks. Serializes on the user row, then reuses the
    # existing per-book notebook when one is already there.
    if dedupe_by_book and book_id is not None:
        await session.scalar(select(User).where(User.id == user.id).with_for_update())
        existing = await session.scalar(
            select(Notebook).where(Notebook.user_id == user.id, Notebook.book_id == book_id)
        )
        if existing is not None:
            return serialize_notebook(existing)
    grade_number: int | None = None
    major_code: str | None = None
    if book_id is not None:
        scope = await book_scope(session, book_id)
        grade_number, major_code = scope.grade_number, scope.major_code
    notebook = Notebook(
        user_id=user.id,
        title=_clean_title(title),
        book_id=book_id,
        grade_number=grade_number,
        major_code=major_code,
    )
    session.add(notebook)
    await session.commit()
    return serialize_notebook(notebook, blocks=[])


async def list_notebooks(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    counts = (
        select(NotebookBlock.notebook_id, func.count(NotebookBlock.id).label("n"))
        .group_by(NotebookBlock.notebook_id)
        .subquery()
    )
    rows = await session.execute(
        select(Notebook, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.notebook_id == Notebook.id)
        .where(Notebook.user_id == user.id)
        .order_by(Notebook.updated_at.desc(), Notebook.id.desc())
    )
    items = []
    for notebook, block_count in rows.all():
        payload = serialize_notebook(notebook)
        payload["block_count"] = int(block_count or 0)
        items.append(payload)
    return items


async def get_notebook(session: AsyncSession, user: User, notebook_id: int) -> dict[str, Any]:
    notebook = await _owned_notebook(session, user, notebook_id)
    return serialize_notebook(notebook, blocks=await _blocks(session, notebook.id))


async def rename_notebook(session: AsyncSession, user: User, notebook_id: int, *, title: str) -> dict[str, Any]:
    notebook = await _owned_notebook(session, user, notebook_id)
    notebook.title = _clean_title(title)
    await session.commit()
    return serialize_notebook(notebook)


async def delete_notebook(session: AsyncSession, user: User, notebook_id: int) -> None:
    notebook = await _owned_notebook(session, user, notebook_id)
    await session.delete(notebook)
    await session.commit()


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------
def _normalize_block(block_type: str, content: str, metadata: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    if block_type not in NOTEBOOK_BLOCK_TYPES:
        raise HTTPException(status_code=422, detail="نوع بلوک مجاز نیست.")
    text = content or ""
    if len(text) > MAX_BLOCK_CHARS:
        raise HTTPException(status_code=422, detail=f"محتوای بلوک بیش از {MAX_BLOCK_CHARS} نویسه است.")
    try:
        if block_type == "comparison_table":
            parsed = json.loads(text or "{}")
            text = json.dumps(validate_table(parsed), ensure_ascii=False)
        else:
            text = sanitize_block_content(block_type, text)
    except (UnsafeVisualError, ValueError) as error:
        raise HTTPException(status_code=422, detail="محتوای بلوک از بررسی ایمنی یا ساختار نگذشت.") from error
    clean_meta = {
        key: str(value)[:300]
        for key, value in (metadata or {}).items()
        if key in ALLOWED_METADATA_KEYS and value is not None
    }
    return text, clean_meta


async def add_block(
    session: AsyncSession,
    user: User,
    notebook_id: int,
    *,
    block_type: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    notebook = await _owned_notebook(session, user, notebook_id)
    # Phase 02-B concurrency control: serialize parallel inserts per notebook so
    # two simultaneous handoff POSTs cannot both pass the duplicate check below.
    # The row lock serializes on PostgreSQL; the in-process lock covers SQLite,
    # where with_for_update() is a no-op.
    async with _ADD_BLOCK_LOCK:
        notebook = await session.scalar(select(Notebook).where(Notebook.id == notebook.id).with_for_update())
        assert notebook is not None
        text, meta = _normalize_block(block_type, content, metadata)
        handoff_ref = _handoff_ref(meta)
        existing = await _blocks(session, notebook.id)
        if handoff_ref is not None:
            for block in existing:
                if _handoff_ref(dict(block.metadata_json or {})) == handoff_ref:
                    # Duplicate request for the same conversation/message: replay the
                    # existing block instead of creating a second copy.
                    return {**serialize_block(block), "idempotent_replay": True}
        if position is None or position >= len(existing):
            place = (existing[-1].position + 1) if existing else 0
        else:
            place = max(0, position)
            for block in existing:
                if block.position >= place:
                    block.position += 1
        block = NotebookBlock(notebook_id=notebook.id, position=place, block_type=block_type, content=text, metadata_json=meta)
        session.add(block)
        notebook.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return serialize_block(block)


async def update_block(
    session: AsyncSession,
    user: User,
    notebook_id: int,
    block_id: int,
    *,
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    notebook = await _owned_notebook(session, user, notebook_id)
    block = await _owned_block(session, notebook, block_id)
    if content is not None:
        text, meta = _normalize_block(block.block_type, content, metadata if metadata is not None else dict(block.metadata_json or {}))
        block.content = text
        block.metadata_json = meta
    elif metadata is not None:
        _, meta = _normalize_block(block.block_type, block.content, metadata)
        block.metadata_json = meta
    if position is not None:
        block.position = max(0, position)
    notebook.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return serialize_block(block)


async def delete_block(session: AsyncSession, user: User, notebook_id: int, block_id: int) -> None:
    notebook = await _owned_notebook(session, user, notebook_id)
    block = await _owned_block(session, notebook, block_id)
    await session.delete(block)
    notebook.updated_at = datetime.now(timezone.utc)
    await session.commit()


# ---------------------------------------------------------------------------
# Inline AI: propose -> preview (client diff) -> accept / reject
# ---------------------------------------------------------------------------
def _parse_flashcard(text: str) -> tuple[str, str] | None:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`").removeprefix("json").strip()
    try:
        payload = json.loads(candidate)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    front = str(payload.get("front") or "").strip()[:1200]
    back = str(payload.get("back") or "").strip()[:2000]
    return (front, back) if front and back else None


async def propose_inline(
    session: AsyncSession,
    user: User,
    notebook_id: int,
    block_id: int,
    *,
    action: str,
    selection: str,
) -> dict[str, Any]:
    if action not in INLINE_ACTIONS:
        raise HTTPException(status_code=422, detail="عملیات هوشمند نامعتبر است.")
    notebook = await _owned_notebook(session, user, notebook_id)
    block = await _owned_block(session, notebook, block_id)
    if block.block_type not in INLINE_TEXT_BLOCKS:
        raise HTTPException(status_code=422, detail="این نوع بلوک قابل ویرایش هوشمند نیست.")
    if not selection or not (2 <= len(selection) <= 1500) or selection not in block.content:
        raise HTTPException(status_code=422, detail="متن انتخاب‌شده در این بلوک پیدا نشد.")
    if notebook.book_id is None:
        raise HTTPException(status_code=422, detail="برای ویرایش هوشمند، دفترچه را به یک کتاب درسی وصل کنید.")

    scope = await book_scope(session, notebook.book_id)
    sources = await search_textbook(
        selection, grade_number=require_grade(scope), major_code=scope.major_code, book_id=scope.book_id, top_k=4
    )
    sources = [source_citation(source, scope.title) for source in sources]
    if not sources:
        await record_decision_audit(
            feature_key=CAPABILITY_KEY,
            user_id=user.id,
            session_id=None,
            request_text=selection[:1500],
            decision={"verdict": "no_source", "action": action, "block_id": block.id},
            flag_reason="rag_miss",
            session=session,
        )
        await session.commit()
        raise HTTPException(status_code=422, detail="برای این متن در کتاب منبعی پیدا نشد؛ پیشنهادی ساخته نشد.")

    citations = [dict(source) for source in sources]
    user_text = (
        f"دستور: {INLINE_ACTIONS[action]}\n\nمتن انتخاب‌شده:\n{selection}\n\nمنابع کتاب:\n"
        + "\n\n".join(f"[{i}] {s.get('citation', '')}\n{str(s.get('full_text', ''))[:1200]}" for i, s in enumerate(sources))
    )
    result, _blocks, _skill = await capability_runtime.run_capability_text(
        session=session,
        capability_key=CAPABILITY_KEY,
        feature_key=CAPABILITY_KEY,
        user_text=user_text,
        user_id=user.id,
        book_id=scope.book_id,
        textbook_strict=True,
        citations=citations,
        rag_hit_count=len(sources),
        user=user,
        enforce=True,
    )
    raw = (result.content if isinstance(result.content, str) else str(result.content or "")).strip()
    if not raw or "NO_SOURCE" in raw:
        await record_decision_audit(
            feature_key=CAPABILITY_KEY,
            user_id=user.id,
            session_id=None,
            request_text=selection[:1500],
            decision={"verdict": "no_source", "action": action, "block_id": block.id},
            flag_reason="rag_miss",
            session=session,
        )
        await session.commit()
        raise HTTPException(status_code=422, detail="منابع کتاب برای این پیشنهاد کافی نبود.")

    kind = "text"
    proposed: Any = raw[:MAX_PROPOSAL_CHARS]
    if action == "to_flashcard":
        card = _parse_flashcard(raw)
        if card is None:
            await session.commit()
            raise HTTPException(status_code=422, detail="پیشنهاد فلش‌کارت معتبر نبود؛ دوباره تلاش کنید.")
        kind = "flashcard"
        proposed = {"front": card[0], "back": card[1]}
    await session.commit()
    return {
        "notebook_id": notebook.id,
        "block_id": block.id,
        "action": action,
        "kind": kind,
        "selection": selection,
        "proposed": proposed,
        "citations": [str(s["citation"]) for s in sources],
        "audit_id": result.audit_id,
    }


async def _decision_exists(session: AsyncSession, user: User, flag_reason: str, audit_id: str) -> bool:
    """True when a decision row of this kind already exists for the proposal (idempotency)."""
    count = await session.scalar(
        select(func.count())
        .select_from(AiAuditLog)
        .where(
            AiAuditLog.user_id == user.id,
            AiAuditLog.feature_key == CAPABILITY_KEY,
            AiAuditLog.flag_reason == flag_reason,
            AiAuditLog.response_text.like(f'%"audit_id": "{audit_id}"%'),
        )
    )
    return bool(count)


async def accept_inline(
    session: AsyncSession,
    user: User,
    notebook_id: int,
    block_id: int,
    *,
    audit_id: str,
    action: str,
    selection: str,
) -> dict[str, Any]:
    notebook = await _owned_notebook(session, user, notebook_id)
    block = await _owned_block(session, notebook, block_id)
    audit = await session.get(AiAuditLog, audit_id)
    if (
        audit is None
        or audit.user_id != user.id
        or audit.feature_key != CAPABILITY_KEY
        or audit.status != "success"
        or not audit.response_text
    ):
        raise HTTPException(status_code=404, detail="پیشنهاد معتبر پیدا نشد.")
    if await _decision_exists(session, user, "notebook_inline_accept", audit_id):
        raise HTTPException(status_code=409, detail="این پیشنهاد قبلاً پذیرفته شده است.")
    if action == "to_flashcard":
        card = _parse_flashcard(audit.response_text)
        if card is None:
            raise HTTPException(status_code=422, detail="پیشنهاد فلش‌کارت معتبر نیست.")
        deck = await session.scalar(
            select(FlashcardDeck).where(
                FlashcardDeck.user_id == user.id,
                FlashcardDeck.title == NOTEBOOK_CARD_DECK_TITLE,
            )
        )
        if deck is None:
            deck = await flashcard_service.create_deck(session, user, title=NOTEBOOK_CARD_DECK_TITLE, source_type="notebook")
        card_row = await flashcard_service.add_manual_card(
            session, deck, front_md=card[0], back_md=card[1], tags=["notebook"]
        )
        await record_decision_audit(
            feature_key=CAPABILITY_KEY,
            user_id=user.id,
            session_id=None,
            request_text=f"accept {action} block={block.id}",
            decision={"verdict": "accepted", "action": action, "card_id": card_row.id, "audit_id": audit_id},
            flag_reason="notebook_inline_accept",
            session=session,
        )
        await session.commit()
        return {"applied": "flashcard", "card_id": card_row.id, "block": serialize_block(block)}

    proposal = audit.response_text[:MAX_PROPOSAL_CHARS]
    if not selection or selection not in block.content:
        raise HTTPException(status_code=422, detail="متن انتخاب‌شده دیگر در بلوک نیست؛ پیشنهاد اعمال نشد.")
    new_content = block.content.replace(selection, proposal, 1)
    if len(new_content) > MAX_BLOCK_CHARS:
        raise HTTPException(status_code=422, detail="نتیجه بیش از حد بلند است.")
    block.content = new_content
    notebook.updated_at = datetime.now(timezone.utc)
    await record_decision_audit(
        feature_key=CAPABILITY_KEY,
        user_id=user.id,
        session_id=None,
        request_text=f"accept {action} block={block.id}",
        decision={"verdict": "accepted", "action": action, "block_id": block.id, "audit_id": audit_id},
        flag_reason="notebook_inline_accept",
        session=session,
    )
    await session.commit()
    return {"applied": "text", "block": serialize_block(block)}


async def reject_inline(session: AsyncSession, user: User, notebook_id: int, block_id: int, *, audit_id: str) -> None:
    notebook = await _owned_notebook(session, user, notebook_id)
    await _owned_block(session, notebook, block_id)
    audit = await session.get(AiAuditLog, audit_id)
    if audit is None or audit.user_id != user.id or audit.feature_key != CAPABILITY_KEY:
        raise HTTPException(status_code=404, detail="پیشنهاد معتبر پیدا نشد.")
    if await _decision_exists(session, user, "notebook_inline_reject", audit_id):
        return
    await record_decision_audit(
        feature_key=CAPABILITY_KEY,
        user_id=user.id,
        session_id=None,
        request_text=f"reject block={block_id}",
        decision={"verdict": "rejected_by_student", "block_id": block_id, "audit_id": audit_id},
        flag_reason="notebook_inline_reject",
        session=session,
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Export (Markdown; print-ready PDF is produced by the browser print view)
# ---------------------------------------------------------------------------
def _table_markdown(content: str) -> str:
    try:
        table = json.loads(content)
    except ValueError:
        return ""
    headers = [str(h).replace("|", "\\|") for h in table.get("headers", [])]
    rows = table.get("rows", [])
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |")
    return "\n".join(lines)


def export_markdown_text(title: str, blocks: list[NotebookBlock]) -> str:
    parts = [f"# {title}"]
    for block in blocks:
        meta = dict(block.metadata_json or {})
        caption = f"\n\n*{meta['caption']}*" if meta.get("caption") else ""
        citation = f"\n\n> منبع: {meta['citation']}" if meta.get("citation") else ""
        if block.block_type == "text_markdown":
            parts.append(block.content)
        elif block.block_type == "formula_latex":
            parts.append("$$\n" + block.content.strip() + "\n$$")
        elif block.block_type == "callout_tip":
            parts.append("> **" + (meta.get("title") or "نکته") + ":** " + block.content.replace("\n", "\n> "))
        elif block.block_type == "comparison_table":
            parts.append(_table_markdown(block.content) + caption)
        elif block.block_type == "diagram_mermaid":
            parts.append("```mermaid\n" + block.content + "\n```" + caption)
        elif block.block_type == "diagram_svg":
            parts.append("```xml\n" + block.content + "\n```" + caption)
        parts[-1] = parts[-1] + citation
    return "\n\n".join(p for p in parts if p) + "\n"


async def export_markdown(session: AsyncSession, user: User, notebook_id: int) -> tuple[str, str]:
    notebook = await _owned_notebook(session, user, notebook_id)
    blocks = await _blocks(session, notebook.id)
    return notebook.title, export_markdown_text(notebook.title, blocks)


__all__ = [
    "INLINE_ACTIONS",
    "accept_inline",
    "add_block",
    "create_notebook",
    "delete_block",
    "delete_notebook",
    "export_markdown",
    "get_notebook",
    "list_notebooks",
    "propose_inline",
    "reject_inline",
    "rename_notebook",
    "update_block",
]
