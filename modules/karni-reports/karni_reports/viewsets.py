"""The reports API, auto-registered at ``/api/reports/``.

* ``POST /api/reports/<report>/<id>/`` requests the report of one row. A file
  ready at the current cache key answers 200 with its download path at once.
  Otherwise a render is queued and the answer is 202 with status
  ``pending``.
* ``GET /api/reports/<report>/<id>/status/`` is the status of the last
  request for that report and row (``none`` before the first).
* ``GET /api/reports/<report>/<id>/download/`` is the PDF, once ready.

Each one first retrieves the row through its model's own viewset
(:mod:`karni_reports.access`): the caller gets what that viewset's
``retrieve`` would answer, 401 or 403 from its gate and 404 for a row out of
their scope, so another user's row is a 404. The download makes the same
check itself: the file is streamed through the API, never handed out as a
public media URL, so a download link alone opens nothing. The three are
throttled per caller
(``reports.request_report``, ``reports.report_status`` and
``reports.download_report``).

``GET /api/reports/`` lists the generated reports for roles granted
``karni_reports.generatedreport:view`` (the admin shows the same).

Override / escape hatch: set each rate under its scope in
``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``, subclass the viewset and set
``auto_register = False`` on this one, or replace the access check of one
report with ``Report.get_object``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from karni.api import BaseViewSet, Granted, Public, Throttle
from karni.exceptions import KarniLookupError
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from karni_reports import services
from karni_reports.api import ReportStatusSerializer, not_requested
from karni_reports.models import GeneratedReport
from karni_reports.registry import get_report
from karni_reports.report import Report

__all__ = ["GeneratedReportViewSet"]

_ROW = r"(?P<report>[a-z0-9][a-z0-9_-]*)/(?P<object_id>[^/.]+)"
_PARAMETERS = [
    OpenApiParameter("report", OpenApiTypes.STR, OpenApiParameter.PATH, description="report name"),
    OpenApiParameter(
        "object_id", OpenApiTypes.STR, OpenApiParameter.PATH, description="the row's id"
    ),
]


class GeneratedReportViewSet(BaseViewSet):
    """Experimental. Request, follow and download the PDF report of one row."""

    model = GeneratedReport
    route = "reports"
    access = Granted()
    serializer_class = ReportStatusSerializer
    filterset_fields: ClassVar[list[str]] = ["report", "status"]
    throttle = Throttle(request_report="60/hour", report_status="60/min", download_report="60/hour")
    #: The request runs the report's get_context, whose queries are the project's.
    unbudgeted_actions = BaseViewSet.unbudgeted_actions | {"request_report"}
    #: The routes besides list and retrieve: the three report endpoints only.
    report_actions: ClassVar[tuple[str, ...]] = (
        "request_report",
        "report_status",
        "download_report",
    )

    @classmethod
    def get_extra_actions(cls) -> list[Any]:
        return [
            extra for extra in super().get_extra_actions() if extra.__name__ in cls.report_actions
        ]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed("POST", detail="Request a report with POST /reports/<report>/<id>/.")

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed(request.method or "PUT", detail="Generated reports are not edited.")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raise MethodNotAllowed("DELETE", detail="Generated reports are pruned by the module.")

    def _report_and_row(self, request: Request, report: str, object_id: str) -> tuple[Report, Any]:
        try:
            found = get_report(report)
        except KarniLookupError as exc:
            raise NotFound(str(exc), code="REPORT001") from exc
        return found, found.get_object(request, object_id)

    def _answer(self, row: GeneratedReport, status: int = 200) -> Response:
        return Response(
            ReportStatusSerializer(row, context=self.get_serializer_context()).data, status=status
        )

    @extend_schema(
        parameters=_PARAMETERS,
        request=None,
        responses={200: ReportStatusSerializer, 202: ReportStatusSerializer},
    )
    @action(
        detail=False, methods=["post"], url_path=_ROW, url_name="request-report", access=Public()
    )
    def request_report(
        self, request: Request, report: str = "", object_id: str = "", **kwargs: Any
    ) -> Response:
        """Request the report of one row: 200 with the download path when ready, else 202."""
        found, obj = self._report_and_row(request, report, object_id)
        row = services.request(found, obj)
        return self._answer(row, 200 if row.is_ready else 202)

    @extend_schema(parameters=_PARAMETERS, responses=ReportStatusSerializer)
    @action(
        detail=False,
        methods=["get"],
        url_path=f"{_ROW}/status",
        url_name="report-status",
        access=Public(),
    )
    def report_status(
        self, request: Request, report: str = "", object_id: str = "", **kwargs: Any
    ) -> Response:
        """The status of the last request for this report and row (``none`` before one)."""
        found, obj = self._report_and_row(request, report, object_id)
        row = services.latest(found, obj.pk)
        if row is None:
            return Response(not_requested(found.name, str(obj.pk)))
        return self._answer(row)

    @extend_schema(
        parameters=_PARAMETERS,
        responses={(200, "application/pdf"): OpenApiResponse(OpenApiTypes.BINARY)},
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=f"{_ROW}/download",
        url_name="download-report",
        access=Public(),
    )
    def download_report(
        self, request: Request, report: str = "", object_id: str = "", **kwargs: Any
    ) -> Any:
        """The PDF of the last request for this report and row, once it is ready."""
        found, obj = self._report_and_row(request, report, object_id)
        row = services.latest(found, obj.pk)
        if row is None or not row.is_ready:
            raise NotFound(
                "REPORT008: no file is ready for this report and row. Request it with POST and "
                "wait until its status/ says ready.",
                code="REPORT008",
            )
        try:
            handle = row.file.open("rb")
        except OSError as exc:  # the file left the storage: render it again on the next request
            row.status, row.error = GeneratedReport.Status.FAILED, f"file missing: {exc}"
            row.save(update_fields=["status", "error", "updated_at"])
            raise NotFound(
                "REPORT008: the file is gone. Request it again.", code="REPORT008"
            ) from exc
        return FileResponse(
            handle,
            as_attachment=True,
            filename=found.get_filename(obj),
            content_type=found.get_renderer().content_type,
        )
