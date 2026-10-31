"""Experimental. The database menu in the admin: the ``NavItem`` tree, and a preview per user.

``NavItemAdmin`` lists the entries in tree order, each label indented by its
depth (the tree changelist of :mod:`karni.admin.tree`), and edits them like
any row: label, route, icon, requirement, parent and position. Every change
is history.

*Menu preview* (a changelist button, ``admin:karni_navigation_navitem_menu_preview``,
``preview/``) shows the menu one user gets: ``?user=<email or id>``, or
``?visitor=1`` for someone who is not signed in. It is
:func:`karni.navigation.menu_for`, so it is exactly what ``GET
/api/navigation/`` answers that user, with each entry's requirement next to
it. Previewing another user's menu shows what they may do, so it needs what
*Effective permissions* needs: the permission matrix's ``view``.

Override / escape hatch: register your own admin for ``NavItem`` first
(``admin.site.unregister(NavItem)`` then ``admin.site.register(...)``), or
subclass :class:`NavItemAdmin`.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _

from karni import navigation
from karni.accounts.admin import _fallback_urls, _unfold_action
from karni.admin import KarniModelAdmin
from karni.imports import import_setting
from karni.navigation.models import NavItem

__all__ = ["NavItemAdmin", "preview_view"]

action = _unfold_action()


def _entries(nodes: list[navigation.NavNode]) -> list[dict[str, Any]]:
    return [
        {
            "label": node.label,
            "route": node.route,
            "icon": node.icon,
            "requires": node.requires,
            "children": _entries(list(node.children)),
        }
        for node in nodes
    ]


def preview_view(model_admin: Any, request: HttpRequest) -> HttpResponse:
    """The menu one user sees. ``?user=<email or id>`` picks them, ``?visitor=1`` a visitor."""
    from karni.accounts.matrix import MATRIX_PERMISSION
    from karni.accounts.matrix_admin import _find_user
    from karni.accounts.roles import user_can

    viewer = request.user
    query = request.GET.get("user", "").strip()
    visitor = request.GET.get("visitor") == "1"
    subject: Any = None
    if visitor:
        subject = AnonymousUser()
    elif query:
        subject = _find_user(query)
        if subject is None:
            messages.error(request, _("No user matches %(query)s.") % {"query": query})
    if (
        subject is not None
        and not visitor
        and subject.pk != viewer.pk
        and not user_can(viewer, f"{MATRIX_PERMISSION}:view")
    ):
        raise PermissionDenied
    menu = navigation.menu_for(subject) if subject is not None else None
    context = {
        **model_admin.admin_site.each_context(request),
        "model_admin": model_admin,
        "opts": model_admin.model._meta,
        "title": _("Menu preview"),
        "query": query,
        "visitor": visitor,
        "subject": subject,
        "source": navigation.source(),
        "entries": _entries(menu) if menu is not None else None,
    }
    return TemplateResponse(request, "karni_navigation/menu_preview.html", context)


class NavItemAdmin(KarniModelAdmin):
    """Experimental. The menu's entries in tree order, with the *Menu preview* button."""

    list_display = ("tree_label", "route", "requires", "icon")
    search_fields = ("label", "route", "requires")
    fields = ("label", "route", "icon", "requires", "parent", "position")
    actions_list = ["menu_preview"]

    @action(
        description="Menu preview",
        url_path="preview",
        permissions=["view"],
        icon="visibility",
    )
    def menu_preview(self, request: HttpRequest) -> HttpResponse:
        """Pick a user, see the menu they get and what each entry requires."""
        return preview_view(self, request)

    def get_urls(self) -> Any:
        return [*_fallback_urls(self, list_actions=("menu_preview",)), *super().get_urls()]


_site: admin.AdminSite = import_setting(
    "KARNI_ADMIN_SITE", getattr(settings, "KARNI_ADMIN_SITE", "django.contrib.admin.site")
)
if not _site.is_registered(NavItem):
    _site.register(NavItem, NavItemAdmin)
