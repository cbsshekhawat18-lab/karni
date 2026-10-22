"""Serializer-walking query optimiser (ADR 0001 Decision 3, Q3.1).

:func:`optimize` derives ``select_related`` / ``prefetch_related`` from the
serializer that will render a queryset — generated or hand-written, with or
without ``?expand=`` — so a list or detail endpoint costs a fixed number of
queries however many rows it returns. ``BaseViewSet`` calls it for every
``list`` and ``retrieve`` (step 4 of the read pipeline, after the access
scope); nothing in project code is needed.

What a serializer field turns into:

=============================================  =========================================
Field                                          Optimisation
=============================================  =========================================
PK relation over a forward FK/O2O              none (DRF reads the ``*_id`` column)
PK list over a to-many (``ManyRelatedField``)  ``Prefetch(s, queryset=<scope>.only(pk))``
nested serializer on a forward FK/O2O          ``select_related(s)``, recursing with prefix
nested serializer ``many=True``                ``Prefetch(s, queryset=optimize(<scope>, child))``
dotted ``source="venue.city.name"``            ``select_related("venue__city")``
any other field that reads a related object    ``select_related`` / full-row ``Prefetch``
``SerializerMethodField``, model property      opaque — use hints (below)
=============================================  =========================================

Every ``Prefetch`` queryset starts from the target model's default manager
(model-level scopes such as soft delete) narrowed by the target viewset's
read scope (ADR 0001 R3) — the ``scope`` callback. A to-one level whose
target scope narrows rows becomes a scoped ``Prefetch`` instead of a join, so
an unreadable target renders as ``null`` (Decision 2, Q2.5).

Hints for what the walker cannot see — merged, never replacing the derived
lookups: ``APIMeta.select`` / ``APIMeta.prefetch`` on a model (applied at
every level that model is rendered at) and ``select`` / ``prefetch``
arguments (``BaseViewSet.select_related`` / ``prefetch_related``). A hint
string is applied as written (model scopes apply, the target viewset's read
scope does not); a hinted ``Prefetch`` owns its subtree.

Override / escape hatches: ``optimize = False`` on a viewset (hints only),
override ``BaseViewSet.optimize_queryset()``, or call :func:`optimize`
yourself (e.g. in a custom action — ``BaseViewSet.paginated_response()``
already does).

What the walker cannot see it records as a :class:`BlindSpot` on the plan
(:func:`blind_spots`): a ``SerializerMethodField``, a model property or
method named by ``source``, a field reading the whole object, a serializer
with its own ``to_representation``. ``karni queries``
(:mod:`karni.api.diagnose`) reads them to say why a repeated query was not
prefetched and which hint fixes it.
"""

from __future__ import annotations

import inspect
import weakref
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model, Prefetch, QuerySet
from django.db.models.constants import LOOKUP_SEP
from rest_framework.fields import SerializerMethodField
from rest_framework.relations import ManyRelatedField, RelatedField
from rest_framework.serializers import BaseSerializer, ListSerializer, Serializer

from karni.exceptions import KarniImproperlyConfigured

__all__ = [
    "BlindSpot",
    "Plan",
    "TargetScope",
    "api_meta_hints",
    "blind_spots",
    "model_relation",
    "optimize",
    "plan_cache_clear",
    "plan_for",
    "planned_lookups",
    "validate_hints",
]

#: ``scope(target_model) -> (readable queryset, filtered)``; see the module docstring.
TargetScope = Callable[[type[Model]], tuple[QuerySet[Any], bool]]

type Hint = str | Prefetch


def _unscoped(model: type[Model]) -> tuple[QuerySet[Any], bool]:
    return model._default_manager.all(), False


# the plan


@dataclass(frozen=True)
class BlindSpot:
    """A serializer field whose reads the walker cannot derive lookups for.

    ``kind``: ``method`` (a ``SerializerMethodField``), ``property`` /
    ``callable`` (a model property or method named by ``source``),
    ``attribute`` (any other non-field attribute: a ``GenericForeignKey``,
    an annotation), ``object`` (a field given the whole object,
    ``source="*"``) or ``representation`` (a serializer that overrides
    ``to_representation``; ``field`` is then ``""``).
    """

    serializer: type[Any]
    field: str
    kind: str
    #: The model whose rows the serializer renders at this level.
    model: type[Model]
    #: The attribute the walker stopped at (``get_venue_city``, ``remaining``).
    attribute: str = ""
    #: The field's dotted source (``""`` for a method field).
    source: str = ""

    @property
    def label(self) -> str:
        """``EventSerializer.venue_city`` — how query origins name a field."""
        return (
            f"{self.serializer.__name__}.{self.field}" if self.field else self.serializer.__name__
        )


@dataclass
class Plan:
    """What rendering one serializer reads from ``model``, relation by relation.

    ``to_one`` / ``to_many`` map an attribute name to its node. ``models`` is
    every model the representation reads (used for cache invalidation).
    ``blind`` lists what this level's walk could not see (:class:`BlindSpot`).
    """

    model: type[Model]
    to_one: dict[str, ToOne] = field(default_factory=dict)
    to_many: dict[str, ToMany] = field(default_factory=dict)
    blind: list[BlindSpot] = field(default_factory=list)

    @property
    def models(self) -> frozenset[type[Model]]:
        found = {self.model}
        for one in self.to_one.values():
            found |= one.plan.models
        for many in self.to_many.values():
            found |= many.plan.models if many.plan else {many.model}
        return frozenset(found)

    def one(self, name: str, model: type[Model], forward: bool) -> ToOne:
        node = self.to_one.get(name)
        if node is None:
            node = self.to_one[name] = ToOne(model, forward, Plan(model))
        return node

    def many(self, name: str, model: type[Model], only: tuple[str, ...]) -> ToMany:
        node = self.to_many.get(name)
        if node is None:
            node = self.to_many[name] = ToMany(model, only, None)
        elif node.only and not only:
            node.only = ()  # some field needs full rows
        elif node.only and only:
            node.only = tuple(dict.fromkeys((*node.only, *only)))
        return node


@dataclass
class ToOne:
    """A to-one relation that is read: joined or (if scoped/reverse) prefetched."""

    model: type[Model]
    forward: bool
    plan: Plan


@dataclass
class ToMany:
    """A to-many relation that is read: always one ``Prefetch``."""

    model: type[Model]
    #: ``()`` = full rows; otherwise ``.only(*fields)`` (PK lists).
    only: tuple[str, ...]
    plan: Plan | None

    def nested(self) -> Plan:
        if self.plan is None:
            self.plan = Plan(self.model)
        self.only = ()
        return self.plan


def _forward(relation: Any) -> bool:
    return not hasattr(relation, "get_accessor_name")  # only ForeignObjectRel has it


def model_relation(model: type[Model], name: str) -> Any | None:
    """The relation behind attribute ``name`` of ``model`` (forward field or reverse rel).

    ``None`` for columns (including a FK's ``*_id`` attname), properties,
    methods and ``GenericForeignKey`` — nothing the ORM can join or prefetch.
    """
    try:
        relation: Any = model._meta.get_field(name)
    except FieldDoesNotExist:
        relation = None
    if relation is not None:
        attribute = relation.name if _forward(relation) else relation.get_accessor_name()
        if attribute != name:
            relation = None if _forward(relation) else _reverse_by_accessor(model, name)
    else:
        relation = _reverse_by_accessor(model, name)
    if relation is None or not relation.is_relation or relation.related_model is None:
        return None
    return relation


def _reverse_by_accessor(model: type[Model], name: str) -> Any | None:
    for rel in model._meta.related_objects:
        if rel.get_accessor_name() == name:
            return rel
    return None


def _to_one(relation: Any) -> bool:
    return bool(relation.many_to_one or relation.one_to_one)


def _pk_only(field_obj: Any) -> bool:
    return (
        isinstance(field_obj, RelatedField)
        and not isinstance(field_obj, BaseSerializer)
        and field_obj.use_pk_only_optimization()
    )


def _pk_only_columns(relation: Any) -> tuple[str, ...]:
    """``.only()`` columns for a PK-list prefetch; ``()`` = full rows.

    Django matches prefetched rows to their parents through a column: M2M
    adds it itself, a reverse FK needs its FK column loaded, anything else
    (generic relations) gets full rows rather than a deferred-load per row.
    """
    if relation.many_to_many:
        return ("pk",)
    if not _forward(relation) and relation.one_to_many:
        return ("pk", relation.field.name)
    return ()


def _attribute_kind(model: type[Model], attr: str) -> str:
    """``""`` for a column (or a FK's ``*_id``); else what the walker cannot see into."""
    try:
        found: Any = model._meta.get_field(attr)
    except FieldDoesNotExist:
        found = None
    if found is not None:
        return "attribute" if found.is_relation and found.related_model is None else ""
    if attr in {getattr(f, "attname", "") for f in model._meta.concrete_fields}:
        return ""
    descriptor = inspect.getattr_static(model, attr, None)
    if isinstance(descriptor, property | cached_property):
        return "property"
    return "callable" if callable(descriptor) else "attribute"


def _blind(
    plan: Plan, serializer: BaseSerializer[Any], field_obj: Any, kind: str, attr: str
) -> None:
    source = "" if kind == "method" else str(getattr(field_obj, "source", "") or "")
    name = str(getattr(field_obj, "field_name", "") or "") if field_obj is not None else ""
    plan.blind.append(BlindSpot(type(serializer), name, kind, plan.model, attr, source))


def _walk(serializer: BaseSerializer[Any], plan: Plan) -> None:
    """Fill ``plan`` from the fields ``serializer`` renders (and note its blind spots)."""
    if isinstance(serializer, ListSerializer):
        serializer = serializer.child
    if type(serializer).to_representation is not Serializer.to_representation:
        _blind(plan, serializer, None, "representation", "to_representation")
    for field_obj in serializer.fields.values():
        if getattr(field_obj, "write_only", False):
            continue
        nested = field_obj.child if isinstance(field_obj, ListSerializer) else field_obj
        attrs = list(getattr(field_obj, "source_attrs", []) or [])
        if not attrs:
            if isinstance(nested, BaseSerializer):  # source="*": same object, same level
                _walk(nested, plan)
            elif isinstance(field_obj, SerializerMethodField):
                _blind(plan, serializer, field_obj, "method", str(field_obj.method_name))
            else:
                _blind(plan, serializer, field_obj, "object", "*")
            continue
        _walk_source(plan, attrs, field_obj, nested, serializer)


def _walk_source(
    plan: Plan, attrs: list[str], field_obj: Any, nested: Any, serializer: BaseSerializer[Any]
) -> None:
    current = plan
    for index, attr in enumerate(attrs):
        relation = model_relation(current.model, attr)
        if relation is None:
            # A column: nothing (more) to fetch. A property or method: opaque (noted at
            # the level it is read on, e.g. Venue for source="venue.label").
            kind = _attribute_kind(current.model, attr)
            if kind:
                _blind(current, serializer, field_obj, kind, attr)
            return
        last = index == len(attrs) - 1
        target: type[Model] = relation.related_model
        if _to_one(relation):
            if last and _forward(relation) and _pk_only(field_obj):
                return  # DRF reads the FK column
            node = current.one(attr, target, _forward(relation))
            if last and isinstance(nested, BaseSerializer):
                _walk(nested, node.plan)
            current = node.plan
            continue
        # to-many (M2M either side, reverse FK, generic relation)
        if last and isinstance(field_obj, ManyRelatedField) and _pk_only(field_obj.child_relation):
            current.many(attr, target, _pk_only_columns(relation))
        elif last and isinstance(nested, BaseSerializer):
            _walk(nested, current.many(attr, target, ()).nested())
        else:
            current.many(attr, target, ())
        return


_PLANS: weakref.WeakKeyDictionary[type[Any], dict[type[Model], Plan]] = weakref.WeakKeyDictionary()


def plan_for(
    serializer: type[BaseSerializer[Any]] | BaseSerializer[Any],
    model: type[Model],
    context: dict[str, Any] | None = None,
) -> Plan:
    """The :class:`Plan` for rendering ``model`` rows with ``serializer``.

    Cached per serializer class (generated serializers are themselves
    cached, so the class is stable); an instance is walked as given. A class
    is instantiated with ``context`` on a cache miss.
    """
    if isinstance(serializer, BaseSerializer):
        plan = Plan(model)
        _walk(serializer, plan)
        return plan
    per_model = _PLANS.setdefault(serializer, {})
    cached = per_model.get(model)
    if cached is None:
        cached = per_model[model] = Plan(model)
        _walk(serializer(context=context or {}), cached)
    return cached


def plan_cache_clear() -> None:
    """Forget every cached plan (after mutating a serializer class at runtime)."""
    _PLANS.clear()


def _levels_of(plan: Plan, prefix: str = "") -> Iterator[tuple[str, Plan]]:
    yield prefix, plan
    for name, one in plan.to_one.items():
        yield from _levels_of(one.plan, f"{prefix}{name}{LOOKUP_SEP}")
    for name, many in plan.to_many.items():
        if many.plan is not None:
            yield from _levels_of(many.plan, f"{prefix}{name}{LOOKUP_SEP}")


def blind_spots(
    serializer: type[BaseSerializer[Any]] | BaseSerializer[Any],
    model: type[Model],
    context: dict[str, Any] | None = None,
) -> list[tuple[str, BlindSpot]]:
    """What the walker could not see when planning ``serializer`` over ``model``.

    ``(prefix, spot)`` pairs: ``prefix`` is the lookup path to the level the
    spot is on (``""`` at the root, ``"tickettier_set__"`` one level down),
    so a hint for it is ``prefix + relation``.
    """
    plan = plan_for(serializer, model, context)
    return [(prefix, spot) for prefix, level in _levels_of(plan) for spot in level.blind]


def planned_lookups(
    serializer: type[BaseSerializer[Any]] | BaseSerializer[Any],
    model: type[Model],
    context: dict[str, Any] | None = None,
) -> frozenset[str]:
    """Every relation path the plan fetches (``"venue"``, ``"tickettier_set__tier"``)."""
    plan = plan_for(serializer, model, context)
    found: set[str] = set()
    for prefix, level in _levels_of(plan):
        found.update(prefix + name for name in (*level.to_one, *level.to_many))
    return frozenset(found)


# hints


def validate_hints(owner: str, name: str, value: Any) -> tuple[Hint, ...]:
    """``value`` as a tuple of lookups, or ``ImproperlyConfigured`` naming ``owner.name``."""
    if value is None:
        return ()
    if isinstance(value, str | Prefetch) or not isinstance(value, Sequence):
        raise KarniImproperlyConfigured(
            f'{owner}.{name} must be a list of lookups (e.g. ["venue"]), got {value!r}.',
            code="E120",
        )
    for item in value:
        if not isinstance(item, str | Prefetch):
            raise KarniImproperlyConfigured(
                f"{owner}.{name} entries must be lookup strings or Prefetch objects, got {item!r}.",
                code="E120",
            )
    return tuple(value)


def api_meta_hints(model: type[Model]) -> tuple[tuple[Hint, ...], tuple[Hint, ...]]:
    """``(APIMeta.select, APIMeta.prefetch)`` of ``model``, validated."""
    api_meta = getattr(model, "APIMeta", None)
    owner = f"{model.__name__}.APIMeta"
    select = validate_hints(owner, "select", getattr(api_meta, "select", None))
    if any(isinstance(item, Prefetch) for item in select):
        raise KarniImproperlyConfigured(f"{owner}.select takes lookup strings only.", code="E120")
    return select, validate_hints(owner, "prefetch", getattr(api_meta, "prefetch", None))


def _prefixed(hint: Hint, prefix: str) -> Hint:
    if not prefix:
        return hint
    if isinstance(hint, str):
        return prefix + hint
    return Prefetch(prefix + hint.prefetch_through, queryset=hint.queryset, to_attr=hint.to_attr)


# materialising


@dataclass
class _Lookups:
    select: list[str] = field(default_factory=list)
    prefetch: list[Hint] = field(default_factory=list)


def _materialize(plan: Plan, scope: TargetScope, prefix: str, out: _Lookups) -> None:
    select, prefetch = api_meta_hints(plan.model)
    out.select.extend(prefix + str(path) for path in select)
    out.prefetch.extend(_prefixed(hint, prefix) for hint in prefetch)
    for name, one in plan.to_one.items():
        lookup = prefix + name
        queryset, filtered = scope(one.model)
        if one.forward and not filtered:
            out.select.append(lookup)
            _materialize(one.plan, scope, lookup + LOOKUP_SEP, out)
        else:
            out.prefetch.append(Prefetch(lookup, queryset=_optimized(queryset, one.plan, scope)))
    for name, many in plan.to_many.items():
        queryset, _filtered = scope(many.model)
        if many.plan is not None:
            queryset = _optimized(queryset, many.plan, scope)
        elif many.only:
            queryset = queryset.only(*many.only)
        out.prefetch.append(Prefetch(prefix + name, queryset=queryset))


def _optimized(queryset: QuerySet[Any], plan: Plan, scope: TargetScope) -> QuerySet[Any]:
    out = _Lookups()
    _materialize(plan, scope, "", out)
    return _apply(queryset, out.select, (), out.prefetch)


def _levels(lookup: str) -> list[str]:
    parts = lookup.split(LOOKUP_SEP)
    return [LOOKUP_SEP.join(parts[: index + 1]) for index in range(len(parts))]


def _prefetch_to(lookup: Hint) -> str:
    return lookup.prefetch_to if isinstance(lookup, Prefetch) else lookup


def _apply(
    queryset: QuerySet[Any],
    select: Iterable[str],
    hints: Iterable[Hint],
    derived: Iterable[Hint],
) -> QuerySet[Any]:
    """Add ``select`` + prefetches; explicit lookups (existing, hints) win over derived ones.

    A derived prefetch is dropped when an explicit lookup touches the same
    level (Django refuses one level with two querysets) or when it sits under
    an explicit ``Prefetch`` (which owns its subtree).
    """
    hints = list(hints)
    explicit = [*queryset._prefetch_related_lookups, *hints]
    touched = {level for lookup in explicit for level in _levels(_prefetch_to(lookup))}
    owned = [lookup.prefetch_to + LOOKUP_SEP for lookup in explicit if isinstance(lookup, Prefetch)]
    kept: list[Hint] = []
    seen: set[str] = set()
    for lookup in derived:
        target = _prefetch_to(lookup)
        if target in touched or target in seen or target.startswith(tuple(owned)):
            continue
        seen.add(target)
        kept.append(lookup)
    paths = list(dict.fromkeys(select))
    if paths:
        queryset = queryset.select_related(*paths)
    if hints or kept:
        queryset = queryset.prefetch_related(*hints, *kept)
    return queryset


def optimize(
    queryset: QuerySet[Any],
    serializer: type[BaseSerializer[Any]] | BaseSerializer[Any] | None,
    *,
    scope: TargetScope | None = None,
    select: Sequence[str] = (),
    prefetch: Sequence[Hint] = (),
    context: dict[str, Any] | None = None,
) -> QuerySet[Any]:
    """Return ``queryset`` with the lookups ``serializer`` needs, plus hints.

    :param serializer: the serializer class (or instance) that will render
        the rows; ``None`` applies only the hints.
    :param scope: ``scope(model) -> (queryset, filtered)`` giving the rows of
        ``model`` the requester may read; default: the model's default
        manager, unfiltered. ``BaseViewSet`` passes the target viewsets'
        read scopes.
    :param select: extra ``select_related`` paths (merged).
    :param prefetch: extra ``prefetch_related`` lookups (merged; they win on
        conflicts).
    :param context: serializer context used to instantiate a class on a
        plan-cache miss.
    """
    scope = scope or _unscoped
    out = _Lookups()
    if serializer is not None:
        _materialize(plan_for(serializer, queryset.model, context), scope, "", out)
    else:
        root_select, root_prefetch = api_meta_hints(queryset.model)
        out.select.extend(str(path) for path in root_select)
        out.prefetch.extend(root_prefetch)
    return _apply(queryset, [*out.select, *select], prefetch, out.prefetch)
