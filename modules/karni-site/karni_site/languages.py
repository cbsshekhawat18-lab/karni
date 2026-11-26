"""The site's languages: what the menus, the sitemap and ``karni check --seo`` ask.

A site is in several languages when its pages' addresses carry the language
(``i18n_patterns``), ``USE_I18N`` is on and ``LANGUAGES`` has two entries or more.
Then:

* a menu is cached and marked per language, and follows its seed in the default
  language only (:mod:`karni_site.menus`);
* the sitemap lists every language's address of each page and row
  (:mod:`karni_site.sitemaps`);
* ``karni check --seo`` compares titles and descriptions within one language
  (:mod:`karni_site.checks_seo`).

A one-language site, or one without ``i18n_patterns``, takes none of these paths.

This module is internal to karni-site. Its helpers serve the menus, the
sitemap and the SEO checks, and they are not public names: they may change or
go in any release, as sites in several languages get their full design. A
project does not import them.

Override / escape hatch: ``i18n = False`` on a sitemap section of your own
(``KARNI_SITE_SITEMAPS``) lists one language there.
"""

from __future__ import annotations

from django.conf import settings
from django.utils import translation


def in_addresses() -> bool:
    """Whether the site's addresses carry the language: ``i18n_patterns`` and two languages."""
    from django.conf.urls.i18n import is_language_prefix_patterns_used

    if not settings.USE_I18N or len(settings.LANGUAGES) < 2:
        return False
    used, _prefix_default = is_language_prefix_patterns_used(settings.ROOT_URLCONF)
    return bool(used)


def default_language() -> str:
    """``LANGUAGE_CODE`` as ``LANGUAGES`` writes it: the language the templates' defaults are in."""
    try:
        return str(translation.get_supported_language_variant(settings.LANGUAGE_CODE))
    except LookupError:
        return str(settings.LANGUAGE_CODE)


def language_of(path: str) -> str:
    """The language of the page at ``path``: its prefix, else the default language.

    ``""`` on a site whose addresses carry no language (:func:`in_addresses`).
    """
    if not in_addresses():
        return ""
    return translation.get_language_from_path(path) or default_language()


def is_language_root(path: str) -> bool:
    """Whether ``path`` is a language's home page (``/fr/``) on a site in several languages."""
    if not in_addresses():
        return False
    language = translation.get_language_from_path(path)
    return bool(language) and path == f"/{language}/"
