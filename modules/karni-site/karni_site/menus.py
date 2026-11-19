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
A list in the seed marked ``data-karni-children-from="<app>.<Model>"`` (as
``karni import design`` marks one whose links are that model's detail pages)
becomes an item with children from that model instead of its links.

A seeded menu follows its seed template, the way an editable block follows
its template's text (:func:`sync_menu`): when the seed's links change (a new
link, a new text, a renamed route), the items nobody changed in the admin
change with it, an item whose link left the seed goes, and a new link is
added. An item someone changed (its title, its target, its place, shown or
not), an item someone added, and an item someone deleted stay as they are.
``Menu.seeded`` records what the seed gave each item, and
``MenuItem.seed_key`` which link an item came from.

An item with children from a model and neither a title nor an address of its
own lists the rows in its place: a footer's list of every service is one
such item, and a service the client adds appears in it.

Saving a menu or an item clears every cached menu. So does saving a row of
a model a menu points at (an item's row, or its ``children_from`` model),
through :func:`model_changed`.

Override / escape hatch: ``KARNI_SITE_MENU_ROWS`` decides which rows a
``children_from`` item lists (default: the model's default manager, so its
scopes apply), ``KARNI_SITE_MENU_ROWS_LIMIT`` how many, and
``KARNI_SITE_IS_ACTIVE`` what counts as the current page.
``KARNI_SITE_MENU_FOLLOW_SEED = False`` seeds a menu once and never changes it
afterwards, and :func:`sync_menu` follows a seed from code of your own.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Final
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

from karni_site import caching, conf
from karni_site.navigation import any_active

__all__ = [
    "CHILDREN_FROM",
    "Link",
    "MenuEntry",
    "NoTarget",
    "entries",
    "in_place",
    "item_fields",
    "menu_rows",
    "model_changed",
    "parse_links",
    "seed_menu",
    "sync_menu",
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


def in_place(item: Any) -> bool:
    """An item with children from a model and no title or address: its rows stand in its place."""
    return bool(item.children_from_id) and not (
        item.title or item.route or item.content_type_id or item.object_id or item.url
    )


def _nodes(items: list[Any], children: dict[Any, list[Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for item in items:
        if in_place(item):
            found.extend(_rows(item))
        elif (node := _node(item, children)) is not None:
            found.append(node)
    return found


def _node(item: Any, children: dict[Any, list[Any]]) -> dict[str, Any] | None:
    try:
        url, patterns, fallback = target(item)
    except _NoTarget as exc:
        logger.warning("karni_site: menu item %s is left out: %s", item.pk, exc)
        return None
    kids = _nodes(children.get(item.pk, []), children)
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


def _build(name: str) -> dict[str, Any]:
    """What the cache keeps of menu ``name``: its tree, its seed template and the seed's digest."""
    from karni_site.models import Menu

    menu = Menu.objects.filter(name=name).first()
    if menu is None:
        return {"items": None, "seed": "", "digest": ""}
    children: dict[Any, list[Any]] = defaultdict(list)
    for item in menu.items.filter(enabled=True).select_related("content_type", "children_from"):
        children[item.parent_id].append(item)
    return {
        "items": _nodes(children.get(None, []), children),
        "seed": menu.seed,
        "digest": str((menu.seeded or {}).get("digest") or ""),
    }


def _cached(name: str) -> dict[str, Any]:
    store = caching.cache()
    key = caching.key("menu", str(caching.version("menus")), name)
    found: dict[str, Any] | None = store.get(key)
    if found is None or "seed" not in found:
        found = _build(name)
        store.set(key, found, caching.timeout())
    return found


def tree(name: str) -> list[dict[str, Any]] | None:
    """The cached tree of menu ``name``, or ``None`` when there is no such menu."""
    items: list[dict[str, Any]] | None = _cached(name)["items"]
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
    """The items of menu ``name`` for ``request``: seeded from ``seed()`` when it is new.

    A menu seeded from ``source`` follows it: when the links ``seed()`` gives change,
    :func:`sync_menu` brings the items nobody changed in line with them.
    """
    try:
        cached = _cached(name)
        found = cached["items"]
        if seed is not None and conf.get("KARNI_SITE_SEED_ON_RENDER"):
            if found is None:
                seed_menu(name, seed(), source=source)
                found = tree(name)
            elif _follows(cached, source) and (markup := _rendered(seed, name)) is not None:
                if _digest(parse_links(markup)) != cached["digest"]:
                    sync_menu(name, markup, source=source)
                    found = tree(name)
    except DatabaseError:
        logger.exception("karni_site: menu %s could not be read", name)
        return []
    return [_entry(node, request) for node in found or []]


def _rendered(seed: Callable[[], str], name: str) -> str | None:
    """The seed's markup, or ``None`` when it fails to render: the stored menu is shown."""
    try:
        return seed()
    except Exception:  # noqa: BLE001 - a broken seed never breaks a page that has its menu
        logger.exception(
            "karni_site: the seed of menu %s does not render, it is not followed", name
        )
        return None


def _follows(cached: dict[str, Any], source: str) -> bool:
    """Whether a menu follows ``source``: it was seeded from it, and following is on."""
    return (
        bool(source) and cached["seed"] == source and bool(conf.get("KARNI_SITE_MENU_FOLLOW_SEED"))
    )


# seeding from markup


@dataclass
class Link:
    """A link of a design's navigation, with the links nested under it.

    ``children_from`` (``"website.Service"``) is the model a marked list stands
    for: the item lists its rows, and ``children`` are the design's links, kept
    for a project without that model.
    """

    title: str
    href: str
    children: list[Link] = field(default_factory=list)
    children_from: str = ""


#: The attribute that marks a seed's list as a model's rows.
CHILDREN_FROM: Final = "data-karni-children-from"


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
            rows = nested.attrs.get(CHILDREN_FROM, "").strip() if nested is not None else ""
            if anchor is not None and "href" in anchor.attrs:
                found.append(Link(anchor.text(), anchor.attrs["href"], kids, rows))
            else:
                found.extend(kids)
        elif child.attrs.get(CHILDREN_FROM, "").strip():
            found.append(Link("", "", _links(child), child.attrs[CHILDREN_FROM].strip()))
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


def _digest(links: list[Link]) -> str:
    """A fingerprint of a seed's links: what a menu compares to know its seed changed."""

    def plain(found: list[Link]) -> list[Any]:
        return [[link.title, link.href, link.children_from, plain(link.children)] for link in found]

    text = json.dumps(plain(links), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seed_menu(name: str, markup: str, *, source: str = "", title: str = "") -> bool:
    """Create menu ``name`` from the links in ``markup``. ``False`` when it exists already."""
    from karni_site.models import Menu

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
            entries = _Follow(menu, {}).level(_planned(links, name), [], None, None, create=True)
            menu.seeded = {"digest": _digest(links), "entries": entries}
            menu.save(update_fields=["seeded"])
    except IntegrityError:
        return False
    caching.bump("menus")
    return True


#: Why following a seed reads the items someone deleted: they stay deleted.
_EVERY_ITEM = "a menu following its seed keeps the items someone deleted deleted"


def sync_menu(name: str, markup: str, *, source: str = "") -> bool:
    """Bring menu ``name`` in line with the links in ``markup``, its seed. ``True`` when it changed.

    Each item the seed made and nobody changed takes its link's new text, target and
    place. An item whose link left the seed is deleted (kept when someone changed it
    or one of its children), and a new link becomes an item. An item someone changed,
    added or deleted stays as it is. A menu seeded from another template than
    ``source``, or not seeded at all, is left alone.
    """
    from karni_site.models import Menu, MenuItem

    links = parse_links(markup)
    fingerprint = _digest(links)
    with transaction.atomic():
        menu = Menu.objects.select_for_update().filter(name=name).first()
        if menu is None or not menu.seed or (source and menu.seed != source):
            return False
        recorded = dict(menu.seeded or {})
        if recorded.get("digest") == fingerprint:
            return False
        rows = list(
            MenuItem.objects.without("soft_delete", reason=_EVERY_ITEM)
            .filter(menu=menu)
            .select_related("children_from")
        )
        old = recorded.get("entries")
        if not isinstance(old, list):
            old = _adopt(menu, rows)
        follow = _Follow(menu, {row.seed_key: row for row in rows if row.seed_key}, rows)
        menu.seeded = {
            "digest": fingerprint,
            "entries": follow.level(_planned(links, name), old, None, None, create=True),
        }
        menu.save(update_fields=["seeded"])
    caching.bump("menus")
    return True


# following a seed: one level of the menu at a time


@dataclass
class _Node:
    """A link of the seed as the menu item it becomes."""

    link: Link
    rows: Any | None
    children: list[_Node] = field(default_factory=list)


def _planned(links: list[Link], name: str) -> list[_Node]:
    """The seed's links as items: a marked list without its model gives its links in its place."""
    found: list[_Node] = []
    for link in links:
        rows = _content_type(link.children_from)
        if link.children_from and rows is None:
            logger.warning(
                "karni_site: menu %r lists %s, which is not a model here: "
                "seeded with the design's links instead",
                name,
                link.children_from,
            )
        if rows is None and not link.href:
            found.extend(_planned(link.children, name))
            continue
        found.append(_Node(link, rows, [] if rows is not None else _planned(link.children, name)))
    return found


def _label(content_type: Any | None) -> str:
    return f"{content_type.app_label}.{content_type.model}" if content_type is not None else ""


def _given(node: _Node, order: int, parent: str) -> dict[str, Any]:
    """The item fields the seed gives ``node`` at ``order`` under the item keyed ``parent``."""
    fields = item_fields(node.link.href) if node.link.href else {}
    return {
        "title": node.link.title,
        "route": str(fields.get("route", "")),
        "route_kwargs": dict(fields.get("route_kwargs") or {}),
        "url": str(fields.get("url", "")),
        "suffix": str(fields.get("suffix", "")),
        "children_from": _label(node.rows),
        "row": "",
        "new_tab": False,
        "enabled": True,
        "order": order,
        "parent": parent,
    }


def _target(values: dict[str, Any]) -> str:
    keys = ("route", "route_kwargs", "url", "suffix", "children_from")
    return json.dumps([values.get(key) for key in keys], sort_keys=True, default=str)


class _Follow:
    """Matches one level of the seed's links with the items the seed made before, and acts."""

    def __init__(self, menu: Any, keyed: dict[str, Any], rows: list[Any] | None = None) -> None:
        self.menu = menu
        self.keyed = keyed
        self.by_pk = {row.pk: row for row in rows or ()}

    def values(self, item: Any) -> dict[str, Any]:
        """An item's fields as :func:`_given` writes them, to tell whether someone changed it."""
        parent = self.by_pk.get(item.parent_id) if item.parent_id else None
        return {
            "title": item.title,
            "route": item.route,
            "route_kwargs": dict(item.route_kwargs or {}),
            "url": item.url,
            "suffix": item.suffix,
            "children_from": _label(item.children_from),
            "row": f"{item.content_type_id}:{item.object_id}" if item.content_type_id else "",
            "new_tab": item.new_tab,
            "enabled": item.enabled,
            "order": item.order,
            "parent": getattr(parent, "seed_key", "") if parent is not None else "",
        }

    def edited(self, item: Any, entry: dict[str, Any]) -> bool:
        given = entry.get("given")
        return not isinstance(given, dict) or self.values(item) != given

    def _probe(self, entry: dict[str, Any]) -> dict[str, Any]:
        given = entry.get("given")
        if isinstance(given, dict):
            return given
        item = self.keyed.get(str(entry.get("key")))
        return self.values(item) if item is not None else {}

    def _match(
        self, old: list[dict[str, Any]], nodes: list[_Node], parent: str
    ) -> tuple[list[dict[str, Any] | None], list[dict[str, Any]]]:
        """For each node, the entry it continues (or ``None``), and the entries left over."""
        matched: list[dict[str, Any] | None] = [None] * len(nodes)
        left = list(old)
        wanted = [_given(node, index, parent) for index, node in enumerate(nodes)]
        tests = (
            lambda probe, given: (
                _target(probe) == _target(given) and probe.get("title") == given["title"]
            ),
            lambda probe, given: _target(probe) == _target(given),
            lambda probe, given: bool(given["title"]) and probe.get("title") == given["title"],
        )
        for test in tests:
            for index, given in enumerate(wanted):
                if matched[index] is not None:
                    continue
                for entry in left:
                    if test(self._probe(entry), given):
                        matched[index] = entry
                        left.remove(entry)
                        break
        # What is left pairs by position, but only an item nobody touched: a changed or
        # deleted one keeps standing for its own link.
        for index in range(len(nodes)):
            if matched[index] is not None:
                continue
            for entry in left:
                item = self.keyed.get(str(entry.get("key")))
                if item is not None and not item.is_deleted and not self.edited(item, entry):
                    matched[index] = entry
                    left.remove(entry)
                    break
        return matched, left

    def level(
        self,
        nodes: list[_Node],
        old: list[dict[str, Any]],
        parent: Any | None,
        parent_key: str | None,
        *,
        create: bool,
    ) -> list[dict[str, Any]]:
        """Follow one level: the entries it records, its children's included.

        ``create`` is false under an item someone deleted: its links make no items.
        """
        key_of_parent = parent_key or ""
        mine = [entry for entry in old if (entry.get("parent") or "") == key_of_parent]
        matched, left = self._match(mine, nodes, key_of_parent)
        recorded: list[dict[str, Any]] = []
        for index, node in enumerate(nodes):
            given = _given(node, index, key_of_parent)
            entry = matched[index]
            item = self.keyed.get(str(entry.get("key"))) if entry is not None else None
            if entry is None and not create:
                continue
            if entry is None:
                item = self._create(node, given, parent)
                key = item.seed_key
            else:
                key = str(entry["key"])
                if item is not None and not item.is_deleted and not self.edited(item, entry):
                    self._update(item, node, given, parent)
            recorded.append({"key": key, "parent": key_of_parent, "given": given})
            live = item is not None and not item.is_deleted
            recorded.extend(
                self.level(node.children, old, item if live else None, key, create=live)
            )
        for entry in left:
            recorded.extend(self._drop(entry, old))
        return recorded

    def _create(self, node: _Node, given: dict[str, Any], parent: Any | None) -> Any:
        from karni_site.models import MenuItem

        fields = {name: given[name] for name in ("title", "route", "route_kwargs", "url", "suffix")}
        item = MenuItem.objects.create(
            menu=self.menu,
            parent=parent,
            order=given["order"],
            children_from=node.rows,
            seed_key=uuid.uuid4().hex[:16],
            **fields,
        )
        self.keyed[item.seed_key] = item
        self.by_pk[item.pk] = item
        return item

    def _update(self, item: Any, node: _Node, given: dict[str, Any], parent: Any | None) -> None:
        before = self.values(item)
        for name in ("title", "route", "route_kwargs", "url", "suffix", "order"):
            setattr(item, name, given[name])
        item.children_from = node.rows
        item.parent = parent
        if self.values(item) != before:
            item.save()

    def _drop(self, entry: dict[str, Any], old: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """An entry whose link left the seed: its item goes unless someone kept it or a child."""
        item = self.keyed.get(str(entry.get("key")))
        children = [child for child in old if child.get("parent") == entry.get("key")]
        kept: list[dict[str, Any]] = []
        for child in children:
            kept.extend(self._drop(child, old))
        if item is None or item.is_deleted:
            return kept
        others = (
            type(item)
            .objects.filter(parent=item)
            .exclude(seed_key__in=[str(child.get("key")) for child in children])
        )
        if kept or self.edited(item, entry) or others.exists():
            return [{**entry, "given": None}, *kept]
        item.delete()
        return []


def _adopt(menu: Any, rows: list[Any]) -> list[dict[str, Any]]:
    """The entries of a menu seeded before seeds were followed, read from its items.

    The seed made its items in the same moment as the menu, so an item created
    within a second of it came from the seed. One never saved since is as the seed
    gave it, one saved since was changed by someone, and one deleted was deleted
    by someone: those two stay as they are.
    """
    from datetime import timedelta

    moment = timedelta(seconds=1)
    by_pk = {row.pk: row for row in rows}
    entries: list[dict[str, Any]] = []
    follow = _Follow(menu, {}, rows)
    seeded = [row for row in rows if abs(row.created_at - menu.created_at) <= moment]
    for row in seeded:
        if not row.seed_key:
            row.seed_key = uuid.uuid4().hex[:16]
            type(row).objects.without("soft_delete", reason=_EVERY_ITEM).filter(pk=row.pk).update(
                seed_key=row.seed_key
            )
    for row in seeded:
        parent = by_pk.get(row.parent_id) if row.parent_id else None
        untouched = not row.is_deleted and row.updated_at - row.created_at <= moment
        entries.append(
            {
                "key": row.seed_key,
                "parent": getattr(parent, "seed_key", "") if parent is not None else "",
                "given": follow.values(row) if untouched else None,
            }
        )
    return entries


def _content_type(label: str) -> Any | None:
    """The content type of the model ``"<app>.<Model>"``, or ``None`` when there is none."""
    if not label:
        return None
    from django.apps import apps
    from django.contrib.contenttypes.models import ContentType

    try:
        model = apps.get_model(label)
    except (LookupError, ValueError):
        return None
    return ContentType.objects.get_for_model(model)


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
