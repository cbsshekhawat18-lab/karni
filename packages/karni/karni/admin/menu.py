"""``KARNI_ADMIN_MENU``: the admin's side menu in groups the project names.

Without the setting the side menu is unfold's list of every app the user may
open, alphabetical. With it, the menu holds the groups as written::

    KARNI_ADMIN_MENU = [
        {"title": "Catalogue", "icon": "inventory_2", "items": ["shop"]},
        {"title": "Orders", "icon": "receipt_long", "items": ["sales.Order", "sales.Refund"]},
        {"title": "People", "icon": "group", "items": ["karni_accounts.User"]},
    ]

Each item is an app label (every model of the app, in the order of the
admin's home page), a model label (``app_label.ModelName``, in any case) or
``"@project"``, every app whose code lives in the project folder (the rule of
:func:`karni.testing._source.project_app_configs`). A model goes to the first
group that names it by its own label, else to the first that names its app,
else to the first ``"@project"``. A group's icon (a Material Symbols name)
marks each of its entries.

Each user sees the entries they may open (a role's grant or a Django
permission, :mod:`karni.admin.base`), and a group with none is left out.
Entries the menu does not name are hidden, except from superusers, who find
them in a last group, *Other*, by app. A label that names no installed app or
model is ``karni.W301``.

The admin's home page and the guide's *What each section is for* show the same
groups, in the same order, with the same entries (:func:`grouped_app_list`):
one grouping, :func:`_sections`, serves all three. Hiding an entry changes no
permission: its pages open for whoever may open them, as before.

``karni_settings()`` sets ``UNFOLD["SIDEBAR"]["navigation"]`` to
:func:`sidebar_navigation`, which unfold calls with the request, and
:func:`install` gives the site's home page the groups.

Override / escape hatch: ``KARNI_ADMIN_MENU = None`` (the default) keeps
unfold's app list and the home page's list of every app, and an
``UNFOLD["SIDEBAR"]`` of the project's own replaces Karni's menu entirely, on
the home page too (``karni.W302`` says so while ``KARNI_ADMIN_MENU`` is set).
``app_list`` in the index's ``extra_context`` wins over the grouped one.
karni-site's ``KARNI_SITE_ADMIN_MENU`` is the menu a site project starts with.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.html import escape
from django.utils.translation import gettext as _

__all__ = [
    "NAVIGATION",
    "PROJECT",
    "grouped_app_list",
    "in_use",
    "install",
    "menu_problems",
    "sidebar_navigation",
    "unknown_labels",
]

#: The item that stands for every app of the project (its code in the project folder).
PROJECT: Final = "@project"

#: What ``karni_settings()`` sets ``UNFOLD["SIDEBAR"]["navigation"]`` to (unfold imports it).
NAVIGATION: Final = "karni.admin.menu.sidebar_navigation"

_GROUP_KEYS: Final = frozenset({"title", "icon", "items"})
_INSTALLED: Final = "_karni_menu_installed"


@dataclass(frozen=True)
class _Entry:
    """One model of the admin's home page, as this user sees it."""

    app_label: str
    app_name: str
    app_url: str
    label: str  # "app_label.modelname"
    name: str
    url: str
    # The home page's own row for it (admin_url, add_url, view_only, perms, model).
    row: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class _Section:
    """One group of the menu as a user sees it: the side menu's, the home page's, the guide's."""

    title: str
    icon: str | None
    entries: tuple[_Entry, ...]
    other: bool = False  # superusers' last group: what the menu does not name


def menu_problems(value: Any) -> list[str]:
    """What is wrong with the shape of a ``KARNI_ADMIN_MENU`` value, one line each.

    ``None`` or a list of groups, each a mapping with a ``title`` (text), an
    optional ``icon`` (text) and ``items`` (a list of labels). Settings
    validation reports these at startup.
    """
    if value is None:
        return []
    example = '[{"title": "Content", "icon": "article", "items": ["blog", "shop.Product"]}]'
    if not isinstance(value, list | tuple):
        return [f"KARNI_ADMIN_MENU = {value!r} must be None or a list of groups, e.g. {example}"]
    problems: list[str] = []
    for index, group in enumerate(value):
        where = f"KARNI_ADMIN_MENU[{index}]"
        if not isinstance(group, Mapping):
            problems.append(f"{where} = {group!r} must be a mapping, e.g. {example}")
            continue
        extra = sorted(set(group) - _GROUP_KEYS)
        if extra:
            problems.append(f"{where} has keys {extra}, and a group takes title, icon and items")
        title = group.get("title")
        if not isinstance(title, str) or not title.strip():
            problems.append(f"{where} needs a title, the group's heading in the menu")
        icon = group.get("icon")
        if icon is not None and not isinstance(icon, str):
            problems.append(f"{where}['icon'] = {icon!r} must be a Material Symbols name")
        items = group.get("items")
        if (
            not isinstance(items, list | tuple)
            or not items
            or not all(isinstance(item, str) and item.strip() for item in items)
        ):
            problems.append(
                f"{where}['items'] = {items!r} must be a list of app labels, model labels "
                f"('app_label.ModelName') or {PROJECT!r}"
            )
    return problems


def unknown_labels(value: Any) -> list[str]:
    """The items of a ``KARNI_ADMIN_MENU`` that name no installed app or model."""
    from django.apps import apps

    if menu_problems(value) or not value:
        return []
    apps_installed = {config.label.lower() for config in apps.get_app_configs()}
    models_installed = {model._meta.label_lower for model in apps.get_models(include_swapped=True)}
    unknown: list[str] = []
    for group in value:
        for item in group["items"]:
            key = item.strip().lower()
            if key == PROJECT or key in apps_installed or key in models_installed:
                continue
            if item not in unknown:
                unknown.append(item)
    return unknown


def in_use() -> bool:
    """Whether ``KARNI_ADMIN_MENU`` shapes the admin: set, well formed, and the side menu Karni's.

    An ``UNFOLD["SIDEBAR"]`` navigation of the project's own replaces the menu,
    and then the home page keeps its list of every app too (``karni.W302``).
    """
    declared = getattr(settings, "KARNI_ADMIN_MENU", None)
    return bool(declared) and not menu_problems(declared) and karni_sidebar()


def karni_sidebar() -> bool:
    """Whether ``UNFOLD["SIDEBAR"]["navigation"]`` is Karni's menu, not one of the project's own."""
    unfold = getattr(settings, "UNFOLD", None)
    sidebar = unfold.get("SIDEBAR") if isinstance(unfold, Mapping) else None
    navigation = sidebar.get("navigation") if isinstance(sidebar, Mapping) else None
    return navigation in (NAVIGATION, sidebar_navigation)


def _entries(app_list: list[dict[str, Any]]) -> list[_Entry]:
    """The entries of the home page this user may open, in its order.

    Models, and screens shaped like one (Karni's *API cache*), keyed by
    ``app_label.object_name`` in lower case.
    """
    found: list[_Entry] = []
    for app in app_list:
        for entry in app.get("models", ()):
            model = entry.get("model")
            url = entry.get("admin_url")
            name = model.__name__ if model is not None else entry.get("object_name")
            if not url or not name:
                continue
            found.append(
                _Entry(
                    app_label=app["app_label"],
                    app_name=str(app["name"]),
                    app_url=str(app.get("app_url", "")),
                    label=f"{app['app_label']}.{name}".lower(),
                    name=str(entry["name"]),
                    url=str(url),
                    row=entry,
                )
            )
    return found


def _project_apps() -> frozenset[str]:
    from karni.testing._source import project_app_configs

    return frozenset(config.label for config in project_app_configs(skip_apps=False))


def _place(groups: list[Mapping[str, Any]], entries: list[_Entry]) -> list[list[_Entry]]:
    """Each group's entries, in the order its items are written.

    A model goes to the first group that names it by its own label, else to
    the first group that names its app, else to the first ``@project``. An app
    label and ``@project`` list their models in the home page's order.
    """
    labels = [[str(item).strip().lower() for item in group["items"]] for group in groups]
    owner: dict[str, int] = {}  # a model label or an app label -> the first group naming it
    for index, items in enumerate(labels):
        for item in items:
            owner.setdefault(item, index)
    project = _project_apps() if any(PROJECT in items for items in labels) else frozenset()

    def home(entry: _Entry) -> tuple[int, str] | None:
        """The group that takes ``entry`` and the item it comes under there."""
        if entry.label in owner:
            return owner[entry.label], entry.label
        app = entry.app_label.lower()
        if app in owner:
            return owner[app], app
        if PROJECT in owner and entry.app_label in project:
            return owner[PROJECT], PROJECT
        return None

    homes = {entry.label: home(entry) for entry in entries}
    placed: list[list[_Entry]] = []
    for index, items in enumerate(labels):
        mine: list[_Entry] = []
        for item in dict.fromkeys(items):
            mine.extend(entry for entry in entries if homes[entry.label] == (index, item))
        placed.append(mine)
    return placed


def _item(entry: _Entry, icon: str | None) -> dict[str, Any]:
    item: dict[str, Any] = {"title": escape(entry.name), "link": entry.url}
    if icon:
        item["icon"] = icon
    return item


def _other(entries: list[_Entry]) -> dict[str, Any] | None:
    """Superusers' last group: each app the menu leaves out, with its models."""
    apps: dict[str, list[_Entry]] = {}
    for entry in entries:
        apps.setdefault(entry.app_label, []).append(entry)
    items = []
    for app_entries in apps.values():
        first = app_entries[0]
        items.append(
            {
                "title": escape(first.app_name),
                "link": first.app_url or first.url,
                "items": [_item(entry, None) for entry in app_entries],
            }
        )
    if not items:
        return None
    return {"title": _("Other"), "collapsible": True, "items": items}


def _sections(request: HttpRequest, app_list: list[dict[str, Any]]) -> list[_Section]:
    """``KARNI_ADMIN_MENU``'s groups as this user sees them, from the home page's ``app_list``.

    Each group holds the entries the user may open, in the order written, and
    a group without one is left out. Superusers get the rest in a last group,
    *Other*. The side menu, the home page and the guide all read this.
    """
    declared = getattr(settings, "KARNI_ADMIN_MENU", None)
    if not declared or menu_problems(declared):
        return []
    entries = _entries(app_list)
    groups = list(declared)
    sections: list[_Section] = []
    shown: set[str] = set()
    for group, placed in zip(groups, _place(groups, entries), strict=True):
        if not placed:
            continue
        shown.update(entry.label for entry in placed)
        sections.append(_Section(group["title"], group.get("icon"), tuple(placed)))
    user = getattr(request, "user", None)
    rest = tuple(entry for entry in entries if entry.label not in shown)
    if getattr(user, "is_superuser", False) and rest:
        sections.append(_Section(_("Other"), None, rest, other=True))
    return sections


def sidebar_navigation(request: HttpRequest) -> list[dict[str, Any]]:
    """``UNFOLD["SIDEBAR"]["navigation"]``: ``KARNI_ADMIN_MENU``'s groups for this user.

    ``[]`` without the setting, which keeps unfold's app list. The groups are
    :func:`_sections`, the ones the home page shows.
    """
    from karni.scoping import admin_site

    if not getattr(settings, "KARNI_ADMIN_MENU", None):
        return []
    navigation: list[dict[str, Any]] = []
    for section in _sections(request, admin_site().get_app_list(request)):
        if section.other:
            other = _other(list(section.entries))
            if other is not None:
                navigation.append(other)
            continue
        navigation.append(
            {
                "title": section.title,
                "items": [_item(entry, section.icon) for entry in section.entries],
            }
        )
    return navigation


def grouped_app_list(request: HttpRequest, app_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The home page's ``app_list`` in the side menu's groups, for this user.

    Each group is shaped like an app of models (``name``, ``app_label``,
    ``app_url``, ``models``), its rows the home page's own rows, so the page and
    the guide render it unchanged. A row of *Other* names its app first. While
    the menu is not in use (:func:`in_use`) ``app_list`` comes back as it is.
    """
    if not in_use():
        return app_list
    grouped: list[dict[str, Any]] = []
    for index, section in enumerate(_sections(request, app_list)):
        first = section.entries[0]
        one_app = all(entry.app_label == first.app_label for entry in section.entries)
        rows = [dict(entry.row) for entry in section.entries]
        if section.other:
            for row, entry in zip(rows, section.entries, strict=True):
                row["name"] = _("%(app)s › %(model)s") % {
                    "app": entry.app_name,
                    "model": entry.name,
                }
        grouped.append(
            {
                "name": section.title,
                "app_label": first.app_label if one_app else f"karni_menu_{index}",
                "app_url": (first.app_url or first.url) if one_app else first.url,
                "has_module_perms": True,
                "models": rows,
            }
        )
    return grouped


def install(site: Any) -> None:
    """Give ``site``'s home page the menu's groups (:func:`grouped_app_list`). Idempotent.

    Call it before the URLconf reads ``site.urls`` (an ``AppConfig.ready``).
    """
    if getattr(site, _INSTALLED, False):
        return
    setattr(site, _INSTALLED, True)
    index: Callable[..., HttpResponse] = site.index

    def index_in_groups(
        request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        extra = dict(extra_context or {})
        if "app_list" not in extra and in_use():
            extra["app_list"] = grouped_app_list(request, site.get_app_list(request))
        return index(request, extra)

    site.index = index_in_groups
