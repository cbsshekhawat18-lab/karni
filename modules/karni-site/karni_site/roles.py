"""The content editor role this module declares (the ``karni.roles`` entry point).

An editor changes what visitors read and nothing else: the site's details,
the page content, the menus and each page's title and description. They
have no grant on enquiries, users, roles, redirects or any project model, so
the admin shows them none of those. Give a person staff status and the role.
Karni's admin pages open for whoever the roles' grants admit
(:meth:`karni.admin.base.KarniAdminMixin.granted`), so no Django permission
needs ticking.

Override / escape hatch: ``KARNI_SITE_EDITOR_ROLE`` names the slug (``None``
declares no role), a role of the same slug in ``KARNI_ROLES`` replaces this
one, and the permission matrix changes its grants without a deploy.
"""

from __future__ import annotations

from typing import Any

__all__ = ["declared", "editor_grants"]


def editor_grants() -> dict[str, str]:
    """The editor's grants: the content models, every row."""
    from karni_site.sitesettings import settings_model

    settings = settings_model()._meta
    label = f"{settings.app_label}.{settings.model_name}"
    return {
        f"{label}:view": "all",
        f"{label}:add": "all",  # the one row, when no template has stored it yet
        f"{label}:change": "all",
        "karni_site.openinghours:*": "all",
        "karni_site.sociallink:*": "all",
        "karni_site.block:view": "all",
        "karni_site.block:change": "all",
        "karni_site.menu:*": "all",
        "karni_site.menuitem:*": "all",
        "karni_site.pageseo:*": "all",
    }


def declared() -> dict[str, Any]:
    """``{slug: spec}`` for ``KARNI_ROLES``' merge, or ``{}`` when the app is not installed."""
    from django.apps import apps

    from karni_site import conf

    slug = conf.get("KARNI_SITE_EDITOR_ROLE")
    if not slug or not apps.ready or not apps.is_installed("karni_site"):
        return {}
    return {
        str(slug): {
            "name": "Editor",
            "description": (
                "Changes the public site's text, images, menus, page titles and contact "
                "details. No enquiries, users or settings."
            ),
            "grants": editor_grants(),
        }
    }
