"""How a saved chart finds its source, checks itself and fetches its data (experimental).

The data is the source resource's own ``GET <source>/aggregate/``, called
in-process as the person viewing the chart: the request is a copy of theirs
with the chart's query string, authenticated as the same user. The source's
access, field visibility, filters, throttles and query budget apply exactly as
if they had called it, so a chart never shows a row the source's list hides.

Override / escape hatch: :func:`sources` decides which resources a chart may
read (``KARNI_API_ROUTER`` decides what is routed), :func:`chart_filters` how
a viewer's filters merge with the chart's, and :func:`run_chart` how the
source is called. Each is a plain function the viewset and the admin call.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from django.http import QueryDict
from karni.aggregation import PARAMETERS, AggregationError, parse_query
from karni.errorcodes import KarniError

if TYPE_CHECKING:
    from karni.api.viewsets import BaseViewSet

    from karni_charts.models import Chart

__all__ = [
    "ChartError",
    "chart_filters",
    "check_chart",
    "run_chart",
    "source_viewset",
    "sources",
]

#: Query parameters a viewer may always send: they never filter (DRF's format suffix).
_IGNORED = frozenset({"format"})


class ChartError(KarniError):
    """Experimental. A chart that cannot run as defined, or a viewer's filter it does not allow."""


def sources() -> dict[str, type[BaseViewSet]]:
    """Experimental. Every routed resource a chart may read: prefix -> viewset.

    A resource qualifies when its viewset (or its model) declares an
    aggregation. A malformed declaration is left out (``karni check`` reports
    it, ``E380``).
    """
    from karni.api.routers import resolve_router
    from karni.api.viewsets import BaseViewSet

    found: dict[str, type[BaseViewSet]] = {}
    for prefix, viewset, _basename in getattr(resolve_router(), "registry", ()):
        if prefix in found or not (isinstance(viewset, type) and issubclass(viewset, BaseViewSet)):
            continue
        try:
            declared = viewset().get_aggregation()
        except KarniError:
            continue
        if declared is not None:
            found[str(prefix)] = viewset
    return found


def source_viewset(name: str) -> type[BaseViewSet]:
    """Experimental. The viewset of the source ``name``, or ``ChartError`` (``CHART001``)."""
    found = sources()
    if name not in found:
        known = ", ".join(sorted(found)) or "none: no routed resource declares an aggregation"
        raise ChartError(
            f"The source {name!r} is not a routed resource with an aggregation. Sources: {known}.",
            code="CHART001",
        )
    return found[name]


def _check_filters(chart: Chart) -> None:
    defaults, allowed = chart.default_filters, chart.allowed_filters
    if not isinstance(defaults, Mapping) or not all(
        isinstance(key, str)
        and (
            isinstance(value, str | int | float | bool)
            or (
                isinstance(value, list)
                and all(isinstance(item, str | int | float | bool) for item in value)
            )
        )
        for key, value in defaults.items()
    ):
        raise ChartError(
            "default_filters must map a list filter to a value or a list of values, e.g. "
            '{"channel": "online"}.',
            code="CHART003",
        )
    if not isinstance(allowed, list) or not all(isinstance(name, str) for name in allowed):
        raise ChartError(
            'allowed_filters must list filter names, e.g. ["channel", "launched_on__gte"].',
            code="CHART003",
        )
    reserved = sorted((set(defaults) | set(allowed)) & set(PARAMETERS))
    if reserved:
        raise ChartError(
            f"{', '.join(reserved)} cannot be a filter: the chart's axes set the aggregate's "
            f"own parameters ({', '.join(PARAMETERS)}).",
            code="CHART003",
        )


def check_chart(chart: Chart) -> None:
    """Experimental. Raise ``ChartError`` when the chart cannot run as defined.

    ``CHART003`` for its filters, ``CHART001`` for its source, ``CHART004``
    for axes the source's aggregation does not declare. Field visibility is not
    checked here: the source checks it for each viewer.
    """
    _check_filters(chart)
    viewset = source_viewset(chart.source)
    view = viewset()
    declaration = view.get_aggregation()
    if declaration is None:  # pragma: no cover - sources() only lists declared ones
        raise ChartError(f"{chart.source} declares no aggregation.", code="CHART001")
    try:
        parse_query(declaration, view.get_model(), chart.query(), check_visibility=False)
    except AggregationError as exc:
        raise ChartError(
            f"The axes do not fit {chart.source}'s aggregation: {exc.code}: {exc.message}",
            code="CHART004",
        ) from None


def chart_filters(chart: Chart, params: Mapping[str, Any]) -> dict[str, list[str]]:
    """Experimental. The chart's ``default_filters`` with the viewer's allowed filters on top.

    ``params`` are the viewer's query parameters (a ``QueryDict`` keeps every
    value of a repeated one). A parameter ``allowed_filters`` does not name
    raises ``ChartError`` (``CHART002``).
    """
    merged: dict[str, list[str]] = {}
    for name, value in (chart.default_filters or {}).items():
        values = value if isinstance(value, list) else [value]
        merged[str(name)] = [_text(item) for item in values]
    allowed = set(chart.allowed_filters or [])
    refused = sorted(name for name in params if name not in allowed and name not in _IGNORED)
    if refused:
        shown = ", ".join(sorted(allowed)) or "none"
        raise ChartError(
            f"The chart {chart.slug!r} does not allow the filter(s) {', '.join(refused)}. "
            f"It allows: {shown}.",
            code="CHART002",
        )
    for name in params:
        if name in _IGNORED:
            continue
        getter = getattr(params, "getlist", None)
        values = getter(name) if callable(getter) else [params[name]]
        merged[str(name)] = [_text(item) for item in values]
    return merged


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def run_chart(chart: Chart, request: Any, filters: Mapping[str, list[str]]) -> Any:
    """Experimental. The source's aggregate for ``chart``, called as ``request``'s user.

    ``request`` is a DRF ``Request`` or a Django ``HttpRequest`` (the admin's
    preview). Returns the source's DRF ``Response``: its ``data`` is the
    aggregate on a 200, the source's refusal (with its code) otherwise.
    """
    viewset = source_viewset(chart.source)
    original = getattr(request, "_request", request)
    copied = copy.copy(original)
    query = QueryDict(mutable=True)
    for name, values in filters.items():
        query.setlist(name, list(values))
    for name, value in chart.query().items():
        query[name] = value
    copied.GET = query
    copied.method = "GET"
    # Authenticated as the viewer already is, whatever the API's auth mode.
    copied._force_auth_user = getattr(request, "user", None)
    return viewset.as_view({"get": "aggregate"})(copied)
