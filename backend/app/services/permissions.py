"""Role taxonomy, least-privilege permissions, and administrator actors.

Roles (highest privilege last):

| role         | rank | purpose                                             |
|--------------|------|-----------------------------------------------------|
| `student`    | 10   | learner (default)                                   |
| `guardian`   | 20   | parent/guardian (legacy, read-only learner context) |
| `teacher`    | 30   | staff, student-facing tools                         |
| `moderator`  | 40   | read-only admin: user list, sessions, audit trail   |
| `admin`      | 50   | user administration (never above its own rank)      |
| `super_admin`| 60   | full administration, may mint administrators        |

Rules enforced by `can_*` helpers below (and re-checked in the service layer, never in
the browser alone):

* A non-`super_admin` may never manage, delete, or change the role of an account whose
  role rank is greater than their own.
* Only `super_admin` may grant `super_admin`.
* The legacy shared-password admin session is treated as `admin` (rank 50): it can manage
  learners and staff, but cannot mint or touch `super_admin` accounts.
* The last active `super_admin` can never be demoted, deactivated or deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RoleName = Literal["student", "guardian", "teacher", "moderator", "admin", "super_admin"]

ROLE_RANKS: dict[str, int] = {
    "student": 10,
    "guardian": 20,
    "teacher": 30,
    "moderator": 40,
    "admin": 50,
    "super_admin": 60,
}

# Roles an administrator can assign, ordered for the UI.
ASSIGNABLE_ROLES: tuple[str, ...] = ("student", "teacher", "moderator", "admin", "super_admin")
MAINTAINABLE_ROLES: tuple[str, ...] = ("student", "guardian", "teacher", "moderator", "admin", "super_admin")

ADMIN_ROLES: frozenset[str] = frozenset({"admin", "super_admin"})
STAFF_ROLES: frozenset[str] = frozenset({"teacher", "moderator", "admin", "super_admin"})


def normalize_role(raw: str | None, *, default: str = "student") -> str:
    role = (raw or "").strip().lower()
    return role if role in ROLE_RANKS else default


def role_rank(raw: str | None) -> int:
    return ROLE_RANKS.get(normalize_role(raw), 0)


def is_admin_role(raw: str | None) -> bool:
    return normalize_role(raw, default="") in ADMIN_ROLES


@dataclass(frozen=True)
class AdminActor:
    """The authenticated principal performing an admin action.

    `legacy` marks the shared-password admin session, which has no backing user row and
    therefore no password of its own for re-authentication (it uses `ADMIN_PASSWORD`).
    """

    role: str
    user_id: str | None = None
    legacy: bool = False

    @property
    def rank(self) -> int:
        return role_rank(self.role)

    @property
    def label(self) -> str:
        if self.user_id:
            return f"user:{self.user_id}"
        return "legacy_admin_session"


def can_read_users(actor: AdminActor) -> bool:
    return actor.rank >= ROLE_RANKS["moderator"]


def can_manage_education_catalog(actor: AdminActor) -> bool:
    """True when `actor` may create/edit/delete/archive the national education
    catalog (cycles, grades, branches, grounds, programs, subjects, textbooks,
    editions, links, academic years).

    Deliberately separate from `can_read_users`: reading user FILES is a
    moderator-level capability, but managing the national catalog is admin-only.
    The catalog owner is the admin; a student's own academic placement stays
    student-owned self-service data and is never touched by this permission.
    """
    return actor.rank >= ROLE_RANKS["admin"]


def can_read_audit(actor: AdminActor) -> bool:
    return actor.rank >= ROLE_RANKS["moderator"]


def can_manage_user(actor: AdminActor, target_role: str | None) -> bool:
    """True when `actor` may edit profile/activation/quota of the target account.

    Moderators are read-only by design (least privilege): every write needs `admin`.
    """
    if actor.rank < ROLE_RANKS["admin"]:
        return False
    if actor.role == "super_admin":
        return True
    # An administrator may manage accounts at or below its own rank, but never a
    # super_admin; the legacy admin session is capped the same way.
    return role_rank(target_role) <= actor.rank and role_rank(target_role) < ROLE_RANKS["super_admin"]


def can_delete_user(actor: AdminActor, target_role: str | None) -> bool:
    """Deletion is strictly hierarchical: only a strictly higher rank may delete."""
    if actor.rank < ROLE_RANKS["admin"]:
        return False
    if actor.role == "super_admin":
        return True
    return role_rank(target_role) < actor.rank


def can_assign_role(actor: AdminActor, new_role: str, target_role: str | None = None) -> bool:
    """Prevent privilege escalation: grant only roles at or below the actor's rank.

    A `super_admin` is explicitly allowed to modify other super_admins — including
    demoting the last one, which the service layer still refuses via the
    last-super_admin guard (409, not 403).
    """
    new_rank = role_rank(new_role)
    if new_rank == 0:
        return False
    if target_role is not None and role_rank(target_role) > actor.rank:
        return False
    if actor.role == "super_admin":
        return True
    if role_rank(target_role) >= ROLE_RANKS["super_admin"]:
        return False
    return new_rank <= actor.rank and new_rank < ROLE_RANKS["super_admin"]


def can_create_user_with_role(actor: AdminActor, new_role: str) -> bool:
    return can_assign_role(actor, new_role, target_role=None)


def can_reset_password(actor: AdminActor, target_role: str | None) -> bool:
    return can_manage_user(actor, target_role)


def can_manage_sessions(actor: AdminActor, target_role: str | None) -> bool:
    """Revoking someone else's sessions is a write operation; viewing needs moderator."""
    return can_manage_user(actor, target_role)


def requires_reauth_for_role_change(actor: AdminActor, new_role: str) -> bool:
    return role_rank(new_role) >= ROLE_RANKS["admin"]


def sensitive_operation(*, needs_reauth: bool) -> bool:
    return needs_reauth
