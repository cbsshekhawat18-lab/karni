"""``{% karni_seo %}`` and ``{% image %}``: part of ``{% load karni_site %}``.

``{% karni_seo %}<title>...</title><meta name="description" ...>{% endkarni_seo %}``
    In base.html's ``<head>``, around the design's own title and
    description. Renders the page's title, description, canonical link,
    ``robots`` when it is hidden, Open Graph and Twitter tags, the site's
    JSON-LD and one CSS rule for images Karni sized. Each value comes from
    the admin's entry for the page, then ``seo`` in the context, then the
    page's object, then the tags written inside, then the site's settings
    (:mod:`karni_site.metadata`). A tag inside that it does not cover is
    kept. If anything fails, the tags inside are rendered as written.

``{% image obj.photo width=800 alt=obj.title %}``
    An ``<img>`` of an uploaded image: ``src``, ``srcset`` and ``sizes``
    from its WebP copies (:mod:`karni_site.renditions`), ``width`` and
    ``height`` in its proportions, ``loading="lazy"`` and
    ``decoding="async"``. ``alt`` is required (``alt=""`` for a decorative
    image). Any other ``name=value`` becomes an attribute, an underscore in
    the name a hyphen (``data_index=1`` is ``data-index="1"``).
    ``loading="eager"`` (or ``fetchpriority="high"``) for the image at the
    top of a page. ``sizes="..."`` replaces the one worked out from
    ``width``. An empty field renders nothing. Before the copies exist the
    original is shown.

Both are registered on the ``karni_site`` library by
:func:`register_tags`. Override / escape hatch: :func:`image_tag` builds
the same markup in Python, and the settings in the module README change
what both write.
"""

from __future__ import annotations

import logging
import re
from html import escape
from typing import Any

from django import template
from django.template.base import FilterExpression, Node, NodeList, Parser, Token
from django.template.context import Context
from django.utils.safestring import SafeString, mark_safe
from karni.errorcodes import docs_url

from karni_site import metadata, renditions

__all__ = ["ImageNode", "KarniSeoNode", "image_tag", "register_tags"]

logger = logging.getLogger("karni_site")
SYNTAX_CODE = "SITE019"
_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _syntax_error(message: str) -> template.TemplateSyntaxError:
    return template.TemplateSyntaxError(f"{SYNTAX_CODE}: {message} See {docs_url(SYNTAX_CODE)}")


def _request(context: Context) -> Any:
    request = getattr(context, "request", None)
    return request if request is not None else context.get("request")


# {% karni_seo %}


class KarniSeoNode(Node):
    child_nodelists = ("nodelist",)

    def __init__(self, nodelist: NodeList) -> None:
        self.nodelist = nodelist

    def render(self, context: Context) -> SafeString:
        markup = str(self.nodelist.render(context))
        try:
            return mark_safe(metadata.render_head(context, _request(context), markup))  # noqa: S308 - escaped values
        except Exception:
            logger.exception(
                "karni_site: {% karni_seo %} failed, the template's own tags are shown"
            )
            return mark_safe(markup)  # noqa: S308 - the template's own markup


def do_karni_seo(parser: Parser, token: Token) -> KarniSeoNode:
    """``{% karni_seo %}<the design's title and meta tags>{% endkarni_seo %}``."""
    if len(token.split_contents()) != 1:
        raise _syntax_error(
            "{% karni_seo %} takes nothing. Put the page's own <title> and <meta> tags between "
            "{% karni_seo %} and {% endkarni_seo %}: they are the defaults."
        )
    nodelist = parser.parse(("endkarni_seo",))
    parser.delete_first_token()
    return KarniSeoNode(nodelist)


# {% image %}


def _int(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def image_tag(
    value: Any,
    *,
    alt: str,
    width: Any = None,
    height: Any = None,
    sizes: str | None = None,
    loading: str | None = None,
    **attrs: Any,
) -> str:
    """The ``<img>`` markup ``{% image %}`` renders, or ``""`` for an empty field. Never raises."""
    source = renditions.source_of(value)
    if source is None:
        return ""
    fetch = str(attrs.get("fetchpriority") or "").lower()
    lazy = (loading or ("eager" if fetch == "high" else "lazy")).lower() == "lazy"
    found: dict[str, str | bool]
    try:
        found = dict(
            renditions.attributes(
                source, width=_int(width), height=_int(height), sizes=sizes or None, lazy=lazy
            )
        )
    except Exception:  # noqa: BLE001 - a broken storage shows the original
        logger.exception("karni_site: {% image %} could not size %s", source.name)
        found = {"src": source.url}
    found["alt"] = str(alt)
    if lazy or loading:
        found["loading"] = "lazy" if lazy else str(loading)
    found.setdefault("decoding", "async")
    found[renditions.MARKER] = ""
    for name, given in attrs.items():
        if given is None or given is False:
            continue
        key = name.replace("_", "-") if name.startswith(("data_", "aria_")) else name
        found[key] = True if given is True else str(given)
    parts = [
        name if value_ is True or name == renditions.MARKER else f'{name}="{escape(str(value_))}"'
        for name, value_ in found.items()
    ]
    return "<img " + " ".join(parts) + ">"


class ImageNode(Node):
    def __init__(self, source: FilterExpression, options: dict[str, FilterExpression]) -> None:
        self.source = source
        self.options = options

    def render(self, context: Context) -> SafeString:
        value = self.source.resolve(context)
        options = {name: expression.resolve(context) for name, expression in self.options.items()}
        alt = options.pop("alt", "")
        return mark_safe(image_tag(value, alt="" if alt is None else str(alt), **options))  # noqa: S308 - escaped


def do_image(parser: Parser, token: Token) -> ImageNode:
    """``{% image <file field> alt="..." [width=800] [name=value ...] %}``."""
    bits = token.split_contents()
    usage = (
        '{% image %} is written {% image obj.photo alt="What it shows" width=800 %}: the image, '
        "then name=value pairs, alt among them."
    )
    if len(bits) < 3:
        raise _syntax_error(usage)
    options: dict[str, FilterExpression] = {}
    for bit in bits[2:]:
        name, equals, value = bit.partition("=")
        if not equals or not _NAME.match(name) or not value:
            raise _syntax_error(f"{usage} Got {bit!r}.")
        if name in options:
            raise _syntax_error(f"{{% image %}} has {name}= twice.")
        options[name] = parser.compile_filter(value)
    if "alt" not in options:
        raise _syntax_error(
            '{% image %} needs alt="...": what the image shows, for people who cannot see it '
            'and for search engines. Write alt="" for an image that only decorates.'
        )
    return ImageNode(parser.compile_filter(bits[1]), options)


def register_tags(library: template.Library) -> None:
    """Add ``{% karni_seo %}`` and ``{% image %}`` to ``library`` (the ``karni_site`` one)."""
    library.tag("karni_seo", do_karni_seo)
    library.tag("image", do_image)
