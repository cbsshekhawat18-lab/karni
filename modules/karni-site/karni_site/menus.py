"""Menus at render time: what ``{% get_menu "<name>" as items %}`` gives a loop.

A menu's tree (titles, addresses, children, the rows a ``children_from``
item expands to) is built once and cached. The current page is marked per
request on the :class:`MenuEntry` objects the tag returns: ``item.current``
when the item is the current page, ``item.active`` when it, a page under its
own path (``/services/web/`` for ``/services/``, ``KARNI_SITE_MENU_SECTIONS``)
or one of its children is. The template keeps the design's markup and only
reads these.

A menu the database does not have yet can be seeded from markup
(:func:`seed_menu`): the links of a design's navigation, nested lists
becoming children. ``{% get_menu "header" seed="website/menus/header.html" %}``
does that on the first render, so the client starts with the designer's menu.

Saving a menu or an item clears every cached menu. So does saving a row of
a model a menu points at (an item's row, or its ``children_from`` model),
through :func:`model_changed`.

Override / escape hatch: ``KARNI_SITE_MENU_ROWS`` decides which rows a
``children_from`` item lists (default: the model's default manager, so its
scopes apply), ``KARNI_SITE_MENU_ROWS_LIMIT`` how many, and
``KARNI_SITE_IS_ACTIVE`` what counts as the current page.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

from karni_site import caching, conf
from karni_site.navigation import any_active

__all__ = [
    "Link",
    "MenuEntry",
    "NoTarget",
    "entries",
    "item_fields",
    "menu_rows",
    "model_changed",
    "parse_links",
    "seed_menu",
    "validate_item",
]

logger = logging.getLogger("karni_site")
MENU_CODE = "SITE007"


@dataclass
class MenuEntry:
    """One link of a menu as a template loops over it."""

    title: str
    url: str
    new_tab: bool = False
    current: bool = False
    active: bool = False
    children: list[MenuEntry] = field(default_factory=list)

    def __str__(self) -> str:
        return self.title


def menu_rows(model: type[Any], item: Any) -> Iterable[Any]:
    """The rows a ``children_from`` item lists: the model's default manager, in its order."""
    return model._default_manager.all()


def _rows_function() -> Callable[[type[Any], Any], Iterable[Any]]:
    configured = conf.get("KARNI_SITE_MENU_ROWS")
    found: Callable[[type[Any], Any], Iterable[Any]] = (
        configured if callable(configured) else import_string(str(configured))
    )
    return found


def _path_patterns(url: str) -> list[str]:
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or not parts.path.startswith("/"):
        return []
    return [parts.path]


class NoTarget(LookupError):
    """An item whose page, row or model is gone: it is left out of the menu."""


_NoTarget = NoTarget


def _row(model: type[Any], pk: str) -> Any | None:
    """The row ``pk`` of ``model`` through its default manager, or ``None`` (a bad key too)."""
    try:
        return model._default_manager.filter(pk=pk).first()
    except (ValueError, ValidationError):
        return None


def target(item: Any) -> tuple[str, list[str], str]:
    """``(address, current-page patterns, default title)`` of an item (``_NoTarget`` if gone)."""
    if item.route:
        kwargs = item.route_kwargs or None
        try:
            url = reverse(item.route, kwargs=kwargs)
        except NoReverseMatch as exc:
            raise _NoTarget(f"no page is named {item.route!r}") from exc
        patterns = _path_patterns(url) if kwargs else [item.route]
        return url + item.suffix, patterns, item.route.rsplit(":", 1)[-1].replace("_", " ").title()
    if item.content_type_id and item.object_id:
        model = item.content_type.model_class()
        if model is None:
            raise _NoTarget("its model no longer exists")
        row = _row(model, item.object_id)
        if row is None or not hasattr(row, "get_absolute_url"):
            raise _NoTarget("its row no longer exists")
        url = str(row.get_absolute_url())
        return url + item.suffix, _path_patterns(url), str(row)
    url = item.url
    return url + (item.suffix if url else ""), _path_patterns(url), url


def _node(item: Any, children: dict[Any, list[Any]]) -> dict[str, Any] | None:
    try:
        url, patterns, fallback = target(item)
    except _NoTarget as exc:
        logger.warning("karni_site: menu item %s is left out: %s", item.pk, exc)
        return None
    kids = [node for child in children.get(item.pk, []) if (node := _node(child, children))]
    if item.children_from_id:
        kids.extend(_rows(item))
    return {
        "title": item.title or fallback,
        "url": url,
        "new_tab": item.new_tab,
        "patterns": patterns,
        "section": _section(url),
        "children": kids,
    }


def _section(url: str) -> str:
    """The path whose pages an item stands for (``/services/``), or ``""`` (home, elsewhere)."""
    parts = urlsplit(url)
    path = parts.path
    if parts.scheme or parts.netloc or not path.startswith("/") or path == "/":
        return ""
    return path if path.endswith("/") else ""


def _rows(item: Any) -> list[dict[str, Any]]:
    model = item.children_from.model_class()
    if model is None:
        return []
    limit = int(conf.get("KARNI_SITE_MENU_ROWS_LIMIT") or 0)
    found: list[dict[str, Any]] = []
    for row in _rows_function()(model, item):
        if limit and len(found) >= limit:
            break
        try:
            url = str(row.get_absolute_url())
        except Exception:  # noqa: BLE001 - a row without its own page is left out
            continue
        found.append(
            {
                "title": str(row),
                "url": url,
                "new_tab": False,
                "patterns": _path_patterns(url),
                "children": [],
            }
        )
    return found


def _build(name: str) -> list[dict[str, Any]] | None:
    from karni_site.models import Menu

    menu = Menu.objects.filter(name=name).first()
    if menu is None:
        return None
    children: dict[Any, list[Any]] = defaultdict(list)
    for item in menu.items.filter(enabled=True).select_related("content_type", "children_from"):
        children[item.parent_id].append(item)
    return [node for item in children.get(None, []) if (node := _node(item, children))]


def tree(name: str) -> list[dict[str, Any]] | None:
    """The cached tree of menu ``name``, or ``None`` when there is no such menu."""
    store = caching.cache()
    key = caching.key("menu", str(caching.version("menus")), name)
    found = store.get(key)
    if found is None:
        found = {"items": _build(name)}
        store.set(key, found, caching.timeout())
    items: list[dict[str, Any]] | None = found["items"]
    return items


def _entry(node: dict[str, Any], request: Any) -> MenuEntry:
    children = [_entry(child, request) for child in node["children"]]
    current = any_active(request, node["patterns"]) if node["patterns"] else False
    section = str(node.get("section") or "")
    below = bool(section) and bool(conf.get("KARNI_SITE_MENU_SECTIONS"))
    return MenuEntry(
        title=node["title"],
        url=node["url"],
        new_tab=node["new_tab"],
        current=current,
        active=current
        or any(child.active for child in children)
        or (below and any_active(request, [section + "*"])),
        children=children,
    )


def entries(
    name: str, request: Any = None, seed: Callable[[], str] | None = None, source: str = ""
) -> list[MenuEntry]:
    """The items of menu ``name`` for ``request``: seeded from ``seed()`` when it is new."""
    try:
        found = tree(name)
        if found is None and seed is not None and conf.get("KARNI_SITE_SEED_ON_RENDER"):
            seed_menu(name, seed(), source=source)
            found = tree(name)
    except DatabaseError:
        logger.exception("karni_site: menu %s could not be read", name)
        return []
    return [_entry(node, request) for node in found or []]


# seeding from markup


@dataclass
class Link:
    """A link of a design's navigation, with the links nested under it."""

    title: str
    href: str
    children: list[Link] = field(default_factory=list)


@dataclass
class _Element:
    tag: str
    attrs: dict[str, str]
    children: list[_Element | str] = field(default_factory=list)

    def text(self) -> str:
        return " ".join(
            "".join(
                child if isinstance(child, str) else child.text() for child in self.children
            ).split()
        )


class _Tree(HTMLParser):
    _VOID = frozenset({"br", "img", "hr", "input", "meta", "link", "source", "wbr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Element("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":  # a sibling <li> closes one left open
            while len(self.stack) > 1 and self.stack[-1].tag not in ("ul", "ol", "root"):
                if self.stack[-1].tag == "li":
                    self.stack.pop()
                    break
                self.stack.pop()
        element = _Element(tag, {name: value or "" for name, value in attrs})
        self.stack[-1].children.append(element)
        if tag not in self._VOID:
            self.stack.append(element)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _first(element: _Element, tags: tuple[str, ...], stop: tuple[str, ...] = ()) -> _Element | None:
    for child in element.children:
        if isinstance(child, str):
            continue
        if child.tag in tags:
            return child
        if child.tag in stop:
            continue
        found = _first(child, tags, stop)
        if found is not None:
            return found
    return None


def _links(element: _Element) -> list[Link]:
    found: list[Link] = []
    for child in element.children:
        if isinstance(child, str):
            continue
        if child.tag == "a" and "href" in child.attrs:
            found.append(Link(child.text(), child.attrs["href"]))
        elif child.tag == "li":
            anchor = _first(child, ("a",), stop=("ul", "ol"))
            nested = _first(child, ("ul", "ol"))
            kids = _links(nested) if nested is not None else []
            if anchor is not None and "href" in anchor.attrs:
                found.append(Link(anchor.text(), anchor.attrs["href"], kids))
            else:
                found.extend(kids)
        else:
            found.extend(_links(child))
    return found


def parse_links(markup: str) -> list[Link]:
    """The links of a navigation's markup: list items with their nested lists, or bare links."""
    parser = _Tree()
    parser.feed(markup)
    parser.close()
    return _links(parser.root)


def _plain(value: Any) -> Any:
    return value if isinstance(value, int | str) else str(value)


def item_fields(href: str) -> dict[str, Any]:
    """The item fields for an address: a page by URL name when it resolves, else the address."""
    href = href.strip()
    parts = urlsplit(href)
    if not href or parts.scheme or parts.netloc or href.startswith(("#", "?")):
        return {"url": href}
    path = parts.path if parts.path.startswith("/") else "/" + parts.path
    try:
        match = resolve(path)
    except Resolver404:
        return {"url": href}
    if not match.view_name or match.args:
        return {"url": href}
    kwargs = {name: _plain(value) for name, value in match.kwargs.items()}
    try:
        if reverse(match.view_name, kwargs=kwargs or None) != path:
            return {"url": href}
    except NoReverseMatch:
        return {"url": href}
    suffix = ("?" + parts.query if parts.query else "") + (
        "#" + parts.fragment if parts.fragment else ""
    )
    return {"route": match.view_name, "route_kwargs": kwargs, "suffix": suffix}


def seed_menu(name: str, markup: str, *, source: str = "", title: str = "") -> bool:
    """Create menu ``name`` from the links in ``markup``. ``False`` when it exists already."""
    from karni_site.models import Menu, MenuItem

    links = parse_links(markup)
    try:
        with transaction.atomic():
            if Menu.objects.filter(name=name).exists():
                return False
            menu = Menu.objects.create(
                name=name,
                title=title or name.replace("-", " ").replace("_", " ").title(),
                seed=source,
            )

            def add(found: list[Link], parent: Any) -> None:
                for order, link in enumerate(found):
                    item = MenuItem.objects.create(
                        menu=menu,
                        parent=parent,
                        title=link.title,
                        order=order,
                        **item_fields(link.href),
                    )
                    add(link.children, item)

            add(links, None)
    except IntegrityError:
        return False
    caching.bump("menus")
    return True


# validation and invalidation


def _error(message: str) -> ValidationError:
    return ValidationError(f"{message} ({MENU_CODE})", code=MENU_CODE)


def validate_item(item: Any) -> None:
    """Refuse an item that points nowhere, at a page that does not exist, or in a circle."""
    from karni_site.sanitize import safe_url

    targets = [bool(item.route), bool(item.content_type_id or item.object_id), bool(item.url)]
    if sum(targets) > 1:
        raise _error(_("Choose one place for the link: a page, a row's page, or an address."))
    if not any(targets) and not item.children_from_id:
        raise _error(_("Choose where the link goes: a page, a row's page, or an address."))
    if item.route:
        try:
            reverse(item.route, kwargs=item.route_kwargs or None)
        except NoReverseMatch:
            raise _error(
                _("No page is named %(route)s. Choose one of the site's pages.")
                % {"route": item.route}
            ) from None
    if item.content_type_id or item.object_id:
        model = item.content_type.model_class() if item.content_type_id else None
        row = _row(model, item.object_id) if model is not None and item.object_id else None
        if row is None or not hasattr(row, "get_absolute_url"):
            raise _error(_("The row this link points at does not exist or has no page."))
    if item.url and not safe_url(item.url):
        raise _error(_("This address cannot be a link: use https://, /path/, #section or mailto:."))
    if item.children_from_id:
        model = item.children_from.model_class()
        if model is None or not hasattr(model, "get_absolute_url"):
            raise _error(_("Rows of this model have no page of their own to link to."))
    seen = {item.pk} if item.pk else set()
    parent = item.parent
    while parent is not None:
        if parent.menu_id != item.menu_id:
            raise _error(_("An item can only be under an item of the same menu."))
        if parent.pk in seen:
            raise _error(_("An item cannot be under itself."))
        seen.add(parent.pk)
        parent = parent.parent


def _referenced_labels() -> set[str]:
    """``app_label.model`` of every model a menu points at (cached with the menus)."""
    from karni_site.models import MenuItem

    store = caching.cache()
    key = caching.key("menu-models", str(caching.version("menus")))
    found: set[str] | None = store.get(key)
    if found is not None:
        return found
    found = set()
    with transaction.atomic():  # a savepoint: a failed read never breaks the caller's
        rows = MenuItem.objects.filter(enabled=True).select_related("content_type", "children_from")
        for item in rows.exclude(content_type=None, children_from=None):
            for content_type in (item.content_type, item.children_from):
                if content_type is not None:
                    found.add(f"{content_type.app_label}.{content_type.model}")
    store.set(key, found, caching.timeout())
    return found


def model_changed(sender: type[Any], **kwargs: Any) -> None:
    """``post_save``/``post_delete`` of any model: clear the menus that list its rows."""
    meta = getattr(sender, "_meta", None)
    if (
        meta is None
        or sender.__module__ == "__fake__"  # a migration's historical model
        or meta.app_label in ("karni_site", "contenttypes", "sessions", "admin")
    ):
        return
    try:
        referenced = _referenced_labels()
    except DatabaseError:
        return
    if f"{meta.app_label}.{meta.model_name}" in referenced:
        caching.bump("menus")
