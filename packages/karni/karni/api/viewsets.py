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
"""

from __future__ import annotations

import functools
import weakref
from collections.abc import Callable, Mapping, Sequence
from typing import Any, ClassVar

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model, QuerySet
from django.db.models.expressions import Combinable
from django.http import Http404
from rest_framework.exceptions import NotFound
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import BasePermission
from rest_framework.serializers import BaseSerializer
from rest_framework.settings import api_settings
from rest_framework.viewsets import ModelViewSet

from karni.accounts.permissions import ObjectPermissionsMixin
from karni.api.access import (
    Access,
    AccessPermission,
    Predicate,
    Unscoped,
    action_predicate,
    apply_rows,
    owner_fields,
    target_read_scope,
    validate_access,
)
from karni.api.expansion import collect_expand_param, scoped_related_lookups, validate_expand
from karni.api.filters import KarniFilterBackend, KarniSearchFilter
from karni.api.serializers import build_serializer
from karni.deprecation import warn_deprecated

__all__ = ["BaseViewSet"]

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
    * ``access`` — required: ``Access(read=..., write=..., create=...)`` or
      ``Unscoped(reason=...)``. Without it every request is denied with a
      403 naming the fix.
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

    The read pipeline is fixed (ADR 0001 §4): the model's default manager
    (model-level scopes such as soft delete) → ``queryset`` / an overridden
    ``get_queryset`` → the ``access.read`` row filter →
    ``filter_queryset_for_user`` → expansion lookups → filter backends →
    pagination. No access predicate can lift a model-level scope.

    Pagination and throttling come from the DRF defaults that ``karni.conf``
    configures. ``REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`` does **not**
    apply to a viewset with an ``Access`` declaration — the declaration is
    the gate; only ``Unscoped`` viewsets fall back to it. The filter backends
    are pinned on the class so they keep working even when a project
    replaces the DRF defaults.
    """

    model: ClassVar[type[Model] | None] = None
    access: ClassVar[Access | Unscoped | None] = None
    serializer_class: type[BaseSerializer[Any]] | None = None
    queryset: QuerySet[Any] | None = None
    expand_depth: ClassVar[int] = 0
    expandable_fields: ClassVar[Mapping[str, str] | None] = None
    auto_register: ClassVar[bool] = True
    route: ClassVar[str | None] = None
    search_fields: Sequence[str] = ()

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
        """Wrap ``get_queryset`` (Q2.7) and validate the ``access`` declaration."""
        super().__init_subclass__(**kwargs)
        resolved = cls.get_queryset
        if not getattr(resolved, _SCOPED_MARK, False):
            cls.get_queryset = _scoped_get_queryset(resolved)  # type: ignore[method-assign]
        if "object_permission_classes" in cls.__dict__ and cls.object_permission_classes:
            # Still honoured (checked after the access object check) until removal.
            warn_deprecated(
                f"{cls.__name__}.object_permission_classes on a BaseViewSet",
                "the access declaration (e.g. access = Access(read=..., write=Owned('owner')))",
                removed_in="1.0",
                doc_anchor="api.md#access-control",
            )
        if apps.models_ready:
            _validate_once(cls)

    # --- model & access ----------------------------------------------------------

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
        raise ImproperlyConfigured(
            f"{type(self).__name__} must declare 'model' or 'queryset' (or "
            "override get_queryset()/get_serializer_class())."
        )

    def get_access(self) -> Access | Unscoped | None:
        """The viewset's access declaration (the class attribute ``access``).

        Read from the class, never the instance: DRF copies
        ``@action(access=...)`` onto the instance, and that per-action
        predicate must not replace the viewset's declaration.

        Override / escape hatch: return a declaration computed per request.
        """
        return type(self).access

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

    # --- the read pipeline -----------------------------------------------------------

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
        read scope, ``filter_queryset_for_user`` and expansion lookups)
        exactly once.
        """
        if self.queryset is not None:
            return self.queryset.all()
        queryset: QuerySet[Any] = self.get_model()._default_manager.all()
        return queryset

    def scope_queryset(self, queryset: QuerySet[Any]) -> QuerySet[Any]:
        """Steps 3–4 of the read pipeline: :meth:`read_scope`, then expansion.

        Schema generation (drf-spectacular's fake views) gets an empty
        queryset of the right model without evaluating any predicate.
        """
        if getattr(self, "swagger_fake_view", False):
            return queryset.none()
        queryset, _filtered = self.read_scope(queryset)
        expand = self.get_validated_expand()
        if expand:
            request = getattr(self, "request", None)
            select, prefetch = scoped_related_lookups(
                queryset.model,
                expand,
                lambda target: target_read_scope(target._default_manager.all(), request),
            )
            if select:
                queryset = queryset.select_related(*select)
            if prefetch:
                queryset = queryset.prefetch_related(*prefetch)
        return queryset

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
        rows = True if isinstance(declaration, Unscoped) else declaration.read.rows(request)
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
                if declaration.read.rows(request) is not True:
                    raise NotFound(
                        f"{exc} Rows are limited by {type(self).__name__}.access "
                        f"read={declaration.read!r}."
                    ) from exc
            raise

    # --- writes & serializers ----------------------------------------------------------

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
