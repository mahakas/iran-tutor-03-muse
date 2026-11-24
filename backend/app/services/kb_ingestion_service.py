"""Web KB Pipeline (Phase 2).

Replaces the CLI-only ``scripts/ingest_book.py`` flow with an admin-driven,
database-tracked pipeline:

- :func:`create_ingestion_job` + :func:`run_ingestion_job` — background jobs
  (``kb_ingestion_jobs``) that drive :func:`ingest_book_pages` with live
  progress (processed/failed page counters) and cooperative cancellation.
- :func:`extract_source_figures` — pull embedded images out of PDF pages into
  ``storage/books/{id}/figures/`` and register ``source_figures`` rows so
  Vision chat can reference the actual textbook diagrams.
- :func:`reindex_page` / :func:`reindex_chapter` — re-run extraction for a
  single page or a whole chapter (force mode).
- :func:`benchmark_models` — Model Benchmark Lab: run the vision OCR skill
  with several models on sample pages and compare quality/latency/tokens.

All model calls go through the Central AI Gateway (``ingest_book_pages``
already uses ``vision_json_via_gateway``), so every page extraction lands in
``ai_audit_logs``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.capabilities import KbIngestionJob, SourceFigure
from app.models.curriculum import Book, BookPage, BookStatus, Grade, Major
from app.services.ingestion_service import (
    STORAGE_DIR,
    ingest_book_pages,
    pdf_page_count,
)

logger = logging.getLogger(__name__)

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

FIGURE_DIR_NAME = "figures"


def figures_dir(book_id: int | str) -> Path:
    return STORAGE_DIR / "books" / str(book_id) / FIGURE_DIR_NAME


def serialize_job(job: KbIngestionJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "book_id": job.book_id,
        "status": job.status,
        "total_pages": job.total_pages,
        "processed_pages": job.processed_pages,
        "failed_pages": job.failed_pages,
        "start_page": job.start_page,
        "end_page": job.end_page,
        "error_log": job.error_log,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


async def create_ingestion_job(
    session: AsyncSession,
    *,
    book_id: int,
    start_page: int,
    end_page: int,
) -> KbIngestionJob:
    job = KbIngestionJob(
        book_id=book_id,
        status=JOB_QUEUED,
        total_pages=end_page - start_page + 1,
        processed_pages=0,
        failed_pages=0,
        start_page=start_page,
        end_page=end_page,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def get_job(session: AsyncSession, job_id: str) -> KbIngestionJob | None:
    return await session.get(KbIngestionJob, job_id)


async def list_jobs(session: AsyncSession, *, book_id: int | None = None) -> list[KbIngestionJob]:
    query = select(KbIngestionJob).order_by(KbIngestionJob.created_at.desc())
    if book_id is not None:
        query = query.where(KbIngestionJob.book_id == book_id)
    rows = await session.scalars(query)
    return list(rows)


async def _update_job(job_id: str, **fields: Any) -> None:
    async with async_session_factory() as session:
        job = await session.get(KbIngestionJob, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        await session.commit()


async def _extract_figures_safely(book_id: int, start_page: int, end_page: int) -> int | None:
    try:
        async with async_session_factory() as session:
            result = await extract_source_figures(
                session, book_id=book_id, start_page=start_page, end_page=end_page
            )
        return int(result["figures_created"])
    except Exception:  # noqa: BLE001
        logger.exception("kb source figure extraction failed book=%s", book_id)
        return None


async def _set_book_status(book_id: int, status: BookStatus) -> None:
    async with async_session_factory() as session:
        book = await session.get(Book, book_id)
        if book is not None:
            book.status = status
            await session.commit()


async def _is_cancelled(job_id: str) -> bool:
    async with async_session_factory() as session:
        job = await session.get(KbIngestionJob, job_id)
        return job is not None and job.status == JOB_CANCELLED


async def run_ingestion_job(job_id: str) -> dict[str, Any]:
    """Execute a queued job in the background (called via BackgroundTasks)."""
    async with async_session_factory() as session:
        job = await session.get(KbIngestionJob, job_id)
        if job is None:
            return {"ok": False, "error": "job not found"}
        if job.status == JOB_CANCELLED:
            return {"ok": False, "error": "job cancelled before start"}
        book = await session.get(Book, job.book_id)
        if book is None:
            await _update_job(job_id, status=JOB_FAILED, error_log="کتاب یافت نشد.")
            return {"ok": False, "error": "book not found"}
        pdf_path = Path(book.pdf_file_path)
        grade = await session.get(Grade, book.grade_id)
        major = await session.get(Major, book.major_id) if book.major_id else None
        start_page = job.start_page or 1
        end_page = job.end_page or pdf_page_count(pdf_path)
        book_title = book.title
        book_db_id = book.id
        grade_number = grade.number if grade else None
        major_code = major.code if major else None

    settings = get_settings()
    await _update_job(job_id, status=JOB_RUNNING, started_at=datetime.now(timezone.utc))

    processed = 0
    failed = 0
    pending: set[asyncio.Task] = set()
    # Progress writes are serialised and read the counter when they run, so an
    # older write can never overwrite a newer count (out-of-order commits).
    progress_lock = asyncio.Lock()

    async def _flush_progress() -> None:
        async with progress_lock:
            await _update_job(job_id, processed_pages=processed, failed_pages=failed)

    def _progress(payload: dict[str, Any]) -> None:
        nonlocal processed
        # ingest_book_pages ticks once per page with status done|skipped.
        if payload.get("status") in ("done", "skipped"):
            processed += 1
        task = asyncio.get_running_loop().create_task(_flush_progress())
        pending.add(task)
        task.add_done_callback(pending.discard)

    try:
        report = await ingest_book_pages(
            pdf_path=pdf_path,
            book_id=book_db_id,
            grade_number=grade_number,
            major_code=major_code,
            book_title=book_title,
            start_page=start_page,
            end_page=end_page,
            model_primary=settings.vision_model_primary,
            model_escalation=settings.vision_model_escalation,
            escalate_figures=settings.escalate_figures,
            use_db=True,
            progress_callback=_progress,
        )
        if pending:
            await asyncio.gather(*list(pending), return_exceptions=True)
        failed = len(report.get("failed_pages") or [])
        cancelled = await _is_cancelled(job_id)
        if cancelled:
            await _update_job(
                job_id,
                status=JOB_CANCELLED,
                processed_pages=processed,
                failed_pages=failed,
                finished_at=datetime.now(timezone.utc),
            )
            return {"ok": False, "error": "cancelled", "report": report}
        await _set_book_status(book_db_id, BookStatus.ready)
        # Source figures are part of the pipeline, not a manual step. A figure
        # failure must not fail the (already successful) text ingestion.
        figures_count = await _extract_figures_safely(book_db_id, start_page, end_page)
        if figures_count is not None:
            report = {**report, "figures_created": figures_count}
        await _update_job(
            job_id,
            status=JOB_COMPLETED,
            processed_pages=processed,
            failed_pages=failed,
            finished_at=datetime.now(timezone.utc),
        )
        return {"ok": True, "report": report}
    except Exception as exc:  # noqa: BLE001
        logger.exception("kb ingestion job %s failed", job_id)
        await _set_book_status(book_db_id, BookStatus.failed)
        await _update_job(
            job_id,
            status=JOB_FAILED,
            error_log=f"{type(exc).__name__}: {str(exc)[:500]}",
            finished_at=datetime.now(timezone.utc),
        )
        return {"ok": False, "error": str(exc)[:500]}


async def cancel_ingestion_job(session: AsyncSession, job_id: str) -> KbIngestionJob | None:
    job = await session.get(KbIngestionJob, job_id)
    if job is None:
        return None
    if job.status in (JOB_QUEUED, JOB_RUNNING):
        job.status = JOB_CANCELLED
        job.finished_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Source figures
# ---------------------------------------------------------------------------


def serialize_figure(figure: SourceFigure) -> dict[str, Any]:
    return {
        "id": figure.id,
        "book_id": figure.book_id,
        "book_page_id": figure.book_page_id,
        "pdf_page_index": figure.pdf_page_index,
        "printed_page_number": figure.printed_page_number,
        "chapter_number": figure.chapter_number,
        "image_path": figure.image_path,
        "figure_label": figure.figure_label,
        "figure_type": figure.figure_type,
        "caption": figure.caption,
        "description": figure.description,
        "bbox": figure.bbox_json,
        "width": figure.width,
        "height": figure.height,
    }


async def list_figures(
    session: AsyncSession, *, book_id: int, page_index: int | None = None
) -> list[SourceFigure]:
    query = (
        select(SourceFigure)
        .where(SourceFigure.book_id == book_id)
        .order_by(SourceFigure.pdf_page_index.asc(), SourceFigure.id.asc())
    )
    if page_index is not None:
        query = query.where(SourceFigure.pdf_page_index == page_index)
    rows = await session.scalars(query)
    return list(rows)


async def extract_source_figures(
    session: AsyncSession,
    *,
    book_id: int,
    start_page: int | None = None,
    end_page: int | None = None,
    replace: bool = True,
) -> dict[str, Any]:
    """Extract embedded images from the book PDF and register source figures.

    Uses PyMuPDF's image XObject listing per page; each unique image is saved
    under ``storage/books/{book_id}/figures/`` and linked to its page row (when
    the page has been ingested) so Vision chat can cite the real diagram.
    """
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("کتاب یافت نشد.")
    pdf_path = Path(book.pdf_file_path)
    if pdf_path.suffix.lower() != ".pdf" or not pdf_path.is_file():
        raise ValueError("فایل PDF اصلی این کتاب در دسترس نیست.")

    page_rows = list(
        (
            await session.scalars(
                select(BookPage).where(BookPage.book_id == book_id)
            )
        ).all()
    )
    page_by_index = {row.pdf_page_index: row for row in page_rows}

    doc = pymupdf.open(pdf_path)
    out_dir = figures_dir(book_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    created = 0
    skipped = 0
    try:
        first = start_page or 1
        last = end_page or doc.page_count
        for page_number in range(first, min(last, doc.page_count) + 1):
            page = doc[page_number - 1]
            images = page.get_images(full=True)
            if not images:
                continue
            page_row = page_by_index.get(page_number)
            if replace:
                stale = list(
                    (
                        await session.scalars(
                            select(SourceFigure).where(
                                SourceFigure.book_id == book_id,
                                SourceFigure.pdf_page_index == page_number,
                            )
                        )
                    ).all()
                )
                for old in stale:
                    await session.delete(old)
                await session.flush()
            for img_index, image_info in enumerate(images, start=1):
                xref = image_info[0]
                try:
                    pix = pymupdf.Pixmap(doc, xref)
                except Exception:  # noqa: BLE001
                    skipped += 1
                    continue
                if pix.n > 4:  # CMYK etc. — convert to RGB
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                filename = f"page_{page_number:04d}_fig_{img_index:02d}.png"
                target = out_dir / filename
                pix.save(target)
                figure = SourceFigure(
                    book_id=book_id,
                    book_page_id=page_row.id if page_row else None,
                    pdf_page_index=page_number,
                    printed_page_number=page_row.printed_page_number if page_row else None,
                    chapter_number=page_row.chapter_number if page_row else None,
                    image_path=str(target),
                    figure_label=f"شکل {img_index} صفحهٔ {page_number}",
                    figure_type="embedded_image",
                    width=pix.width,
                    height=pix.height,
                )
                session.add(figure)
                created += 1
            await session.commit()
    finally:
        doc.close()
    return {"book_id": book_id, "figures_created": created, "skipped": skipped}


# ---------------------------------------------------------------------------
# Re-index helpers
# ---------------------------------------------------------------------------


async def reindex_page(
    session: AsyncSession, *, book_id: int, pdf_page_index: int
) -> dict[str, Any]:
    """Re-run vision extraction for a single page (force mode)."""
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("کتاب یافت نشد.")
    pdf_path = Path(book.pdf_file_path)
    if pdf_path.suffix.lower() != ".pdf" or not pdf_path.is_file():
        raise ValueError("فایل PDF اصلی این کتاب در دسترس نیست.")
    settings = get_settings()
    grade = await session.get(Grade, book.grade_id)
    major = await session.get(Major, book.major_id) if book.major_id else None
    report = await ingest_book_pages(
        pdf_path=pdf_path,
        book_id=book_id,
        grade_number=grade.number if grade else None,
        major_code=major.code if major else None,
        book_title=book.title,
        start_page=pdf_page_index,
        end_page=pdf_page_index,
        model_primary=settings.vision_model_primary,
        model_escalation=settings.vision_model_escalation,
        escalate_figures=settings.escalate_figures,
        use_db=True,
        force=True,
    )
    return {"book_id": book_id, "pdf_page_index": pdf_page_index, "report": report}


async def reindex_chapter(
    session: AsyncSession, *, book_id: int, chapter_number: int
) -> dict[str, Any]:
    """Re-run vision extraction for every ingested page of a chapter."""
    rows = list(
        (
            await session.scalars(
                select(BookPage.pdf_page_index)
                .where(
                    BookPage.book_id == book_id,
                    BookPage.chapter_number == chapter_number,
                )
                .order_by(BookPage.pdf_page_index.asc())
            )
        ).all()
    )
    if not rows:
        raise ValueError(f"صفحه‌ای از فصل {chapter_number} در این کتاب ثبت نشده است.")
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("کتاب یافت نشد.")
    pdf_path = Path(book.pdf_file_path)
    if pdf_path.suffix.lower() != ".pdf" or not pdf_path.is_file():
        raise ValueError("فایل PDF اصلی این کتاب در دسترس نیست.")
    settings = get_settings()
    grade = await session.get(Grade, book.grade_id)
    major = await session.get(Major, book.major_id) if book.major_id else None
    report = await ingest_book_pages(
        pdf_path=pdf_path,
        book_id=book_id,
        grade_number=grade.number if grade else None,
        major_code=major.code if major else None,
        book_title=book.title,
        start_page=min(rows),
        end_page=max(rows),
        model_primary=settings.vision_model_primary,
        model_escalation=settings.vision_model_escalation,
        escalate_figures=settings.escalate_figures,
        use_db=True,
        force=True,
    )
    return {
        "book_id": book_id,
        "chapter_number": chapter_number,
        "pages": list(rows),
        "report": report,
    }


# ---------------------------------------------------------------------------
# Model Benchmark Lab
# ---------------------------------------------------------------------------


async def benchmark_models(
    session: AsyncSession,
    *,
    book_id: int,
    models: list[str],
    pages: list[int],
) -> dict[str, Any]:
    """Compare vision OCR models on sample pages (compare mode, no DB writes
    to the production page rows beyond the compare artifacts)."""
    if not models:
        raise ValueError("حداقل یک مدل برای مقایسه لازم است.")
    if not pages:
        raise ValueError("حداقل یک صفحه برای نمونه لازم است.")
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("کتاب یافت نشد.")
    pdf_path = Path(book.pdf_file_path)
    if pdf_path.suffix.lower() != ".pdf" or not pdf_path.is_file():
        raise ValueError("فایل PDF اصلی این کتاب در دسترس نیست.")
    grade = await session.get(Grade, book.grade_id)
    major = await session.get(Major, book.major_id) if book.major_id else None
    start_page, end_page = min(pages), max(pages)
    report = await ingest_book_pages(
        pdf_path=pdf_path,
        book_id=book_id,
        grade_number=grade.number if grade else None,
        major_code=major.code if major else None,
        book_title=book.title,
        start_page=start_page,
        end_page=end_page,
        models=models,
        use_db=False,
        force=True,
    )
    totals = report.get("totals") or {}
    comparison = []
    for model in models:
        total = totals.get(model) or {}
        comparison.append(
            {
                "model": model,
                "pages": total.get("pages", 0),
                "done": total.get("done", 0),
                "failed": total.get("failed", 0),
                "needs_review": total.get("needs_review", 0),
                "warnings": total.get("warnings", 0),
                "tokens": total.get("tokens", 0),
                "latency_seconds": round(float(total.get("latency", 0.0)), 3),
            }
        )
    return {
        "book_id": book_id,
        "pages": pages,
        "models": models,
        "comparison": comparison,
        "totals": totals,
    }
