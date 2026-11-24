"""Student academic profile — self-service placement (base/track/ground/program).

Product policy (owner spec): the student alone owns and edits this profile.
There is NO admin approval step anywhere; the admin panel only displays it.
Every combination is validated server-side against the education catalog:
- grades 1–9: base/grade only — track, ground and program are refused;
- grades 10–12: a track is required;
  - نظری: program required, must belong to the theoretical track, ground refused;
  - فنی‌وحرفه‌ای/کاردانش: ground required first, then a program under that ground.
The legacy columns (users.grade_level / users.major) are mirrored so existing
tutor/RAG filters keep working unchanged. user.role is never touched here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.catalog import EducationGround, ProgramAvailability, StudentAcademicProfile
from app.models.curriculum import (
    AcademicYear,
    EducationBranch,
    EducationCycle,
    FieldOfStudy,
    Grade,
)

REQUIRED_PROGRAM_GRADE_MIN = 10

PROFILE_REQUIRED_MESSAGE = (
    "برای استفاده از امکانات آموزشی، ابتدا پایهٔ تحصیلی خود را در پروفایل انتخاب کن."
)


async def load_profile(session: AsyncSession, user: User) -> StudentAcademicProfile | None:
    return await session.scalar(
        select(StudentAcademicProfile).where(StudentAcademicProfile.user_id == user.id)
    )


async def get_grade(session: AsyncSession, grade_number: int | None) -> Grade | None:
    if grade_number is None:
        return None
    return await session.scalar(select(Grade).where(Grade.number == grade_number))


async def get_branch(session: AsyncSession, branch_code: str | None) -> EducationBranch | None:
    if not branch_code:
        return None
    return await session.scalar(
        select(EducationBranch).where(
            EducationBranch.code == branch_code, EducationBranch.is_active.is_(True)
        )
    )


async def get_ground(
    session: AsyncSession, branch: EducationBranch, ground_code: str | None
) -> EducationGround | None:
    if not ground_code:
        return None
    return await session.scalar(
        select(EducationGround).where(
            EducationGround.branch_id == branch.id,
            EducationGround.code == ground_code,
            EducationGround.is_active.is_(True),
        )
    )


async def get_field(session: AsyncSession, field_code: str | None) -> FieldOfStudy | None:
    if not field_code:
        return None
    return await session.scalar(select(FieldOfStudy).where(FieldOfStudy.code == field_code))


async def validate_placement(
    session: AsyncSession,
    *,
    grade_number: int | None,
    branch_code: str | None,
    ground_code: str | None,
    field_code: str | None,
) -> tuple[Grade, EducationBranch | None, EducationGround | None, FieldOfStudy | None]:
    """Validate a (grade, track, ground, program) combination; Persian errors."""
    grade = await get_grade(session, grade_number)
    if grade is None:
        raise HTTPException(status_code=422, detail="پایهٔ تحصیلی نامعتبر است.")

    if grade.number < REQUIRED_PROGRAM_GRADE_MIN:
        if branch_code or ground_code or field_code:
            raise HTTPException(
                status_code=422,
                detail="پایه‌های ۱ تا ۹ شاخه، زمینه و رشته ندارند؛ فقط پایه را انتخاب کن.",
            )
        return grade, None, None, None

    branch = await get_branch(session, branch_code)
    if branch is None:
        raise HTTPException(
            status_code=422,
            detail="برای پایه‌های دهم تا دوازدهم انتخاب شاخه (نظری، فنی‌وحرفه‌ای، کاردانش) الزامی است.",
        )
    if not branch.min_grade <= grade.number <= branch.max_grade:
        raise HTTPException(status_code=422, detail="این شاخه برای پایهٔ انتخاب‌شده تعریف نشده است.")

    ground = await get_ground(session, branch, ground_code)
    field = await get_field(session, field_code)

    if branch.code == "theoretical":
        if ground_code:
            raise HTTPException(
                status_code=422, detail="در شاخهٔ نظری زمینه وجود ندارد؛ رشته را مستقیم انتخاب کن."
            )
        if field is None:
            raise HTTPException(status_code=422, detail="رشتهٔ نظری باید انتخاب شود.")
        if field.branch_id != branch.id:
            raise HTTPException(status_code=422, detail="این رشته به شاخهٔ نظری تعلق ندارد.")
        return grade, branch, None, field

    # فنی‌وحرفه‌ای / کاردانش: Track -> Ground -> Program
    if ground is None:
        raise HTTPException(
            status_code=422, detail="ابتدا زمینهٔ تحصیلی (صنعت، خدمات، هنر، کشاورزی) را انتخاب کن."
        )
    if ground.branch_id != branch.id:
        raise HTTPException(status_code=422, detail="این زمینه به شاخهٔ انتخاب‌شده تعلق ندارد.")
    if field is None:
        raise HTTPException(status_code=422, detail="رشتهٔ تحصیلی باید انتخاب شود.")
    if field.branch_id != branch.id:
        raise HTTPException(status_code=422, detail="این رشته به شاخهٔ انتخاب‌شده تعلق ندارد.")
    if field.ground_id != ground.id:
        raise HTTPException(status_code=422, detail="این رشته به زمینهٔ انتخاب‌شده تعلق ندارد.")
    return grade, branch, ground, field


async def update_profile(
    session: AsyncSession,
    user: User,
    *,
    grade_number: int | None,
    branch_code: str | None,
    ground_code: str | None,
    field_code: str | None,
    academic_year_id: int | None = None,
) -> StudentAcademicProfile:
    """Validate and persist the student's own placement; sync legacy mirrors."""
    grade, branch, ground, field = await validate_placement(
        session,
        grade_number=grade_number,
        branch_code=branch_code,
        ground_code=ground_code,
        field_code=field_code,
    )
    profile = await load_profile(session, user)
    if profile is None:
        profile = StudentAcademicProfile(user_id=user.id)
        session.add(profile)
    profile.grade_id = grade.id
    profile.branch_id = branch.id if branch is not None else None
    profile.ground_id = ground.id if ground is not None else None
    profile.field_of_study_id = field.id if field is not None else None
    profile.academic_year_id = academic_year_id
    profile.updated_at = datetime.now(timezone.utc)

    # Legacy mirrors used by the tutor/RAG grade filter and old clients.
    user.grade_level = grade.number
    user.major = field.code if field is not None else None
    # user.role is intentionally NOT modified here: the academic profile API can
    # never change roles or permissions.
    await session.commit()
    await session.refresh(profile)
    return profile


async def serialize_profile(session: AsyncSession, profile: StudentAcademicProfile | None) -> dict[str, object]:
    if profile is None:
        return {"exists": False}
    grade = await session.get(Grade, profile.grade_id) if profile.grade_id else None
    cycle_title = None
    if grade is not None and grade.cycle_id is not None:
        cycle = await session.get(EducationCycle, grade.cycle_id)
        cycle_title = cycle.title if cycle else None
    branch = await session.get(EducationBranch, profile.branch_id) if profile.branch_id else None
    ground = await session.get(EducationGround, profile.ground_id) if profile.ground_id else None
    field = await session.get(FieldOfStudy, profile.field_of_study_id) if profile.field_of_study_id else None
    year = await session.get(AcademicYear, profile.academic_year_id) if profile.academic_year_id else None
    field_validity_status: str | None = None
    if field is not None:
        availability_year_id = profile.academic_year_id or (
            (await session.scalar(select(AcademicYear.id).where(AcademicYear.is_active.is_(True)).order_by(AcademicYear.id.desc())))
        )
        if availability_year_id is not None:
            availability = await session.scalar(
                select(ProgramAvailability).where(
                    ProgramAvailability.field_of_study_id == field.id,
                    ProgramAvailability.academic_year_id == availability_year_id,
                )
            )
            field_validity_status = availability.validity_status if availability else "unknown"
    if field_validity_status is None and field is None:
        field_validity_status = None
    return {
        "exists": True,
        "grade_number": grade.number if grade else None,
        "grade_title": grade.title if grade else None,
        "cycle_title": cycle_title,
        "branch_code": branch.code if branch else None,
        "branch_title": branch.title if branch else None,
        "ground_code": ground.code if ground else None,
        "ground_title": ground.title if ground else None,
        "field_code": field.code if field else None,
        "field_title": field.title if field else None,
        "field_validity_status": field_validity_status,
        "academic_year_code": year.code if year else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
