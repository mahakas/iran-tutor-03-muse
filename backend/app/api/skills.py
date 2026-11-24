"""Skills System API (Phase 2) — admin-only.

Admins can list, create, edit (versioned), test and roll back teaching skills
without a deploy. Every edit snapshots the previous prompt pack into
``skill_versions``; rollback restores a snapshot as a new version.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.db.session import get_session
from app.models.capabilities import Skill
from app.services import capability_runtime, capability_service

router = APIRouter(
    prefix="/api/v1/admin/skills",
    tags=["admin-skills"],
    dependencies=[Depends(require_admin)],
)


def _admin_identity(request: Request) -> str:
    identity = getattr(request.state, "admin_identity", None)
    if isinstance(identity, dict):
        return str(identity.get("user_id") or identity.get("kind") or "admin")
    return "admin"


@router.get("")
async def list_admin_skills(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skills = await capability_runtime.list_skills(session)
    return {"skills": [capability_runtime.serialize_skill(s) for s in skills]}


@router.get("/{slug}")
async def get_admin_skill(
    slug: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = await capability_runtime.get_skill_by_slug(session, slug)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"مهارت «{slug}» یافت نشد.")
    versions = await capability_runtime.list_skill_versions(session, skill.id)
    return {
        **capability_runtime.serialize_skill(skill),
        "versions": [capability_runtime.serialize_skill_version(v) for v in versions],
    }


class SkillCreateBody(BaseModel):
    slug: str = Field(min_length=1, max_length=96)
    capability_key: str = Field(min_length=1, max_length=64)
    title_fa: str = Field(min_length=1, max_length=160)
    subject_scope: str | None = None
    grade_scope: str | None = None
    system_prompt: str = ""
    pedagogy_rules_md: str = ""
    output_schema: dict[str, Any] = Field(default_factory=dict)
    safety_gate_rules: str = ""


class SkillUpdateBody(BaseModel):
    title_fa: str | None = None
    system_prompt: str | None = None
    pedagogy_rules_md: str | None = None
    output_schema: dict[str, Any] | None = None
    safety_gate_rules: str | None = None
    is_active: bool | None = None
    change_note: str | None = None


@router.post("", status_code=201)
async def create_admin_skill(
    body: SkillCreateBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    capability = await capability_service.get_capability(session, body.capability_key)
    if capability is None:
        raise HTTPException(
            status_code=422, detail=f"قابلیت «{body.capability_key}» یافت نشد."
        )
    existing = await capability_runtime.get_skill_by_slug(session, body.slug)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"مهارت «{body.slug}» از قبل وجود دارد.")
    skill = Skill(
        slug=body.slug,
        capability_key=body.capability_key,
        title_fa=body.title_fa,
        subject_scope=body.subject_scope,
        grade_scope=body.grade_scope,
        system_prompt=body.system_prompt,
        pedagogy_rules_md=body.pedagogy_rules_md,
        output_schema_json=dict(body.output_schema),
        safety_gate_rules=body.safety_gate_rules,
        version=1,
        is_active=True,
        updated_by=_admin_identity(request),
    )
    session.add(skill)
    await session.flush()
    from app.models.capabilities import SkillVersion

    session.add(
        SkillVersion(
            skill_id=skill.id,
            version=1,
            system_prompt=skill.system_prompt,
            pedagogy_rules_md=skill.pedagogy_rules_md,
            output_schema_json=dict(skill.output_schema_json),
            safety_gate_rules=skill.safety_gate_rules,
            change_note="نسخهٔ اولیه",
            created_by=_admin_identity(request),
        )
    )
    await session.commit()
    await session.refresh(skill)
    return capability_runtime.serialize_skill(skill)


@router.put("/{slug}")
async def update_admin_skill(
    slug: str,
    body: SkillUpdateBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = await capability_runtime.update_skill(
        session,
        slug,
        system_prompt=body.system_prompt,
        pedagogy_rules_md=body.pedagogy_rules_md,
        output_schema_json=body.output_schema,
        safety_gate_rules=body.safety_gate_rules,
        title_fa=body.title_fa,
        is_active=body.is_active,
        updated_by=_admin_identity(request),
        change_note=body.change_note,
    )
    return capability_runtime.serialize_skill(skill)


class SkillRollbackBody(BaseModel):
    to_version: int = Field(ge=1)


@router.post("/{slug}/rollback")
async def rollback_admin_skill(
    slug: str,
    body: SkillRollbackBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = await capability_runtime.rollback_skill(
        session, slug, to_version=body.to_version, updated_by=_admin_identity(request)
    )
    return capability_runtime.serialize_skill(skill)


class SkillTestBody(BaseModel):
    sample_input: str = Field(min_length=1, max_length=4000)


@router.post("/{slug}/test")
async def test_admin_skill(
    slug: str,
    body: SkillTestBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    identity = getattr(request.state, "admin_identity", None)
    user_id = identity.get("user_id") if isinstance(identity, dict) else None
    return await capability_runtime.test_skill(
        session=session, slug=slug, sample_input=body.sample_input, user_id=user_id
    )


@router.delete("/{slug}")
async def delete_admin_skill(
    slug: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    skill = await capability_runtime.get_skill_by_slug(session, slug)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"مهارت «{slug}» یافت نشد.")
    from app.models.capabilities import SkillVersion

    await session.execute(
        SkillVersion.__table__.delete().where(SkillVersion.skill_id == skill.id)
    )
    await session.delete(skill)
    await session.commit()
    return {"ok": True, "deleted": slug}
