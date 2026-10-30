"""Experimental. The tree endpoints a ``BaseViewSet`` serves when its model is a tree model.

A viewset whose model is a :class:`karni.models.TreeModel` gets four more
routes, and its list two more filters, with no declaration:

* ``GET tree/?root=<key>&depth=<n>``: the tree, nested. Without ``root`` the
  top level is the roots, and for a requester who reads only part of the
  tree, each readable node whose parent is live but out of their read scope.
  With ``root`` it is that node's children. ``depth`` (default 2) counts the
  levels returned, and at most ``tree_max_nodes`` nodes come back: a level
  that does not fit is left out whole and ``truncated`` is true. Every node
  says whether it has children (``has_children``), and ``children`` is
  ``null`` where they were not loaded, so a client loads a branch when it is
  opened.
* ``GET <key>/children/``: the children of a node, paginated, in sibling order.
* ``GET <key>/ancestors/``: the nodes above a node, root first.
* ``POST <key>/move/`` with ``{"parent": <key or null>, "position": <n>}``:
  write access to the node and a readable new parent. A parent below the
  node is a 400 on ``parent`` (``E340``).
* ``?parent=<key>``, ``?parent=null`` (the roots) and ``?descendants_of=<key>``
  on the list.

Access applies to all of them: each walk follows only the live rows the
requester may read (:mod:`karni.tree`), so a node out of scope hides its
branch, as a soft-deleted node does. Query counts do not grow with the
number of nodes: ``tree/`` runs one walk and one fetch, plus the
prefetches of the serializer.

Every tree endpoint answers with tree nodes: the row, as the viewset's
serializer renders it, plus ``has_children`` and ``children``
(:func:`tree_node_serializer`).

Override / escape hatch: the viewset attributes ``tree_max_nodes``,
``tree_default_depth`` and ``tree_max_depth``, the methods
``tree_top_level()`` and ``get_tree_node_serializer_class()``, or the actions
themselves (``tree``, ``children``, ``ancestors``, ``move``) on a subclass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import django_filters
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Exists, OuterRef, Q
from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from karni.exceptions import api_error
from karni.tree import is_tree_model

if TYPE_CHECKING:
    from rest_framework.request import Request

__all__ = [
    "DescendantsFilter",
    "TreeChildrenField",
    "TreeParentFilter",
    "tree_move_serializer",
    "tree_node_serializer",
    "tree_response_serializer",
]

#: The annotation that carries ``has_children`` (an ``Exists`` over the readable children).
HAS_CHILDREN: Final = "tree_has_children"

_NODE_CACHE: dict[type[Any], type[serializers.Serializer[Any]]] = {}
_RESPONSE_CACHE: dict[type[Any], type[serializers.Serializer[Any]]] = {}
_MOVE_CACHE: dict[type[models.Model], type[serializers.Serializer[Any]]] = {}


# serializers


class HasChildrenField(serializers.BooleanField):
    """Experimental. ``has_children``: whether the node has children the requester may read.

    The tree endpoints annotate it in the query that fetches the nodes. A row
    without the annotation asks the database (one query), so a single node
    still renders right.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("read_only", True)
        super().__init__(**kwargs)

    def get_attribute(self, instance: Any) -> Any:
        if hasattr(instance, HAS_CHILDREN):
            return bool(getattr(instance, HAS_CHILDREN))
        return bool(type(instance)._default_manager.filter(parent=instance).exists())


class TreeChildrenField(serializers.Field):  # type: ignore[type-arg]
    """Experimental. ``children``: the nested nodes ``tree/`` loaded, else ``null``.

    The serializer always renders ``null``. The ``tree/`` endpoint fills the
    lists in after rendering every node in one pass, so the per-page access
    checks run once for the whole tree.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs["read_only"] = True
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)

    def get_attribute(self, instance: Any) -> Any:
        return None

    def to_representation(self, value: Any) -> Any:
        return value


class TreeChildrenFieldExtension(OpenApiSerializerFieldExtension):
    """``children`` in the OpenAPI document: a nullable array of the node's own component."""

    target_class = "karni.api.tree.TreeChildrenField"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: Any, direction: Any) -> Any:
        component = auto_schema.resolve_serializer(type(self.target.parent), direction)
        return {"type": "array", "items": component.ref, "nullable": True, "readOnly": True}


def _stem(serializer_class: type[Any]) -> str:
    name = serializer_class.__name__
    return name[: -len("Serializer")] if name.endswith("Serializer") else name


def tree_node_serializer(base: type[Any]) -> type[serializers.Serializer[Any]]:
    """Experimental. ``base`` plus ``has_children`` and ``children`` (cached per class).

    The class is named after ``base`` (``TestappRegionSerializer`` gives
    ``TestappRegionTreeNodeSerializer``), so the OpenAPI component is
    ``<stem>TreeNode``.
    """
    cached = _NODE_CACHE.get(base)
    if cached is not None:
        return cached
    attrs: dict[str, Any] = {
        "__module__": base.__module__,
        "__doc__": f"A tree node: {base.__name__} plus has_children and children.",
        "has_children": HasChildrenField(),
        "children": TreeChildrenField(),
    }
    meta = getattr(base, "Meta", None)
    if meta is not None:
        fields = getattr(meta, "fields", None)
        extra: dict[str, Any] = {}
        if isinstance(fields, list | tuple):
            extra["fields"] = [*fields, "has_children", "children"]
        attrs["Meta"] = type("Meta", (meta,), extra)
    name = f"{_stem(base)}TreeNodeSerializer"
    node: type[serializers.Serializer[Any]] = type(name, (base,), attrs)
    _NODE_CACHE[base] = node
    return node


def tree_response_serializer(node: type[Any]) -> type[serializers.Serializer[Any]]:
    """Experimental. The ``tree/`` answer: ``{"results": [node], "truncated": bool}``."""
    cached = _RESPONSE_CACHE.get(node)
    if cached is not None:
        return cached
    stem = _stem(node).removesuffix("TreeNode")
    response: type[serializers.Serializer[Any]] = type(
        f"{stem}TreeSerializer",
        (serializers.Serializer,),
        {
            "__module__": node.__module__,
            "__doc__": "The tree: the top level, nested, and whether the node limit cut it.",
            "results": node(many=True, read_only=True),
            "truncated": serializers.BooleanField(read_only=True),
        },
    )
    _RESPONSE_CACHE[node] = response
    return response


def tree_move_serializer(model: type[models.Model]) -> type[serializers.Serializer[Any]]:
    """Experimental. The body of ``move/``: ``parent`` (a key or null) and ``position``."""
    cached = _MOVE_CACHE.get(model)
    if cached is not None:
        return cached
    from karni.api.serializers import serializer_name

    pk = model._meta.pk
    key: serializers.Field[Any, Any, Any, Any]
    if isinstance(pk, models.UUIDField):
        key = serializers.UUIDField(allow_null=True)
    elif isinstance(pk, models.IntegerField | models.AutoField):
        key = serializers.IntegerField(allow_null=True)
    else:
        key = serializers.CharField(allow_null=True)
    move: type[serializers.Serializer[Any]] = type(
        serializer_name(model).removesuffix("Serializer") + "MoveSerializer",
        (serializers.Serializer,),
        {
            "__module__": __name__,
            "__doc__": "Where to move a node: its new parent (null for a root) and position.",
            "parent": key,
            "position": serializers.IntegerField(
                min_value=0, required=False, allow_null=True, default=None
            ),
        },
    )
    _MOVE_CACHE[model] = move
    return move


# reading the request


def parse_key(model: type[models.Model], value: Any, param: str) -> Any:
    """A key of ``model`` from a query parameter, or a 400 with ``E342`` naming ``param``."""
    from karni.tree import pk_field

    try:
        return pk_field(model).to_python(value)
    except ValidationError as exc:
        raise api_error(
            "E342", f"?{param}={value!r} is not a key of {model.__name__}.", field=param
        ) from exc


def parse_depth(view: Any, value: str | None) -> int:
    """``?depth=``: a whole number from 1 to ``tree_max_depth`` (else ``tree_default_depth``)."""
    if value in (None, ""):
        return int(view.tree_default_depth)
    maximum = int(view.tree_max_depth)
    try:
        depth = int(str(value))
    except ValueError:
        depth = 0
    if not 1 <= depth <= maximum:
        raise api_error(
            "E342",
            f"?depth= takes a whole number from 1 to {maximum}, not {value!r}.",
            field="depth",
        )
    return depth


def parse_branch(value: str | None) -> bool:
    """``?branch=``: true or false (absent is false)."""
    if value in (None, ""):
        return False
    lowered = str(value).lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise api_error("E342", f"?branch= takes true or false, not {value!r}.", field="branch")


# the endpoints


def with_has_children(queryset: Any, readable: Any) -> Any:
    """``queryset`` annotated with ``tree_has_children``: a readable child exists."""
    return queryset.annotate(**{HAS_CHILDREN: Exists(readable.filter(parent=OuterRef("pk")))})


def top_level(view: Any, readable: Any, filtered: bool, base: Any) -> Any:
    """The top of ``tree/`` without ``root``: the roots, or the tops of what the requester reads.

    With a narrowing read scope a node whose parent is live but unreadable
    starts the requester's tree. A node whose parent is soft-deleted stays
    hidden with its branch.
    """
    if not filtered:
        return readable.filter(parent__isnull=True)
    hidden = base.exclude(pk__in=readable.values("pk")).values("pk")
    return readable.filter(Q(parent__isnull=True) | Q(parent__in=hidden))


def render_nodes(view: Any, nodes: list[Any]) -> list[dict[str, Any]]:
    """Every node rendered in one pass (one batch of access checks for the whole list)."""
    serializer_class = view.get_tree_node_serializer_class()
    rendered: list[dict[str, Any]] = list(
        serializer_class(nodes, many=True, context=view.get_serializer_context()).data
    )
    return rendered


def tree_response(view: Any, request: Request) -> Response:
    """``GET tree/``: the nested tree (see the module docstring)."""
    model = view.get_model()
    base = view.base_queryset()
    readable, filtered = view.read_scope(base)
    _require_walks(view, readable)
    params = request.query_params
    depth = parse_depth(view, params.get("depth"))
    max_nodes = max(1, int(view.tree_max_nodes))
    ordering = model.tree_ordering()
    root_value = params.get("root")
    if root_value not in (None, ""):
        key = parse_key(model, root_value, "root")
        if not readable.filter(pk=key).exists():
            raise NotFound(f"No {model.__name__} with the key {root_value!r} is readable here.")
        start: Any = [key]
        include_self, offset, steps = False, 1, depth
        first_level = readable.filter(parent=key)
    else:
        first_level = view.tree_top_level(readable, filtered, base)
        start, include_self, offset, steps = first_level, True, 0, depth - 1
    walked = readable.walk(start, include_self=include_self, max_depth=steps, limit=max_nodes + 1)
    counts: dict[int, int] = {}
    for _key, _parent, level in walked:
        counts[level - offset] = counts.get(level - offset, 0) + 1
    truncated = len(walked) > max_nodes
    kept = depth - 1
    if truncated:
        total, kept = 0, -1
        for level in sorted(counts):
            if total + counts[level] > max_nodes or level == max(counts):
                break
            total += counts[level]
            kept = level
    if kept < 0:
        # Even the first level does not fit: its first nodes in sibling order.
        nodes_qs = first_level.order_by(*ordering)
        nodes = list(
            view.optimize_queryset(
                with_has_children(nodes_qs, readable)[:max_nodes],
                view.get_tree_node_serializer_class(),
            )
        )
        levels = {node.pk: 0 for node in nodes}
        kept = 0
    else:
        nodes_qs = readable.descendants(start, include_self=include_self, max_depth=kept + offset)
        nodes = list(
            view.optimize_queryset(
                with_has_children(nodes_qs, readable).order_by(*ordering),
                view.get_tree_node_serializer_class(),
            )
        )
        levels = {key: level - offset for key, _parent, level in walked}
    rendered = render_nodes(view, nodes)
    by_key = {node.pk: data for node, data in zip(nodes, rendered, strict=True)}
    results: list[dict[str, Any]] = []
    for node, data in zip(nodes, rendered, strict=True):
        level = levels.get(node.pk, 0)
        if level < kept and data.get("has_children"):
            data["children"] = []
        elif not data.get("has_children"):
            data["children"] = []
        parent_data = by_key.get(getattr(node, "parent_id", None))
        if level == 0 or parent_data is None:
            results.append(data)
        elif isinstance(parent_data.get("children"), list):
            parent_data["children"].append(data)
    return Response({"results": results, "truncated": truncated})


def children_response(view: Any, request: Request) -> Response:
    """``GET <key>/children/``: the readable children of a readable node, paginated."""
    node = view.get_object()
    readable = view.get_queryset()
    model = view.get_model()
    children = with_has_children(readable.filter(parent=node), readable).order_by(
        *model.tree_ordering()
    )
    response: Response = view.paginated_response(children, view.get_tree_node_serializer_class())
    return response


def ancestors_response(view: Any, request: Request) -> Response:
    """``GET <key>/ancestors/``: the readable nodes above a node, root first."""
    node = view.get_object()
    readable = view.get_queryset()
    _require_walks(view, readable)
    walked = readable.walk(node, up=True, limit=max(1, int(view.tree_max_nodes)))
    keys = [key for key, _parent, _depth in sorted(walked, key=lambda row: -row[2])]
    found = {
        row.pk: row
        for row in view.optimize_queryset(
            with_has_children(readable.filter(pk__in=keys), readable),
            view.get_tree_node_serializer_class(),
        )
    }
    nodes = [found[key] for key in keys if key in found]
    return Response(render_nodes(view, nodes))


def move_response(view: Any, request: Request) -> Response:
    """``POST <key>/move/``: a new parent (readable) and, on an ordered tree, a position."""
    from karni.exceptions import KarniValueError

    node = view.get_object()
    model = view.get_model()
    body = tree_move_serializer(model)(data=request.data)
    body.is_valid(raise_exception=True)
    parent_key = body.validated_data.get("parent")
    position = body.validated_data.get("position")
    parent = None
    if parent_key is not None:
        parent = view.get_queryset().filter(pk=parent_key).first()
        if parent is None:
            raise api_error(
                "E342",
                f"No {model.__name__} with the key {parent_key!r} is readable here.",
                field="parent",
            )
    try:
        node.move_to(parent, position)
    except KarniValueError as exc:
        if getattr(exc, "code", None) == "E343":
            raise api_error("E343", exc.message, field="position") from exc
        raise
    readable = view.get_queryset()
    moved = with_has_children(readable.filter(pk=node.pk), readable).first() or node
    return Response(render_nodes(view, [moved])[0])


def _require_walks(view: Any, queryset: Any) -> None:
    """The viewset's queryset must be a TreeQuerySet (``E344`` otherwise)."""
    if not hasattr(queryset, "walk"):
        from karni.exceptions import KarniImproperlyConfigured

        raise KarniImproperlyConfigured(
            f"{type(view).__name__}'s queryset of {view.get_model().__name__} has no tree walks. "
            "List TreeModel before the base (class Region(TreeModel, BaseModel)), or build the "
            "manager on karni.managers.TreeQuerySet.",
            code="E344",
        )


# list filters


@extend_schema_field(OpenApiTypes.STR)
class TreeParentFilter(django_filters.CharFilter):
    """Experimental. ``?parent=<key>`` (the children of a node) or ``?parent=null`` (the roots)."""

    def filter(self, qs: Any, value: Any) -> Any:
        if value in (None, ""):
            return qs
        if str(value).lower() == "null":
            return qs.filter(parent__isnull=True)
        return qs.filter(parent=parse_key(qs.model, value, "parent"))


@extend_schema_field(OpenApiTypes.STR)
class DescendantsFilter(django_filters.CharFilter):
    """Experimental. ``?descendants_of=<key>``: every readable node below a readable node.

    The walk runs over the list's readable rows before any other filter, so
    ``?descendants_of=<key>&name__icontains=lake`` is the lakes anywhere in
    that branch.
    """

    def filter(self, qs: Any, value: Any) -> Any:
        if value in (None, ""):
            return qs
        key = parse_key(qs.model, value, "descendants_of")
        readable = getattr(self.parent, "queryset", None)
        if readable is None or not hasattr(readable, "descendants"):
            readable = qs
        return qs.filter(pk__in=readable.descendants([key]).values("pk"))


def tree_filters(model: type[models.Model]) -> dict[str, django_filters.Filter]:
    """The filters a tree model's derived filterset declares (empty for another model)."""
    if not is_tree_model(model):
        return {}
    return {
        "parent": TreeParentFilter(
            field_name="parent",
            help_text="A node's key for its children, or null for the roots.",
        ),
        "descendants_of": DescendantsFilter(
            field_name="pk", help_text="A node's key: every node below it."
        ),
    }
