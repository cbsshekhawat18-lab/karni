"""The ``class Karni`` keys karni-site reads (listed in docs/REFERENCE.md).

* ``sitemap``: whether, and which, rows of a model with pages of their own
  are in sitemap.xml (:mod:`karni_site.sitemaps`).
* ``seo``: which fields give a row's page its title, description, share
  image and Open Graph type (:mod:`karni_site.metadata`).
"""

from __future__ import annotations

from karni.meta import Option

__all__ = ["KARNI_OPTIONS"]

KARNI_OPTIONS: tuple[Option, ...] = (
    Option(
        "sitemap",
        "listed when the model has `get_absolute_url()`",
        "Which rows sitemap.xml lists: `False` for none, or a dict of `filter` and `exclude` "
        "lookups, `lastmod`, `changefreq` and `priority`. Without a filter, a `published` "
        "field (or `KARNI_SITE_PUBLISHED_FIELDS`) must be true.",
        'sitemap = {"filter": {"status": "live"}, "lastmod": "edited_at"}',
    ),
    Option(
        "seo",
        "`title` or `name`, `description` or `summary`, `image` or `photo`",
        "The fields (or methods) that give a row's own page its title, description, share "
        "image and Open Graph type in `{% karni_seo %}`.",
        'seo = {"title": "name", "description": "intro", "image": "photo"}',
    ),
)
