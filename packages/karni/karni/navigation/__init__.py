"""Experimental. Navigation from data: each user's menu, opened by the same grants as the API.

Large apps show each customer a different set of modules and pages, and
admins change the menu without a deploy. The menu comes from one of two
sources, in one shape:

* ``KARNI_NAVIGATION`` as a list of items and groups in the settings::

      KARNI_NAVIGATION = [
          {"label": "Home", "route": "/", "icon": "home"},
          {
              "label": "Catalog",
              "icon": "box",
              "children": [
                  {"label": "Products", "route": "/products", "requires": "catalog.product:view"},
                  {"label": "Regions", "route": "/regions", "requires": "catalog.region:view"},
              ],
          },
      ]

* ``KARNI_NAVIGATION = "db"``: the :class:`~karni.navigation.models.NavItem`
  tree, edited in the admin. Its table comes with the ``karni.navigation``
  app, which a project adds to ``INSTALLED_APPS`` only for this source, so a
  project that keeps its menu in the settings gains no table.

An item has a ``label``, an ``icon`` name, a ``route`` (an app path such as
``/products``), an ``order`` among its siblings (default 0, then the list
order) and what it ``requires``:

* ``"public"``: everyone, signed in or not.
* ``"authenticated"`` (the default): every signed-in user.
* a permission pattern written as in ``KARNI_ROLES`` grants
  (``"catalog.product:view"``, ``"catalog.*:view"``, ``"*"``): a user who
  holds a grant for a permission the pattern names, from a role or a live
  per-user grant, exactly as ``user.can`` and ``Granted()`` read them
  (:func:`karni.accounts.roles.grants_for`). A superuser holds every
  permission.

A group is an item without a route. It shows when its own requirement
opens and at least one entry inside it shows, so a group whose entries are
all hidden is left out.

:func:`menu_for` answers the menu one user sees, siblings in order. The
``GET /api/navigation/`` endpoint (:mod:`karni.navigation.api`) and the
admin's preview read it. Its cost: no query for ``public`` and
``authenticated`` items, one for the role grants once an item names a
permission (and one for the user grants while ``KARNI_USER_GRANTS`` is on),
and one for the rows of the database source.

Override / escape hatch: ``menu_for(user, nodes=...)`` filters any tree of
:class:`NavNode` (a project's own source), :func:`opens` is the requirement
check on its own, and :class:`karni.navigation.api.NavigationView` is a plain
view to subclass or to replace at the same path.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Final

from django.conf import settings

from karni.exceptions import KarniImproperlyConfigured

__all__ = [
    "APP",
    "AUTHENTICATED",
    "DATABASE",
    "PUBLIC",
    "SETTING",
    "NavNode",
    "icon_problem",
    "load_nodes",
    "menu_for",
    "nodes_from_db",
    "nodes_from_setting",
    "opens",
    "payload",
    "requirement_problem",
    "route_problem",
    "settings_problems",
    "source",
    "walk",
]

#: The setting: a list of items and groups, ``"db"``, or ``None`` (no menu, no endpoint).
SETTING: Final = "KARNI_NAVIGATION"
#: The value of ``KARNI_NAVIGATION`` that reads the menu from the ``NavItem`` table.
DATABASE: Final = "db"
#: The app that holds ``NavItem``, added to ``INSTALLED_APPS`` for the database source only.
APP: Final = "karni.navigation"
#: Everyone, signed in or not.
PUBLIC: Final = "public"
#: Every signed-in user: what an item requires unless it says otherwise.
AUTHENTICATED: Final = "authenticated"

LABEL_MAX: Final = 100
ROUTE_MAX: Final = 200
ICON_MAX: Final = 50
REQUIRES_MAX: Final = 200
#: An icon is a name the frontend maps to a picture: ``home``, ``bar-chart``.
ICON_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
#: The code of ``"db"`` without the app (the other problems are ``E530`` and ``E532``).
_NO_APP: Final = "E531"
_KEYS: Final = frozenset({"label", "route", "icon", "order", "requires", "children"})


@dataclass(frozen=True)
class NavNode:
    """Experimental. One entry of the menu: an item (it has a ``route``) or a group (it has none).

    ``icon`` is a name (``None`` for none) and ``requires`` is ``public``,
    ``authenticated`` or a permission pattern. ``children`` are a group's
    entries, already in order. :meth:`as_dict` is the shape the endpoint
    answers, which leaves ``requires`` out.
    """

    label: str
    route: str | None = None
    icon: str | None = None
    requires: str = AUTHENTICATED
    children: tuple[NavNode, ...] = ()

    @property
    def is_group(self) -> bool:
        """A group has no route. It shows when an entry inside it shows."""
        return self.route is None

    def as_dict(self) -> dict[str, Any]:
        """``{label, icon, route, children}``: what ``GET /api/navigation/`` answers per entry."""
        return {
            "label": self.label,
            "icon": self.icon,
            "route": self.route,
            "children": [child.as_dict() for child in self.children],
        }


def source() -> str | None:
    """Experimental. ``"settings"``, ``"db"``, or ``None`` while ``KARNI_NAVIGATION`` is unset."""
    value = getattr(settings, SETTING, None)
    if value is None:
        return None
    return DATABASE if value == DATABASE else "settings"


# checking a menu


def requirement_problem(value: Any) -> str | None:
    """Experimental. Why ``value`` is not a requirement (``None`` when it is one).

    A requirement is ``public``, ``authenticated``, ``*`` or a permission
    pattern ``app_label.model:action`` with ``*`` for any part.
    """
    if not isinstance(value, str) or not value:
        return f"{value!r} is not a requirement"
    if value in (PUBLIC, AUTHENTICATED, "*"):
        return None
    label, sep, action = value.rpartition(":")
    if not sep or not action or not label or any(ch.isspace() for ch in value):
        return (
            f"{value!r} is not a requirement: write 'public', 'authenticated' or a permission "
            "pattern as in KARNI_ROLES ('app_label.model:action', with * for a part)"
        )
    if len(value) > REQUIRES_MAX:
        return f"{value[:40]!r}... is longer than {REQUIRES_MAX} characters"
    return None


def route_problem(value: Any) -> str | None:
    """Experimental. Why ``value`` is not a route (``None`` when it is one).

    A route is an app path that starts with ``/``, such as ``/products``.
    """
    if not isinstance(value, str) or not value.startswith("/"):
        return f"route {value!r} must be an app path that starts with '/', e.g. '/products'"
    if any(ch.isspace() for ch in value) or len(value) > ROUTE_MAX:
        return f"route {value[:60]!r} must have no spaces and at most {ROUTE_MAX} characters"
    return None


def icon_problem(value: Any) -> str | None:
    """Experimental. Why ``value`` is not an icon name (``None`` when it is one, or empty)."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not ICON_NAME.match(value) or len(value) > ICON_MAX:
        return (
            f"icon {value!r} must be a name in lowercase letters, digits, - and _ "
            f"(at most {ICON_MAX} characters), e.g. 'home' or 'bar-chart'"
        )
    return None


def _item_problems(item: Any, where: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{where} = {item!r} must be a dict with a label (E530)"]
    problems: list[str] = []
    unknown = sorted(str(key) for key in item if key not in _KEYS)
    if unknown:
        problems.append(
            f"{where} has unknown keys {unknown} (known: {', '.join(sorted(_KEYS))}) (E530)"
        )
    label = item.get("label")
    if not isinstance(label, str) or not label.strip() or len(label) > LABEL_MAX:
        problems.append(
            f"{where}['label'] = {label!r} must be a text of 1 to {LABEL_MAX} characters (E530)"
        )
    children = item.get("children")
    route = item.get("route")
    if children is not None and not isinstance(children, list):
        problems.append(f"{where}['children'] must be a list of items (E530)")
        children = None
    if route is not None:
        problem = route_problem(route)
        if problem:
            problems.append(f"{where}: {problem} (E530)")
        if children:
            problems.append(
                f"{where} has a route and children: a group is an item without a route. Move "
                "the route to an item inside the group (E530)"
            )
    elif not children:
        problems.append(
            f"{where} has neither a route nor children: give an item its route, or a group "
            "its entries (E530)"
        )
    icon = icon_problem(item.get("icon"))
    if icon:
        problems.append(f"{where}: {icon} (E530)")
    order = item.get("order", 0)
    if not isinstance(order, int) or isinstance(order, bool):
        problems.append(f"{where}['order'] = {order!r} must be an integer (E530)")
    if "requires" in item:
        problem = requirement_problem(item["requires"])
        if problem:
            problems.append(f"{where}['requires']: {problem} (E532)")
    for index, child in enumerate(children or []):
        problems.extend(_item_problems(child, f"{where}['children'][{index}]"))
    return problems


def settings_problems(value: Any, installed_apps: Iterable[Any] | None = None) -> list[str]:
    """Experimental. Every problem with a ``KARNI_NAVIGATION`` value, each ending with its code.

    ``None`` and a valid list have none. ``"db"`` needs ``karni.navigation`` in
    ``installed_apps`` (``E531``; not checked when ``installed_apps`` is
    ``None``). Startup validation (:mod:`karni.conf`) calls it.
    """
    if value is None:
        return []
    if value == DATABASE:
        if installed_apps is None:
            return []
        names = {str(app) for app in installed_apps}
        if not any(name == APP or name.startswith(f"{APP}.apps.") for name in names):
            return [
                f"{SETTING} = 'db' reads the menu from the NavItem table, which comes with the "
                f"'{APP}' app: add it to INSTALLED_APPS and run migrate ({_NO_APP})"
            ]
        return []
    if not isinstance(value, list):
        return [
            f"{SETTING} = {value!r} must be a list of items and groups, 'db' (the NavItem "
            "table) or None (no menu) (E530)"
        ]
    problems: list[str] = []
    for index, item in enumerate(value):
        problems.extend(_item_problems(item, f"{SETTING}[{index}]"))
    return problems


# reading a menu


def _node(item: dict[str, Any]) -> NavNode:
    children = item.get("children") or []
    return NavNode(
        label=str(item["label"]),
        route=item.get("route"),
        icon=item.get("icon") or None,
        requires=item.get("requires", AUTHENTICATED),
        children=_ordered(children),
    )


def _ordered(items: Sequence[dict[str, Any]]) -> tuple[NavNode, ...]:
    ranked = sorted(enumerate(items), key=lambda pair: (pair[1].get("order", 0), pair[0]))
    return tuple(_node(item) for _index, item in ranked)


def nodes_from_setting(value: Any = None) -> tuple[NavNode, ...]:
    """Experimental. The menu a ``KARNI_NAVIGATION`` list declares (default: the setting's).

    Siblings sort by ``order`` (default 0), then by their place in the list.
    A value with a problem raises ``E530`` (startup validation reports it
    first, unless ``KARNI_VALIDATE`` is off).
    """
    value = getattr(settings, SETTING, None) if value is None else value
    if not isinstance(value, list):
        return ()
    problems = settings_problems(value)
    if problems:
        raise KarniImproperlyConfigured(
            f"{SETTING} is not valid: {problems[0]}. Fix the setting (the startup check lists "
            "every problem).",
            code="E530",
        )
    return _ordered(value)


def nodes_from_db(using: str | None = None) -> tuple[NavNode, ...]:
    """Experimental. The menu the ``NavItem`` rows hold: one query, siblings in tree order.

    A soft-deleted row hides its branch. A row with a route is an item: the
    admin refuses children under it (``E536``), and any it has are not shown.
    """
    from karni.navigation.models import NavItem

    manager = NavItem._default_manager
    if using is not None:
        manager = manager.db_manager(using)
    rows = list(manager.order_by(*NavItem.tree_ordering()))
    by_parent: dict[Any, list[Any]] = {}
    for row in rows:
        by_parent.setdefault(row.parent_id, []).append(row)

    def build(parent: Any, seen: frozenset[Any]) -> tuple[NavNode, ...]:
        nodes: list[NavNode] = []
        for row in by_parent.get(parent, []):
            if row.pk in seen:
                continue  # cyclic data never loops
            route = row.route or None
            nodes.append(
                NavNode(
                    label=row.label,
                    route=route,
                    icon=row.icon or None,
                    requires=row.requires or AUTHENTICATED,
                    children=() if route else build(row.pk, seen | {row.pk}),
                )
            )
        return tuple(nodes)

    return build(None, frozenset())


def load_nodes() -> tuple[NavNode, ...]:
    """Experimental. The whole menu of the active source, before any user's requirements."""
    found = source()
    if found == DATABASE:
        return nodes_from_db()
    if found == "settings":
        return nodes_from_setting()
    return ()


def walk(nodes: Iterable[NavNode], trail: tuple[str, ...] = ()) -> Iterator[tuple[str, NavNode]]:
    """Experimental. Every node depth first, with its place: ``"Catalog > Products"``."""
    for node in nodes:
        place = (*trail, node.label)
        yield " > ".join(place), node
        yield from walk(node.children, place)


# whose menu


def _authenticated(user: Any) -> bool:
    return user is not None and bool(getattr(user, "is_authenticated", False))


def opens(requirement: str, user: Any) -> bool:
    """Experimental. Whether ``requirement`` lets ``user`` see an entry.

    A permission pattern reads :func:`karni.accounts.roles.grants_for`, the
    grants ``Granted()`` and ``user.can`` read: role grants and live user
    grants, once per user instance.
    """
    if requirement == PUBLIC:
        return True
    if not _authenticated(user):
        return False
    if requirement == AUTHENTICATED:
        return True
    from karni.accounts.roles import grants_for

    held = grants_for(user)
    if "*" not in requirement:
        return bool(held.get(requirement))
    glob = "*:*" if requirement == "*" else requirement
    return any(grants and fnmatch.fnmatchcase(key, glob) for key, grants in held.items())


def _visible(node: NavNode, user: Any) -> NavNode | None:
    if not opens(node.requires, user):
        return None
    if not node.is_group:
        return node
    children = tuple(
        shown for shown in (_visible(child, user) for child in node.children) if shown is not None
    )
    if not children:
        return None
    return NavNode(node.label, None, node.icon, node.requires, children)


def menu_for(user: Any, nodes: Iterable[NavNode] | None = None) -> list[NavNode]:
    """Experimental. The entries ``user`` sees, in order: hidden ones and empty groups left out.

    ``nodes`` is the menu to filter (default: the active source's,
    :func:`load_nodes`). ``user`` may be anonymous.
    """
    found = load_nodes() if nodes is None else nodes
    return [shown for shown in (_visible(node, user) for node in found) if shown is not None]


def payload(user: Any, nodes: Iterable[NavNode] | None = None) -> dict[str, Any]:
    """Experimental. ``{"items": [...]}``: the body of ``GET /api/navigation/`` for ``user``."""
    return {"items": [node.as_dict() for node in menu_for(user, nodes)]}
