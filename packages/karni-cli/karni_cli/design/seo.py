"""Which of a design's ``<head>`` tags ``{% karni_seo %}`` writes itself.

``karni import design`` puts ``{% karni_seo %}`` in base.html where the
design's first such tag was, with the design's title and description
inside as the defaults (and any share image every page has). A tag the
tag writes from the page's title, description and address (``og:title``,
``og:description``, ``og:url`` and their Twitter twins) is dropped: the
tag writes it for every page. One a page has of its own (an ``og:image``)
goes into the page's ``{% block seo %}``. Every other head tag stays where
it was.

The names match karni_site.metadata.COVERED (the CLI does not import karni-site).
"""

from __future__ import annotations

from typing import Final

from karni_cli.design.parse import Node

__all__ = ["COVERED", "DERIVED", "covered", "derived"]

#: The ``<meta>`` names and properties {% karni_seo %} writes.
COVERED: Final = frozenset(
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
#: Those it writes from the page's own title, description and address, whatever a page says.
DERIVED: Final = frozenset(
    {"og:title", "og:description", "og:url", "twitter:title", "twitter:description"}
)


def _key(node: Node, source: str) -> str:
    attrs = node.attrs(source)
    return (attrs.get("property") or attrs.get("name") or "").strip().lower()


def covered(node: Node, source: str) -> bool:
    """Whether {% karni_seo %} writes this head element (title, description, canonical, share tags)."""
    if node.tag == "title":
        return True
    if node.tag == "link":
        return "canonical" in (node.attr(source, "rel") or "").lower().split()
    return node.tag == "meta" and _key(node, source) in COVERED


def derived(node: Node, source: str) -> bool:
    """Whether the tag writes this one from the page's title, description or address anyway."""
    return node.tag == "meta" and _key(node, source) in DERIVED
