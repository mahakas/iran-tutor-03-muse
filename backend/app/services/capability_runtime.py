"""Shared Capability Runtime (Phase 2).

Every pluggable learning feature executes through this runtime, which:

1. resolves the active :class:`~app.models.capabilities.Skill` for the
   capability (most specific ``subject_scope``/``grade_scope`` wins);
2. composes the system prompt from the skill's prompt pack
   (``system_prompt`` + ``pedagogy_rules_md`` + ``safety_gate_rules``);
3. performs the model call through the Central AI Gateway
   (:mod:`app.services.ai_gateway`) so it is audited, quota-checked and
   admin-routable;
4. optionally converts the answer into typed
   :class:`~app.services.learning_blocks.LearningBlock` items.

Admins can edit, test and roll back skill versions without a deploy; the
runtime always reads the active row from the database.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.capabilities import Skill, SkillVersion
from app.services.capability_service import require_capability_enabled
from app.services.ai_gateway import (
    CallContext,
    GatewayResult,
    complete_json_via_gateway,
    complete_text_via_gateway,
    speech_via_gateway,
)
from app.services.learning_blocks import LearningBlock, blocks_from_answer, parse_blocks_json
from app.services.grounding_guard import check_textbook_grounding
from app.services.quota_service import enforce_ai_quota

logger = logging.getLogger(__name__)


def compose_system_prompt(skill: Skill) -> str:
    """Assemble the effective system prompt from a skill's prompt pack."""
    parts = [skill.system_prompt.strip()]
    if skill.pedagogy_rules_md and skill.pedagogy_rules_md.strip():
        parts.append(skill.pedagogy_rules_md.strip())
    if skill.safety_gate_rules and skill.safety_gate_rules.strip():
        parts.append("قواعد ایمنی:\n" + skill.safety_gate_rules.strip())
    return "\n\n".join(part for part in parts if part)


async def load_active_skill(
    session: AsyncSession,
    capability_key: str,
    *,
    subject_scope: str | None = None,
    grade_scope: str | None = None,
) -> Skill | None:
    """Resolve the active skill for a capability.

    Specificity order: subject+grade match > subject match > grade match >
    generic (both scopes null). Inactive skills are never returned.
    """
    rows = list(
        (
            await session.scalars(
                select(Skill).where(
                    Skill.capability_key == capability_key,
                    Skill.is_active.is_(True),
                )
            )
        ).all()
    )
    if not rows:
        return None

    def specificity(skill: Skill) -> tuple[int, int]:
        score = 0
        if skill.subject_scope and subject_scope and skill.subject_scope == subject_scope:
            score += 2
        if skill.grade_scope and grade_scope and skill.grade_scope == grade_scope:
            score += 1
        return (score, skill.version)

    rows.sort(key=specificity, reverse=True)
    return rows[0]


async def get_skill_by_slug(session: AsyncSession, slug: str) -> Skill | None:
    return await session.scalar(select(Skill).where(Skill.slug == slug))


async def list_skills(session: AsyncSession) -> list[Skill]:
    rows = await session.scalars(
        select(Skill).order_by(Skill.capability_key.asc(), Skill.slug.asc())
    )
    return list(rows)


def serialize_skill(skill: Skill, *, include_prompt: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": skill.id,
        "slug": skill.slug,
        "capability_key": skill.capability_key,
        "title_fa": skill.title_fa,
        "subject_scope": skill.subject_scope,
        "grade_scope": skill.grade_scope,
        "output_schema": dict(skill.output_schema_json or {}),
        "version": skill.version,
        "is_active": bool(skill.is_active),
        "updated_by": skill.updated_by,
    }
    if include_prompt:
        payload.update(
            {
                "system_prompt": skill.system_prompt,
                "pedagogy_rules_md": skill.pedagogy_rules_md,
                "safety_gate_rules": skill.safety_gate_rules,
            }
        )
    return payload


def serialize_skill_version(version: SkillVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "skill_id": version.skill_id,
        "version": version.version,
        "system_prompt": version.system_prompt,
        "pedagogy_rules_md": version.pedagogy_rules_md,
        "output_schema": dict(version.output_schema_json or {}),
        "safety_gate_rules": version.safety_gate_rules,
        "change_note": version.change_note,
        "created_by": version.created_by,
    }


async def list_skill_versions(session: AsyncSession, skill_id: int) -> list[SkillVersion]:
    rows = await session.scalars(
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill_id)
        .order_by(SkillVersion.version.desc())
    )
    return list(rows)


async def update_skill(
    session: AsyncSession,
    slug: str,
    *,
    system_prompt: str | None = None,
    pedagogy_rules_md: str | None = None,
    output_schema_json: dict[str, Any] | None = None,
    safety_gate_rules: str | None = None,
    title_fa: str | None = None,
    is_active: bool | None = None,
    updated_by: str | None = None,
    change_note: str | None = None,
) -> Skill:
    """Apply an edit as a new immutable version (version bump + snapshot)."""
    skill = await get_skill_by_slug(session, slug)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"مهارت «{slug}» یافت نشد.")
    if system_prompt is not None:
        skill.system_prompt = system_prompt
    if pedagogy_rules_md is not None:
        skill.pedagogy_rules_md = pedagogy_rules_md
    if output_schema_json is not None:
        skill.output_schema_json = dict(output_schema_json)
    if safety_gate_rules is not None:
        skill.safety_gate_rules = safety_gate_rules
    if title_fa is not None:
        skill.title_fa = title_fa
    if is_active is not None:
        skill.is_active = is_active
    skill.version += 1
    skill.updated_by = updated_by
    await session.flush()
    session.add(
        SkillVersion(
            skill_id=skill.id,
            version=skill.version,
            system_prompt=skill.system_prompt,
            pedagogy_rules_md=skill.pedagogy_rules_md,
            output_schema_json=dict(skill.output_schema_json or {}),
            safety_gate_rules=skill.safety_gate_rules,
            change_note=change_note,
            created_by=updated_by,
        )
    )
    await session.commit()
    await session.refresh(skill)
    return skill


async def rollback_skill(
    session: AsyncSession,
    slug: str,
    *,
    to_version: int,
    updated_by: str | None = None,
) -> Skill:
    """Restore a previous version as a new version (history is never rewritten)."""
    skill = await get_skill_by_slug(session, slug)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"مهارت «{slug}» یافت نشد.")
    snapshot = await session.scalar(
        select(SkillVersion).where(
            SkillVersion.skill_id == skill.id,
            SkillVersion.version == to_version,
        )
    )
    if snapshot is None:
        raise HTTPException(
            status_code=404, detail=f"نسخهٔ {to_version} برای مهارت «{slug}» یافت نشد."
        )
    skill.system_prompt = snapshot.system_prompt
    skill.pedagogy_rules_md = snapshot.pedagogy_rules_md
    skill.output_schema_json = dict(snapshot.output_schema_json or {})
    skill.safety_gate_rules = snapshot.safety_gate_rules
    skill.version += 1
    skill.updated_by = updated_by
    await session.flush()
    session.add(
        SkillVersion(
            skill_id=skill.id,
            version=skill.version,
            system_prompt=skill.system_prompt,
            pedagogy_rules_md=skill.pedagogy_rules_md,
            output_schema_json=dict(skill.output_schema_json or {}),
            safety_gate_rules=skill.safety_gate_rules,
            change_note=f"بازگشت به نسخهٔ {to_version}",
            created_by=updated_by,
        )
    )
    await session.commit()
    await session.refresh(skill)
    return skill


async def enforce_capability_call(
    session: AsyncSession | None,
    capability_key: str,
    *,
    user: User | None,
    feature_key: str,
) -> None:
    """Pre-call gate used by every runtime execution (Phase 2 hardening).

    1. The capability must exist and be enabled for the user's role/plan
       (`require_capability_enabled`: 404 unknown, 403 disabled/not allowed).
    2. When a user is known, the AI quota / rate limit is consumed first
       (`enforce_ai_quota`: 402/403/429). The gateway itself does not gate quota.

    Without a DB session no gate can be evaluated, so callers must pass one
    unless they explicitly run in a non-enforcing mode (admin skill test).
    """
    if session is None:
        raise RuntimeError("capability calls require a database session for enforcement")
    await require_capability_enabled(session, capability_key, user)
    if user is not None:
        await enforce_ai_quota(session, user=user, feature_key=feature_key)



def _detached_accounting(session: AsyncSession | None, requested: bool) -> bool:
    """Detach audit/quota writes only where the race exists (Phase 04C).

    The user_quotas unique-index entry held open across provider network calls
    is a PostgreSQL behaviour; SQLite tests use a single-writer database where
    a second write session would just deadlock, so there the audit stays in
    the caller's transaction.
    """
    if not requested or session is None:
        return False
    try:
        return session.bind.dialect.name == "postgresql"
    except Exception:  # noqa: BLE001 - defensive: fall back to same-transaction
        return False


async def run_capability_text(
    *,
    session: AsyncSession | None,
    capability_key: str,
    user_text: str,
    feature_key: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    book_id: int | None = None,
    textbook_strict: bool = True,
    citations: list[dict[str, Any]] | None = None,
    rag_hit_count: int | None = None,
    subject_scope: str | None = None,
    grade_scope: str | None = None,
    extra_system: str | None = None,
    model: str | None = None,
    user: User | None = None,
    enforce: bool = True,
    audit_in_own_transaction: bool = False,
) -> tuple[GatewayResult, list[LearningBlock], Skill | None]:
    """Execute one capability call: skill prompt -> gateway -> typed blocks.

    Returns ``(gateway_result, blocks, skill)``. When no active skill exists
    the caller-provided ``extra_system`` (or a generic Persian tutor prompt)
    is used so the capability still works before skills are seeded.
    """
    skill: Skill | None = None
    system_prompt = extra_system or "تو معلم خصوصی فارسیِ دانش‌آموزان ایران هستی."
    if enforce:
        await enforce_capability_call(
            session, capability_key, user=user, feature_key=feature_key or capability_key
        )
    if session is not None:
        skill = await load_active_skill(
            session, capability_key, subject_scope=subject_scope, grade_scope=grade_scope
        )
        if skill is not None:
            system_prompt = compose_system_prompt(skill)
            if extra_system:
                system_prompt = system_prompt + "\n\n" + extra_system

    ctx = CallContext(
        feature_key=feature_key or capability_key,
        user_id=user_id,
        session_id=session_id,
        skill_id=skill.slug if skill else None,
        book_id=book_id,
        textbook_strict=textbook_strict,
        citations=citations or [],
        rag_hit_count=rag_hit_count,
    )
    result = await complete_text_via_gateway(
        ctx=ctx,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        model=model,
        session=session,
        audit_in_own_transaction=_detached_accounting(session, audit_in_own_transaction),
    )
    answer = result.content if isinstance(result.content, str) else str(result.content)
    blocks = blocks_from_answer(answer, citations)
    await check_textbook_grounding(
        session,
        capability_key=capability_key,
        feature_key=feature_key or capability_key,
        book_id=book_id,
        citations=citations,
        user_id=user_id,
        session_id=session_id,
    )
    return result, blocks, skill


async def test_skill(
    *,
    session: AsyncSession,
    slug: str,
    sample_input: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Run a skill against a sample input through the gateway (admin test)."""
    skill = await get_skill_by_slug(session, slug)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"مهارت «{slug}» یافت نشد.")
    # Admin test: non-enforcing (admins may test a capability before enabling it),
    # but the call still goes through the gateway and is audited.
    result, blocks, _ = await run_capability_text(
        session=session,
        capability_key=skill.capability_key,
        user_text=sample_input,
        user_id=user_id,
        textbook_strict=False,
        enforce=False,
    )
    answer = result.content if isinstance(result.content, str) else str(result.content)
    return {
        "skill_slug": skill.slug,
        "skill_version": skill.version,
        "capability_key": skill.capability_key,
        "model_name": result.model_name,
        "latency_ms": result.latency_ms,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "audit_id": result.audit_id,
        "status": result.status,
        "answer": answer,
        "blocks": [block.model_dump() for block in blocks],
    }


async def run_capability_json(
    *,
    session: AsyncSession | None,
    capability_key: str,
    user_text: str,
    feature_key: str | None = None,
    user_id: str | None = None,
    book_id: int | None = None,
    textbook_strict: bool = True,
    citations: list[dict[str, Any]] | None = None,
    rag_hit_count: int | None = None,
    subject_scope: str | None = None,
    grade_scope: str | None = None,
    model: str | None = None,
    user: User | None = None,
    enforce: bool = True,
    extra_system: str | None = None,
) -> tuple[GatewayResult, Skill | None]:
    """JSON variant of :func:`run_capability_text` (structured output skills).

    `extra_system` carries server-built context such as learner memory (Phase 4).
    """
    skill: Skill | None = None
    system_prompt = "تو یک موتور آموزشی فارسی هستی. فقط JSON برگردان."
    if enforce:
        await enforce_capability_call(
            session, capability_key, user=user, feature_key=feature_key or capability_key
        )
    if session is not None:
        skill = await load_active_skill(
            session, capability_key, subject_scope=subject_scope, grade_scope=grade_scope
        )
        if skill is not None:
            system_prompt = compose_system_prompt(skill)
    if extra_system:
        system_prompt = system_prompt + "\n\n" + extra_system
    ctx = CallContext(
        feature_key=feature_key or capability_key,
        user_id=user_id,
        skill_id=skill.slug if skill else None,
        book_id=book_id,
        textbook_strict=textbook_strict,
        citations=citations or [],
        rag_hit_count=rag_hit_count,
    )
    result = await complete_json_via_gateway(
        ctx=ctx,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        model=model,
        session=session,
    )
    await check_textbook_grounding(
        session,
        capability_key=capability_key,
        feature_key=feature_key or capability_key,
        book_id=book_id,
        citations=citations,
        user_id=user_id,
    )
    return result, skill


__all__ = [
    "compose_system_prompt",
    "get_skill_by_slug",
    "list_skills",
    "list_skill_versions",
    "load_active_skill",
    "parse_blocks_json",
    "rollback_skill",
    "run_capability_json",
    "run_capability_text",
    "serialize_skill",
    "serialize_skill_version",
    "test_skill",
    "update_skill",
]


async def run_capability_speech(
    *,
    session: AsyncSession,
    capability_key: str,
    text: str,
    voice: str,
    feature_key: str | None = None,
    user_id: str | None = None,
    book_id: int | None = None,
    user: User | None = None,
    enforce: bool = True,
    audit_in_own_transaction: bool = False,
) -> tuple[bytes, GatewayResult]:
    """Text-to-speech through the runtime: capability/quota gate -> gateway -> audit.

    Speech has no prompt skill, but it still passes the same gates as every other
    capability call, so admin toggles, plan access and `user_quotas` apply.
    """
    key = feature_key or capability_key
    if enforce:
        await enforce_capability_call(session, capability_key, user=user, feature_key=key)
    ctx = CallContext(
        feature_key=key,
        user_id=user_id,
        book_id=book_id,
        textbook_strict=False,
    )
    return await speech_via_gateway(
        ctx=ctx, text=text, voice=voice, session=session,
        audit_in_own_transaction=_detached_accounting(session, audit_in_own_transaction),
    )
