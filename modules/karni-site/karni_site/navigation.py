"""Which page is the current one: what ``{% ifactive %}`` asks for each pattern.

A pattern is either a URL name or a path:

* ``"website:about"``: the current request resolved to that URL name. Shell
  wildcards match several, ``"website:service_*"``.
* ``"/about/"``: the current path is exactly that. ``"/services/*"`` matches
  every path under ``/services/``.

Override / escape hatch: point ``KARNI_SITE_IS_ACTIVE`` at another
``(request, pattern) -> bool`` function.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from fnmatch import fnmatchcase
from typing import Any

from django.utils.module_loading import import_string

from karni_site import conf

__all__ = ["any_active", "is_active", "matcher"]


def is_active(request: Any, pattern: str) -> bool:
    """``True`` when ``pattern`` (a URL name or a path, wildcards allowed) is this page."""
    pattern = str(pattern).strip()
    if not pattern:
        return False
    if pattern.startswith("/"):
        path = str(getattr(request, "path", "") or "")
        return fnmatchcase(path, pattern)
    match = getattr(request, "resolver_match", None)
    view_name = getattr(match, "view_name", None)
    return bool(view_name) and fnmatchcase(str(view_name), pattern)


def matcher() -> Callable[[Any, str], bool]:
    """The function ``KARNI_SITE_IS_ACTIVE`` names."""
    configured = conf.get("KARNI_SITE_IS_ACTIVE")
    found: Callable[[Any, str], bool] = (
        configured if callable(configured) else import_string(str(configured))
    )
    return found


def any_active(request: Any, patterns: Iterable[str]) -> bool:
    """``True`` when one of ``patterns`` names the current page. No request: ``False``."""
    if request is None:
        return False
    test = matcher()
    return any(test(request, pattern) for pattern in patterns)
