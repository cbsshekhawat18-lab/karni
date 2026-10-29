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
    # What a client types around words to highlight them, in an editable block and in a
    # field rendered with {{ value|highlight }}, and the element (with its class) the
    # words render in. A backslash before the marker keeps it as typed. An empty marker
    # turns it off.
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
    # The cache alias blocks, menus, redirects, page SEO entries and the settings live in.
    "KARNI_SITE_CACHE": "default",
    # Seconds a cached entry lives. Every save clears what it changed, so this is a backstop.
    "KARNI_SITE_CACHE_TIMEOUT": 3600,
    # Whether the first render of a template stores its defaults (blocks, a menu's
    # seed, the site's details). False: nothing is written while a page renders.
    "KARNI_SITE_SEED_ON_RENDER": True,
    # The rows a menu item's "children from" model contributes: (model, item) ->
    # iterable of rows with get_absolute_url(). A dotted path.
    "KARNI_SITE_MENU_ROWS": "karni_site.menus.menu_rows",
    # At most this many rows per "children from" item.
    "KARNI_SITE_MENU_ROWS_LIMIT": 100,
    # True: a menu item is active (item.active) on every page under its own path too, so
    # "Services" at /services/ stays marked on /services/web/. The home page (/) never is.
    # False: an item is active on its own page and when one of its children is.
    "KARNI_SITE_MENU_SECTIONS": True,
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


# --- Public forms ({% karni_form %}, karni_site.forms, karni_site.notify) -------
# Kept as one block at the end of the file: each key is read through get() like the ones above.
DEFAULTS |= {
    # Form name -> the dotted path of the BaseViewSet that saves it, or a model label
    # ("shop.Enquiry"). Without an entry, {% karni_form "enquiry" %} finds the model by name.
    "KARNI_SITE_FORMS": {},
    # The class that renders and submits a form. A dotted path to a karni_site.forms.SiteForm
    # subclass, to change how fields are described or how a submission is saved.
    "KARNI_SITE_FORM_CLASS": "karni_site.forms.SiteForm",
    # The template {% karni_form %} renders. Each field renders karni_site/forms/field.html, or
    # karni_site/forms/<form>/<field>.html or karni_site/forms/<form>/field.html when one exists.
    "KARNI_SITE_FORM_TEMPLATE": "karni_site/forms/form.html",
    # Class names on the form's markup, merged over the module's plain defaults:
    # form, row, column, field, label, input, select, check, check_input, check_label,
    # invalid, error, help, message, success, failure, button, required.
    "KARNI_SITE_FORM_CLASSES": {},
    # Named sets of class names a tag picks with classes="<name>", merged over the shipped
    # "bootstrap" preset (Bootstrap 5). {"salon": {"field": "field", "row": "form-row"}}.
    "KARNI_SITE_FORM_PRESETS": {},
    # The texts a form shows, merged over the defaults: success, invalid, throttled, refused,
    # failed, choose (a select's empty option) and button. A tag's own success="..." wins.
    "KARNI_SITE_FORM_MESSAGES": {},
    # The text after a required field's label.
    "KARNI_SITE_FORM_REQUIRED_MARK": "*",
    # Whether {% karni_form %} adds karni_site/forms.js (submit in place, inline errors).
    # False leaves the form working without JavaScript, and a site may load its own script.
    "KARNI_SITE_FORM_SCRIPT": True,
    # The query parameter the page gets after a form was sent without JavaScript: ?sent=<form>.
    "KARNI_SITE_FORM_SENT_PARAM": "sent",
    # The page that shows a form with its errors when the page it was sent from cannot be
    # rendered again (no page, a page that needs a POST, a page that fails).
    "KARNI_SITE_FORM_PAGE_TEMPLATE": "karni_site/forms/page.html",
    # The sender of karni_site.notify emails. Empty: Django's DEFAULT_FROM_EMAIL.
    "KARNI_SITE_NOTIFY_FROM": "",
}


# SEO and images: {% karni_seo %}, {% image %}, the sitemap, robots.txt, karni check --seo.
DEFAULTS |= {
    # The site's own address, "https://www.example.com". Canonical links, share tags, the
    # sitemap and robots.txt use it. None: the address each request came to.
    "KARNI_SITE_URL": None,
    # Whether search engines may index the site. None: only when DJANGO_ENV is "prod", so a
    # development or staging copy is never indexed. True or False decides for every environment.
    "KARNI_SITE_ALLOW_INDEXING": None,
    # Paths robots.txt asks crawlers to stay out of while indexing is allowed: ["/search/"].
    "KARNI_SITE_ROBOTS_DISALLOW": [],
    # URL names and paths the sitemap leaves out, shell wildcards allowed:
    # ["website:thanks", "/drafts/*"]. The admin, the API and redirects are never in it.
    "KARNI_SITE_SITEMAP_EXCLUDE": [],
    # The function that lists the sitemap's sections: () -> {name: Sitemap}. A dotted path.
    "KARNI_SITE_SITEMAPS": "karni_site.sitemaps.sitemaps",
    # Boolean fields that mark a row as public, tried in order on a model in the sitemap
    # without a filter of its own (class Karni: sitemap = {"filter": {...}}).
    "KARNI_SITE_PUBLISHED_FIELDS": [
        "published",
        "is_published",
        "is_public",
        "public",
        "visible",
        "is_visible",
    ],
    # The schema.org type of the site's JSON-LD: "auto" (LocalBusiness when the site has
    # opening hours, else Organization), any schema.org type ("Bakery", "Dentist"), or None.
    "KARNI_SITE_SCHEMA_TYPE": "auto",
    # The function that builds the JSON-LD: (request, site) -> dict or None. A dotted path.
    "KARNI_SITE_JSONLD": "karni_site.jsonld.build",
    # The function that finds the object a page is about: (context, request) -> object or None.
    "KARNI_SITE_SEO_OBJECT": "karni_site.metadata.page_object",
    # How a title taken from the page's object is written. {title} and {site}.
    "KARNI_SITE_TITLE_FORMAT": "{title} | {site}",
    # The longest description taken from the page's object, in characters.
    "KARNI_SITE_DESCRIPTION_LENGTH": 160,
    # The widths, in pixels, of the WebP copies made of each uploaded image (those below its own
    # width, and its own width when it is not a WebP). [] makes none.
    "KARNI_SITE_IMAGE_WIDTHS": [320, 480, 640, 800, 960, 1280, 1600, 1920],
    # The WebP quality of those copies, 1 to 100.
    "KARNI_SITE_IMAGE_QUALITY": 80,
    # An uploaded image wider or taller than this many pixels is scaled down to fit. None keeps it.
    "KARNI_SITE_IMAGE_MAX_SIZE": 2560,
    # Whether an upload, and the first page that shows an image without copies, queue the
    # copies (a Celery task). False: make them yourself (karni_site.renditions.make).
    "KARNI_SITE_QUEUE_RENDITIONS": True,
    # The function that makes an image's copies: (name, storage) -> manifest. A dotted path.
    "KARNI_SITE_RENDITIONER": "karni_site.renditions.generate",
    # The CSS {% karni_seo %} puts in the head so an image Karni sized keeps its shape when the
    # design's CSS sets only its width or only its height. "" leaves it out.
    "KARNI_SITE_IMAGE_STYLE": (
        ":where(img[data-karni-image]){height:auto}"
        ":where(img[data-karni-image=natural]){width:auto}"
    ),
    # karni check --seo: at most this many pages are requested.
    "KARNI_SITE_SEO_MAX_PAGES": 500,
    # karni check --seo: an image without smaller copies is oversized above this many bytes.
    "KARNI_SITE_SEO_IMAGE_BYTES": 500_000,
    # karni check --seo: an image is oversized when wider than this many times its width.
    "KARNI_SITE_SEO_PIXEL_RATIO": 2,
    # karni check --seo: regular expressions of paths it never requests.
    "KARNI_SITE_SEO_IGNORE": [],
    # karni check --seo: the loggers held back while it requests the pages (one or more
    # lines per request). Their errors are counted, and the first is shown. [] keeps them.
    "KARNI_SITE_SEO_QUIET": [
        "django_structlog",
        "django.request",
        "django.server",
        "karni.queries",
    ],
}
