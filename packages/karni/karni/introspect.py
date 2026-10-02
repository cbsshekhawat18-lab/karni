"""Machine-readable project inventory backing ``manage.py karni_context``.

Everything printed is derived from the live Django app registry and router at
call time — nothing is hand-maintained. Override the skip list with the
``KARNI_CONTEXT_SKIP_APPS`` setting (list of app labels).
"""

from __future__ import annotations

import sys
from collections import Counter
from importlib.metadata import packages_distributions

from django.apps import apps
from django.conf import settings
from django.db import models

#: App labels whose models are framework noise, not domain inventory.
CONTEXT_SKIP_APPS: frozenset[str] = frozenset(
    {
        "admin",
        "auth",
        "contenttypes",
        "sessions",
        "sites",
        "django_celery_beat",
        "django_celery_results",
        "token_blacklist",
        "django_otp",
        "otp_totp",
        "account",
        "socialaccount",
        "django_structlog",
        "karni",
        "karni_accounts",
        "karni_admin",
    }
)

#: Audit/base fields never shown, plus user-model internals.
_SKIP_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
        "updated_by",
        "password",
        "last_login",
        "is_superuser",
        "groups",
        "user_permissions",
    }
)

#: Karni base classes, versioned with this package (guarded by an import test).
BASES: tuple[str, ...] = (
    "BaseModel",
    "UUIDModel",
    "TimestampedModel",
    "SoftDeleteModel",
    "AuditedModel",
    "BaseViewSet",
    "KarniModelAdmin",
    "AbstractKarniUser",
)

FIELD_CAP = 4
MODEL_CAP = 40
#: Model names listed per scope in the SCOPES section.
SCOPE_MODEL_CAP = 6


def _skip_apps() -> frozenset[str]:
    override = getattr(settings, "KARNI_CONTEXT_SKIP_APPS", None)
    return frozenset(override) if override is not None else CONTEXT_SKIP_APPS


def _model_fields(model: type[models.Model]) -> list[str]:
    """First FIELD_CAP concrete field names in declaration order, minus audit fields."""
    names = [f.name for f in model._meta.concrete_fields if f.name not in _SKIP_FIELDS]
    return names[:FIELD_CAP]


def _domain_models() -> list[tuple[str, type[models.Model]]]:
    """(display name, model) for every non-skipped model, sorted by app label then name.

    The display name is ``label.Name`` only when two apps share a model name.
    """
    skip = _skip_apps()
    entries: list[tuple[str, str, type[models.Model]]] = []
    for cfg in apps.get_app_configs():
        if cfg.label in skip:
            continue
        for model in cfg.get_models():
            entries.append((cfg.label, model.__name__, model))
    entries.sort(key=lambda e: (e[0], e[1]))
    name_counts = Counter(name for _, name, _ in entries)
    return [
        (f"{label}.{name}" if name_counts[name] > 1 else name, model)
        for label, name, model in entries
    ]


def models_section() -> str | None:
    entries = _domain_models()
    if not entries:
        return None
    parts = [f"{shown}({','.join(_model_fields(model))})" for shown, model in entries[:MODEL_CAP]]
    if len(entries) > MODEL_CAP:
        parts.append(f"+{len(entries) - MODEL_CAP} more")
    return "MODELS: " + " ".join(parts)


def _capped(names: list[str]) -> str:
    shown = ",".join(names[:SCOPE_MODEL_CAP])
    return shown + (f",+{len(names) - SCOPE_MODEL_CAP}" if len(names) > SCOPE_MODEL_CAP else "")


def scopes_section() -> str | None:
    """Model scopes that differ from the default, and how to lift one.

    ``soft_delete`` on every soft-delete model is the documented default and
    is only printed when ``KARNI_SCOPES`` switched it off. Every other active
    scope is printed with the domain models it covers: ``(all)``,
    ``(all except A,B)``, or the covered models when they are the minority.
    """
    from karni.scopes import SOFT_DELETE, registry

    try:
        active = registry.active()
        registered = registry.names()
    except Exception as exc:  # noqa: BLE001 - inventory must degrade, never crash
        sys.stderr.write(f"WARNING: scope inventory unavailable: {exc}\n")
        return None
    entries = _domain_models()
    parts: list[str] = []
    if SOFT_DELETE in registered and all(scope.name != SOFT_DELETE for scope in active):
        parts.append(f"{SOFT_DELETE}(off)")
    for scope in active:
        if scope.name == SOFT_DELETE:
            continue
        covered = [shown for shown, model in entries if scope in registry.for_model(model)]
        skipped = [shown for shown, model in entries if scope not in registry.for_model(model)]
        if not covered:
            continue
        if not skipped:
            parts.append(f"{scope.name}(all)")
        elif len(skipped) <= len(covered):
            parts.append(f"{scope.name}(all except {_capped(skipped)})")
        else:
            parts.append(f"{scope.name}({_capped(covered)})")
    if not parts:
        return None
    return "SCOPES: " + " ".join(parts) + '; lift: objects.without("<scope>", reason=...)'


def viewsets_section() -> str | None:
    """Viewset class names from the configured router; omitted entirely on failure."""
    from django.utils.module_loading import import_string

    try:
        factory = import_string(
            getattr(settings, "KARNI_API_ROUTER", "karni.api.routers.get_default_router")
        )
        router = factory()
        names = sorted({viewset.__name__ for _, viewset, _ in router.registry})
    except Exception as exc:  # noqa: BLE001 - inventory must degrade, never crash
        sys.stderr.write(f"WARNING: viewset inventory unavailable: {exc}\n")
        return None
    return "VIEWSETS: " + " ".join(names) if names else None


def modules_section() -> str | None:
    """Installed optional Karni modules (apps named ``karni_<x>`` at top level)."""
    found: list[str] = []
    for cfg in apps.get_app_configs():
        module = cfg.name
        if "." in module or not module.startswith("karni_"):
            continue
        found.append(module.removeprefix("karni_"))
    return "MODULES: " + " ".join(sorted(found)) if found else None


def module_distribution(module: str) -> str:
    """Distribution that ships ``module`` (metadata first, karni-<x> convention fallback)."""
    dists = packages_distributions().get(module)
    return dists[0] if dists else module.replace("_", "-")


def build_context() -> str:
    """The full inventory, one section per line, empty sections omitted."""
    sections = [
        models_section(),
        scopes_section(),
        viewsets_section(),
        modules_section(),
        "BASES: " + " ".join(BASES),
    ]
    return "\n".join(s for s in sections if s)
