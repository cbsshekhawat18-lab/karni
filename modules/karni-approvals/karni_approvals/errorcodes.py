"""karni-approvals' error codes (prefix ``APR``), registered with Karni's registry.

Exposed through the ``karni.errorcodes`` entry point, so ``karni explain
APR002`` and ``docs/errors.md`` include them. Codes are permanent: never
renumber or reuse one; append new codes at the end.
"""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["CODES"]

_SOURCE = "karni_approvals"

CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="APR001",
        title="The change was sent for approval instead of being written",
        kind="api",
        source=f"{_SOURCE}.interception",
        why="The model declares requires_approval and the change touches a guarded field, so "
        "a pending change holds it until a second person approves (the API answers 202 "
        "with the pending change; the admin says so; code gets KarniWriteDeferred).",
        fix="Nothing is wrong. Have a checker approve it (the admin queue, "
        "/api/pending-changes/, <ApprovalsQueue/>); trusted code may write inside "
        "karni_approvals.interception.bypass(reason=...).",
    ),
    ErrorCode(
        code="APR002",
        title="The maker cannot be the checker",
        kind="api",
        source=f"{_SOURCE}.services.decide",
        why="Second-person approval means a second person: the user who proposed a change "
        "may never approve or reject it, through the API, the admin or a direct call.",
        fix="Ask another holder of the approve permission to decide it.",
    ),
    ErrorCode(
        code="APR003",
        title="This user may not decide this pending change",
        kind="api",
        source=f"{_SOURCE}.services.decide",
        why="Deciding needs the karni_approvals.pendingchange:approve (or :reject) grant, the "
        "model's approver_roles when it declares them, and the row inside the checker's "
        "own scope.",
        fix="Grant the permission in KARNI_ROLES (or the permission matrix), assign the "
        "approver role, or have someone whose scope covers the row decide.",
    ),
    ErrorCode(
        code="APR004",
        title="This checker has already decided this change",
        kind="api",
        source=f"{_SOURCE}.services.decide",
        why="One decision per person per change; a second one would count twice.",
        fix="Another checker must supply the remaining approvals.",
    ),
    ErrorCode(
        code="APR005",
        title="The pending change is no longer pending",
        kind="api",
        source=f"{_SOURCE}.services.decide",
        why="It was already approved, rejected, expired or failed; decisions are final.",
        fix="Propose the change again if it is still wanted.",
    ),
    ErrorCode(
        code="APR006",
        title="The change could not be applied: the row changed since it was proposed",
        kind="api",
        source=f"{_SOURCE}.services.apply",
        why="Every recorded old value must still be current when the change is applied, or "
        "an approval would overwrite something nobody reviewed.",
        fix="Propose the change again against the row as it is now.",
    ),
    ErrorCode(
        code="APR007",
        title="The model's approval policy is malformed",
        kind="check",
        source=f"{_SOURCE}.meta.approval_policy",
        why="requires_approval, approvals_required, approver_roles, approval_timeout and "
        "approval_on_timeout are read at boot; a typo would silently hold or release changes.",
        fix="requires_approval = True or a list of field names; approvals_required a positive "
        "int; approver_roles / approval_escalation_roles lists of KARNI_ROLES slugs; "
        "approval_timeout a timedelta or hours; approval_on_timeout 'expire' or 'escalate'.",
    ),
)
