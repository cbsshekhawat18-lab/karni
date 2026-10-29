"""Experimental. The project as plain facts: models, viewsets, roles, features, modules, seeders.

``manage.py karni_facts`` prints :func:`project_facts` as JSON, and
``karni spec export`` turns it into a ``karni.yaml``. The facts say what the
code declares, with no opinion on the spec format: each field's class and
its ``deconstruct()`` arguments, each model's key type, table and whether
Django manages it, each viewset's route and ``describe()``d access, the
settings the spec's features and roles come from, the database aliases, and
every installed module's settings next to the module's defaults. Every value
is JSON-safe: a function or class becomes its dotted path, a ``Decimal`` a
string, an enum member its value.

``manage.py karni_rows`` prints :func:`count_rows`: the row counts ``karni
plan`` shows next to a risky change. It is the only part that opens the
database, and it runs only ``SELECT COUNT`` queries.

The project's own apps are the installed apps whose code lives under the
directory ``manage.py`` runs in (``BASE_DIR`` when the settings define it)
and outside any ``site-packages``.

Override / escape hatch: ``KARNI_FACTS_APPS`` (a list of app labels) names
the apps to describe instead.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from django.apps import AppConfig, apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils.functional import Promise

__all__ = ["COUNT_KINDS", "count_rows", "project_apps", "project_facts"]

#: The settings a spec's ``features`` and ``roles`` come from, and the default key type.
FEATURE_SETTINGS: tuple[str, ...] = (
    "KARNI_2FA",
    "KARNI_EMAIL_OTP",
    "KARNI_SOCIAL_TOKEN_PROVIDERS",
    "KARNI_TERMS",
    "KARNI_ROLES",
    "KARNI_ACCOUNTS_DEFAULT_ROLES",
    "KARNI_PK",
)
#: Experimental. What :func:`count_rows` counts (see its docstring).
COUNT_KINDS: tuple[str, ...] = ("all", "set", "empty", "longer", "in")


def _safe(value: Any) -> Any:
    """``value`` as JSON-safe data (see the module docstring)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value if not isinstance(value, str) else str(value)
    if isinstance(value, enum.Enum):
        return _safe(value.value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Promise):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        items = [_safe(item) for item in value]
        return sorted(items, key=repr) if isinstance(value, set | frozenset) else items
    if isinstance(value, models.Field):
        _, path, _, kwargs = value.deconstruct()
        return {"class": path, "kwargs": _safe(kwargs)}
    if isinstance(value, type) and issubclass(value, models.Model):
        return str(cast(Any, value)._meta.label)
    if callable(value):
        module = getattr(value, "__module__", "") or ""
        name = getattr(value, "__qualname__", "") or type(value).__name__
        return f"{module}.{name}" if module else name
    return repr(value)


def _base_root() -> Path:
    return Path(getattr(settings, "BASE_DIR", None) or Path.cwd()).resolve()


def project_apps() -> list[AppConfig]:
    """Experimental. The project's own app configs (see the module docstring)."""
    chosen = getattr(settings, "KARNI_FACTS_APPS", None)
    if chosen is not None:
        return [apps.get_app_config(label) for label in chosen]
    root = _base_root()
    found = []
    for config in apps.get_app_configs():
        path = Path(config.path).resolve()
        if "site-packages" in path.parts or not path.is_relative_to(root):
            continue
        found.append(config)
    return found


def _mixin_fields(model: type[models.Model]) -> frozenset[str]:
    """The fields ``model`` inherits from Karni's model mixins (its key, timestamps, ...)."""
    from karni.models import (
        AuditedModel,
        IntegerKeyModel,
        SoftDeleteModel,
        TimestampedModel,
        UUIDModel,
    )

    mixins = (UUIDModel, IntegerKeyModel, TimestampedModel, SoftDeleteModel, AuditedModel)
    return frozenset(
        field.name
        for mixin in mixins
        if issubclass(model, mixin)
        for field in cast(Any, mixin)._meta.local_fields
    )


def _key_type(model: type[models.Model]) -> str | None:
    """``bigint`` for a ``BigAutoField`` key, ``uuid`` for a ``UUIDField`` one, else ``None``."""
    key = model._meta.pk
    if isinstance(key, models.BigAutoField):
        return "bigint"
    if isinstance(key, models.UUIDField):
        return "uuid"
    return None


def _field(field: Any, user: type[models.Model]) -> dict[str, Any]:
    _, path, _, kwargs = field.deconstruct()
    fact: dict[str, Any] = {
        "name": field.name,
        "class": f"{type(field).__module__}.{type(field).__qualname__}",
        "path": path,
        "kwargs": _safe(kwargs),
        "null": bool(field.null),
        "blank": bool(field.blank),
        "generated": isinstance(field, models.GeneratedField),
    }
    related: Any = getattr(field, "related_model", None)
    if isinstance(related, type):
        fact["related"] = cast(Any, related)._meta.label
        fact["related_is_user"] = related is user
    choices = getattr(field, "choices", None)
    if choices and not hasattr(field, "machine"):
        fact["choices"] = [str(_safe(value)) for value, _label in field.flatchoices]
    machine = getattr(field, "machine", None)
    if machine is not None:
        fact["states"] = list(machine.states)
        fact["transitions"] = {state: list(t) for state, t in machine.transitions.items() if t}
    return fact


def _declared(cls: Any) -> dict[str, Any]:
    if not isinstance(cls, type):
        return {}
    names = [name for name in dir(cls) if not name.startswith("_")]
    return {name: _safe(getattr(cls, name)) for name in names}


def _model(model: type[models.Model], user: type) -> dict[str, Any]:
    from karni.models import BaseModel, BigIntBaseModel

    inherited = _mixin_fields(model)
    fields = [
        _field(field, user)
        for field in sorted(
            [*model._meta.local_fields, *model._meta.local_many_to_many],
            key=lambda field: field.creation_counter,
        )
        if field.name not in inherited
    ]
    admin_meta = _declared(getattr(model, "AdminMeta", None))
    return {
        "name": model.__name__,
        "label": model._meta.label,
        # on BaseModel or BigIntBaseModel: the fields of Karni's mixins are left out of "fields"
        "base_model": issubclass(model, BaseModel | BigIntBaseModel),
        "pk": _key_type(model),
        "managed": bool(model._meta.managed),
        "db_table": model._meta.db_table,
        "proxy": bool(model._meta.proxy),
        "fields": fields,
        "ordering": [_safe(item) for item in model._meta.ordering],
        "karni": _declared(getattr(model, "Karni", None)),
        "admin_meta": admin_meta,
        "api_meta": sorted(_declared(getattr(model, "APIMeta", None))),
    }


def _access(viewset: type) -> dict[str, Any]:
    from karni.api.access import Access, Granted, Unscoped
    from karni.api.viewsets import BaseViewSet

    if getattr(viewset, "get_access", None) is not BaseViewSet.get_access:
        return {"computed": True}
    declared = getattr(viewset, "access", None)
    if isinstance(declared, Granted):
        return {"read": declared.describe(), "write": declared.describe()}
    if isinstance(declared, Access):
        found = {"read": declared.read.describe(), "write": declared.write.describe()}
        if declared.create is not declared.write:
            found["create"] = declared.create.describe()
        return found
    if isinstance(declared, Unscoped):
        return {"unscoped": declared.reason}
    return {"missing": True}


def _viewsets() -> list[dict[str, Any]]:
    from django.utils.module_loading import import_string

    factory = import_string(
        getattr(settings, "KARNI_API_ROUTER", "karni.api.routers.get_default_router")
    )
    found = []
    for prefix, viewset, _basename in factory().registry:
        model: Any = getattr(viewset, "model", None)
        found.append(
            {
                "class": f"{viewset.__module__}.{viewset.__qualname__}",
                "route": prefix,
                "model": getattr(getattr(model, "_meta", None), "label", None),
                "access": _access(viewset),
                "search_fields": [str(name) for name in getattr(viewset, "search_fields", ())],
            }
        )
    return found


def _modules() -> list[dict[str, Any]]:
    found = []
    for config in apps.get_app_configs():
        if "." in config.name or not config.name.startswith("karni_"):
            continue
        name = config.name.removeprefix("karni_")
        prefix = f"KARNI_{name.upper()}_"
        try:
            defaults = dict(import_module(f"{config.name}.conf").DEFAULTS)
        except (ImportError, AttributeError):
            defaults = {}
        keys = [key for key in defaults if key.startswith(prefix)]
        found.append(
            {
                "name": name,
                "settings": {key: _safe(getattr(settings, key, defaults[key])) for key in keys},
                "defaults": {key: _safe(defaults[key]) for key in keys},
            }
        )
    return found


def _seeders() -> dict[str, Any]:
    from karni.seeding import seeders

    found = seeders().items()
    return {model._meta.label: seeder.Meta.__dict__.get("count") for model, seeder in found}


def project_facts() -> dict[str, Any]:
    """Experimental. Everything ``karni spec export`` reads, as JSON-safe data."""
    from karni.conf import base

    user = get_user_model()
    declared = {name: _safe(getattr(settings, name, None)) for name in FEATURE_SETTINGS}
    shipped_roles = _safe(base.BASE["KARNI_ROLES"])
    return {
        "user_model": user._meta.label,
        "apps": [
            {
                "label": config.label,
                "name": config.name,
                "models": [_model(model, user) for model in config.get_models()],
            }
            for config in project_apps()
        ],
        "viewsets": _viewsets(),
        "settings": declared,
        "databases": sorted(settings.DATABASES),
        "shipped_roles": shipped_roles,
        "modules": _modules(),
        "seeders": _seeders(),
    }


def _count(model: type[models.Model], alias: str, request: Mapping[str, Any]) -> int:
    from django.db.models import Q
    from django.db.models.functions import Length

    rows = cast(Any, model)._base_manager.using(alias)
    name = request.get("field")
    kind = request.get("kind") or "all"
    if not name or kind == "all":
        return int(rows.count())
    field: Any = model._meta.get_field(str(name))
    if field.many_to_many:
        if kind == "set":
            return int(field.remote_field.through._base_manager.using(alias).count())
        if kind == "empty":
            return int(rows.filter(**{f"{name}__isnull": True}).count())
        raise ValueError(f"{kind} does not apply to a many-to-many field")
    empty = Q(**{f"{name}__isnull": True})
    if field.empty_strings_allowed:
        empty |= Q(**{name: ""})
    if kind == "set":
        return int(rows.exclude(empty).count())
    if kind == "empty":
        return int(rows.filter(empty).count())
    if kind == "longer":
        longer = rows.annotate(_karni_length=Length(name)).filter(
            _karni_length__gt=int(request["arg"])
        )
        return int(longer.count())
    if kind == "in":
        return int(rows.filter(**{f"{name}__in": list(request["arg"])}).count())
    raise ValueError(f"unknown count kind {kind!r} (kinds: {', '.join(COUNT_KINDS)})")


def _unreachable(alias: str) -> str | None:
    """Why ``alias`` cannot be counted, else ``None`` (it answered)."""
    from django.core.exceptions import ImproperlyConfigured
    from django.db import DatabaseError, connections

    connection = connections[alias]
    name = str(connection.settings_dict.get("NAME") or "")
    is_file = connection.vendor == "sqlite" and name and not name.startswith("file:")
    if is_file and name != ":memory:" and not Path(name).exists():
        return f"{alias}: the database file {name} does not exist yet"  # connecting would create it
    try:
        connection.ensure_connection()
    except (DatabaseError, ImproperlyConfigured) as exc:
        first = (str(exc).strip().splitlines() or [""])[0]
        return f"{alias}: {type(exc).__name__}: {first}".rstrip(": ")
    return None


def count_rows(requests: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Experimental. Row counts for ``karni plan``: one count per request, ``None`` when it fails.

    Each request is ``{"model": "app.Model"}``, plus ``"field"`` and
    ``"kind"`` to count part of the rows: ``all`` (every row), ``set`` (rows
    whose field holds a value: not null, and not blank where the column takes
    text; for a many-to-many field, its links), ``empty`` (rows whose field is
    null or blank), ``longer`` (rows whose value is longer than ``"arg"``
    characters) or ``in`` (rows whose value is one of the list ``"arg"``).
    Counts read through each model's base manager, so soft-deleted rows and
    rows a scope hides count too, on the database the router reads the model
    from. Only ``SELECT COUNT`` queries run, and a SQLite file that does not
    exist is not created.

    Returns ``{"rows": [...], "unreachable": {alias: why}}``: a count is
    ``None`` when its model, field or table is missing, or when its database
    did not answer.
    """
    from django.core.exceptions import FieldDoesNotExist
    from django.db import DatabaseError, router

    rows: list[int | None] = []
    checked: dict[str, str | None] = {}
    for request in requests:
        try:
            model = apps.get_model(str(request["model"]))
        except (KeyError, LookupError, ValueError):
            rows.append(None)
            continue
        alias = router.db_for_read(model) or "default"
        if alias not in checked:
            checked[alias] = _unreachable(alias)
        if checked[alias] is not None:
            rows.append(None)
            continue
        try:
            rows.append(_count(model, alias, request))
        except (DatabaseError, FieldDoesNotExist, KeyError, TypeError, ValueError):
            rows.append(None)
    return {"rows": rows, "unreachable": {a: why for a, why in checked.items() if why}}
