"""Automatic ``ModelSerializer`` generation for Karni API endpoints.

:func:`build_serializer` turns a model class into a fully configured DRF
serializer so viewsets need no hand-written serializer for the common case.
Behaviour is steered by an inner ``class APIMeta:`` on the model:

``fields``
    Explicit field list (default: every concrete non-relation-through field
    plus declared many-to-many fields). Mutually exclusive with ``exclude``.
``exclude``
    Field names removed from the default list.
``read_only`` / ``write_only``
    Field names forced read-only / write-only. Both must be subsets of the
    effective field set. ``BaseModel``'s ``id`` / ``created_at`` /
    ``updated_at`` are *always* read-only.
``schema_name``
    Replaces the ``{CamelAppLabel}{Model}`` stem used for generated class
    (and therefore OpenAPI component) names.
``select`` / ``prefetch``
    Query hints for what the optimiser cannot see (a property listed in
    ``fields``): ``select_related`` / ``prefetch_related`` lookups applied
    wherever the model is rendered — see :mod:`karni.api.optimizer`.

Sensitive-field policy: a field named ``password`` is never exposed by the
automatic default, and for ``AbstractBaseUser`` / ``PermissionsMixin``
subclasses it is stripped even from an explicit ``APIMeta.fields`` while
``last_login`` / ``is_staff`` / ``is_superuser`` / ``is_active`` / ``groups``
/ ``user_permissions`` are forced read-only.

Relations serialize as writable primary keys by default; relations named in
``expand`` become nested read-only serializers built recursively (a cycle or
the depth limit stops nesting at the primary key). A writable relation only
accepts primary keys of rows the requester can read through the target
model's routed viewset (ADR 0001 Q2.5, see
:class:`KarniPrimaryKeyRelatedField`), and every related row a generated
serializer renders — expanded, or in a to-many list of primary keys — is one
the requester can read, on every response path (:mod:`karni.api.related`).

Override / escape hatch: set ``serializer_class`` on the viewset to bypass
generation entirely, declare ``APIMeta`` for per-model tweaks, or subclass
:class:`KarniModelSerializer` and generate from it in your own code.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Model, QuerySet
from django.db.models.manager import BaseManager
from django.test.signals import setting_changed
from rest_framework import serializers
from rest_framework.relations import (
    MANY_RELATION_KWARGS,
    ManyRelatedField,
    PrimaryKeyRelatedField,
)
from rest_framework.validators import UniqueTogetherValidator, UniqueValidator

from karni.api.expansion import DEFAULT_MAX_EXPAND_DEPTH, is_forward_relation
from karni.api.lifecycle import StateChoiceField, lifecycle_errors, serializer_field
from karni.api.related import readable_related, related_scope
from karni.exceptions import KarniImproperlyConfigured

__all__ = [
    "KarniListSerializer",
    "KarniManyRelatedField",
    "KarniModelSerializer",
    "KarniPrimaryKeyRelatedField",
    "build_serializer",
    "serializer_name",
]

USER_FORCED_READ_ONLY = frozenset(
    {"last_login", "is_staff", "is_superuser", "is_active", "groups", "user_permissions"}
)
"""Fields forced read-only on user-model serializers (sensitive-field policy)."""


class KarniPrimaryKeyRelatedField(PrimaryKeyRelatedField):
    """``PrimaryKeyRelatedField`` used by Karni-generated serializers.

    Two differences from the stock field:

    * **Scoped PK validation** (ADR 0001 Q2.5): :meth:`get_queryset` narrows
      the target model's default manager to the rows the requester may read
      through the target's routed viewset (its ``access.read`` and
      ``filter_queryset_for_user``; see
      :func:`karni.api.access.target_read_scope`). A PK outside that scope
      fails exactly like a PK that does not exist, so a client can neither
      link an object it cannot read nor probe for its existence. A target
      with no routed viewset has no row policy (default manager only); with
      no request in the serializer context nothing is narrowed.
    * drf-spectacular extensions annotate exactly these fields with the
      ``x-karni-relation`` vendor extension (see :mod:`karni.api.schema`).

    Override / escape hatch: set ``serializer_related_field`` on a
    :class:`KarniModelSerializer` subclass to swap the relation field class,
    or declare the field explicitly with your own ``queryset``.
    """

    def get_queryset(self) -> QuerySet[Any]:
        """The stock queryset narrowed to what the requester may read."""
        from karni.api.access import readable

        queryset: QuerySet[Any] = super().get_queryset()
        return readable(queryset, self.context.get("request"))

    @classmethod
    def many_init(cls, *args: Any, **kwargs: Any) -> KarniManyRelatedField:
        """Build a :class:`KarniManyRelatedField` wrapping this field."""
        list_kwargs: dict[str, Any] = {"child_relation": cls(*args, **kwargs)}
        for key in kwargs:
            if key in MANY_RELATION_KWARGS:
                list_kwargs[key] = kwargs[key]
        return KarniManyRelatedField(**list_kwargs)


class KarniManyRelatedField(ManyRelatedField):
    """``ManyRelatedField`` counterpart of :class:`KarniPrimaryKeyRelatedField`.

    Created by :meth:`KarniPrimaryKeyRelatedField.many_init` for to-many
    relations so schema generation can mark them ``{"many": true}``. The
    list it renders holds only the related rows the requester may read
    (:func:`karni.api.related.readable_related`), on every response path.
    """

    def to_representation(self, iterable: Any) -> list[Any]:
        return list(super().to_representation(readable_related(self.context, iterable)))


class KarniListSerializer(serializers.ListSerializer):
    """The ``many=True`` form of every generated serializer.

    Nested (an expanded to-many relation), it renders only the rows the
    requester may read. At the root (a page of rows), it first checks the
    related rows the page already holds that did not come through a read
    scope (a hint's join or prefetch) in one query per model, so the per-row
    checks that follow cost nothing (:mod:`karni.api.related`).
    """

    def to_representation(self, data: Any) -> list[Any]:
        iterable = data.all() if isinstance(data, BaseManager) else data
        if self.parent is not None:
            rows = readable_related(self.context, iterable)
        else:
            rows = list(iterable)
            _check_related(self.context, self.child, rows)
        return [self.child.to_representation(row) for row in rows]


def _check_related(context: Any, serializer: Any, rows: list[Any]) -> None:
    """Batch-check the related rows ``rows`` already hold for ``serializer``'s relation fields."""
    if related_scope(context) is None or not isinstance(serializer, serializers.Serializer):
        return
    held: list[Any] = []
    for relation in serializer.fields.values():
        attrs = list(getattr(relation, "source_attrs", None) or [])
        if getattr(relation, "write_only", False) or len(attrs) != 1:
            continue
        if isinstance(relation, ManyRelatedField | serializers.ListSerializer):
            for row in rows:
                manager = getattr(row, attrs[0], None)
                cached = manager.all()._result_cache if isinstance(manager, BaseManager) else None
                held.extend(cached or ())
        elif isinstance(relation, KarniModelSerializer):
            for row in rows:
                related = _cached_related(row, attrs[0])
                if related is not None:
                    held.append(related)
    readable_related(context, held)


def _cached_related(row: Any, name: str) -> Any | None:
    """The to-one row ``row.<name>`` already holds (joined or prefetched), else ``None``."""
    try:
        relation = row._meta.get_field(name)
    except (AttributeError, FieldDoesNotExist):
        return None
    if not hasattr(relation, "is_cached") or not relation.is_cached(row):
        return None
    return relation.get_cached_value(row)


class KarniModelSerializer(serializers.ModelSerializer):
    """Base class of every serializer produced by :func:`build_serializer`.

    Relations are rendered with :class:`KarniPrimaryKeyRelatedField` (and its
    to-many wrapper) so the OpenAPI schema can carry Karni's vendor
    extensions.

    Override / escape hatch: subclass this (or plain ``ModelSerializer``) and
    point the viewset's ``serializer_class`` at your class — an explicit
    ``serializer_class`` always wins over generation.
    """

    serializer_related_field = KarniPrimaryKeyRelatedField

    def get_attribute(self, instance: Any) -> Any:
        """Nested as an expanded to-one: the related row, or ``None`` when it is unreadable.

        Only called when this serializer is a field of another; the read
        scope check is :func:`karni.api.related.readable_related`.
        """
        value = super().get_attribute(instance)
        if self.source == "*" or not isinstance(value, Model):
            return value  # the parent row itself, or no row
        return value if readable_related(self.context, [value]) else None

    # field-level visibility (ADR 0002, P3)

    def visibility_user(self) -> Any | None:
        """The requesting user, or ``None`` outside a request (server-side use: every field)."""
        request = self.context.get("request") if isinstance(self.context, dict) else None
        return getattr(request, "user", None) if request is not None else None

    def get_fields(self) -> dict[str, Any]:
        """The generated fields minus what ``Karni.field_roles`` hides from this user.

        A field the user may not read is **absent** (never ``null``: that
        would say the field exists). A field the user may read but not write
        is published read-only, and :meth:`to_internal_value` still rejects
        an explicit attempt to send it, naming the roles that may.
        """
        from karni.accounts.visibility import hidden_fields, protected_fields

        fields = super().get_fields()
        user = self.visibility_user()
        if user is None:
            return fields
        model = self.Meta.model
        hidden = hidden_fields(model, user)
        protected = protected_fields(model, user)
        for name in list(fields):
            if name in hidden:
                if name in protected or fields[name].read_only:
                    del fields[name]
                else:
                    fields[name].write_only = True  # may write, may not read back
            elif name in protected and not fields[name].read_only:
                fields[name].read_only = True
                fields[name].required = False
        return fields

    def to_internal_value(self, data: Any) -> Any:
        from karni.accounts.visibility import allowed_roles, hidden_fields, protected_fields

        user = self.visibility_user()
        if user is not None and isinstance(data, dict):
            model = self.Meta.model
            hidden = hidden_fields(model, user)
            refused = {
                name
                for name in protected_fields(model, user)
                if name in data and name not in hidden and name in self.fields
            }
            if refused:
                raise serializers.ValidationError(
                    {
                        name: [
                            f"Only roles {', '.join(allowed_roles(model, name))} may change {name}."
                        ]
                        for name in sorted(refused)
                    }
                )
        return super().to_internal_value(data)

    def build_standard_field(self, field_name: str, model_field: Any) -> tuple[Any, dict[str, Any]]:
        """Publish a model field's plain default in the schema (``default:``).

        DRF leaves a model default to the model, so the OpenAPI document never
        says what a field starts as; forms then cannot prefill it. A literal
        default (``"draft"``, ``True``) becomes the serializer field's default,
        which drf-spectacular emits. Callable defaults (``uuid4``, ``now``)
        stay with the model.
        """
        field_class, kwargs = super().build_standard_field(field_name, model_field)
        live_unique = _live_unique_validator(model_field)
        if live_unique is not None:
            kwargs["validators"] = [
                v for v in kwargs.get("validators", []) if not isinstance(v, UniqueValidator)
            ] + [live_unique]
        lifecycle = serializer_field(model_field)  # StateField / range fields (karni.api.lifecycle)
        if lifecycle is not None:
            field_class = lifecycle[0]
            kwargs.update(lifecycle[1])
            if field_class is not StateChoiceField:
                kwargs.pop("choices", None)
        default = model_field.default if model_field.has_default() else None
        if (
            model_field.has_default()
            and not callable(default)
            and not kwargs.get("read_only")
            and not kwargs.get("required")
            and "default" not in kwargs
        ):
            kwargs["default"] = default
        return field_class, kwargs

    def get_unique_together_validators(self) -> list[Any]:
        """DRF's, plus one per multi-field ``LiveUniqueConstraint`` (live rows only).

        DRF skips a constraint whose condition names a field the serializer
        lacks (``deleted_at``); the default manager already hides deleted
        rows, so checking it is exactly the constraint's condition.
        """
        from karni.fields.constraints import LiveUniqueConstraint

        validators = list(super().get_unique_together_validators())
        model = self.Meta.model
        writable = {name for name, f in self.fields.items() if not f.read_only}
        for constraint in model._meta.constraints:
            names = list(constraint.fields) if isinstance(constraint, LiveUniqueConstraint) else []
            if len(names) < 2 or constraint.extra_condition is not None:
                continue
            if set(names) <= writable:
                validators.append(
                    UniqueTogetherValidator(queryset=model._default_manager.all(), fields=names)
                )
        return validators

    def create(self, validated_data: dict[str, Any]) -> Any:
        self.run_lifecycle_checks(validated_data)
        self.run_model_clean(validated_data)
        return super().create(validated_data)

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        self.run_lifecycle_checks(validated_data, instance)
        self.run_model_clean(validated_data, instance)
        return super().update(instance, validated_data)

    def run_lifecycle_checks(self, validated_data: dict[str, Any], instance: Any = None) -> None:
        """A StateField change the lifecycle forbids is a 400 on the field (``E980`` / ``E982``).

        Checked against the state the row was loaded with; the save repeats
        the check and makes the ``UPDATE`` conditional, so a concurrent
        change still cannot slip through. Override to skip or extend it.
        """
        errors = lifecycle_errors(self.Meta.model, validated_data, instance)
        if errors:
            raise serializers.ValidationError(errors)

    def run_model_clean(self, validated_data: dict[str, Any], instance: Any = None) -> None:
        """Run ``Model.clean()`` on the would-be row; its errors become a 400.

        The probe carries every validated value, including what the viewset
        stamps on save (owner fields), so a cross-field rule in ``clean()``
        is the one place a domain invariant lives — no serializer needed.

        Override / escape hatch: ``class APIMeta: validate = False`` on the
        model skips it; override this method for another validation step.
        """
        model = self.Meta.model
        if getattr(getattr(model, "APIMeta", None), "validate", True) is False:
            return
        concrete = {field.name for field in model._meta.concrete_fields}
        probe = copy.copy(instance) if instance is not None else model()
        for name, value in validated_data.items():
            if name in concrete:
                setattr(probe, name, value)
        try:
            probe.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(serializers.as_serializer_error(exc)) from exc


def _live_unique_validator(model_field: Any) -> UniqueValidator | None:
    """The uniqueness check for a Karni unique field or a one-field ``LiveUniqueConstraint``.

    DRF derives none for them (the constraint names ``deleted_at`` or an
    expression), so a duplicate would reach the database as an IntegrityError
    instead of a 400. The default manager hides deleted rows, matching the
    partial index; a case-insensitive field compares with ``iexact``.
    """
    from karni.fields.constraints import LiveUniqueConstraint

    model = getattr(model_field, "model", None)
    if model is None:
        return None
    single_live = any(
        isinstance(c, LiveUniqueConstraint)
        and list(c.fields) == [model_field.name]
        and c.extra_condition is None
        for c in model._meta.constraints
    )
    if not (getattr(model_field, "karni_unique", False) or single_live):
        return None
    lookup = "iexact" if getattr(model_field, "case_insensitive_unique", False) else "exact"
    return UniqueValidator(
        queryset=model._default_manager.all(),
        lookup=lookup,
        message=(
            f"A {model._meta.verbose_name} with this {model_field.verbose_name} already exists."
        ),
    )


def serializer_name(model: type[Model], expand: frozenset[str] = frozenset()) -> str:
    """Return the deterministic class name for a generated serializer.

    The stem is ``APIMeta.schema_name`` if declared, otherwise the
    camel-cased app label followed by the model name (app-qualified so names
    never collide across apps). Expanded variants append the sorted expand
    paths — each path camel-cased per dotted segment, paths joined with
    ``_`` so ``{"a", "b"}`` and ``{"a.b"}`` stay distinct — plus an
    ``Expanded`` marker.

    Override / escape hatch: declare ``APIMeta.schema_name`` on the model.
    """
    api_meta = getattr(model, "APIMeta", None)
    stem = getattr(api_meta, "schema_name", None) or (
        f"{_camel(model._meta.app_label)}{model.__name__}"
    )
    if not expand:
        return f"{stem}Serializer"
    joined = "_".join(
        "".join(_camel(segment) for segment in path.split(".")) for path in sorted(expand)
    )
    return f"{stem}_{joined}ExpandedSerializer"


def build_serializer(
    model: type[Model],
    *,
    expand: frozenset[str] = frozenset(),
    _seen: tuple[type[Model], ...] = (),
    max_depth: int | None = None,
    read_only: Iterable[str] = (),
) -> type[serializers.ModelSerializer]:
    """Build (or fetch from cache) the generated serializer for ``model``.

    :param model: the model to serialize.
    :param expand: validated relation paths (see
        :func:`karni.api.expansion.validate_expand`) to embed as nested
        read-only serializers instead of primary keys.
    :param _seen: internal recursion guard — the models already on the
        nesting path. Expanding into a model present here (a cycle) stops at
        the primary key. Callers pass a non-empty value only when they want
        an uncached nested build.
    :param max_depth: nesting depth limit; ``None`` reads the
        ``KARNI_API_MAX_EXPAND_DEPTH`` setting (default 2). Reaching the
        limit stops nesting at the primary key.
    :param read_only: extra top-level fields forced read-only on top of the
        ``APIMeta`` policy — ``BaseViewSet`` passes the owner fields of its
        ``access`` declaration (``Owned("organizer")`` in ``write``), which
        are stamped server-side. Names outside the field set are ignored.

    Caching: only top-level builds (empty ``_seen``) are cached, keyed by
    ``(model, expand, effective max depth, read_only)``; nested and guard-truncated
    variants are always built fresh. Cache writes are last-write-wins under
    the GIL and generated classes are pure (no mutable class state), so
    concurrent builds are safe. ``build_serializer.cache_clear()`` empties
    the cache; it is also emptied automatically when ``override_settings``
    changes ``KARNI_API_MAX_EXPAND_DEPTH``.

    Override / escape hatch: an explicit ``serializer_class`` on the viewset
    bypasses this function entirely; ``APIMeta`` on the model steers what is
    generated.
    """
    expand = frozenset(expand)
    forced = frozenset(read_only)
    if _seen:
        return _build_serializer_class(
            model, expand, tuple(_seen), _resolve_max_depth(max_depth), forced
        )
    depth = _resolve_max_depth(max_depth)
    key = (model, expand, depth, forced)
    cached = _SERIALIZER_CACHE.get(key)
    if cached is not None:
        return cached
    built = _build_serializer_class(model, expand, (), depth, forced)
    _SERIALIZER_CACHE[key] = built
    return built


_SERIALIZER_CACHE: dict[
    tuple[type[Model], frozenset[str], int, frozenset[str]], type[serializers.ModelSerializer]
] = {}


def _cache_clear() -> None:
    """Drop every cached generated serializer class.

    Public as ``build_serializer.cache_clear()``. Call it after mutating a
    model's ``APIMeta`` at runtime (tests do; production code should not).
    """
    _SERIALIZER_CACHE.clear()


build_serializer.cache_clear = _cache_clear  # type: ignore[attr-defined]


def _reset_cache_on_setting_change(sender: object, setting: str, **kwargs: Any) -> None:
    """Reset the serializer cache when the expansion depth setting changes."""
    if setting == "KARNI_API_MAX_EXPAND_DEPTH":
        _SERIALIZER_CACHE.clear()


setting_changed.connect(
    _reset_cache_on_setting_change, dispatch_uid="karni.api.serializers.cache_reset"
)


def _resolve_max_depth(max_depth: int | None) -> int:
    """Return the effective nesting depth limit."""
    if max_depth is not None:
        return int(max_depth)
    return int(getattr(settings, "KARNI_API_MAX_EXPAND_DEPTH", DEFAULT_MAX_EXPAND_DEPTH))


def _camel(value: str) -> str:
    """Camel-case a snake_case name (``karni_accounts`` → ``KarniAccounts``)."""
    return "".join(part[:1].upper() + part[1:] for part in value.split("_") if part)


def _is_user_model(model: type[Model]) -> bool:
    """True for ``AbstractBaseUser`` / ``PermissionsMixin`` subclasses."""
    from django.contrib.auth.base_user import AbstractBaseUser
    from django.contrib.auth.models import PermissionsMixin

    return issubclass(model, AbstractBaseUser | PermissionsMixin)


def _default_field_names(model: type[Model]) -> list[str]:
    """Default field set: concrete fields plus declared M2Ms, sans password.

    Generated columns (a ``karni.fields.SearchField``) are left out: they are
    an index of the data, not data.
    """
    names = [
        field.name
        for field in model._meta.concrete_fields
        if not getattr(field, "generated", False)
    ]
    names += [field.name for field in model._meta.many_to_many]
    return [name for name in names if name not in ("password", "deleted_at")]


def _effective_field_names(model: type[Model], api_meta: Any) -> list[str]:
    """Resolve the serializer's field list from ``APIMeta`` (or defaults)."""
    declared = getattr(api_meta, "fields", None)
    excluded = getattr(api_meta, "exclude", None)
    if declared is not None and excluded is not None:
        raise KarniImproperlyConfigured(
            f"{model.__name__}.APIMeta declares both 'fields' and 'exclude', but "
            "they are mutually exclusive.",
            code="E122",
        )
    if declared is not None:
        names = list(declared)
    else:
        names = _default_field_names(model)
        if excluded is not None:
            excluded_set = set(excluded)
            names = [name for name in names if name not in excluded_set]
    if _is_user_model(model):
        names = [name for name in names if name != "password"]
    return names


def _extra_kwargs(
    model: type[Model],
    api_meta: Any,
    field_names: Iterable[str],
    forced_read_only: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Any]]:
    """Build ``Meta.extra_kwargs`` enforcing the read-only/write-only policy."""
    effective = set(field_names)
    read_only = list(getattr(api_meta, "read_only", ()) or ())
    write_only = list(getattr(api_meta, "write_only", ()) or ())
    for label, listed in (("read_only", read_only), ("write_only", write_only)):
        unknown = sorted(set(listed) - effective)
        if unknown:
            raise KarniImproperlyConfigured(
                f"{model.__name__}.APIMeta.{label} names fields outside the "
                f"serializer's field set: {', '.join(unknown)}.",
                code="E123",
            )
    always_read_only = {
        model._meta.pk.name,
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "deleted_at",
    } & effective
    forced = (USER_FORCED_READ_ONLY & effective) if _is_user_model(model) else set()
    read_only_set = set(read_only) | always_read_only | forced | (forced_read_only & effective)
    overlap = sorted(read_only_set & set(write_only))
    if overlap:
        raise KarniImproperlyConfigured(
            f"{model.__name__}.APIMeta marks fields as both read-only and "
            f"write-only: {', '.join(overlap)}.",
            code="E124",
        )
    kwargs: dict[str, dict[str, Any]] = {
        name: {"read_only": True} for name in sorted(read_only_set)
    }
    for name in write_only:
        kwargs[name] = {"write_only": True}
    return kwargs


def _group_expand(expand: frozenset[str]) -> dict[str, set[str]]:
    """Group expand paths by their first segment: ``a.b`` → ``{"a": {"b"}}``."""
    groups: dict[str, set[str]] = {}
    for path in expand:
        head, _, rest = path.partition(".")
        bucket = groups.setdefault(head, set())
        if rest:
            bucket.add(rest)
    return groups


def _relation_field_or_raise(model: type[Model], name: str) -> Any:
    """Return the relation field ``name`` of ``model`` or raise loudly."""
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist as exc:
        raise KarniImproperlyConfigured(
            f"Cannot expand {name!r} on {model.__name__}: no such field.", code="E125"
        ) from exc
    if not getattr(field, "is_relation", False) or field.related_model is None:
        raise KarniImproperlyConfigured(
            f"Cannot expand {name!r} on {model.__name__}: it is not a relation.", code="E125"
        )
    return field


def _build_serializer_class(
    model: type[Model],
    expand: frozenset[str],
    seen: tuple[type[Model], ...],
    max_depth: int,
    forced_read_only: frozenset[str] = frozenset(),
) -> type[serializers.ModelSerializer]:
    """Assemble the serializer class (uncached workhorse)."""
    api_meta = getattr(model, "APIMeta", None)
    field_names = _effective_field_names(model, api_meta)
    extra_kwargs = _extra_kwargs(model, api_meta, field_names, forced_read_only)
    effective = set(field_names)
    meta_fields = list(field_names)
    declared: dict[str, Any] = {}

    for head, sub_paths in sorted(_group_expand(expand).items()):
        field = _relation_field_or_raise(model, head)
        forward = is_forward_relation(field)
        if forward and head not in effective:
            # Excluded forward relation: expansion never leaks it back in.
            continue
        related = field.related_model
        if related is model or related in seen or len(seen) + 1 > max_depth:
            # Cycle or depth guard: the representation stays at the PK
            # (reverse relations simply stay absent).
            continue
        nested_class = _build_serializer_class(
            related, frozenset(sub_paths), (*seen, model), max_depth
        )
        many = bool(getattr(field, "many_to_many", False) or getattr(field, "one_to_many", False))
        declared[head] = nested_class(read_only=True, many=many)
        extra_kwargs.pop(head, None)
        if not forward and head not in effective:
            meta_fields.append(head)

    meta = type(
        "Meta",
        (),
        {
            "model": model,
            "fields": meta_fields,
            "extra_kwargs": extra_kwargs,
            "list_serializer_class": KarniListSerializer,
        },
    )
    attrs: dict[str, Any] = {
        "Meta": meta,
        "__module__": __name__,
        "__doc__": (
            f"Auto-generated serializer for {model._meta.label}"
            + (f" expanding {', '.join(sorted(expand))}." if expand else ".")
            + " See karni.api.serializers.build_serializer."
        ),
        **declared,
    }
    return type(serializer_name(model, expand), (KarniModelSerializer,), attrs)
