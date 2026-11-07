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

The project's own brand comes from the same file its staff app loads: the
frontend's ``karni-theme.css`` (``karni ui detect`` writes it). The setting
``KARNI_THEME_CSS`` names it (default ``frontend/src/karni-theme.css``,
relative to the project root), :class:`ProjectThemeFinder` serves it as the
static file ``karni/project-theme.css`` (``runserver`` reads it live and
``collectstatic`` copies it, so production serves it from the site's own
origin, which the Content-Security-Policy's ``style-src 'self'`` allows), and
:func:`project_theme_stylesheet` loads it third in ``UNFOLD["STYLES"]``,
after the tokens and the unfold bridge. Without the file the URL serves an
empty stylesheet, so the admin never loads a missing file.

Override / escape hatch: ``KARNI_THEME_CSS`` points at another file (or
``""`` for none); append a stylesheet of ``--karni-*`` overrides to
``UNFOLD["STYLES"]``, or replace ``UNFOLD["STYLES"]`` / ``UNFOLD["COLORS"]``
in settings to drop Karni's theme. Unfold resolves each ``STYLES`` entry per
request: a dotted path to a ``(request) -> url`` callable, or a plain URL.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any, Final

from django.conf import settings
from django.contrib.staticfiles.finders import BaseFinder
from django.core.files.storage import FileSystemStorage

__all__ = [
    "A11Y_JS",
    "ADMIN_PAGES_CSS",
    "DEFAULT_THEME_CSS",
    "PROJECT_THEME_CSS",
    "TOKENS_CSS",
    "UNFOLD_THEME_CSS",
    "a11y_script",
    "ProjectThemeFinder",
    "project_theme_path",
    "project_theme_stylesheet",
    "tokens_css",
    "tokens_stylesheet",
    "unfold_theme_stylesheet",
]

TOKENS_CSS: Final = "karni/tokens.css"
"""Static path of the @karni/ui token stylesheet copy."""

UNFOLD_THEME_CSS: Final = "karni/unfold-theme.css"
"""Static path of the stylesheet that maps unfold onto the tokens."""

A11Y_JS: Final = "karni/admin-a11y.js"
"""Static path of the script that adds landmarks and names to unfold's pages."""

ADMIN_PAGES_CSS: Final = "karni/admin-pages.css"
"""Static path of the stylesheet Karni's own admin pages share."""

PROJECT_THEME_CSS: Final = "karni/project-theme.css"
"""Static path the project's ``karni-theme.css`` is served at (:class:`ProjectThemeFinder`)."""

DEFAULT_THEME_CSS: Final = "frontend/src/karni-theme.css"
"""Fallback for ``KARNI_THEME_CSS``: where ``karni ui detect`` writes in a scaffolded project."""

_STATIC_ROOT: Final = Path(__file__).parent / "static"
_NO_THEME: Final = Path(__file__).parent / "project-theme-empty.css"


def _static_url(path: str) -> str:
    from django.templatetags.static import static

    return static(path)


def tokens_stylesheet(request: Any) -> str:
    """``UNFOLD["STYLES"]`` entry: the URL of ``karni/tokens.css``."""
    return _static_url(TOKENS_CSS)


def a11y_script(request: Any) -> str:
    """``UNFOLD["SCRIPTS"]`` entry: the URL of ``karni/admin-a11y.js``."""
    return _static_url(A11Y_JS)


def unfold_theme_stylesheet(request: Any) -> str:
    """``UNFOLD["STYLES"]`` entry: the URL of ``karni/unfold-theme.css``."""
    return _static_url(UNFOLD_THEME_CSS)


@cache
def tokens_css() -> str:
    """The token stylesheet's text, for pages that inline it (the welcome page)."""
    return (_STATIC_ROOT / TOKENS_CSS).read_text(encoding="utf-8")


def project_theme_stylesheet(request: Any) -> str:
    """``UNFOLD["STYLES"]`` entry: the URL of the project's theme (``karni/project-theme.css``)."""
    return _static_url(PROJECT_THEME_CSS)


def project_theme_path() -> Path | None:
    """The project's ``karni-theme.css`` (``KARNI_THEME_CSS``), or ``None`` when there is none.

    A relative path is read from the project root: ``BASE_DIR``, else the
    directory above the settings package (a Karni scaffold's root).
    """
    configured = getattr(settings, "KARNI_THEME_CSS", DEFAULT_THEME_CSS)
    if not configured:
        return None
    path = Path(str(configured))
    if not path.is_absolute():
        from karni.testing._source import project_root

        path = project_root() / path
    return path if path.is_file() else None


class _OneFile(FileSystemStorage):
    """A storage that holds one file under one name: what collectstatic copies."""

    def __init__(self, source: Path) -> None:
        super().__init__(location=str(source.parent))
        self.source = source

    def path(self, name: str) -> str:
        return str(self.source)


class ProjectThemeFinder(BaseFinder):
    """Serves the project's ``karni-theme.css`` as the static file ``karni/project-theme.css``.

    Listed in ``STATICFILES_FINDERS`` by ``karni_settings()``. Without a theme
    file it serves an empty stylesheet, so the admin's ``<link>`` always
    answers 200.

    Escape hatch: ``KARNI_THEME_CSS`` names the file, and removing this
    finder (with ``karni.admin.theme.project_theme_stylesheet`` in
    ``UNFOLD["STYLES"]``) turns the project theme off in the admin.
    """

    def source(self) -> Path:
        return project_theme_path() or _NO_THEME

    def find(self, path: str, find_all: bool = False, **kwargs: Any) -> Any:
        # Django 5.2 renamed `all` to `find_all`; accept both.
        wants_all = find_all or bool(kwargs.get("all", False))
        if path != PROJECT_THEME_CSS:
            # An empty list either way, as Django's own finders answer: a None
            # would end up in finders.find()'s matches and read as found.
            return []
        found = str(self.source())
        return [found] if wants_all else found

    def list(self, ignore_patterns: Any) -> Iterator[tuple[str, FileSystemStorage]]:
        yield PROJECT_THEME_CSS, _OneFile(self.source())

    def check(self, **kwargs: Any) -> builtins.list[Any]:
        return []
