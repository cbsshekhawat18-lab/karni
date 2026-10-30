"""The saved chart: a source resource, its axes and its filters (experimental).

A chart's data is never stored. It is the source's aggregate
(``GET <source>/aggregate/``) for the axes below, fetched as the person who
views the chart (:mod:`karni_charts.services`).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from karni.aggregation import BUCKETS, METRICS
from karni.models import BaseModel

__all__ = ["BUCKET_CHOICES", "Chart"]

#: The date buckets an axis takes, as the admin offers them (the model keeps plain text,
#: checked by ``clean``, so the API documents one string and no enum per axis).
BUCKET_CHOICES = [("", "None"), *((bucket, bucket.capitalize()) for bucket in BUCKETS)]
_METRIC_LABELS = {
    "count": "Count",
    "sum": "Sum",
    "avg": "Average",
    "min": "Minimum",
    "max": "Maximum",
    "distinct_count": "Distinct count",
}


class Chart(BaseModel):
    """Experimental. A chart people edit in the admin and the app draws with ``SavedChart``.

    The x axis is ``x_field`` (a group of the source's aggregation) with an
    optional date bucket. The y axis is ``y_metric`` over ``y_value``. The z
    axis, optional, is a second group, stacked or as series. ``top`` keeps the
    largest x groups and puts the rest in "Other". ``default_filters`` always
    apply, and a viewer may add the list filters ``allowed_filters`` names.

    Override / escape hatch: :meth:`query` builds the source's query string,
    and :mod:`karni_charts.services` runs it.
    """

    class Kind(models.TextChoices):
        BAR = "bar", "Bar"
        LINE = "line", "Line"

    class Mode(models.TextChoices):
        STACK = "stack", "Stacked"
        SERIES = "series", "Separate series"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(blank=True, default="")
    source = models.CharField(
        max_length=100,
        help_text="The resource the chart reads, e.g. products: a routed resource whose model "
        "declares class Karni: aggregate.",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.BAR)
    x_field = models.CharField(
        max_length=200, help_text="What the x axis groups by: a group the source declares."
    )
    x_bucket = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="For a date: one bar or point per year, quarter or month (empty: none).",
    )
    x_label = models.CharField(max_length=100, blank=True, default="")
    y_metric = models.CharField(
        max_length=20,
        choices=[(metric, _METRIC_LABELS[metric]) for metric in METRICS],
        default="count",
    )
    y_value = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="The value the metric reads (not needed for a count).",
    )
    y_label = models.CharField(max_length=100, blank=True, default="")
    z_field = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="A second group, optional: one bar segment or one line per value.",
    )
    z_bucket = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="For a date: year, quarter or month (empty: none).",
    )
    z_mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.STACK)
    top = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Keep the N largest groups of the x axis and put the rest in Other.",
    )
    default_filters = models.JSONField(
        default=dict,
        blank=True,
        help_text='List filters the chart always applies, e.g. {"channel": "online"}.',
    )
    allowed_filters = models.JSONField(
        default=list,
        blank=True,
        help_text='List filters a viewer may add, e.g. ["channel", "launched_on__gte"].',
    )
    position = models.IntegerField(default=0, help_text="Charts are listed by position, then name.")

    class Meta(BaseModel.Meta):
        ordering = ["position", "name"]

    class Karni:
        natural_key = "slug"

    class AdminMeta:
        list_display = ["name", "source", "kind", "x_field", "y_metric", "position"]
        search_fields = ["name", "slug", "source"]

    def __str__(self) -> str:
        return self.name

    def query(self) -> dict[str, str]:
        """Experimental. The source's aggregate parameters for this chart's axes."""
        found = {
            "group_by": f"{self.x_field}:{self.x_bucket}" if self.x_bucket else self.x_field,
            "metric": self.y_metric,
        }
        if self.y_value:
            found["value"] = self.y_value
        if self.top:
            found["top"] = str(self.top)
        if self.z_field:
            split = f"{self.z_field}:{self.z_bucket}" if self.z_bucket else self.z_field
            found[self.z_mode] = split
        return found

    def clean(self) -> None:
        """Check the filters (``CHART003``), the source (``CHART001``), the axes (``CHART004``)."""
        from karni_charts.services import ChartError, check_chart

        super().clean()
        try:
            check_chart(self)
        except ChartError as exc:
            field = {"CHART001": "source", "CHART003": "default_filters"}.get(exc.code, "x_field")
            raise ValidationError({field: f"{exc.code}: {exc.message}"}) from None
