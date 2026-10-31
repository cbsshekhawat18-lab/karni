"""Experimental. The API of taxonomy tagging (:mod:`karni.taxonomy`), with no declaration.

A ``BaseViewSet`` whose model declares ``class Karni: taxonomies`` gets, for
each key (``region`` below):

* ``?region=<key>,<key>`` on the list: the rows tagged with any of those
  nodes. With ``?region_descendants=true``, also the rows tagged with any
  node below them. The nodes and the walk are the tree's nodes the requester
  may read, and the filter is one subquery: the cycle-safe walk of
  :mod:`karni.tree` inside the subquery of tagged keys.
* ``GET facets/?taxonomy=region&rollup=true``: how many rows each node counts,
  under the list's filters, search and access (the queryset the list uses,
  :meth:`~karni.api.viewsets.BaseViewSet.facet_queryset`). ``rollup=true``
  counts the rows tagged with a node or any node below it, each row once.
  ``taxonomy`` may be left out when the model has one. The answer is
  ``{"taxonomy", "rollup", "results": [{"id", "label", "parent", "count"}]}``
  in the tree's order, the nodes without a row left out: two queries
  whatever the number of nodes.

A tree resource that a taxonomy points at gets ``GET <key>/tagged/``: for
each tagging model with a routed viewset, how many of its rows are tagged
with the node (``?descendants=true``: with the node or a node below it),
each count under that model's own access: one query per tagging model.

A bad key, an unknown taxonomy or a value other than true or false is a 400
with ``E573``.

Override / escape hatch: ``facet_queryset()`` on the viewset (the rows the
facets count), the actions ``facets`` and ``tagged`` themselves, or the
queries of :mod:`karni.taxonomy`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import django_filters
from django.core.exceptions import ValidationError
from django.db import models
from django_filters.rest_framework import BooleanFilter
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.response import Response

from karni.exceptions import api_error
from karni.taxonomy import Taxonomy, facets, get_taxonomy, tagged_rows, tagging, taxonomies

if TYPE_CHECKING:
    from rest_framework.request import Request

__all__ = [
    "TaxonomyDescendantsFilter",
    "TaxonomyFilter",
    "facets_response",
    "facets_serializer",
    "tagged_response",
    "tagged_serializer",
    "taxonomy_filters",
]

_FACETS_CACHE: dict[type[models.Model], type[serializers.Serializer[Any]]] = {}
_TAGGED_CACHE: dict[type[models.Model], type[serializers.Serializer[Any]]] = {}


# reading the request


def parse_flag(value: Any, param: str) -> bool:
    """``true``/``1`` or ``false``/``0`` (absent is false), else a 400 with ``E573``."""
    if value in (None, ""):
        return False
    lowered = str(value).lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise api_error("E573", f"?{param}= takes true or false, not {value!r}.", field=param)


def parse_nodes(tree: type[models.Model], value: Any, param: str) -> list[Any]:
    """``"<key>,<key>"`` as keys of ``tree``, once each, else a 400 with ``E573``."""
    from karni.tree import pk_field

    pk = pk_field(tree)
    keys: list[Any] = []
    for part in str(value).split(","):
        text = part.strip()
        if not text:
            continue
        try:
            key = pk.to_python(text)
        except ValidationError as exc:
            raise api_error(
                "E573",
                f"?{param}={value!r}: {text!r} is not a key of {tree.__name__}. Send keys "
                "separated by commas.",
                field=param,
            ) from exc
        if key not in keys:
            keys.append(key)
    return keys


def readable_nodes(taxonomy: Taxonomy, request: Any) -> models.QuerySet[Any]:
    """The tree's live nodes ``request`` may read (through the tree's routed viewset)."""
    from karni.api.access import readable

    return readable(taxonomy.tree._default_manager.all(), request)


# list filters


@extend_schema_field(OpenApiTypes.STR)
class TaxonomyFilter(django_filters.CharFilter):
    """Experimental. ``?<key>=<node>,<node>``: the rows tagged with any of those nodes.

    With ``?<key>_descendants=true`` it also reads the rows tagged with any
    node below them. Nodes the requester may not read match nothing, and
    hide their branch.
    """

    def filter(self, qs: Any, value: Any) -> Any:
        if value in (None, ""):
            return qs
        taxonomy = get_taxonomy(self.model, self.field_name)
        if taxonomy is None:
            return qs
        keys = parse_nodes(taxonomy.tree, value, self.field_name)
        parent = getattr(self, "parent", None)
        data = getattr(parent, "data", None) or {}
        param = taxonomy.descendants_param
        descendants = parse_flag(data.get(param), param)
        within = readable_nodes(taxonomy, getattr(parent, "request", None))
        return qs.filter(tagged_rows(taxonomy, keys, descendants=descendants, within=within))


class TaxonomyDescendantsFilter(BooleanFilter):
    """Experimental. ``?<key>_descendants=true``: read by :class:`TaxonomyFilter`, filters nothing.

    Its ``field_name`` is the taxonomy key, so a field ``Karni.field_roles``
    hides takes its two filters with it.
    """

    def filter(self, qs: Any, value: Any) -> Any:
        return qs


def taxonomy_filters(
    model: type[models.Model], allowed: frozenset[str] | None = None
) -> dict[str, django_filters.Filter]:
    """The filters of ``model``'s taxonomies (``allowed``: the API's field names; ``None``: all)."""
    found: dict[str, django_filters.Filter] = {}
    for key, taxonomy in taxonomies(model).items():
        if allowed is not None and key not in allowed:
            continue
        if taxonomy.problem() is not None:
            continue
        tree = taxonomy.tree.__name__
        found[key] = TaxonomyFilter(
            field_name=key,
            help_text=f"Keys of {tree} nodes, separated by commas: the rows tagged with any.",
        )
        found[taxonomy.descendants_param] = TaxonomyDescendantsFilter(
            field_name=key,
            help_text=f"true: also the rows tagged with a node below those of ?{key}=.",
        )
    return found


# facets/


def _key_field(model: type[models.Model], **kwargs: Any) -> serializers.Field[Any, Any, Any, Any]:
    from karni.api.tree import _key_field as key_field

    return key_field(model, **kwargs)


def facets_serializer(model: type[models.Model]) -> type[serializers.Serializer[Any]]:
    """Experimental. The ``facets/`` answer of ``model``: ``{taxonomy, rollup, results}``.

    The serializers describe the answer in the OpenAPI document (components
    ``<Stem>FacetNode`` and ``<Stem>Facets``). The node key is typed after the
    first taxonomy's tree.
    """
    cached = _FACETS_CACHE.get(model)
    if cached is not None:
        return cached
    from karni.api.serializers import serializer_name

    stem = serializer_name(model).removesuffix("Serializer")
    found = list(taxonomies(model).values())
    keyed = found[0].tree if found and found[0].problem() is None else model
    node: type[serializers.Serializer[Any]] = type(
        f"{stem}FacetNodeSerializer",
        (serializers.Serializer,),
        {
            "__module__": __name__,
            "__doc__": "A node of a facet: its key, label, parent key and how many rows it counts.",
            "id": _key_field(keyed, read_only=True),
            "label": serializers.CharField(read_only=True),
            "parent": _key_field(keyed, read_only=True, allow_null=True),
            "count": serializers.IntegerField(read_only=True),
        },
    )
    answer: type[serializers.Serializer[Any]] = type(
        f"{stem}FacetsSerializer",
        (serializers.Serializer,),
        {
            "__module__": __name__,
            "__doc__": (
                "Rows per node of one taxonomy, under the list's filters and access. With "
                "rollup a node also counts the rows tagged below it."
            ),
            "taxonomy": serializers.CharField(read_only=True),
            "rollup": serializers.BooleanField(read_only=True),
            "results": node(many=True, read_only=True),
        },
    )
    _FACETS_CACHE[model] = answer
    return answer


def facet_taxonomy(model: type[models.Model], value: Any) -> Taxonomy:
    """``?taxonomy=``: one of ``model``'s keys (optional when it has one), else ``E573``."""
    found = taxonomies(model)
    names = ", ".join(found) or "none"
    if value in (None, ""):
        if len(found) == 1:
            return next(iter(found.values()))
        raise api_error(
            "E573",
            f"?taxonomy= names the taxonomy to count. {model.__name__} has {names}.",
            field="taxonomy",
        )
    taxonomy = found.get(str(value))
    if taxonomy is None:
        raise api_error(
            "E573",
            f"?taxonomy={value!r} is not a taxonomy of {model.__name__}. It has {names}.",
            field="taxonomy",
        )
    return taxonomy


def facets_response(view: Any, request: Request) -> Response:
    """``GET facets/``: rows per node of one taxonomy (see the module docstring)."""
    params = request.query_params
    taxonomy = facet_taxonomy(view.get_model(), params.get("taxonomy"))
    rollup = parse_flag(params.get("rollup"), "rollup")
    rows = view.facet_queryset()
    nodes = readable_nodes(taxonomy, request)
    found = facets(taxonomy, rows, rollup=rollup, nodes=nodes)
    return Response(
        {
            "taxonomy": taxonomy.key,
            "rollup": rollup,
            "results": [node.to_dict() for node in found],
        }
    )


# <key>/tagged/


def tagged_serializer(model: type[models.Model]) -> type[serializers.Serializer[Any]]:
    """Experimental. The ``tagged/`` answer of a tree: ``{id, descendants, results}``."""
    cached = _TAGGED_CACHE.get(model)
    if cached is not None:
        return cached
    from karni.api.serializers import serializer_name

    stem = serializer_name(model).removesuffix("Serializer")
    count: type[serializers.Serializer[Any]] = type(
        f"{stem}TaggedCountSerializer",
        (serializers.Serializer,),
        {
            "__module__": __name__,
            "__doc__": "How many rows of one tagging model the node tags, under its access.",
            "model": serializers.CharField(read_only=True),
            "resource": serializers.CharField(read_only=True, allow_null=True),
            "taxonomy": serializers.CharField(read_only=True),
            "count": serializers.IntegerField(read_only=True),
        },
    )
    answer: type[serializers.Serializer[Any]] = type(
        f"{stem}TaggedSerializer",
        (serializers.Serializer,),
        {
            "__module__": __name__,
            "__doc__": "The rows tagged with a node, per tagging model.",
            "id": _key_field(model, read_only=True),
            "descendants": serializers.BooleanField(read_only=True),
            "results": count(many=True, read_only=True),
        },
    )
    _TAGGED_CACHE[model] = answer
    return answer


def _prefix(viewset: type[Any]) -> str | None:
    """The router prefix ``viewset`` is registered under (``None`` when it is not)."""
    from karni.api.routers import resolve_router

    router = resolve_router()
    for prefix, registered, _basename in getattr(router, "registry", ()) or ():
        if registered is viewset:
            return str(prefix)
    return None


def tagged_response(view: Any, request: Request) -> Response:
    """``GET <key>/tagged/``: rows tagged with the node per tagging model, each under its access."""
    from karni.api.access import routed_view

    node = view.get_object()
    descendants = parse_flag(request.query_params.get("descendants"), "descendants")
    nodes = view.get_queryset()
    results: list[dict[str, Any]] = []
    for taxonomy in tagging(view.get_model()):
        rows_view = routed_view(taxonomy.model, request)
        if rows_view is None:
            continue  # not an API resource: no access declaration to count under
        rows, _filtered = rows_view.read_scope(rows_view.base_queryset())
        count = rows.filter(
            tagged_rows(taxonomy, [node.pk], descendants=descendants, within=nodes)
        ).count()
        results.append(
            {
                "model": taxonomy.model._meta.label_lower,
                "resource": _prefix(type(rows_view)),
                "taxonomy": taxonomy.key,
                "count": count,
            }
        )
    return Response({"id": node.pk, "descendants": descendants, "results": results})


def serves_facets(model: type[models.Model] | None) -> bool:
    """Whether ``model`` declares a taxonomy (its viewset then routes ``facets/``)."""
    if model is None:
        return False
    try:
        return bool(taxonomies(model))
    except Exception:  # noqa: BLE001 - a malformed declaration fails at import (E570)
        return False


def serves_tagged(model: type[models.Model] | None) -> bool:
    """Whether a taxonomy points at ``model`` (its viewset then routes ``<key>/tagged/``)."""
    from karni.tree import is_tree_model

    if model is None or not is_tree_model(model):
        return False
    return bool(tagging(model))
