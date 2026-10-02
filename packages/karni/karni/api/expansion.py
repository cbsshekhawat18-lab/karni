"""Relation expansion for Karni API endpoints.

Clients opt into embedded related objects with the ``?expand=`` query
parameter: a comma-separated list of relation names, nested with dots
(``?expand=venue,organizer`` or ``?expand=organizer.groups``). The parameter
may be repeated; all values are merged. Expansion drives two things:

* nested read-only serializers (:func:`karni.api.serializers.build_serializer`),
* automatic ``select_related`` / ``prefetch_related`` on the queryset
  (:meth:`karni.api.viewsets.BaseViewSet.get_queryset` via
  :func:`related_lookups`).

Override / escape hatch: a viewset restricts or aliases what may be expanded
with ``expandable_fields`` (a mapping of client-facing expand key to model
relation name; reverse relations are only expandable when explicitly listed
there and require a ``related_name``). The depth guard is the
``KARNI_API_MAX_EXPAND_DEPTH`` setting (default ``2``), overridable per
viewset with ``expand_depth``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db.models import Field, ForeignKey, ManyToManyField, Model
from rest_framework.exceptions import ValidationError

__all__ = [
    "auto_expandable_fields",
    "collect_expand_param",
    "effective_max_depth",
    "related_lookups",
    "validate_expand",
]

DEFAULT_MAX_EXPAND_DEPTH = 2
"""Fallback for ``settings.KARNI_API_MAX_EXPAND_DEPTH`` when it is unset."""


#: Audit FKs from ``AuditedModel``; never auto-expandable.
AUDIT_RELATIONS = frozenset({"created_by", "updated_by"})


def auto_expandable_fields(model: type[Model]) -> dict[str, str]:
    """Return the automatically expandable relations of ``model``.

    Every forward ``ForeignKey``, ``OneToOneField`` and ``ManyToManyField``
    is expandable under its own field name (an identity mapping of expand key
    to relation name). Reverse relations are never included automatically, nor
    are the ``AuditedModel`` fields ``created_by``/``updated_by`` — expanding them
    would embed user records in every response; list them in
    ``expandable_fields`` to opt in deliberately.

    Override / escape hatch: set ``expandable_fields`` on the viewset to
    replace this mapping entirely — restrict keys, alias them, or add reverse
    relations (which must carry an explicit ``related_name``).
    """
    result: dict[str, str] = {}
    for field in model._meta.get_fields():
        if getattr(field, "auto_created", False):
            continue
        if field.name in AUDIT_RELATIONS:
            continue
        if isinstance(field, ForeignKey | ManyToManyField):
            result[field.name] = field.name
    return result


def collect_expand_param(request: Any) -> tuple[str, ...]:
    """Collect the raw ``?expand=`` values from ``request``.

    The parameter may be given multiple times and each value may itself be a
    comma-separated list; everything is merged, stripped and de-duplicated
    while preserving first-seen order. Requests without query parameters
    (including drf-spectacular's mocked schema-generation requests) safely
    yield an empty tuple.
    """
    params = getattr(request, "query_params", None)
    if params is None:
        params = getattr(request, "GET", None)
    if params is None:
        return ()
    getlist = getattr(params, "getlist", None)
    if callable(getlist):
        raw_values: Iterable[str] = getlist("expand")
    else:
        value = params.get("expand") if hasattr(params, "get") else None
        raw_values = [value] if value else []
    return _split_values(raw_values)


def effective_max_depth(viewset: Any = None) -> int:
    """Return the expansion depth limit that applies to ``viewset``.

    A positive ``expand_depth`` on the viewset wins; otherwise the
    ``KARNI_API_MAX_EXPAND_DEPTH`` setting applies (default
    :data:`DEFAULT_MAX_EXPAND_DEPTH`).
    """
    view_depth = int(getattr(viewset, "expand_depth", 0) or 0)
    if view_depth > 0:
        return view_depth
    return int(getattr(settings, "KARNI_API_MAX_EXPAND_DEPTH", DEFAULT_MAX_EXPAND_DEPTH))


def validate_expand(viewset: Any, raw: str | Iterable[str] | None) -> frozenset[str]:
    """Validate raw expand input against ``viewset`` and resolve it.

    ``raw`` is a comma-separated string, an iterable of such strings (e.g.
    the result of :func:`collect_expand_param`), or ``None``. Validation is
    per dotted level: the first segment of each path is checked against the
    viewset's allowed expands (``expandable_fields`` or
    :func:`auto_expandable_fields` of its model) and every deeper segment
    against the automatic expands of the model reached so far.

    Returns the validated paths with each top-level alias resolved to its
    model relation name, ready for serializer generation and
    :func:`related_lookups`.

    :raises rest_framework.exceptions.ValidationError: (HTTP 400) for an
        unknown key — the message lists the allowed keys at the failing
        level — or for a path deeper than :func:`effective_max_depth` (the
        unbounded-expansion guard).
    """
    paths = _split_values([raw] if isinstance(raw, str) else (raw or []))
    if not paths:
        return frozenset()
    model = _viewset_model(viewset)
    max_depth = effective_max_depth(viewset)
    top_allowed: Mapping[str, str] = getattr(
        viewset, "expandable_fields", None
    ) or auto_expandable_fields(model)
    resolved: set[str] = set()
    for path in paths:
        segments = path.split(".")
        if any(not segment for segment in segments):
            raise ValidationError({"expand": [f"Malformed expand path {path!r}."]})
        if len(segments) > max_depth:
            raise ValidationError(
                {
                    "expand": [
                        f"Expand path {path!r} is {len(segments)} levels deep; the "
                        f"maximum allowed depth is {max_depth}."
                    ]
                }
            )
        current_model = model
        allowed: Mapping[str, str] = top_allowed
        resolved_segments: list[str] = []
        for segment in segments:
            if segment not in allowed:
                allowed_keys = ", ".join(sorted(allowed)) or "(none)"
                raise ValidationError(
                    {
                        "expand": [
                            f"Unknown expand key {segment!r} in {path!r}. Allowed keys "
                            f"at this level: {allowed_keys}."
                        ]
                    }
                )
            relation = allowed[segment]
            field = _relation_field(current_model, relation)
            if field is None:
                raise ValidationError(
                    {
                        "expand": [
                            f"Expand key {segment!r} in {path!r} does not map to a "
                            f"relation on {current_model.__name__}."
                        ]
                    }
                )
            resolved_segments.append(relation)
            current_model = field.related_model
            allowed = auto_expandable_fields(current_model)
        resolved.add(".".join(resolved_segments))
    return frozenset(resolved)


def related_lookups(model: type[Model], expand: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split validated expand paths into query-optimisation lookups.

    Returns ``(select_related_paths, prefetch_related_paths)`` for ``model``:
    a path whose every segment is a forward ``ForeignKey``/``OneToOneField``
    goes to ``select_related``; a path containing any many-to-many or reverse
    segment goes — whole — to ``prefetch_related`` (Django populates every
    level of a prefetched path, including leading foreign keys). Paths that
    do not resolve to relations are skipped silently, so this never raises
    for input that :func:`validate_expand` accepted.
    """
    select: list[str] = []
    prefetch: list[str] = []
    for path in sorted(expand):
        segments = path.split(".")
        current: type[Model] | None = model
        forward_fk_only = True
        for segment in segments:
            field = _relation_field(current, segment) if current is not None else None
            if field is None:
                current = None
                break
            if not isinstance(field, ForeignKey):
                forward_fk_only = False
            current = field.related_model
        if current is None:
            continue
        lookup = "__".join(segments)
        if forward_fk_only:
            select.append(lookup)
        else:
            prefetch.append(lookup)
    return select, prefetch


def _split_values(values: Iterable[str | None]) -> tuple[str, ...]:
    """Comma-split, strip and de-duplicate ``values``, keeping order."""
    seen: set[str] = set()
    collected: list[str] = []
    for value in values:
        if value is None:
            continue
        for part in str(value).split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                collected.append(cleaned)
    return tuple(collected)


def _viewset_model(viewset: Any) -> type[Model]:
    """Resolve the model a viewset serves, mirroring ``BaseViewSet.get_model``."""
    get_model = getattr(viewset, "get_model", None)
    if callable(get_model):
        return get_model()
    model = getattr(viewset, "model", None)
    if model is None:
        model = getattr(getattr(viewset, "queryset", None), "model", None)
    if model is None:
        raise ImproperlyConfigured(
            f"{type(viewset).__name__} exposes neither 'model' nor 'queryset'; "
            "expansion cannot be validated."
        )
    return model


def _relation_field(model: type[Model], name: str) -> Any | None:
    """Return the relation field ``name`` of ``model``, or ``None``.

    Covers forward fields and reverse accessors alike; non-relations resolve
    to ``None``.
    """
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        return None
    if not getattr(field, "is_relation", False) or field.related_model is None:
        return None
    return field


def is_forward_relation(field: Any) -> bool:
    """True when ``field`` is a forward relation (FK/O2O/M2M), not a reverse one."""
    return isinstance(field, Field)
