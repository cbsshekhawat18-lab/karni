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
    "SoftDeleteModel",
    "BaseViewSet",
    "KarniModelAdmin",
    "AbstractKarniUser",
)

FIELD_CAP = 4
MODEL_CAP = 40


def _skip_apps() -> frozenset[str]:
    override = getattr(settings, "KARNI_CONTEXT_SKIP_APPS", None)
    return frozenset(override) if override is not None else CONTEXT_SKIP_APPS


def _model_fields(model: type[models.Model]) -> list[str]:
    """First FIELD_CAP concrete field names in declaration order, minus audit fields."""
    names = [f.name for f in model._meta.concrete_fields if f.name not in _SKIP_FIELDS]
    return names[:FIELD_CAP]


def models_section() -> str | None:
    skip = _skip_apps()
    entries: list[tuple[str, str, type[models.Model]]] = []
    for cfg in apps.get_app_configs():
        if cfg.label in skip:
            continue
        for model in cfg.get_models():
            entries.append((cfg.label, model.__name__, model))
    if not entries:
        return None
    entries.sort(key=lambda e: (e[0], e[1]))
    name_counts = Counter(name for _, name, _ in entries)
    parts: list[str] = []
    for label, name, model in entries[:MODEL_CAP]:
        shown = f"{label}.{name}" if name_counts[name] > 1 else name
        parts.append(f"{shown}({','.join(_model_fields(model))})")
    if len(entries) > MODEL_CAP:
        parts.append(f"+{len(entries) - MODEL_CAP} more")
    return "MODELS: " + " ".join(parts)


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
        viewsets_section(),
        modules_section(),
        "BASES: " + " ".join(BASES),
    ]
    return "\n".join(s for s in sections if s)
