"""The template tags and filters ``{% load karni_site %}`` gives a page, in one place.

``karni explain image`` (or ``"{% image %}"``) prints an entry, and the table
in docs/public-site.md (*The karni-site module*) is rendered from
:func:`markdown` by ``scripts/gen_reference.py``. ``tests/test_tagref.py``
fails when a tag the library registers has no entry here, or an entry names
a tag it does not register.

Stdlib only, and nothing is imported to be read: karni-cli loads this file by
path, so ``karni explain`` works without Django.

    python -m karni_site.tagref --explain image [--json] [--docs-base URL]
    python -m karni_site.tagref --markdown
"""

# ruff: noqa: E501  (the entries are prose)
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Final

__all__ = ["DOCS_PAGE", "TAGS", "Tag", "lookup", "markdown", "normalise", "render"]

#: The docs page the tags are described on (``docs/public-site.md``).
DOCS_PAGE: Final = "public-site"


@dataclass(frozen=True)
class Tag:
    """One tag or filter: how it is written, what it does, where the docs say more."""

    name: str
    kind: str  # "tag" or "filter"
    syntax: str
    text: str
    anchor: str  # on DOCS_PAGE

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


TAGS: Final[tuple[Tag, ...]] = (
    Tag(
        "karni_seo",
        "tag",
        '{% karni_seo %}<title>...</title><meta name="description" content="...">{% endkarni_seo %}',
        "In base.html's <head>, around the design's own title and description. It writes the page's title, description, canonical link, robots for a hidden page, the Open Graph and Twitter tags and the site's JSON-LD. Each value is the first of: the admin's entry for the page (Page titles and descriptions), `seo` in the view's context (a dict), the page's row, the tags written inside, the site's settings. The page's row is `seo` or `object` in the context when it is a row, else the row in the context whose get_absolute_url() is the page's path. Its fields are the ones `class Karni: seo` names, else seo_title, seo_description and seo_image, else a title, description or image field by a usual name. A detail page that has its row in the context needs no title of its own.",
        "seo-by-default",
    ),
    Tag(
        "image",
        "tag",
        "{% image obj.photo alt=obj.title width=800 %}",
        'An <img> of an uploaded image: src, srcset and sizes from its WebP copies, width and height in its proportions, lazy loading. alt is required (alt="" for an image that only decorates). eager=True, or eager=forloop.first in a loop, for the image at the top of a page. sizes="..." replaces the one worked out from width. Any other name=value becomes an attribute, an underscore a hyphen (data_index=1 is data-index="1"). An empty field renders nothing, and the original is shown until its copies exist.',
        "seo-by-default",
    ),
    Tag(
        "editable",
        "tag",
        '{% editable "home.intro" %}<default HTML>{% endeditable %}',
        "Text the client edits in the admin. The content is the default: the first render stores it under the key, and the block follows the template until someone edits it. An edited block shows the edited HTML, cleaned to the inline markup KARNI_SITE_INLINE_TAGS allows. The key's first part is the page the admin groups it under.",
        "everything-the-client-edits",
    ),
    Tag(
        "editable_image",
        "tag",
        '{% editable_image "home.hero" %}<img src="..." alt="...">{% endeditable_image %}',
        "An image the client replaces. The design's markup stays: an upload changes the <img>'s src (its srcset and <source> elements go), an edited alternative text its alt. With url after the key, it holds a bare address instead, for a style=\"background-image: url(...)\".",
        "everything-the-client-edits",
    ),
    Tag(
        "site_image",
        "tag",
        '{% site_image "logo" %}<img src="..." alt="...">{% endsite_image %}',
        "An image from a file field of the site's settings (logo, favicon, share_image): the design's image until one is uploaded in the admin.",
        "everything-the-client-edits",
    ),
    Tag(
        "site_defaults",
        "tag",
        '{% site_defaults name="Crumb & Co" phone="01234 567890" %}',
        "The design's values for the site's details (`site` in every template), stored the first time and followed until someone changes them in the admin. It renders nothing. Put it at the top of the layout, before anything reads `site`.",
        "everything-the-client-edits",
    ),
    Tag(
        "get_menu",
        "tag",
        '{% get_menu "header" seed="website/menus/header.html" as items %}',
        "A menu's items for a {% for %} loop in the design's markup: item.title, item.url, item.new_tab, item.current (this page), item.active (this page or one under it) and item.children. With seed, a menu the database does not have yet is created from the links in that template. An item with children from a model lists that model's rows, so a new row appears in the menu by itself, and with no title or address of its own it lists them in its place. karni import design --editable --map seeds a list of a model's detail pages that way.",
        "everything-the-client-edits",
    ),
    Tag(
        "ifactive",
        "tag",
        '{% ifactive "website:about" %} class="active"{% else %}...{% endifactive %}',
        'Renders its content when one of its patterns names the current page, else the {% else %} part. A pattern is a URL name, wildcards allowed ("website:service_*"), or a path ("/about/", "/blog/*"). Put it where the design marks the current page: a class, a token inside a class, or a whole attribute. It needs the request in the context. karni check reports a name no URL has (SITE002).',
        "the-karni-site-module",
    ),
    Tag(
        "karni_form",
        "tag",
        '{% karni_form "contact" button="Send" classes="bootstrap" %}',
        "A public form that works with and without JavaScript: the fields a visitor fills (the writable fields of the form viewset's create serializer) with labels, limits and errors, the CSRF token and the honeypot. It posts through the viewset's own create, so the access declaration, rate limit and validation are the API's. Options such as fields, rows, labels, widgets, classes, button and editable fit it to the design. Also {% load karni_forms %}.",
        "the-tag",
    ),
    Tag(
        "csp_hash",
        "tag",
        "<script>{% csp_hash %}...{% endcsp_hash %}</script>",
        "Renders its content unchanged and adds its SHA-256 hash to the script-src of this response's Content-Security-Policy, so the design's inline script runs under Karni's policy. {% csp_hash attribute %} is for an event handler attribute (onclick=\"...\").",
        "the-design-under-the-content-security-policy",
    ),
    Tag(
        "csp_allow",
        "tag",
        '{% csp_allow "style-src https://fonts.googleapis.com" "font-src https://fonts.gstatic.com" %}',
        "Adds sources to this response's Content-Security-Policy, one directive per argument, next to the markup that loads from that origin. It renders nothing. KARNI_CSP adds them site-wide instead.",
        "the-design-under-the-content-security-policy",
    ),
    Tag(
        "highlight",
        "filter",
        "{{ value|highlight }}",
        'The words a field keeps between the highlight markers (==marked words==), in KARNI_SITE_HIGHLIGHT\'s tag and class, everything else escaped. |highlight:"em" names another markup for one value, |highlight:"" drops the marks, and a backslash before a marker (\\==) keeps it as typed.',
        "the-karni-site-module",
    ),
)


def normalise(text: str) -> str:
    """``"{% image %}"``, ``"image"``, ``"|highlight"``, ``"endeditable"``: the tag's name."""
    name = text.strip()
    for wrapper in ("{%", "%}", "{{", "}}"):
        name = name.replace(wrapper, " ")
    words = name.split()
    name = words[0] if words else ""
    name = name.lstrip("|").split(":", 1)[0].lower()
    if name.startswith("end") and any(tag.name == name[3:] for tag in TAGS):
        name = name[3:]
    return name


def lookup(text: str) -> Tag | None:
    """The entry for a tag or filter, written any way :func:`normalise` reads."""
    name = normalise(text)
    return next((tag for tag in TAGS if tag.name == name), None)


def render(tag: Tag, url: str = "") -> str:
    """The text ``karni explain`` prints."""
    what = "template tag" if tag.kind == "tag" else "template filter"
    return "\n".join(
        [
            f"{tag.name}  (a karni-site {what}: {{% load karni_site %}})",
            "",
            f"Write:  {tag.syntax}",
            f"What:   {tag.text}",
            f"Docs:   {url or f'{DOCS_PAGE}.md#{tag.anchor}'}",
        ]
    )


def _cell(text: str) -> str:
    """A table cell: ``<`` and ``>`` outside code spans as entities, every pipe escaped."""
    parts = text.split("`")
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("<", "&lt;").replace(">", "&gt;")
    return "`".join(parts).replace("|", "\\|")


def markdown() -> list[str]:
    """The table docs/public-site.md shows: every tag and filter, as here."""
    lines = ["| Tag | Write | What it does |", "| --- | --- | --- |"]
    for tag in TAGS:
        name = f"`{{% {tag.name} %}}`" if tag.kind == "tag" else f"`|{tag.name}`"
        lines.append(f"| {_cell(name)} | {_cell(f'`{tag.syntax}`')} | {_cell(tag.text)} |")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--explain", metavar="TAG")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--docs-base", default="", help="the published docs' address")
    args = parser.parse_args(argv)
    if args.markdown:
        print("\n".join(markdown()))
        return 0
    if args.explain:
        tag = lookup(args.explain)
        if tag is None:
            return 1
        url = f"{args.docs_base}{DOCS_PAGE}/#{tag.anchor}" if args.docs_base else ""
        if args.json:
            print(json.dumps({**tag.to_dict(), **({"url": url} if url else {})}, indent=2))
        else:
            print(render(tag, url))
        return 0
    parser.print_usage()
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
