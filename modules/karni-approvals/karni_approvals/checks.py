"""Build-failing checks for ``karni check`` (the ``karni.checks`` entry point)."""

from __future__ import annotations

from karni.exceptions import KarniError

__all__ = ["run_checks"]


def run_checks() -> list[str]:
    """Every guarded model must be a BaseModel with a well-formed policy naming declared roles."""
    from django.apps import apps
    from karni.accounts.roles import declared_roles
    from karni.meta import karni_option
    from karni.models import BaseModel

    from karni_approvals.meta import approval_policy

    failures: list[str] = []
    try:
        slugs = {spec.slug for spec in declared_roles()}
    except KarniError:
        slugs = set()
    for model in apps.get_models():
        if not karni_option(model, "requires_approval", None):
            continue
        label = model._meta.label
        if not issubclass(model, BaseModel):
            failures.append(
                f"{label} declares requires_approval but is not a karni.models.BaseModel, so its "
                "writes send no pre_write signal and are never held (APR007)."
            )
            continue
        try:
            policy = approval_policy(model)
        except KarniError as exc:
            failures.append(str(exc))
            continue
        if policy is None:
            continue
        unknown = sorted(set(policy.roles + policy.escalation_roles) - slugs) if slugs else []
        if unknown:
            failures.append(
                f"{label}: approver/escalation roles not in KARNI_ROLES: "
                f"{', '.join(unknown)} (APR007)."
            )
    return failures
