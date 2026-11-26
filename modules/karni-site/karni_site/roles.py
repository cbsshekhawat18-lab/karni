"""The content editor role this module declares (the ``karni.roles`` entry point).

An editor changes what visitors read and nothing else: the site's details,
the page content, the menus and each page's title and description. They
have no grant on enquiries, users, roles, redirects or any project model, so
the admin shows them none of those. Give a person staff status and the role.
Karni's admin pages open for whoever the roles' grants admit
(:meth:`karni.admin.base.KarniAdminMixin.granted`), so no Django permission
needs ticking.

``KARNI_SITE_EDITOR_GRANTS`` adds grants to the role, merged over the
module's own (:func:`editor_grants`): ``{"website.article:*": "all"}`` lets an
editor change the project's articles too. It is plain data, so settings.py
sets it with nothing imported, and it is read here, when the role is built
(after the apps are ready). A grant is a pattern, ``"app_label.model:action"``
(the actions a model has: ``view``, ``add``, ``change``, ``delete`` and its
``class Karni: actions``, ``*`` for either part), and a scope (``"all"``,
``"own"``, ``"related:<key>"``, ``"custom:<name>"``, ``"tree:<path>"``), as in
``KARNI_ROLES``. An entry the role cannot grant (a model or an action the
project does not have, a scope the model cannot carry) is left out of the
role, so the sync after ``migrate`` never fails on it, and ``karni check``
names it (``SITE026``).

Override / escape hatch: ``KARNI_SITE_EDITOR_ROLE`` names the slug (``None``
declares no role), a role of the same slug in ``KARNI_ROLES`` replaces this
one with its grants and ``KARNI_SITE_EDITOR_GRANTS`` both, and the permission
matrix changes its grants without a deploy.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from difflib import get_close_matches
from fnmatch import fnmatchcase
from typing import Any

__all__ = ["check_grants", "declared", "editor_grants", "extra_grants", "grant_problems"]

logger = logging.getLogger("karni_site")
SETTING = "KARNI_SITE_EDITOR_GRANTS"
CODE = "SITE026"


def editor_grants() -> dict[str, str]:
    """The editor's own grants: the content models, every row.

    It reads the site's settings model, so it is called once the apps are
    ready, never while settings load: ``KARNI_SITE_EDITOR_GRANTS`` adds to it.
    """
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


def extra_grants() -> dict[str, str]:
    """``KARNI_SITE_EDITOR_GRANTS`` as written, ``{}`` when it is not a dict (``SITE026``)."""
    from karni_site import conf

    value = conf.get(SETTING) or {}
    if not isinstance(value, Mapping):
        return {}
    return {str(pattern): str(scope) for pattern, scope in value.items()}


def _unknown(pattern: str, keys: Mapping[str, Any]) -> str:
    """Why ``pattern`` matches no permission: no such model, or no such action."""
    label, _, action = ("*:*" if pattern == "*" else pattern).partition(":")
    labels = sorted({key.split(":", 1)[0] for key in keys})
    models = [known for known in labels if fnmatchcase(known, label)]
    if not models:
        close = get_close_matches(label, labels, n=3)
        hint = f" Did you mean {' or '.join(repr(c) for c in close)}?" if close else ""
        return f"no installed model is {label!r} (a model label is 'app_label.model').{hint}"
    actions = sorted({key.split(":", 1)[1] for key in keys if key.split(":", 1)[0] in models})
    return f"{', '.join(models)} has no action {action!r}. Its actions: {', '.join(actions)}."


def grant_problems(grants: Mapping[str, str] | None = None) -> dict[str, str]:
    """``{pattern: why}`` for each grant the editor role cannot give, checked as the sync will."""
    from karni.accounts.roles import declared_roles, expand_grants, permission_keys
    from karni.exceptions import KarniError

    from karni_site import conf

    grants = extra_grants() if grants is None else grants
    slug = str(conf.get("KARNI_SITE_EDITOR_ROLE") or "editor")
    keys = permission_keys()
    found: dict[str, str] = {}
    for pattern, scope in grants.items():
        try:
            (spec,) = declared_roles({slug: {"grants": {pattern: scope}}})
            expand_grants(spec, keys)
        except KarniError as exc:
            message = exc.message
            if "matches no permission" in message:
                found[pattern] = _unknown(pattern, keys)
            else:  # the message names KARNI_ROLES, where the probe role was declared
                found[pattern] = message.split("]: ", 1)[-1].removeprefix("KARNI_ROLES: ")
    return found


def declared() -> dict[str, Any]:
    """``{slug: spec}`` for ``KARNI_ROLES``' merge, or ``{}`` when the app is not installed.

    The grants are :func:`editor_grants` with ``KARNI_SITE_EDITOR_GRANTS`` merged over
    them, less the entries the role cannot give (:func:`grant_problems`), which are logged.
    """
    from django.apps import apps

    from karni_site import conf

    slug = conf.get("KARNI_SITE_EDITOR_ROLE")
    if not slug or not apps.ready or not apps.is_installed("karni_site"):
        return {}
    grants = editor_grants()
    extra = extra_grants()
    if extra:
        problems = grant_problems(extra)
        for pattern, why in problems.items():
            logger.warning(
                "karni_site: %s[%r] is left out of the %s role: %s (%s)",
                SETTING,
                pattern,
                slug,
                why,
                CODE,
            )
        grants |= {pattern: scope for pattern, scope in extra.items() if pattern not in problems}
    return {
        str(slug): {
            "name": "Editor",
            "description": (
                "Changes the public site's text, images, menus, page titles and contact "
                "details. No enquiries, users or settings."
            ),
            "grants": grants,
        }
    }


def check_grants() -> list[str]:
    """``SITE026``: ``KARNI_SITE_EDITOR_GRANTS`` names what the role cannot grant, or is unused."""
    from django.conf import settings

    from karni_site import conf

    value = conf.get(SETTING)
    if not value:
        return []
    if not isinstance(value, Mapping):
        return [
            f"{CODE}: {SETTING} is a {type(value).__name__}. It is a dict of "
            "'app_label.model:action' -> scope: {'website.article:*': 'all'}."
        ]
    slug = conf.get("KARNI_SITE_EDITOR_ROLE")
    if not slug:
        return [
            f"{CODE}: {SETTING} is set, but KARNI_SITE_EDITOR_ROLE is None, so there is no editor "
            f"role to add the grants to. Remove {SETTING}, or name the role."
        ]
    roles = getattr(settings, "KARNI_ROLES", None) or {}
    if isinstance(roles, Mapping) and slug in roles:
        return [
            f"{CODE}: {SETTING} is set, but KARNI_ROLES names the {slug!r} role, which replaces "
            f"the module's role with its own grants, so {SETTING} adds nothing. Put the grants "
            f"in KARNI_ROLES[{slug!r}], or remove {slug!r} from KARNI_ROLES to use the module's "
            f"role with {SETTING}."
        ]
    return [
        f"{CODE}: {SETTING}[{pattern!r}] is not granted to the {slug!r} role: {why}"
        for pattern, why in grant_problems().items()
    ]
