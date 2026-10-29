"""What a page tells search engines and sharing sites: what ``{% karni_seo %}`` renders.

The tag wraps the design's own head tags::

    {% karni_seo %}
      <title>{% block title %}Crumb & Co{% endblock %}</title>
      <meta name="description" content="{% block description %}{% endblock %}">
      {% block seo %}{% endblock %}
    {% endkarni_seo %}

and renders, in their place, the title, the description, the canonical
link, ``robots`` when the page is hidden, the Open Graph and Twitter tags
and the site's JSON-LD (:mod:`karni_site.jsonld`). Each value is the first
of:

1. the page's entry in the admin's *Page titles and descriptions*
   (:func:`karni_site.seo.page_seo`);
2. ``seo`` in the template's context, a dict a view passes:
   ``{"title": ..., "description": ..., "image": ..., "noindex": True}``;
3. the object the page is about (:func:`page_object`): what its
   ``class Karni: seo`` names, else its ``seo_title``, ``seo_description``
   and ``seo_image``, else a ``title``, ``description`` or ``image`` field
   by a usual name;
4. the template's own tags between ``{% karni_seo %}`` and
   ``{% endkarni_seo %}`` (``<title>``, ``<meta name="description">``,
   ``og:image``, ``twitter:card``...);
5. the site's settings: its name, its tagline, its default share image.

A tag the template writes that this does not cover (``theme-color``,
``twitter:site``, a design's own JSON-LD) is kept where it is.

Override / escape hatch: ``KARNI_SITE_SEO_OBJECT`` (how the page's object
is found), ``KARNI_SITE_TITLE_FORMAT``, ``KARNI_SITE_DESCRIPTION_LENGTH``,
``KARNI_SITE_URL``, ``KARNI_SITE_JSONLD`` and ``KARNI_SITE_IMAGE_STYLE``.
:func:`resolve` returns the values without markup, for a tag of your own.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape, unescape
from typing import Any
from urllib.parse import urlsplit

from django.db import models
from django.db.models.fields.files import FieldFile
from django.utils.html import strip_tags
from django.utils.module_loading import import_string
from django.utils.translation import get_language

from karni_site import conf, renditions

__all__ = [
    "COVERED",
    "Head",
    "PageMeta",
    "absolute",
    "object_values",
    "page_object",
    "parse_head",
    "render_head",
    "resolve",
    "site_url",
]

logger = logging.getLogger("karni_site")

_TOKEN = re.compile(
    r"<!--.*?-->"
    r"|<(?P<raw>script|style|noscript|template)\b.*?</(?P=raw)\s*>"
    r"|<title\b[^>]*>(?P<title>.*?)</title\s*>"
    r"|<(?:meta|link)\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
_ATTR = re.compile(
    r"""(?P<name>[^\s"'=<>/`]+)(?:\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<uq>[^\s"'=<>`]+)))?""",
)
#: The ``<meta>`` names and properties ``{% karni_seo %}`` writes itself.
COVERED = frozenset(
    {
        "description",
        "robots",
        "og:title",
        "og:description",
        "og:url",
        "og:image",
        "og:image:url",
        "og:image:secure_url",
        "og:image:alt",
        "og:image:width",
        "og:image:height",
        "og:image:type",
        "og:type",
        "og:site_name",
        "og:locale",
        "twitter:card",
        "twitter:title",
        "twitter:description",
        "twitter:image",
        "twitter:image:alt",
    }
)
#: Field names tried, in order, on the page's object.
_TITLE_FIELDS = ("seo_title", "title", "name", "headline")
_DESCRIPTION_FIELDS = (
    "seo_description",
    "description",
    "summary",
    "excerpt",
    "intro",
    "lead",
    "subtitle",
    "body",
    "content",
    "text",
)
_IMAGE_FIELDS = ("seo_image", "image", "photo", "picture", "cover", "thumbnail", "hero")
_SEO_KEYS = frozenset({"title", "description", "image", "type"})
#: The width a share image is best at: the copy closest above it is used.
SHARE_WIDTH = 1200


def site_url(request: Any = None) -> str:
    """The site's address without a trailing slash: ``KARNI_SITE_URL``, else the request's."""
    configured = conf.get("KARNI_SITE_URL")
    if configured:
        return str(configured).rstrip("/")
    if request is not None:
        try:
            return f"{request.scheme}://{request.get_host()}"
        except Exception:  # noqa: BLE001 - a host Django refuses: no absolute address
            return ""
    return ""


def absolute(url: str, request: Any = None) -> str:
    """``url`` as an absolute address on the site (one with a scheme stays as it is)."""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme:
        return url
    base = site_url(request)
    if url.startswith("//"):
        scheme = urlsplit(base).scheme or "https"
        return f"{scheme}:{url}"
    return f"{base}{url if url.startswith('/') else '/' + url}"


# the template's own tags


@dataclass
class Head:
    """The template's tags between ``{% karni_seo %}`` and ``{% endkarni_seo %}``, read."""

    title: str | None = None
    #: name or property -> content, for every covered ``<meta>`` (the first of each).
    meta: dict[str, str] = field(default_factory=dict)
    canonical: str | None = None
    #: The markup in order, a covered tag as ``None``.
    pieces: list[str | None] = field(default_factory=list)


def _attributes(tag: str) -> dict[str, str]:
    found: dict[str, str] = {}
    body = tag[1:].split(None, 1)
    if len(body) < 2:
        return found
    for match in _ATTR.finditer(body[1].rstrip("/>")):
        value = next((match.group(g) for g in ("dq", "sq", "uq") if match.group(g) is not None), "")
        found.setdefault(match.group("name").lower(), unescape(value))
    return found


@lru_cache(maxsize=512)
def parse_head(markup: str) -> Head:
    """Read the template's head tags: what they set, and the markup to keep."""
    head = Head()
    cursor = 0
    for match in _TOKEN.finditer(markup):
        head.pieces.append(markup[cursor : match.start()])
        cursor = match.end()
        text = match.group(0)
        covered = False
        if match.group("title") is not None:
            covered = True
            if head.title is None:
                head.title = " ".join(unescape(strip_tags(match.group("title"))).split())
        elif text[:5].lower() == "<meta":
            attrs = _attributes(text)
            key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
            if key in COVERED:
                covered = True
                head.meta.setdefault(key, (attrs.get("content") or "").strip())
        elif text[:5].lower() == "<link":
            attrs = _attributes(text)
            if "canonical" in (attrs.get("rel") or "").lower().split():
                covered = True
                if head.canonical is None:
                    head.canonical = (attrs.get("href") or "").strip()
        head.pieces.append(None if covered else text)
    head.pieces.append(markup[cursor:])
    return head


def _assemble(head: Head, generated: list[str]) -> str:
    """The template's markup with the generated tags where its first covered tag was."""
    pieces = head.pieces
    spaces = [p for p in pieces if p is not None and p.strip() == "" and "\n" in p]
    indent = "\n" + spaces[0].rsplit("\n", 1)[1] if spaces else "\n"
    block = indent.join(generated)
    first = next((i for i, piece in enumerate(pieces) if piece is None), None)
    if first is None:
        lead = pieces[0] or ""
        rest = "".join(p for p in pieces[1:] if p is not None)
        return lead + block + rest
    out: list[str] = []
    for index, piece in enumerate(pieces):
        if piece is None:
            if index == first:
                out.append(block)
            continue
        following = pieces[index + 1] if index + 1 < len(pieces) else ""
        if following is None and index + 1 != first and piece.strip() == "":
            continue  # the space before a removed tag
        out.append(piece)
    return "".join(out)


# the page's object


def page_object(context: Any, request: Any) -> Any | None:
    """The row a page is about (``KARNI_SITE_SEO_OBJECT``'s default).

    ``seo`` or ``object`` in the context when it is a row, else the row in
    the context whose ``get_absolute_url()`` is the request's path.
    """
    for name in ("seo", "object"):
        value = context.get(name)
        if isinstance(value, models.Model):
            return value
    path = getattr(request, "path", None)
    if not path:
        return None
    try:
        values = list(context.flatten().values())
    except (AttributeError, ValueError):
        return None
    for value in values:
        if not isinstance(value, models.Model) or not hasattr(value, "get_absolute_url"):
            continue
        try:
            if value.get_absolute_url() == path:
                return value
        except Exception:  # noqa: BLE001 - a row whose page cannot be named is not this one
            continue
    return None


def _read(obj: Any, name: str) -> Any:
    try:
        value = getattr(obj, name)
        return value() if callable(value) and not isinstance(value, FieldFile) else value
    except Exception:  # noqa: BLE001 - a property that fails gives nothing
        logger.exception("karni_site: %s.%s could not be read for the page's tags", obj, name)
        return None


def _declared(obj: Any) -> Mapping[str, Any]:
    from karni.meta import karni_option

    declared = karni_option(type(obj), "seo")
    if declared is None:
        return {}
    if not isinstance(declared, Mapping) or set(declared) - {
        "title",
        "description",
        "image",
        "type",
    }:
        from karni.exceptions import KarniImproperlyConfigured

        raise KarniImproperlyConfigured(
            f"{type(obj).__name__}.Karni.seo is {declared!r}. It maps title, description, image "
            'and type to fields or methods of the model: seo = {"title": "name", '
            '"description": "summary", "image": "photo"}.',
            code="SITE019",
        )
    return declared


def object_values(obj: Any) -> dict[str, Any]:
    """``title``, ``description``, ``image`` and ``type`` of the page's object, where set."""
    if obj is None:
        return {}
    declared = _declared(obj)
    found: dict[str, Any] = {}
    for key, names in (
        ("title", _TITLE_FIELDS),
        ("description", _DESCRIPTION_FIELDS),
        ("image", _IMAGE_FIELDS),
    ):
        candidates = [declared[key]] if key in declared else [n for n in names if hasattr(obj, n)]
        for name in candidates:
            value = _read(obj, str(name))
            if value:
                found[key] = value
                break
    if declared.get("type"):
        found["type"] = str(declared["type"])
    return found


# resolving


@dataclass
class PageMeta:
    """Everything ``{% karni_seo %}`` writes for one page, as plain values."""

    title: str = ""
    description: str = ""
    canonical: str = ""
    image: str = ""
    image_alt: str = ""
    image_width: int | None = None
    image_height: int | None = None
    noindex: bool = False
    type: str = "website"
    twitter_card: str = "summary"
    site_name: str = ""
    locale: str = ""

    def tags(self) -> list[str]:
        """The ``<title>``, ``<meta>`` and ``<link>`` tags, in order."""

        def meta(attribute: str, key: str, value: str | int | None) -> str | None:
            if value in (None, ""):
                return None
            return f'<meta {attribute}="{key}" content="{escape(str(value))}">'

        lines: list[str | None] = [
            f"<title>{escape(self.title, quote=False)}</title>",
            meta("name", "description", self.description),
        ]
        if self.canonical:
            lines.append(f'<link rel="canonical" href="{escape(self.canonical)}">')
        if self.noindex:
            lines.append('<meta name="robots" content="noindex">')
        lines += [
            meta("property", "og:type", self.type),
            meta("property", "og:site_name", self.site_name),
            meta("property", "og:title", self.title),
            meta("property", "og:description", self.description),
            meta("property", "og:url", self.canonical),
            meta("property", "og:locale", self.locale),
            meta("property", "og:image", self.image),
            meta("property", "og:image:width", self.image_width if self.image else None),
            meta("property", "og:image:height", self.image_height if self.image else None),
            meta("property", "og:image:alt", self.image_alt if self.image else None),
            meta("name", "twitter:card", self.twitter_card),
            meta("name", "twitter:title", self.title),
            meta("name", "twitter:description", self.description),
            meta("name", "twitter:image", self.image),
            meta("name", "twitter:image:alt", self.image_alt if self.image else None),
        ]
        return [line for line in lines if line]


def _text(value: Any) -> str:
    return " ".join(unescape(strip_tags(str(value or ""))).split())


def _shorten(text: str) -> str:
    limit = int(conf.get("KARNI_SITE_DESCRIPTION_LENGTH") or 0)
    if not limit or len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:.-")
    return f"{cut}…"


def _image(value: Any, request: Any) -> tuple[str, int | None, int | None]:
    """An absolute address for a share image (a copy near 1200 pixels wide), and its size."""
    if isinstance(value, FieldFile):
        source = renditions.source_of(value)
        if source is None:
            return "", None, None
        manifest = renditions.info(source)
        if manifest is None:
            return absolute(source.url, request), None, None
        options = renditions.candidates(source, manifest) or [(source.url, manifest.width)]
        url, width = next(((u, w) for u, w in options if w >= SHARE_WIDTH), options[-1])
        height = max(1, round(width * manifest.height / manifest.width))
        return absolute(url, request), width, height
    if isinstance(value, str):
        return absolute(value, request), None, None
    address = getattr(value, "url", None)
    return (absolute(str(address), request), None, None) if address else ("", None, None)


def _locale() -> str:
    language = get_language() or ""
    if not language:
        return ""
    lang, _, region = language.replace("_", "-").partition("-")
    return f"{lang.lower()}_{region.upper()}" if region else lang.lower()


def resolve(context: Any, request: Any, head: Head | None = None) -> PageMeta:
    """The page's values, each from the first place that has one (see the module docstring)."""
    from karni_site.seo import page_seo
    from karni_site.sitesettings import get_site_settings

    head = head or Head()
    found = context.get("site")
    site = found if found is not None and found != "" else get_site_settings()
    entry = page_seo(request)
    given = context.get("seo")
    view: Mapping[str, Any] = given if isinstance(given, Mapping) else {}
    finder = import_string(str(conf.get("KARNI_SITE_SEO_OBJECT")))
    obj = finder(context, request)
    from_object = object_values(obj)
    site_name = str(getattr(site, "name", "") or "") or head.meta.get("og:site_name", "")

    title = _text(getattr(entry, "title", "") or view.get("title") or "")
    if not title and from_object.get("title"):
        title = _text(from_object["title"])
        pattern = str(conf.get("KARNI_SITE_TITLE_FORMAT") or "{title}")
        if site_name and site_name.lower() not in title.lower():
            title = pattern.format(title=title, site=site_name)
    title = title or (head.title or "") or site_name

    description = _text(getattr(entry, "description", "") or view.get("description") or "")
    if not description and from_object.get("description"):
        description = _shorten(_text(from_object["description"]))
    description = (
        description or head.meta.get("description", "") or _text(getattr(site, "tagline", "") or "")
    )

    image: Any = getattr(entry, "share_image", None) or view.get("image")
    image = image or from_object.get("image")
    image = image or head.meta.get("og:image") or head.meta.get("og:image:url")
    image = image or head.meta.get("twitter:image") or getattr(site, "share_image", None)
    image_url, image_width, image_height = _image(image, request) if image else ("", None, None)

    canonical: str = ""
    if "canonical" in view:
        canonical = absolute(str(view["canonical"] or ""), request)
    elif head.canonical:
        canonical = absolute(head.canonical, request)
    elif request is not None:
        canonical = absolute(getattr(request, "path", "") or "/", request)

    noindex = bool(getattr(entry, "noindex", False) or view.get("noindex"))
    noindex = noindex or "noindex" in head.meta.get("robots", "").lower()
    return PageMeta(
        title=title,
        description=description,
        canonical=canonical,
        image=image_url,
        image_alt=_text(view.get("image_alt") or head.meta.get("og:image:alt") or title),
        image_width=image_width,
        image_height=image_height,
        noindex=noindex,
        type=str(
            view.get("type") or from_object.get("type") or head.meta.get("og:type") or "website"
        ),
        twitter_card=head.meta.get("twitter:card")
        or ("summary_large_image" if image_url else "summary"),
        site_name=site_name,
        locale=head.meta.get("og:locale") or _locale(),
    )


def _jsonld(context: Any, request: Any) -> str:
    found = context.get("site")
    from karni_site.sitesettings import get_site_settings

    site = found if found is not None and found != "" else get_site_settings()
    builder = import_string(str(conf.get("KARNI_SITE_JSONLD")))
    data = builder(request, site)
    if not data:
        return ""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'<script type="application/ld+json">{text}</script>'


def render_head(context: Any, request: Any, markup: str) -> str:
    """The template's head markup with the page's title, tags and JSON-LD in place."""
    head = parse_head(markup)
    page = resolve(context, request, head)
    generated = page.tags()
    style = str(conf.get("KARNI_SITE_IMAGE_STYLE") or "")
    if style:
        generated.append(f"<style>{style}</style>")
    jsonld = _jsonld(context, request)
    if jsonld:
        generated.append(jsonld)
    return _assemble(head, generated)
