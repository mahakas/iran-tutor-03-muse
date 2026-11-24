"""Scratch-DB check for the 1405-1406 catalog seed: run twice, verify
idempotency and print real counts (used for the implementation report).

Run: backend/.venv/bin/python scripts/catalog_seed_check.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, func, select
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
from app.models.curriculum import FieldOfStudy, Grade, Subject


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:////tmp/catalog_seed_check.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine)

    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await session.commit()

        stats1 = await seed_education_catalog_1405_1406(session)
        print("FIRST RUN:", dict(sorted(stats1.counts.items())))

        stats2 = await seed_education_catalog_1405_1406(session)
        print("SECOND RUN (must be zero-created):", dict(sorted(stats2.counts.items())))

        grades = await session.scalar(select(func.count(Grade.id)))
        grounds = await session.scalar(select(func.count(EducationGround.id)))
        fields_total = await session.scalar(select(func.count(FieldOfStudy.id)))
        tvo_fields = await session.scalar(
            select(func.count(FieldOfStudy.id)).where(FieldOfStudy.code.like("tec%"))
        )
        kd_fields = await session.scalar(
            select(func.count(FieldOfStudy.id)).where(FieldOfStudy.code.like("kar%"))
        )
        subjects = await session.scalar(select(func.count(Subject.id)))
        textbooks = await session.scalar(select(func.count(CatalogTextbook.id)))
        links = await session.scalar(select(func.count(CatalogCourseTextbook.id)))
        availability = await session.scalar(select(func.count(ProgramAvailability.id)))
        unverified_programs = await session.scalar(
            select(func.count(ProgramAvailability.id)).where(
                ProgramAvailability.validity_status == "needs_verification"
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
        no_grade = await session.scalar(
            select(func.count(CatalogTextbook.id)).where(CatalogTextbook.grade_id.is_(None))
        )
        duplicate_slugs = await session.scalar(
            select(func.count())
            .select_from(CatalogTextbook)
            .group_by(CatalogTextbook.slug)
            .having(func.count(CatalogTextbook.id) > 1)
        )
        print(
            f"grades={grades} grounds={grounds} fields_total={fields_total} "
            f"tvo={tvo_fields} kardanesh={kd_fields} subjects={subjects}"
        )
        print(
            f"textbooks={textbooks} links={links} availability={availability} "
            f"unverified_programs={unverified_programs}"
        )
        print(
            f"experimental={experimental} regional={regional} minority={minority} "
            f"no_grade_books={no_grade} duplicate_slugs={duplicate_slugs}"
        )

        # sanity: the common-book rule — «ریاضی (۱)» نظری دهم must have one record
        # with links to both ریاضی‌فیزیک and تجربی
        row = await session.execute(
            select(CatalogTextbook.slug, func.count(CatalogCourseTextbook.id))
            .join(CatalogCourseTextbook, CatalogCourseTextbook.textbook_id == CatalogTextbook.id)
            .where(CatalogTextbook.slug.like("g10-theo-ریاضی%"))
            .group_by(CatalogTextbook.id)
        )
        print("g10-theo-ریاضی(۱) links:", row.all())

        await session.execute(delete(CatalogTextbook).where(CatalogTextbook.id < 0))
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
