"""Machine-readable project inventory backing ``manage.py karni_context``.

Everything printed is derived from the live Django app registry and router at
call time — nothing is hand-maintained. Override the skip list with the
``KARNI_CONTEXT_SKIP_APPS`` setting (list of app labels).

Slices (experimental) let an agent read one area of a large project at a
time: :func:`summary_context` prints one line per app,
:func:`app_context` one app in full (every model, its relations in and
out, its viewsets with their routes and access) and :func:`model_context`
one model in depth (every field, the relations that point at it, its
viewsets). Unknown names raise :class:`ContextSliceError` (``E470``) with
the names that exist.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from difflib import get_close_matches
from importlib.metadata import packages_distributions
from typing import Any

from django.apps import apps
from django.conf import settings
from django.db import models

from karni.errorcodes import KarniError

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
    "BigIntBaseModel",
    "UUIDModel",
    "IntegerKeyModel",
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


def key_type(model: type[models.Model]) -> str:
    """The primary key's type in a word: ``uuid``, ``bigint``, ``int``, ``str`` or the field's."""
    pk = model._meta.pk
    if isinstance(pk, models.OneToOneField) and pk.related_model is not None:
        return key_type(pk.related_model)  # a multi-table child shares its parent's key
    if isinstance(pk, models.UUIDField):
        return "uuid"
    if isinstance(pk, models.BigAutoField | models.BigIntegerField):
        return "bigint"
    if isinstance(pk, models.AutoField | models.IntegerField):
        return "int"
    if isinstance(pk, models.CharField):
        return "str"
    return pk.get_internal_type().removesuffix("Field").lower() if pk is not None else "none"


def keys_section() -> str | None:
    """Each domain model's primary-key type: ``KEYS: uuid(all)``, or the exceptions named.

    The most common type is printed as ``(all)`` or ``(rest)``, every other
    type with its models, so each model's key type is stated in one short line.
    """
    entries = _domain_models()
    if not entries:
        return None
    groups: dict[str, list[str]] = {}
    for shown, model in entries:
        groups.setdefault(key_type(model), []).append(shown)
    common = max(groups, key=lambda name: (len(groups[name]), name == "uuid"))
    parts = [
        f"{name}({','.join(models_[:MODEL_CAP])}"
        + (f",+{len(models_) - MODEL_CAP}" if len(models_) > MODEL_CAP else "")
        + ")"
        for name, models_ in sorted(groups.items())
        if name != common
    ]
    parts.append(f"{common}({'rest' if parts else 'all'})")
    return "KEYS: " + " ".join(parts)


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

    Relaxed query budgets, unpaginated viewsets, cache opt-outs,
    ``optimize = False`` and the scaling declarations (``query_scaling``,
    experimental) — each with its reason or numbers. Omitted when there are none
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
        scaling = getattr(viewset, "query_scaling", None)
        if scaling is not None and hasattr(scaling, "describe"):
            notes.append(f"scaling({scaling.describe()})")
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


def features_section() -> str | None:
    """Experimental. The built-in features that are on (``FEATURES: two_factor terms``).

    A feature is on when the setting its manifest names as the switch
    (:func:`karni.catalog.features`) holds a value. ``none`` when none is on,
    so ``karni context`` can tell an older karni (no line) from no feature.
    """
    from karni.catalog import ManifestError, features

    try:
        found = features()
    except ManifestError as exc:  # inventory must degrade, never crash
        sys.stderr.write(f"WARNING: feature inventory unavailable: {exc}\n")
        return None
    on = [manifest.name for manifest in found if getattr(settings, manifest.switch, None)]
    return "FEATURES: " + (" ".join(on) if on else "none")


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


def visibility_section(only: Iterable[type[models.Model]] | None = None) -> str | None:
    """Models with ``Karni.field_roles``: which fields only some roles see (ADR 0002, P3).

    ``only`` (experimental) limits the line to those models.
    """
    from karni.meta import field_roles

    chosen = set(only) if only is not None else None
    parts: list[str] = []
    for shown, model in _domain_models():
        if chosen is not None and model not in chosen:
            continue
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
        keys_section(),
        scopes_section(),
        viewsets_section(),
        roles_section(),
        visibility_section(),
        performance_section(),
        features_section(),
        modules_section(),
        "BASES: " + " ".join(BASES),
    ]
    return "\n".join(s for s in sections if s)


# slices (experimental): one area of a large project at a time

#: Fields listed per model in an app slice (a model slice lists every field).
APP_FIELD_CAP = 12
#: Model names listed per app in the summary.
SUMMARY_MODEL_CAP = 20
#: Choices listed per field in a model slice.
CHOICE_CAP = 6


class ContextSliceError(KarniError):
    """Experimental. ``--app`` or ``--model`` names nothing in the project (``E470``, ``E471``)."""


def _display_names() -> dict[type[models.Model], str]:
    return {model: shown for shown, model in _domain_models()}


def _shown(model: Any, names: dict[type[models.Model], str]) -> str:
    """A model's display name: the inventory's, else ``app_label.Name``."""
    if model in names:
        return names[model]
    meta = getattr(model, "_meta", None)
    return meta.label if meta is not None else str(model)


def _model_fields_capped(model: type[models.Model], cap: int) -> list[str]:
    names = [f.name for f in model._meta.concrete_fields if f.name not in _SKIP_FIELDS]
    if len(names) > cap:
        return [*names[:cap], f"+{len(names) - cap}"]
    return names


def _viewset_routes() -> list[tuple[str, type, Any]]:
    """``(route prefix, viewset, model)`` of every routed viewset (``[]`` without a router)."""
    from django.utils.module_loading import import_string

    try:
        factory = import_string(
            getattr(settings, "KARNI_API_ROUTER", "karni.api.routers.get_default_router")
        )
        registry = list(factory().registry)
    except Exception as exc:  # noqa: BLE001 - inventory must degrade, never crash
        sys.stderr.write(f"WARNING: viewset inventory unavailable: {exc}\n")
        return []
    found = []
    for prefix, viewset, _basename in registry:
        model = getattr(viewset, "model", None)
        if model is None:
            model = getattr(getattr(viewset, "queryset", None), "model", None)
        found.append((prefix, viewset, model))
    return found


def _access_text(viewset: type) -> str:
    """``read=Public() write=HasRole('staff')``: the declared access, in one short phrase."""
    declared = getattr(viewset, "access", None)
    read = getattr(declared, "read", None)
    write = getattr(declared, "write", None)
    if read is None or write is None:
        return repr(declared) if declared is not None else "access missing"
    text = f"read={read!r} write={write!r}"
    create = getattr(declared, "create", None)
    if create is not None and create is not write:
        text += f" create={create!r}"
    return text


def _viewset_text(prefix: str, viewset: type, with_search: bool = False) -> str:
    parts = [prefix, _access_text(viewset)]
    search = [str(name) for name in getattr(viewset, "search_fields", None) or ()]
    if with_search and search:
        parts.append("search=" + ",".join(search))
    return f"{viewset.__name__}({' '.join(parts)})"


_PAGE_SUFFIXES = (".tsx", ".ts", ".jsx", ".js")
#: Page names an entity's pages take (``karni make model -a``, ``karni build``): kebab + suffix.
_PAGE_KINDS = ("", "-detail", "-form", "-list", "-edit", "-new", "-create")


def _page_files() -> list[str]:
    """Every page under ``frontend/src/pages/``, as ``karni/product-detail`` (no suffix)."""
    from karni.testing._source import project_root

    pages = project_root() / "frontend" / "src" / "pages"
    if not pages.is_dir():
        return []
    return sorted(
        path.relative_to(pages).with_suffix("").as_posix()
        for path in pages.rglob("*")
        if path.suffix in _PAGE_SUFFIXES and not path.name.endswith((".test.tsx", ".test.ts"))
    )


def _model_pages(model: type[models.Model], pages: list[str]) -> list[str]:
    """The pages of ``model``: named after its route (``products``) or its kebab name and a kind."""
    from karni.api.routers import default_route, kebab

    stem = kebab(model.__name__)
    names = {default_route(model), *(stem + kind for kind in _PAGE_KINDS)}
    return [page for page in pages if page.rsplit("/", 1)[-1] in names]


def _app_entries(label: str) -> list[tuple[str, type[models.Model]]]:
    return [(shown, model) for shown, model in _domain_models() if model._meta.app_label == label]


def resolve_apps(labels: Iterable[str]) -> list[str]:
    """Experimental. The app labels of ``labels``, each checked against the inventory.

    :raises ContextSliceError: ``E470`` for a label with no model in the inventory.
    """
    known = sorted({model._meta.app_label for _, model in _domain_models()})
    found: list[str] = []
    for label in labels:
        if label not in known:
            close = get_close_matches(label, known, n=3)
            hint = f" Did you mean {' or '.join(close)}?" if close else ""
            raise ContextSliceError(
                f"--app {label}: no app with models has that label.{hint} The apps: "
                f"{', '.join(known) or 'none'}. karni context --summary lists them.",
                code="E470",
            )
        if label not in found:
            found.append(label)
    return found


def resolve_models(names: Iterable[str]) -> list[type[models.Model]]:
    """Experimental. The models ``names`` mean: ``Name``, ``app_label.Name`` or a display name.

    :raises ContextSliceError: ``E470`` for a name that matches no model,
        ``E471`` for a bare name two apps share.
    """
    entries = _domain_models()
    found: list[type[models.Model]] = []
    for name in names:
        lowered = name.lower()
        matches = [
            model
            for shown, model in entries
            if lowered in (shown.lower(), model._meta.label_lower, model.__name__.lower())
        ]
        if not matches:
            known = sorted({model.__name__ for _, model in entries})
            close = get_close_matches(name.rsplit(".", 1)[-1], known, n=3)
            hint = f" Did you mean {' or '.join(close)}?" if close else ""
            raise ContextSliceError(
                f"--model {name}: no model has that name.{hint} karni context --summary "
                "lists the models of each app.",
                code="E470",
            )
        if len(matches) > 1:
            labels = ", ".join(sorted(model._meta.label for model in matches))
            raise ContextSliceError(
                f"--model {name} names {labels}: write app_label.Model.", code="E471"
            )
        if matches[0] not in found:
            found.append(matches[0])
    return found


def summary_context() -> str:
    """Experimental. ``SUMMARY:`` with the totals, then one ``APP <label>:`` line per app.

    Each app line has its model count and names (capped at
    :data:`SUMMARY_MODEL_CAP`), its viewset count and its page count (the
    pages under ``frontend/src/pages/`` named after one of its models).
    """
    entries = _domain_models()
    by_app: dict[str, list[str]] = {}
    for shown, model in entries:
        by_app.setdefault(model._meta.app_label, []).append(shown)
    pages = _page_files()
    page_counts: Counter[str] = Counter(
        model._meta.app_label for _, model in entries for _page in _model_pages(model, pages)
    )
    viewsets: Counter[str] = Counter()
    seen: set[type] = set()
    for _prefix, viewset, model in _viewset_routes():
        if viewset in seen or model is None:
            continue
        seen.add(viewset)
        viewsets[model._meta.app_label] += 1
    lines = [
        f"SUMMARY: {len(by_app)} apps, {len(entries)} models, {len(seen)} viewsets. "
        "One app: karni context --app <label>. One model: karni context --model <name>."
    ]
    for label in sorted(by_app):
        names = by_app[label]
        shown = " ".join(names[:SUMMARY_MODEL_CAP])
        if len(names) > SUMMARY_MODEL_CAP:
            shown += f" +{len(names) - SUMMARY_MODEL_CAP}"
        count, page_count = viewsets[label], page_counts[label]
        lines.append(
            f"APP {label}: {len(names)} model{'s' if len(names) != 1 else ''} ({shown}), "
            f"{count} viewset{'s' if count != 1 else ''}, "
            f"{page_count} page{'s' if page_count != 1 else ''}"
        )
    return "\n".join(lines)


def _relations_line(chosen: list[type[models.Model]]) -> str | None:
    """``RELATIONS:`` the relations out of the chosen models, then ``in:`` those into them."""
    names = _display_names()
    members = set(chosen)
    out: list[str] = []
    for model in chosen:
        for relation in [*model._meta.concrete_fields, *model._meta.many_to_many]:
            target = relation.related_model
            if not relation.is_relation or target is None or relation.name in _SKIP_FIELDS:
                continue
            out.append(f"{_shown(model, names)}.{relation.name}->{_shown(target, names)}")
    incoming: list[str] = []
    for _shown_name, model in _domain_models():
        if model in members:
            continue
        for relation in [*model._meta.concrete_fields, *model._meta.many_to_many]:
            if relation.is_relation and relation.related_model in members:
                incoming.append(
                    f"{_shown(model, names)}.{relation.name}->"
                    f"{_shown(relation.related_model, names)}"
                )
    if not out and not incoming:
        return None
    line = "RELATIONS: " + (" ".join(out) if out else "none out")
    if incoming:
        line += "; in: " + " ".join(incoming)
    return line


def _routed_for(chosen: set[type[models.Model]]) -> list[tuple[str, type]]:
    seen: set[type] = set()
    found = []
    for prefix, viewset, model in _viewset_routes():
        if model in chosen and viewset not in seen:
            seen.add(viewset)
            found.append((prefix, viewset))
    return sorted(found, key=lambda item: item[1].__name__)


def _perf_for(viewsets: set[type]) -> str | None:
    line = performance_section()
    if not line:
        return None
    names = {viewset.__name__ for viewset in viewsets}
    parts = [
        part for part in line.removeprefix("PERF: ").split("; ") if part.split(" ")[0] in names
    ]
    return "PERF: " + "; ".join(parts) if parts else None


def _scopes_for(chosen: list[type[models.Model]]) -> str | None:
    """``SCOPES:`` each chosen model's active scopes, ``soft_delete`` aside (the default)."""
    from karni.scopes import SOFT_DELETE, registry

    names = _display_names()
    parts = []
    try:
        if SOFT_DELETE in registry.names() and all(
            scope.name != SOFT_DELETE for scope in registry.active()
        ):
            parts.append(f"{SOFT_DELETE}(off)")
        for model in chosen:
            scopes = sorted(
                scope.name for scope in registry.for_model(model) if scope.name != SOFT_DELETE
            )
            if scopes:
                parts.append(f"{_shown(model, names)}({','.join(scopes)})")
    except Exception as exc:  # noqa: BLE001 - inventory must degrade, never crash
        sys.stderr.write(f"WARNING: scope inventory unavailable: {exc}\n")
        return None
    if not parts:
        return None
    return "SCOPES: " + " ".join(parts) + '; lift: objects.without("<scope>", reason=...)'


def _roles_for(chosen: list[type[models.Model]]) -> list[str]:
    """``ROLES:`` and ``ACTIONS:`` cut to the grants that can reach the chosen models."""
    from fnmatch import fnmatch

    from karni.accounts.roles import declared_roles
    from karni.meta import karni_option

    try:
        specs = declared_roles()
    except Exception as exc:  # noqa: BLE001 - inventory must degrade, never crash
        sys.stderr.write(f"WARNING: role inventory unavailable: {exc}\n")
        return []
    targets = [f"{model._meta.app_label}.{model._meta.model_name}" for model in chosen]
    parts = []
    for spec in specs:
        grants = [
            f"{pattern}={scope}"
            for pattern, scope in spec.grants.items()
            if any(fnmatch(target, pattern.split(":", 1)[0]) for target in targets)
        ]
        if grants:
            parts.append(f"{spec.slug}{'!' if spec.system else ''}[{','.join(grants)}]")
    lines = ["ROLES: " + " ".join(parts)] if parts else []
    names = _display_names()
    actions = [
        f"{_shown(model, names)}({','.join(extra)})"
        for model in chosen
        if (extra := [a for a in (karni_option(model, "actions", ()) or ())])
    ]
    if actions:
        lines.append("ACTIONS: " + " ".join(actions))
    return lines


def app_context(labels: Sequence[str]) -> str:
    """Experimental. One area of the project: every model of ``labels`` and what touches them.

    ``MODELS`` (up to :data:`APP_FIELD_CAP` fields each), ``KEYS``,
    ``RELATIONS`` (out of the apps, then ``in:`` from other apps),
    ``SCOPES``, ``VIEWSETS`` with their route and access, ``ROLES`` and
    ``ACTIONS`` that reach the models, ``VISIBILITY``, ``PERF``, ``PAGES``
    (the pages named after the models) and ``BASES``.

    :raises ContextSliceError: for a label with no model (:func:`resolve_apps`).
    """
    chosen_labels = resolve_apps(labels)
    entries = [entry for label in chosen_labels for entry in _app_entries(label)]
    chosen = [model for _, model in entries]
    models_line = "MODELS: " + " ".join(
        f"{shown}({','.join(_model_fields_capped(model, APP_FIELD_CAP))})"
        for shown, model in entries
    )
    groups: dict[str, list[str]] = {}
    for shown, model in entries:
        groups.setdefault(key_type(model), []).append(shown)
    keys = "KEYS: " + " ".join(
        f"{name}({','.join(found)})" if len(groups) > 1 else f"{name}(all)"
        for name, found in sorted(groups.items())
    )
    routed = _routed_for(set(chosen))
    viewsets = (
        "VIEWSETS: " + " ".join(_viewset_text(prefix, viewset) for prefix, viewset in routed)
        if routed
        else None
    )
    sections = [
        models_line,
        keys,
        _relations_line(chosen),
        _scopes_for(chosen),
        viewsets,
        *_roles_for(chosen),
        visibility_section(chosen),
        _perf_for({viewset for _, viewset in routed}),
        _pages_line(chosen),
        "BASES: " + " ".join(BASES),
    ]
    return "\n".join(s for s in sections if s)


def _pages_line(chosen: list[type[models.Model]]) -> str | None:
    pages = _page_files()
    found = [page for model in chosen for page in _model_pages(model, pages)]
    return "PAGES: " + " ".join(dict.fromkeys(found)) if found else None


def field_text(field: Any, names: dict[type[models.Model], str] | None = None) -> str:
    """Experimental. A field in the spec's words: ``str:200``, ``fk:Category``, ``decimal:10,2?``.

    ``?`` marks an optional field (null or blank), ``unique`` a unique one,
    ``choices(a,b)`` the stored values of a field with choices. ``names`` maps
    models to their display names (default: the inventory's).
    """
    names = _display_names() if names is None else names
    if field.many_to_many:
        text = f"m2m:{_shown(field.related_model, names)}"
    elif field.one_to_one and field.related_model is not None:
        text = f"o2o:{_shown(field.related_model, names)}"
    elif field.is_relation and field.related_model is not None:
        text = f"fk:{_shown(field.related_model, names)}"
    elif isinstance(field, models.DecimalField):
        text = f"decimal:{field.max_digits},{field.decimal_places}"
    elif isinstance(field, models.SlugField | models.EmailField | models.URLField):
        text = field.get_internal_type().removesuffix("Field").lower()
    elif isinstance(field, models.CharField):
        text = f"str:{field.max_length}" if field.max_length else "str"
    else:
        text = {
            "TextField": "text",
            "IntegerField": "int",
            "SmallIntegerField": "int",
            "PositiveIntegerField": "int",
            "PositiveSmallIntegerField": "int",
            "BigIntegerField": "bigint",
            "PositiveBigIntegerField": "bigint",
            "BooleanField": "bool",
            "FloatField": "float",
            "DateField": "date",
            "DateTimeField": "datetime",
            "TimeField": "time",
            "DurationField": "duration",
            "UUIDField": "uuid",
            "JSONField": "json",
            "FileField": "file",
            "ImageField": "image",
        }.get(field.get_internal_type(), field.get_internal_type().removesuffix("Field").lower())
    if getattr(field, "null", False) or getattr(field, "blank", False):
        text += "?"
    if getattr(field, "unique", False) and not field.primary_key:
        text += " unique"
    choices = getattr(field, "choices", None)
    if choices:
        values = [str(value) for value, _label in field.flatchoices]
        extra = f",+{len(values) - CHOICE_CAP}" if len(values) > CHOICE_CAP else ""
        text += f" choices({','.join(values[:CHOICE_CAP])}{extra})"
    return f"{field.name} {text}"


def _source(model: type[models.Model]) -> str:
    """``catalog/models.py:12``: where the class is, relative to the project root."""
    import inspect
    from pathlib import Path

    from karni.testing._source import project_root

    try:
        file = inspect.getsourcefile(model)
        _lines, line = inspect.getsourcelines(model)
    except (OSError, TypeError):
        return model.__module__
    if not file:
        return model.__module__
    path = Path(file).resolve()
    try:
        shown = path.relative_to(project_root()).as_posix()
    except ValueError:
        shown = model.__module__.replace(".", "/") + ".py"
    return f"{shown}:{line}"


def model_context(names: Sequence[str]) -> str:
    """Experimental. One block per model: ``MODEL``, ``FIELDS``, ``RELATED``, ``VIEWSETS``, ...

    ``MODEL`` names the label, the source file and line, the key type and the
    table. ``FIELDS`` lists every field (:func:`field_text`), ``RELATED`` the
    relations of other models that point at it, ``VIEWSETS`` its routed
    viewsets with route, access and search fields, then its ``SCOPES``,
    ``ACTIONS``, ``VISIBILITY``, ``PERF`` and ``PAGES``.

    :raises ContextSliceError: for a name that is unknown or ambiguous (:func:`resolve_models`).
    """
    blocks: list[str] = []
    shown = _display_names()
    for model in resolve_models(names):
        meta = model._meta
        fields = [
            field_text(field, shown)
            for field in [*meta.concrete_fields, *meta.many_to_many]
            if field.name not in _SKIP_FIELDS
        ]
        related = [
            f"{_shown(relation.related_model, shown)}.{relation.field.name}"
            for relation in meta.related_objects
            if relation.related_model is not None and hasattr(relation, "field")
        ]
        routed = _routed_for({model})
        viewsets = " ".join(
            _viewset_text(prefix, viewset, with_search=True) for prefix, viewset in routed
        )
        lines = [
            f"MODEL: {meta.label} ({_source(model)}) key {key_type(model)}, table {meta.db_table}",
            "FIELDS: " + ", ".join(fields) if fields else None,
            "RELATED: " + " ".join(sorted(set(related))) if related else None,
            f"VIEWSETS: {viewsets}" if viewsets else None,
            _scopes_for([model]),
            *[line for line in _roles_for([model]) if line.startswith("ACTIONS:")],
            visibility_section([model]),
            _perf_for({viewset for _, viewset in routed}),
            _pages_line([model]),
        ]
        blocks.append("\n".join(line for line in lines if line))
    return "\n".join(blocks)
