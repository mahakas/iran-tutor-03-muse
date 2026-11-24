"""Self-service academic profile API — the student edits their own placement.

- GET  /api/v1/account/academic-profile   → current placement + picker options
- PUT  /api/v1/account/academic-profile   → validate + save (no reload needed)

There is no approval workflow in this file by design: the profile is saved
immediately and the next tutor/RAG request uses it. Ownership is enforced by
`require_student` (only the caller's own profile is touched), CSRF/RBAC come
from the shared dependencies, and `user.role` is never writable here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, require_student
from app.models.auth import User
from app.models.catalog import EducationGround, ProgramAvailability
from app.models.curriculum import AcademicYear, EducationBranch, FieldOfStudy, Grade
from app.services import academic_profile_service as profile_service

router = APIRouter(prefix="/api/v1/account", tags=["account"])

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class AcademicProfileUpdateBody(BaseModel):
    grade_number: int | None = Field(default=None, ge=1, le=12)
    branch_code: str | None = Field(default=None, max_length=64)
    ground_code: str | None = Field(default=None, max_length=64)
    field_code: str | None = Field(default=None, max_length=64)


async def _picker_options(session: AsyncSession) -> dict[str, object]:
    grades = (await session.scalars(select(Grade).order_by(Grade.number))).all()
    branches = (
        await session.scalars(
            select(EducationBranch)
            .where(EducationBranch.is_active.is_(True))
            .order_by(EducationBranch.sort_order)
        )
    ).all()
    grounds = (
        await session.scalars(
            select(EducationGround)
            .where(EducationGround.is_active.is_(True))
            .order_by(EducationGround.sort_order)
        )
    ).all()
    programs = (
        await session.scalars(
            select(FieldOfStudy)
            .where(FieldOfStudy.is_active.is_(True))
            .order_by(FieldOfStudy.sort_order)
        )
    ).all()
    # Official validity status per program (owner working list stays honest):
    # needs_verification programs stay selectable but are never presented as
    # "active/confirmed" — display is independent of the official status.
    active_year = await session.scalar(
        select(AcademicYear).where(AcademicYear.is_active.is_(True)).order_by(AcademicYear.id.desc())
    )
    validity_by_program: dict[int, str] = {}
    if active_year is not None:
        rows = (
            await session.scalars(
                select(ProgramAvailability).where(ProgramAvailability.academic_year_id == active_year.id)
            )
        ).all()
        validity_by_program = {row.field_of_study_id: row.validity_status for row in rows}
    return {
        "grades": [
            {"number": grade.number, "title": grade.title, "requires_track": grade.number >= 10}
            for grade in grades
        ],
        "branches": [
            {
                "code": branch.code,
                "title": branch.title,
                "min_grade": branch.min_grade,
                "max_grade": branch.max_grade,
                "uses_grounds": branch.code != "theoretical",
            }
            for branch in branches
        ],
        "grounds": [
            {
                "branch_code": next(
                    (b.code for b in branches if b.id == ground.branch_id), None
                ),
                "code": ground.code,
                "title": ground.title,
            }
            for ground in grounds
        ],
        "programs": [
            {
                "branch_code": next(
                    (b.code for b in branches if b.id == program.branch_id), None
                ),
                "ground_code": next(
                    (g.code for g in grounds if g.id == program.ground_id), None
                ),
                "code": program.code,
                "title": program.title,
                "is_theoretical": program.ground_id is None
                and any(b.id == program.branch_id and b.code == "theoretical" for b in branches),
                "validity_status": validity_by_program.get(program.id, "unknown"),
            }
            for program in programs
        ],
    }


@router.get("/academic-profile")
async def get_academic_profile(
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    for key, value in _NO_STORE.items():
        response.headers[key] = value
    profile = await profile_service.load_profile(session, current_user)
    return {
        "profile": await profile_service.serialize_profile(session, profile),
        "options": await _picker_options(session),
        "mirror": {
            "grade_level": current_user.grade_level,
            "major": current_user.major,
        },
    }


@router.put("/academic-profile")
async def update_academic_profile(
    body: AcademicProfileUpdateBody,
    response: Response,
    current_user: User = Depends(require_student),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    for key, value in _NO_STORE.items():
        response.headers[key] = value
    if body.grade_number is None:
        raise HTTPException(status_code=422, detail=profile_service.PROFILE_REQUIRED_MESSAGE)
    profile = await profile_service.update_profile(
        session,
        current_user,
        grade_number=body.grade_number,
        branch_code=body.branch_code,
        ground_code=body.ground_code,
        field_code=body.field_code,
    )
    return {
        "profile": await profile_service.serialize_profile(session, profile),
        "saved": True,
    }
