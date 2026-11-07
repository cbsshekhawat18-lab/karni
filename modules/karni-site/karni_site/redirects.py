"""Redirects a client manages in the admin: lookup, the response, and loop refusal.

A redirect matches the request's path. One whose old address has a query
string matches only that exact query and is tried first. Without one, any
query the request has is passed on to the new address. Each address looked
up is cached, found or not, so a lookup is one cache read. Saving a
redirect makes every cached answer stale.

A redirect that would send a visitor in a circle (``/a/`` to ``/b/`` and
back, or to itself) is refused when it is saved (``SITE006``), and so is one
from the admin's, the API's or the static files' own addresses.

Override / escape hatch: ``KARNI_SITE_REDIRECTS_BEFORE_VIEWS`` (see
:mod:`karni_site.middleware`), or call :func:`redirect_for` from your own
middleware or view.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpResponseBase, HttpResponsePermanentRedirect, HttpResponseRedirect
from django.utils.translation import gettext as _

from karni_site import caching

__all__ = ["lookup", "normalize_path", "redirect_for", "validate_redirect"]

logger = logging.getLogger("karni_site")
LOOP_CODE = "SITE006"
_MAX_HOPS = 50


def normalize_path(value: str, *, keep_query: bool = True) -> str:
    """``value`` as a path from the first slash: a full URL's host and any fragment dropped."""
    value = (value or "").strip()
    parts = urlsplit(value)
    path = parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    query = parts.query if keep_query else ""
    return path + ("?" + query if query else "")


def _local_path(url: str) -> str | None:
    """The path ``url`` reaches on this site, or ``None`` for another site."""
    parts = urlsplit(url.strip())
    if parts.scheme or parts.netloc:
        hosts = [host for host in getattr(settings, "ALLOWED_HOSTS", []) if host not in ("*", "")]
        host = (parts.hostname or "").lower()
        if not any(
            host == h.lstrip(".") or (h.startswith(".") and host.endswith(h)) for h in hosts
        ):
            return None
    if not parts.path and not parts.netloc:
        return None  # "#section" or "?query": the same page
    return normalize_path(parts.path or "/", keep_query=False)


def _protected_prefixes() -> list[str]:
    prefixes = ["/api/"]
    admin_path = str(getattr(settings, "KARNI_ADMIN_PATH", "") or "")
    if admin_path:
        prefixes.append("/" + admin_path.strip("/") + "/")
    for name in ("STATIC_URL", "MEDIA_URL"):
        value = str(getattr(settings, name, "") or "")
        if value.startswith("/") and value != "/":
            prefixes.append(value)
        elif value and "://" not in value:
            prefixes.append("/" + value.lstrip("/"))
    return prefixes


def validate_redirect(redirect: Any) -> None:
    """Refuse a redirect from a protected address, to an unsafe one, or in a circle."""
    from karni_site.models import Redirect
    from karni_site.sanitize import safe_url

    old = normalize_path(redirect.old_path)
    for prefix in _protected_prefixes():
        if old.startswith(prefix):
            raise ValidationError(
                _("%(path)s belongs to the site's own machinery and cannot be redirected.")
                % {"path": prefix},
                code="protected",
            )
    new = (redirect.new_url or "").strip()
    if not new or not safe_url(new):
        raise ValidationError(_("Write the new address as /path/ or https://..."), code="invalid")
    start = old.split("?", 1)[0]
    seen = [start]
    current = _local_path(new)
    others = Redirect.objects.exclude(pk=redirect.pk) if redirect.pk else Redirect.objects.all()
    while current is not None and len(seen) <= _MAX_HOPS:
        if current in seen:
            chain = " -> ".join([*seen, current])
            raise ValidationError(
                _("This redirect would send visitors in a circle: %(chain)s. (%(code)s)")
                % {"chain": chain, "code": LOOP_CODE},
                code=LOOP_CODE,
            )
        seen.append(current)
        following = others.filter(old_path=current).values_list("new_url", flat=True).first()
        if following is None:
            return
        current = _local_path(following)


def lookup(path: str, query: str = "") -> tuple[str, int, bool] | None:
    """``(new address, status, exact)`` for a request to ``path?query``, or ``None``."""
    from karni_site.models import Redirect

    store = caching.cache()
    version = str(caching.version("redirects"))
    candidates = ([(f"{path}?{query}", True)] if query else []) + [(path, False)]
    for candidate, exact in candidates:
        key = caching.key("redirect", version, candidate)
        found = store.get(key)
        if found is None:
            row = Redirect.objects.filter(old_path=candidate).values_list("new_url", "status")
            found = row.first() or ""
            store.set(key, found, caching.timeout())
        if found:
            return str(found[0]), int(found[1]), exact
    return None


def _with_query(url: str, query: str) -> str:
    base, hash_sep, fragment = url.partition("#")
    joiner = "&" if "?" in base else "?"
    return f"{base}{joiner}{query}{hash_sep}{fragment}"


def redirect_for(request: Any) -> HttpResponseBase | None:
    """The redirect response for ``request``, or ``None`` when no redirect matches."""
    query = request.META.get("QUERY_STRING", "")
    try:
        found = lookup(request.path, query)
    except DatabaseError:
        logger.exception("karni_site: redirects could not be read")
        return None
    if found is None:
        return None
    url, status, exact = found
    if query and not exact:
        url = _with_query(url, query)
    if url == request.get_full_path():
        return None  # never answer a page with a redirect to itself
    if status == 301:
        return HttpResponsePermanentRedirect(url)
    return HttpResponseRedirect(url)
