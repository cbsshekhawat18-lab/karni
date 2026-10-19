"""``class Karni`` — a model's Karni metadata, read in one place.

A model declares what Karni's data-driven layers need to know about it in a
nested class, next to ``Meta``, ``APIMeta`` and ``AdminMeta``::

    class Order(BaseModel):
        class Karni:
            owner_field = "created_by"          # the `own` scope (default: created_by)
            scope_paths = {"branch": "branch", "region": "branch__region"}
            actions = ["approve", "export"]     # besides view/add/change/delete
            field_roles = {                     # who sees / changes a field (P3)
                "phone": {"read": ["staff", "support"], "write": ["staff"]},
                "internal_note": ["staff"],     # shorthand: read and write
            }
            audit = True                        # change history (P4)
            natural_key = "number"              # how imports and exports name a row (P6)
            import_key = "number"               # the column an import matches rows on
            import_lookup = {"customer": "email"}       # FK column → target field
            import_transform = "shop.imports.clean_order_row"
            after_import = "shop.imports.reindex"

Every option has a default, so a model with no ``Karni`` class behaves
sensibly: owned by whoever created it, no extra scope paths, the four
standard actions, every field visible to whoever may read the row, no
history, keyed by its first unique text field (else the primary key).
Readers go through :func:`karni_option` so a project can also set an option
on an abstract base and inherit it.

Override / escape hatch: subclass a model's ``Karni`` class in a subclass
model (``class Karni(Parent.Karni): ...``) to change one option.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from django.core.exceptions import FieldDoesNotExist
from django.db import models

from karni.exceptions import KarniImproperlyConfigured

__all__ = [
    "STANDARD_ACTIONS",
    "FieldRule",
    "ImportOptions",
    "field_roles",
    "import_options",
    "karni_option",
    "model_actions",
    "natural_key",
    "owner_field",
    "permission_key",
    "scope_paths",
]


@dataclass(frozen=True)
class FieldRule:
    """Who may read and who may write one field: role slugs, any of which suffices."""

    read: tuple[str, ...]
    write: tuple[str, ...]


#: The actions every model has a permission for (Django's names, so the
#: admin's vocabulary and Karni's agree).
STANDARD_ACTIONS: Final[tuple[str, ...]] = ("view", "add", "change", "delete")


def karni_option(model: type[models.Model] | Any, name: str, default: Any = None) -> Any:
    """``model.Karni.<name>``, else ``default``."""
    return getattr(getattr(model, "Karni", None), name, default)


def model_actions(model: type[models.Model]) -> tuple[str, ...]:
    """The standard actions plus the model's own (``Karni.actions``), in order."""
    extra = tuple(karni_option(model, "actions", ()) or ())
    return STANDARD_ACTIONS + tuple(action for action in extra if action not in STANDARD_ACTIONS)


def permission_key(model: type[models.Model], action: str) -> str:
    """``"app_label.modelname:action"`` — how a grant names a permission."""
    return f"{model._meta.label_lower}:{action}"


def owner_field(model: type[models.Model]) -> str | None:
    """The field the ``own`` scope compares with the user, or ``None`` when the model has none.

    ``Karni.owner_field`` when declared; else ``created_by`` when the model
    carries it (every ``BaseModel`` does); else ``None``.
    """
    declared = karni_option(model, "owner_field")
    if declared:
        return str(declared)
    names = {field.name for field in model._meta.get_fields()}
    return "created_by" if "created_by" in names else None


def scope_paths(model: type[models.Model]) -> dict[str, str]:
    """``Karni.scope_paths``: scope key → lookup path on the model (``{"branch": "branch"}``)."""
    declared = karni_option(model, "scope_paths", None) or {}
    return {str(key): str(path) for key, path in dict(declared).items()}


def _slugs(model: type[models.Model], name: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, str) or not all(isinstance(slug, str) and slug for slug in value):
        raise KarniImproperlyConfigured(
            f"{model.__name__}.Karni.field_roles[{name!r}] must list role slugs, e.g. "
            "{'read': ['staff', 'support'], 'write': ['staff']} or ['staff'].",
            code="E212",
        )
    return tuple(dict.fromkeys(value))


def field_roles(model: type[models.Model]) -> dict[str, FieldRule]:
    """``Karni.field_roles``: field name → :class:`FieldRule` (roles are the project's own).

    A list of slugs is the shorthand for "these roles read and write"; a
    mapping names ``read`` and, optionally, ``write`` (default: the readers).
    A field not listed is visible to everyone who may read the row.
    """
    declared = karni_option(model, "field_roles", None) or {}
    if not isinstance(declared, Mapping):
        raise KarniImproperlyConfigured(
            f"{model.__name__}.Karni.field_roles must be a dict of field name -> roles.",
            code="E212",
        )
    rules: dict[str, FieldRule] = {}
    for name, spec in declared.items():
        if isinstance(spec, Mapping):
            if "read" not in spec:
                raise KarniImproperlyConfigured(
                    f"{model.__name__}.Karni.field_roles[{name!r}] needs 'read': the roles "
                    "that may see the field ('write' defaults to them).",
                    code="E212",
                )
            read = _slugs(model, str(name), spec["read"])
            write = _slugs(model, str(name), spec.get("write", read))
        else:
            read = write = _slugs(model, str(name), spec)
        rules[str(name)] = FieldRule(read, write)
    return rules


# import and export (ADR 0002, P6)

_KEY_FIELD_TYPES: Final[tuple[str, ...]] = ("SlugField", "CharField", "EmailField")


def natural_key(model: type[models.Model]) -> str | None:
    """The field that names a row of ``model`` to people: ``Karni.natural_key``.

    How an import refers to a related row (``venue = "Arena"``) and how an
    export writes a relation. Declared explicitly, else the first unique
    slug/char/email field (``slug``, ``email``, ``sku``), else ``None`` —
    imports and exports then use the primary key.
    """
    declared = karni_option(model, "natural_key")
    if declared:
        name = str(declared)
        try:
            model._meta.get_field(name)
        except FieldDoesNotExist as exc:
            raise KarniImproperlyConfigured(
                f"{model.__name__}.Karni.natural_key names {name!r}, which the model does "
                "not have.",
                code="E801",
            ) from exc
        return name
    for field in model._meta.concrete_fields:
        if field.unique and not field.primary_key and field.get_internal_type() in _KEY_FIELD_TYPES:
            return str(field.name)
    return None


@dataclass(frozen=True)
class ImportOptions:
    """What generic import code cannot know about a model, from ``class Karni``.

    ``key`` is the column an import matches existing rows on (update instead
    of create); ``lookups`` maps a relation field to the target field its
    column carries; ``transform`` rewrites each row's mapped values before
    validation; ``after`` runs once a commit has succeeded, with the result.
    """

    key: str | None
    lookups: Mapping[str, str]
    transform: Callable[..., Mapping[str, Any]] | None
    after: Callable[..., Any] | None


def _callable_option(model: type[models.Model], name: str) -> Callable[..., Any] | None:
    value = karni_option(model, name)
    if value is None:
        return None
    if isinstance(value, str):
        from django.utils.module_loading import import_string

        try:
            value = import_string(value)
        except ImportError as exc:
            raise KarniImproperlyConfigured(
                f"{model.__name__}.Karni.{name} = {value!r} cannot be imported: {exc}",
                code="E801",
            ) from exc
    if isinstance(value, staticmethod):
        value = value.__func__
    if not callable(value):
        raise KarniImproperlyConfigured(
            f"{model.__name__}.Karni.{name} must be a callable or its dotted path, got {value!r}.",
            code="E801",
        )
    return value


def import_options(model: type[models.Model]) -> ImportOptions:
    """``Karni.import_key`` / ``import_lookup`` / ``import_transform`` / ``after_import``."""
    key = karni_option(model, "import_key") or natural_key(model)
    if key is not None:
        try:
            model._meta.get_field(str(key))
        except FieldDoesNotExist as exc:
            raise KarniImproperlyConfigured(
                f"{model.__name__}.Karni.import_key names {key!r}, which the model does not have.",
                code="E801",
            ) from exc
    lookups = karni_option(model, "import_lookup", None) or {}
    if not isinstance(lookups, Mapping):
        raise KarniImproperlyConfigured(
            f"{model.__name__}.Karni.import_lookup must map a relation field to the target "
            "field its column carries, e.g. {'venue': 'name'}.",
            code="E801",
        )
    return ImportOptions(
        key=str(key) if key is not None else None,
        lookups={str(field): str(target) for field, target in lookups.items()},
        transform=_callable_option(model, "import_transform"),
        after=_callable_option(model, "after_import"),
    )
