"""Experimental. ``navigation:`` of ``karni.yaml``: the menu ``karni build`` writes to ``KARNI_NAVIGATION``.

``navigation: true`` is every page of ``pages`` that has a route of its own,
in the order ``pages`` lists them (a sign-in page and an entity without a
``list`` page are left out). A list says the order and the groups::

    navigation:
      - home
      - Catalog: [Product, Category]          # a group: a label and its entries
      - Region: {icon: map}                   # a page, with options
      - Reports: {icon: bar-chart, items: [sales, stock]}

An entry is a page of ``pages`` (its key: ``Product``, ``shop.Product``,
``home`` or ``shop.reports``, a code page under the app's route), a one-key
mapping from a page to its options (``label``, ``icon``, ``requires``), or a
one-key mapping from a group's label to its entries (a list, or ``{items,
icon, requires}``). A key that names a page is the page. A family page the
project's modules provide (``orders`` with commerce, ``settings`` with
preferences) may be named without being listed in ``pages``.

Each page's requirement comes from its access, the way the API reads it:
``public`` reads stay ``public``, ``authenticated`` and ``owned:`` reads are
``authenticated``, and ``granted`` or a role is the entity's view
permission (``shop.product:view``), so role grants and per-user grants open
it. A named page is ``authenticated``, and a sign-in page ``public``. A
group is ``public`` when one of its entries is, else ``authenticated``.
``requires`` replaces any of them.

:func:`menu` gives the ``KARNI_NAVIGATION`` list (``None`` without
``navigation``), :func:`summary` the line ``karni plan`` prints, and
:func:`entries_from_setting` the ``navigation:`` of a project's setting
(``karni spec export``).

Named menus: a mapping of a menu's name to such a list writes the named
menus (``GET /api/navigation/?menu=``)::

    navigation:
      app: [orders, Product]                 # the back office's sidebar
      public: [{shop.catalogue: {label: Products, requires: public}}]   # the site's header
      account: [orders]                      # the signed-in person's own links

A list is the ``app`` menu alone, and builds the same setting as before.

Override / escape hatch: leave ``navigation`` out and write
``KARNI_NAVIGATION`` (or ``"db"``) below the spec block in the settings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from karni_cli.generators.naming import default_route, humanize
from karni_cli.spec import schema

__all__ = [
    "APP_MENU",
    "FAMILY_PROVIDERS",
    "SETTING",
    "Page",
    "entries_from_setting",
    "family_pages",
    "known_pages",
    "menu",
    "menus",
    "pages",
    "people_label",
    "provided",
    "requirement_problem",
    "sells_alone",
    "summary",
]

#: The setting ``karni build`` writes the menu to.
SETTING: Final = "KARNI_NAVIGATION"
#: The menu a list is: the back office's sidebar.
APP_MENU: Final = "app"
PUBLIC: Final = "public"
AUTHENTICATED: Final = "authenticated"
ICON_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")
LABEL_MAX: Final = 100


@dataclass(frozen=True)
class Page:
    """Experimental. A page of ``pages`` that a menu entry can name."""

    key: str
    route: str | None
    label: str
    requires: str
    kind: str


def _entity_requirement(app: str, name: str, entity: schema.Entity) -> str:
    view = f"{app}.{name.lower()}:view"
    if entity.access == "code":
        return view
    read = entity.access.read
    if PUBLIC in read:
        return PUBLIC
    if AUTHENTICATED in read or any(rule.startswith("owned:") for rule in read):
        return AUTHENTICATED
    return view


def _entity(spec: schema.Spec, ref: str) -> tuple[str, str, schema.Entity] | None:
    if "." in ref:
        app, _, name = ref.partition(".")
        entity = spec.apps.get(app, schema.App()).entities.get(name)
        return (app, name, entity) if entity is not None else None
    found = [
        (app, ref, block.entities[ref]) for app, block in spec.apps.items() if ref in block.entities
    ]
    return found[0] if len(found) == 1 else None


#: Experimental. The family pages a menu may name without listing them in ``pages``, each
#: with what provides it: a module (``modules.commerce``), a contract (``features.people``)
#: or Karni itself (``""``). They belong to Karni and its contracts, never to a part.
FAMILY_PROVIDERS: Final[dict[str, str]] = {
    "home": "",
    "signin": "",
    "account": "",
    "search": "",
    "inbox": "features.notify",
    "people": "features.people",
    "settings": "features.preferences",
    "cart": "modules.commerce",
    "checkout": "modules.commerce",
    "orders": "modules.commerce",
}


def provided(spec: schema.Spec, provider: str) -> bool:
    """Experimental. Whether ``provider`` (``modules.commerce``, ``features.people``, ``""``)
    is installed in ``spec``."""
    group, _dot, name = provider.partition(".")
    if group == "modules":
        return name in spec.modules
    if group == "features":
        return bool(getattr(spec.features, name, False))
    return True


def sells_alone(spec: schema.Spec) -> bool:
    """Experimental. The project holds one part, and it sells (commerce is installed): a shop
    alone. Its people are its customers."""
    return len(spec.app.recipes) == 1 and "commerce" in spec.modules


def people_label(spec: schema.Spec) -> str:
    """Experimental. What the family's people list is called: ``Customers`` in a project whose
    only part sells, else ``People``."""
    return "Customers" if sells_alone(spec) else "People"


def family_pages(spec: schema.Spec) -> dict[str, Page]:
    """Experimental. The family pages this spec's modules and contracts provide, by name."""
    from karni_cli.recipes.compose import FAMILY_PAGES

    found: dict[str, Page] = {}
    for name, provider in FAMILY_PROVIDERS.items():
        if not provided(spec, provider):
            continue
        label = people_label(spec) if name == "people" else humanize(name)
        requires = PUBLIC if name == "signin" else AUTHENTICATED
        found[name] = Page(name, FAMILY_PAGES[name], label, requires, "family")
    return found


def known_pages(spec: schema.Spec) -> dict[str, Page]:
    """Experimental. The pages a menu entry may name: the family pages the project's
    modules and contracts provide (:func:`family_pages`: ``orders`` with commerce,
    ``settings`` with preferences), then every page of ``pages`` (:func:`pages`)."""
    return {**family_pages(spec), **pages(spec)}


def pages(spec: schema.Spec) -> dict[str, Page]:
    """Experimental. Every page of ``pages`` by its key, with its route, label and requirement.

    ``route`` is ``None`` for an entity without a ``list`` page (its pages
    take an id). A key that names no entity of the spec is left out.
    """
    found: dict[str, Page] = {}
    for item in spec.pages:
        for key, kinds in item.items():
            label, dot, rest = key.partition(".")
            if dot and rest[:1].islower():  # <app>.<name>: a code page under the app's route
                owner = spec.apps.get(label)
                base = (owner.route if owner is not None else None) or f"/{label}"
                found[key] = Page(key, f"{base}/{rest}", humanize(rest), AUTHENTICATED, "code")
                continue
            if key[:1].isupper() or "." in key:
                resolved = _entity(spec, key)
                if resolved is None:
                    continue
                app, name, entity = resolved
                base = default_route(name)
                prefix = spec.apps[app].route or "" if app in spec.apps else ""
                found[key] = Page(
                    key,
                    f"{prefix}/{base}" if "list" in kinds else None,
                    humanize(base),
                    _entity_requirement(app, name, entity),
                    "list",
                )
                continue
            first = kinds[0] if kinds else "blank"
            kind = first if isinstance(first, str) else "blank"  # a detail page with options
            found[key] = Page(
                key,
                "/"
                if kind == "dashboard" and key == "home"
                else f"/{key}",  # a named dashboard is /<name>
                humanize(key),
                PUBLIC if kind == "login" else AUTHENTICATED,
                kind,
            )
    return found


def requirement_problem(value: str) -> str | None:
    """Experimental. Why ``value`` is not a requirement (``None`` when it is one)."""
    if value in (PUBLIC, AUTHENTICATED, "*"):
        return None
    label, sep, action = value.rpartition(":")
    if not sep or not label or not action or any(ch.isspace() for ch in value):
        return (
            f"{value!r} is not a requirement: write public, authenticated or a permission "
            "pattern as in grants (app.entity:action, with * for a part)"
        )
    return None


def _group_requirement(children: list[dict[str, Any]]) -> str:
    return PUBLIC if any(child["requires"] == PUBLIC for child in children) else AUTHENTICATED


def _item(page: Page, options: schema.NavigationOptions | None) -> dict[str, Any]:
    found: dict[str, Any] = {"label": page.label, "route": page.route}
    if options is not None and options.label:
        found["label"] = options.label
    if options is not None and options.icon:
        found["icon"] = options.icon
    found["requires"] = options.requires if options and options.requires else page.requires
    return found


def _group(
    label: str, entries: list[Any], options: schema.NavigationOptions | None, known: dict[str, Page]
) -> dict[str, Any]:
    built = [_entry(entry, known) for entry in entries]
    children = [child for child in built if child is not None]
    found: dict[str, Any] = {"label": label}
    if options is not None and options.icon:
        found["icon"] = options.icon
    found["requires"] = (
        options.requires if options and options.requires else _group_requirement(children)
    )
    found["children"] = children
    return found


def _entry(entry: Any, known: dict[str, Page]) -> dict[str, Any] | None:
    if isinstance(entry, str):
        page = known.get(entry)
        return _item(page, None) if page is not None and page.route else None
    ((key, value),) = entry.items()
    page = known.get(key)
    if page is not None:
        options = value if isinstance(value, schema.NavigationOptions) else None
        return _item(page, options) if page.route else None
    if isinstance(value, schema.NavigationOptions):
        return _group(key, value.items or [], value, known)
    return _group(key, value, None, known)


def menus(spec: schema.Spec) -> dict[str, list[Any]]:
    """Experimental. The entries of each menu ``navigation:`` names: a list is ``app``."""
    if isinstance(spec.navigation, bool):
        return {}
    if isinstance(spec.navigation, dict):
        return dict(spec.navigation)
    return {APP_MENU: list(spec.navigation)}


def _built(entries: list[Any], known: dict[str, Page]) -> list[dict[str, Any]]:
    found = [_entry(entry, known) for entry in entries]
    return [item for item in found if item is not None]


def menu(spec: schema.Spec) -> list[dict[str, Any]] | dict[str, list[dict[str, Any]]] | None:
    """Experimental. The ``KARNI_NAVIGATION`` value of ``spec``, or ``None`` without ``navigation``.

    A list for the ``app`` menu alone (``true`` or a list), a mapping of named
    menus for ``navigation: {app: [...], public: [...]}``.
    """
    if spec.navigation is False:
        return None
    if spec.navigation is True:
        listed = pages(spec).values()
        return [_item(page, None) for page in listed if page.route and page.kind != "login"]
    known = known_pages(spec)
    if isinstance(spec.navigation, dict):
        return {name: _built(entries, known) for name, entries in spec.navigation.items()}
    return _built(spec.navigation, known)


def summary(items: list[dict[str, Any]] | dict[str, list[dict[str, Any]]] | None) -> str:
    """Experimental. ``Home /, Catalog (Products /products, Categories /categories)``, and for
    named menus ``app: ...; public: ...``."""

    def show(item: dict[str, Any]) -> str:
        if item.get("route") is not None:
            return f"{item['label']} {item['route']}"
        inner = ", ".join(show(child) for child in item.get("children") or [])
        return f"{item['label']} ({inner})"

    if isinstance(items, dict):
        return "; ".join(
            f"{name}: {', '.join(show(item) for item in entries)}"
            for name, entries in items.items()
        )
    return ", ".join(show(item) for item in items or [])


def entries_from_setting(
    value: Any, known: dict[str, Page], left_out: list[str]
) -> list[Any] | dict[str, list[Any]] | None:
    """Experimental. The ``navigation:`` entries a ``KARNI_NAVIGATION`` value writes, or ``None``.

    An item becomes the page whose route it links to, with the options where
    it differs from the page's defaults. A group keeps its label. What the
    spec cannot say (``"db"``, a route no page of the spec has, a page's
    second entry, a group labelled like a page) is added to ``left_out`` and
    skipped. Named menus give a mapping of each menu's entries.
    """
    if value is None:
        return None
    if value == "db":
        left_out.append(
            f"navigation: {SETTING} = 'db', a menu the admin edits (it stays in the settings)"
        )
        return None
    if isinstance(value, dict):
        named: dict[str, list[Any]] = {}
        for name, items in value.items():
            found = _entries_of(items, known, left_out)
            if found is not None:
                named[str(name)] = found
        return named
    return _entries_of(value, known, left_out)


def _entries_of(value: Any, known: dict[str, Page], left_out: list[str]) -> list[Any] | None:
    if not isinstance(value, list):
        return None
    by_route = {page.route: page for page in known.values() if page.route}
    seen: set[str] = set()

    def ordered(items: list[Any]) -> list[dict[str, Any]]:
        valid = [item for item in items if isinstance(item, dict)]
        ranked = sorted(enumerate(valid), key=lambda pair: (pair[1].get("order", 0), pair[0]))
        return [item for _index, item in ranked]

    def convert(item: dict[str, Any]) -> tuple[Any, dict[str, Any]] | None:
        label = str(item.get("label", ""))
        icon = item.get("icon") or None
        requires = item.get("requires", AUTHENTICATED)
        if item.get("route") is not None:
            page = by_route.get(item["route"])
            if page is None:
                left_out.append(
                    f"navigation: {label} at {item['route']}, a route no page of the spec has"
                )
                return None
            if page.key in seen:
                left_out.append(f"navigation: {label} at {item['route']}, a second entry for it")
                return None
            seen.add(page.key)
            options: dict[str, Any] = {}
            if label != page.label:
                options["label"] = label
            if icon:
                options["icon"] = icon
            if requires != page.requires:
                options["requires"] = requires
            written = {"label": label, "route": page.route, "requires": requires}
            return ({page.key: options} if options else page.key), written
        if label in known:
            left_out.append(f"navigation: the group {label}, whose label names a page")
            return None
        converted = [found for found in map(convert, ordered(item.get("children") or [])) if found]
        if not converted:
            left_out.append(f"navigation: the group {label}, with no entry the spec can name")
            return None
        children = [written for _entry_, written in converted]
        entries = [entry_ for entry_, _written in converted]
        group: dict[str, Any] = {}
        if icon:
            group["icon"] = icon
        if requires != _group_requirement(children):
            group["requires"] = requires
        if group:
            return {label: {**group, "items": entries}}, {"requires": requires}
        return {label: entries}, {"requires": requires}

    out = [found[0] for found in map(convert, ordered(value)) if found is not None]
    return out
