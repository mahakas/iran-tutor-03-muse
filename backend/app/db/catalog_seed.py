"""Idempotent, versioned importer for the Iran Education Catalog 1405–1406.

Run:  backend/.venv/bin/python -m app.db.catalog_seed

Design rules (owner spec):
- every catalog row carries provenance (catalog source) and validity flags;
- re-running never duplicates records (slug/scope-key lookups);
- common books are one record expanded into multiple offering links;
- nothing is silently promoted to confirmed/active status;
- user data is never touched, and no create_all is used anywhere.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.catalog_data import (
    GROUND_SPECS,
    KARDANESH_PROGRAMS,
    LOWER_SECONDARY_BOOKS,
    PRIMARY_BOOKS,
    TVO_PROGRAMS,
)
from app.db.catalog_data_upper import THEORETICAL_BOOKS, TVO_COMMON_BOOKS
from app.models.catalog import (
    CatalogCourseTextbook,
    CatalogImportRun,
    CatalogSource,
    CatalogTextbook,
    EducationGround,
    ProgramAvailability,
)
from app.models.curriculum import AcademicYear, EducationBranch, EducationCycle, FieldOfStudy, Grade, Subject

CATALOG_KEY = "darsyar_iran_education_catalog_1405-1406"
ACADEMIC_YEAR_CODE = "1405-1406"
ACADEMIC_YEAR_TITLE = "سال تحصیلی ۱۴۰۵–۱۴۰۶"

SOURCE_NOTE = (
    "کاتالوگ ارائه‌شدهٔ مالک پروژه (darsyar_complete_grade_first_list_1405-1406). "
    "فهرست کاری — موارد آزمایشی/منطقه‌ای/بدون کد به‌صورت جداگانه علامت خورده‌اند و "
    "پیش از استفادهٔ رسمی باید با جداول سازمان پژوهش راستی‌آزمایی شوند."
)

SUBJECT_TITLE_OVERRIDES: dict[str, str] = {
    "tarikh": "تاریخ",
    "adyan-akhlagh": "تعلیمات ادیان الهی و اخلاق",
}

_PAREN_RE = re.compile(r"[（(][^（）()]*[）)]")
_PUNCT_RE = re.compile(r"[،,\-ـ_\s]+")


def _slugify(title: str) -> str:
    slug = _PUNCT_RE.sub("-", title.strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "book"


def _clean_subject_title(title: str) -> str:
    cleaned = _PAREN_RE.sub(" ", title)
    cleaned = re.sub(r"(?<![\w])([۰-۹0-9]+)(?![\w])", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ـ-،,")
    return cleaned or title


def _variant_of(title: str, flags: dict[str, object]) -> str | None:
    variant = flags.get("variant")
    if variant:
        return str(variant)
    if "(پسران)" in title:
        return "boys"
    if "(دختران)" in title:
        return "girls"
    if "اقلیت‌های دینی" in title or "اقلیت های دینی" in title:
        return "religious_minority"
    return None


def _variant_suffix(variant: str | None) -> str:
    return {
        "boys": "-پسران",
        "girls": "-دختران",
        "religious_minority": "-اقلیت",
    }.get(variant or "", "")


def _scope_code(year_code: str, grade: int | None, branch: str | None, field: str | None) -> str:
    parts = [f"year:{year_code}", f"grade:{grade if grade is not None else 'unassigned'}"]
    if branch:
        parts.append(f"branch:{branch}")
    if field:
        parts.append(f"field:{field}")
    return "|".join(parts)


class CatalogSeedStats:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.review_items: list[dict[str, str]] = []

    def bump(self, key: str, amount: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + amount


async def _ensure_catalog_context(session: AsyncSession) -> tuple[AcademicYear, CatalogSource, CatalogImportRun]:
    year = await session.scalar(select(AcademicYear).where(AcademicYear.code == ACADEMIC_YEAR_CODE))
    if year is None:
        year = AcademicYear(
            code=ACADEMIC_YEAR_CODE,
            title=ACADEMIC_YEAR_TITLE,
            is_active=True,
        )
        session.add(year)
        await session.flush()

    source = await session.scalar(select(CatalogSource).where(CatalogSource.key == CATALOG_KEY))
    if source is None:
        source = CatalogSource(
            key=CATALOG_KEY,
            title="کاتالوگ آموزشی ایران ۱۴۰۵–۱۴۰۶ درسیار",
            authority="مالک پروژه (فهرست کاری)",
            notes=SOURCE_NOTE,
            retrieved_at=datetime.now(timezone.utc),
        )
        session.add(source)
        await session.flush()

    run = CatalogImportRun(catalog_key=CATALOG_KEY, academic_year_id=year.id, status="running")
    session.add(run)
    await session.flush()
    return year, source, run


async def _ensure_subject(session: AsyncSession, slug: str, title: str, stats: CatalogSeedStats) -> Subject:
    subject = await session.scalar(select(Subject).where(Subject.code == slug))
    if subject is None:
        subject = Subject(code=slug, title=title, is_active=True)
        session.add(subject)
        await session.flush()
        stats.bump("subjects_created")
    return subject


async def _ensure_grounds(session: AsyncSession, stats: CatalogSeedStats) -> dict[tuple[int, str], EducationGround]:
    branches = {
        b.code: b for b in (await session.scalars(select(EducationBranch))).all()
    }
    grounds: dict[tuple[int, str], EducationGround] = {}
    existing = {
        (g.branch_id, g.code): g for g in (await session.scalars(select(EducationGround))).all()
    }
    for branch_code, ground_code, ground_title in GROUND_SPECS:
        branch = branches.get(branch_code)
        if branch is None:
            raise RuntimeError(f"branch {branch_code} missing — run base seed first")
        key = (branch.id, ground_code)
        ground = existing.get(key)
        if ground is None:
            ground = EducationGround(branch_id=branch.id, code=ground_code, title=ground_title)
            session.add(ground)
            await session.flush()
            stats.bump("grounds_created")
        grounds[key] = ground
    return grounds


def _program_specs() -> list[tuple[str, str, str, str]]:
    """(branch_code, ground_code, program_code, program_title) — verbatim titles."""
    specs: list[tuple[str, str, str, str]] = []
    for branch_code, programs in (("technical_vocational", TVO_PROGRAMS), ("kar_danesh", KARDANESH_PROGRAMS)):
        for ground_code, titles in programs.items():
            for title in titles:
                specs.append(
                    (
                        branch_code,
                        ground_code,
                        f"{branch_code[:3]}-{ground_code}-{_slugify(title)}",
                        title,
                    )
                )
    return specs


async def _ensure_programs(
    session: AsyncSession,
    year: AcademicYear,
    source: CatalogSource,
    grounds: dict[tuple[int, str], EducationGround],
    stats: CatalogSeedStats,
) -> dict[str, FieldOfStudy]:
    branches = {b.code: b for b in (await session.scalars(select(EducationBranch))).all()}
    ground_ids: dict[str, int] = {}
    for (branch_id, ground_code), ground in grounds.items():
        for branch_code, branch in branches.items():
            if branch.id == branch_id:
                ground_ids[f"{branch_code}:{ground_code}"] = ground.id

    fields = {f.code: f for f in (await session.scalars(select(FieldOfStudy))).all()}
    availability_keys = {
        (row.field_of_study_id, row.academic_year_id)
        for row in (await session.scalars(select(ProgramAvailability))).all()
    }
    order = 100  # after the four theoretical fields
    for branch_code, ground_code, code, title in _program_specs():
        field = fields.get(code)
        if field is None:
            field = FieldOfStudy(
                branch_id=branches[branch_code].id,
                code=code,
                title=title,
                ground_id=ground_ids[f"{branch_code}:{ground_code}"],
                sort_order=order,
                is_active=True,
            )
            session.add(field)
            await session.flush()
            fields[code] = field
            stats.bump("programs_created")
        order += 1
        if (field.id, year.id) not in availability_keys:
            session.add(
                ProgramAvailability(
                    field_of_study_id=field.id,
                    academic_year_id=year.id,
                    validity_status="needs_verification",
                    evidence_note="فهرست کاری مالک؛ گواهی فعال‌بودن پذیرش در همهٔ هنرستان‌ها نیست — تطبیق با جدول رسمی سال ۱۴۰۵–۱۴۰۶ لازم است.",
                    catalog_source_id=source.id,
                )
            )
            stats.bump("program_availability_created")
    return fields


async def _ensure_textbook(
    session: AsyncSession,
    year: AcademicYear,
    source: CatalogSource,
    grade_rows: dict[int, Grade],
    subject_by_slug: dict[str, Subject],
    *,
    slug: str,
    title: str,
    grade_number: int | None,
    flags: dict[str, object],
    stats: CatalogSeedStats,
) -> CatalogTextbook:
    textbook = await session.scalar(select(CatalogTextbook).where(CatalogTextbook.slug == slug))
    variant = _variant_of(title, flags)
    impl = str(flags.get("impl", "confirmed"))
    validity = str(flags.get("validity", "needs_verification"))
    if "subject" in flags:
        subject_slug = flags["subject"]
    else:
        subject_slug = _clean_subject_title(title)
    subject = subject_by_slug.get(str(subject_slug)) if subject_slug else None
    if textbook is None:
        textbook = CatalogTextbook(
            slug=slug,
            title_fa=title,
            national_code=None,  # never fabricated; official codes stay unknown
            grade_id=grade_rows[grade_number].id if grade_number is not None else None,
            subject_id=subject.id if subject is not None else None,
            academic_year_id=year.id,
            textbook_kind=str(flags.get("kind", "student_book")),
            audience_variant=variant or "general",
            audience_scope="school_specific" if impl == "experimental" else "national",
            implementation_status=impl,
            geographic_scope=str(flags["geo"]) if flags.get("geo") else ("provincial" if impl == "regional_pilot" else "national"),
            alternative_group=str(flags["alt"]) if flags.get("alt") else None,
            validity_status=validity,
            verification_note=str(flags["note"]) if flags.get("note") else None,
            catalog_source_id=source.id,
        )
        session.add(textbook)
        await session.flush()
        stats.bump("textbooks_created")
        if impl in {"experimental", "regional_pilot", "needs_verification"} or validity != "active":
            stats.review_items.append(
                {"slug": slug, "title": title, "implementation_status": impl, "validity_status": validity}
            )
        if variant == "religious_minority":
            stats.bump("audience_minority")
        elif variant in {"girls", "boys"}:
            stats.bump("audience_gender")
        if impl == "experimental":
            stats.bump("experimental_books")
        if impl == "regional_pilot":
            stats.bump("regional_books")
        if textbook.national_code is None and not flags.get("no_code_expected", False):
            stats.bump("national_code_unknown")
    return textbook


async def _ensure_link(
    session: AsyncSession,
    year: AcademicYear,
    branch_by_code: dict[str, EducationBranch],
    field_by_code: dict[str, FieldOfStudy],
    grade_rows: dict[int, Grade],
    textbook: CatalogTextbook,
    *,
    grade_number: int | None,
    branch_code: str | None,
    field_code: str | None,
    is_mandatory: bool,
    note: str | None,
    stats: CatalogSeedStats,
) -> None:
    scope = _scope_code(
        ACADEMIC_YEAR_CODE,
        grade_number,
        branch_by_code[branch_code].code if branch_code else None,
        field_by_code[field_code].code if field_code else None,
    )
    existing = await session.scalar(
        select(CatalogCourseTextbook).where(
            CatalogCourseTextbook.textbook_id == textbook.id,
            CatalogCourseTextbook.scope_code == scope,
        )
    )
    if existing is not None:
        return
    session.add(
        CatalogCourseTextbook(
            textbook_id=textbook.id,
            academic_year_id=year.id,
            grade_id=grade_rows[grade_number].id if grade_number is not None else None,
            branch_id=branch_by_code[branch_code].id if branch_code else None,
            field_of_study_id=field_by_code[field_code].id if field_code else None,
            scope_code=scope,
            is_mandatory=is_mandatory,
            note=note,
        )
    )
    stats.bump("links_created")


async def _catalog_row_counts(session: AsyncSession) -> dict[str, int]:
    """Row counts of the catalog tables — used to detect a pure no-op re-run."""
    tables = [
        EducationCycle,
        EducationBranch,
        EducationGround,
        CatalogTextbook,
        ProgramAvailability,
    ]
    return {
        t.__name__: int(await session.scalar(sa_func.count(t.id)))
        for t in tables
    }


async def seed_education_catalog_1405_1406(session: AsyncSession) -> CatalogSeedStats:
    stats = CatalogSeedStats()
    before = await _catalog_row_counts(session)
    year, source, run = await _ensure_catalog_context(session)
    stats.bump("academic_years", 1)

    grounds = await _ensure_grounds(session, stats)
    field_by_code = await _ensure_programs(session, year, source, grounds, stats)
    branch_by_code = {b.code: b for b in (await session.scalars(select(EducationBranch))).all()}
    grade_rows = {g.number: g for g in (await session.scalars(select(Grade))).all()}

    # ── collect every book entry once (subject resolution before inserts) ──
    subject_pairs: dict[str, str] = {}
    book_entries: list[tuple[str, int | None, str | None, str | None, dict[str, object], str]] = []
    # (slug, grade, branch_code, field_code, flags, title)

    def _entry_slug(grade_number: int | None, title: str, flags: dict[str, object], scope: str) -> str:
        # Gradeless records (e.g. the periodic «از ایرانمان دفاع می‌کنیم» booklet)
        # must be ONE record regardless of how many grade lists mention them.
        if flags.get("grade", grade_number) is None:
            return f"periodic-{_slugify(title)}"
        variant = _variant_of(title, flags)
        if scope == "periodic":
            return f"periodic-{_slugify(title)}"
        prefix = "" if scope == "plain" else f"{scope}-"
        return f"g{grade_number:02d}-{prefix}{_slugify(title)}{_variant_suffix(variant)}"

    for grade_number, entries in PRIMARY_BOOKS.items():
        for title, flags in entries:
            if "subject" in flags:
                subject_slug = flags["subject"]
            else:
                subject_slug = _clean_subject_title(title)
            if subject_slug:
                subject_pairs.setdefault(str(subject_slug), _clean_subject_title(title))
            slug = _entry_slug(grade_number, title, flags, "plain")
            book_entries.append((slug, grade_number, None, None, flags, title))

    for grade_number, entries in LOWER_SECONDARY_BOOKS.items():
        for title, flags in entries:
            if "subject" in flags:
                subject_slug = flags["subject"]
            else:
                subject_slug = _clean_subject_title(title)
            if subject_slug:
                subject_pairs.setdefault(str(subject_slug), _clean_subject_title(title))
            slug = _entry_slug(grade_number, title, flags, "plain")
            book_entries.append((slug, grade_number, None, None, flags, title))

    for grade_number, per_field in THEORETICAL_BOOKS.items():
        for field_code, entries in per_field.items():
            for title, flags in entries:
                if "subject" in flags:
                    subject_slug = flags["subject"]
                else:
                    subject_slug = _clean_subject_title(title)
                if subject_slug:
                    subject_pairs.setdefault(str(subject_slug), _clean_subject_title(title))
                slug = _entry_slug(grade_number, title, flags, "theo")
                book_entries.append((slug, grade_number, "theoretical", field_code, flags, title))

    for grade_number, entries in TVO_COMMON_BOOKS.items():
        for title, flags in entries:
            if "subject" in flags:
                subject_slug = flags["subject"]
            else:
                subject_slug = _clean_subject_title(title)
            if subject_slug:
                subject_pairs.setdefault(str(subject_slug), _clean_subject_title(title))
            slug = _entry_slug(grade_number, title, flags, "tvo")
            book_entries.append((slug, grade_number, "technical_vocational", None, flags, title))

    # subjects first so textbook rows can reference them
    subject_by_slug: dict[str, Subject] = {}
    for subject_slug, subject_title in subject_pairs.items():
        override = SUBJECT_TITLE_OVERRIDES.get(subject_slug)
        subject_by_slug[subject_slug] = await _ensure_subject(
            session, subject_slug, override or subject_title, stats
        )

    for slug, grade_number, branch_code, field_code, flags, title in book_entries:
        textbook = await _ensure_textbook(
            session,
            year,
            source,
            grade_rows,
            subject_by_slug,
            slug=slug,
            title=title,
            grade_number=None if flags.get("grade", grade_number) is None else int(flags.get("grade", grade_number)),  # type: ignore[arg-type]
            flags=flags,
            stats=stats,
        )
        link_grade = None if flags.get("grade", grade_number) is None else grade_number
        await _ensure_link(
            session,
            year,
            branch_by_code,
            field_by_code,
            grade_rows,
            textbook,
            grade_number=link_grade,
            branch_code=branch_code,
            field_code=field_code,
            is_mandatory=bool(flags.get("mandatory", True)),
            note=str(flags["note"]) if flags.get("note") else None,
            stats=stats,
        )

    # Idempotency: a re-run that created nothing must not leave a new
    # import-run row behind (no duplicate audit rows on repeated seeds).
    after = await _catalog_row_counts(session)
    if after == before:
        await session.delete(run)
        stats.bump("noop_run_discarded")
    else:
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        run.stats = dict(stats.counts)
        run.notes = (
            f"review_items={len(stats.review_items)}; "
            f"textbooks_total={await session.scalar(sa_func.count(CatalogTextbook.id))}"
        )
    await session.commit()
    return stats


async def main() -> None:
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        stats = await seed_education_catalog_1405_1406(session)
        print("CATALOG SEED OK")
        for key, value in sorted(stats.counts.items()):
            print(f"  {key}: {value}")
        print(f"  review_items: {len(stats.review_items)}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
