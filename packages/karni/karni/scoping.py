"""Where row scope is switched off: every ``scope_exempt`` viewset and admin, for ``karni check``.

An exemption keeps the request gate (or Django's model permissions, in the
admin) and shows every row it admits. It needs a reason (``E210`` without
one) and ``karni check`` prints the list on every run, so exemptions stay
visible instead of accumulating quietly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["ScopeExemption", "admin_site", "render_exemptions", "scope_exemptions"]


@dataclass(frozen=True)
class ScopeExemption:
    kind: str  # "viewset" or "admin"
    name: str
    reason: str


def admin_site() -> Any:
    """The admin site ``KARNI_ADMIN_SITE`` names (default ``django.contrib.admin.site``)."""
    from django.conf import settings

    from karni.imports import import_setting

    return import_setting(
        "KARNI_ADMIN_SITE", getattr(settings, "KARNI_ADMIN_SITE", "django.contrib.admin.site")
    )


def scope_exemptions() -> list[ScopeExemption]:
    """Every routed viewset and registered Karni admin that sets ``scope_exempt``."""
    from karni.admin.base import KarniAdminMixin
    from karni.api.routers import resolve_router
    from karni.api.viewsets import BaseViewSet

    found: list[ScopeExemption] = []
    seen: set[type[Any]] = set()
    for _prefix, viewset, _basename in getattr(resolve_router(), "registry", ()):
        if viewset in seen or not (isinstance(viewset, type) and issubclass(viewset, BaseViewSet)):
            continue
        seen.add(viewset)
        if getattr(viewset, "scope_exempt", False):
            reason = str(getattr(viewset, "scope_exempt_reason", "") or "").strip()
            found.append(ScopeExemption("viewset", viewset.__name__, reason))
    for model, model_admin in admin_site()._registry.items():
        if isinstance(model_admin, KarniAdminMixin) and getattr(model_admin, "scope_exempt", False):
            reason = str(getattr(model_admin, "scope_exempt_reason", "") or "").strip()
            name = f"{type(model_admin).__name__} ({model._meta.label_lower})"
            found.append(ScopeExemption("admin", name, reason))
    return found


def render_exemptions(found: list[ScopeExemption]) -> str:
    """One line per exemption, for ``karni check``."""
    lines = [f"scope exemptions ({len(found)}): rows unscoped, the gate still applies"]
    for item in found:
        lines.append(f"  {item.kind} {item.name}: {item.reason or '(no reason: E210)'}")
    return "\n".join(lines)
