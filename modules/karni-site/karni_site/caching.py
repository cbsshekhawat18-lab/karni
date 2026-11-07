"""The cache every karni_site lookup reads: one alias, one timeout, versioned keys.

Blocks, menus, redirects, page SEO entries and the site's settings are read
on every page, so each is cached and every save clears exactly what it
changed (the receivers in :mod:`karni_site.signals`). A key group that a
save cannot name precisely (every menu, every redirect) carries a version
number, and the save bumps the version.

Override / escape hatch: ``KARNI_SITE_CACHE`` (the alias) and
``KARNI_SITE_CACHE_TIMEOUT`` (seconds, ``None`` for no expiry).
"""

from __future__ import annotations

import hashlib
from typing import Any

from django.core.cache import BaseCache, caches

from karni_site import conf

__all__ = ["bump", "cache", "key", "timeout", "version"]

PREFIX = "karni_site"


def cache() -> BaseCache:
    return caches[str(conf.get("KARNI_SITE_CACHE"))]


def timeout() -> Any:
    return conf.get("KARNI_SITE_CACHE_TIMEOUT")


def key(*parts: str) -> str:
    """A cache key for ``parts``. Long or unusual parts are hashed, so any path fits."""
    joined = ":".join(parts)
    if len(joined) > 120 or any(ord(char) < 33 or ord(char) > 126 for char in joined):
        joined = parts[0] + ":" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:40]
    return f"{PREFIX}:{joined}"


def version(group: str) -> int:
    """The current version of a key group (0 until the first bump)."""
    found = cache().get(key("version", group))
    return int(found) if found is not None else 0


def bump(group: str) -> None:
    """Make every key of ``group`` stale."""
    store = cache()
    name = key("version", group)
    try:
        store.incr(name)
    except ValueError:
        store.set(name, 1, None)
