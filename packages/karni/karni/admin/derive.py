"""Pure derivation rules that turn a model into Django admin options.

Every function here is a module-level pure function so a project can import
and reuse any single rule. :class:`karni.admin.base.KarniAdminMixin` exposes a
matching classmethod hook for each one (``derive_list_display`` and friends)
that simply delegates here — subclass :data:`karni.admin.KarniModelAdmin` and
override the hook to change one rule per project without touching the rest.

Caps are read from settings on every call (``KARNI_ADMIN_LIST_DISPLAY_MAX``,
``KARNI_ADMIN_LIST_FILTER_MAX``, ``KARNI_ADMIN_SEARCH_MAX``), so
``override_settings`` works in tests and projects can tune them in
``settings.py``.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib import admin
from django.db import models

from karni.admin.soft_delete import SoftDeleteListFilter
from karni.models import SoftDeleteModel

AUDIT_FIELDS = frozenset(
    {"id", "created_at", "updated_at", "deleted_at", "created_by", "updated_by"}
)
"""Field names treated as audit metadata: hidden from displays, kept read-only.

Override / escape hatch: per model, set explicit values on ``class AdminMeta``
(``list_display``, ``read_only``, …) — those always win over derivation.
"""

DEFAULT_LIST_DISPLAY_MAX = 6
DEFAULT_LIST_FILTER_MAX = 6
DEFAULT_SEARCH_MAX = 5

#: A single ``list_filter`` entry as Django admin accepts it.
FilterSpec = str | tuple[str, type[admin.FieldListFilter]] | type[admin.SimpleListFilter]

_DISPLAY_EXCLUDED_TYPES = (
    models.TextField,
    models.JSONField,
    models.FileField,  # covers ImageField
    models.BinaryField,
)
_DISPLAY_INCLUDED_TYPES = (
    models.CharField,  # covers Slug/Email/URL
    models.IntegerField,  # covers Small/Big/Positive*/Auto*
    models.DecimalField,
    models.FloatField,
    models.BooleanField,
    models.DateField,  # covers DateTimeField
    models.ForeignKey,  # covers OneToOneField
)


def _int_setting(name: str, default: int) -> int:
    """Read a positive-int cap from settings, falling back to ``default``."""
    return int(getattr(settings, name, default))


def admin_meta(model: type[models.Model]) -> type | None:
    """Return the model's inner ``class AdminMeta``, or ``None``.

    ``AdminMeta`` is the per-model override convention (mirroring ``APIMeta``):
    any attribute it defines beats the derived default for that model only.
    """
    meta = getattr(model, "AdminMeta", None)
    return meta if isinstance(meta, type) else None


def is_password_field(field: models.Field) -> bool:
    """True for password-ish fields, which are never displayed or searched.

    Override / escape hatch: expose one deliberately via
    ``AdminMeta.list_display`` / ``AdminMeta.extra`` on the model.
    """
    return "password" in field.name


def password_field_names(model: type[models.Model]) -> tuple[str, ...]:
    """Names of password-ish concrete fields, excluded from derived admin forms."""
    return tuple(f.name for f in model._meta.fields if is_password_field(f))


def _skip_always(field: models.Field) -> bool:
    return field.name in AUDIT_FIELDS or is_password_field(field)


def derive_list_display(model: type[models.Model]) -> list[str]:
    """Derive ``list_display``: scalar-ish concrete fields in declaration order.

    Includes Char/Slug/Email/URL, integer family, Decimal, Float, Boolean,
    Date/DateTime and FK fields (choices are fine); never Text, JSON, File,
    Image, M2M, binary or UUID fields, audit fields, or password-ish fields.
    Capped at ``KARNI_ADMIN_LIST_DISPLAY_MAX`` (default 6); falls back to
    ``["__str__"]`` when nothing qualifies.
    """
    max_items = _int_setting("KARNI_ADMIN_LIST_DISPLAY_MAX", DEFAULT_LIST_DISPLAY_MAX)
    names: list[str] = []
    for field in model._meta.fields:
        if _skip_always(field):
            continue
        if field.primary_key and isinstance(field, models.UUIDField):
            continue
        if isinstance(field, _DISPLAY_EXCLUDED_TYPES):
            continue
        if isinstance(field, _DISPLAY_INCLUDED_TYPES):
            names.append(field.name)
        if len(names) >= max_items:
            break
    return names or ["__str__"]


def derive_list_filter(model: type[models.Model]) -> list[FilterSpec]:
    """Derive ``list_filter``: booleans, choice fields, FKs, then date fields.

    FKs become ``(name, admin.RelatedOnlyFieldListFilter)`` tuples. Capped at
    ``KARNI_ADMIN_LIST_FILTER_MAX`` (default 6). Soft-delete models get
    :class:`karni.admin.soft_delete.SoftDeleteListFilter` prepended, not
    counted against the cap.
    """
    max_items = _int_setting("KARNI_ADMIN_LIST_FILTER_MAX", DEFAULT_LIST_FILTER_MAX)
    booleans: list[FilterSpec] = []
    with_choices: list[FilterSpec] = []
    foreign_keys: list[FilterSpec] = []
    dates: list[FilterSpec] = []
    for field in model._meta.fields:
        if _skip_always(field):
            continue
        if isinstance(field, models.BooleanField):
            booleans.append(field.name)
        elif field.choices:
            with_choices.append(field.name)
        elif isinstance(field, models.ForeignKey):
            foreign_keys.append((field.name, admin.RelatedOnlyFieldListFilter))
        elif isinstance(field, models.DateField):
            dates.append(field.name)
    entries: list[FilterSpec] = [*booleans, *with_choices, *foreign_keys, *dates][:max_items]
    if issubclass(model, SoftDeleteModel):
        entries.insert(0, SoftDeleteListFilter)
    return entries


def derive_search_fields(model: type[models.Model]) -> list[str]:
    """Derive ``search_fields``: char-ish and text fields without choices.

    Skips password-ish and audit fields; capped at ``KARNI_ADMIN_SEARCH_MAX``
    (default 5). Non-empty search fields also make the model an autocomplete
    target (see :func:`derive_autocomplete_fields`).
    """
    max_items = _int_setting("KARNI_ADMIN_SEARCH_MAX", DEFAULT_SEARCH_MAX)
    names = [
        field.name
        for field in model._meta.fields
        if isinstance(field, models.CharField | models.TextField)
        and not field.choices
        and not _skip_always(field)
    ]
    return names[:max_items]


def derive_date_hierarchy(model: type[models.Model]) -> str | None:
    """Derive ``date_hierarchy``: first declared non-audit date field.

    Falls back to ``created_at`` when the model has it, else ``None``.
    """
    field_names: list[str] = []
    for field in model._meta.fields:
        field_names.append(field.name)
        if isinstance(field, models.DateField) and field.name not in AUDIT_FIELDS:
            return field.name
    return "created_at" if "created_at" in field_names else None


def derive_readonly_fields(model: type[models.Model]) -> tuple[str, ...]:
    """Derive ``readonly_fields``: the model's audit fields, declaration order.

    ``AdminMeta.read_only`` entries are appended on top at
    :meth:`karni.admin.base.KarniAdminMixin.__init__` time (via the generated
    class's ``karni_read_only`` attribute).
    """
    return tuple(f.name for f in model._meta.fields if f.name in AUDIT_FIELDS)


def derive_list_select_related(
    model: type[models.Model],
    list_display: list[str] | None = None,
) -> tuple[str, ...]:
    """Derive ``list_select_related``: FK names present in ``list_display``.

    Prevents the classic changelist N+1. Pass the effective ``list_display``
    (e.g. from ``AdminMeta``); when omitted it is derived first.
    """
    effective = list_display if list_display is not None else derive_list_display(model)
    fk_names = {f.name for f in model._meta.fields if isinstance(f, models.ForeignKey)}
    return tuple(name for name in effective if isinstance(name, str) and name in fk_names)


def derive_autocomplete_fields(model: type[models.Model], site: admin.AdminSite) -> list[str]:
    """Derive ``autocomplete_fields``: relations whose target can be searched.

    A FK/M2M field qualifies only when its target model is registered on the
    same ``site`` with non-empty ``search_fields`` at the time this runs —
    otherwise the field keeps Django's default widget (avoids ``admin.E039``/
    ``admin.E040``). ``autodiscover()`` applies this in a second pass, after
    every registration, so targets are known; the pass only touches
    karni-created admin classes.
    """
    names: list[str] = []
    relations: list[models.Field] = [*model._meta.fields, *model._meta.many_to_many]
    for field in relations:
        if not isinstance(field, models.ForeignKey | models.ManyToManyField):
            continue
        if _skip_always(field):
            continue
        target = field.remote_field.model
        target_admin: Any = site._registry.get(target)
        if target_admin is not None and target_admin.search_fields:
            names.append(field.name)
    return names
