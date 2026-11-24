"""Authoritative post-seed counts for the implementation report (from the DB)."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.catalog_seed import seed_education_catalog_1405_1406
from app.db.seed import seed_curriculum_taxonomy, seed_grades, seed_majors
from app.models.catalog import (
    CatalogCourseTextbook,
    CatalogTextbook,
    EducationGround,
    ProgramAvailability,
)
from app.models.curriculum import EducationBranch, FieldOfStudy, Grade, Subject


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:////tmp/catalog_report_counts.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine)
    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await session.commit()
        await seed_education_catalog_1405_1406(session)

        grades = await session.scalar(select(func.count(Grade.id)))
        cycles = await session.scalar(select(func.count(func.distinct(Grade.cycle_id))))
        branches = await session.scalar(select(func.count(EducationBranch.id)))
        grounds = await session.scalar(select(func.count(EducationGround.id)))
        theo = await session.scalar(
            select(func.count(FieldOfStudy.id)).where(FieldOfStudy.ground_id.is_(None))
        )
        tvo = await session.scalar(
            select(func.count(FieldOfStudy.id)).where(FieldOfStudy.code.like("tec-%"))
        )
        kd = await session.scalar(
            select(func.count(FieldOfStudy.id)).where(FieldOfStudy.code.like("kar-%"))
        )
        subjects = await session.scalar(select(func.count(Subject.id)))
        textbooks = await session.scalar(select(func.count(CatalogTextbook.id)))
        links = await session.scalar(select(func.count(CatalogCourseTextbook.id)))
        avail = await session.scalar(select(func.count(ProgramAvailability.id)))
        unverified_programs = await session.scalar(
            select(func.count(ProgramAvailability.id)).where(
                ProgramAvailability.validity_status != "active"
            )
        )
        needs_impl = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(
                CatalogTextbook.implementation_status.in_(["experimental", "regional_pilot", "needs_verification"])
            )
        )
        experimental = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(
                CatalogTextbook.implementation_status == "experimental"
            )
        )
        regional = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(
                CatalogTextbook.implementation_status == "regional_pilot"
            )
        )
        minority = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(
                CatalogTextbook.audience_variant == "religious_minority"
            )
        )
        gender = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(
                CatalogTextbook.audience_variant.in_(["girls", "boys"])
            )
        )
        no_code = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(CatalogTextbook.national_code.is_(None))
        )
        no_grade = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(CatalogTextbook.grade_id.is_(None))
        )
        dup = await session.scalar(
            select(func.count())
            .select_from(CatalogTextbook)
            .group_by(CatalogTextbook.slug)
            .having(func.count(CatalogTextbook.id) > 1)
        )
        print(
            "grades=%d cycles=%d branches=%d grounds=%d theo=%d tvo=%d kd=%d subjects=%d "
            "textbooks=%d links=%d availability=%d unverified_programs=%d review_books=%d "
            "experimental=%d regional=%d minority=%d gender=%d no_code=%d no_grade=%d duplicates=%d"
            % (
                grades, cycles, branches, grounds, theo, tvo, kd, subjects,
                textbooks, links, avail, unverified_programs, needs_impl,
                experimental, regional, minority, gender, no_code, no_grade, dup or 0,
            )
        )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())


async def book_stats() -> None:
    """R3: catalog book statistics (title / code / edition / PDF / ready / review)."""
    from app.models.catalog import CatalogCourseTextbook
    from app.models.curriculum import AcademicYear, Book, BookStatus

    engine = create_async_engine("sqlite+aiosqlite:////tmp/catalog_report_counts.db")
    factory = async_sessionmaker(bind=engine)
    async with factory() as session:
        year = await session.scalar(select(AcademicYear).where(AcademicYear.code == "1405-1406"))
        total = await session.scalar(select(func.count(CatalogTextbook.id)))
        with_title = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(CatalogTextbook.title_fa.is_not(None))
        )
        with_code = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(CatalogTextbook.national_code.is_not(None))
        )
        with_edition_year = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(CatalogTextbook.academic_year_id == year.id)
        )
        links = await session.scalar(select(func.count(CatalogCourseTextbook.id)))
        editions = await session.scalar(
            select(func.count(Book.id)).where(Book.catalog_textbook_id.is_not(None))
        )
        pdf_editions = await session.scalar(
            select(func.count(Book.id)).where(
                Book.catalog_textbook_id.is_not(None), Book.pdf_file_path.is_not(None)
            )
        )
        ready = await session.scalar(
            select(func.count(Book.id)).where(
                Book.status == BookStatus.ready, Book.catalog_textbook_id.is_not(None)
            )
        )
        needs_review = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(
                (CatalogTextbook.implementation_status.in_(["experimental", "regional_pilot", "needs_verification"]))
                | (CatalogTextbook.validity_status != "active")
            )
        )
        no_grade = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(CatalogTextbook.grade_id.is_(None))
        )
        print(
            "BOOK_STATS total=%d with_title=%d with_code=%d with_edition_year=%d links=%d "
            "editions=%d pdf_editions=%d ready=%d needs_review=%d no_grade=%d"
            % (total, with_title, with_code, with_edition_year, links, editions, pdf_editions, ready, needs_review, no_grade)
        )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(book_stats())
