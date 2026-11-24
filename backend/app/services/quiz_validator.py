"""Phase 5 Validator Gate: stage 2 of the self-validated quiz pipeline.

Stage 1 (Generator) produces candidate questions from textbook pages. This module
checks each candidate and keeps only questions that are:

1. structurally sound (4 distinct non-empty choices, valid answer key, sourced),
2. LaTeX-valid (balanced `$`, braces, `\\begin`/`\\end`, `\\left`/`\\right`),
3. grounded in the provided textbook text, unambiguous, and whose answer key the
   validator model independently confirms.

A defective question gets one repair attempt (`fix`) that must pass the same
deterministic checks and match the confirmed answer; otherwise it is rejected.
The model call goes through `capability_runtime` -> `ai_gateway`, so it is
routable by the admin and audited. Every rejection or repair is also recorded as
a decision in `ai_audit_logs` (glass box). Fail-closed: a missing verdict rejects.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_gateway import CallContext, record_decision_audit
from app.services.capability_runtime import run_capability_json

logger = logging.getLogger(__name__)

VALIDATOR_CAPABILITY = "quiz_validator"
VALIDATOR_FEATURE = "quiz_validator"
CHOICE_KEYS = ("A", "B", "C", "D")
_BEGIN_RE = re.compile(r"\\begin\{([a-zA-Z*]+)\}")
_END_RE = re.compile(r"\\end\{([a-zA-Z*]+)\}")


# ---------------------------------------------------------------------------
# Deterministic checks
# ---------------------------------------------------------------------------
def latex_problems(text: str) -> list[str]:
    """Return LaTeX validity problems for one text block (empty list = valid)."""
    problems: list[str] = []
    if not text:
        return problems
    stripped = text.replace("\\$", "").replace("\\{", "").replace("\\}", "")
    if stripped.count("$") % 2:
        problems.append("delimiter_unbalanced")
    depth = 0
    for char in stripped:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                break
    if depth != 0:
        problems.append("braces_unbalanced")
    begins = _BEGIN_RE.findall(stripped)
    ends = _END_RE.findall(stripped)
    if sorted(begins) != sorted(ends):
        problems.append("environment_unbalanced")
    if stripped.count("\\left") != stripped.count("\\right"):
        problems.append("left_right_unbalanced")
    return problems


def structural_problems(question: dict[str, Any]) -> list[str]:
    """Return structural problems of a candidate question (empty list = sound)."""
    problems: list[str] = []
    prompt = str(question.get("prompt") or "").strip()
    if not prompt:
        problems.append("prompt_empty")
    choices = question.get("choices")
    if not isinstance(choices, dict) or sorted(choices.keys()) != sorted(CHOICE_KEYS):
        problems.append("choices_not_four")
        choices = choices if isinstance(choices, dict) else {}
    texts = [str(choices.get(key) or "").strip() for key in CHOICE_KEYS]
    if any(not text for text in texts):
        problems.append("choice_empty")
    if len({text.lower() for text in texts if text}) != len([t for t in texts if t]):
        problems.append("choices_not_distinct")
    if question.get("correct_option") not in CHOICE_KEYS:
        problems.append("answer_key_invalid")
    if not str(question.get("explanation") or "").strip():
        problems.append("explanation_empty")
    source = question.get("source")
    if not isinstance(source, dict) or source.get("pdf_page_index") is None or source.get("book_id") is None:
        problems.append("source_missing")
    for block in [prompt, *texts, str(question.get("explanation") or "")]:
        if latex_problems(block):
            problems.append("latex_invalid")
            break
    return problems


# ---------------------------------------------------------------------------
# Model verdicts
# ---------------------------------------------------------------------------
@dataclass
class QuestionDecision:
    index: int
    verdict: str  # approved | fixed | rejected
    reasons: list[str]
    question: dict[str, Any] | None
    audit_id: str | None = None


@dataclass
class ValidationOutcome:
    accepted: list[dict[str, Any]]
    decisions: list[QuestionDecision] = field(default_factory=list)
    audit_id: str | None = None


def _parse_verdicts(content: Any) -> dict[int, dict[str, Any]]:
    payload = content
    if not isinstance(payload, dict):
        try:
            payload = json.loads(str(content))
        except (TypeError, ValueError):
            return {}
    rows = payload.get("verdicts") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("index"), int):
            out[row["index"]] = row
    return out


def _model_reasons(verdict: dict[str, Any], correct_option: str) -> list[str]:
    reasons: list[str] = []
    if verdict.get("grounded") is not True:
        reasons.append("ungrounded")
    if verdict.get("unambiguous") is not True:
        reasons.append("ambiguous")
    if verdict.get("latex_ok") is not True:
        reasons.append("latex_model_flag")
    if str(verdict.get("confirmed_option") or "").upper() != correct_option:
        reasons.append("answer_key_mismatch")
    return reasons


def _merge_fix(original: dict[str, Any], fix: dict[str, Any]) -> dict[str, Any]:
    merged = dict(original)
    for key in ("prompt", "choices", "correct_option", "explanation"):
        if key in fix and fix[key] is not None:
            merged[key] = fix[key]
    if isinstance(merged.get("choices"), dict):
        merged["choices"] = {k: str(v) for k, v in merged["choices"].items()}
    merged["correct_option"] = str(merged.get("correct_option") or "").upper()
    return merged


async def validate_questions(
    session: AsyncSession,
    *,
    items: list[dict[str, Any]],
    user_id: str | None,
    book_id: int | None,
    exam_id: str | None = None,
) -> ValidationOutcome:
    """Validate generated questions. `items`: [{"question": {...}, "source_text": str}].

    Returns the accepted questions (renumbering is the caller's job) and one
    decision per input question. Never raises for a bad question: it is rejected.
    """
    if not items:
        return ValidationOutcome(accepted=[])

    lines: list[str] = []
    for index, item in enumerate(items):
        question = item["question"]
        source_text = str(item.get("source_text") or "")[:3000]
        lines.append(
            json.dumps(
                {
                    "index": index,
                    "prompt": question.get("prompt"),
                    "choices": question.get("choices"),
                    "correct_option": question.get("correct_option"),
                    "explanation": question.get("explanation"),
                },
                ensure_ascii=False,
            )
        )
        lines.append(f"متن منبع برای سؤال {index}:\n{source_text}")
    user_text = "سؤال‌ها و منبع‌هایشان:\n" + "\n".join(lines)

    citations = [dict(item["question"].get("source") or {}) for item in items]
    verdicts: dict[int, dict[str, Any]] = {}
    audit_id: str | None = None
    # model_mode: "model" (verdicts from the model), "disabled" (admin turned the
    # validator capability off: deterministic checks only), or "error" (fail closed).
    model_mode = "model"
    try:
        result, _skill = await run_capability_json(
            session=session,
            capability_key=VALIDATOR_CAPABILITY,
            feature_key=VALIDATOR_FEATURE,
            user_text=user_text,
            user_id=user_id,
            book_id=book_id,
            textbook_strict=True,
            citations=citations,
            rag_hit_count=len(items),
            enforce=True,
        )
        verdicts = _parse_verdicts(result.content)
        audit_id = result.audit_id
    except HTTPException as error:
        if error.status_code in (403, 404):
            model_mode = "disabled"
            logger.info("quiz_validator.capability_disabled; deterministic checks only")
        else:
            model_mode = "error"
    except Exception:  # noqa: BLE001 - validator outage must fail closed, not crash generation
        model_mode = "error"
        logger.exception("quiz_validator.model_call_failed; rejecting all candidates")

    # Fail closed: grounding and key confirmation are model checks. Without the model
    # nothing can be verified against the textbook, so no candidate is accepted.
    if model_mode == "disabled":
        await record_decision_audit(
            feature_key=VALIDATOR_FEATURE,
            user_id=user_id,
            session_id=None,
            request_text=f"exam={exam_id} candidates={len(items)}",
            decision={"verdict": "deterministic_only", "exam_id": exam_id},
            flag_reason="validator_model_disabled",
            session=session,
        )

    accepted: list[dict[str, Any]] = []
    decisions: list[QuestionDecision] = []
    for index, item in enumerate(items):
        original = dict(item["question"])
        problems = structural_problems(original)
        verdict_row = verdicts.get(index)
        if model_mode == "disabled":
            reasons = [*problems, "validator_model_disabled"]
            verdict_row = {}
        elif verdict_row is None:
            reasons = [*problems, "validator_missing_verdict"]
            verdict_row = {}
        else:
            reasons = [*problems, *_model_reasons(verdict_row, str(original.get("correct_option") or ""))]

        if not reasons:
            accepted.append(original)
            approved_audit = await record_decision_audit(
                feature_key=VALIDATOR_FEATURE,
                user_id=user_id,
                session_id=None,
                request_text=str(original.get("prompt") or "")[:1500],
                decision={"verdict": "approved", "reasons": [], "exam_id": exam_id, "index": index},
                flag_reason="validator_approved",
                session=session,
            )
            decisions.append(QuestionDecision(index, "approved", [], original, approved_audit or audit_id))
            continue

        repaired: dict[str, Any] | None = None
        fix = verdict_row.get("fix")
        if isinstance(fix, dict) and verdict_row:
            candidate = _merge_fix(original, fix)
            confirmed = str(verdict_row.get("confirmed_option") or "").upper()
            if (
                not structural_problems(candidate)
                and candidate["correct_option"] == confirmed
                and verdict_row.get("grounded") is True
                and verdict_row.get("unambiguous") is True
            ):
                repaired = candidate

        if model_mode == "disabled":
            repaired = None
        if repaired is not None:
            accepted.append(repaired)
            decisions.append(QuestionDecision(index, "fixed", reasons, repaired, audit_id))
            flag = "validator_fixed"
            verdict_name = "fixed"
        else:
            decisions.append(QuestionDecision(index, "rejected", reasons, None, audit_id))
            flag = "validator_rejected"
            verdict_name = "rejected"

        decision_audit = await record_decision_audit(
            feature_key=VALIDATOR_FEATURE,
            user_id=user_id,
            session_id=None,
            request_text=str(original.get("prompt") or "")[:1500],
            decision={"verdict": verdict_name, "reasons": reasons, "exam_id": exam_id, "index": index},
            flag_reason=flag,
            session=session,
        )
        decisions[-1] = QuestionDecision(index, verdict_name, reasons, repaired, decision_audit or audit_id)

    return ValidationOutcome(accepted=accepted, decisions=decisions, audit_id=audit_id)


__all__ = [
    "CallContext",
    "QuestionDecision",
    "ValidationOutcome",
    "latex_problems",
    "structural_problems",
    "validate_questions",
]
