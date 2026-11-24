"""Admin education-catalog management service.

A real CRUD system over the education taxonomy (cycles, grades, branches,
grounds, programs, subjects, catalog textbooks, offering links, academic years,
editions, program availability) with:
- dependency-guarded deletion (hard delete only when nothing references the
  record; otherwise the admin archives/deactivates instead),
- soft-archive/restore where the model carries is_active/archived_at,
- reuse of AdminActionLog for a full before/after audit trail,
- honest handling of the auto-publish rule: an admin can unpull an edition from
  student reach, but `ready` is only ever set by the ingest pipeline,
- Persian error messages and Persian audit payloads.

Student self-service is untouched: catalog edits change what EXISTS, never a
student's own placement.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.catalog import (
    CatalogCourseTextbook,
    CatalogTextbook,
    EducationGround,
    ProgramAvailability,
)
from app.models.curriculum import (
    AcademicYear,
    Book,
    BookStatus,
    BookCurriculumLink,
    EducationBranch,
    EducationCycle,
    FieldOfStudy,
    Grade,
    Subject,
)
from app.models.phase5 import AdminActionLog
from app.services import permissions

ARCHIVE_DIR = Path("storage/books")

# Persian labels for audit + UI payloads
ENTITY_LABELS: dict[str, str] = {
    "cycles": "دورهٔ تحصیلی",
    "grades": "پایه",
    "branches": "شاخه",
    "grounds": "زمینه",
    "fields": "رشته",
    "subjects": "درس",
    "textbooks": "کتاب کاتالوگ",
    "links": "ارتباط کتاب",
    "academic-years": "سال تحصیلی",
    "editions": "نسخهٔ کتاب",
    "program-availability": "وضعیت اعتبار رشته",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def log_action(
    session: AsyncSession,
    *,
    actor: permissions.AdminActor,
    action: str,
    entity: str,
    entity_id: int | str,
    before: dict | None = None,
    after: dict | None = None,
    result: str = "success",
    note: str | None = None,
) -> None:
    """Audit trail (AdminActionLog) — no secrets are ever stored here."""
    payload: dict[str, Any] = {
        "entity": entity,
        "entity_label": ENTITY_LABELS.get(entity, entity),
        "entity_id": str(entity_id),
        "before": before or {},
        "after": after or {},
        "result": result,
    }
    if note:
        payload["note"] = note
    session.add(
        AdminActionLog(
            actor=actor.user_id or actor.role,
            action=f"catalog.{entity}.{action}",
            target=f"catalog:{entity}:{entity_id}",
            payload_json=payload,
        )
    )
    await session.commit()


def _model_for(entity: str) -> type:
    models = {
        "cycles": EducationCycle,
        "grades": Grade,
        "branches": EducationBranch,
        "grounds": EducationGround,
        "fields": FieldOfStudy,
        "subjects": Subject,
        "textbooks": CatalogTextbook,
        "links": CatalogCourseTextbook,
        "academic-years": AcademicYear,
        "editions": Book,
        "program-availability": ProgramAvailability,
    }
    if entity not in models:
        raise HTTPException(status_code=404, detail="موجودیت کاتالوگ شناخته‌شده نیست.")
    return models[entity]


def _slugify(text: str) -> str:
    slug = re.sub(r"[\s،,\-_ـ]+", "-", text.strip())
    return re.sub(r"-+", "-", slug).strip("-") or "item"


# field name → validator/normalizer applied on create/update
def _clean(entity: str, field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in {"title", "title_fa", "full_name"} and isinstance(value, str):
        return value.strip()[:255]
    if field in {"code", "slug"} and isinstance(value, str):
        return value.strip()[:80]
    if field in {"national_code"} and isinstance(value, str):
        value = value.strip()
        return value or None  # never fabricate
    return value


async def _ensure_fk(session: AsyncSession, model: type, value: int | None, label: str) -> int | None:
    if value is None:
        return None
    obj = await session.get(model, value)
    if obj is None:
        raise HTTPException(status_code=422, detail=f"{label} یافت نشد.")
    return value


async def _validate_row(session: AsyncSession, entity: str, data: dict[str, Any], *, obj_id: int | None = None) -> dict[str, Any]:
    """FK existence + cross-entity consistency for one row's payload."""
    if "cycle_id" in data and data["cycle_id"] is not None:
        await _ensure_fk(session, EducationCycle, data["cycle_id"], "دورهٔ تحصیلی")
    if "branch_id" in data and data["branch_id"] is not None:
        await _ensure_fk(session, EducationBranch, data["branch_id"], "شاخه")
    if "ground_id" in data and data["ground_id"] is not None:
        await _ensure_fk(session, EducationGround, data["ground_id"], "زمینه")
        branch_id = data.get("branch_id")
        ground = await session.get(EducationGround, data["ground_id"])
        if branch_id is not None and ground is not None and ground.branch_id != branch_id:
            raise HTTPException(status_code=422, detail="این زمینه به شاخهٔ انتخاب‌شده تعلق ندارد.")
    if "field_of_study_id" in data and data["field_of_study_id"] is not None:
        await _ensure_fk(session, FieldOfStudy, data["field_of_study_id"], "رشته")
        branch_id = data.get("branch_id")
        program = await session.get(FieldOfStudy, data["field_of_study_id"])
        if branch_id is None and program is not None and entity in {"links", "editions"}:
            # admin UX: the offering's branch is derived from the program
            data["branch_id"] = program.branch_id
            branch_id = program.branch_id
        if branch_id is not None and program is not None and program.branch_id != branch_id:
            raise HTTPException(status_code=422, detail="این رشته به شاخهٔ انتخاب‌شده تعلق ندارد.")
        ground_id = data.get("ground_id")
        if ground_id is not None and program is not None and program.ground_id != ground_id:
            raise HTTPException(status_code=422, detail="این رشته به زمینهٔ انتخاب‌شده تعلق ندارد.")
    if "grade_id" in data and data["grade_id"] is not None:
        await _ensure_fk(session, Grade, data["grade_id"], "پایه")
    if "subject_id" in data and data["subject_id"] is not None:
        await _ensure_fk(session, Subject, data["subject_id"], "درس")
    if "academic_year_id" in data and data["academic_year_id"] is not None:
        await _ensure_fk(session, AcademicYear, data["academic_year_id"], "سال تحصیلی")
    if "textbook_id" in data and data["textbook_id"] is not None:
        await _ensure_fk(session, CatalogTextbook, data["textbook_id"], "کتاب کاتالوگ")
    if "catalog_textbook_id" in data and data["catalog_textbook_id"] is not None:
        await _ensure_fk(session, CatalogTextbook, data["catalog_textbook_id"], "کتاب کاتالوگ")
    if entity == "grounds" and data.get("branch_id") is not None:
        branch = await session.get(EducationBranch, data["branch_id"])
        if branch is None or branch.code == "theoretical":
            raise HTTPException(
                status_code=422, detail="زمینه فقط برای شاخه‌های فنی‌وحرفه‌ای و کاردانش تعریف می‌شود."
            )
    if entity == "grades" and data.get("number") is not None:
        if not 1 <= int(data["number"]) <= 12:
            raise HTTPException(status_code=422, detail="شمارهٔ پایه باید بین ۱ تا ۱۲ باشد.")
    return data


async def _check_unique(session: AsyncSession, entity: str, data: dict[str, Any], *, obj_id: int | None = None) -> None:
    model = _model_for(entity)
    unique_cols: dict[str, tuple[str, ...]] = {
        "cycles": ("code",),
        "grades": ("number",),
        "branches": ("code",),
        "fields": ("code",),
        "subjects": ("code",),
        "academic-years": ("code",),
        "grounds": ("branch_id", "code"),
        "program-availability": ("field_of_study_id", "academic_year_id"),
    }
    cols = unique_cols.get(entity)
    if not cols:
        return
    values = {c: data.get(c) for c in cols}
    if any(v is None for v in values.values()):
        return
    stmt = select(model).where(*(getattr(model, c) == v for c, v in values.items()))
    existing = await session.scalar(stmt)
    if existing is not None and (obj_id is None or existing.id != obj_id):
        raise HTTPException(status_code=409, detail="رکورد تکراری است؛ ترکیب کلید قبلاً ثبت شده است.")


def _scope_code(data: dict[str, Any], year_code: str) -> str:
    parts = [f"year:{year_code}", f"grade:{data.get('grade_id') or 'unassigned'}"]
    if data.get("branch_id"):
        parts.append(f"branch:{data['branch_id']}")
    if data.get("field_of_study_id"):
        parts.append(f"field:{data['field_of_study_id']}")
    return "|".join(parts)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

_TEXT_COLUMNS: dict[str, tuple[str, ...]] = {
    "cycles": ("id", "code", "title", "sort_order", "is_active"),
    "grades": ("id", "number", "title", "cycle_id", "is_active", "has_major"),
    "branches": ("id", "code", "title", "min_grade", "max_grade", "sort_order", "is_active"),
    "grounds": ("id", "branch_id", "code", "title", "sort_order", "is_active"),
    "fields": ("id", "branch_id", "ground_id", "code", "title", "sort_order", "is_active"),
    "subjects": ("id", "code", "title", "course_kind", "weekly_hours", "is_mandatory", "is_active"),
    "textbooks": (
        "id", "slug", "title_fa", "title_en", "national_code", "grade_id", "subject_id",
        "academic_year_id", "textbook_kind", "audience_variant", "audience_scope",
        "implementation_status", "geographic_scope", "alternative_group", "validity_status",
        "verification_note", "source_url", "archived_at", "verified_at",
    ),
    "links": ("id", "textbook_id", "academic_year_id", "grade_id", "branch_id",
              "field_of_study_id", "scope_code", "is_mandatory", "note"),
    "academic-years": ("id", "code", "title", "start_date", "end_date", "is_active"),
    "editions": ("id", "title", "grade_id", "catalog_textbook_id", "academic_year_id",
                 "edition_label", "print_year", "publisher", "official_source_url",
                 "pdf_file_path", "total_pdf_pages", "status", "created_at", "catalog_status"),
    "program-availability": ("id", "field_of_study_id", "academic_year_id", "validity_status",
                             "valid_from_year", "valid_to_year", "evidence_note", "verified_at"),
}


async def serialize_row(session: AsyncSession, entity: str, obj: Any) -> dict[str, Any]:
    cols = _TEXT_COLUMNS[entity]
    row: dict[str, Any] = {}
    for col in cols:
        value = getattr(obj, col, None)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif hasattr(value, "value"):  # enum
            value = value.value
        row[col] = value
    # resolved display names for the admin UI
    names: dict[str, str | None] = {}
    if getattr(obj, "grade_id", None):
        grade = await session.get(Grade, obj.grade_id)
        names["grade_title"] = grade.title if grade else None
    if getattr(obj, "branch_id", None):
        branch = await session.get(EducationBranch, obj.branch_id)
        names["branch_title"] = branch.title if branch else None
    if getattr(obj, "ground_id", None):
        ground = await session.get(EducationGround, obj.ground_id)
        names["ground_title"] = ground.title if ground else None
        names["ground_code"] = ground.code if ground else None
    if getattr(obj, "field_of_study_id", None):
        program = await session.get(FieldOfStudy, obj.field_of_study_id)
        names["field_title"] = program.title if program else None
    if getattr(obj, "subject_id", None):
        subject = await session.get(Subject, obj.subject_id)
        names["subject_title"] = subject.title if subject else None
    if getattr(obj, "academic_year_id", None):
        year = await session.get(AcademicYear, obj.academic_year_id)
        names["academic_year_code"] = year.code if year else None
    if getattr(obj, "cycle_id", None):
        cycle = await session.get(EducationCycle, obj.cycle_id)
        names["cycle_title"] = cycle.title if cycle else None
    if entity == "textbooks":
        row["edition_count"] = int(
            await session.scalar(
                select(func.count(Book.id)).where(Book.catalog_textbook_id == obj.id)
            )
            or 0
        )
        row["link_count"] = int(
            await session.scalar(
                select(func.count(CatalogCourseTextbook.id)).where(
                    CatalogCourseTextbook.textbook_id == obj.id
                )
            )
            or 0
        )
    if entity == "links":
        textbook = await session.get(CatalogTextbook, obj.textbook_id)
        names["textbook_title"] = textbook.title_fa if textbook else None
    if entity == "editions":
        names["is_student_visible"] = obj.status.value == "ready"
        names["has_pdf"] = bool(obj.pdf_file_path)
    row.update(names)
    return row


def _snapshot(entity: str, obj: Any) -> dict[str, Any]:
    return {col: str(getattr(obj, col, None)) for col in _TEXT_COLUMNS[entity]}


# ---------------------------------------------------------------------------
# Dependency counting (safe-delete policy)
# ---------------------------------------------------------------------------

DEPENDENCY_QUERIES: dict[str, list[tuple[str, Any]]] = {}


async def entity_dependencies(session: AsyncSession, entity: str, obj_id: int) -> dict[str, int]:
    """Count dependent records; drives the pre-delete warning message."""
    deps: dict[str, int] = {}

    async def count(label: str, stmt) -> None:
        deps[label] = int(await session.scalar(stmt) or 0)

    if entity == "cycles":
        await count("grades", select(func.count(Grade.id)).where(Grade.cycle_id == obj_id))
    elif entity == "grades":
        await count("books", select(func.count(Book.id)).where(Book.grade_id == obj_id))
        await count("catalog_textbooks", select(func.count(CatalogTextbook.id)).where(CatalogTextbook.grade_id == obj_id))
        await count("links", select(func.count(CatalogCourseTextbook.id)).where(CatalogCourseTextbook.grade_id == obj_id))
        await count("student_profiles", select(func.count(StudentAcademicProfileSafe.id)).where(StudentAcademicProfileSafe.grade_id == obj_id))
    elif entity == "branches":
        await count("grounds", select(func.count(EducationGround.id)).where(EducationGround.branch_id == obj_id))
        await count("fields", select(func.count(FieldOfStudy.id)).where(FieldOfStudy.branch_id == obj_id))
    elif entity == "grounds":
        await count("fields", select(func.count(FieldOfStudy.id)).where(FieldOfStudy.ground_id == obj_id))
    elif entity == "fields":
        await count("links", select(func.count(CatalogCourseTextbook.id)).where(CatalogCourseTextbook.field_of_study_id == obj_id))
        await count("program_availability", select(func.count(ProgramAvailability.id)).where(ProgramAvailability.field_of_study_id == obj_id))
        await count("student_profiles", select(func.count(StudentAcademicProfileSafe.id)).where(StudentAcademicProfileSafe.field_of_study_id == obj_id))
    elif entity == "subjects":
        await count("catalog_textbooks", select(func.count(CatalogTextbook.id)).where(CatalogTextbook.subject_id == obj_id))
    elif entity == "textbooks":
        await count("links", select(func.count(CatalogCourseTextbook.id)).where(CatalogCourseTextbook.textbook_id == obj_id))
        await count("editions", select(func.count(Book.id)).where(Book.catalog_textbook_id == obj_id))
    elif entity == "academic-years":
        await count("links", select(func.count(CatalogCourseTextbook.id)).where(CatalogCourseTextbook.academic_year_id == obj_id))
        await count("program_availability", select(func.count(ProgramAvailability.id)).where(ProgramAvailability.academic_year_id == obj_id))
        await count("textbooks", select(func.count(CatalogTextbook.id)).where(CatalogTextbook.academic_year_id == obj_id))
    elif entity == "editions":
        await count("book_curriculum_links", select(func.count(BookCurriculumLink.id)).where(BookCurriculumLink.book_id == obj_id))
        await count("book_pages", select(func.count(BookPageSafe.id)).where(BookPageSafe.book_id == obj_id))
    return deps


# Imported late to avoid circulars at module import time in tests
from app.models.catalog import StudentAcademicProfile as StudentAcademicProfileSafe  # noqa: E402
from app.models.curriculum import BookPage as BookPageSafe  # noqa: E402

async def delete_entity(session: AsyncSession, entity: str, obj_id: int) -> dict[str, Any]:
    model = _model_for(entity)
    obj = await session.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="رکورد یافت نشد.")
    deps = await entity_dependencies(session, entity, obj_id)
    total = sum(deps.values())
    if total > 0:
        detail = "، ".join(f"{label}: {count}" for label, count in deps.items() if count)
        raise HTTPException(
            status_code=409,
            detail=(
                f"این {ENTITY_LABELS.get(entity, entity)} به {total} رکورد وابسته متصل است ({detail}). "
                "حذف دائمی مجاز نیست — از آرشیو/غیرفعال‌سازی استفاده کنید."
            ),
        )
    snapshot = _snapshot(entity, obj)
    await session.delete(obj)
    await session.commit()
    return snapshot


# ---------------------------------------------------------------------------
# Archive / restore
# ---------------------------------------------------------------------------

ARCHIVE_FIELD: dict[str, str] = {
    "cycles": "is_active",
    "grades": "is_active",
    "branches": "is_active",
    "grounds": "is_active",
    "fields": "is_active",
    "subjects": "is_active",
    "textbooks": "archived_at",
}


async def set_archived(session: AsyncSession, entity: str, obj_id: int, archived: bool) -> dict[str, Any]:
    model = _model_for(entity)
    field = ARCHIVE_FIELD.get(entity)
    if field is None:
        raise HTTPException(status_code=422, detail="این موجودیت قابلیت آرشیو ندارد؛ از حذف استفاده کنید.")
    obj = await session.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="رکورد یافت نشد.")
    before = _snapshot(entity, obj)
    if field == "archived_at":
        setattr(obj, field, _now() if archived else None)
    else:
        setattr(obj, field, not archived)
    await session.commit()
    after = _snapshot(entity, obj)
    return {"before": before, "after": after, "id": obj_id}


# ---------------------------------------------------------------------------
# Academic-year structure copy (never mutates the source year)
# ---------------------------------------------------------------------------

async def copy_year_structure(
    session: AsyncSession,
    *,
    actor: permissions.AdminActor,
    target_year_id: int,
    source_year_id: int,
) -> dict[str, int]:
    if target_year_id == source_year_id:
        raise HTTPException(status_code=422, detail="سال مبدأ و مقصد نمی‌توانند یکی باشند.")
    source = await session.get(AcademicYear, source_year_id)
    target = await session.get(AcademicYear, target_year_id)
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="سال تحصیلی مبدأ یا مقصد یافت نشد.")
    stats = {"program_availability": 0, "links": 0}

    existing_avail = set(
        (
            await session.scalars(
                select(ProgramAvailability.field_of_study_id).where(
                    ProgramAvailability.academic_year_id == target_year_id
                )
            )
        ).all()
    )
    for row in (
        await session.scalars(
            select(ProgramAvailability).where(ProgramAvailability.academic_year_id == source_year_id)
        )
    ).all():
        if row.field_of_study_id in existing_avail:
            continue  # idempotent copy: never duplicate, never overwrite
        session.add(
            ProgramAvailability(
                field_of_study_id=row.field_of_study_id,
                academic_year_id=target_year_id,
                validity_status=row.validity_status,
                valid_from_year=row.valid_from_year,
                valid_to_year=row.valid_to_year,
                evidence_note=row.evidence_note,
                catalog_source_id=row.catalog_source_id,
            )
        )
        stats["program_availability"] += 1

    existing_links = set(
        (
            await session.scalars(
                select(CatalogCourseTextbook.scope_code).where(
                    CatalogCourseTextbook.academic_year_id == target_year_id
                )
            )
        ).all()
    )
    for link in (
        await session.scalars(
            select(CatalogCourseTextbook).where(CatalogCourseTextbook.academic_year_id == source_year_id)
        )
    ).all():
        scope = link.scope_code.replace(f"year:{source.code}", f"year:{target.code}", 1)
        if scope in existing_links:
            continue
        session.add(
            CatalogCourseTextbook(
                textbook_id=link.textbook_id,
                academic_year_id=target_year_id,
                grade_id=link.grade_id,
                branch_id=link.branch_id,
                field_of_study_id=link.field_of_study_id,
                scope_code=scope,
                is_mandatory=link.is_mandatory,
                note=link.note,
            )
        )
        stats["links"] += 1

    await session.commit()
    await log_action(
        session,
        actor=actor,
        action="copy-structure",
        entity="academic-years",
        entity_id=target_year_id,
        after={"source_year": source.code, "target_year": target.code, **stats},
    )
    return stats


# ---------------------------------------------------------------------------
# Edition PDF upload (never publishes: status stays non-ready)
# ---------------------------------------------------------------------------

async def upload_edition_pdf(
    session: AsyncSession,
    *,
    actor: permissions.AdminActor,
    edition_id: int,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    edition = await session.get(Book, edition_id)
    if edition is None:
        raise HTTPException(status_code=404, detail="نسخهٔ کتاب یافت نشد.")
    if not filename.lower().endswith(".pdf") or not content[:5].startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="فایل باید PDF معتبر باشد.")
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    target = ARCHIVE_DIR / f"edition-{edition_id}.pdf"
    target.write_bytes(content)
    before = _snapshot("editions", edition)
    edition.pdf_file_path = str(target)
    edition.source_checksum = digest
    # Auto-publish rule preserved: the admin upload NEVER sets ready; the ingest
    # pipeline keeps exclusive ownership of the published state.
    await session.commit()
    after = _snapshot("editions", edition)
    await log_action(
        session,
        actor=actor,
        action="pdf-upload",
        entity="editions",
        entity_id=edition_id,
        before=before,
        after={"pdf_file_path": str(target), "sha256": digest, "size": len(content)},
    )
    return {"path": str(target), "sha256": digest, "size": len(content), "status": edition.status.value}


# ---------------------------------------------------------------------------
# Field registry (allowed columns per entity)
# ---------------------------------------------------------------------------

CREATE_FIELDS: dict[str, tuple[str, ...]] = {
    "cycles": ("code", "title", "sort_order", "is_active"),
    "grades": ("number", "title", "cycle_id", "is_active", "has_major"),
    "branches": ("code", "title", "min_grade", "max_grade", "sort_order", "is_active"),
    "grounds": ("branch_id", "code", "title", "sort_order", "is_active"),
    "fields": ("branch_id", "ground_id", "code", "title", "sort_order", "is_active"),
    "subjects": ("code", "title", "course_kind", "weekly_hours", "is_mandatory", "is_active", "description"),
    "textbooks": (
        "slug", "title_fa", "title_en", "national_code", "grade_id", "subject_id",
        "academic_year_id", "textbook_kind", "audience_variant", "audience_scope",
        "implementation_status", "geographic_scope", "alternative_group", "validity_status",
        "verification_note", "source_url",
    ),
    "links": ("textbook_id", "academic_year_id", "grade_id", "branch_id", "field_of_study_id",
              "is_mandatory", "note"),
    "academic-years": ("code", "title", "start_date", "end_date", "is_active"),
    "editions": ("title", "grade_id", "catalog_textbook_id", "academic_year_id",
                 "edition_label", "print_year", "publisher", "official_source_url",
                 "pdf_file_path", "total_pdf_pages"),
    "program-availability": ("field_of_study_id", "academic_year_id", "validity_status",
                             "valid_from_year", "valid_to_year", "evidence_note", "verified_at"),
}

REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "cycles": ("code", "title"),
    "grades": ("number", "title"),
    "branches": ("code", "title"),
    "grounds": ("branch_id", "code", "title"),
    "fields": ("branch_id", "code", "title"),
    "subjects": ("code", "title"),
    "textbooks": ("title_fa",),
    "links": ("textbook_id", "academic_year_id"),
    "academic-years": ("code", "title"),
    "editions": ("title", "grade_id"),
    "program-availability": ("field_of_study_id", "academic_year_id", "validity_status"),
}

UPDATE_FIELDS: dict[str, tuple[str, ...]] = CREATE_FIELDS


def _require_fields(entity: str, payload: dict[str, Any], *, partial: bool) -> None:
    required = REQUIRED_FIELDS[entity]
    if partial:
        return
    missing = [f for f in required if payload.get(f) in (None, "")]
    if missing:
        raise HTTPException(status_code=422, detail=f"فیلدهای الزامی ناقص است: {', '.join(missing)}")


async def create_entity(session: AsyncSession, *, actor: permissions.AdminActor, entity: str, payload: dict[str, Any]) -> dict[str, Any]:
    model = _model_for(entity)
    _require_fields(entity, payload, partial=False)
    data = {f: _clean(entity, f, payload[f]) for f in CREATE_FIELDS[entity] if f in payload}
    data = await _validate_row(session, entity, data)

    if entity == "textbooks" and not data.get("slug"):
        base = _slugify(data.get("title_fa", "book"))
        grade_id = data.get("grade_id")
        prefix = "periodic" if grade_id is None else f"g{int((await session.get(Grade, grade_id)).number):02d}" if grade_id else "book"
        data["slug"] = f"{prefix}-{base}"
        # slug uniqueness with a numbered fallback
        counter = 2
        while await session.scalar(select(CatalogTextbook.id).where(CatalogTextbook.slug == data["slug"])):
            data["slug"] = f"{data['slug']}-{counter}"
            counter += 1
        data.setdefault("validity_status", "needs_verification")
        data.setdefault("audience_variant", "general")
        data.setdefault("textbook_kind", "student_book")
        data.setdefault("implementation_status", "confirmed")
    if entity == "links":
        year = await session.get(AcademicYear, data["academic_year_id"])
        data["scope_code"] = _scope_code(data, year.code)
    if entity == "editions":
        data.setdefault("pdf_file_path", "")
        data.setdefault("total_pdf_pages", 0)
        data["status"] = BookStatus.created  # never created as ready

    await _check_unique(session, entity, data)
    obj = model(**data)
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    await log_action(session, actor=actor, action="create", entity=entity, entity_id=obj.id, after=_snapshot(entity, obj))
    return await serialize_row(session, entity, obj)


async def update_entity(session: AsyncSession, *, actor: permissions.AdminActor, entity: str, obj_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    model = _model_for(entity)
    obj = await session.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="رکورد یافت نشد.")
    if entity == "editions" and "status" in payload and payload["status"] == "ready":
        raise HTTPException(status_code=422, detail="وضعیت ready فقط توسط خط پردازش کتاب تنظیم می‌شود.")
    before = _snapshot(entity, obj)
    data = {f: _clean(entity, f, payload[f]) for f in UPDATE_FIELDS[entity] if f in payload}
    data = await _validate_row(session, entity, data, obj_id=obj_id)
    if entity == "links" and (("grade_id" in data) or ("branch_id" in data) or ("field_of_study_id" in data)):
        year = await session.get(AcademicYear, data.get("academic_year_id") or obj.academic_year_id)
        merged = {**{k: getattr(obj, k) for k in ("grade_id", "branch_id", "field_of_study_id")}, **{k: v for k, v in data.items() if k in ("grade_id", "branch_id", "field_of_study_id")}}
        data["scope_code"] = _scope_code(merged, year.code)
    await _check_unique(session, entity, {**{c: getattr(obj, c) for c in (_TEXT_COLUMNS[entity])}, **data}, obj_id=obj_id)
    for field, value in data.items():
        setattr(obj, field, value)
    await session.commit()
    await session.refresh(obj)
    await log_action(session, actor=actor, action="update", entity=entity, entity_id=obj_id, before=before, after=_snapshot(entity, obj))
    return await serialize_row(session, entity, obj)


# ---------------------------------------------------------------------------
# List with search / filters / sort / pagination
# ---------------------------------------------------------------------------

SEARCH_FIELDS: dict[str, tuple[str, ...]] = {
    "cycles": ("code", "title"),
    "grades": ("title",),
    "branches": ("code", "title"),
    "grounds": ("code", "title"),
    "fields": ("code", "title"),
    "subjects": ("code", "title"),
    "textbooks": ("title_fa", "title_en", "slug"),
    "links": ("scope_code", "note"),
    "academic-years": ("code", "title"),
    "editions": ("title",),
    "program-availability": ("evidence_note",),
}

FILTER_FIELDS: dict[str, tuple[str, ...]] = {
    "cycles": ("is_active",),
    "grades": ("cycle_id", "is_active"),
    "branches": ("is_active",),
    "grounds": ("branch_id", "is_active"),
    "fields": ("branch_id", "ground_id", "is_active"),
    "subjects": ("is_active", "course_kind"),
    "textbooks": ("grade_id", "subject_id", "academic_year_id", "audience_variant",
                  "implementation_status", "validity_status", "textbook_kind"),
    "links": ("textbook_id", "academic_year_id", "grade_id", "branch_id", "field_of_study_id", "is_mandatory"),
    "academic-years": ("is_active",),
    "editions": ("grade_id", "academic_year_id", "catalog_textbook_id", "status"),
    "program-availability": ("academic_year_id", "field_of_study_id", "validity_status"),
}

SORTABLE: dict[str, tuple[str, ...]] = {
    "cycles": ("id", "code", "title", "sort_order"),
    "grades": ("id", "number", "title"),
    "branches": ("id", "sort_order", "title"),
    "grounds": ("id", "sort_order", "title"),
    "fields": ("id", "sort_order", "title", "code"),
    "subjects": ("id", "code", "title"),
    "textbooks": ("id", "title_fa", "grade_id"),
    "links": ("id", "textbook_id"),
    "academic-years": ("id", "code"),
    "editions": ("id", "title", "grade_id"),
    "program-availability": ("id", "field_of_study_id"),
}


async def list_entity(
    session: AsyncSession,
    entity: str,
    *,
    q: str | None = None,
    filters: dict[str, Any] | None = None,
    sort: str = "id",
    direction: str = "asc",
    page: int = 1,
    page_size: int = 25,
    include_archived: bool = False,
) -> dict[str, Any]:
    model = _model_for(entity)
    stmt = select(model)
    if q:
        fields = SEARCH_FIELDS[entity]
        stmt = stmt.where(or_(*(getattr(model, f).ilike(f"%{q}%") for f in fields)))
    filters = filters or {}
    for key, value in filters.items():
        if key not in FILTER_FIELDS[entity] or value in (None, "", "all"):
            continue
        column = getattr(model, key)
        if isinstance(value, str) and value in {"true", "false"}:
            stmt = stmt.where(column.is_(value == "true"))
        else:
            try:
                stmt = stmt.where(column == int(value))
            except (TypeError, ValueError):
                stmt = stmt.where(column == value)
    # archived semantics: is_active=False or archived_at set
    archive_field = ARCHIVE_FIELD.get(entity)
    if archive_field and not include_archived:
        if archive_field == "archived_at":
            stmt = stmt.where(getattr(model, archive_field).is_(None))
        else:
            stmt = stmt.where(getattr(model, archive_field).is_(True))
    sort_col = getattr(model, sort if sort in SORTABLE[entity] else "id")
    stmt = stmt.order_by(sort_col.desc() if direction == "desc" else sort_col.asc())
    total = int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    items = (await session.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all()
    rows = [await serialize_row(session, entity, item) for item in items]
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


async def get_entity(session: AsyncSession, entity: str, obj_id: int) -> dict[str, Any]:
    model = _model_for(entity)
    obj = await session.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="رکورد یافت نشد.")
    return await serialize_row(session, entity, obj)


async def list_archived(session: AsyncSession, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """Cross-entity archive view (inactive rows or archived_at set)."""
    out: list[dict[str, Any]] = []
    for entity, field in ARCHIVE_FIELD.items():
        model = _model_for(entity)
        if field == "archived_at":
            stmt = select(model).where(model.archived_at.is_not(None))
        else:
            stmt = select(model).where(getattr(model, field).is_(False))
        for obj in (await session.scalars(stmt.limit(page_size))).all():
            row = await serialize_row(session, entity, obj)
            row["entity"] = entity
            out.append(row)
    return {"items": out, "total": len(out)}


async def catalog_overview(session: AsyncSession) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity, model in {
        "cycles": EducationCycle,
        "grades": Grade,
        "branches": EducationBranch,
        "grounds": EducationGround,
        "fields": FieldOfStudy,
        "subjects": Subject,
        "textbooks": CatalogTextbook,
        "links": CatalogCourseTextbook,
        "academic-years": AcademicYear,
        "editions": Book,
        "program-availability": ProgramAvailability,
    }.items():
        counts[entity] = int(await session.scalar(select(func.count()).select_from(model)) or 0)
    return counts
