"""karni-impersonation's error codes (prefix ``IMP``), registered with Karni's registry."""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["CODES"]

_SOURCE = "karni_impersonation"

CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="IMP001",
        title="Impersonation needs the explicit impersonate permission",
        kind="api",
        source=f"{_SOURCE}.services.start",
        why=(
            "Staff or admin status never implies the right to act as someone else. Only a role "
            "granted karni_impersonation.impersonationsession:impersonate may start a session."
        ),
        fix="Grant the permission to the support role in KARNI_ROLES (or the permission matrix).",
    ),
    ErrorCode(
        code="IMP002",
        title="The target holds something the impersonator does not",
        kind="api",
        source=f"{_SOURCE}.services.privilege_gap",
        why="Impersonation must never escalate privileges: a target who is a superuser, is staff, "
        "or holds any grant or Django permission the impersonator lacks cannot be impersonated.",
        fix="Impersonate from an account that holds at least everything the target holds, or "
        "ask such a person to.",
    ),
    ErrorCode(
        code="IMP003",
        title="A reason is required to impersonate",
        kind="api",
        source=f"{_SOURCE}.services.start",
        why="KARNI_IMPERSONATION_REQUIRE_REASON is on (the default for customer data): the reason "
        "is recorded with the session and sent to the impersonated user.",
        fix="Give a reason, or set KARNI_IMPERSONATION_REQUIRE_REASON = False for a project "
        "that does not need one.",
    ),
    ErrorCode(
        code="IMP004",
        title="This user cannot be impersonated now",
        kind="api",
        source=f"{_SOURCE}.services.start",
        why="You cannot impersonate yourself or an inactive account, or start a second session "
        "while one is running.",
        fix="Stop the current session first, or pick another user.",
    ),
    ErrorCode(
        code="IMP005",
        title="This request is not part of an impersonated session",
        kind="api",
        source=f"{_SOURCE}.viewsets.ImpersonationSessionViewSet.stop",
        why=(
            "stop/ ends the session the request belongs to, and there is none (it ended, expired "
            "or never started)."
        ),
        fix="Nothing to do: you are yourself.",
    ),
    ErrorCode(
        code="IMP006",
        title="This action is blocked while impersonating",
        kind="api",
        source=f"{_SOURCE}.vetoes, {_SOURCE}.middleware",
        why="KARNI_IMPERSONATION_BLOCKED names what an impersonator may never do (deleting, "
        "exporting, payment changes, credential changes by default), whatever the target may.",
        fix=(
            "Stop impersonating and do it as yourself, or ask the user to. A project narrows the "
            "list in KARNI_IMPERSONATION_BLOCKED."
        ),
    ),
    ErrorCode(
        code="IMP007",
        title="karni-impersonation is installed but not wired",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "The middleware resolves the impersonated session, enforces the limit and injects the "
            "banner. The URL include serves the banner's exit. Without them sessions start but "
            "nothing acts on them."
        ),
        fix="Add 'karni_impersonation.middleware.ImpersonationMiddleware' after "
        "AuthenticationMiddleware in MIDDLEWARE and "
        "path('impersonation/', include('karni_impersonation.urls')) to config/urls.py.",
    ),
    ErrorCode(
        code="IMP008",
        title="KARNI_IMPERSONATION_BLOCKED is malformed",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "The blocked list is matched on every gate, so a non-string entry would silently "
            "match nothing."
        ),
        fix="Use strings: action names, 'app.model', 'app.model:action' patterns, or '/path/*'.",
    ),
)
