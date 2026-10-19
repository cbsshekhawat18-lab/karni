"""Karni's declarative ``BaseViewSet``.

The target developer experience::

    from karni.api import Access, Authenticated, BaseViewSet, Public
    from myapp.models import Event

    class EventViewSet(BaseViewSet):
        model = Event
        access = Access(read=Public(), write=Authenticated())
        search_fields = ["title"]

gives working CRUD, filtering, pagination, ordering, search, access control,
expansion and OpenAPI schema — everything else is convention plus settings.

Access (ADR 0001, Decision 2): every viewset declares ``access``; see
:mod:`karni.api.access` for the vocabulary. A viewset without one denies
every request (and fails the ``viewset-access`` architecture rule).

Escape hatches (every DRF hook still applies — override any of
``get_queryset`` / ``get_serializer_class`` / ``get_permissions`` / … as
usual):

* ``serializer_class`` — an explicit serializer always wins over generation.
* ``queryset`` — replaces the ``model._default_manager.all()`` default.
* ``get_queryset()`` — may be overridden freely: ``__init_subclass__`` wraps
  it so the ``access`` read scope and expansion still apply to whatever it
  returns.
* ``get_access()`` — return a declaration computed per request.
* ``@action(..., access=HasRole("x"))`` — one action's predicate.
* ``permission_classes`` — extra DRF permissions, ANDed after the access
  gate (they can only narrow).
* ``filter_queryset_for_user`` — the row hook from
  :class:`karni.accounts.permissions.ObjectPermissionsMixin`; it receives
  the access-scoped queryset. Overriding it needs
  ``# karni: allow(access-override): <reason>``.
* ``access = Unscoped(reason=...)`` — plain DRF permissions, no row policy.
* ``expandable_fields`` — restrict/alias what ``?expand=`` may name.
* ``expand_depth`` — per-viewset override of ``KARNI_API_MAX_EXPAND_DEPTH``.
* ``auto_register`` / ``route`` — steer (or opt out of) router autodiscovery.
* ``filter_backends`` / ``filterset_fields`` / ``search_fields`` /
  ``ordering_fields`` — standard DRF/django-filter attributes.

Performance (ADR 0001, Decision 3) — every hatch is a declaration, never
silence:

* ``select_related`` / ``prefetch_related`` — hints merged into the lookups
  the optimiser derives from the serializer (:mod:`karni.api.optimizer`);
  ``optimize = False`` keeps only the hints; ``optimize_queryset()`` may be
  overridden.
* ``query_budget = Budget(list=25, reason="...")`` — raise (or lift with
  ``None``) the per-action query budget (:mod:`karni.performance`).
* ``pagination = Unpaginated(max_rows=N, reason="...")`` — the only way to
  switch pagination off (:mod:`karni.pagination`); list-returning custom
  actions use ``self.paginated_response(queryset)``.
* ``cache = Uncached(reason="...")`` / ``Cache(ttl=..., depends_on=[...])`` —
  opt out of / tune response caching when ``KARNI_API_CACHE`` is on
  (:mod:`karni.api.caching`).
"""

from __future__ import annotations

import functools
import logging
import weakref
from collections.abc import Callable, Mapping, Sequence
from typing import Any, ClassVar, Final

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model, Prefetch, QuerySet
from django.db.models.expressions import Combinable
from django.http import Http404, HttpRequest
from rest_framework.exceptions import NotFound
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import BasePagination
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.settings import api_settings
from rest_framework.viewsets import ModelViewSet

from karni.accounts.permissions import ObjectPermissionsMixin
from karni.api.access import (
    Access,
    AccessPermission,
    Granted,
    Predicate,
    RowFilter,
    Unscoped,
    action_predicate,
    apply_rows,
    owner_fields,
    rows_or_exempt,
    target_read_scope,
    validate_access,
)
from karni.api.caching import Cache, ResponseCache, Uncached, response_cache
from karni.api.expansion import collect_expand_param, validate_expand
from karni.api.filters import KarniFilterBackend, KarniSearchFilter
from karni.api.optimizer import TargetScope, optimize, validate_hints
from karni.api.serializers import build_serializer
from karni.deprecation import warn_deprecated
from karni.exceptions import KarniImproperlyConfigured
from karni.pagination import Unpaginated, check_pagination_class
from karni.performance import (
    Budget,
    QueryBudgetExceeded,
    QueryRecorder,
    budget_failure,
    budget_mode,
    record_queries,
    resolve_budget,
)

__all__ = ["BaseViewSet"]

logger = logging.getLogger("karni.performance")

#: Actions whose queryset the optimiser shapes from the serializer.
OPTIMIZED_ACTIONS: Final = frozenset({"list", "retrieve"})

#: Standard actions a ``Budget`` may name (plus the viewset's ``@action`` names).
_STANDARD_ACTIONS: Final = frozenset(
    {"list", "retrieve", "create", "update", "partial_update", "destroy", "metadata", "*"}
)

_SCOPED_MARK = "_karni_scoped_queryset"
_DEPTH_ATTR = "_karni_queryset_depth"


def _scoped_get_queryset(func: Callable[[Any], QuerySet[Any]]) -> Callable[[Any], QuerySet[Any]]:
    """Wrap a ``get_queryset`` so the access scope applies to its result (ADR 0001 Q2.7).

    Nested calls (an override calling ``super().get_queryset()``) return the
    unscoped base; only the outermost call scopes, so the scope runs exactly
    once whatever the override does.
    """

    @functools.wraps(func)
    def get_queryset(self: Any) -> QuerySet[Any]:
        depth = self.__dict__.get(_DEPTH_ATTR, 0)
        setattr(self, _DEPTH_ATTR, depth + 1)
        try:
            queryset = func(self)
        finally:
            setattr(self, _DEPTH_ATTR, depth)
        if depth:
            return queryset
        scoped: QuerySet[Any] = self.scope_queryset(queryset)
        return scoped

    setattr(get_queryset, _SCOPED_MARK, True)
    return get_queryset


class BaseViewSet(ObjectPermissionsMixin, ModelViewSet):
    """Model-driven ``ModelViewSet``: declare ``model`` and ``access``, get a full API.

    Declarative attributes (see the module docstring for the escape
    hatches):

    * ``model`` — required unless ``queryset`` is set (or ``get_queryset``
      overridden).
    * ``access`` — required: ``Granted()`` (the roles' grants for this model
      and the current action, row-scoped; shorthand for ``Access(read=Granted(),
      write=Granted())``), ``Access(read=..., write=..., create=...)`` or
      ``Unscoped(reason=...)``. Without it every request is denied with a 403
      naming the fix.
    * ``scope_exempt`` — ``True`` (with ``scope_exempt_reason``) keeps the
      gate and shows every row it admits; ``karni check`` lists each one.
    * ``serializer_class`` — explicit serializer; ``None`` generates one via
      :func:`karni.api.serializers.build_serializer`.
    * ``queryset`` — explicit base queryset; ``None`` uses
      ``model._default_manager.all()``.
    * ``expand_depth`` — ``0`` defers to ``KARNI_API_MAX_EXPAND_DEPTH``; a
      positive value overrides the expansion depth limit for this viewset.
    * ``expandable_fields`` — mapping of expand key → model relation name;
      ``None`` allows every forward FK/O2O/M2M under its own name.
    * ``auto_register`` — ``False`` hides the viewset from router
      autodiscovery.
    * ``route`` — router prefix; ``None`` derives the kebab-cased plural of
      the model name.
    * ``search_fields`` — fields searched by ``?search=`` through the
      configured search provider.

    * ``select_related`` / ``prefetch_related`` — query hints merged into
      the optimiser's derived lookups; ``optimize = False`` keeps only them.
    * ``query_budget`` — ``Budget(list=25, reason=...)``; ``None`` uses
      ``KARNI_QUERY_BUDGET``.
    * ``pagination`` — ``Unpaginated(max_rows=N, reason=...)`` to return
      plain (still bounded) lists; ``None`` keeps ``pagination_class``.
    * ``cache`` — ``Uncached(reason=...)`` or ``Cache(ttl=..., depends_on=...)``;
      ``None`` follows ``KARNI_API_CACHE``.

    The read pipeline is fixed (ADR 0001 §4): the model's default manager
    (model-level scopes such as soft delete) → ``queryset`` / an overridden
    ``get_queryset`` → the ``access.read`` row filter →
    ``filter_queryset_for_user`` → the optimiser (``list``/``retrieve``:
    lookups derived from the serializer, each prefetch through its target's
    read scope) → filter backends → pagination. No access predicate can lift
    a model-level scope.

    Pagination always applies (a :class:`karni.pagination.KarniPagination`;
    ``pagination_class = None`` without ``Unpaginated`` is a class-definition
    error), and every request is counted against its query budget unless
    ``KARNI_QUERY_BUDGET_MODE`` is ``"off"``. Throttling comes from the DRF
    defaults that ``karni.conf`` configures.
    ``REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`` does **not** apply to a
    viewset with an ``Access`` declaration — the declaration is
    the gate; only ``Unscoped`` viewsets fall back to it. The filter backends
    are pinned on the class so they keep working even when a project
    replaces the DRF defaults.
    """

    model: ClassVar[type[Model] | None] = None
    access: ClassVar[Access | Unscoped | Granted | None] = None
    serializer_class: type[BaseSerializer[Any]] | None = None
    queryset: QuerySet[Any] | None = None
    expand_depth: ClassVar[int] = 0
    expandable_fields: ClassVar[Mapping[str, str] | None] = None
    auto_register: ClassVar[bool] = True
    route: ClassVar[str | None] = None
    search_fields: Sequence[str] = ()
    optimize: ClassVar[bool] = True
    select_related: ClassVar[Sequence[str]] = ()
    prefetch_related: ClassVar[Sequence[str | Prefetch]] = ()
    query_budget: ClassVar[Budget | None] = None
    pagination: ClassVar[Unpaginated | None] = None
    cache: ClassVar[Cache | Uncached | None] = None
    scope_exempt: ClassVar[bool] = False
    scope_exempt_reason: ClassVar[str] = ""

    # The access declaration is the gate; DRF's project-wide default does
    # not apply. Classes listed here (or via @action) are ANDed after it.
    permission_classes: Sequence[type[BasePermission]] = ()

    # Pinned explicitly (not just via conf defaults) so BaseViewSet behaves
    # the same even if a project overrides REST_FRAMEWORK defaults. Search
    # runs LAST so an explicit ?ordering= wins while search-rank ordering
    # survives when no ordering was requested.
    filter_backends = [KarniFilterBackend, OrderingFilter, KarniSearchFilter]
    ordering_fields = "__all__"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Wrap ``get_queryset`` (Q2.7); validate access and the performance declarations."""
        super().__init_subclass__(**kwargs)
        declared = cls.__dict__.get("access")
        if isinstance(declared, Granted):
            # The shorthand: reads, writes and creates all follow the roles' grants.
            cls.access = Access(read=declared, write=declared)
        resolved = cls.get_queryset
        if not getattr(resolved, _SCOPED_MARK, False):
            cls.get_queryset = _scoped_get_queryset(resolved)  # type: ignore[method-assign]
        _validate_performance(cls)
        if "object_permission_classes" in cls.__dict__ and cls.object_permission_classes:
            # Still honoured (checked after the access object check) until removal.
            warn_deprecated(
                f"{cls.__name__}.object_permission_classes on a BaseViewSet",
                "the access declaration (e.g. access = Access(read=..., write=Owned('owner')))",
                removed_in="1.0",
                doc_anchor="migrations/0.2.md#object_permission_classes",
            )
        if apps.models_ready:
            _validate_once(cls)

    # model & access

    def get_model(self) -> type[Model]:
        """Return the model this viewset serves.

        Resolves ``model`` first, then ``queryset.model``.

        :raises django.core.exceptions.ImproperlyConfigured: when neither is
            declared — set one of them or override the relevant hooks.
        """
        if self.model is not None:
            return self.model
        if self.queryset is not None:
            return self.queryset.model
        raise KarniImproperlyConfigured(
            f"{type(self).__name__} must declare 'model' or 'queryset' (or "
            "override get_queryset()/get_serializer_class()).",
            code="E110",
        )

    def get_access(self) -> Access | Unscoped | None:
        """The viewset's access declaration (the class attribute ``access``).

        Read from the class, never the instance: DRF copies
        ``@action(access=...)`` onto the instance, and that per-action
        predicate must not replace the viewset's declaration.

        Override / escape hatch: return a declaration computed per request.
        """
        declared = type(self).access
        if isinstance(declared, Granted):  # set after class definition: normalise here
            return Access(read=declared, write=declared)
        return declared

    def get_access_predicate(self) -> Predicate | None:
        """The predicate governing the current action (``None`` without an ``Access``)."""
        declaration = self.get_access()
        if not isinstance(declaration, Access):
            return None
        return action_predicate(self, declaration)

    def get_permissions(self) -> list[BasePermission]:
        """The access gate first, then any ``permission_classes`` (ANDed).

        ``Unscoped`` viewsets get plain DRF behaviour instead: their
        ``permission_classes``, else ``DEFAULT_PERMISSION_CLASSES``.
        """
        _validate_once(type(self))
        extra = [permission() for permission in self.permission_classes]
        if isinstance(self.get_access(), Unscoped):
            if extra:
                return extra
            return [permission() for permission in api_settings.DEFAULT_PERMISSION_CLASSES]
        return [AccessPermission(), *extra]

    def get_owner_fields(self) -> tuple[str, ...]:
        """Owner FKs of the declaration: stamped on create, read-only when generated."""
        try:
            model = self.get_model()
        except ImproperlyConfigured:
            return ()
        return owner_fields(self.get_access(), model)

    # the read pipeline

    @property
    def ordering(self) -> Sequence[str | Combinable]:
        """Default ordering: ``Meta.ordering``, else ``-created_at``, else ``-pk``.

        Consumed by ``OrderingFilter`` only when the request carries no
        ``?ordering=`` parameter. Override / escape hatch: assign a plain
        ``ordering`` attribute on a subclass — it shadows this property.
        """
        try:
            model = self.get_model()
        except ImproperlyConfigured:
            return ["-pk"]
        if model._meta.ordering:
            return list(model._meta.ordering)
        field_names = {field.name for field in model._meta.get_fields()}
        if "created_at" in field_names:
            return ["-created_at"]
        return ["-pk"]

    def get_validated_expand(self) -> frozenset[str]:
        """Return the request's validated ``?expand=`` paths (cached per request).

        Resolves aliases to model relation names via
        :func:`karni.api.expansion.validate_expand`. Without a request (e.g.
        during schema generation) this is an empty set, never an error.
        """
        cached = getattr(self, "_validated_expand", None)
        if cached is not None:
            return cached
        request = getattr(self, "request", None)
        if request is None:
            expand: frozenset[str] = frozenset()
        else:
            expand = validate_expand(self, collect_expand_param(request))
        self._validated_expand = expand
        return expand

    @_scoped_get_queryset
    def get_queryset(self) -> QuerySet[Any]:
        """The base queryset: ``queryset`` or ``model._default_manager.all()``.

        Whatever this returns — here or in any override, with or without
        ``super()`` — is passed through :meth:`scope_queryset` (the access
        read scope, ``filter_queryset_for_user`` and, for ``list`` /
        ``retrieve``, the optimiser) exactly once.
        """
        if self.queryset is not None:
            return self.queryset.all()
        queryset: QuerySet[Any] = self.get_model()._default_manager.all()
        return queryset

    def scope_queryset(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        """Steps 3–4 of the read pipeline: :meth:`read_scope`, then the optimiser.

        The optimiser runs for ``list`` and ``retrieve`` (custom actions opt
        in through :meth:`paginated_response` or :meth:`optimize_queryset`).
        Schema generation (drf-spectacular's fake views) gets an empty
        queryset of the right model without evaluating any predicate.
        """
        if getattr(self, "swagger_fake_view", False):
            return queryset.none()
        queryset, _filtered = self.read_scope(queryset)
        if getattr(self, "action", None) in OPTIMIZED_ACTIONS:
            queryset = self.optimize_queryset(queryset)
        return queryset

    def target_scope(self) -> TargetScope:
        """``scope(model) -> (readable rows, filtered)`` for prefetches (ADR 0001 R3)."""
        request = getattr(self, "request", None)

        def scope(target: type[Model]) -> tuple[QuerySet[Any], bool]:
            return target_read_scope(target._default_manager.all(), request)

        return scope

    def optimize_queryset(
        self,
        queryset: QuerySet[Any],
        serializer_class: type[BaseSerializer[Any]] | None = None,
    ) -> QuerySet[Any]:
        """Add the lookups rendering with ``serializer_class`` needs, plus the hints.

        ``serializer_class`` defaults to :meth:`get_serializer_class` (so
        ``?expand=`` is covered). ``optimize = False`` applies only
        ``select_related`` / ``prefetch_related`` (and ``APIMeta`` hints).
        Calling it twice is harmless: lookups already present win.

        Override / escape hatch: override this method for a hand-built
        strategy.
        """
        serializer = None
        if self.optimize:
            serializer = serializer_class or self.get_serializer_class()
        context = {
            "request": getattr(self, "request", None),
            "format": getattr(self, "format_kwarg", None),
            "view": self,
        }
        return optimize(
            queryset,
            serializer,
            scope=self.target_scope(),
            select=self.select_related,
            prefetch=self.prefetch_related,
            context=context,
        )

    def read_scope(self, queryset: QuerySet[Any]) -> tuple[QuerySet[Any], bool]:
        """Narrow ``queryset`` by ``access.read`` and ``filter_queryset_for_user``.

        Returns ``(queryset, filtered)``; ``filtered`` is ``False`` only when
        every row stays visible. A missing declaration or a missing request
        yields no rows. Relation validation and expansion into this model
        reuse this method (:func:`karni.api.access.target_read_scope`).
        """
        declaration = self.get_access()
        request = getattr(self, "request", None)
        if declaration is None or request is None:
            return queryset.none(), True
        if isinstance(declaration, Unscoped):
            rows: RowFilter = True
        else:
            rows = rows_or_exempt(self, declaration.read.bind(self, "view"), request)
        queryset = apply_rows(queryset, rows)
        filtered = rows is not True
        hook = type(self).filter_queryset_for_user
        if hook is not ObjectPermissionsMixin.filter_queryset_for_user:
            queryset = self.filter_queryset_for_user(queryset)
            filtered = True
        return queryset, filtered

    def get_object(self) -> Any:
        """DRF lookup over the read scope: out of scope → 404, not writable → 403.

        A 404 caused by a narrowing read scope names that scope, so the
        cause is visible without revealing whether the row exists.
        """
        try:
            return super().get_object()
        except Http404 as exc:
            declaration = self.get_access()
            request = getattr(self, "request", None)
            if isinstance(declaration, Access) and request is not None:
                bound = declaration.read.bind(self, "view")
                if rows_or_exempt(self, bound, request) is not True:
                    shown = f"read={declaration.read!r}"
                    if bound != declaration.read:
                        shown += f" (= {bound!r})"
                    raise NotFound(
                        f"{exc} Rows are limited by {type(self).__name__}.access {shown}."
                    ) from exc
            raise

    # writes & serializers

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        """Save, stamping every owner field from ``request.user`` (ADR 0001 R6).

        The request body never chooses the owner. Override / escape hatch:
        override this method (call ``serializer.save(...)`` yourself).
        """
        user = getattr(self.request, "user", None)
        stamps: dict[str, Any] = {}
        if user is not None and user.is_authenticated:
            stamps = {name: user for name in self.get_owner_fields()}
        serializer.save(**stamps)

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        """Explicit ``serializer_class`` if set, else a generated serializer.

        Generation is cached per ``(model, expand, depth, owner fields)`` —
        see :func:`karni.api.serializers.build_serializer`; owner fields of
        the ``access`` declaration are read-only. Without a request (schema
        generation) the unexpanded base serializer is returned.
        """
        if self.serializer_class is not None:
            return self.serializer_class
        return build_serializer(
            self.get_model(),
            expand=self.get_validated_expand(),
            max_depth=self.expand_depth or None,
            read_only=self.get_owner_fields(),
        )

    # pagination

    @property
    def paginator(self) -> BasePagination:
        """The paginator instance; a viewset without one is a configuration error.

        ``REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"]`` missing (``None``)
        would silently return whole tables; boot validation refuses it, and
        this is the backstop when validation is off.
        """
        if self.pagination_class is None:
            raise KarniImproperlyConfigured(
                f"{type(self).__name__} has no pagination_class (REST_FRAMEWORK"
                "['DEFAULT_PAGINATION_CLASS'] is None?). Keep "
                "'karni.pagination.KarniPageNumberPagination', or declare "
                "pagination = Unpaginated(max_rows=N, reason='...').",
                code="E111",
            )
        paginator: BasePagination = super().paginator
        return paginator

    def paginated_response(
        self,
        queryset: QuerySet[Any],
        serializer_class: type[BaseSerializer[Any]] | None = None,
    ) -> Response:
        """Paginate, optimise and serialise ``queryset`` — the list-returning ``@action`` path.

        ``return self.paginated_response(self.get_queryset().filter(...))``
        gives the same envelope, page-size cap and query optimisation as
        ``list``. An unordered queryset gets the viewset's default
        ``ordering`` (stable pages). Pass ``self.filter_queryset(qs)`` to
        apply the request's filters and ``?ordering=`` too.
        ``serializer_class`` defaults to :meth:`get_serializer_class`.
        """
        serializer_class = serializer_class or self.get_serializer_class()
        if not queryset.ordered:
            queryset = queryset.order_by(*self.ordering)
        page = self.paginate_queryset(self.optimize_queryset(queryset, serializer_class))
        serializer = serializer_class(page, many=True, context=self.get_serializer_context())
        response: Response = self.get_paginated_response(serializer.data)
        return response

    # query budget

    def get_query_budget(self) -> int | None:
        """The query budget of the current action (``None`` = unchecked).

        ``query_budget`` on the class first, then ``KARNI_QUERY_BUDGET``.
        """
        return resolve_budget(type(self).query_budget, getattr(self, "action", None))

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        """DRF's dispatch, counted against the action's query budget.

        ``KARNI_QUERY_BUDGET_MODE``: ``"off"`` → no counting; ``"warn"`` →
        an over-budget request logs the grouped duplicate report; ``"raise"``
        → it raises :class:`karni.performance.QueryBudgetExceeded`. Both
        counting modes set ``X-Karni-Queries`` (and ``X-Karni-Query-Budget``).
        """
        mode = budget_mode()
        if mode == "off":
            return super().dispatch(request, *args, **kwargs)
        with record_queries() as recorder:
            response = super().dispatch(request, *args, **kwargs)
        self.check_query_budget(recorder, response, mode)
        return response

    def check_query_budget(self, recorder: QueryRecorder, response: Any, mode: str) -> None:
        """Compare ``recorder`` with :meth:`get_query_budget`; warn or raise per ``mode``."""
        limit = self.get_query_budget()
        response["X-Karni-Queries"] = str(recorder.count)
        if limit is None:
            return
        response["X-Karni-Query-Budget"] = str(limit)
        if recorder.count <= limit:
            return
        action = getattr(self, "action", None) or "*"
        name = type(self).__name__
        message = budget_failure(
            f"{name}.{action}",
            recorder.report(),
            limit,
            "Fix the repeated query (the optimiser derives select_related/prefetch_related "
            "from the serializer; hint opaque fields with select_related/prefetch_related "
            f"on {name}), or declare query_budget = Budget({action}=N, reason=...).",
        )
        if mode == "raise":
            raise QueryBudgetExceeded(message)
        logger.warning(message)

    # response cache

    def get_response_cache(self) -> ResponseCache | None:
        """The cache entry for this request, or ``None`` when it is not cached.

        Cached: ``GET`` ``list``/``retrieve`` while ``KARNI_API_CACHE`` is on
        and ``cache`` is not ``Uncached`` (see :mod:`karni.api.caching`).
        Override / escape hatch: return ``None`` to skip caching per request.
        """
        return response_cache(self)

    # list/retrieve: DRF's, served from the response cache when it is enabled.
    # No docstrings on purpose — drf-spectacular would publish them as every
    # operation's description in place of the viewset's own docstring.

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        cache = self.get_response_cache()
        if cache is not None and (hit := cache.get()) is not None:
            return hit
        response: Response = super().list(request, *args, **kwargs)
        if cache is not None:
            cache.store(response)
        return response

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        cache = self.get_response_cache()
        if cache is not None and (hit := cache.get()) is not None:
            return hit
        response: Response = super().retrieve(request, *args, **kwargs)
        if cache is not None:
            cache.store(response)
        return response


def _validate_performance(cls: type[BaseViewSet]) -> None:
    """Class-definition checks for the Decision 3 declarations (ADR 0001 Q3.5)."""
    name = cls.__name__
    declared = cls.__dict__.get("pagination")
    if declared is not None:
        if not isinstance(declared, Unpaginated):
            raise KarniImproperlyConfigured(
                f"{name}.pagination must be Unpaginated(max_rows=N, reason='...'), got "
                f"{declared!r}; to change the paginator set pagination_class instead.",
                code="E113",
            )
        own = cls.__dict__.get("pagination_class")
        if own is not None:
            raise KarniImproperlyConfigured(
                f"{name} declares both pagination = Unpaginated(...) and pagination_class; "
                "keep one.",
                code="E114",
            )
        cls.pagination_class = declared.paginator_class()
    elif "pagination_class" in cls.__dict__:
        check_pagination_class(name, cls.__dict__["pagination_class"])
    budget = cls.__dict__.get("query_budget")
    if budget is not None:
        if not isinstance(budget, Budget):
            raise KarniImproperlyConfigured(
                f"{name}.query_budget must be a Budget, e.g. "
                f"query_budget = Budget(list={budget!r}, reason='...'), got {budget!r}.",
                code="E115",
            )
        known = _STANDARD_ACTIONS | {extra.__name__ for extra in cls.get_extra_actions()}
        unknown = sorted(set(budget.limits) - known)
        if unknown:
            raise KarniImproperlyConfigured(
                f"{name}.query_budget names unknown action(s) {', '.join(unknown)}; "
                f"known: {', '.join(sorted(known - {'*'}))} (default= for the rest).",
                code="E116",
            )
    cache = cls.__dict__.get("cache")
    if cache is not None and not isinstance(cache, Cache | Uncached):
        raise KarniImproperlyConfigured(
            f"{name}.cache must be Cache(...) or Uncached(reason='...'), got {cache!r}.",
            code="E119",
        )
    for hint in ("select_related", "prefetch_related"):
        if hint in cls.__dict__:
            validate_hints(name, hint, cls.__dict__[hint])
    if not isinstance(cls.optimize, bool):
        raise KarniImproperlyConfigured(f"{name}.optimize must be True or False.", code="E121")


_VALIDATED: weakref.WeakSet[type[Any]] = weakref.WeakSet()


def _validate_once(cls: type[BaseViewSet]) -> None:
    """Validate ``cls.access`` against its model once (at class creation when apps are ready)."""
    if cls in _VALIDATED:
        return
    model = cls.model
    if model is None:
        model = getattr(cls.queryset, "model", None)
    validate_access(cls, model)
    _VALIDATED.add(cls)
