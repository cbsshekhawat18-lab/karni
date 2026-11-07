"""Settings vocabulary for karni-reports.

:data:`DEFAULTS` is the module's **settings fragment**: it is exposed through
the ``karni.settings`` entry point (see this module's ``pyproject.toml``), so
:func:`karni.conf.karni_settings` merges it into every project's settings
after Karni's BASE and profile defaults and before project overrides, new
top-level names only.

The fragment is import-light on purpose: plain data plus django-environ
reads, and it never touches ``django.conf.settings`` at import time.

:func:`get` is the accessor every ``karni_reports`` module reads settings
through, ``getattr(settings, name, DEFAULTS[name])``, so the module also
works in projects that configure Django without ``karni_settings()``.

Override / escape hatch: define any of these names in your ``settings.py`` or
set the matching environment variable.
"""

from __future__ import annotations

from typing import Any

import environ
from django.conf import settings

env = environ.Env()

DEFAULTS: dict[str, Any] = {
    # Turns HTML into PDF: "weasyprint", "fake" (deterministic bytes, no system
    # libraries: for tests) or the dotted path of a karni_reports.rendering.Renderer
    # subclass.
    "KARNI_REPORTS_RENDERER": env("KARNI_REPORTS_RENDERER", default="weasyprint"),
    # The STORAGES alias the files are saved to.
    "KARNI_REPORTS_STORAGE": env("KARNI_REPORTS_STORAGE", default="default"),
    # The folder inside that storage. Each report gets a folder of its own under it.
    "KARNI_REPORTS_DIRECTORY": env("KARNI_REPORTS_DIRECTORY", default="karni/reports"),
    # The CSS page size the base template prints on: "A4", "letter", "A5 landscape"...
    "KARNI_REPORTS_PAGE_SIZE": env("KARNI_REPORTS_PAGE_SIZE", default="A4"),
    # Ready files kept per report and row, the newest first. Older files and their
    # rows are deleted after each render. 0 keeps every file.
    "KARNI_REPORTS_KEEP": env.int("KARNI_REPORTS_KEEP", default=1),
    # Seconds after which a report still pending or rendering is queued again
    # by the next request (a worker that died mid-render).
    "KARNI_REPORTS_RENDER_TIMEOUT": env.int("KARNI_REPORTS_RENDER_TIMEOUT", default=600),
}
"""The karni-reports settings fragment (``karni.settings`` entry point)."""


def get(name: str) -> Any:
    """Return the effective value of a karni-reports setting.

    Project settings win; :data:`DEFAULTS` is the fallback.

    :raises KeyError: when ``name`` is not a karni-reports setting and the
        project has not defined it either.
    """
    return getattr(settings, name, DEFAULTS[name])
