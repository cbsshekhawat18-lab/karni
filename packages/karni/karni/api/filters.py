"""Karni's DRF filter backends: auto-derived filtersets and pluggable search.

Both backends are part of :class:`karni.api.viewsets.BaseViewSet`'s default
``filter_backends`` (and of the conf-level DRF defaults), in the order
``[KarniFilterBackend, OrderingFilter, KarniSearchFilter]`` — search runs
last so a ranking provider can either impose rank ordering (no explicit
``?ordering=``) or leave the explicitly requested ordering untouched.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, cast

import django_filters
from django.db import models
from django_filters.rest_framework import DjangoFilterBackend, FilterSet
from rest_framework.filters import BaseFilterBackend, OrderingFilter
from rest_framework.request import Request
from rest_framework.settings import api_settings

from karni.api.search import get_search_provider

__all__ = ["KarniFilterBackend", "KarniFilterSet", "KarniOrderingFilter", "KarniSearchFilter"]

_FILTERSET_CACHE: dict[tuple[type, type[models.Model]], type[FilterSet]] = {}
_NARROWED_CACHE: dict[tuple[type[FilterSet], frozenset[str]], type[FilterSet]] = {}


def searchable_fields(view: Any, request: Any) -> tuple[str, ...]:
    """``view.search_fields`` minus write-only fields and fields hidden from the requester.

    Search over a field the API never reads back is a membership oracle, so
    ``APIMeta.write_only`` fields never search (``karni.E131`` reports them
    at boot) and ``Karni.field_roles`` fields search only for a role that may
    read them.
    """
    from karni.accounts.visibility import visible

    fields = tuple(getattr(view, "search_fields", None) or ())
    model = getattr(view, "model", None)
    if model is None:
        model = getattr(getattr(view, "queryset", None), "model", None)
    if model is None or not fields:
        return fields
    write_only = frozenset(getattr(getattr(model, "APIMeta", None), "write_only", None) or ())
    user = getattr(request, "user", None)
    kept: list[str] = []
    for name in fields:
        sources = _search_sources(model, str(name))
        if sources is None:
            kept.append(name)
            continue
        # A SearchField searches all its sources at once: only when the requester may
        # read every one of them; otherwise search just the ones they may read.
        allowed = visible(model, user, [s for s in sources if s not in write_only])
        kept.extend([name] if list(allowed) == list(sources) else allowed)
    kept = [name for name in kept if str(name).lstrip("^=@$").split("__", 1)[0] not in write_only]
    return tuple(visible(model, user, kept))


def _search_sources(model: type[models.Model], name: str) -> list[str] | None:
    """The source fields of SearchField ``name``, or ``None`` when it is not one."""
    from karni.fields.search import SearchField

    try:
        field = model._meta.get_field(name)
    except Exception:  # noqa: BLE001 - a plain or related path
        return None
    return list(field.sources) if isinstance(field, SearchField) else None


def _api_filterable_names(model: type[models.Model]) -> frozenset[str]:
    """Field names eligible for filter derivation under the ``APIMeta`` policy.

    Mirrors the serializer-generation convention: the effective field set is
    ``APIMeta.fields`` when declared (else every concrete + many-to-many field
    except ``deleted_at``, which the generated API never exposes) minus
    ``APIMeta.exclude``. Fields in ``APIMeta.write_only`` and fields named
    ``"password"`` are never filterable — filters must not leak values the
    API never reads back.
    """
    api_meta = getattr(model, "APIMeta", None)
    declared = getattr(api_meta, "fields", None)
    excluded = frozenset(getattr(api_meta, "exclude", None) or ())
    write_only = frozenset(getattr(api_meta, "write_only", None) or ())
    if declared is not None:
        effective = frozenset(declared)
    else:
        effective = frozenset(
            field.name
            for field in (*model._meta.concrete_fields, *model._meta.many_to_many)
            if field.name != "deleted_at"
        )
    return frozenset(name for name in effective - excluded - write_only if name != "password")


class KarniFilterSet(FilterSet):
    """The base of every FilterSet Karni's backend builds: relation choices are the readable rows.

    django-filter turns a relation named in ``filterset_fields`` into a
    ``ModelChoiceFilter`` over every target row, so a value naming a row the
    requester cannot read filters (200) where a missing one is refused (400):
    an existence oracle. Here the choices are the target's readable rows
    (:func:`karni.api.access.readable`), so both are refused alike.

    Override / escape hatch: declare the filter yourself with a ``queryset``,
    or set ``filterset_base`` on a backend subclass.
    """

    @classmethod
    def filter_for_lookup(cls, field: Any, lookup_type: str) -> tuple[Any, dict[str, Any]]:
        filter_class, params = super().filter_for_lookup(field, lookup_type)
        queryset = params.get("queryset")
        if isinstance(queryset, models.QuerySet):
            params = {**params, "queryset": _readable_choices(queryset)}
        return filter_class, params


def _readable_choices(queryset: models.QuerySet[Any]) -> Any:
    """``queryset`` narrowed per request to what the requester may read (a filter's choices)."""

    def choices(request: Any) -> models.QuerySet[Any]:
        from karni.api.access import readable

        return readable(queryset.all(), request)

    return choices


class KarniFilterBackend(DjangoFilterBackend):
    """``DjangoFilterBackend`` that derives a sensible FilterSet automatically.

    For a :class:`~karni.api.viewsets.BaseViewSet` subclass (or any view
    setting ``karni_auto_filterset = True``) with no explicit
    ``filterset_class`` / ``filterset_fields``, a FilterSet is derived from the
    model and cached per (backend class, model):

    * fields with ``choices`` → a ``ChoiceFilter`` with ``exact`` only (the
      enum stays an enum);
    * Char/Slug/Email → ``exact`` and ``icontains``;
    * Integer/Float/Decimal/Date/DateTime → ``exact``, ``gte`` and ``lte``
      (parameters ``?field=``, ``?field__gte=``, ``?field__lte=``);
    * Boolean → ``exact``;
    * forward FK / OneToOne → ``exact`` against the target's primary-key type
      (for example ``UUIDFilter`` for UUID keys — never a
      ``ModelChoiceFilter`` that would render the whole related queryset);
    * everything else — Text, JSON, File/Image, binary, M2M — is skipped, as
      is any field outside the model's ``APIMeta`` policy (see
      :func:`_api_filterable_names`).

    On every other view this backend behaves exactly like the stock
    ``DjangoFilterBackend``, and an explicit ``filterset_class`` or
    ``filterset_fields`` (even an empty one) on any view always wins untouched.

    Override / escape hatch: set ``filterset_class`` / ``filterset_fields`` on
    the view for full control, or subclass this backend and override
    :attr:`lookup_map`, :attr:`pk_filter_map`, :meth:`filterable_fields` or
    :meth:`derive_filterset_class`, then point the view's ``filter_backends``
    (or ``REST_FRAMEWORK["DEFAULT_FILTER_BACKENDS"]``) at your subclass.
    Filtersets built from ``filterset_fields`` derive from
    :class:`KarniFilterSet` (``filterset_base``), so their relation choices
    are the requester's readable rows.
    """

    filterset_base = KarniFilterSet

    lookup_map: ClassVar[Mapping[type[models.Field], tuple[str, ...]]] = {
        models.CharField: ("exact", "icontains"),
        models.SlugField: ("exact", "icontains"),
        models.EmailField: ("exact", "icontains"),
        models.IntegerField: ("exact", "gte", "lte"),
        models.FloatField: ("exact", "gte", "lte"),
        models.DecimalField: ("exact", "gte", "lte"),
        models.DateTimeField: ("exact", "gte", "lte"),
        models.DateField: ("exact", "gte", "lte"),
        models.BooleanField: ("exact",),
    }
    """Field type → derived lookups. Resolved through each field's MRO, so
    subclasses (``PositiveIntegerField`` → ``IntegerField``) inherit their
    base's lookups while ``TextField`` (deliberately absent: unindexed
    seq-scans) stays excluded. Override on a backend subclass to change it."""

    pk_filter_map: ClassVar[Mapping[type[models.Field], type[django_filters.Filter]]] = {
        models.UUIDField: django_filters.UUIDFilter,
        models.IntegerField: django_filters.NumberFilter,
        models.CharField: django_filters.CharFilter,
    }
    """Relation-target pk type → filter class for derived FK/O2O filters."""

    def get_filterset_class(
        self, view: Any, queryset: models.QuerySet[Any] | None = None
    ) -> type[FilterSet] | None:
        """Explicit ``filterset_*`` wins; otherwise derive for opted-in views."""
        if (
            getattr(view, "filterset_class", None) is not None
            or getattr(view, "filterset_fields", None) is not None
        ):
            return super().get_filterset_class(view, queryset)
        if queryset is None or not self._auto_derivation_enabled(view):
            return super().get_filterset_class(view, queryset)
        derived = self.derive_filterset_class(queryset.model)
        request = getattr(view, "request", None)
        return self.narrow_filterset_class(derived, queryset.model, getattr(request, "user", None))

    def derive_filterset_class(self, model: type[models.Model]) -> type[FilterSet]:
        """Return the derived FilterSet for ``model``, cached per backend class."""
        cache_key = (type(self), model)
        cached = _FILTERSET_CACHE.get(cache_key)
        if cached is None:
            cached = _FILTERSET_CACHE[cache_key] = self._build_filterset(model)
        return cached

    def narrow_filterset_class(
        self, filterset: type[FilterSet], model: type[models.Model], user: Any
    ) -> type[FilterSet]:
        """``filterset`` without the filters on fields ``Karni.field_roles`` hides from ``user``.

        A filter on a hidden field is a value oracle (``?salary__gte=`` tells
        the ranking even when the column is absent), so the request's user
        decides which filters exist and which the schema documents.
        """
        from karni.accounts.visibility import hidden_fields

        hidden = hidden_fields(model, user)
        if not hidden:
            return filterset
        key = (filterset, hidden)
        cached = _NARROWED_CACHE.get(key)
        if cached is None:
            narrowed = type(filterset.__name__, (filterset,), {})
            narrowed.base_filters = {  # type: ignore[attr-defined]
                name: declared
                for name, declared in filterset.base_filters.items()
                if str(declared.field_name).split("__", 1)[0] not in hidden
            }
            cached = _NARROWED_CACHE[key] = narrowed
        return cached

    def filterable_fields(self, model: type[models.Model]) -> frozenset[str]:
        """Names eligible for derivation; override to change the policy."""
        return _api_filterable_names(model)

    def _auto_derivation_enabled(self, view: Any) -> bool:
        """Auto-derivation is opt-in: BaseViewSet or ``karni_auto_filterset``."""
        if getattr(view, "karni_auto_filterset", False):
            return True
        from karni.api.viewsets import BaseViewSet

        return isinstance(view, BaseViewSet)

    def _lookups_for(self, field: models.Field) -> tuple[str, ...] | None:
        for klass in type(field).__mro__:
            lookups = self.lookup_map.get(klass)
            if lookups is not None:
                return tuple(lookups)
        return None

    def _relation_filter(self, field: models.Field) -> django_filters.Filter:
        """Exact filter typed after the relation target's primary key."""
        # Only forward FK/O2O fields reach this point (see _build_filterset).
        target = cast("models.ForeignKey[Any, Any]", field).target_field
        for klass in type(target).__mro__:
            filter_class = self.pk_filter_map.get(klass)
            if filter_class is not None:
                return filter_class(field_name=field.name)
        return django_filters.CharFilter(field_name=field.name)

    def _build_filterset(self, model: type[models.Model]) -> type[FilterSet]:
        allowed = self.filterable_fields(model)
        meta_fields: dict[str, list[str]] = {}
        declared: dict[str, Any] = {}
        for field in model._meta.concrete_fields:
            if field.name not in allowed:
                continue
            if field.is_relation:
                if field.many_to_one or field.one_to_one:
                    declared[field.name] = self._relation_filter(field)
                continue
            if getattr(field, "choices", None):
                meta_fields[field.name] = ["exact"]
                continue
            lookups = self._lookups_for(field)
            if lookups is not None:
                meta_fields[field.name] = list(lookups)
        meta = type("Meta", (), {"model": model, "fields": meta_fields})
        return type(
            f"{model.__name__}AutoFilterSet",
            (self.filterset_base,),
            {"Meta": meta, **declared},
        )


class KarniOrderingFilter(OrderingFilter):
    """``OrderingFilter`` whose valid fields are what this request's serializer reads back.

    Without ``ordering_fields`` on the view, DRF derives the orderable fields
    from the serializer but scans the model class with ``dir()``/``getattr``
    to skip properties — which touches every descriptor, deprecated managers
    included. This derivation reads the serializer's fields only (write-only
    fields and fields ``Karni.field_roles`` hides from the requester are not
    there, so neither can order the list) and detects properties statically.

    Relations order by what the response shows of them, never by the related
    rows themselves (which the requester may not be allowed to read): a
    forward to-one orders by its key column (``?ordering=venue`` is
    ``venue_id``, not the venue model's ``Meta.ordering``), and to-many or
    reverse relations are not orderable at all (ordering by one repeats each
    row once per related row, readable or not, and drops others from the page).

    Override / escape hatch: an explicit ``ordering_fields`` on the view is
    honoured as DRF does, terms untouched.
    """

    def get_default_valid_fields(
        self, queryset: models.QuerySet[Any], view: Any, context: dict[str, Any] | None = None
    ) -> list[tuple[str, str]]:
        import inspect

        from karni.api.optimizer import model_relation

        serializer_class = getattr(view, "get_serializer_class", None)
        klass = serializer_class() if callable(serializer_class) else view.serializer_class
        if klass is None:
            return []
        model_class = queryset.model
        valid: list[tuple[str, str]] = []
        for field_name, field in klass(context=context or {}).fields.items():
            source = getattr(field, "source", None) or field_name
            if getattr(field, "write_only", False) or source == "*":
                continue
            head = source.split(".", 1)[0]
            if isinstance(inspect.getattr_static(model_class, head, None), property):
                continue
            relation = model_relation(model_class, head)
            if relation is not None and _key_column(relation) is None:
                continue  # to-many or reverse: one row per related row
            valid.append((source.replace(".", "__"), str(getattr(field, "label", field_name))))
        return valid

    def remove_invalid_fields(
        self, queryset: models.QuerySet[Any], fields: list[str], view: Any, request: Request
    ) -> list[str]:
        """The valid terms, a forward to-one relation's mapped to its key column."""
        from karni.api.optimizer import model_relation

        kept: list[str] = super().remove_invalid_fields(queryset, fields, view, request)
        if getattr(view, "ordering_fields", None) is not None:
            return kept
        mapped: list[str] = []
        for term in kept:
            sign, name = ("-", term[1:]) if term.startswith("-") else ("", term)
            relation = model_relation(queryset.model, name)
            column = _key_column(relation) if relation is not None else None
            mapped.append(f"{sign}{column or name}")
        return mapped


def _key_column(relation: Any) -> str | None:
    """The column a forward FK/O2O stores its key in (``venue_id``); ``None`` for anything else."""
    forward = getattr(relation, "concrete", False) and not hasattr(relation, "get_accessor_name")
    if forward and (relation.many_to_one or relation.one_to_one):
        return str(relation.attname)
    return None


class KarniSearchFilter(BaseFilterBackend):
    """Backend delegating ``?search=`` to the configured search provider.

    Reads the search term from the request (parameter name from DRF's
    ``SEARCH_PARAM``, default ``"search"``), and is a no-op when the term is
    empty or the view declares no ``search_fields``. Otherwise it calls
    ``get_search_provider().search(...)`` with ``rank_order`` set to whether
    the request carries **no** explicit ordering parameter — so search-rank
    ordering stands by default but an explicit ``?ordering=`` always wins
    (this backend runs after ``OrderingFilter``).

    The ``search`` schema parameter is emitted only for views whose
    ``search_fields`` is non-empty, so resources without search never document
    a dead search box.

    Override / escape hatch: change the provider via the
    ``KARNI_SEARCH_PROVIDER`` setting (see :mod:`karni.api.search`), or
    subclass and override :meth:`rank_order` / :meth:`filter_queryset`.
    """

    search_param: str = api_settings.SEARCH_PARAM
    search_description: str = "A search term."

    def filter_queryset(
        self, request: Request, queryset: models.QuerySet[Any], view: Any
    ) -> models.QuerySet[Any]:
        """Delegate to the provider, or pass through when there is no search."""
        query = self.get_search_query(request)
        fields = searchable_fields(view, request)
        if not query or not fields:
            return queryset
        return get_search_provider().search(
            queryset=queryset,
            query=query,
            fields=fields,
            view=view,
            rank_order=self.rank_order(request, view),
        )

    def get_search_query(self, request: Request) -> str:
        """The stripped ``?search=`` value (empty string when absent)."""
        value = request.query_params.get(self.search_param, "")
        return value.strip() if isinstance(value, str) else ""

    def rank_order(self, request: Request, view: Any) -> bool:
        """``True`` when no explicit ordering parameter is on the request."""
        return self.ordering_param(view) not in request.query_params

    def ordering_param(self, view: Any) -> str:
        """The ordering parameter name honoured by the view's OrderingFilter."""
        for backend in getattr(view, "filter_backends", None) or ():
            if isinstance(backend, type) and issubclass(backend, OrderingFilter):
                return cast("type[OrderingFilter]", backend).ordering_param
        return api_settings.ORDERING_PARAM

    def get_schema_operation_parameters(self, view: Any) -> list[dict[str, Any]]:
        """Document ``?search=`` — only where searching actually does something."""
        if not getattr(view, "search_fields", None):
            return []
        return [
            {
                "name": self.search_param,
                "required": False,
                "in": "query",
                "description": self.search_description,
                "schema": {"type": "string"},
            }
        ]
