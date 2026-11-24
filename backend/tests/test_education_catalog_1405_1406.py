"""Iran Education Catalog 1405–1406 — mandatory acceptance tests.

Covers: education structure (12 grades / 3 stages / 3 tracks / grounds /
programs), the catalog books of this stage (elementary, lower-secondary, the
four theoretical programs, TVO common books, absence of vocational-specialist
and Kardanesh books), unique-record rules, audience/implementation flags, and
the self-service academic profile (student-only ownership, immediate save,
server-side combination validation, hard grade filter interplay).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.catalog_seed import seed_education_catalog_1405_1406
from app.db.seed import seed_curriculum_taxonomy, seed_grades, seed_majors
from app.models.auth import User
from app.models.catalog import (
    CatalogCourseTextbook,
    CatalogTextbook,
    EducationGround,
    ProgramAvailability,
    StudentAcademicProfile,
)
from app.models.curriculum import AcademicYear, EducationBranch, FieldOfStudy, Grade, Subject

# ---------------------------------------------------------------------------
# Shared fixture: full scratch DB + base seeds + the 1405-1406 catalog seed.
# ---------------------------------------------------------------------------


@pytest.fixture
async def catalog_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await session.commit()
        await seed_education_catalog_1405_1406(session)
        yield session
    await engine.dispose()


def _user(session: AsyncSession, phone: str) -> User:
    return User(phone_number=phone, role="student", plan_code="trial", plan_title="هدیه ثبت‌نام")


# ---------------------------------------------------------------------------
# ۱) ساختار آموزشی
# ---------------------------------------------------------------------------


async def test_structure_twelve_grades_and_three_cycles(catalog_session: AsyncSession):
    session = catalog_session
    grade_count = await session.scalar(select(func.count(Grade.id)))
    assert grade_count == 12
    cycle_ids = {
        row for row in (await session.scalars(select(Grade.cycle_id))).all() if row is not None
    }
    assert len(cycle_ids) == 3


async def test_grades_one_to_nine_have_no_track_or_program(catalog_session: AsyncSession):
    session = catalog_session
    branches = (await session.scalars(select(EducationBranch))).all()
    assert {b.code for b in branches} == {"theoretical", "technical_vocational", "kar_danesh"}
    for branch in branches:
        assert branch.min_grade == 10
    # No catalog offering of grades 1-9 is linked to any branch.
    lower_links = (
        await session.scalars(
            select(CatalogCourseTextbook).join(
                Grade, Grade.id == CatalogCourseTextbook.grade_id
            ).where(Grade.number < 10, CatalogCourseTextbook.branch_id.is_not(None))
        )
    ).all()
    assert lower_links == []


async def test_four_theoretical_programs_and_grounds(catalog_session: AsyncSession):
    session = catalog_session
    theoretical = await session.scalar(
        select(EducationBranch).where(EducationBranch.code == "theoretical")
    )
    fields = (
        await session.scalars(select(FieldOfStudy).where(FieldOfStudy.branch_id == theoretical.id))
    ).all()
    assert {f.code for f in fields} == {
        "math_physics",
        "experimental",
        "humanities",
        "islamic_studies",
    }
    assert all(f.ground_id is None for f in fields)

    grounds = (await session.scalars(select(EducationGround))).all()
    assert len(grounds) == 8  # (فنی‌وحرفه‌ای + کاردانش) × (صنعت، خدمات، هنر، کشاورزی)
    for branch_code in ("technical_vocational", "kar_danesh"):
        branch = await session.scalar(
            select(EducationBranch).where(EducationBranch.code == branch_code)
        )
        branch_grounds = [g for g in grounds if g.branch_id == branch.id]
        assert {g.code for g in branch_grounds} == {"industry", "services", "art", "agriculture"}

    tvo_count = await session.scalar(
        select(func.count(FieldOfStudy.id)).where(
            FieldOfStudy.code.like("tec-%"), FieldOfStudy.ground_id.is_not(None)
        )
    )
    kd_count = await session.scalar(
        select(func.count(FieldOfStudy.id)).where(
            FieldOfStudy.code.like("kar-%"), FieldOfStudy.ground_id.is_not(None)
        )
    )
    assert tvo_count == 44
    assert kd_count == 74


async def test_every_program_links_to_its_ground(catalog_session: AsyncSession):
    session = catalog_session
    programs = (
        await session.scalars(select(FieldOfStudy).where(FieldOfStudy.ground_id.is_not(None)))
    ).all()
    grounds = {g.id: g for g in (await session.scalars(select(EducationGround))).all()}
    assert programs
    for program in programs:
        ground = grounds[program.ground_id]
        assert ground.branch_id == program.branch_id  # same هنرستانی track
    # The unverified working list must never pretend to be confirmed.
    availability = (await session.scalars(select(ProgramAvailability))).all()
    assert availability
    assert all(a.validity_status == "needs_verification" for a in availability)


# ---------------------------------------------------------------------------
# ۲) کتاب‌ها
# ---------------------------------------------------------------------------


async def test_elementary_and_lower_secondary_books_exist(catalog_session: AsyncSession):
    session = catalog_session
    g1 = await session.scalar(select(Grade).where(Grade.number == 1))
    g9 = await session.scalar(select(Grade).where(Grade.number == 9))
    g1_books = (
        await session.scalars(
            select(CatalogTextbook).where(CatalogTextbook.grade_id == g1.id)
        )
    ).all()
    g1_titles = {b.title_fa for b in g1_books}
    assert {"فارسی", "ریاضی", "علوم تجربی", "جهان پیرامون", "حرکت و بازی"} <= g1_titles
    g9_books = (
        await session.scalars(
            select(CatalogTextbook).where(CatalogTextbook.grade_id == g9.id)
        )
    ).all()
    g9_titles = {b.title_fa for b in g9_books}
    assert {"آمادگی دفاعی", "پیام‌های آسمان", "زبان انگلیسی (۳)"} <= g9_titles


async def test_grade_twelve_books_for_all_four_theoretical_programs(catalog_session: AsyncSession):
    session = catalog_session
    g12 = await session.scalar(select(Grade).where(Grade.number == 12))
    theoretical = await session.scalar(
        select(EducationBranch).where(EducationBranch.code == "theoretical")
    )
    links = (
        await session.scalars(
            select(CatalogCourseTextbook).where(
                CatalogCourseTextbook.grade_id == g12.id,
                CatalogCourseTextbook.branch_id == theoretical.id,
                CatalogCourseTextbook.field_of_study_id.is_not(None),
            )
        )
    ).all()
    fields_by_link: dict[str, set[str]] = {}
    for link in links:
        program = await session.get(FieldOfStudy, link.field_of_study_id)
        textbook = await session.get(CatalogTextbook, link.textbook_id)
        fields_by_link.setdefault(textbook.title_fa, set()).add(program.code)
    for program in ("math_physics", "experimental", "humanities", "islamic_studies"):
        assert any(program in codes for codes in fields_by_link.values()), program
    # Each of the four programs has a full book list for grade 12.
    per_program: dict[str, int] = {}
    for link in links:
        program = await session.get(FieldOfStudy, link.field_of_study_id)
        per_program[program.code] = per_program.get(program.code, 0) + 1
    assert per_program == {
        "math_physics": 13,
        "experimental": 12,
        "humanities": 14,
        "islamic_studies": 18,
    }


async def test_common_theoretical_book_is_one_record_with_many_links(catalog_session: AsyncSession):
    session = catalog_session
    textbook = await session.scalar(
        select(CatalogTextbook).where(CatalogTextbook.slug == "g10-theo-فارسی-(۱)")
    )
    assert textbook is not None
    links = (
        await session.scalars(
            select(CatalogCourseTextbook).where(CatalogCourseTextbook.textbook_id == textbook.id)
        )
    ).all()
    assert len(links) == 4  # one record, four theoretical programs
    duplicate_rows = await session.scalar(
        select(func.count())
        .select_from(CatalogTextbook)
        .group_by(CatalogTextbook.slug)
        .having(func.count(CatalogTextbook.id) > 1)
    )
    assert not duplicate_rows


async def test_tvo_common_books_branch_scoped_no_specialist_books(catalog_session: AsyncSession):
    session = catalog_session
    tvo = await session.scalar(
        select(EducationBranch).where(EducationBranch.code == "technical_vocational")
    )
    g10 = await session.scalar(select(Grade).where(Grade.number == 10))
    g11 = await session.scalar(select(Grade).where(Grade.number == 11))
    g12 = await session.scalar(select(Grade).where(Grade.number == 12))
    links = (
        await session.scalars(
            select(CatalogCourseTextbook).where(
                CatalogCourseTextbook.branch_id == tvo.id,
                CatalogCourseTextbook.grade_id.in_([g10.id, g11.id, g12.id]),
            )
        )
    ).all()
    titles = set()
    for link in links:
        textbook = await session.get(CatalogTextbook, link.textbook_id)
        titles.add(textbook.title_fa)
        assert link.field_of_study_id is None  # branch-wide common scope only
    assert {
        "دین و زندگی (۱)",
        "الزامات محیط کار",
        "هوش مصنوعی",
        "کارگاه نوآوری و کارآفرینی",
        "اخلاق حرفه‌ای",
        "فارسی و نگارش (۳)",
    } <= titles
    assert len([t for t in titles if t == "اخلاق حرفه‌ای"]) == 1  # duplicated input → one record
    assert len(titles) == 9 + 11 + 10  # grade 10 + 11 + 12 common lists

    # No TVO/Kardanesh specialist textbooks exist in this stage, and no Kardanesh
    # books at all: every TVO/Kardanesh-scoped textbook title belongs to the
    # common lists above.
    kar = await session.scalar(select(EducationBranch).where(EducationBranch.code == "kar_danesh"))
    kar_links = (
        await session.scalars(
            select(CatalogCourseTextbook).where(CatalogCourseTextbook.branch_id == kar.id)
        )
    ).all()
    assert kar_links == []


async def test_audience_variants_and_uncertain_status_flags(catalog_session: AsyncSession):
    session = catalog_session
    # Religious-minority books are separate audience variants (TVO 1/2/3).
    minority = (
        await session.scalars(
            select(CatalogTextbook).where(CatalogTextbook.audience_variant == "religious_minority")
        )
    ).all()
    assert len(minority) == 3
    # Gender variants are independent records.
    girls = (
        await session.scalars(
            select(CatalogTextbook).where(CatalogTextbook.audience_variant == "girls")
        )
    ).all()
    boys = (
        await session.scalars(
            select(CatalogTextbook).where(CatalogTextbook.audience_variant == "boys")
        )
    ).all()
    assert len(girls) == 3 and len(boys) == 3

    # Experimental books keep their flag and are never mandatory for all schools.
    experimental_titles = {
        "ریاضی دوست‌داشتنی",
        "آموزش قرآن بخش اول",
        "جریان‌شناسی اندیشه‌های معاصر ایران",
    }
    experimental = (
        await session.scalars(
            select(CatalogTextbook).where(CatalogTextbook.implementation_status == "experimental")
        )
    ).all()
    assert {b.title_fa for b in experimental} == experimental_titles

    regional = (
        await session.scalars(
            select(CatalogTextbook).where(CatalogTextbook.implementation_status == "regional_pilot")
        )
    ).all()
    assert {b.title_fa for b in regional} == {"از من تا خدا", "از من تا خدا"}
    assert all(b.geographic_scope == "provincial" for b in regional)

    # The periodic booklet has NO grade: the exact placement is still unverified.
    periodic = await session.scalar(
        select(CatalogTextbook).where(
            CatalogTextbook.slug == "periodic-از-ایرانمان-دفاع-می‌کنیم"
        )
    )
    assert periodic is not None
    assert periodic.grade_id is None
    assert periodic.textbook_kind == "periodical"

    # The grade-11 معارف «هنر» title has no fabricated national code.
    honar = await session.scalar(
        select(CatalogTextbook).where(CatalogTextbook.slug == "g11-theo-هنر")
    )
    assert honar is not None
    assert honar.national_code is None
    assert honar.validity_status == "needs_verification"


async def test_grade_nine_dini_alternatives_never_both_mandatory(catalog_session: AsyncSession):
    session = catalog_session
    books = (
        await session.scalars(
            select(CatalogTextbook).where(
                CatalogTextbook.alternative_group == "tarbiat-dini-9"
            )
        )
    ).all()
    assert {b.title_fa for b in books} == {"پیام‌های آسمان", "از من تا خدا"}
    links = (
        await session.scalars(
            select(CatalogCourseTextbook).where(
                CatalogCourseTextbook.textbook_id.in_([b.id for b in books])
            )
        )
    ).all()
    mandatory = [link for link in links if link.is_mandatory]
    assert len(mandatory) == 1  # only پیام‌های آسمان is the default; the pair never co-mandatory


# ---------------------------------------------------------------------------
# ۳) پروفایل تحصیلی self-service
# ---------------------------------------------------------------------------


async def _student(catalog_session: AsyncSession, phone: str) -> User:
    session = catalog_session
    user = _user(session, phone)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def test_student_saves_and_changes_grade_without_admin(catalog_session: AsyncSession):
    from app.services.academic_profile_service import load_profile, update_profile

    session = catalog_session
    user = await _student(catalog_session, "09120000001")
    profile = await update_profile(
        session, user, grade_number=4, branch_code=None, ground_code=None, field_code=None
    )
    assert profile.grade_id is not None
    stored = await load_profile(session, user)
    assert stored is not None and stored.grade_id == profile.grade_id
    assert user.grade_level == 4  # legacy mirror updated in the same transaction
    assert user.role == "student"  # role is never touched by the profile API

    # The student changes the grade any time — still no approval step anywhere.
    await update_profile(session, user, grade_number=7, branch_code=None, ground_code=None, field_code=None)
    assert user.grade_level == 7


async def test_student_changes_track_ground_program_without_admin(catalog_session: AsyncSession):
    from app.services.academic_profile_service import load_profile, update_profile

    session = catalog_session
    user = await _student(catalog_session, "09120000002")
    await update_profile(
        session,
        user,
        grade_number=10,
        branch_code="technical_vocational",
        ground_code="services",
        field_code="tec-services-حسابداری",
    )
    profile = await load_profile(session, user)
    field = await session.get(FieldOfStudy, profile.field_of_study_id)
    assert field.code == "tec-services-حسابداری"
    assert user.major == field.code
    # Change to a theoretical program — the new field applies on the next request.
    await update_profile(
        session,
        user,
        grade_number=10,
        branch_code="theoretical",
        ground_code=None,
        field_code="experimental",
    )
    profile = await load_profile(session, user)
    field = await session.get(FieldOfStudy, profile.field_of_study_id)
    assert field.code == "experimental"
    assert user.major == "experimental"


async def test_profile_combination_validation_persian_errors(catalog_session: AsyncSession):
    from app.services.academic_profile_service import update_profile

    session = catalog_session
    user = await _student(catalog_session, "09120000003")

    with pytest.raises(HTTPException) as exc:
        await update_profile(
            session, user, grade_number=3, branch_code="theoretical", ground_code=None, field_code=None
        )
    assert "شاخه، زمینه و رشته ندارند" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        await update_profile(session, user, grade_number=10, branch_code=None, ground_code=None, field_code=None)
    assert "انتخاب شاخه" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        await update_profile(
            session,
            user,
            grade_number=10,
            branch_code="theoretical",
            ground_code="industry",
            field_code=None,
        )
    assert "زمینه وجود ندارد" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        await update_profile(
            session,
            user,
            grade_number=10,
            branch_code="technical_vocational",
            ground_code=None,
            field_code=None,
        )
    assert "زمینهٔ تحصیلی" in exc.value.detail

    # A theoretical program is refused under a هنرستانی track (wrong branch).
    with pytest.raises(HTTPException) as exc:
        await update_profile(
            session,
            user,
            grade_number=10,
            branch_code="kar_danesh",
            ground_code="industry",
            field_code="math_physics",
        )
    assert "تعلق ندارد" in exc.value.detail

    # A program under the wrong ground is refused.
    with pytest.raises(HTTPException) as exc:
        await update_profile(
            session,
            user,
            grade_number=10,
            branch_code="technical_vocational",
            ground_code="art",
            field_code="tec-services-حسابداری",
        )
    assert "به زمینهٔ انتخاب‌شده تعلق ندارد" in exc.value.detail


async def test_profile_api_is_self_only_and_role_immutable(catalog_session: AsyncSession):
    from app.api.academic_profile import get_academic_profile, update_academic_profile
    from app.api.academic_profile import AcademicProfileUpdateBody

    session = catalog_session
    user_a = await _student(catalog_session, "09120000004")
    user_b = await _student(catalog_session, "09120000005")

    response = Response()
    await update_academic_profile(
        AcademicProfileUpdateBody(grade_number=5),
        response,
        current_user=user_a,
        session=session,
    )
    # user_b's own profile view never leaks user_a's placement.
    payload_b = await get_academic_profile(Response(), current_user=user_b, session=session)
    assert payload_b["profile"]["exists"] is False
    payload_a = await get_academic_profile(Response(), current_user=user_a, session=session)
    assert payload_a["profile"]["exists"] is True
    assert payload_a["profile"]["grade_number"] == 5
    # The update body cannot carry a role/plan change at all.
    assert not hasattr(AcademicProfileUpdateBody, "role")
    assert user_a.role == "student" and user_b.role == "student"


async def test_profile_gates_missing_grade_message_for_tutor(catalog_session: AsyncSession):
    """A student without a profile gets the Persian self-service message, not an English error."""
    from app.api import dependencies

    from types import SimpleNamespace

    settings_stub = SimpleNamespace(demo_mode=False, require_student_grade_profile=True)
    user = SimpleNamespace(grade_level=None, role="student")

    from unittest.mock import patch

    with patch.object(dependencies, "get_settings", return_value=settings_stub):
        with pytest.raises(HTTPException) as exc:
            dependencies.enforce_student_grade_level(user, 10)
    assert "پایهٔ تحصیلی خود را در پروفایل انتخاب کن" in exc.value.detail


async def test_grade_change_applies_to_next_tutor_request_and_blocks_above_grade(catalog_session: AsyncSession):
    """After a profile change, the new grade is the bound for the next request.

    No mixing: content above the NEW grade is refused even though it was allowed
    before the change; the hard grade filter itself is untouched.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.api import dependencies
    from app.services.academic_profile_service import update_profile

    session = catalog_session
    user = await _student(catalog_session, "09120000006")
    await update_profile(
        session,
        user,
        grade_number=12,
        branch_code="theoretical",
        ground_code=None,
        field_code="math_physics",
    )

    settings_stub = SimpleNamespace(demo_mode=False, require_student_grade_profile=True)
    with patch.object(dependencies, "get_settings", return_value=settings_stub):
        # grade 12 profile: a grade-12 book is allowed.
        dependencies.enforce_student_grade_level(user, 12)
        # The student moves down to grade 10 — the same grade-12 book is now blocked.
        await update_profile(
            session,
            user,
            grade_number=10,
            branch_code="theoretical",
            ground_code=None,
            field_code="math_physics",
        )
        with pytest.raises(HTTPException) as exc:
            dependencies.enforce_student_grade_level(user, 12)
    assert "above the student's assigned grade" in exc.value.detail
    assert user.grade_level == 10


async def test_seed_is_idempotent_and_versions_by_academic_year(catalog_session: AsyncSession):
    session = catalog_session
    year = await session.scalar(select(AcademicYear).where(AcademicYear.code == "1405-1406"))
    assert year is not None
    before_books = await session.scalar(select(func.count(CatalogTextbook.id)))
    before_links = await session.scalar(select(func.count(CatalogCourseTextbook.id)))
    await seed_education_catalog_1405_1406(session)
    after_books = await session.scalar(select(func.count(CatalogTextbook.id)))
    after_links = await session.scalar(select(func.count(CatalogCourseTextbook.id)))
    assert before_books == after_books
    assert before_links == after_links
    # Every catalog textbook of this import carries the 1405-1406 year.
    wrong_year = await session.scalar(
        select(func.count(CatalogTextbook.id)).where(CatalogTextbook.academic_year_id != year.id)
    )
    assert wrong_year == 0


async def test_program_validity_is_visible_but_separate_from_selectability(catalog_session: AsyncSession):
    """Final review §2: the working-list status stays honest in UI data.

    needs_verification programs remain selectable (student self-service) but the
    options/profile payload always carries the official status so the UI can
    label them truthfully — and nothing is ever shown as confirmed/active.
    """
    from app.api.academic_profile import _picker_options
    from app.services.academic_profile_service import (
        load_profile,
        serialize_profile,
        update_profile,
    )

    session = catalog_session
    user = _user(session, "09120000009")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    await update_profile(
        session,
        user,
        grade_number=10,
        branch_code="technical_vocational",
        ground_code="services",
        field_code="tec-services-حسابداری",
    )
    profile = await load_profile(session, user)
    data = await serialize_profile(session, profile)
    assert data["field_code"] == "tec-services-حسابداری"
    assert data["field_validity_status"] == "needs_verification"  # honest, not "active"

    options = await _picker_options(session)
    accounting = next(p for p in options["programs"] if p["code"] == "tec-services-حسابداری")  # type: ignore[index]
    assert accounting["validity_status"] == "needs_verification"  # type: ignore[typeddict-item]
    # No option ever claims confirmed/active without an official source.
    assert all(
        p["validity_status"] in {"needs_verification", "unknown"}  # type: ignore[typeddict-item]
        for p in options["programs"]  # type: ignore[union-attr]
    )
