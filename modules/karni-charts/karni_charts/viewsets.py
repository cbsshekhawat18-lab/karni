"""The charts API: definitions and their data (experimental).

``GET /api/charts/`` and ``GET /api/charts/<slug>/`` list and read the
definitions, for whoever ``KARNI_CHARTS_READ`` admits. ``GET
/api/charts/<slug>/data/`` returns ``{"chart": <definition>, "data":
<aggregate>}``: the data comes from the source resource's own aggregate
action, called as the viewer (:func:`karni_charts.services.run_chart`), so
its access is the source's. Charts are written in the admin: the API only
reads.

Override / escape hatch: ``KARNI_CHARTS_READ`` chooses who reads the
definitions, :meth:`ChartViewSet.get_access` computes it per request, and the
functions of :mod:`karni_charts.services` are what the ``data`` action calls.
"""

from __future__ import annotations

from typing import Any

from karni.api import Access, Authenticated, BaseViewSet, Granted, HasRole, Public
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from karni_charts import conf
from karni_charts.models import Chart
from karni_charts.services import ChartError, chart_filters, run_chart

__all__ = ["ChartViewSet"]

_READERS = {"authenticated": Authenticated, "public": Public}


class ChartViewSet(BaseViewSet):
    """Experimental. Read-only: the definitions, and each chart's data through its source."""

    model = Chart
    lookup_field = "slug"
    http_method_names = ["get", "head", "options"]
    access = Access(read=Authenticated(), write=HasRole("staff"))

    def get_access(self) -> Access:
        """``KARNI_CHARTS_READ``: ``authenticated`` (default), ``public`` or ``granted``."""
        reader = str(conf.get("KARNI_CHARTS_READ") or "authenticated")
        if reader == "granted":
            return Access(read=Granted(), write=Granted())
        predicate = _READERS.get(reader, Authenticated)()
        return Access(read=predicate, write=HasRole("staff"))

    @action(detail=True, methods=["get"], url_path="data")
    def data(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Experimental. The chart's definition and its data, read through the source's aggregate.

        The chart's ``default_filters`` always apply, and the viewer may add the
        list filters its ``allowed_filters`` names (any other is a 400,
        ``CHART002``). The data follows the source's access: a viewer the
        source refuses gets the source's answer.
        """
        chart = self.get_object()
        definition = self.get_serializer(chart).data
        try:
            filters = chart_filters(chart, request.query_params)
            answer = run_chart(chart, request, filters)
        except ChartError as exc:
            return Response({"code": exc.code, "detail": str(exc)}, status=400)
        if answer.status_code != 200:
            return Response(answer.data, status=answer.status_code)
        return Response({"chart": definition, "data": answer.data})
