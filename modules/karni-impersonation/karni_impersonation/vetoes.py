"""The veto: while impersonating, the blocked list wins over anything the target holds."""

from __future__ import annotations

from karni.vetoes import VetoContext

from karni_impersonation import services

__all__ = ["BLOCKED_CODE", "blocked_while_impersonating"]

BLOCKED_CODE = "IMP006"


def blocked_while_impersonating(context: VetoContext) -> str | None:
    """``karni.vetoes`` hook: refuse actions on ``KARNI_IMPERSONATION_BLOCKED`` during a session."""
    session = services.current()
    if session is None:
        return None
    pattern = services.is_blocked(context.names())
    if pattern is None:
        return None
    return (
        f"{BLOCKED_CODE}: {context.action} is blocked while impersonating "
        f"({services._email(session.actor)} acting as {services._email(session.target)}, "
        f"pattern {pattern!r})."
    )
