"""Phase 4 admin routes: learner memory inspector, concept links, deleted-chat monitoring.

All routes sit under `/api/v1/admin/*` and use `require_admin` (strict governance).
Students never reach these endpoints and cannot read or override memory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.db.session import get_session
from app.models.auth import User
from app.models.chat import ChatSession
from app.models.concepts import CONCEPT_RELATIONS, ConceptLink
from app.models.curriculum import Book, Grade
from app.models.learner_memory import LearnerMemory
from app.services.learner_memory_service import memory_counts, rebuild_l3_profile, serialize_memory

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-phase4"],
    dependencies=[Depends(require_admin)],
)


# ---------------------------------------------------------------------------
# Learner memory inspector
# ---------------------------------------------------------------------------
class MemoryItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    layer: Literal["L2", "L3"] = "L2"
    kind: Literal["mastered", "weak", "note", "profile"] = "note"
    book_id: int | None = None
    chapter_number: int | None = Field(default=None, ge=1, le=60)
    topic_key: str | None = Field(default=None, max_length=255)
    content_fa: str = Field(min_length=1, max_length=1000)
    evidence_count: int | None = Field(default=None, ge=0, le=100000)


class MemoryPutBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MemoryItemIn] = Field(min_length=1, max_length=50)


async def _admin_user(session: AsyncSession, user_id: str) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    return user


def _user_brief(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "phone_number": user.phone_number,
        "full_name": user.full_name,
        "grade_level": user.grade_level,
        "major": user.major,
    }


@router.get("/users/{user_id}/memory")
async def get_user_memory(
    user_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _admin_user(session, user_id)
    rows = (
        await session.scalars(
            select(LearnerMemory)
            .where(LearnerMemory.user_id == user_id)
            .order_by(LearnerMemory.layer.asc(), LearnerMemory.updated_at.desc(), LearnerMemory.id.desc())
        )
    ).all()
    return {
        "user": _user_brief(user),
        "counts": await memory_counts(session, user_id),
        "items": [serialize_memory(row) for row in rows],
    }


@router.put("/users/{user_id}/memory")
async def put_user_memory(
    user_id: str,
    body: MemoryPutBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create or edit L2 facts and L3 profile text. Edits are marked `edited_by_admin`."""
    await _admin_user(session, user_id)
    now = datetime.now(timezone.utc)
    for item in body.items:
        if item.id is not None:
            row = await session.scalar(
                select(LearnerMemory).where(
                    LearnerMemory.id == item.id, LearnerMemory.user_id == user_id
                )
            )
            if row is None:
                raise HTTPException(status_code=404, detail="memory item not found")
            if row.layer == "L1":
                raise HTTPException(status_code=422, detail="L1 session trace is read-only")
            if row.layer != item.layer:
                raise HTTPException(status_code=422, detail="layer cannot be changed")
            # Identity fields (layer, book, chapter, topic) are fixed on update so the
            # automatic upserts keep matching the same row. Only wording/kind change.
            row.content_fa = item.content_fa.strip()
            if row.layer == "L2" and "kind" in item.model_fields_set:
                row.kind = item.kind
            if item.evidence_count is not None:
                row.evidence_count = item.evidence_count
            row.edited_by_admin = True
            row.updated_at = now
            continue

        if item.layer == "L3":
            raise HTTPException(
                status_code=422, detail="L3 profile is rebuilt automatically; edit it by id"
            )
        if item.book_id is not None and await session.get(Book, item.book_id) is None:
            raise HTTPException(status_code=422, detail="book not found")
        session.add(
            LearnerMemory(
                user_id=user_id,
                layer="L2",
                kind=item.kind if item.kind != "profile" else "note",
                book_id=item.book_id,
                chapter_number=item.chapter_number,
                topic_key=(item.topic_key or item.content_fa[:60]).strip().casefold()[:255],
                content_fa=item.content_fa.strip(),
                evidence_count=item.evidence_count or 1,
                source_type="admin",
                created_by="admin",
                edited_by_admin=True,
                data_json={"topic": (item.topic_key or item.content_fa[:60])[:120]},
            )
        )
    await session.flush()
    await rebuild_l3_profile(session, user_id)
    await session.commit()
    return await get_user_memory(user_id, session)


@router.delete("/users/{user_id}/memory")
async def delete_user_memory(
    user_id: str,
    memory_id: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Delete one memory item (`memory_id`), or reset L1/L2/L3 for the user when omitted."""
    await _admin_user(session, user_id)
    if memory_id is not None:
        row = await session.scalar(
            select(LearnerMemory).where(LearnerMemory.id == memory_id, LearnerMemory.user_id == user_id)
        )
        if row is None:
            raise HTTPException(status_code=404, detail="memory item not found")
        await session.delete(row)
        deleted = 1
    else:
        result = await session.execute(delete(LearnerMemory).where(LearnerMemory.user_id == user_id))
        deleted = int(result.rowcount or 0)
    await session.flush()
    if memory_id is not None:
        await rebuild_l3_profile(session, user_id)
    await session.commit()
    return {"deleted": deleted, "user_id": user_id, "counts": await memory_counts(session, user_id)}


# ---------------------------------------------------------------------------
# Concept links (cross-grade Konkoor citations)
# ---------------------------------------------------------------------------
class ConceptLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_book_id: int = Field(gt=0)
    source_chapter: int = Field(ge=1, le=60)
    target_book_id: int = Field(gt=0)
    target_chapter: int = Field(ge=1, le=60)
    relation: Literal["same_concept", "prerequisite", "related"] = "related"
    label_fa: str = Field(default="", max_length=255)


def _serialize_link(link: ConceptLink, books: dict[int, dict[str, Any]]) -> dict[str, Any]:
    source = books.get(link.source_book_id, {})
    target = books.get(link.target_book_id, {})
    return {
        "id": link.id,
        "relation": link.relation,
        "label_fa": link.label_fa,
        "source": {
            "book_id": link.source_book_id,
            "book_title": source.get("title"),
            "grade_number": source.get("grade_number"),
            "chapter_number": link.source_chapter,
        },
        "target": {
            "book_id": link.target_book_id,
            "book_title": target.get("title"),
            "grade_number": target.get("grade_number"),
            "chapter_number": link.target_chapter,
        },
        "created_by": link.created_by,
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }


async def _book_index(session: AsyncSession, book_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not book_ids:
        return {}
    rows = (
        await session.execute(
            select(Book.id, Book.title, Grade.number)
            .join(Grade, Book.grade_id == Grade.id)
            .where(Book.id.in_(book_ids))
        )
    ).all()
    return {book_id: {"title": title, "grade_number": grade} for book_id, title, grade in rows}


@router.get("/concept-links")
async def list_concept_links(
    book_id: int | None = Query(default=None, gt=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    statement = select(ConceptLink).order_by(ConceptLink.id.desc()).limit(500)
    if book_id is not None:
        statement = statement.where(
            (ConceptLink.source_book_id == book_id) | (ConceptLink.target_book_id == book_id)
        )
    links = (await session.scalars(statement)).all()
    ids = {l.source_book_id for l in links} | {l.target_book_id for l in links}
    books = await _book_index(session, ids)
    return {
        "relations": list(CONCEPT_RELATIONS),
        "items": [_serialize_link(link, books) for link in links],
    }


@router.post("/concept-links")
async def create_concept_link(
    body: ConceptLinkIn,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if body.source_book_id == body.target_book_id and body.source_chapter == body.target_chapter:
        raise HTTPException(status_code=422, detail="a chapter cannot link to itself")
    books = await _book_index(session, {body.source_book_id, body.target_book_id})
    if body.source_book_id not in books or body.target_book_id not in books:
        raise HTTPException(status_code=422, detail="source or target book not found")
    link = ConceptLink(
        source_book_id=body.source_book_id,
        source_chapter=body.source_chapter,
        target_book_id=body.target_book_id,
        target_chapter=body.target_chapter,
        relation=body.relation,
        label_fa=body.label_fa.strip(),
        created_by="admin",
    )
    session.add(link)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="this concept link already exists") from error
    await session.refresh(link)
    return _serialize_link(link, books)


@router.delete("/concept-links/{link_id}")
async def delete_concept_link(
    link_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    link = await session.get(ConceptLink, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="concept link not found")
    await session.delete(link)
    await session.commit()
    return {"deleted": True, "id": link_id}


# ---------------------------------------------------------------------------
# Monitoring: chats in the Recycle Bin (glass box)
# ---------------------------------------------------------------------------
@router.get("/chat-sessions")
async def list_chat_sessions_for_admin(
    status: Literal["active", "deleted", "all"] = Query(default="deleted"),
    user_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    statement = (
        select(ChatSession, Book.title, User.phone_number)
        .outerjoin(Book, ChatSession.book_id == Book.id)
        .join(User, ChatSession.user_id == User.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
    )
    if status == "deleted":
        statement = statement.where(ChatSession.deleted_at.is_not(None))
    elif status == "active":
        statement = statement.where(ChatSession.deleted_at.is_(None))
    if user_id:
        statement = statement.where(ChatSession.user_id == user_id)
    rows = (await session.execute(statement)).all()
    items = [
        {
            "id": chat.id,
            "user_id": chat.user_id,
            "phone_number": phone,
            "title": chat.title,
            "book_title": book_title,
            "mode": chat.mode,
            "message_count": len(chat.messages or []),
            "deleted_at": chat.deleted_at.isoformat() if chat.deleted_at else None,
            "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
        }
        for chat, book_title, phone in rows
    ]
    total_deleted = await session.scalar(
        select(func.count()).select_from(ChatSession).where(ChatSession.deleted_at.is_not(None))
    )
    return {"status": status, "deleted_total": int(total_deleted or 0), "items": items}
