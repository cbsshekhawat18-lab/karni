"""``/robots.txt``, ``/sitemap.xml`` and the sitemap's sections: karni_site's URLs.

``karni make site`` and ``karni add site`` include them in config/urls.py::

    path("", include("karni_site.urls")),

robots.txt lets search engines in only where :func:`indexing_allowed` says
so: in production (``DJANGO_ENV=prod``) unless ``KARNI_SITE_ALLOW_INDEXING``
decides otherwise. Elsewhere it asks every crawler to stay out, so a
development or staging copy never shows up in search results. While
indexing is allowed it names the sitemap and the paths of
``KARNI_SITE_ROBOTS_DISALLOW``. It renders ``karni_site/robots.txt``.

sitemap.xml lists the sections ``KARNI_SITE_SITEMAPS`` returns
(:mod:`karni_site.sitemaps`). When one has more addresses than a sitemap
may hold (50,000), sitemap.xml becomes an index of
``/sitemap-<section>.xml?p=<page>``.

Override / escape hatch: the settings above, a ``karni_site/robots.txt``
template of the project's own (its context: ``allowed``, ``disallow``,
``sitemap_url``), or routes of your own for these paths placed before the
include.
"""

from __future__ import annotations

import os
from typing import Any

from django.contrib.sitemaps import views as sitemap_views
from django.http import Http404, HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.module_loading import import_string

from karni_site import conf
from karni_site.metadata import absolute

__all__ = ["indexing_allowed", "robots", "sections", "sitemap", "sitemap_section"]


def indexing_allowed() -> bool:
    """``KARNI_SITE_ALLOW_INDEXING``, else whether ``DJANGO_ENV`` is ``prod``."""
    value = conf.get("KARNI_SITE_ALLOW_INDEXING")
    if value is None:
        return os.environ.get("DJANGO_ENV", "dev").strip().lower() == "prod"
    return bool(value)


def robots(request: HttpRequest) -> HttpResponse:
    """robots.txt: everything closed outside production, else the sitemap and the exceptions."""
    allowed = indexing_allowed()
    context = {
        "allowed": allowed,
        "disallow": [str(p) for p in conf.get("KARNI_SITE_ROBOTS_DISALLOW") or ()],
        "sitemap_url": absolute(reverse("karni_site:sitemap"), request),
    }
    return TemplateResponse(
        request, "karni_site/robots.txt", context, content_type="text/plain; charset=utf-8"
    )


def sections() -> dict[str, Any]:
    """The sitemap's sections: ``KARNI_SITE_SITEMAPS`` called."""
    return dict(import_string(str(conf.get("KARNI_SITE_SITEMAPS")))())


def sitemap(request: HttpRequest) -> HttpResponse:
    """sitemap.xml: every address in one file, or an index when a section needs pages."""
    found = sections()
    if all(section.paginator.num_pages <= 1 for section in found.values()):
        response: HttpResponse = sitemap_views.sitemap(
            request, found, template_name="karni_site/sitemap.xml"
        )
        return response
    entries: list[str] = []
    for name, section in found.items():
        address = absolute(reverse("karni_site:sitemap_section", kwargs={"section": name}), request)
        entries.append(address)
        entries.extend(f"{address}?p={page}" for page in range(2, section.paginator.num_pages + 1))
    return TemplateResponse(
        request,
        "karni_site/sitemap_index.xml",
        {"sitemaps": entries},
        content_type="application/xml",
    )


def sitemap_section(request: HttpRequest, section: str) -> HttpResponse:
    """One section of a sitemap index: ``/sitemap-<section>.xml?p=<page>``."""
    found = sections()
    if section not in found:
        raise Http404(f"No sitemap section {section!r}.")
    response: HttpResponse = sitemap_views.sitemap(
        request, found, section=section, template_name="karni_site/sitemap.xml"
    )
    return response
