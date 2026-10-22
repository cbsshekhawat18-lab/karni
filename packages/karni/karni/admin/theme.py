"""The admin's look: @karni/ui's design tokens, shipped as Django static files.

One source: ``karni/tokens.css`` in this app's static files is a byte-for-byte
copy of ``packages/karni-ui/src/styles.css`` (the stylesheet ``@karni/ui``
publishes as ``@karni/ui/styles.css``). A test fails when the two differ and
prints the ``cp`` command that syncs them. Everything Django renders reads
that copy:

* the admin, through ``UNFOLD["STYLES"]`` (:func:`tokens_stylesheet`, then
  :func:`unfold_theme_stylesheet`, which draws unfold with the tokens) and
  ``UNFOLD["COLORS"]`` in :mod:`karni.conf.base`, whose primary and text
  colours are ``var(--karni-color-*)`` references;
* Karni's own admin pages (import, permission matrix), through the template
  ``karni_admin/includes/page_styles.html``: ``karni/admin-pages.css``, and
  the tokens too when ``UNFOLD["STYLES"]`` did not load them, so the pages
  keep their look when a project replaces ``STYLES`` and never load the
  tokens a second time after a project's own overrides;
* the welcome page, which inlines the file (:func:`tokens_css`).

Dark mode is the ``dark`` class on ``<html>`` everywhere, as in @karni/ui:
unfold sets it from its light/dark/system switch, the welcome page from the
system preference.

Override / escape hatch: retheme by appending a stylesheet of ``--karni-*``
overrides to ``UNFOLD["STYLES"]`` (the same values a frontend's
``karni-theme.css`` holds), or replace ``UNFOLD["STYLES"]`` /
``UNFOLD["COLORS"]`` in settings to drop Karni's theme. Unfold resolves each
``STYLES`` entry per request: a dotted path to a ``(request) -> url``
callable, or a plain URL.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any, Final

__all__ = [
    "ADMIN_PAGES_CSS",
    "TOKENS_CSS",
    "UNFOLD_THEME_CSS",
    "tokens_css",
    "tokens_stylesheet",
    "unfold_theme_stylesheet",
]

TOKENS_CSS: Final = "karni/tokens.css"
"""Static path of the @karni/ui token stylesheet copy."""

UNFOLD_THEME_CSS: Final = "karni/unfold-theme.css"
"""Static path of the stylesheet that maps unfold onto the tokens."""

ADMIN_PAGES_CSS: Final = "karni/admin-pages.css"
"""Static path of the stylesheet Karni's own admin pages share."""

_STATIC_ROOT: Final = Path(__file__).parent / "static"


def _static_url(path: str) -> str:
    from django.templatetags.static import static

    return static(path)


def tokens_stylesheet(request: Any) -> str:
    """``UNFOLD["STYLES"]`` entry: the URL of ``karni/tokens.css``."""
    return _static_url(TOKENS_CSS)


def unfold_theme_stylesheet(request: Any) -> str:
    """``UNFOLD["STYLES"]`` entry: the URL of ``karni/unfold-theme.css``."""
    return _static_url(UNFOLD_THEME_CSS)


@cache
def tokens_css() -> str:
    """The token stylesheet's text, for pages that inline it (the welcome page)."""
    return (_STATIC_ROOT / TOKENS_CSS).read_text(encoding="utf-8")
