"""Who to tell, and how: the default notifier emails the checkers.

``KARNI_APPROVALS_NOTIFY`` names the callable the Celery task runs with the
pending change (``""`` turns notification off); replace it to post to chat,
page someone or fan out to several channels. :func:`checkers_for` is the
reusable half: the users who may decide this change, maker excluded.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db.models import Q
from django.utils.module_loading import import_string
from karni.accounts.models import RolePermission

from karni_approvals import conf
from karni_approvals.meta import approval_policy
from karni_approvals.models import PendingChange

__all__ = ["checkers_for", "email_checkers", "email_escalation", "notifier", "users_in_roles"]


def users_in_roles(slugs: Iterable[str]) -> Any:
    """Active users holding any of the roles ``slugs``."""
    return (
        get_user_model()
        ._default_manager.filter(is_active=True, groups__name__in=list(slugs))
        .distinct()
    )


def checkers_for(pending: PendingChange) -> Any:
    """Users who may decide ``pending``: the approver roles, else every role granted approve."""
    model = pending.model_class
    policy = approval_policy(model) if model is not None else None
    if policy is not None and policy.roles:
        users = users_in_roles(policy.roles)
    else:
        slugs = (
            RolePermission.objects.filter(
                permission__content_type__app_label="karni_approvals",
                permission__content_type__model="pendingchange",
                permission__action="approve",
            )
            .exclude(scope="none")
            .values_list("role__slug", flat=True)
        )
        users = (
            get_user_model()
            ._default_manager.filter(
                Q(groups__name__in=list(slugs)) | Q(is_superuser=True), is_active=True
            )
            .distinct()
        )
    if pending.maker_id is not None:
        users = users.exclude(pk=pending.maker_id)
    return users.filter(~Q(email="")).distinct()


def _send(subject: str, body: str, recipients: Iterable[str]) -> int:
    to = [email for email in recipients if email]
    if not to:
        return 0
    sender = conf.get("KARNI_APPROVALS_FROM_EMAIL") or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    return int(send_mail(subject, body, sender, to, fail_silently=False))


def _describe(pending: PendingChange) -> str:
    lines = [f"{pending.get_action_display()}: {pending.summary}", ""]
    for name, change in (pending.changes or {}).items():
        old, new = (
            change if isinstance(change, list | tuple) and len(change) == 2 else (None, change)
        )
        lines.append(f"  {name}: {old!r} -> {new!r}")
    maker = getattr(pending.maker, "email", None) or "someone"
    lines += ["", f"Proposed by {maker}; {pending.required} approval(s) needed."]
    return "\n".join(lines)


def email_checkers(pending: PendingChange) -> int:
    """The default notifier: one email to every checker. Returns the recipient count."""
    recipients = [user.email for user in checkers_for(pending)]
    return _send(f"[Approval needed] {pending.summary}", _describe(pending), recipients)


def email_escalation(pending: PendingChange) -> int:
    """Escalation: email the escalation roles (falls back to the checkers)."""
    model = pending.model_class
    policy = approval_policy(model) if model is not None else None
    roles = policy.escalation_roles if policy is not None else ()
    users = users_in_roles(roles) if roles else checkers_for(pending)
    recipients = [user.email for user in users if user.email]
    return _send(f"[Approval overdue] {pending.summary}", _describe(pending), recipients)


def notifier() -> Any | None:
    """The configured notifier callable, or ``None`` when notification is off."""
    dotted = conf.get("KARNI_APPROVALS_NOTIFY")
    if not dotted:
        return None
    return import_string(dotted) if isinstance(dotted, str) else dotted
