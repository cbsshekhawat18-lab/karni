"""Settings vocabulary for karni-charts.

:data:`DEFAULTS` is the module's settings fragment, exposed through the
``karni.settings`` entry point, so :func:`karni.conf.karni_settings` merges
it into every project that installs the module. It is import-light: plain
data and django-environ reads, never ``django.conf.settings`` at import
time. :func:`get` is the accessor every ``karni_charts`` module reads
settings through, so the module also works without ``karni_settings()``.

Override / escape hatch: define any of these names in your ``settings.py``
or set the matching environment variable.
"""

from __future__ import annotations

from typing import Any

import environ
from django.conf import settings

env = environ.Env()

#: The values ``KARNI_CHARTS_READ`` takes.
READERS = ("authenticated", "public", "granted")

DEFAULTS: dict[str, Any] = {
    # Who may read the chart definitions (/api/charts/): "authenticated" (the
    # default), "public" (anyone, for charts on a public page) or "granted"
    # (the roles' grants on karni_charts.chart). The data always follows the
    # source resource's own access, whoever reads the definition.
    "KARNI_CHARTS_READ": env("KARNI_CHARTS_READ", default="authenticated"),
}
"""The karni-charts settings fragment (``karni.settings`` entry point)."""


def get(name: str) -> Any:
    """The effective value of a karni-charts setting: the project's, else :data:`DEFAULTS`.

    :raises KeyError: when ``name`` is not a karni-charts setting and the
        project does not define it either.
    """
    return getattr(settings, name, DEFAULTS[name])
