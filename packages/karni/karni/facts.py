"""Experimental. The project as plain facts: models, viewsets, roles, features, modules, seeders.

``manage.py karni_facts`` prints :func:`project_facts` as JSON, and
``karni spec export`` turns it into a ``karni.yaml``. The facts say what the
code declares, with no opinion on the spec format: each field's class and
its ``deconstruct()`` arguments, each viewset's route and ``describe()``d
access, the settings the spec's features and roles come from, and every
installed module's settings next to the module's defaults. Every value is
JSON-safe: a function or class becomes its dotted path, a ``Decimal`` a
string, an enum member its value.

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

__all__ = ["project_apps", "project_facts"]

#: The settings a spec's ``features`` and ``roles`` come from.
FEATURE_SETTINGS: tuple[str, ...] = (
    "KARNI_2FA",
    "KARNI_EMAIL_OTP",
    "KARNI_SOCIAL_TOKEN_PROVIDERS",
    "KARNI_TERMS",
    "KARNI_ROLES",
    "KARNI_ACCOUNTS_DEFAULT_ROLES",
)


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


def _base_field_names() -> frozenset[str]:
    from karni.models import BaseModel

    return frozenset(field.name for field in BaseModel._meta.get_fields())


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


def _model(model: type[models.Model], base: frozenset[str], user: type) -> dict[str, Any]:
    from karni.models import BaseModel

    on_base = issubclass(model, BaseModel)
    fields = [
        _field(field, user)
        for field in sorted(
            [*model._meta.local_fields, *model._meta.local_many_to_many],
            key=lambda field: field.creation_counter,
        )
        if not (on_base and field.name in base)
    ]
    admin_meta = _declared(getattr(model, "AdminMeta", None))
    return {
        "name": model.__name__,
        "label": model._meta.label,
        "base_model": on_base,
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
    base_fields = _base_field_names()
    declared = {name: _safe(getattr(settings, name, None)) for name in FEATURE_SETTINGS}
    shipped_roles = _safe(base.BASE["KARNI_ROLES"])
    return {
        "user_model": user._meta.label,
        "apps": [
            {
                "label": config.label,
                "name": config.name,
                "models": [_model(model, base_fields, user) for model in config.get_models()],
            }
            for config in project_apps()
        ],
        "viewsets": _viewsets(),
        "settings": declared,
        "shipped_roles": shipped_roles,
        "modules": _modules(),
        "seeders": _seeders(),
    }
