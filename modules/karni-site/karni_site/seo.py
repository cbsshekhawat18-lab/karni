"""Per-page SEO entries: the lookup ``{% karni_seo %}`` calls.

:func:`page_seo` answers "is there an entry for this page": the entry for
the request's exact path first, then the one for its URL name (which covers
every page of that view). Each answer, found or not, is cached; saving an
entry makes every cached answer stale. The tag that renders the title,
description, share image and robots line reads this, then the object in the
template's context, then the site's settings.

Override / escape hatch: call :func:`lookup` with any path or URL name.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import DatabaseError

from karni_site import caching

__all__ = ["lookup", "page_seo"]

logger = logging.getLogger("karni_site")


def lookup(path: str | None = None, route: str | None = None) -> Any | None:
    """The :class:`~karni_site.models.PageSeo` for ``path``, else for ``route``, or ``None``."""
    from karni_site.models import PageSeo

    store = caching.cache()
    version = str(caching.version("seo"))
    for field, value in (("path", path), ("route", route)):
        if not value:
            continue
        key = caching.key("seo", version, field, value)
        found = store.get(key)
        if found is None:
            found = PageSeo.objects.filter(**{field: value}).first() or ""
            store.set(key, found, caching.timeout())
        if found:
            return found
    return None


def page_seo(request: Any) -> Any | None:
    """The entry for the page ``request`` asks for, or ``None``. Never raises for the database."""
    if request is None:
        return None
    match = getattr(request, "resolver_match", None)
    try:
        return lookup(path=getattr(request, "path", None), route=getattr(match, "view_name", None))
    except DatabaseError:
        logger.exception("karni_site: page SEO entries could not be read")
        return None
