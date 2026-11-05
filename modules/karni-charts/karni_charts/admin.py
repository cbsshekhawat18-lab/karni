"""Saved charts in the admin, with a preview (an explicit registration, see the README).

The change form offers the sources (the routed resources whose model declares
an aggregation) as a choice, checks the axes against the source's declaration
when it saves (``Chart.clean``), and shows a preview under the fields: the
chart's data as a table, fetched through the source's aggregate action as the
signed-in staff user, so the preview shows what that user may see.

Override / escape hatch: unregister ``Chart`` and register your own subclass
of :class:`ChartAdmin` (``admin.site.unregister(Chart)``).
"""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest
from karni.admin import KarniModelAdmin

from karni_charts.models import BUCKET_CHOICES, Chart
from karni_charts.services import ChartError, chart_filters, run_chart, sources

__all__ = ["ChartAdmin", "ChartForm", "preview"]


class ChartForm(forms.ModelForm):
    """The chart form: ``source`` is a choice of the resources a chart may read."""

    class Meta:
        model = Chart
        fields = "__all__"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        names = sorted(sources())
        current = getattr(self.instance, "source", "")
        if current and current not in names:
            names.append(current)  # keep a source that went away visible, clean() says why
        self.fields["source"] = forms.ChoiceField(
            choices=[(name, name) for name in names],
            help_text=Chart._meta.get_field("source").help_text,
        )
        for name in ("x_bucket", "z_bucket"):
            self.fields[name] = forms.ChoiceField(
                choices=BUCKET_CHOICES,
                required=False,
                help_text=Chart._meta.get_field(name).help_text,
            )


def preview(chart: Chart, request: HttpRequest) -> dict[str, Any]:
    """Experimental. What the change form shows: rows and series, or ``{"error": ...}``."""
    try:
        answer = run_chart(chart, request, chart_filters(chart, {}))
    except ChartError as exc:
        return {"error": f"{exc.code}: {exc.message}"}
    data = answer.data if isinstance(answer.data, dict) else {}
    if answer.status_code != 200:
        return {"error": f"{data.get('code') or answer.status_code}: {data.get('detail', '')}"}
    series = [entry["label"] for entry in data.get("series", [])]
    rows = []
    for index, category in enumerate(data.get("categories", [])):
        values = [entry["values"][index] for entry in data.get("series", [])]
        rows.append({"label": category["label"], "values": values})
    return {"series": series, "rows": rows, "header": chart.x_label or chart.x_field}


@admin.register(Chart)
class ChartAdmin(KarniModelAdmin):
    """Experimental. Saved charts: the definition in groups, and a preview of its data."""

    form = ChartForm
    change_form_template = "karni_charts/admin/chart_change_form.html"
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "kind", "position")}),
        (
            "Source and axes",
            {
                "fields": (
                    "source",
                    "x_field",
                    "x_bucket",
                    "x_label",
                    "y_metric",
                    "y_value",
                    "y_label",
                    "z_field",
                    "z_bucket",
                    "z_mode",
                    "top",
                )
            },
        ),
        ("Filters", {"fields": ("default_filters", "allowed_filters")}),
    )

    def render_change_form(
        self,
        request: HttpRequest,
        context: dict[str, Any],
        add: bool = False,
        change: bool = False,
        form_url: str = "",
        obj: Any = None,
    ) -> Any:
        if obj is not None and obj.pk is not None:
            context["chart_preview"] = preview(obj, request)
        return super().render_change_form(request, context, add, change, form_url, obj)
