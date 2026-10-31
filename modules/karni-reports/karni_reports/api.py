"""The answer of the report endpoints: a report's status for one row."""

from __future__ import annotations

from typing import Any

from django.urls import NoReverseMatch, reverse
from rest_framework import serializers

from karni_reports.models import GeneratedReport

__all__ = ["DOWNLOAD_URL_NAME", "ReportStatusSerializer", "download_path"]

#: The URL name of the download: the router's basename plus the action's url_name.
DOWNLOAD_URL_NAME = "karni_reports-generated-report-download-report"


def download_path(report: str, object_id: str) -> str | None:
    """The path of the download endpoint for one report of one row."""
    try:
        return reverse(DOWNLOAD_URL_NAME, kwargs={"report": report, "object_id": object_id})
    except NoReverseMatch:  # the API is not routed (a project without karni.api.urls)
        return None


class ReportStatusSerializer(serializers.ModelSerializer[GeneratedReport]):
    """Experimental. One generated report: its status and, once ready, its download path.

    ``status`` is ``pending``, ``rendering``, ``ready`` or ``failed``.
    ``url`` is set only while the file is ready. ``error`` never carries the
    exception: staff read it in the admin.
    """

    url = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()

    class Meta:
        model = GeneratedReport
        fields = [
            "id",
            "report",
            "object_id",
            "status",
            "url",
            "size",
            "data_version",
            "error",
            "requested_at",
            "rendered_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_url(self, obj: GeneratedReport) -> str | None:
        if not obj.is_ready:
            return None
        return download_path(obj.report, obj.object_id)

    def get_error(self, obj: GeneratedReport) -> str:
        if obj.status != GeneratedReport.Status.FAILED:
            return ""
        return "REPORT007: the report could not be rendered. Staff can read why in the admin."


def not_requested(report: str, object_id: str) -> dict[str, Any]:
    """The status of a report never requested for this row."""
    return {
        "id": None,
        "report": report,
        "object_id": object_id,
        "status": "none",
        "url": None,
        "size": 0,
        "data_version": "",
        "error": "",
        "requested_at": None,
        "rendered_at": None,
        "created_at": None,
    }
