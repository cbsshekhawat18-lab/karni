"""Experimental. Field groups and column sets: usable screens for a model with many fields.

A model with a hundred columns and a dozen long markdown sections turns a
generated form or detail page into one endless list, and its table into a
hundred columns. Three ``class Karni`` options lay it out::

    class Product(BaseModel):
        class Karni:
            field_groups = {
                "Overview": ["name", "sku", "summary"],
                "Financials": ["price", "cost", "margin"],
            }
            field_group_layout = "tabs"     # or "sections" (the default)
            column_sets = {
                "default": ["name", "sku", "price"],
                "financial": ["name", "price", "cost", "margin"],
            }

* ``field_groups``: titled groups of fields, in the declaration's order, the
  fields of each in the order listed. ``@karni/ui``'s ResourceForm and
  ResourceDetail show each group as a section (or a tab, with
  ``field_group_layout = "tabs"``), and the admin's change form as a
  fieldset. The fields in no group go into a last group, titled
  :data:`REST_GROUP` ("Other"). To title them yourself, list them in a group.
* ``column_sets``: named column presets of ResourceTable. A selector switches
  between them and the choice is kept per user in the browser. The set named
  ``default`` is shown first, else the first set.

The OpenAPI schema publishes them on the model's list operation as
``x-karni-field-groups`` (``{"layout", "groups": [{"label", "fields"}]}``)
and ``x-karni-column-sets`` (``{"default", "sets": [{"name", "label",
"columns"}]}``), each limited to the fields the requester's serializer has, so
a field the role may not read is never named (``KarniAutoSchema``).

``karni check`` refuses a malformed declaration (``E550``, ``E553``), a group
or column set that names a field the model does not have (``E551``) and a
field in two groups (``E552``), naming the model, the group or set, and the
field.

Override / escape hatch: subclass the model's ``Karni`` class to change one
option, override ``KarniAutoSchema.get_karni_field_groups`` /
``get_karni_column_sets`` to publish something else, declare
``AdminMeta.fieldsets`` (it wins in the admin), and pass ResourceForm's and
ResourceDetail's ``fieldGroups`` / ``groupLayout`` or ResourceTable's
``columnSets`` / ``columnSet`` props to replace them in one screen.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from django.db import models

from karni.exceptions import KarniImproperlyConfigured
from karni.meta import karni_option

__all__ = [
    "LAYOUTS",
    "REST_GROUP",
    "ColumnSet",
    "FieldGroup",
    "column_sets",
    "default_column_set",
    "field_group_layout",
    "field_groups",
    "fieldsets",
    "layout_errors",
]

#: The title of the last group: the fields no declared group lists.
REST_GROUP: Final = "Other"
#: How ResourceForm and ResourceDetail show the groups (``field_group_layout``).
LAYOUTS: Final = ("sections", "tabs")
#: The column set shown first when the model declares one with this name.
DEFAULT_SET: Final = "default"

Layout = Literal["sections", "tabs"]


@dataclass(frozen=True)
class FieldGroup:
    """Experimental. One titled group of fields, in the order listed."""

    label: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class ColumnSet:
    """Experimental. One named column preset of ResourceTable."""

    name: str
    label: str
    columns: tuple[str, ...]


def _model_fields(model: type[models.Model]) -> set[str]:
    """The names a group or a column set may list: the model's own fields, many-to-many included."""
    return {
        field.name for field in model._meta.get_fields() if not field.auto_created or field.concrete
    }


def _names(value: Any) -> list[str] | None:
    """A list of field names, or ``None`` when ``value`` is not a list or tuple of strings."""
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _malformed(
    model: type[models.Model], code: str, option: str, problem: str
) -> KarniImproperlyConfigured:
    return KarniImproperlyConfigured(f"{model.__name__}.Karni.{option} {problem}", code=code)


def _unknown(
    model: type[models.Model], option: str, what: str, name: str
) -> KarniImproperlyConfigured:
    return KarniImproperlyConfigured(
        f"{model.__name__}.Karni.{option}: {what} names {name!r}, which is not a field of "
        f"{model.__name__}.",
        code="E551",
    )


def _group_errors(
    model: type[models.Model],
) -> tuple[list[FieldGroup], list[KarniImproperlyConfigured]]:
    raw = karni_option(model, "field_groups", None)
    errors: list[KarniImproperlyConfigured] = []
    layout = karni_option(model, "field_group_layout", "sections")
    if layout not in LAYOUTS:
        errors.append(
            _malformed(
                model, "E550", "field_group_layout", f"is {layout!r}: write 'sections' or 'tabs'."
            )
        )
    if raw is None:
        return [], errors
    if not isinstance(raw, Mapping):
        errors.append(
            _malformed(
                model,
                "E550",
                "field_groups",
                f"must map each group's title to a list of field names, not {type(raw).__name__}.",
            )
        )
        return [], errors
    known = _model_fields(model)
    seen: dict[str, str] = {}
    groups: list[FieldGroup] = []
    for title, members in raw.items():
        names = _names(members)
        if not isinstance(title, str) or not title.strip():
            errors.append(
                _malformed(
                    model, "E550", "field_groups", f"has a group without a title ({title!r})."
                )
            )
            continue
        if not names:
            errors.append(
                _malformed(
                    model,
                    "E550",
                    "field_groups",
                    f"group {title!r} must list field names, not {members!r}.",
                )
            )
            continue
        kept: list[str] = []
        for name in names:
            if name not in known:
                errors.append(_unknown(model, "field_groups", f"group {title!r}", name))
            elif name in seen:
                where = (
                    "twice in group"
                    if seen[name] == title
                    else f"in group {seen[name]!r} and in group"
                )
                errors.append(
                    KarniImproperlyConfigured(
                        f"{model.__name__}.Karni.field_groups: {name!r} is {where} {title!r}. "
                        "A field belongs to one group.",
                        code="E552",
                    )
                )
            else:
                seen[name] = title
                kept.append(name)
        groups.append(FieldGroup(title, tuple(kept)))
    return groups, errors


def _set_errors(
    model: type[models.Model],
) -> tuple[list[ColumnSet], list[KarniImproperlyConfigured]]:
    raw = karni_option(model, "column_sets", None)
    if raw is None:
        return [], []
    errors: list[KarniImproperlyConfigured] = []
    if not isinstance(raw, Mapping) or not raw:
        errors.append(
            _malformed(
                model,
                "E553",
                "column_sets",
                f"must map each set's name to a list of field names, not {raw!r}.",
            )
        )
        return [], errors
    known = _model_fields(model)
    sets: list[ColumnSet] = []
    for name, members in raw.items():
        columns = _names(members)
        if not isinstance(name, str) or not name.strip():
            errors.append(
                _malformed(model, "E553", "column_sets", f"has a set without a name ({name!r}).")
            )
            continue
        if not columns:
            errors.append(
                _malformed(
                    model,
                    "E553",
                    "column_sets",
                    f"set {name!r} must list field names, not {members!r}.",
                )
            )
            continue
        twice = sorted({column for column in columns if columns.count(column) > 1})
        if twice:
            errors.append(
                _malformed(
                    model, "E553", "column_sets", f"set {name!r} lists {', '.join(twice)} twice."
                )
            )
        for column in columns:
            if column not in known:
                errors.append(_unknown(model, "column_sets", f"set {name!r}", column))
        label = name.replace("_", " ").strip()
        sets.append(ColumnSet(name, label[:1].upper() + label[1:], tuple(dict.fromkeys(columns))))
    return sets, errors


def layout_errors(model: type[models.Model]) -> list[KarniImproperlyConfigured]:
    """Experimental. Every problem of ``field_groups``, ``field_group_layout``, ``column_sets``."""
    return [*_group_errors(model)[1], *_set_errors(model)[1]]


def field_groups(model: type[models.Model]) -> tuple[FieldGroup, ...]:
    """Experimental. The model's ``Karni.field_groups``, in order (empty when it declares none).

    Raises :class:`~karni.exceptions.KarniImproperlyConfigured` (``E550`` to
    ``E552``) for the first problem, as ``karni check`` reports every one.
    """
    groups, errors = _group_errors(model)
    if errors:
        raise errors[0]
    return tuple(groups)


def field_group_layout(model: type[models.Model]) -> Layout:
    """Experimental. ``"sections"`` (the default) or ``"tabs"``: how the UI shows the groups."""
    layout = karni_option(model, "field_group_layout", "sections")
    if layout not in LAYOUTS:
        raise _malformed(
            model, "E550", "field_group_layout", f"is {layout!r}: write 'sections' or 'tabs'."
        )
    return "tabs" if layout == "tabs" else "sections"


def column_sets(model: type[models.Model]) -> tuple[ColumnSet, ...]:
    """Experimental. The model's ``Karni.column_sets``, in order (empty when it declares none).

    Raises :class:`~karni.exceptions.KarniImproperlyConfigured` (``E551`` or
    ``E553``) for the first problem.
    """
    sets, errors = _set_errors(model)
    if errors:
        raise errors[0]
    return tuple(sets)


def default_column_set(sets: Iterable[ColumnSet]) -> str | None:
    """Experimental. The set shown first: the one named ``default``, else the first one."""
    names = [found.name for found in sets]
    if DEFAULT_SET in names:
        return DEFAULT_SET
    return names[0] if names else None


def fieldsets(
    model: type[models.Model], names: Iterable[str]
) -> list[tuple[str | None, dict[str, Any]]] | None:
    """Experimental. The admin's fieldsets for ``names`` (its form's fields), from ``field_groups``.

    Each group keeps the fields of ``names`` it lists, in its order, and a
    group left with none is dropped. The fields of ``names`` in no group form
    the last fieldset, titled :data:`REST_GROUP`. ``None`` when the model
    declares no groups (Django's single fieldset stays).
    """
    groups = field_groups(model)
    if not groups:
        return None
    shown = list(names)
    available = set(shown)
    grouped: set[str] = set()
    found: list[tuple[str | None, dict[str, Any]]] = []
    for group in groups:
        members = [name for name in group.fields if name in available]
        grouped.update(members)
        if members:
            found.append((group.label, {"fields": members}))
    rest = [name for name in shown if name not in grouped]
    if rest:
        found.append((REST_GROUP, {"fields": rest}))
    return found
