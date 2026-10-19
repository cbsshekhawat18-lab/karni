"""Tell the impersonated user: who, why, when, and how long at most."""

from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail

from karni_impersonation import conf
from karni_impersonation.models import ImpersonationSession

__all__ = ["email_target"]


def email_target(session: ImpersonationSession) -> int:
    """The default notification: one email to the target. Returns the recipient count."""
    email = str(getattr(session.target, "email", "") or "")
    if not email:
        return 0
    actor = str(getattr(session.actor, "email", "") or session.actor.get_username())
    body = "\n".join(
        [
            f"{actor} accessed your account at {session.started_at:%Y-%m-%d %H:%M %Z}.",
            "",
            f"Reason: {session.reason or '(none given)'}",
            f"The session ends by {session.expires_at:%Y-%m-%d %H:%M %Z} at the latest.",
            "",
            "If you did not expect this, contact your administrator.",
        ]
    )
    sender = conf.get("KARNI_IMPERSONATION_FROM_EMAIL") or getattr(
        settings, "DEFAULT_FROM_EMAIL", None
    )
    return int(
        send_mail(
            "Your account was accessed by support", body, sender, [email], fail_silently=False
        )
    )
