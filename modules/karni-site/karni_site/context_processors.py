"""``site`` in every template: the site's settings (``karni_site.context_processors.site``).

``{{ site.name }}``, ``{{ site.phone }}``, ``{{ site.phone_href }}``,
``{{ site.email }}``, ``{% for row in site.hours %}``, ``site.social.instagram.url``,
``{{ site.logo.url }}``. The row is read lazily, from the cache, once per
render.

``karni make site`` (and ``karni add site``) add it to the template
engine's context processors. ``karni check`` reports it missing
(``SITE004``).

Override / escape hatch: ``KARNI_SITE_SETTINGS_MODEL``, or a context
processor of your own that sets ``site``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.utils.functional import SimpleLazyObject

from karni_site.sitesettings import get_site_settings

__all__ = ["SiteProxy", "site"]


class SiteProxy(SimpleLazyObject):
    """The settings row, read on first use. ``{% site_defaults %}`` swaps in a fresh one."""

    def replace(self, row: Any) -> None:
        self._wrapped = row


def site(request: HttpRequest) -> dict[str, Any]:
    return {"site": SiteProxy(get_site_settings)}
