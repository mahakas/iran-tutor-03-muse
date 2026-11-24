"""Phase 6 student API: learning notebook, Inline AI, web visuals, TTS, Living Book.

Every route is gated by `require_capability_enabled` (fail-closed). AI work goes only
through the services, which call `capability_runtime -> ai_gateway -> ai_audit_logs`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_student
from app.db.session import get_session
from app.models.auth import User
from app.services import notebook_service as nb
from app.services import tts_service
from app.services.capability_service import require_capability_enabled
from app.services.visualize_service import generate_visual

router = APIRouter(tags=["phase6"])


class NotebookCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    book_id: int | None = Field(default=None, gt=0)


class NotebookRenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class BlockCreateBody(BaseModel):
    block_type: str = Field(min_length=1, max_length=32)
    content: str = Field(default="", max_length=nb.MAX_BLOCK_CHARS)
    metadata: dict[str, Any] = Field(default_factory=dict)
    position: int | None = Field(default=None, ge=0)


class BlockUpdateBody(BaseModel):
    content: str | None = Field(default=None, max_length=nb.MAX_BLOCK_CHARS)
    metadata: dict[str, Any] | None = None
    position: int | None = Field(default=None, ge=0)


class InlineProposeBody(BaseModel):
    action: Literal["simplify", "summarize", "example", "to_formula_or_table", "to_flashcard"]
    selection: str = Field(min_length=2, max_length=1500)


class InlineDecisionBody(BaseModel):
    audit_id: str = Field(min_length=1, max_length=36)
    action: Literal["simplify", "summarize", "example", "to_formula_or_table", "to_flashcard"] = "simplify"
    selection: str = Field(default="", max_length=1500)


class VisualizeBody(BaseModel):
    kind: Literal["mermaid", "svg", "table"]
    prompt: str = Field(min_length=1, max_length=500)
    book_id: int = Field(gt=0)


class SpeakBody(BaseModel):
    text: str = Field(min_length=1, max_length=tts_service.MAX_TTS_CHARS)
    book_id: int | None = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# Notebook
# ---------------------------------------------------------------------------
@router.get("/api/v1/notebooks")
async def list_notebooks(
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    return {"items": await nb.list_notebooks(session, current_user)}


@router.post("/api/v1/notebooks", status_code=201)
async def create_notebook(
    body: NotebookCreateBody,
    dedupe_book: bool = Query(default=False, description="Handoff mode: reuse an existing notebook for the same book"),
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    return await nb.create_notebook(
        session, current_user, title=body.title, book_id=body.book_id, dedupe_by_book=dedupe_book
    )


@router.get("/api/v1/notebooks/{notebook_id}")
async def get_notebook(
    notebook_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    return await nb.get_notebook(session, current_user, notebook_id)


@router.patch("/api/v1/notebooks/{notebook_id}")
async def rename_notebook(
    notebook_id: int,
    body: NotebookRenameBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    return await nb.rename_notebook(session, current_user, notebook_id, title=body.title)


@router.delete("/api/v1/notebooks/{notebook_id}", status_code=204)
async def delete_notebook(
    notebook_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    await nb.delete_notebook(session, current_user, notebook_id)
    return Response(status_code=204)


@router.post("/api/v1/notebooks/{notebook_id}/blocks", status_code=201)
async def add_block(
    notebook_id: int,
    body: BlockCreateBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    return await nb.add_block(
        session,
        current_user,
        notebook_id,
        block_type=body.block_type,
        content=body.content,
        metadata=body.metadata,
        position=body.position,
    )


@router.patch("/api/v1/notebooks/{notebook_id}/blocks/{block_id}")
async def update_block(
    notebook_id: int,
    block_id: int,
    body: BlockUpdateBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    return await nb.update_block(
        session,
        current_user,
        notebook_id,
        block_id,
        content=body.content,
        metadata=body.metadata,
        position=body.position,
    )


@router.delete("/api/v1/notebooks/{notebook_id}/blocks/{block_id}", status_code=204)
async def delete_block(
    notebook_id: int,
    block_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    await nb.delete_block(session, current_user, notebook_id, block_id)
    return Response(status_code=204)


@router.post("/api/v1/notebooks/{notebook_id}/blocks/{block_id}/inline/propose")
async def propose_inline(
    notebook_id: int,
    block_id: int,
    body: InlineProposeBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    return await nb.propose_inline(
        session, current_user, notebook_id, block_id, action=body.action, selection=body.selection
    )


@router.post("/api/v1/notebooks/{notebook_id}/blocks/{block_id}/inline/accept")
async def accept_inline(
    notebook_id: int,
    block_id: int,
    body: InlineDecisionBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    return await nb.accept_inline(
        session,
        current_user,
        notebook_id,
        block_id,
        audit_id=body.audit_id,
        action=body.action,
        selection=body.selection,
    )


@router.post("/api/v1/notebooks/{notebook_id}/blocks/{block_id}/inline/reject", status_code=204)
async def reject_inline(
    notebook_id: int,
    block_id: int,
    body: InlineDecisionBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    await nb.reject_inline(session, current_user, notebook_id, block_id, audit_id=body.audit_id)
    return Response(status_code=204)


@router.get("/api/v1/notebooks/{notebook_id}/export.md")
async def export_notebook(
    notebook_id: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await require_capability_enabled(session, nb.CAPABILITY_KEY, current_user)
    title, markdown = await nb.export_markdown(session, current_user, notebook_id)
    filename = f"notebook-{notebook_id}.md"
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Web visualization
# ---------------------------------------------------------------------------
@router.post("/api/v1/visualize")
async def visualize(
    body: VisualizeBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_capability_enabled(session, "web_visualize", current_user)
    return await generate_visual(session, current_user, kind=body.kind, prompt=body.prompt, book_id=body.book_id)


# ---------------------------------------------------------------------------
# TTS read-aloud (cached)
# ---------------------------------------------------------------------------
@router.post("/api/v1/tts")
async def speak(
    body: SpeakBody,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    result = await tts_service.speak(session, current_user, text=body.text, book_id=body.book_id)
    response = FileResponse(Path(result.path), media_type=result.media_type)
    response.headers["X-Tts-Cache"] = "hit" if result.cache_hit else "miss"
    return response


# ---------------------------------------------------------------------------
# Living Book (one chapter, shared cache)
# ---------------------------------------------------------------------------
@router.get("/api/v1/living-book/{book_id}/chapters/{chapter_number}")
async def get_living_book(
    book_id: int,
    chapter_number: int,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if chapter_number < 1 or chapter_number > 99:
        raise HTTPException(status_code=422, detail="شمارهٔ فصل نامعتبر است.")
    from app.services import living_book_service as lbs

    return await lbs.get_living_book(session, current_user, book_id=book_id, chapter_number=chapter_number)
