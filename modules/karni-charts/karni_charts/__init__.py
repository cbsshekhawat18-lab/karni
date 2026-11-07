"""karni-charts: saved charts, defined in the admin and drawn from a resource's aggregate.

A :class:`~karni_charts.models.Chart` names a source resource (any routed
viewset whose model declares ``class Karni: aggregate``), its x axis (a
group), its y axis (a metric and a value), an optional z axis (a second
group, stacked or as series), the filters it always applies and the ones a
viewer may add. ``GET /api/charts/<slug>/data/`` returns the definition and
the data, fetched through the source's own ``aggregate`` action as the
requesting user, so the access is the source's (:mod:`karni_charts.services`).
``@karni/charts-ui``'s ``SavedChart`` draws it.

Experimental, like the aggregations it builds on (docs/charts.md).
"""

from __future__ import annotations

from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("karni-charts")  # [project] version in pyproject.toml
except _metadata.PackageNotFoundError:  # a source tree on sys.path, never installed
    __version__ = "0+unknown"
