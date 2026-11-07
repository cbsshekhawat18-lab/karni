"""Renderers: HTML in, PDF bytes out.

* :class:`WeasyPrintRenderer` (``KARNI_REPORTS_RENDERER = "weasyprint"``, the
  default) draws the PDF with WeasyPrint. It needs Pango, a system library.
  While rendering it reads only ``data:`` URLs and the files under
  ``STATIC_URL`` and ``MEDIA_URL``, never the network.
* :class:`FakeRenderer` (``"fake"``) returns deterministic bytes without any
  system library and records the HTML of each render, for tests.

Override / escape hatch: set ``KARNI_REPORTS_RENDERER`` to the dotted path of
your own :class:`Renderer` subclass, or override ``Report.get_renderer`` for
one report. Subclass :class:`WeasyPrintRenderer` with ``allow_network = True``
to let a template load images from other hosts.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from typing import Any, ClassVar
from urllib.parse import unquote, urljoin

from django.utils.module_loading import import_string
from karni.exceptions import KarniImportError, KarniImproperlyConfigured, KarniValueError

from karni_reports import conf

__all__ = [
    "BASE_URL",
    "FakeRenderer",
    "Renderer",
    "WeasyPrintRenderer",
    "get_renderer",
]

logger = logging.getLogger(__name__)

#: The base every relative URL in a template resolves against while rendering.
#: ``/static/logo.png`` becomes ``http://karni-reports.invalid/static/logo.png``,
#: which the renderer reads from the static files, never over the network.
BASE_URL = "http://karni-reports.invalid/"

SHORTCUTS = {
    "weasyprint": "karni_reports.rendering.WeasyPrintRenderer",
    "fake": "karni_reports.rendering.FakeRenderer",
}


class Renderer:
    """Experimental. Turns a report's HTML into the bytes of a PDF.

    Override / escape hatch: subclass it, implement :meth:`render` and name
    the class in ``KARNI_REPORTS_RENDERER``.
    """

    content_type: ClassVar[str] = "application/pdf"

    def render(self, html: str, *, base_url: str = BASE_URL) -> bytes:
        """The PDF of ``html``. Relative URLs in it resolve against ``base_url``."""
        raise NotImplementedError

    def identity(self) -> str:
        """What the template version records of the renderer: its class path by default."""
        return f"{type(self).__module__}.{type(self).__qualname__}"


class FakeRenderer(Renderer):
    """Experimental. A renderer for tests: deterministic bytes and no system library.

    The HTML of every render is appended to :attr:`rendered`, so a test reads
    what was printed. :meth:`reset` empties it.
    """

    rendered: ClassVar[list[str]] = []

    def render(self, html: str, *, base_url: str = BASE_URL) -> bytes:
        FakeRenderer.rendered.append(html)
        digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
        return f"%PDF-1.4\n% karni-reports fake renderer\n% {digest}\n%%EOF\n".encode()

    @classmethod
    def reset(cls) -> None:
        cls.rendered.clear()


class WeasyPrintRenderer(Renderer):
    """Experimental. The PDF drawn by WeasyPrint (``KARNI_REPORTS_RENDERER = "weasyprint"``).

    WeasyPrint needs Pango, a system library: ``REPORT006`` names the
    packages when it is missing. While rendering, a URL is read only when it
    is a ``data:`` URL or a file under ``STATIC_URL`` (through the static
    files finders, then the static files storage) or ``MEDIA_URL`` (the
    default storage). Any other URL is left out of the PDF with a
    ``REPORT009`` warning, so a value in a row can never make the server
    call another host.

    Override / escape hatch: set ``allow_network = True`` on a subclass to
    fetch other URLs, or override :meth:`local_file`.
    """

    allow_network: ClassVar[bool] = False

    def render(self, html: str, *, base_url: str = BASE_URL) -> bytes:
        weasyprint = _import_weasyprint()
        document = weasyprint.HTML(string=html, base_url=base_url, url_fetcher=self.fetcher())
        pdf: bytes = document.write_pdf()
        return pdf

    def fetcher(self) -> Any:
        """The WeasyPrint URL fetcher this renderer reads images and stylesheets with."""
        from weasyprint.urls import URLFetcher, URLFetcherResponse

        renderer = self

        class LocalFetcher(URLFetcher):
            def fetch(self, url: str, headers: Any = None) -> Any:
                if url.startswith("data:") or renderer.allow_network:
                    return super().fetch(url, headers)
                found = renderer.local_file(url)
                if found is None:
                    logger.warning(
                        "REPORT009: the report's template references %s, which is neither a "
                        "data: URL nor a static or media file, so it is left out of the PDF.",
                        url,
                    )
                    raise KarniValueError(f"{url} is not read while rendering.", code="REPORT009")
                body, mime = found
                return URLFetcherResponse(url, body=body, headers={"Content-Type": mime})

        return LocalFetcher()

    def local_file(self, url: str) -> tuple[bytes, str] | None:
        """``(content, media type)`` of a static or media file ``url`` names, else ``None``."""
        from django.conf import settings

        for setting, opener in (("STATIC_URL", _static_file), ("MEDIA_URL", _media_file)):
            prefix = getattr(settings, setting, None)
            if not prefix:
                continue
            absolute = urljoin(BASE_URL, str(prefix))
            if not url.startswith(absolute):
                continue
            name = unquote(url[len(absolute) :].split("?", 1)[0].split("#", 1)[0])
            if not name or ".." in name.split("/"):
                return None
            content = opener(name)
            if content is not None:
                return content, mimetypes.guess_type(name)[0] or "application/octet-stream"
        return None


def _static_file(name: str) -> bytes | None:
    from django.apps import apps

    if not apps.is_installed("django.contrib.staticfiles"):
        return None
    from django.contrib.staticfiles import finders
    from django.contrib.staticfiles.storage import staticfiles_storage

    try:
        path = finders.find(name)
        if isinstance(path, str):
            with open(path, "rb") as handle:
                return handle.read()
        with staticfiles_storage.open(name) as stored:
            content: bytes = stored.read()
            return content
    except Exception:  # noqa: BLE001 - a missing or refused file is left out, like a 404
        return None


def _media_file(name: str) -> bytes | None:
    from django.core.files.storage import default_storage

    try:
        with default_storage.open(name) as stored:
            content: bytes = stored.read()
            return content
    except Exception:  # noqa: BLE001 - a missing or refused file is left out, like a 404
        return None


def _import_weasyprint() -> Any:
    try:
        import weasyprint
    except (ImportError, OSError) as exc:
        raise KarniImportError(
            f"WeasyPrint cannot load ({exc}). It needs Pango, a system library: apt-get "
            "install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core "
            "(Debian, Ubuntu), apk add pango font-dejavu (Alpine) or brew install pango "
            "(macOS). In tests set KARNI_REPORTS_RENDERER = 'fake'.",
            code="REPORT006",
        ) from exc
    return weasyprint


def get_renderer() -> Renderer:
    """The renderer ``KARNI_REPORTS_RENDERER`` names (``REPORT005`` when it cannot load)."""
    configured = str(conf.get("KARNI_REPORTS_RENDERER") or "weasyprint")
    dotted = SHORTCUTS.get(configured, configured)
    try:
        found = import_string(dotted)
    except ImportError as exc:
        raise KarniImproperlyConfigured(
            f"KARNI_REPORTS_RENDERER = {configured!r} cannot be imported ({exc}). Use "
            "'weasyprint', 'fake' or the dotted path of a karni_reports.rendering.Renderer "
            "subclass.",
            code="REPORT005",
        ) from exc
    if not (isinstance(found, type) and issubclass(found, Renderer)):
        raise KarniImproperlyConfigured(
            f"KARNI_REPORTS_RENDERER = {configured!r} is not a karni_reports.rendering.Renderer "
            "subclass.",
            code="REPORT005",
        )
    return found()
