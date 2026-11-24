"""Phase 1 step C+D: PDF ingestion engine.

Renders PDF pages to PNG (200 DPI), extracts each page with a vision LLM via
``vision_json``, validates with Pydantic, applies sanity checks, optionally
escalates low-quality/figure pages to a second model, and saves both to storage
(JSON + Markdown per page) and to Postgres.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.curriculum import Book, BookPage, Grade, Major, PageStatus
from app.services.ai_gateway import CallContext, vision_json_via_gateway
from app.services.ingestion_checks import (
    check_printed_consistency,
    choose_escalation,
    outcome_quality,
    printed_page_offset,
    should_escalate,
    should_process,
)

logger = logging.getLogger(__name__)

STORAGE_DIR = Path(__file__).resolve().parents[2] / "storage"
DPI = 200
UPLOAD_DIR = STORAGE_DIR / "uploads"

__all__ = [
    "STORAGE_DIR",
    "UPLOAD_DIR",
    "PageExtraction",
    "VisualElement",
    "check_printed_consistency",
    "choose_escalation",
    "extracted_dir",
    "ingest_book_pages",
    "model_tag",
    "page_image_path",
    "printed_page_offset",
    "render_pdf_pages",
    "should_escalate",
    "should_process",
]


class VisualElement(BaseModel):
    label: str
    type: str
    scientific_description: str


class PageExtraction(BaseModel):
    printed_page_number: int | None = None
    chapter_number: int | None = None
    chapter_title: str | None = None
    markdown_content: str = ""
    visual_elements: list[VisualElement] = Field(default_factory=list)


EXTRACTION_SYSTEM_PROMPT = (
    "تو یک موتور استخراج دقیق از کتاب‌های درسی رسمی ایران هستی. "
    "متن صفحه را با دقت کامل استخراج کن و فقط به‌صورت JSON برگردان؛ هیچ متن دیگری اضافه نکن.\n"
    "قوانین:\n"
    "- جهت راست‌به‌چپ (RTL) را حفظ کن و نیم‌فاصله (ZWNJ) را درست رعایت کن.\n"
    "- تمام فرمول‌ها، بردارها، حروف یونانی، واحدها و پایین/بالانویس‌ها را به LaTeX تبدیل کن: "
    "درون‌خطی با $...$ و نمایشی با $$...$$.\n"
    "- هرگز ترجمه نکن و چیزی ابداع نکن؛ فقط آنچه را در کتاب هست بنویس.\n"
    "- جعبه‌هایی مانند پرسش/مثال/تمرین/فعالیت/خود را بیازمایید را به عناوین مارک‌داون "
    "یا بلوک‌نقل‌قول تبدیل کن.\n"
    "- هر نمودار و شکل را به فارسی توصیف کن: محورها، واحدها، رفتار منحنی، شیب‌ها و نقاط کلیدی، "
    "طوری که دانش‌آموز نابینا یا نظام بازیابی درکش کند.\n"
    "- نمادها را دقیقاً مثل کتاب درسی ایران بنویس.\n"
    "- اگر از نویسه‌ای مطمئن نیستی به جای حدس زدن [؟] بنویس.\n"
    "- شماره صفحه چاپی: عددی که واقعاً روی صفحه چاپ شده؛ برای جلد یا صفحات خالی مقدار null.\n"
    "ساختار JSON:\n"
    '{"printed_page_number": int|null, "chapter_number": int|null, "chapter_title": str|null, '
    '"markdown_content": str, '
    '"visual_elements": [{"label": str, "type": str, "scientific_description": str}]}\n'
)

USER_PROMPT = "این صفحه از کتاب درسی را استخراج کن و JSON را دقیقاً مطابق ساختار اعلام‌شده برگردان."


def page_image_path(book_id: str | int, idx: int) -> Path:
    return STORAGE_DIR / "books" / str(book_id) / "pages" / f"page_{idx:04d}.png"


def extracted_dir(book_id: str | int, tag: str) -> Path:
    return STORAGE_DIR / "books" / str(book_id) / "extracted" / tag


def model_tag(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", model)


def _unbalanced_dollars_warning(markdown: str) -> str | None:
    unescaped = re.sub(r"\\\$", "", markdown)
    if unescaped.count("$") % 2 != 0:
        return "unbalanced $ delimiters in markdown"
    return None


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Rendering / saving
# ---------------------------------------------------------------------------


def pdf_page_count(pdf_path: Path) -> int:
    doc = pymupdf.open(pdf_path)
    try:
        return doc.page_count
    finally:
        doc.close()


def render_pdf_pages(
    pdf_path: Path, book_id: str | int, start_page: int, end_page: int, dpi: int = DPI
) -> dict[int, Path]:
    if start_page < 1 or end_page < start_page:
        raise ValueError("invalid page range: expected 1 <= start_page <= end_page")

    doc = pymupdf.open(pdf_path)
    rendered: dict[int, Path] = {}
    try:
        if end_page > doc.page_count:
            raise ValueError(
                f"page range ends at {end_page}, but the PDF contains only {doc.page_count} pages"
            )
        for idx in range(start_page, end_page + 1):
            page = doc[idx - 1]
            pix = page.get_pixmap(dpi=dpi)
            target = page_image_path(book_id, idx)
            target.parent.mkdir(parents=True, exist_ok=True)
            pix.save(target)
            rendered[idx] = target
    finally:
        doc.close()
    return rendered


def _save_page_outputs(book_id: str | int, tag: str, idx: int, data: dict[str, Any]) -> tuple[Path, Path]:
    folder = extracted_dir(book_id, tag)
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / f"page_{idx:04d}.json"
    md_path = folder / f"page_{idx:04d}.md"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(data.get("markdown", ""), encoding="utf-8")
    return json_path, md_path


async def _upsert_page(session: AsyncSession, book_id: int, values: dict[str, Any]) -> None:
    insert = pg_insert
    if session.get_bind().dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        insert = sqlite_insert
    stmt = insert(BookPage).values(**values).on_conflict_do_update(
        index_elements=["book_id", "pdf_page_index"],
        set_={k: v for k, v in values.items() if k not in ("book_id", "pdf_page_index")},
    )
    await session.execute(stmt)


async def _load_existing_rows(
    session: AsyncSession | None, book_id: int | None
) -> dict[int, dict[str, Any]]:
    if session is None or book_id is None:
        return {}
    rows = await session.execute(
        select(BookPage.pdf_page_index, BookPage.status, BookPage.edited_by_human).where(
            BookPage.book_id == book_id
        )
    )
    return {
        idx: {"status": status, "edited_by_human": edited}
        for idx, status, edited in rows
    }


async def resolve_book(
    session: AsyncSession,
    *,
    title: str,
    grade_number: int | None,
    major_code: str | None,
) -> Book | None:
    """Find an existing book by title + grade + major."""
    query = select(Book).where(Book.title == title)
    if grade_number is not None:
        grade_id = await session.scalar(select(Grade.id).where(Grade.number == grade_number))
        if grade_id is None:
            return None
        query = query.where(Book.grade_id == grade_id)
    if major_code:
        major_id = await session.scalar(select(Major.id).where(Major.code == major_code))
        if major_id is None:
            return None
        query = query.where(Book.major_id == major_id)
    return await session.scalar(query.limit(1))


# ---------------------------------------------------------------------------
# Single-page extraction
# ---------------------------------------------------------------------------


async def _run_page(
    sem: asyncio.Semaphore,
    idx: int,
    model: str,
    image_path: Path,
    carry: dict[str, Any],
) -> dict[str, Any]:
    async with sem:
        started = time.perf_counter()
        try:
            gateway_result = await vision_json_via_gateway(
                ctx=CallContext(feature_key="ingest_ocr", book_id=carry.get("book_id")),
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                user_text=USER_PROMPT,
                image_bytes=image_path.read_bytes(),
                model=model,
            )
            parsed = gateway_result.content
            usage = {
                "prompt_tokens": gateway_result.tokens_in,
                "completion_tokens": gateway_result.tokens_out,
                "total_tokens": gateway_result.tokens_in + gateway_result.tokens_out,
            }
            latency = time.perf_counter() - started
            try:
                extraction = PageExtraction.model_validate(parsed)
            except ValidationError as exc:
                return {
                    "status": PageStatus.needs_review,
                    "error": f"JSON validation issue: {str(exc)[:300]}",
                    "warnings": [f"JSON validation issue: {str(exc)[:200]}"],
                    "extraction": None,
                    "usage": usage,
                    "latency": latency,
                }
        except Exception as exc:  # noqa: BLE001
            latency = time.perf_counter() - started
            return {
                "status": PageStatus.failed,
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "warnings": [],
                "extraction": None,
                "usage": None,
                "latency": latency,
            }

        warnings: list[str] = []
        if get_settings().demo_mode:
            warnings.append("DEMO_MODE: OCR واقعی اجرا نشده؛ این صفحه قبل از RAG باید توسط انسان بازبینی شود.")

        if extraction.chapter_number is None and carry.get("chapter_number") is not None:
            extraction.chapter_number = carry["chapter_number"]
        if extraction.chapter_title is None and carry.get("chapter_title") is not None:
            extraction.chapter_title = carry["chapter_title"]

        unbalanced = _unbalanced_dollars_warning(extraction.markdown_content)
        if unbalanced:
            warnings.append(unbalanced)
        if extraction.printed_page_number is not None and not extraction.markdown_content.strip():
            warnings.append("empty markdown on non-blank page")

        consistency = check_printed_consistency(
            carry.get("prev_printed"), extraction.printed_page_number
        )
        if consistency:
            warnings.append(consistency)

        carry["chapter_number"] = (
            extraction.chapter_number
            if extraction.chapter_number is not None
            else carry.get("chapter_number")
        )
        carry["chapter_title"] = (
            extraction.chapter_title
            if extraction.chapter_title is not None
            else carry.get("chapter_title")
        )
        if extraction.printed_page_number is not None:
            carry["prev_printed"] = extraction.printed_page_number

        status = PageStatus.needs_review if warnings else PageStatus.done
        return {
            "status": status,
            "error": None,
            "warnings": warnings,
            "extraction": extraction,
            "usage": usage,
            "latency": latency,
        }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _export_page_from_row(row: BookPage) -> dict[str, Any]:
    status = row.status.value if hasattr(row.status, "value") else row.status
    return {
        "pdf_page_index": row.pdf_page_index,
        "printed_page_number": row.printed_page_number,
        "chapter_number": row.chapter_number,
        "chapter_title": row.chapter_title,
        "status": status,
        "warnings": row.warnings or [],
        "markdown_content": row.markdown_content or "",
        "visual_elements": row.visual_elements or [],
        "model": row.extraction_model,
        "edited_by_human": bool(row.edited_by_human),
    }


def build_export_pages(rows: list[BookPage]) -> list[dict[str, Any]]:
    return [_export_page_from_row(row) for row in sorted(rows, key=lambda r: r.pdf_page_index)]


def _export_assets(book_id: str | int, pages: list[dict[str, Any]]) -> dict[str, Any]:
    folder = STORAGE_DIR / "books" / str(book_id)
    folder.mkdir(parents=True, exist_ok=True)
    md_lines: list[str] = []
    for p in pages:
        printed = p.get("printed_page_number")
        chapter = p.get("chapter_number")
        md_lines.append(
            f"<!-- page: pdf={p['pdf_page_index']} printed={printed if printed is not None else 'null'} "
            f"chapter={chapter if chapter is not None else 'null'} -->"
        )
        md_lines.append(p.get("markdown_content", ""))
        md_lines.append("")
    (folder / "book.md").write_text("\n".join(md_lines), encoding="utf-8")

    offset, deviations = printed_page_offset(
        (p["pdf_page_index"], p.get("printed_page_number")) for p in pages
    )
    payload = {
        "book_id": str(book_id),
        "printed_page_offset": offset,
        "printed_page_deviations": deviations,
        "pages": pages,
    }
    (folder / "book.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def ingest_book_pages(
    *,
    pdf_path: Path,
    book_id: str | int,
    grade_number: int | None = None,
    major_code: str | None = None,
    book_title: str | None = None,
    start_page: int,
    end_page: int,
    models: list[str] | None = None,
    model_primary: str | None = None,
    model_escalation: str | None = None,
    escalate_figures: bool = False,
    use_db: bool = True,
    force: bool = False,
    only_failed: bool = False,
    overwrite_human: bool = False,
    dry_run: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Ingest pages ``start_page..end_page``.

    ``models`` selects compare mode (multiple models, no escalation). Otherwise
    production mode uses ``model_primary`` with optional escalation to
    ``model_escalation``.

    ``dry_run`` resolves the book and the page plan without rendering pages,
    calling the LLM or writing anything.
    """
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if start_page < 1 or end_page < start_page:
        raise ValueError("invalid page range: expected 1 <= start_page <= end_page")
    page_count = pdf_page_count(pdf_path)
    if end_page > page_count:
        raise ValueError(
            f"page range ends at {end_page}, but the PDF contains only {page_count} pages"
        )

    settings = get_settings()
    sem = asyncio.Semaphore(settings.max_concurrency)

    compare_mode = models is not None
    if compare_mode:
        model_names = list(models)
    else:
        if model_primary is None:
            raise ValueError("model_primary is required outside compare mode")
        model_names = [model_primary]
        if model_escalation and model_escalation != model_primary:
            model_names.append(model_escalation)

    session: AsyncSession | None = None
    db_book_id: int | None = None
    if use_db:
        session = async_session_factory()
        book = None
        if isinstance(book_id, int) or (isinstance(book_id, str) and book_id.isdigit()):
            candidate = await session.get(Book, int(book_id))
            if candidate is not None:
                book = candidate
        if book is None:
            book = await resolve_book(
                session,
                title=book_title or "",
                grade_number=grade_number,
                major_code=major_code,
            )
        if book is None and not dry_run:
            grade_id = None
            if grade_number is not None:
                grade_id = await session.scalar(select(Grade.id).where(Grade.number == grade_number))
            major_id = None
            if major_code:
                major_id = await session.scalar(select(Major.id).where(Major.code == major_code))
            book = Book(
                title=book_title or pdf_path.stem,
                grade_id=grade_id,
                major_id=major_id,
                pdf_file_path=str(pdf_path),
                total_pdf_pages=pdf_page_count(pdf_path),
                status="ingesting",
            )
            session.add(book)
            await session.commit()
            await session.refresh(book)
        if book is not None:
            db_book_id = book.id
            if not dry_run:
                book.status = "ingesting"
                await session.commit()

    storage_book_id: str | int = db_book_id if db_book_id is not None else book_id
    existing = (
        await _load_existing_rows(session, db_book_id)
        if (use_db and db_book_id is not None and session is not None)
        else {}
    )

    totals: dict[str, dict[str, Any]] = {
        m: {
            "tokens": 0,
            "latency": 0.0,
            "warnings": 0,
            "pages": 0,
            "done": 0,
            "failed": 0,
            "needs_review": 0,
        }
        for m in model_names
    }
    results: dict[str, dict[int, dict[str, Any]]] = {m: {} for m in model_names}
    outputs: dict[str, dict[int, dict[str, str]]] = {m: {} for m in model_names}
    carries = {m: {"chapter_number": None, "chapter_title": None, "prev_printed": None} for m in model_names}
    escalated_pages = 0
    skipped_pages = 0
    processed_pages = 0
    warnings_by_page: dict[int, list[str]] = {}

    def _tick(status: str = "", tokens: int = 0) -> None:
        if progress_callback is not None:
            progress_callback({"status": status, "tokens": tokens})

    # --- dry run: decide the plan only ---
    if dry_run:
        plan: list[dict[str, Any]] = []
        for idx in range(start_page, end_page + 1):
            existing_idx = existing.get(idx)
            if compare_mode:
                decision = True
                reason = "compare"
            else:
                decision = should_process(
                    existing_idx["status"] if existing_idx else None,
                    bool(existing_idx["edited_by_human"]) if existing_idx else False,
                    force=force,
                    only_failed=only_failed,
                    overwrite_human=overwrite_human,
                )
                reason = "process" if decision else "skip"
            plan.append({"pdf_page_index": idx, "decision": decision, "reason": reason})
            if decision:
                processed_pages += 1
            else:
                skipped_pages += 1
        if session is not None:
            await session.close()
        return {
            "book_id": db_book_id if db_book_id is not None else book_id,
            "dry_run": True,
            "plan": plan,
            "processed": processed_pages,
            "skipped": skipped_pages,
            "results": results,
            "totals": totals,
            "outputs": outputs,
            "escalated_pages": 0,
            "total_tokens": 0,
            "pages": [],
            "printed_page_offset": None,
            "printed_page_deviations": [],
        }

    images = render_pdf_pages(pdf_path, storage_book_id, start_page, end_page)

    try:
        for idx in range(start_page, end_page + 1):
            image_path = images[idx]
            existing_idx = existing.get(idx)

            if compare_mode:
                for model in model_names:
                    if (
                        not force
                        and not only_failed
                        and existing_idx
                        and existing_idx["status"] == PageStatus.done
                    ):
                        results[model][idx] = {
                            "status": PageStatus.done,
                            "skipped": True,
                            "warnings": [],
                            "latency": 0.0,
                        }
                        totals[model]["pages"] += 1
                        totals[model]["done"] += 1
                        continue
                    outcome = await _run_page(sem, idx, model, image_path, carries[model])
                    data = _build_page_data(idx, model, image_path, outcome)
                    json_path, md_path = _save_page_outputs(storage_book_id, model_tag(model), idx, data)
                    outputs[model][idx] = {"json": str(json_path), "md": str(md_path)}
                    results[model][idx] = data
                    _accumulate(totals[model], outcome)
                    if use_db and db_book_id is not None and session is not None:
                        values = _page_values(db_book_id, idx, image_path, model, outcome)
                        await _upsert_page(session, db_book_id, values)
                        await session.commit()
                _tick("done", sum(t["tokens"] for t in totals.values()))
                continue

            # ---- production mode ----
            if not should_process(
                existing_idx["status"] if existing_idx else None,
                bool(existing_idx["edited_by_human"]) if existing_idx else False,
                force=force,
                only_failed=only_failed,
                overwrite_human=overwrite_human,
            ):
                prev = existing_idx["status"] if existing_idx else None
                results[model_primary][idx] = {
                    "status": prev,
                    "skipped": True,
                    "warnings": [],
                    "latency": 0.0,
                }
                totals[model_primary]["pages"] += 1
                if prev == PageStatus.done:
                    totals[model_primary]["done"] += 1
                skipped_pages += 1
                _tick("skipped", sum(t["tokens"] for t in totals.values()))
                continue

            primary_outcome = await _run_page(
                sem, idx, model_primary, image_path, carries[model_primary]
            )
            primary_data = _build_page_data(idx, model_primary, image_path, primary_outcome)
            json_path, md_path = _save_page_outputs(
                storage_book_id, model_tag(model_primary), idx, primary_data
            )
            outputs[model_primary][idx] = {"json": str(json_path), "md": str(md_path)}

            final_outcome = primary_outcome
            final_model = model_primary
            escalation_rejected: str | None = None
            esc_outcome: dict[str, Any] | None = None

            if (
                model_escalation
                and model_escalation != model_primary
                and should_escalate(
                    primary_outcome["status"], _visuals(primary_outcome), escalate_figures
                )
            ):
                esc_outcome = await _run_page(
                    sem, idx, model_escalation, image_path, carries[model_escalation]
                )
                esc_data = _build_page_data(idx, model_escalation, image_path, esc_outcome)
                esc_json, esc_md = _save_page_outputs(
                    storage_book_id, model_tag(model_escalation), idx, esc_data
                )
                outputs[model_escalation][idx] = {"json": str(esc_json), "md": str(esc_md)}
                use_escalation, final_outcome = choose_escalation(primary_outcome, esc_outcome)
                if use_escalation:
                    final_model = model_escalation
                    escalated_pages += 1
                else:
                    escalation_rejected = "escalated result was not better than primary"

            final_data = _build_page_data(idx, final_model, image_path, final_outcome)
            results[final_model][idx] = final_data
            _accumulate_usage(totals[model_primary], primary_outcome)
            if esc_outcome is not None and model_escalation in totals:
                _accumulate_usage(totals[model_escalation], esc_outcome)
            _accumulate_status(totals[final_model], final_outcome)
            if escalation_rejected:
                warnings_by_page_extra = warnings_by_page.setdefault(idx, [])
                if isinstance(warnings_by_page_extra, list):
                    warnings_by_page_extra.append(escalation_rejected)

            if use_db and db_book_id is not None and session is not None:
                values = _page_values(db_book_id, idx, image_path, final_model, final_outcome)
                await _upsert_page(session, db_book_id, values)
                await session.commit()
            processed_pages += 1
            _tick("done", sum(t["tokens"] for t in totals.values()))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.warning("ingestion interrupted at page %s", idx)
        if session is not None and db_book_id is not None:
            book = await session.get(Book, db_book_id)
            if book is not None:
                book.status = "failed"
                await session.commit()
            await session.close()
            session = None
        raise

    export_pages: list[dict[str, Any]] = []
    if use_db and db_book_id is not None and session is not None:
        rows = list(
            (
                await session.scalars(
                    select(BookPage)
                    .where(BookPage.book_id == db_book_id)
                    .order_by(BookPage.pdf_page_index)
                )
            ).all()
        )
        export_pages = build_export_pages(rows)
        book = await session.get(Book, db_book_id)
        if book is not None:
            active = [t for t in totals.values() if t["pages"]]
            all_failed = bool(active) and all(t["failed"] == t["pages"] for t in active)
            book.status = "failed" if all_failed else "ready"
            await session.commit()
        await session.close()

    export_payload: dict[str, Any] = {}
    try:
        if export_pages:
            export_payload = _export_assets(storage_book_id, export_pages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("export failed: %s", exc)

    needs_review_pages = [
        p["pdf_page_index"]
        for p in export_pages
        if p.get("status") == PageStatus.needs_review.value
    ]
    failed_pages = [p["pdf_page_index"] for p in export_pages if p.get("status") == PageStatus.failed.value]
    for p in export_pages:
        page_warnings = list(p.get("warnings") or [])
        if page_warnings:
            warnings_by_page[p["pdf_page_index"]] = page_warnings + warnings_by_page.get(
                p["pdf_page_index"], []
            )
        else:
            warnings_by_page.setdefault(p["pdf_page_index"], [])

    report_total_tokens = sum(t["tokens"] for t in totals.values())
    return {
        "book_id": db_book_id if db_book_id is not None else storage_book_id,
        "storage_book_id": storage_book_id,
        "images": {idx: str(p) for idx, p in images.items()},
        "results": results,
        "totals": totals,
        "outputs": outputs,
        "escalated_pages": escalated_pages,
        "total_tokens": report_total_tokens,
        "processed": processed_pages,
        "skipped": skipped_pages,
        "pages": export_pages,
        "needs_review_pages": needs_review_pages,
        "failed_pages": failed_pages,
        "warnings_by_page": warnings_by_page,
        "printed_page_offset": export_payload.get("printed_page_offset"),
        "printed_page_deviations": export_payload.get("printed_page_deviations", []),
    }


def _visuals(outcome: dict[str, Any]) -> list:
    extraction = outcome.get("extraction")
    return extraction.visual_elements if extraction else []


def _build_page_data(idx: int, model: str, image_path: Path, outcome: dict[str, Any]) -> dict[str, Any]:
    extraction = outcome.get("extraction")
    return {
        "pdf_page_index": idx,
        "status": outcome["status"],
        "error": outcome.get("error"),
        "warnings": outcome.get("warnings", []),
        "markdown": extraction.markdown_content if extraction else "",
        "visual_elements": [el.model_dump() for el in extraction.visual_elements] if extraction else [],
        "printed_page_number": extraction.printed_page_number if extraction else None,
        "chapter_number": extraction.chapter_number if extraction else None,
        "chapter_title": extraction.chapter_title if extraction else None,
        "model": model,
        "latency": outcome.get("latency", 0.0),
        "usage": outcome.get("usage"),
        "image_path": str(image_path),
    }


def _accumulate(total: dict[str, Any], outcome: dict[str, Any]) -> None:
    _accumulate_usage(total, outcome)
    _accumulate_status(total, outcome)


def _accumulate_usage(total: dict[str, Any], outcome: dict[str, Any]) -> None:
    usage = outcome.get("usage") or {}
    total["tokens"] += int(usage.get("total_tokens") or 0)
    total["latency"] += outcome.get("latency", 0.0)


def _accumulate_status(total: dict[str, Any], outcome: dict[str, Any]) -> None:
    total["warnings"] += len(outcome.get("warnings", []))
    total["pages"] += 1
    status = outcome["status"]
    total[status.value if hasattr(status, "value") else str(status)] += 1


def _page_values(book_id: int, idx: int, image_path: Path, model: str, outcome: dict[str, Any]) -> dict[str, Any]:
    extraction = outcome.get("extraction")
    usage = outcome.get("usage") or {}
    return {
        "book_id": book_id,
        "pdf_page_index": idx,
        "printed_page_number": extraction.printed_page_number if extraction else None,
        "chapter_number": extraction.chapter_number if extraction else None,
        "chapter_title": extraction.chapter_title if extraction else None,
        "markdown_content": extraction.markdown_content if extraction else "",
        "visual_elements": [el.model_dump() for el in extraction.visual_elements] if extraction else [],
        "page_image_path": str(image_path),
        "status": outcome["status"],
        "error_message": outcome.get("error"),
        "extraction_model": model,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "warnings": outcome.get("warnings", []),
    }
