"""The text an extraction reads: given as text, fetched from a URL, or taken from a PDF.

:func:`read_source` takes exactly one of the three and returns a
:class:`Source`: its kind, a label for the import job and the usage log, and
its text. Every refusal is AI010 (the URL's own are AI011 and AI012, from
:mod:`karni_ai.services.fetch`).

PDF text comes from **pypdf**: pure Python with no C library or system
package, permissively licensed, small, and it reads the text layer of a PDF,
which is what a language model needs. A scanned PDF has no text layer and is
refused: run text recognition first. An HTML page is reduced to its visible
text with the standard library's HTML parser (scripts, styles and templates
left out).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Final

from karni_ai import conf
from karni_ai.conf import load_class
from karni_ai.exceptions import ExtractionRefused

__all__ = ["Source", "pdf_text", "read_source", "visible_text"]

#: Tags whose content a reader never sees.
_HIDDEN: Final = frozenset({"script", "style", "noscript", "template", "svg", "head"})
#: Tags that start a new line of text.
_BLOCKS: Final = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "table",
        "ul",
        "ol",
        "dt",
        "dd",
        "header",
        "footer",
        "blockquote",
        "pre",
    }
)
_PDF_TYPES: Final = frozenset({"application/pdf", "application/x-pdf"})


@dataclass(frozen=True)
class Source:
    """Experimental. What an extraction reads: ``text``, ``url`` or ``pdf``, a label, the text."""

    kind: str
    label: str
    text: str


class _Visible(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN:
            self.hidden += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN:
            self.hidden = max(0, self.hidden - 1)
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def visible_text(html: str) -> str:
    """The text a reader sees on an HTML page, one line per block."""
    parser = _Visible()
    parser.feed(html)
    parser.close()
    return _lines("".join(parser.parts))


def _tidy(text: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _lines(text: str) -> str:
    """``text`` with one line per block and no blank lines (what a page's markup gives)."""
    return re.sub(r"\n{2,}", "\n", _tidy(text))


def pdf_text(data: bytes) -> str:
    """The text layer of a PDF, page by page (AI010 when it is not one, locked or too long)."""
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    if not data.lstrip()[:5].startswith(b"%PDF-"):
        raise ExtractionRefused("The file is not a PDF.", code="AI010")
    max_pages = int(conf.get("KARNI_AI_MAX_PDF_PAGES"))
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionRefused(
                "The PDF is protected by a password. Send an unlocked copy.", code="AI010"
            )
        pages = len(reader.pages)
        if pages > max_pages:
            raise ExtractionRefused(
                f"The PDF has {pages} pages, and at most {max_pages} are read "
                "(KARNI_AI_MAX_PDF_PAGES). Send the pages that matter.",
                code="AI010",
            )
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    except ExtractionRefused:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError) as exc:
        raise ExtractionRefused(f"The PDF cannot be read: {exc}.", code="AI010") from exc
    text = _tidy(text)
    if not text:
        raise ExtractionRefused(
            "The PDF has no text layer (a scanned document). Run text recognition on it first.",
            code="AI010",
        )
    return text


def _limit(text: str) -> str:
    limit = int(conf.get("KARNI_AI_MAX_SOURCE_CHARS"))
    text = text.strip()
    if not text:
        raise ExtractionRefused("The source has no text.", code="AI010")
    if len(text) > limit:
        raise ExtractionRefused(
            f"The source has {len(text)} characters, and at most {limit} are sent "
            "(KARNI_AI_MAX_SOURCE_CHARS). Send a shorter part; nothing is cut silently.",
            code="AI010",
        )
    return text


def _from_url(url: str) -> Source:
    from karni_ai.services.fetch import Fetcher

    fetcher = load_class("KARNI_AI_FETCHER", Fetcher)()
    fetched = fetcher.fetch(url)
    if fetched.content_type in _PDF_TYPES:
        text = pdf_text(fetched.body)
    elif fetched.content_type in ("text/html", "application/xhtml+xml", "text/plain", ""):
        decoded = fetched.body.decode(fetched.charset or "utf-8", errors="replace")
        text = decoded if fetched.content_type == "text/plain" else visible_text(decoded)
    else:
        raise ExtractionRefused(
            f"{fetched.url} is {fetched.content_type}, and only HTML, plain text and PDF are read.",
            code="AI012",
        )
    return Source(kind="url", label=fetched.url, text=_limit(text))


def _from_file(upload: Any) -> Source:
    limit = int(conf.get("KARNI_AI_MAX_UPLOAD_BYTES"))
    size = getattr(upload, "size", None)
    if size is not None and int(size) > limit:
        raise ExtractionRefused(
            f"The file has {size} bytes, and the limit is {limit} (KARNI_AI_MAX_UPLOAD_BYTES).",
            code="AI010",
        )
    data = upload.read(limit + 1)
    if len(data) > limit:
        raise ExtractionRefused(
            f"The file is larger than {limit} bytes (KARNI_AI_MAX_UPLOAD_BYTES).", code="AI010"
        )
    name = str(getattr(upload, "name", "") or "upload.pdf")
    return Source(kind="pdf", label=name.rsplit("/", 1)[-1][:200], text=_limit(pdf_text(data)))


def read_source(*, text: str | None = None, url: str | None = None, file: Any = None) -> Source:
    """Experimental. The one source given, as text within the limits in settings."""
    given = [name for name, value in (("text", text), ("url", url), ("file", file)) if value]
    if len(given) != 1:
        raise ExtractionRefused(
            "Give exactly one source: text, url or file"
            + (f" (got {', '.join(given)})." if given else "."),
            code="AI010",
        )
    if url:
        return _from_url(url)
    if file is not None:
        return _from_file(file)
    return Source(kind="text", label="text", text=_limit(str(text)))
