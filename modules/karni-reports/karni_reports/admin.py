"""Generated reports in the admin (an explicit registration, documented in the README).

The list shows each file's report, row, status, size, data version and
times, filters by status (``failed`` lists the renders that failed, with
their error) and by report, and offers **Regenerate selected**, which queues
the renders again. Rows are read only: the module writes them.

Override / escape hatch: ``admin.site.unregister(GeneratedReport)`` and
register your own ``KarniModelAdmin`` subclass of :class:`GeneratedReportAdmin`.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext_lazy as _
from karni.admin import KarniModelAdmin

from karni_reports import services
from karni_reports.models import GeneratedReport

__all__ = ["GeneratedReportAdmin"]


@admin.register(GeneratedReport)
class GeneratedReportAdmin(KarniModelAdmin):
    """Experimental. The generated files: status, size, versions, errors, a Regenerate action."""

    list_display = (
        "report",
        "row",
        "status",
        "file_size",
        "short_data_version",
        "created_at",
        "rendered_at",
        "short_error",
    )
    list_filter = ("status", "report")
    search_fields = ("report", "object_id")
    readonly_fields = (
        "report",
        "content_type",
        "object_id",
        "status",
        "file",
        "size",
        "template",
        "template_version",
        "data_version",
        "error",
        "requested_at",
        "rendered_at",
        "created_at",
    )
    fields = readonly_fields
    actions = ("regenerate_selected",)
    karni_transfer = False

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        return super().get_queryset(request).select_related("content_type")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_regenerate_permission(self, request: HttpRequest) -> bool:
        """Regenerating needs the change permission on generated reports."""
        return bool(self.has_change_permission(request))

    @admin.display(description=_("row"))
    def row(self, obj: GeneratedReport) -> str:
        return f"{obj.content_type.app_label}.{obj.content_type.model} {obj.object_id}"

    @admin.display(description=_("size"), ordering="size")
    def file_size(self, obj: GeneratedReport) -> str:
        return filesizeformat(obj.size) if obj.size else "-"

    @admin.display(description=_("data version"))
    def short_data_version(self, obj: GeneratedReport) -> str:
        return obj.data_version[:12]

    @admin.display(description=_("error"))
    def short_error(self, obj: GeneratedReport) -> str:
        return obj.error[:120]

    @admin.action(description=_("Regenerate selected reports"), permissions=["regenerate"])
    def regenerate_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        count = services.regenerate(queryset)
        self.message_user(
            request, f"{count} report(s) queued to render again.", level=messages.SUCCESS
        )
