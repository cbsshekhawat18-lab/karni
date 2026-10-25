"""Settings vocabulary for karni-site: the ``karni.settings`` entry point.

Import-light by contract: plain data plus django-environ reads, never
``django.conf.settings`` at import time. Module code reads settings through
:func:`get`, so it also works without ``karni_settings()``.

Override / escape hatch: define any of these names in the project's
settings.py.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

DEFAULTS: dict[str, Any] = {
    # The function {% ifactive %} asks whether a pattern names the current page:
    # (request, pattern) -> bool. A dotted path, so a project can swap the rule.
    "KARNI_SITE_IS_ACTIVE": "karni_site.navigation.is_active",
    # The templates karni_site.views.server_error tries in order. The first that
    # renders is the page. The last is this module's plain page, which needs nothing.
    "KARNI_SITE_SERVER_ERROR_TEMPLATES": ["500.html", "karni_site/500.html"],
    # The same for karni_site.views.page_not_found.
    "KARNI_SITE_NOT_FOUND_TEMPLATES": ["404.html", "karni_site/404.html"],
}


def get(name: str) -> Any:
    """``settings.<name>`` if the project defines it, else the module default."""
    return getattr(settings, name, DEFAULTS[name])
