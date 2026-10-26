"""Settings vocabulary for karni-site: the ``karni.settings`` entry point.

Import-light by contract: plain data plus django-environ reads, never
``django.conf.settings`` at import time. Module code reads settings through
:func:`get`, so it also works without ``karni_settings()``.

Override / escape hatch: define any of these names in the project's
settings.py.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

DEFAULTS: dict[str, Any] = {
    # The function {% ifactive %} asks whether a pattern names the current page:
    # (request, pattern) -> bool. A dotted path, so a project can swap the rule.
    "KARNI_SITE_IS_ACTIVE": "karni_site.navigation.is_active",
    # The templates karni_site.views.server_error tries in order. The first that
    # renders is the page. The last is this module's plain page, which needs nothing.
    "KARNI_SITE_SERVER_ERROR_TEMPLATES": ["500.html", "karni_site/500.html"],
    # The same for karni_site.views.page_not_found.
    "KARNI_SITE_NOT_FOUND_TEMPLATES": ["404.html", "karni_site/404.html"],
    # The model `site` is in every template: "app_label.ModelName". A project with
    # fields of its own subclasses karni_site.models.AbstractSiteSettings and names
    # its model here, before karni_site's first migrate (like AUTH_USER_MODEL).
    "KARNI_SITE_SETTINGS_MODEL": "karni_site.SiteSettings",
    # What a client types around words to highlight them in an editable block, and
    # the element (with its class) the words render in. "" as the marker turns it off.
    "KARNI_SITE_HIGHLIGHT": {"marker": "==", "tag": "mark", "class": ""},
    # The inline markup an edited block keeps: element -> the attributes it keeps.
    # Everything else is removed, its text kept. The highlight element joins it.
    "KARNI_SITE_INLINE_TAGS": {
        "b": [],
        "strong": [],
        "i": [],
        "em": [],
        "br": [],
        "a": ["href", "title", "target", "rel"],
    },
    # The schemes a link in an edited block may use. A relative link always may.
    "KARNI_SITE_LINK_SCHEMES": ["http", "https", "mailto", "tel"],
    # The function that cleans a block's HTML: (html) -> html. A dotted path.
    "KARNI_SITE_SANITIZER": "karni_site.sanitize.sanitize",
    # The file types an image upload may be (by extension, checked against the
    # file's own bytes). SVG is left out on purpose: an SVG file can carry script.
    "KARNI_SITE_IMAGE_TYPES": ["jpg", "jpeg", "png", "gif", "webp", "avif", "ico"],
    # The cache alias, and the seconds a cached block, menu, redirect or setting
    # lives. Every save clears what it changed, so the timeout is only a backstop.
    "KARNI_SITE_CACHE": "default",
    "KARNI_SITE_CACHE_TIMEOUT": 3600,
    # Whether the first render of a template stores its defaults (blocks, a menu's
    # seed, the site's details). False: nothing is written while a page renders.
    "KARNI_SITE_SEED_ON_RENDER": True,
    # The rows a menu item's "children from" model contributes: (model, item) ->
    # iterable of rows with get_absolute_url(). A dotted path.
    "KARNI_SITE_MENU_ROWS": "karni_site.menus.menu_rows",
    # At most this many rows per "children from" item.
    "KARNI_SITE_MENU_ROWS_LIMIT": 100,
    # False: an admin redirect answers only where the site has no page (a 404), and a
    # request for a page that exists costs nothing. True: every request is looked up
    # before the view runs, one cache read each.
    "KARNI_SITE_REDIRECTS_BEFORE_VIEWS": False,
    # The slug of the content editor role this module declares (karni.roles), or None
    # to declare none. A role of the same slug in KARNI_ROLES replaces it.
    "KARNI_SITE_EDITOR_ROLE": "editor",
}


def get(name: str) -> Any:
    """``settings.<name>`` if the project defines it, else the module default."""
    return getattr(settings, name, DEFAULTS[name])
