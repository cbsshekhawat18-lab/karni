"""Karni's declarative ``BaseViewSet``.

The target developer experience::

    from karni.api import BaseViewSet
    from myapp.models import Event

    class EventViewSet(BaseViewSet):
        model = Event
        search_fields = ["title"]

gives working CRUD, filtering, pagination, ordering, search, permissions,
expansion and OpenAPI schema — everything else is convention plus settings.

Escape hatches (every DRF hook still applies — override any of
``get_queryset`` / ``get_serializer_class`` / ``get_permissions`` / … as
usual):

* ``serializer_class`` — an explicit serializer always wins over generation.
* ``queryset`` — replaces the ``model._default_manager.all()`` default.
* ``expandable_fields`` — restrict/alias what ``?expand=`` may name.
* ``expand_depth`` — per-viewset override of ``KARNI_API_MAX_EXPAND_DEPTH``.
* ``auto_register`` / ``route`` — steer (or opt out of) router autodiscovery.
* ``filter_backends`` / ``filterset_fields`` / ``search_fields`` /
  ``ordering_fields`` — standard DRF/django-filter attributes.
* ``permission_classes`` / ``object_permission_classes`` /
  ``filter_queryset_for_user`` — see
  :class:`karni.accounts.permissions.ObjectPermissionsMixin`.

Security posture: with Karni's default ``DEFAULT_PERMISSION_CLASSES``
(``IsAuthenticatedOrReadOnly``) every auto-registered viewset is readable by
anonymous users. Set ``permission_classes`` per viewset (or the DRF default
project-wide) to lock reads down, and ``auto_register = False`` to keep a
viewset out of the auto-router.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model, QuerySet
from django.db.models.expressions import Combinable
from rest_framework.filters import OrderingFilter
from rest_framework.serializers import BaseSerializer
from rest_framework.viewsets import ModelViewSet

from karni.accounts.permissions import ObjectPermissionsMixin
from karni.api.expansion import collect_expand_param, related_lookups, validate_expand
from karni.api.filters import KarniFilterBackend, KarniSearchFilter
from karni.api.serializers import build_serializer

__all__ = ["BaseViewSet"]


class BaseViewSet(ObjectPermissionsMixin, ModelViewSet):
    """Model-driven ``ModelViewSet``: declare ``model``, get a full API.

    Declarative attributes (see the module docstring for the escape
    hatches):

    * ``model`` — required unless ``queryset`` is set (or ``get_queryset``
      overridden).
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

    Pagination, throttling and permissions come from the DRF defaults that
    ``karni.conf`` configures (``KarniPageNumberPagination``, anon/user
    throttle rates, ``IsAuthenticatedOrReadOnly``); the filter backends are
    pinned on the class so they keep working even when a project replaces
    the DRF defaults.
    """

    model: ClassVar[type[Model] | None] = None
    serializer_class: type[BaseSerializer[Any]] | None = None
    queryset: QuerySet[Any] | None = None
    expand_depth: ClassVar[int] = 0
    expandable_fields: ClassVar[Mapping[str, str] | None] = None
    auto_register: ClassVar[bool] = True
    route: ClassVar[str | None] = None
    search_fields: Sequence[str] = ()

    # Pinned explicitly (not just via conf defaults) so BaseViewSet behaves
    # the same even if a project overrides REST_FRAMEWORK defaults. Search
    # runs LAST so an explicit ?ordering= wins while search-rank ordering
    # survives when no ordering was requested.
    filter_backends = [KarniFilterBackend, OrderingFilter, KarniSearchFilter]
    ordering_fields = "__all__"

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

    def get_queryset(self) -> QuerySet[Any]:
        """Base queryset, user-scoped and optimised for the requested expansion.

        Pipeline: ``queryset`` (or ``model._default_manager.all()``) →
        :meth:`filter_queryset_for_user` (the ObjectPermissionsMixin hook,
        override it for owner-scoping) → automatic ``select_related`` /
        ``prefetch_related`` for the validated ``?expand=`` paths.
        """
        if self.queryset is not None:
            queryset: QuerySet[Any] = self.queryset.all()
        else:
            queryset = self.get_model()._default_manager.all()
        queryset = self.filter_queryset_for_user(queryset)
        expand = self.get_validated_expand()
        if expand:
            select, prefetch = related_lookups(queryset.model, expand)
            if select:
                queryset = queryset.select_related(*select)
            if prefetch:
                queryset = queryset.prefetch_related(*prefetch)
        return queryset

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        """Explicit ``serializer_class`` if set, else a generated serializer.

        Generation is cached per ``(model, expand, depth)`` — see
        :func:`karni.api.serializers.build_serializer`. Without a request
        (schema generation) the unexpanded base serializer is returned.
        """
        if self.serializer_class is not None:
            return self.serializer_class
        return build_serializer(
            self.get_model(),
            expand=self.get_validated_expand(),
            max_depth=self.expand_depth or None,
        )
