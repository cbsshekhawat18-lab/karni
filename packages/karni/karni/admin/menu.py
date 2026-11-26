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

Each user sees the entries they may open, the same ones the home page lists
(a role's grant or a Django permission, :mod:`karni.admin.base`), and a group
with none is left out. Entries the menu does not name are hidden, except from
superusers, who find them in a last group, *Other*, by app. A label that names
no installed app or model is ``karni.W301``.

``karni_settings()`` sets ``UNFOLD["SIDEBAR"]["navigation"]`` to
:func:`sidebar_navigation`, which unfold calls with the request.

Override / escape hatch: ``KARNI_ADMIN_MENU = None`` (the default) keeps
unfold's app list, and an ``UNFOLD["SIDEBAR"]`` of the project's own replaces
Karni's menu entirely (``karni.W302`` says so while ``KARNI_ADMIN_MENU`` is
set). karni-site's ``KARNI_SITE_ADMIN_MENU`` is the menu a site project starts
with.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from django.conf import settings
from django.http import HttpRequest
from django.utils.html import escape
from django.utils.translation import gettext as _

__all__ = ["NAVIGATION", "PROJECT", "menu_problems", "sidebar_navigation", "unknown_labels"]

#: The item that stands for every app of the project (its code in the project folder).
PROJECT: Final = "@project"

#: What ``karni_settings()`` sets ``UNFOLD["SIDEBAR"]["navigation"]`` to (unfold imports it).
NAVIGATION: Final = "karni.admin.menu.sidebar_navigation"

_GROUP_KEYS: Final = frozenset({"title", "icon", "items"})


@dataclass(frozen=True)
class _Entry:
    """One model of the admin's home page, as this user sees it."""

    app_label: str
    app_name: str
    app_url: str
    label: str  # "app_label.modelname"
    name: str
    url: str


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


def _entries(site: Any, request: HttpRequest) -> list[_Entry]:
    """The entries of the home page this user may open, in its order.

    Models, and screens shaped like one (Karni's *API cache*), keyed by
    ``app_label.object_name`` in lower case.
    """
    found: list[_Entry] = []
    for app in site.get_app_list(request):
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


def sidebar_navigation(request: HttpRequest) -> list[dict[str, Any]]:
    """``UNFOLD["SIDEBAR"]["navigation"]``: ``KARNI_ADMIN_MENU``'s groups for this user.

    ``[]`` without the setting, which keeps unfold's app list. Each group holds
    the entries the user may open, in the order written, and a group without
    one is left out. Superusers get the rest in a last group, *Other*.
    """
    declared = getattr(settings, "KARNI_ADMIN_MENU", None)
    if not declared or menu_problems(declared):
        return []
    from karni.scoping import admin_site

    entries = _entries(admin_site(), request)
    groups = list(declared)
    navigation: list[dict[str, Any]] = []
    shown: set[str] = set()
    for group, placed in zip(groups, _place(groups, entries), strict=True):
        if not placed:
            continue
        shown.update(entry.label for entry in placed)
        navigation.append(
            {
                "title": group["title"],
                "items": [_item(entry, group.get("icon")) for entry in placed],
            }
        )
    user = getattr(request, "user", None)
    if getattr(user, "is_superuser", False):
        other = _other([entry for entry in entries if entry.label not in shown])
        if other is not None:
            navigation.append(other)
    return navigation
