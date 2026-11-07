"""Experimental. ``GET /api/search/``: one ranked search over every model that opts in.

A model opts in with ``class Karni: search = {...}`` (:mod:`karni.global_search`).
The endpoint is mounted by ``karni.api.urls``, next to the routed resources::

    GET /api/search/?q=lamp&models=products,suppliers&limit=5

    {"query": "lamp",
     "groups": [{"resource": "products", "label": "Products",
                 "hits": [{"resource": "products", "id": 7, "title": "Desk lamp",
                           "subtitle": "LMP-01", "score": 1.4}]}]}

* **Access per model.** Each model is searched through the queryset its own
  list endpoint uses for this request: the routed ``BaseViewSet``'s request
  gate, then its ``get_queryset()`` (model scopes, the ``access.read`` row
  filter, ``filter_queryset_for_user``). A model the caller cannot list is
  left out, and so is every row its list leaves out.
* **One query per model.** Each model's hits are one ``SELECT``, plus what
  access needs to know about the user (once per request).
* **Ranking.** On PostgreSQL a row matches when a searched field contains the
  query (``ILIKE``) or is similar to it (pg_trgm ``%``, then
  ``KARNI_GLOBAL_SEARCH_THRESHOLD``), and scores the greatest trigram
  similarity of its fields. On another database (SQLite) a row matches when a
  field contains the query, and scores 1 when a field equals it, 0.75 when a
  field starts with it, else 0.5. A model's ``weight`` multiplies its scores.
  Hits are best first within a group, and groups are ordered by their best
  hit.
* **Limits.** ``?limit=`` hits per model (``KARNI_GLOBAL_SEARCH_LIMIT``, at
  most ``KARNI_GLOBAL_SEARCH_MAX_LIMIT``). ``?models=`` names the resources
  to search (comma-separated). A resource search does not cover answers 400
  ``E431``. A query shorter than ``KARNI_GLOBAL_SEARCH_MIN_LENGTH`` answers
  no groups, not an error.

Each hit carries its ``resource`` (the router prefix) and ``id``, so a client
links it to the resource's detail page (``/<resource>/<id>`` in a Karni
frontend). The OpenAPI operation carries ``x-karni-search``: the resources
it covers.

Override / escape hatch: override a viewset's ``global_search_queryset`` to
change how one model matches and ranks (call :func:`search_queryset` for the
default). Subclass :class:`GlobalSearchView` (``get_targets``,
``bound_view``, ``search_target``, ``get_limit``) and declare
``path("api/search/", MyView.as_view())`` before Karni's API include to
replace the endpoint.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Final

from django.conf import settings
from django.db import connections
from django.db.models import (
    Case,
    CharField,
    F,
    FloatField,
    Lookup,
    Model,
    Q,
    QuerySet,
    Value,
    When,
)
from django.utils.text import capfirst
from drf_spectacular.utils import OpenApiParameter, extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from karni.api.schema import KarniAutoSchema
from karni.exceptions import KarniImproperlyConfigured
from karni.global_search import SearchDeclaration, search_declaration, searchable_models

__all__ = [
    "SCORE",
    "SUBTITLE",
    "TITLE",
    "GlobalSearchErrorSerializer",
    "GlobalSearchGroupSerializer",
    "GlobalSearchHitSerializer",
    "GlobalSearchResultSerializer",
    "GlobalSearchSchema",
    "GlobalSearchView",
    "SearchTarget",
    "search_queryset",
    "search_targets",
]

#: The annotation a search queryset carries for each hit's title.
TITLE: Final = "karni_search_title"
#: The annotation for each hit's subtitle (``None`` when the model has none).
SUBTITLE: Final = "karni_search_subtitle"
#: The annotation for each hit's score, before the model's weight.
SCORE: Final = "karni_search_score"

_PORTABLE_SCORES: Final = (1.0, 0.75, 0.5)


@dataclass(frozen=True)
class SearchTarget:
    """Experimental. One searchable resource: its model, routed viewset and declaration."""

    resource: str
    model: type[Model]
    viewset: type[Any]
    declaration: SearchDeclaration
    label: str


def search_targets(router: Any | None = None) -> list[SearchTarget]:
    """Experimental. Every model that declares ``Karni.search`` and has a routed ``BaseViewSet``.

    In the router's registration order, one target per model (the first
    viewset that serves it, as :func:`karni.api.routers.viewset_for_model`
    picks). A malformed declaration is left out: ``karni check`` reports it
    (``E430``).
    """
    from karni.api.routers import resolve_router
    from karni.api.viewsets import BaseViewSet

    declared = set(searchable_models())
    if not declared:
        return []
    registry = getattr(router if router is not None else resolve_router(), "registry", ())
    targets: list[SearchTarget] = []
    seen: set[type[Model]] = set()
    for prefix, viewset, _basename in registry:
        if not (isinstance(viewset, type) and issubclass(viewset, BaseViewSet)):
            continue
        model = getattr(viewset, "model", None) or getattr(
            getattr(viewset, "queryset", None), "model", None
        )
        if model not in declared or model in seen:
            continue
        seen.add(model)
        try:
            declaration = search_declaration(model)
        except KarniImproperlyConfigured:
            continue
        if declaration is None:
            continue
        label = str(capfirst(model._meta.verbose_name_plural))
        targets.append(SearchTarget(str(prefix), model, viewset, declaration, label))
    return targets


# matching and ranking -------------------------------------------------------------------


class _ILike(Lookup):  # type: ignore[type-arg]
    """``lhs ILIKE rhs``: the form a GIN trigram index answers (Django's icontains uses UPPER)."""

    lookup_name = "karni_ilike"
    prepare_rhs = False

    def as_sql(self, compiler: Any, connection: Any) -> tuple[str, list[Any]]:
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"{lhs} ILIKE {rhs}", [*lhs_params, *rhs_params]


def _like_pattern(query: str) -> str:
    """``%query%`` with LIKE's wildcards in ``query`` escaped (backslash is the escape)."""
    return "%" + re.sub(r"([\\%_])", r"\\\1", query) + "%"


def _any(conditions: Sequence[Any]) -> Q:
    combined = Q()
    for condition in conditions:
        combined |= condition if isinstance(condition, Q) else Q(condition)
    return combined


def _postgres(queryset: QuerySet[Any], query: str, fields: Sequence[str]) -> QuerySet[Any]:
    from django.contrib.postgres.lookups import TrigramSimilar
    from django.contrib.postgres.search import TrigramSimilarity
    from django.db.models.functions import Greatest

    threshold = float(getattr(settings, "KARNI_GLOBAL_SEARCH_THRESHOLD", 0.3))
    similarities = [TrigramSimilarity(name, query) for name in fields]
    score = similarities[0] if len(similarities) == 1 else Greatest(*similarities)
    pattern = Value(_like_pattern(query))
    contains = _any([_ILike(F(name), pattern) for name in fields])
    # The lookup classes themselves: django.contrib.postgres need not be installed.
    similar = _any([TrigramSimilar(F(name), Value(query)) for name in fields])
    return queryset.annotate(**{SCORE: score}).filter(
        contains | (similar & Q(**{f"{SCORE}__gt": threshold}))
    )


def _portable(queryset: QuerySet[Any], query: str, fields: Sequence[str]) -> QuerySet[Any]:
    exact, prefix, contained = _PORTABLE_SCORES
    score = Case(
        When(_any([Q(**{f"{name}__iexact": query}) for name in fields]), then=Value(exact)),
        When(_any([Q(**{f"{name}__istartswith": query}) for name in fields]), then=Value(prefix)),
        default=Value(contained),
        output_field=FloatField(),
    )
    contains = _any([Q(**{f"{name}__icontains": query}) for name in fields])
    return queryset.filter(contains).annotate(**{SCORE: score})


def search_queryset(
    queryset: QuerySet[Any], query: str, declaration: SearchDeclaration
) -> QuerySet[Any]:
    """Experimental. The rows of ``queryset`` that match ``query``, best first.

    The default every ``BaseViewSet.global_search_queryset`` returns (see the
    module docstring for the matching and the scores). The result carries the
    annotations :data:`TITLE`, :data:`SUBTITLE` and :data:`SCORE` and is
    ordered by score, then title, then primary key. Nothing runs until the
    caller slices and evaluates it.
    """
    fields = list(declaration.fields)
    if connections[queryset.db].vendor == "postgresql":
        matched = _postgres(queryset, query, fields)
    else:
        matched = _portable(queryset, query, fields)
    subtitle: Any = (
        F(declaration.subtitle)
        if declaration.subtitle is not None
        else Value(None, output_field=CharField())
    )
    return matched.annotate(**{TITLE: F(declaration.title), SUBTITLE: subtitle}).order_by(
        f"-{SCORE}", TITLE, "pk"
    )


# the response, for the OpenAPI document -------------------------------------------------


@extend_schema_field({"oneOf": [{"type": "string"}, {"type": "integer"}]})
class _KeyField(serializers.Field):  # type: ignore[type-arg]
    """A primary key: a UUID as text, an integer as a number."""

    def to_representation(self, value: Any) -> Any:
        return value


class GlobalSearchHitSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. One hit: a row of one resource, ready to link to its page."""

    resource = serializers.CharField(help_text="The resource (router prefix) of the row.")
    id = _KeyField(help_text="The row's primary key: its page is /<resource>/<id>.")
    title = serializers.CharField()
    subtitle = serializers.CharField(allow_null=True)
    score = serializers.FloatField(help_text="Higher is better, the model's weight included.")


class GlobalSearchGroupSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. The hits of one resource, best first."""

    resource = serializers.CharField()
    label = serializers.CharField(help_text="The model's plural name, for a heading.")
    hits = GlobalSearchHitSerializer(many=True)


class GlobalSearchResultSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. The answer of GET /api/search/: groups ordered by their best hit."""

    query = serializers.CharField()
    groups = GlobalSearchGroupSerializer(many=True)


class GlobalSearchErrorSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """Experimental. A refused request: E431 and the resources search covers."""

    code = serializers.CharField()
    detail = serializers.CharField()
    resources = serializers.ListField(child=serializers.CharField())


class GlobalSearchSchema(KarniAutoSchema):
    """Experimental. The OpenAPI operation of :class:`GlobalSearchView`.

    Documents ``q``, ``models`` (an enum of the resources search covers),
    ``limit``, the response, and ``x-karni-search: {"resources": [...]}``.
    """

    def get_operation(
        self, path: str, path_regex: str, path_prefix: str, method: str, registry: Any
    ) -> dict[str, Any] | None:
        operation = super().get_operation(path, path_regex, path_prefix, method, registry)
        if operation is not None:
            operation["x-karni-search"] = {"resources": self._resources()}
        return operation

    def get_operation_id(self) -> str:
        return "global_search"

    def get_tags(self) -> list[str]:
        return ["search"]

    def get_description(self) -> str:  # type: ignore[override]
        return (
            "Experimental. Search every model that declares class Karni: search, each "
            "through its list endpoint's access for this request. Results are grouped per "
            "resource, best first."
        )

    def get_response_serializers(self) -> Any:
        return {200: GlobalSearchResultSerializer, 400: GlobalSearchErrorSerializer}

    def get_request_serializer(self) -> Any:
        return None

    def _resources(self) -> list[str]:
        return [target.resource for target in search_targets()]

    def get_override_parameters(self) -> list[Any]:
        resources = self._resources()
        models = OpenApiParameter(
            name="models",
            type=str,
            many=True,
            explode=False,
            style="form",
            location=OpenApiParameter.QUERY,
            required=False,
            enum=resources or None,
            description="Comma-separated resources to search (default: every one search covers).",
        )
        return [
            OpenApiParameter(
                name="q",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "The query. Shorter than KARNI_GLOBAL_SEARCH_MIN_LENGTH (2) answers no groups."
                ),
            ),
            models,
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Hits per resource (KARNI_GLOBAL_SEARCH_LIMIT, at most "
                "KARNI_GLOBAL_SEARCH_MAX_LIMIT).",
            ),
        ]


# the endpoint ---------------------------------------------------------------------------


class GlobalSearchView(APIView):
    """Experimental. ``GET /api/search/?q=&models=&limit=`` (see the module docstring).

    Open to every caller: what each one finds is what each model's list
    endpoint shows them.
    """

    permission_classes: ClassVar[list[type]] = [AllowAny]
    schema = GlobalSearchSchema()
    #: The query parameters, by role.
    query_param: ClassVar[str] = "q"
    models_param: ClassVar[str] = "models"
    limit_param: ClassVar[str] = "limit"

    def get(self, request: Request, **kwargs: Any) -> Response:
        query = self.get_query(request)
        targets = self.get_targets()
        known = {target.resource: target for target in targets}
        wanted = self.get_models(request)
        unknown = [name for name in wanted if name not in known]
        if unknown:
            return Response(
                {
                    "code": "E431",
                    "detail": (
                        f"?{self.models_param}= names {', '.join(unknown)}, which search does "
                        f"not cover. It covers: {', '.join(known) or 'nothing yet'}."
                    ),
                    "resources": list(known),
                },
                status=400,
            )
        minimum = int(getattr(settings, "KARNI_GLOBAL_SEARCH_MIN_LENGTH", 2))
        if len(query) < max(minimum, 1):
            return Response({"query": query, "groups": []})
        selected = [known[name] for name in wanted] if wanted else targets
        limit = self.get_limit(request)
        groups = [
            group
            for group in (self.search_target(target, query, limit) for target in selected)
            if group is not None and group["hits"]
        ]
        groups.sort(key=lambda group: -float(group["hits"][0]["score"]))
        return Response({"query": query, "groups": groups})

    def get_query(self, request: Request) -> str:
        """The stripped ``?q=`` (empty when absent)."""
        value = request.query_params.get(self.query_param, "")
        return value.strip() if isinstance(value, str) else ""

    def get_models(self, request: Request) -> list[str]:
        """The resources ``?models=`` names (comma-separated or repeated), in order."""
        names: list[str] = []
        for value in request.query_params.getlist(self.models_param):
            for part in str(value).split(","):
                name = part.strip()
                if name and name not in names:
                    names.append(name)
        return names

    def get_limit(self, request: Request) -> int:
        """``?limit=`` within 1 and ``KARNI_GLOBAL_SEARCH_MAX_LIMIT``; the default otherwise."""
        default = int(getattr(settings, "KARNI_GLOBAL_SEARCH_LIMIT", 5))
        ceiling = int(getattr(settings, "KARNI_GLOBAL_SEARCH_MAX_LIMIT", 20))
        raw = request.query_params.get(self.limit_param)
        try:
            limit = int(raw) if raw not in (None, "") else default
        except (TypeError, ValueError):
            limit = default
        return max(1, min(limit, ceiling))

    def get_targets(self) -> list[SearchTarget]:
        """The resources this endpoint covers (:func:`search_targets`)."""
        return search_targets()

    def bound_view(self, target: SearchTarget) -> Any:
        """An instance of ``target``'s viewset bound to this request, as its ``list`` action."""
        view = target.viewset()
        view.request = self.request
        view.args = ()
        view.kwargs = {}
        view.format_kwarg = None
        view.action = "list"
        view.detail = False
        view.basename = target.resource
        return view

    def search_target(self, target: SearchTarget, query: str, limit: int) -> dict[str, Any] | None:
        """The group of ``target``: its best ``limit`` hits, or ``None`` if it is not listable."""
        view = self.bound_view(target)
        try:
            view.check_permissions(self.request)
        except (NotAuthenticated, PermissionDenied):
            return None
        queryset = view.get_queryset().prefetch_related(None)
        matched = view.global_search_queryset(queryset, query, target.declaration)
        rows = matched.values_list("pk", TITLE, SUBTITLE, SCORE)[:limit]
        weight = target.declaration.weight
        hits = [
            {
                "resource": target.resource,
                "id": pk if isinstance(pk, int) else str(pk),
                "title": str(title) if title is not None else str(pk),
                "subtitle": str(subtitle) if subtitle is not None else None,
                "score": round(float(score or 0) * weight, 4),
            }
            for pk, title, subtitle, score in rows
        ]
        return {"resource": target.resource, "label": target.label, "hits": hits}
