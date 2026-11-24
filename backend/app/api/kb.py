"""Web KB Pipeline API (Phase 2) — admin-only.

Admin endpoints for the database-tracked ingestion pipeline: trigger/resume/
cancel ingestion jobs, re-index a single page or chapter, extract and inspect
source figures, and run the Model Benchmark Lab.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.db.session import get_session
from app.services import kb_ingestion_service
from app.services.ingestion_service import pdf_page_count

router = APIRouter(
    prefix="/api/v1/admin/kb",
    tags=["admin-kb"],
    dependencies=[Depends(require_admin)],
)


class IngestTriggerBody(BaseModel):
    start_page: int = Field(default=1, ge=1)
    end_page: int | None = None


@router.post("/books/{book_id}/ingest", status_code=202)
async def trigger_ingestion(
    book_id: int,
    body: IngestTriggerBody,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.models.curriculum import Book

    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="کتاب یافت نشد.")
    pdf_path = Path(book.pdf_file_path)
    if not pdf_path.is_file():
        raise HTTPException(status_code=422, detail="فایل PDF اصلی این کتاب در دسترس نیست.")
    file_pages = pdf_page_count(pdf_path)
    end_page = body.end_page or file_pages
    if end_page > file_pages:
        raise HTTPException(status_code=422, detail=f"PDF فقط {file_pages} صفحه دارد.")
    if body.start_page < 1 or end_page < body.start_page:
        raise HTTPException(status_code=422, detail="بازهٔ صفحات نامعتبر است.")
    job = await kb_ingestion_service.create_ingestion_job(
        session, book_id=book_id, start_page=body.start_page, end_page=end_page
    )
    background_tasks.add_task(kb_ingestion_service.run_ingestion_job, job.id)
    return {"job": kb_ingestion_service.serialize_job(job)}


@router.get("/jobs")
async def list_ingestion_jobs(
    book_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    jobs = await kb_ingestion_service.list_jobs(session, book_id=book_id)
    return {"jobs": [kb_ingestion_service.serialize_job(job) for job in jobs]}


@router.get("/jobs/{job_id}")
async def get_ingestion_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    job = await kb_ingestion_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="جاب ایندکس یافت نشد.")
    return {"job": kb_ingestion_service.serialize_job(job)}


@router.post("/jobs/{job_id}/cancel")
async def cancel_ingestion_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    job = await kb_ingestion_service.cancel_ingestion_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="جاب ایندکس یافت نشد.")
    return {"job": kb_ingestion_service.serialize_job(job)}


class ReindexPageBody(BaseModel):
    pdf_page_index: int = Field(ge=1)


@router.post("/books/{book_id}/reindex-page")
async def reindex_single_page(
    book_id: int,
    body: ReindexPageBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await kb_ingestion_service.reindex_page(
            session, book_id=book_id, pdf_page_index=body.pdf_page_index
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


class ReindexChapterBody(BaseModel):
    chapter_number: int = Field(ge=1)


@router.post("/books/{book_id}/reindex-chapter")
async def reindex_chapter(
    book_id: int,
    body: ReindexChapterBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await kb_ingestion_service.reindex_chapter(
            session, book_id=book_id, chapter_number=body.chapter_number
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


class ExtractFiguresBody(BaseModel):
    start_page: int | None = Field(default=None, ge=1)
    end_page: int | None = Field(default=None, ge=1)
    replace: bool = True


@router.post("/books/{book_id}/figures/extract")
async def extract_figures(
    book_id: int,
    body: ExtractFiguresBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await kb_ingestion_service.extract_source_figures(
            session,
            book_id=book_id,
            start_page=body.start_page,
            end_page=body.end_page,
            replace=body.replace,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


@router.get("/books/{book_id}/figures")
async def list_book_figures(
    book_id: int,
    page_index: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    figures = await kb_ingestion_service.list_figures(
        session, book_id=book_id, page_index=page_index
    )
    return {"figures": [kb_ingestion_service.serialize_figure(f) for f in figures]}


@router.get("/figures/{figure_id}/image")
async def get_figure_image(
    figure_id: int,
    session: AsyncSession = Depends(get_session),
):
    from app.models.capabilities import SourceFigure

    figure = await session.get(SourceFigure, figure_id)
    if figure is None:
        raise HTTPException(status_code=404, detail="شکل یافت نشد.")
    # `image_path` comes from the database: never serve a path outside the
    # book's own figures directory (a tampered row must not turn this
    # admin-only endpoint into an arbitrary-file read, e.g. `../../.env`).
    # Read through kb_ingestion_service.figures_dir() at request time so the
    # check uses the same storage root that wrote the file.
    path = Path(figure.image_path).resolve()
    allowed_root = kb_ingestion_service.figures_dir(figure.book_id).resolve()
    if not path.is_file() or not path.is_relative_to(allowed_root):
        raise HTTPException(status_code=404, detail="فایل تصویر شکل در دسترس نیست.")
    return FileResponse(path, media_type="image/png")


class BenchmarkBody(BaseModel):
    models: list[str] = Field(min_length=1, max_length=6)
    pages: list[int] = Field(min_length=1, max_length=20)


@router.post("/books/{book_id}/benchmark")
async def benchmark_book_models(
    book_id: int,
    body: BenchmarkBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await kb_ingestion_service.benchmark_models(
            session, book_id=book_id, models=body.models, pages=body.pages
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result
