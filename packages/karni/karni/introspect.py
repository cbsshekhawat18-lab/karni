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
        "karni_audit",
        "karni_transfer",
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


def _routed_viewsets() -> list[type]:
    from django.utils.module_loading import import_string

    factory = import_string(
        getattr(settings, "KARNI_API_ROUTER", "karni.api.routers.get_default_router")
    )
    seen: dict[type, None] = {}
    for _, viewset, _ in factory().registry:
        seen.setdefault(viewset, None)
    return list(seen)


def performance_section() -> str | None:
    """Declared performance exceptions (ADR 0001 §3.4), so an agent sees them first.

    Relaxed query budgets, unpaginated viewsets, cache opt-outs and
    ``optimize = False`` — each with its reason. Omitted when there are none
    (or the router cannot be built).
    """
    from karni.api.caching import Uncached
    from karni.pagination import UnpaginatedPagination

    try:
        viewsets = _routed_viewsets()
    except Exception:  # noqa: BLE001 - inventory must degrade, never crash
        return None
    parts: list[str] = []
    for viewset in sorted(viewsets, key=lambda cls: cls.__name__):
        notes: list[str] = []
        budget = getattr(viewset, "query_budget", None)
        if budget is not None:
            notes.append(f"budget({budget.describe()}: {budget.reason})")
        paginator = getattr(viewset, "pagination_class", None)
        if isinstance(paginator, type) and issubclass(paginator, UnpaginatedPagination):
            notes.append(f"unpaginated({paginator.max_rows}: {paginator.reason})")
        cache = getattr(viewset, "cache", None)
        if isinstance(cache, Uncached):
            notes.append(f"uncached({cache.reason})")
        if getattr(viewset, "optimize", True) is False:
            notes.append("optimize=False")
        if notes:
            parts.append(f"{viewset.__name__} " + " ".join(notes))
    return "PERF: " + "; ".join(parts) if parts else None


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


ROLE_CAP = 8
GRANT_CAP = 3


def roles_section() -> str | None:
    """``KARNI_ROLES`` in one line: each role with its grant patterns and scopes.

    ``ROLES: staff[*=all] manager[shop.order:*=related:branch]`` — the
    patterns as declared (not expanded), capped per role; a ``system`` role
    is marked ``!``. Models with extra actions follow as ``ACTIONS:``.
    """
    from karni.accounts.roles import declared_roles
    from karni.meta import karni_option

    try:
        specs = declared_roles()
    except Exception as exc:  # noqa: BLE001 - inventory must degrade, never crash
        sys.stderr.write(f"WARNING: role inventory unavailable: {exc}\n")
        return None
    if not specs:
        return None
    parts = []
    for spec in specs[:ROLE_CAP]:
        grants = [f"{pattern}={scope}" for pattern, scope in spec.grants.items()]
        shown = ",".join(grants[:GRANT_CAP])
        if len(grants) > GRANT_CAP:
            shown += f",+{len(grants) - GRANT_CAP}"
        parts.append(f"{spec.slug}{'!' if spec.system else ''}[{shown}]")
    if len(specs) > ROLE_CAP:
        parts.append(f"+{len(specs) - ROLE_CAP} more")
    line = "ROLES: " + " ".join(parts)
    actions = [
        f"{shown}({','.join(extra)})"
        for shown, model in _domain_models()
        if (extra := [a for a in (karni_option(model, "actions", ()) or ())])
    ]
    if actions:
        line += "\nACTIONS: " + " ".join(actions)
    return line


VISIBILITY_CAP = 6


def visibility_section() -> str | None:
    """Models with ``Karni.field_roles``: which fields only some roles see (ADR 0002, P3)."""
    from karni.meta import field_roles

    parts: list[str] = []
    for shown, model in _domain_models():
        try:
            rules = field_roles(model)
        except Exception:  # noqa: BLE001 - inventory must degrade, never crash
            continue
        if not rules:
            continue
        fields = [f"{name}:{','.join(rule.read)}" for name, rule in rules.items()]
        extra = f",+{len(fields) - VISIBILITY_CAP}" if len(fields) > VISIBILITY_CAP else ""
        parts.append(f"{shown}({'; '.join(fields[:VISIBILITY_CAP])}{extra})")
    return "VISIBILITY: " + " ".join(parts) if parts else None


def build_context() -> str:
    """The full inventory, one section per line, empty sections omitted."""
    sections = [
        models_section(),
        scopes_section(),
        viewsets_section(),
        roles_section(),
        visibility_section(),
        performance_section(),
        modules_section(),
        "BASES: " + " ".join(BASES),
    ]
    return "\n".join(s for s in sections if s)
