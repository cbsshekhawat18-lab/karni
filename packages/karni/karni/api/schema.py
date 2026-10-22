"""OpenAPI schema generation for Karni endpoints.

:class:`KarniAutoSchema` extends drf-spectacular's ``AutoSchema`` with
exactly one extra query parameter — ``expand`` on ``BaseViewSet`` list and
retrieve operations (an enum of the allowed top-level keys) — plus the
vendor extensions the ``@karni/ui`` frontend consumes:

* ``x-karni-resource: "<router prefix>"`` on the list operation of every
  ``BaseViewSet`` registered with the default router;
* ``x-karni-relation: {"resource": "<router prefix>", "many": bool}`` on
  every relation field of a generated serializer whose target model has a
  registered route (omitted silently otherwise);
* ``x-karni-access`` on every ``BaseViewSet`` operation: the access
  predicate governing that operation (ADR 0001 Decision 2), e.g.
  ``{"any": [{"owned": "organizer"}, {"role": ["staff"]}]}``. Keys:
  ``public``, ``authenticated``, ``role`` (any of the names), ``owned``
  (owner path), ``where`` (custom function name), ``any`` / ``all``
  (``|`` / ``&``), ``unscoped`` (the reason) and ``deny`` (no declaration).
  Display hints for clients only — the server enforces.

Operations whose access predicate can admit anonymous callers (``Public``,
``Where``, or a combination containing them) list the empty security
requirement ``{}``, as drf-spectacular does for ``AllowAny``.

The ``search`` parameter is contributed by ``KarniSearchFilter``; ordering
and pagination parameters come from their native classes untouched. v0.1
documents only the unexpanded response shape — expanded variants never
appear in the schema.

Two postprocessing hooks run after generation (``SPECTACULAR_SETTINGS
["POSTPROCESSING_HOOKS"]``): :func:`postprocess_schema_enums` names the
shared choice enums, by model and field where a plain field name collides
(``BookingStatusEnum``, never ``Status469Enum``), and :func:`add_auth_mode`
stamps ``x-karni-auth-mode`` at the root.

Override / escape hatch: subclass and point
``REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"]`` (or a view's ``schema``
attribute) at your class; replace ``KARNI_API_ROUTER`` to change where
route prefixes are looked up.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping
from typing import Any, NamedTuple

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db.models import Model
from django.utils.module_loading import import_string
from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiParameter

from karni.api.access import (
    Access,
    AllOf,
    AnyOf,
    Owned,
    Predicate,
    Public,
    Where,
    action_predicate,
    describe_access,
)
from karni.api.expansion import auto_expandable_fields

__all__ = ["KarniAutoSchema"]

DEFAULT_ROUTER_FACTORY = "karni.api.routers.get_default_router"
"""Fallback for ``settings.KARNI_API_ROUTER`` when it is unset."""


class KarniAutoSchema(AutoSchema):
    """Karni's default ``AutoSchema`` (see the module docstring).

    Set as ``REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"]`` by ``karni.conf``.
    """

    def get_operation(
        self,
        path: str,
        path_regex: str,
        path_prefix: str,
        method: str,
        registry: Any,
    ) -> dict[str, Any] | None:
        """Stock operation plus ``x-karni-resource`` (routed list ops) and ``x-karni-access``."""
        if self._karni_action() == "history" and not self._karni_audited():
            return None  # no history is kept for this resource: no operation to document
        operation = super().get_operation(path, path_regex, path_prefix, method, registry)
        if operation is None:
            return None
        if self._karni_action() == "list":
            prefix = _route_for_viewset(type(self.view))
            if prefix is not None:
                operation["x-karni-resource"] = prefix
        view = self._karni_view()
        if view is not None:
            declaration, predicate = self._karni_access(view)
            operation["x-karni-access"] = describe_access(declaration, predicate)
        return operation

    #: The detail routes drf-spectacular already names apart from the list.
    _DETAIL_ACTIONS = frozenset({"retrieve", "update", "partial_update", "destroy"})

    def get_operation_id(self) -> str:
        """Stock ID, plus ``_by_<param>`` for any other route that ends in a path parameter.

        drf-spectacular drops path parameters from the ID, so ``GET import/``
        and ``GET import/{job}/`` (or ``permissions/effective/`` and
        ``.../{user_id}/``) both became ``..._retrieve`` and a client got a
        ``_2`` suffix. The standard detail routes keep their IDs.
        """
        operation_id: str = super().get_operation_id()
        if self._karni_action() in self._DETAIL_ACTIONS:
            return operation_id
        params = re.findall(r"\{(\w+)\}", self.path)
        if not params or not self.path.rstrip("/").endswith("}"):
            return operation_id
        base, _, verb = operation_id.rpartition("_")
        return f"{base}_by_{params[-1]}_{verb}" if base else operation_id

    def get_response_serializers(self) -> Any:
        """History answers with change-log entries; export and import with files and job states."""
        action = self._karni_action()
        if action == "history":
            from karni.audit.serializers import ChangeLogSerializer

            return ChangeLogSerializer
        if action in ("export", "import_template"):
            from drf_spectacular.types import OpenApiTypes

            return OpenApiTypes.BINARY
        if action == "import_data" and self.method == "GET":
            from karni.transfer.serializers import ImportDescribeSerializer

            return ImportDescribeSerializer
        if action in ("import_data", "import_job", "import_preview", "import_commit"):
            from karni.transfer.serializers import ImportJobSerializer

            return ImportJobSerializer
        return super().get_response_serializers()

    def get_request_serializer(self) -> Any:
        """The import endpoints take an upload, then a mapping."""
        action = self._karni_action()
        if action == "import_data" and self.method == "POST":
            from karni.transfer.serializers import ImportUploadSerializer

            return ImportUploadSerializer
        if action == "import_preview":
            from karni.transfer.serializers import ImportMappingSerializer

            return ImportMappingSerializer
        if action == "import_commit":
            return None
        return super().get_request_serializer()

    def get_override_parameters(self) -> list[Any]:
        """Contribute ``expand`` on list/retrieve and ``format`` on export/template."""
        parameters = list(super().get_override_parameters())
        expand = self._build_expand_parameter()
        if expand is not None:
            parameters.append(expand)
        if self._karni_action() in ("export", "import_template"):
            parameters.append(
                OpenApiParameter(
                    name="format",
                    type=str,
                    location=OpenApiParameter.QUERY,
                    required=False,
                    enum=["csv", "xlsx"],
                    description="File format (csv by default for an export, xlsx for a template).",
                )
            )
        return parameters

    def _is_list_view(self, serializer: Any = None) -> bool:
        """The history action is a paginated list (``paginated_response``); the rest are not."""
        action = self._karni_action()
        if action == "history":
            return True
        if action in (
            "export",
            "import_template",
            "import_data",
            "import_job",
            "import_preview",
            "import_commit",
        ):
            return False
        return bool(super()._is_list_view(serializer))

    def _karni_audited(self) -> bool:
        """Whether the view's model keeps change history (``Karni.audit``)."""
        from karni.audit.services import audited

        view = self._karni_view()
        model = getattr(view, "model", None) if view is not None else None
        if model is None and view is not None:
            model = getattr(getattr(view, "queryset", None), "model", None)
        return model is not None and audited(model)

    def get_auth(self) -> list[Any]:
        """Stock security requirements, optional (``{}``) where access admits anonymous."""
        auths = list(super().get_auth())
        view = self._karni_view()
        if view is None or {} in auths:
            return auths
        _declaration, predicate = self._karni_access(view)
        if predicate is not None and _admits_anonymous(predicate):
            auths.append({})
        return auths

    def _karni_access(self, view: Any) -> tuple[Any, Predicate | None]:
        """The view's declaration and the predicate governing this operation."""
        declaration = view.get_access()
        if not isinstance(declaration, Access):
            return declaration, None
        return declaration, action_predicate(view, declaration, method=self.method)

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


def _admits_anonymous(predicate: Predicate) -> bool:
    """Whether ``predicate``'s request gate can pass for an anonymous caller (static)."""
    if isinstance(predicate, Public | Where):
        return True
    if isinstance(predicate, AnyOf):
        return any(_admits_anonymous(part) for part in predicate.parts)
    if isinstance(predicate, AllOf):
        return all(_admits_anonymous(part) for part in predicate.parts)
    if isinstance(predicate, Owned) and predicate.bypass is not None:
        return _admits_anonymous(predicate.bypass)
    return False


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
    """Router prefix of the first registered viewset serving ``model``.

    Same model → viewset rule as relation scoping
    (:func:`karni.api.routers.viewset_for_model`): registry order, the
    viewset's ``model`` else ``queryset.model``.
    """
    from karni.api.routers import serves_model

    return _registered_prefix(lambda registered: serves_model(registered, model))


def add_auth_mode(result: dict, generator: object, request: object, public: bool) -> dict:
    """drf-spectacular postprocessing hook: expose the backend auth mode.

    ``@karni/ui``'s AuthProvider defaults its mode from this root-level
    ``x-karni-auth-mode`` value (a prop overrides it). Remove the hook from
    ``SPECTACULAR_SETTINGS["POSTPROCESSING_HOOKS"]`` to opt out.
    """
    from django.conf import settings

    result["x-karni-auth-mode"] = getattr(settings, "KARNI_AUTH_MODE", "jwt")
    return result


_SCHEMA_REF = "#/components/schemas/"


class _EnumOwner(NamedTuple):
    """Who a choice property belongs to: the model, else the serializer component."""

    name: str  # "Booking"
    qualified: str  # "EventsBooking" (app label first), the fallback on a clash
    is_model: bool


def postprocess_schema_enums(
    result: dict[str, Any], generator: Any, **kwargs: Any
) -> dict[str, Any]:
    """drf-spectacular postprocessing hook: shared choice enums, named by model and field.

    Runs drf-spectacular's ``postprocess_schema_enums`` (every choice set
    becomes one shared ``<Field>Enum`` component), then renames the enums
    whose plain name collided. When two models expose a ``status`` field with
    different choices, drf-spectacular names them ``<Component><Field>Enum``
    or, when a choice set appears in several components, with a hash such as
    ``Status469Enum`` that changes whenever the choices do. Karni names them
    ``<Model><Field>Enum`` instead (``BookingStatusEnum``, ``EventStatusEnum``),
    so generated TypeScript types keep readable, stable names:

    * A field name used for one choice set keeps drf-spectacular's plain
      ``<Field>Enum``, so schemas without a collision do not change.
    * The model is the serializer's ``Meta.model``. A serializer without a
      model contributes its component name, as drf-spectacular does.
    * One choice set shared by several models stays one enum, named after
      all of them in alphabetical order (``InvoiceOrderStatusEnum``).
    * Two models of the same name in different apps get the app label in
      front (``EventsBookingStatusEnum``). An enum whose name is still taken
      keeps drf-spectacular's name.
    * drf-spectacular's collision warning is dropped for the enums Karni
      named. Every other warning is reported as usual.

    Override / escape hatch: a choice set listed in
    ``SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"]`` keeps the project's name.
    For drf-spectacular's own naming, list
    ``"drf_spectacular.hooks.postprocess_schema_enums"`` in
    ``POSTPROCESSING_HOOKS`` in place of this hook, or point it at your own.
    """
    from drf_spectacular.drainage import GENERATOR_STATS
    from drf_spectacular.hooks import postprocess_schema_enums as spectacular_enums

    before = set(result.get("components", {}).get("schemas", {}))
    caches = (GENERATOR_STATS._warn_cache, GENERATOR_STATS._error_cache)
    reported = [dict(cache) for cache in caches]
    silent = bool(GENERATOR_STATS.silent)
    with GENERATOR_STATS.silence():  # held back until Karni knows which collisions it named
        result = spectacular_enums(result, generator, **kwargs)
    schemas = result.get("components", {}).get("schemas", {})
    renames = _enum_renames(schemas, generator, created=set(schemas) - before)
    if renames:
        _rename_schemas(result, generator, renames)
    resolved = tuple(f'resolved with "{old}"' for old in renames)
    for cache, earlier in zip(caches, reported, strict=True):
        for message in [m for m in cache if cache[m] > earlier.get(m, 0)]:
            if any(marker in message for marker in resolved):
                if message in earlier:
                    cache[message] = earlier[message]
                else:
                    del cache[message]
            elif not silent and message not in earlier:
                print(message, file=sys.stderr)  # what drf-spectacular would have printed
    return result


def _enum_renames(
    schemas: Mapping[str, Any], generator: Any, *, created: set[str]
) -> dict[str, str]:
    """``{drf-spectacular's name: Karni's name}`` for the enums whose plain name collided."""
    from drf_spectacular.plumbing import load_enum_name_overrides
    from drf_spectacular.settings import spectacular_settings

    suffix = str(spectacular_settings.ENUM_SUFFIX)
    overridden = set(load_enum_name_overrides().values())
    users: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for component, properties in _property_maps(schemas):
        for prop, prop_schema in properties.items():
            enum = _enum_target(prop_schema)
            if enum is not None and enum in created:
                users[enum].append((component, prop))
    wanted: dict[str, tuple[str, str]] = {}
    for enum, uses in users.items():
        if enum in overridden or any(_camelize(prop) + suffix == enum for _, prop in uses):
            continue  # the project's override, or drf-spectacular's plain <Field>Enum
        owners = [_enum_owner(generator, component) for component, _ in uses]
        owners = [owner for owner in owners if owner.is_model] or owners
        fields = "".join(sorted({_camelize(prop) for _, prop in uses}))
        wanted[enum] = (
            "".join(sorted({owner.name for owner in owners})) + fields + suffix,
            "".join(sorted({owner.qualified for owner in owners})) + fields + suffix,
        )
    return _assign_enum_names(wanted, taken=set(schemas))


def _assign_enum_names(wanted: Mapping[str, tuple[str, str]], *, taken: set[str]) -> dict[str, str]:
    """Pick each enum's short name, else its app-qualified one, never a name in use.

    A name two enums want goes to neither (both try the next form), so the
    result does not depend on order. An enum with no free name is left out
    and keeps drf-spectacular's name.
    """
    chosen: dict[str, str] = {}
    for form in (0, 1):
        pending = [enum for enum in sorted(wanted) if enum not in chosen]
        demand = Counter(wanted[enum][form] for enum in pending)
        for enum in pending:
            name = wanted[enum][form]
            free = name == enum or (name not in taken and name not in chosen.values())
            if demand[name] == 1 and free:
                chosen[enum] = name
    return {old: new for old, new in chosen.items() if old != new}


def _property_maps(schemas: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """``(component, properties)`` pairs, as drf-spectacular's enum hook walks them."""

    def walk(name: str, node: Any) -> Iterator[tuple[str, Mapping[str, Any]]]:
        if isinstance(node, list):
            for item in node:
                yield from walk(name, item)
        elif isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict) and properties:
                yield name, properties
            for key in ("oneOf", "allOf", "anyOf"):
                yield from walk(name, node.get(key, []))

    for name, schema in schemas.items():
        yield from walk(name, schema)


def _enum_target(schema: Any) -> str | None:
    """The component a property's choices point at (drf-spectacular puts it first)."""
    if isinstance(schema, dict) and schema.get("type") == "array":
        schema = schema.get("items")
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    for key in ("allOf", "oneOf"):
        branches = schema.get(key)
        if ref is None and isinstance(branches, list) and branches:
            first = branches[0]
            ref = first.get("$ref") if isinstance(first, dict) else None
    if isinstance(ref, str) and ref.startswith(_SCHEMA_REF):
        return ref.removeprefix(_SCHEMA_REF)
    return None


def _enum_owner(generator: Any, component: str) -> _EnumOwner:
    """The model behind ``component``'s serializer, else the component's base name."""
    from drf_spectacular.settings import spectacular_settings

    model = _serializer_model(generator, component)
    if model is not None:
        name = model.__name__
        return _EnumOwner(name, _camelize(model._meta.app_label) + name, is_model=True)
    # The request and patch twins of a component share its base name.
    if spectacular_settings.COMPONENT_SPLIT_PATCH:
        component = re.sub("^Patched(.+)", r"\1", component)
    if spectacular_settings.COMPONENT_SPLIT_REQUEST:
        component = re.sub("(.+)Request$", r"\1", component)
    return _EnumOwner(component, component, is_model=False)


def _serializer_model(generator: Any, component: str) -> type[Model] | None:
    """``Meta.model`` of the serializer registered as ``component``, if it has one."""
    from drf_spectacular.plumbing import ResolvedComponent

    registry = getattr(generator, "registry", None)
    if registry is None:
        return None
    try:
        resolved = registry[(component, ResolvedComponent.SCHEMA)]
    except KeyError:
        return None
    model = getattr(getattr(resolved.object, "Meta", None), "model", None)
    return model if isinstance(model, type) and issubclass(model, Model) else None


def _rename_schemas(result: dict[str, Any], generator: Any, renames: Mapping[str, str]) -> None:
    """Rename schema components (kept sorted) and every ``$ref`` that points at them."""
    from drf_spectacular.plumbing import ResolvedComponent

    components = result["components"]
    renamed = {renames.get(name, name): schema for name, schema in components["schemas"].items()}
    components["schemas"] = dict(sorted(renamed.items()))
    _rewrite_refs(result, {_SCHEMA_REF + old: _SCHEMA_REF + new for old, new in renames.items()})
    registry = getattr(generator, "registry", None)
    if registry is None:
        return
    for old, new in renames.items():  # so a later hook that rebuilds components agrees
        try:
            resolved = registry[(old, ResolvedComponent.SCHEMA)]
        except KeyError:
            continue
        del registry[resolved]
        resolved.name = new
        registry.register_on_missing(resolved)


def _rewrite_refs(node: Any, refs: Mapping[str, str]) -> None:
    """Point every ``$ref`` found in ``refs`` at its new target, in place."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref in refs:
            node["$ref"] = refs[ref]
        for value in node.values():
            _rewrite_refs(value, refs)
    elif isinstance(node, list):
        for item in node:
            _rewrite_refs(item, refs)


def _camelize(name: str) -> str:
    """``device_type`` to ``DeviceType``, the rule drf-spectacular names enums with."""
    return re.sub(r"(?:^|_)(.)", lambda match: match.group(1).upper(), name)
