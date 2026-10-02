"""OpenAPI schema generation for Karni endpoints.

:class:`KarniAutoSchema` extends drf-spectacular's ``AutoSchema`` with
exactly one extra query parameter — ``expand`` on ``BaseViewSet`` list and
retrieve operations (an enum of the allowed top-level keys) — plus the
vendor extensions the ``@karni/ui`` frontend consumes:

* ``x-karni-resource: "<router prefix>"`` on the list operation of every
  ``BaseViewSet`` registered with the default router;
* ``x-karni-relation: {"resource": "<router prefix>", "many": bool}`` on
  every relation field of a generated serializer whose target model has a
  registered route (omitted silently otherwise).

The ``search`` parameter is contributed by ``KarniSearchFilter``; ordering
and pagination parameters come from their native classes untouched. v0.1
documents only the unexpanded response shape — expanded variants never
appear in the schema.

Override / escape hatch: subclass and point
``REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"]`` (or a view's ``schema``
attribute) at your class; replace ``KARNI_API_ROUTER`` to change where
route prefixes are looked up.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db.models import Model
from django.utils.module_loading import import_string
from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiParameter

from karni.api.expansion import auto_expandable_fields

__all__ = ["KarniAutoSchema"]

DEFAULT_ROUTER_FACTORY = "karni.api.routers.get_default_router"
"""Fallback for ``settings.KARNI_API_ROUTER`` when it is unset."""


class KarniAutoSchema(AutoSchema):
    """Karni's default ``AutoSchema`` (see the module docstring).

    Set as ``REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"]`` by ``karni.conf``.
    """

    def get_override_parameters(self) -> list[Any]:
        """Contribute the ``expand`` query parameter on list/retrieve."""
        parameters = list(super().get_override_parameters())
        expand = self._build_expand_parameter()
        if expand is not None:
            parameters.append(expand)
        return parameters

    def get_operation(
        self,
        path: str,
        path_regex: str,
        path_prefix: str,
        method: str,
        registry: Any,
    ) -> dict[str, Any] | None:
        """Stock operation plus ``x-karni-resource`` on routed list ops."""
        operation = super().get_operation(path, path_regex, path_prefix, method, registry)
        if operation is None:
            return None
        if self._karni_action() == "list":
            prefix = _route_for_viewset(type(self.view))
            if prefix is not None:
                operation["x-karni-resource"] = prefix
        return operation

    def _karni_view(self) -> Any | None:
        """The view when it is a ``BaseViewSet``, else ``None``."""
        from karni.api.viewsets import BaseViewSet

        view = getattr(self, "view", None)
        return view if isinstance(view, BaseViewSet) else None

    def _karni_action(self) -> str | None:
        """The viewset action ("list", "retrieve", …) for BaseViewSets."""
        view = self._karni_view()
        if view is None:
            return None
        return getattr(view, "action", None)

    def _build_expand_parameter(self) -> OpenApiParameter | None:
        """The ``expand`` parameter, or ``None`` when it does not apply."""
        view = self._karni_view()
        if view is None or self._karni_action() not in {"list", "retrieve"}:
            return None
        try:
            model = view.get_model()
        except ImproperlyConfigured:
            return None
        allowed: Mapping[str, str] = view.expandable_fields or auto_expandable_fields(model)
        if not allowed:
            return None
        keys = sorted(allowed)
        return OpenApiParameter(
            name="expand",
            type=str,
            many=True,
            explode=False,
            style="form",
            location=OpenApiParameter.QUERY,
            required=False,
            enum=keys,
            description=(
                "Comma-separated relations to embed as nested objects instead of "
                "primary keys (dotted paths nest deeper, e.g. `a.b`). Allowed "
                "keys: " + ", ".join(keys) + "."
            ),
        )


class KarniRelatedFieldExtension(OpenApiSerializerFieldExtension):
    """Adds ``x-karni-relation`` to generated to-one relation fields.

    Matches only :class:`karni.api.serializers.KarniPrimaryKeyRelatedField`
    (the field class generated serializers use), so hand-written serializers
    are untouched. The extension is omitted silently when the target model
    has no registered route.
    """

    target_class = "karni.api.serializers.KarniPrimaryKeyRelatedField"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: AutoSchema, direction: Any) -> Any:
        """Default field schema plus the relation vendor extension."""
        schema = auto_schema._map_serializer_field(self.target, direction, bypass_extensions=True)
        return _annotate_relation(schema, self.target, many=False)


class KarniManyRelatedFieldExtension(OpenApiSerializerFieldExtension):
    """Adds ``x-karni-relation`` (``"many": true``) to generated to-many fields.

    Counterpart of :class:`KarniRelatedFieldExtension` for
    :class:`karni.api.serializers.KarniManyRelatedField`.
    """

    target_class = "karni.api.serializers.KarniManyRelatedField"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: AutoSchema, direction: Any) -> Any:
        """Default array schema plus the relation vendor extension."""
        schema = auto_schema._map_serializer_field(self.target, direction, bypass_extensions=True)
        return _annotate_relation(schema, self.target, many=True)


def _annotate_relation(schema: Any, field: Any, *, many: bool) -> Any:
    """Attach ``x-karni-relation`` when the target model has a route."""
    if not isinstance(schema, dict):
        return schema
    model = _field_target_model(field)
    if model is None:
        return schema
    resource = _route_for_model(model)
    if resource is None:
        return schema
    schema["x-karni-relation"] = {"resource": resource, "many": many}
    return schema


def _field_target_model(field: Any) -> type[Model] | None:
    """Resolve the model a (possibly many) related field points at."""
    child = getattr(field, "child_relation", None) or field
    queryset = getattr(child, "queryset", None)
    if queryset is not None:
        return queryset.model
    # Read-only relations carry no queryset: derive from the bound parent
    # serializer's model and the field's source.
    parent = getattr(field, "parent", None)
    while parent is not None and getattr(parent, "Meta", None) is None:
        parent = getattr(parent, "parent", None)
    model = getattr(getattr(parent, "Meta", None), "model", None)
    if model is None:
        return None
    name = getattr(field, "source", None) or getattr(field, "field_name", None)
    if not name:
        return None
    try:
        model_field = model._meta.get_field(name)
    except FieldDoesNotExist:
        return None
    return getattr(model_field, "related_model", None)


def _default_router() -> Any | None:
    """Resolve and call the ``KARNI_API_ROUTER`` factory (``None`` on failure).

    Override / escape hatch: point ``KARNI_API_ROUTER`` at any zero-argument
    factory returning an object with a DRF ``registry``.
    """
    dotted = getattr(settings, "KARNI_API_ROUTER", DEFAULT_ROUTER_FACTORY)
    try:
        factory = import_string(dotted)
    except ImportError:
        return None
    return factory()


def _registered_prefix(match: Callable[[Any], bool]) -> str | None:
    """First router prefix whose registered viewset satisfies ``match``."""
    router = _default_router()
    if router is None:
        return None
    for prefix, viewset, _basename in getattr(router, "registry", ()):
        if match(viewset):
            return str(prefix)
    return None


def _route_for_viewset(viewset_class: type) -> str | None:
    """Router prefix under which exactly ``viewset_class`` is registered."""
    return _registered_prefix(lambda registered: registered is viewset_class)


def _route_for_model(model: type[Model]) -> str | None:
    """Router prefix of the first registered viewset serving ``model``."""
    return _registered_prefix(lambda registered: getattr(registered, "model", None) is model)


def add_auth_mode(result: dict, generator: object, request: object, public: bool) -> dict:
    """drf-spectacular postprocessing hook: expose the backend auth mode.

    ``@karni/ui``'s AuthProvider defaults its mode from this root-level
    ``x-karni-auth-mode`` value (a prop overrides it). Remove the hook from
    ``SPECTACULAR_SETTINGS["POSTPROCESSING_HOOKS"]`` to opt out.
    """
    from django.conf import settings

    result["x-karni-auth-mode"] = getattr(settings, "KARNI_AUTH_MODE", "jwt")
    return result
