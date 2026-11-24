"""Governance tests for preserving versioned learning-objective identity and edges."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.admin import (
    _prerequisite_scope_is_compatible,
    _validate_objective_unit_reuse,
)


def _unit(
    *,
    unit_id: int,
    grade_id: int = 10,
    academic_year_id: int | None = 7,
    scope_code: str = "1405-1406",
    branch_id: int | None = 1,
    field_of_study_id: int | None = 11,
):
    return SimpleNamespace(
        id=unit_id,
        grade_id=grade_id,
        academic_year_id=academic_year_id,
        scope_code=scope_code,
        branch_id=branch_id,
        field_of_study_id=field_of_study_id,
    )


def test_objective_reimport_must_keep_same_unit_identity():
    unit = _unit(unit_id=1)

    _validate_objective_unit_reuse(unit, unit)

    with pytest.raises(HTTPException) as error:
        _validate_objective_unit_reuse(_unit(unit_id=2), unit)

    assert error.value.status_code == 409


def test_missing_existing_objective_unit_is_not_silently_repaired_by_reparenting():
    with pytest.raises(HTTPException) as error:
        _validate_objective_unit_reuse(None, _unit(unit_id=1))

    assert error.value.status_code == 409


def test_specific_objective_can_depend_on_shared_same_year_curriculum():
    objective = _unit(unit_id=1, branch_id=1, field_of_study_id=11)
    shared_prerequisite = _unit(
        unit_id=2,
        branch_id=None,
        field_of_study_id=None,
    )

    assert _prerequisite_scope_is_compatible(objective, shared_prerequisite)


@pytest.mark.parametrize(
    ("objective", "prerequisite"),
    [
        # A field-specific prerequisite cannot unlock a branch-wide objective.
        (_unit(unit_id=1, field_of_study_id=None), _unit(unit_id=2, field_of_study_id=11)),
        # Prerequisites cannot cross branches or fields.
        (_unit(unit_id=1, branch_id=1), _unit(unit_id=2, branch_id=2, field_of_study_id=22)),
        (_unit(unit_id=1, field_of_study_id=11), _unit(unit_id=2, field_of_study_id=12)),
        # Grade and academic-year versions are strict boundaries.
        (_unit(unit_id=1, grade_id=11), _unit(unit_id=2, grade_id=10)),
        (_unit(unit_id=1, academic_year_id=8, scope_code="1406-1407"),
         _unit(unit_id=2, academic_year_id=7, scope_code="1405-1406")),
        # A version-specific prerequisite cannot gate a generic objective.
        (_unit(unit_id=1, academic_year_id=None, scope_code="unspecified"),
         _unit(unit_id=2, academic_year_id=7, scope_code="1405-1406")),
    ],
)
def test_prerequisites_cannot_cross_curriculum_scope(objective, prerequisite):
    assert not _prerequisite_scope_is_compatible(objective, prerequisite)
