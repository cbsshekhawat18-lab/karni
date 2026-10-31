"""Experimental. ``karni check`` on the menu: each route has a page, each requirement a permission.

``manage.py karni_check`` (``karni check``) runs :func:`check_navigation`
while ``KARNI_NAVIGATION`` is set:

* ``E533``: an item's route is served by no page of the frontend. The pages
  are the ``path:`` entries of the files in ``KARNI_NAVIGATION_PAGES``
  (``frontend/src/routes.tsx``, where ``karni make page`` and ``karni
  build`` register each page). A ``$param`` segment takes any value, and the
  message names the closest route.
* ``E534``: an item's requirement names no permission of the project, so
  nobody but a superuser would see it.
* ``W630``: the database menu could not be read (the database does not
  answer, or ``karni.navigation``'s migration has not run), so it was not
  compared.
* ``W631``: none of the ``KARNI_NAVIGATION_PAGES`` files exists, so the
  routes were not compared.

The settings source is always compared. The database source is compared
when its database answers. Like the comparison of external tables, it is
not a Django system check: ``runserver`` and ``migrate`` never open the
database for it. Codes in ``SILENCED_SYSTEM_CHECKS`` are left out.

Override / escape hatch: ``KARNI_NAVIGATION_PAGES = []`` turns the route
comparison off, and ``check_navigation(nodes=..., routes=...)`` compares any
menu with any routes.
"""

from __future__ import annotations

import difflib
import fnmatch
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from django.conf import settings
from django.core import checks
from django.db import DatabaseError

from karni import navigation
from karni.errorcodes import get as registry_entry
from karni.exceptions import check_error, check_warning

__all__ = [
    "DEFAULT_PAGES",
    "check_navigation",
    "frontend_routes",
    "navigation_check_failures",
    "route_served",
]

#: Where a Karni scaffold registers its pages.
DEFAULT_PAGES: Final = ("frontend/src/routes.tsx",)
_PATH: Final = re.compile(r"""\bpath:\s*["'`]([^"'`]+)["'`]""")


def _fix(code: str) -> str:
    entry = registry_entry(code)
    return entry.fix if entry is not None else "See the linked page."


def _page_files() -> list[Path]:
    configured = getattr(settings, "KARNI_NAVIGATION_PAGES", DEFAULT_PAGES)
    from karni.testing._source import project_root

    root = project_root()
    files = []
    for name in configured or ():
        path = Path(str(name))
        files.append(path if path.is_absolute() else root / path)
    return files


def frontend_routes() -> list[str] | None:
    """Experimental. The ``path:`` routes of the ``KARNI_NAVIGATION_PAGES`` files, in file order.

    ``None`` when no file is configured or none exists.
    """
    files = [path for path in _page_files() if path.is_file()]
    if not files:
        return None
    found: list[str] = []
    for path in files:
        for route in _PATH.findall(path.read_text(encoding="utf-8")):
            if route not in found:
                found.append(route)
    return found


def _normal(route: str) -> str:
    path = route.split("?", 1)[0].split("#", 1)[0]
    return path.rstrip("/") or "/"


def _pattern(route: str) -> re.Pattern[str]:
    parts = []
    for segment in _normal(route).split("/"):
        if segment == "$":
            parts.append(".*")
        elif segment.startswith("$"):
            parts.append("[^/]+")
        else:
            parts.append(re.escape(segment))
    return re.compile("^" + "/".join(parts) + "$")


def route_served(route: str, routes: Iterable[str]) -> bool:
    """Experimental. Whether one of ``routes`` serves ``route`` (``$id`` takes any one segment)."""
    wanted = _normal(route)
    return any(_pattern(candidate).match(wanted) for candidate in routes)


def _closest(route: str, routes: list[str]) -> str:
    close = difflib.get_close_matches(_normal(route), [_normal(r) for r in routes], n=1)
    return f"The closest route is {close[0]}." if close else "No route is close to it."


def _matches_permission(requirement: str, keys: Iterable[str]) -> bool:
    if requirement in (navigation.PUBLIC, navigation.AUTHENTICATED):
        return True
    glob = "*:*" if requirement == "*" else requirement
    return any(fnmatch.fnmatchcase(key, glob) for key in keys)


def _nodes() -> tuple[tuple[navigation.NavNode, ...] | None, list[checks.CheckMessage]]:
    if navigation.source() != navigation.DATABASE:
        return navigation.nodes_from_setting(), []
    try:
        return navigation.nodes_from_db(), []
    except DatabaseError as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return None, [
            check_warning(
                "W630",
                f"The navigation menu is in the database (KARNI_NAVIGATION = 'db'), which did "
                f"not answer ({reason}), so its routes and requirements were not compared.",
                hint=_fix("W630"),
            )
        ]


def check_navigation(
    nodes: Iterable[navigation.NavNode] | None = None, routes: list[str] | None = None
) -> list[checks.CheckMessage]:
    """Experimental. ``E533``, ``E534``, ``W630`` and ``W631`` for the active menu.

    ``nodes`` and ``routes`` default to the active source's menu and
    :func:`frontend_routes`. Nothing to report while ``KARNI_NAVIGATION`` is
    unset and no ``nodes`` are given.
    """
    messages: list[checks.CheckMessage] = []
    if nodes is None:
        if navigation.source() is None:
            return []
        loaded, messages = _nodes()
        if loaded is None:
            return _unsilenced(messages)
        nodes = loaded
    menu = list(navigation.walk(nodes))
    if routes is None:
        routes = frontend_routes()
        if routes is None and _page_files():
            names = ", ".join(str(path) for path in _page_files())
            messages.append(
                check_warning(
                    "W631",
                    f"No KARNI_NAVIGATION_PAGES file exists ({names}), so the menu's routes were "
                    "not compared with the frontend's pages.",
                    hint=_fix("W631"),
                )
            )
    if routes is not None:
        for place, node in menu:
            if node.route is not None and not route_served(node.route, routes):
                messages.append(
                    check_error(
                        "E533",
                        f"Navigation item {place!r} links to {node.route}, which no page of "
                        f"the frontend serves. {_closest(node.route, routes)}",
                        hint=_fix("E533"),
                    )
                )
    from karni.accounts.roles import permission_keys

    keys = list(permission_keys())
    for place, node in menu:
        if not _matches_permission(node.requires, keys):
            messages.append(
                check_error(
                    "E534",
                    f"Navigation entry {place!r} requires {node.requires!r}, which names no "
                    "permission of the project, so only a superuser would see it.",
                    hint=_fix("E534"),
                )
            )
    return _unsilenced(messages)


def _unsilenced(messages: list[checks.CheckMessage]) -> list[checks.CheckMessage]:
    silenced = set(getattr(settings, "SILENCED_SYSTEM_CHECKS", None) or [])
    return [message for message in messages if message.id not in silenced]


def navigation_check_failures() -> tuple[list[str], list[str]]:
    """Experimental. ``(errors, warnings)`` of :func:`check_navigation`, for ``karni check``."""
    errors: list[str] = []
    warnings: list[str] = []
    for message in check_navigation():
        text = f"{message.id}: {message.msg}"
        if message.hint:
            text += f"\n\tHINT: {message.hint}"
        (errors if message.is_serious() else warnings).append(text)
    return errors, warnings
