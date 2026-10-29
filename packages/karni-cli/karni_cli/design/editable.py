"""``karni import design --editable``: every word and image of the design editable in the admin.

The import keeps the design's markup and marks what a client may change,
with karni-site's tags (``karni_site.templatetags.karni_site``):

* **Text.** Each run of text, with the inline markup a block keeps (bold,
  emphasis, plain links, line breaks, the design's highlight), becomes
  ``{% editable "<page>.<section>.<name>" %}...{% endeditable %}``. A run
  inside an element with other markup (a button with an icon, a label
  before an address) is a block of its own, so the markup around it stays
  the template's.
* **Images.** An ``<img>`` or ``<picture>`` becomes ``{% editable_image %}``
  around the design's own markup, and an image in a ``style`` attribute's
  ``url(...)`` an ``{% editable_image ... url %}``. The site's logo (an
  image in the header or footer that links home, or named like a logo) and
  the favicon come from the site's settings (``{% site_image %}``).
* **The site's details.** The site's name wherever a text is exactly the
  name, the first phone number (``tel:``), email address (``mailto:``) and
  map link, and links to social profiles come from ``site``. Their values
  are the defaults of one ``{% site_defaults %}`` at the top of base.html,
  with the logo, the favicon and the share image as static paths: the
  ``og:image`` every page has, or else an image no page uses that is named
  for sharing (``share.jpg``, ``og-image.png``).
* **Opening hours.** A table, list or lines of days and times
  (:mod:`karni_cli.design.hours`) become a loop over ``site.hours`` in the
  design's own markup, seeded once with ``{% site_defaults hours="..." %}``.
  When the footer and the contact page both show them, both loop over the
  same rows, seeded from the one whose markup parts days from times. Lists
  that show different hours stay text blocks, and the report says so.
* **Menus.** A navigation whose items share one markup (a list of links,
  nested lists for submenus, or bare links side by side) becomes
  ``{% get_menu %}`` and a ``{% for %}`` loop in that markup, seeded from
  the design's own links (``templates/<app>/menus/<name>.html``). One whose
  items differ keeps its markup, and its link texts are blocks.

Keys are readable (the page, the section, the first words of the text) and
stable: ``.karni/design.json`` records each key with where it was, and a
later import gives the same place the same key, so a client's edits stay
attached when the designer changes the text.

The planning works on the parsed source (:mod:`karni_cli.design.parse`) and
produces an :class:`Overlay` per page: text inserted at source offsets,
spans replaced and start tags transformed, which the site renderer applies
while it writes each template.
"""

from __future__ import annotations

import posixpath
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Final
from urllib.parse import urlsplit

from karni_cli.design import compare, hours, rewrite
from karni_cli.design.parse import Node, Token, attributes, collapse

__all__ = [
    "Editable",
    "Overlay",
    "detect_highlight",
    "key_part",
    "short_name",
]

#: Elements whose content is never editable text.
SKIP: Final = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "math",
        "iframe",
        "object",
        "embed",
        "video",
        "audio",
        "canvas",
        "select",
        "option",
        "textarea",
        "title",
        "head",
        "pre",  # its whitespace is its meaning: an edit as plain text would lose it
    }
)
#: Inline elements a block keeps, with the attributes they may carry (karni-site's defaults).
INLINE: Final[dict[str, frozenset[str]]] = {
    "b": frozenset(),
    "strong": frozenset(),
    "i": frozenset(),
    "em": frozenset(),
    "br": frozenset(),
    "mark": frozenset(),
    "a": frozenset({"href", "title", "target", "rel"}),
}
#: Social networks by host, for ``site.social.<name>``.
SOCIAL_HOSTS: Final[dict[str, str]] = {
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "instagram.com": "instagram",
    "twitter.com": "x",
    "x.com": "x",
    "linkedin.com": "linkedin",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "tiktok.com": "tiktok",
    "pinterest.com": "pinterest",
    "github.com": "github",
    "gitlab.com": "gitlab",
    "threads.net": "threads",
    "bsky.app": "bluesky",
    "mastodon.social": "mastodon",
    "vimeo.com": "vimeo",
    "behance.net": "behance",
    "dribbble.com": "dribbble",
    "wa.me": "whatsapp",
    "whatsapp.com": "whatsapp",
    "tripadvisor.com": "tripadvisor",
    "yelp.com": "yelp",
    "houzz.com": "houzz",
}
_MARK: Final = "__karni_menu_item__"
_HEADING = re.compile(r"h[1-6]$")
_HAS_WORD = re.compile(r"[^\W_]")
_STATIC = re.compile(r"\{% static (['\"])(?P<path>[^'\"]+)\1 %\}")
_WORDS = re.compile(r"[a-z0-9]+")
_TEMPLATE = re.compile(r"\{%|%\}|\{\{|\}\}|\{#|#\}")
#: The head tags that name a page's share image.
_SHARE_TAGS: Final = frozenset({"og:image", "og:image:url", "og:image:secure_url", "twitter:image"})
#: A file name that says the image is for sharing: share.jpg, og-image.png, social-card.webp.
_SHARE_NAME = re.compile(r"(?:^|[-_.\s])(?:share|og|opengraph|social)(?:[-_.\s]|$)", re.IGNORECASE)
_RASTER: Final = (".jpg", ".jpeg", ".png", ".webp")
#: Inline elements a design highlights words of a heading with.
_HIGHLIGHT_TAGS: Final = frozenset({"span", "em", "strong", "mark", "b", "i"})
#: The marker KARNI_SITE_HIGHLIGHT reads around highlighted words (the import writes it).
MARKER: Final = "=="


# keys


def key_part(text: str, fallback: str = "section") -> str:
    """``text`` as one part of a block key: lowercase letters, digits and underscores."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    part = "_".join(_WORDS.findall(ascii_text.lower()))
    return part[:40].strip("_") or fallback


def short_name(text: str, fallback: str) -> str:
    """The first words of ``text`` as a key's last part: ``"Bread worth the walk"`` → ``bread_worth_the_walk``."""
    ascii_text = unicodedata.normalize("NFKD", unescape(text)).encode("ascii", "ignore").decode()
    words = _WORDS.findall(ascii_text.lower())[:4]
    return "_".join(words)[:40].strip("_") or fallback


# the overlay the renderer applies


Render = Callable[[Any, Any, Any, int], str]


@dataclass
class Overlay:
    """What the editable rewrite changes in one page's source, by offset.

    ``opens`` is written before the character at an offset, ``closes`` after
    the character before it. ``replace`` replaces a span that starts and ends
    on token boundaries (a callable gets the renderer, the page, the
    variations and the span's start). ``text_replace`` replaces a span inside
    one text token. ``tags`` transform the rewritten start tag of the element
    at an offset.
    """

    opens: dict[int, list[str]] = field(default_factory=dict)
    closes: dict[int, list[str]] = field(default_factory=dict)
    replace: dict[int, tuple[int, str | Render]] = field(default_factory=dict)
    text_replace: dict[int, tuple[int, str]] = field(default_factory=dict)
    tags: dict[int, list[Callable[[str], str]]] = field(default_factory=dict)

    def wrap(self, start: int, end: int, before: str, after: str) -> None:
        self.opens.setdefault(start, []).append(before)
        self.closes.setdefault(end, []).insert(0, after)

    def tag_transform(self, start: int, transform: Callable[[str], str]) -> None:
        self.tags.setdefault(start, []).append(transform)

    def before(self, offset: int) -> str:
        return "".join(self.opens.get(offset, ()))

    def after(self, offset: int) -> str:
        return "".join(self.closes.get(offset, ()))

    def replacement(self, offset: int) -> tuple[int, str | Render] | None:
        return self.replace.get(offset)

    def tag(self, offset: int, text: str) -> str:
        for transform in self.tags.get(offset, ()):
            text = transform(text)
        return text

    def text(self, token: Token, source: str) -> str:
        """A text token, with what falls inside it inserted or replaced."""
        start, end = token.start, token.end
        points = sorted(
            {o for o in self.opens if start < o < end}
            | {o for o in self.closes if start < o < end}
            | {o for o in self.text_replace if start <= o < end}
        )
        out: list[str] = []
        position = start
        for point in points:
            if point < position:
                continue
            out.append(rewrite.escape_template_syntax(source[position:point]))
            if point > start:
                out.append(self.after(point))
            if point in self.text_replace:
                stop, value = self.text_replace[point]
                if point > start:
                    out.append(self.before(point))
                out.append(value)
                position = stop
                continue
            position = point
            if point > start:
                out.append(self.before(point))
        out.append(rewrite.escape_template_syntax(source[position:end]))
        return "".join(out)


# what the design highlights


def detect_highlight(pages: Iterable[Any]) -> tuple[str, str] | None:
    """The ``(tag, class)`` a design wraps highlighted words of its headings in, or ``None``.

    An inline element around some of a heading's words, with exactly one
    class (``<span class="highlight">``) or none (``<em>``), on two or more
    headings. The most common one wins. Words a design marks with
    characters (``*whole*``) are text, not a highlight.
    """
    found: Counter[tuple[str, str]] = Counter()
    for page in pages:
        body = page.doc.body_or_root()
        for heading in body.iter_elements():
            if not _HEADING.match(heading.tag):
                continue
            whole = heading.plain_text(page.text)
            for child in heading.elements():
                if child.tag not in _HIGHLIGHT_TAGS:
                    continue
                inner = child.plain_text(page.text)
                if not inner or inner == whole:
                    continue  # the whole heading is not a highlight
                attrs = child.attrs(page.text)
                classes = (attrs.get("class") or "").split()
                if set(attrs) == {"class"} and len(classes) == 1:
                    found[(child.tag, classes[0])] += 1
                elif not attrs and child.tag != "span":
                    found[(child.tag, "")] += 1
    if not found:
        return None
    best, count = found.most_common(1)[0]
    return best if count >= 2 else None


# planning


@dataclass
class _Item:
    """Something that gets a key: a text run or an image."""

    page: Any
    path: str
    prefix: str
    section: str
    short: str
    apply: Callable[[str], None]
    key: str = ""
    #: The source the item holds: two detail pages share a key for the same text.
    text: str = ""


@dataclass
class _Menu:
    page: Any
    node: Node
    name: str
    kind: str  # "list" or "flat"
    items: list[Node]
    nested: dict[int, Node]  # li start -> its nested list
    group: Any = None  # the shared group it is rendered from, if any


@dataclass
class Report:
    blocks: int = 0
    images: int = 0
    menus: list[str] = field(default_factory=list)
    site: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class Editable:
    """Plans the editable rewrite of one import (see the module docstring)."""

    def __init__(
        self,
        app: str,
        mapped: rewrite.Mapped,
        *,
        site_name: str,
        highlight: tuple[str, str] | None,
        previous: Mapping[str, Any] | None = None,
        rows: Mapping[str, set[int]] | None = None,
        shared: Mapping[str, str] | None = None,
    ) -> None:
        self.app = app
        #: Page path → the key prefix of a model's detail pages (``course``), which
        #: share their blocks' keys (:func:`karni_cli.design.regions.detail_pages`).
        self.shared: dict[str, str] = {
            page: key_part(model, "page") for page, model in (shared or {}).items()
        }
        #: Page path → starts of the elements a content map reads into rows
        #: (:mod:`karni_cli.design.regions`): rendered from the rows, so never a block.
        self.rows: dict[str, set[int]] = {page: set(s) for page, s in (rows or {}).items()}
        self.left_out: dict[str, int] = {}
        self.mapped = mapped
        self.site_name = collapse(unescape(site_name))
        self.highlight = highlight
        record = dict((previous or {}).get("editable") or {})
        self.previous: dict[str, str] = dict(record.get("keys") or {})
        self.items: list[_Item] = []
        self.menus: list[_Menu] = []
        self.defaults: dict[str, str] = {}
        if self.site_name and not _TEMPLATE.search(self.site_name):
            self.defaults["name"] = self.site_name
        self.report = Report()
        self.markers: set[str] = set()
        self.logo_src: str | None = None
        self.menu_names: set[str] = set()
        self.keys: dict[str, str] = {}
        #: Page path → starts of the elements a loop over site.hours replaced (never walked).
        self.hours_parts: dict[str, set[int]] = {}

    # entry points

    def prepare(self, pages: list[Any], layout: compare.Layout, by_key: Mapping[str, Any]) -> None:
        """Walk every region the templates are made of and fill each page's overlay."""
        for page in pages:
            page.overlay = Overlay()
            page.element_starts = [
                token.start for token in page.doc.tokens if token.kind in ("start", "startend")
            ]
        self._find_markers(layout, by_key)
        shared = [*layout.prefix, *layout.suffix, *layout.partials]
        self._find_logo(shared, by_key)
        regions: list[tuple[Any, Node, str, str, str, Any]] = []
        for group in shared:
            page = by_key[group.reference]
            node = group.instances[group.reference].node
            regions.append(
                (page, node, "shared", key_part(group.name), f"shared:{group.name}", group)
            )
        for page in pages:
            plan = layout.pages[page.path]
            prefix = self.shared.get(page.path) or key_part(
                page.name or f"error_{page.error}", "page"
            )
            for name, block in plan.overrides.items():
                if block is not None:
                    regions.append(
                        (
                            page,
                            block.node,
                            prefix,
                            key_part(name),
                            f"{page.path}:{name}",
                            "override",
                        )
                    )
            for item in plan.content:
                if isinstance(item, compare.Block):
                    regions.append(
                        (
                            page,
                            item.node,
                            prefix,
                            key_part(item.name),
                            f"{page.path}:{item.name}",
                            None,
                        )
                    )
        self._plan_hours(regions)
        for page, node, prefix, section, region, group in regions:
            in_layout = group is not None
            self._walk(
                page,
                node,
                prefix,
                section,
                region,
                node,
                in_layout,
                group if group != "override" else None,
            )
        if pages:
            self._head(pages[0], layout, by_key)
        self._assign_keys()

    def finish(self, templates: dict[str, str], base_name: str, renderer: Any) -> dict[str, Any]:
        """Put ``{% site_defaults %}`` into base.html, add the menus' seeds, return the record."""
        base_rel = f"templates/{base_name}"
        base = templates[base_rel]
        load = "{% load static karni_site %}"
        if self.defaults and base.startswith(load):
            images = ("logo", "favicon", "share_image")  # the static paths go last
            ordered = sorted(self.defaults.items(), key=lambda item: item[0] in images)
            pairs = " ".join(f'{name}="{_quoted(value)}"' for name, value in ordered)
            templates[base_rel] = load + "{% site_defaults " + pairs + " %}" + base[len(load) :]
        for menu in self.menus:
            original = menu.page.overlay
            try:
                if menu.group is not None:
                    group = menu.group
                    variations = compare.element_variations(
                        group, {k: renderer.by_key[k].text for k in group.instances}
                    )
                    root = group.instances[group.reference].node
                    markup = _slice_rendered(renderer, menu.page, root, menu.node, variations)
                else:
                    menu.page.overlay = None
                    markup = renderer.span(menu.page, menu.node.start, menu.node.end)
            finally:
                menu.page.overlay = original
            templates[f"templates/{self._seed(menu.name)}"] = load + "\n" + markup + "\n"
        self.report.site = dict(self.defaults)
        return {
            "enabled": True,
            "highlight": {"tag": self.highlight[0], "class": self.highlight[1]}
            if self.highlight
            else None,
            "keys": dict(sorted(self.keys.items())),
            "menus": {menu.name: self._seed(menu.name) for menu in self.menus},
            "site": dict(self.defaults),
        }

    def _seed(self, name: str) -> str:
        return f"{self.app}/menus/{name}.html"

    # opening hours

    def _plan_hours(self, regions: list[tuple[Any, Node, str, str, str, Any]]) -> None:
        """Make the design's opening hours ``site.hours``, when every list of them agrees."""
        found: list[tuple[Any, hours.HoursList, bool]] = []
        for page, root, _prefix, _section, _region, group in regions:
            inside: list[Node] = []
            for node in root.iter_elements():
                if node.tag in SKIP or self._row(page, node):
                    continue
                if any(node.start >= done.start and node.end <= done.end for done in inside):
                    continue
                listed = hours.find(node, page.text)
                if listed is not None and self._plain_rows(listed, page):
                    found.append((page, listed, group is not None and group != "override"))
                    inside.append(node)
        if not found:
            return
        where = [self._where(page, listed, shared) for page, listed, shared in found]
        first = found[0][1]
        if not all(hours.same_hours(first, listed) for _page, listed, _shared in found):
            self.report.notes.append(
                f"opening hours: {' and '.join(where)} show different hours, so they stay text "
                "blocks. Loop over site.hours by hand where they are the same hours."
            )
            return
        seed = max(found, key=lambda entry: entry[1].explicit)[1]
        text = "|".join(f"{days}={times}" for days, times in seed.rows)
        if any(char in "".join(d + t for d, t in seed.rows) for char in '|="'):
            return
        self.defaults["hours"] = collapse(unescape(text))
        for page, listed, _shared in found:
            self._loop_hours(page, listed)
        shown = ", ".join(f"{days} {times}" for days, times in seed.rows)
        note = (
            f"opening hours: {' and '.join(where)} now loop over site.hours, seeded from "
            f"{self._where(*next((p, h, sh) for p, h, sh in found if h is seed))} ({shown}): "
            "the client enters them once, in Site settings."
        )
        other = [w for (_p, h, _s), w in zip(found, where, strict=True) if h.rows != seed.rows]
        if other:
            named = " and ".join(other)
            note += f" {named[:1].upper()}{named[1:]} wrote them another way, and now shows these."
        self.report.notes.append(note)

    def _plain_rows(self, listed: hours.HoursList, page: Any) -> bool:
        """Whether every cell of the list holds text only (its markup can loop as it is)."""
        return all(
            all(child.kind == "text" for child in cell.children)
            for pair in listed.cells
            for cell in pair
        )

    def _where(self, page: Any, listed: hours.HoursList, shared: bool) -> str:
        if shared:
            return "the layout shared by every page"
        line = page.text.count("\n", 0, listed.node.start) + 1
        return f"{page.path}:{line}"

    def _loop_hours(self, page: Any, listed: hours.HoursList) -> None:
        """Replace the list's rows with one row's markup looped over ``site.hours``."""
        text = page.text
        esc = rewrite.escape_template_syntax
        parts = self.hours_parts.setdefault(page.path, set())
        overlay: Overlay = page.overlay
        if listed.kind == "lines":
            begin, finish = listed.node.inner
            breaks = [child for child in listed.node.children if child.kind == "element"]
            brk = text[breaks[0].start : breaks[0].end] if breaks else "<br>"
            lead = text[begin:finish][: len(text[begin:finish]) - len(text[begin:finish].lstrip())]
            tail = text[begin:finish][len(text[begin:finish].rstrip()) :]
            loop = (
                lead + "{% for row in site.hours %}{{ row.days }} {{ row.times }}"
                "{% if not forloop.last %}" + brk + "{% endif %}{% endfor %}" + tail
            )
            overlay.replace[begin] = (finish, loop)
            parts.add(listed.node.start)
            return
        items = listed.items
        if listed.kind == "dl":
            first_end = listed.cells[0][1].end
            last_end = listed.cells[-1][1].end
            between = text[first_end : items[1].start] if len(items) > 1 else ""
        else:
            first_end, last_end = items[0].end, items[-1].end
            between = text[items[0].end : items[1].start] if len(items) > 1 else ""
        start = items[0].start
        markup: list[str] = []
        position = start
        if listed.kind == "list":
            inner = items[0].inner
            markup += [esc(text[start : inner[0]]), "{{ row.days }} {{ row.times }}"]
            position = inner[1]
        else:
            days, times = listed.cells[0]
            for cell, variable in ((days, "{{ row.days }}"), (times, "{{ row.times }}")):
                inner = cell.inner
                markup += [esc(text[position : inner[0]]), variable]
                position = inner[1]
        markup.append(esc(text[position:first_end]))
        loop = (
            "{% for row in site.hours %}"
            + "".join(markup)
            + "{% if not forloop.last %}"
            + esc(between)
            + "{% endif %}{% endfor %}"
        )
        overlay.replace[start] = (last_end, loop)
        for item in items:
            parts.add(item.start)
        for pair in listed.cells:
            parts.update(cell.start for cell in pair)

    # the share image

    def share_default(self, page: Any, node: Node) -> bool:
        """Take a shared ``og:image`` of a design file as the site's default share image.

        ``True`` when ``node`` is one: base.html then leaves it out of
        ``{% karni_seo %}``, which writes the site's share image instead.
        """
        if node.tag != "meta":
            return False
        attrs = node.attrs(page.text)
        key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
        if key not in _SHARE_TAGS:
            return False
        ref = self.mapped.resolve(unescape(attrs.get("content") or ""), page.dir)
        if ref.kind != "asset":
            return False
        if "share_image" not in self.defaults:
            self.defaults["share_image"] = f"{self.app}/{ref.path}"
            self.report.notes.append(
                f"share image: the {key} every page has ({ref.path}) is the site's default "
                "(share_image in {% site_defaults %}). The client replaces it in Site settings."
            )
        return True

    def share_fallback(self, unused: Iterable[str]) -> None:
        """Without an ``og:image``, the one image no page uses that is named for sharing."""
        if "share_image" in self.defaults:
            return
        named = [
            path
            for path in unused
            if path.lower().endswith(_RASTER)
            and _SHARE_NAME.search(posixpath.basename(path).rsplit(".", 1)[0])
        ]
        if len(named) != 1:
            return
        self.defaults["share_image"] = f"{self.app}/{named[0]}"
        self.report.notes.append(
            f"share image: no page has an og:image, and {named[0]}, which no page uses, is named "
            "for sharing: it is the site's default (share_image in {% site_defaults %}). "
            "Remove it there if it is not."
        )

    # the current-page markers the import found, so menu items compare without them

    def _find_markers(self, layout: compare.Layout, by_key: Mapping[str, Any]) -> None:
        for group in layout.groups():
            variations = compare.element_variations(
                group, {k: by_key[k].text for k in group.instances}
            )
            for variation in variations.values():
                for token, members in variation.class_tokens.items():
                    if len(members) != len(variation.pages):
                        self.markers.add(token)

    def _find_logo(self, shared: list[compare.Group], by_key: Mapping[str, Any]) -> None:
        found: Counter[str] = Counter()
        for group in shared:
            page = by_key[group.reference]
            for node in group.instances[group.reference].node.iter_elements():
                if node.tag != "img":
                    continue
                src = node.attr(page.text, "src") or ""
                ref = self.mapped.resolve(src, page.dir)
                if ref.kind != "asset":
                    continue
                named = "logo" in posixpath.basename(ref.path).lower()
                if named or self._links_home(node, page):
                    found[ref.path] += 1
        if found:
            self.logo_src = found.most_common(1)[0][0]
            self.defaults.setdefault("logo", f"{self.app}/{self.logo_src}")

    def _links_home(self, node: Node, page: Any) -> bool:
        parent = node.parent
        while parent is not None and parent.kind == "element":
            if parent.tag == "a":
                ref = self.mapped.resolve(parent.attr(page.text, "href") or "", page.dir)
                return ref.kind == "page" and self.mapped.pages.get(ref.path) == "home"
            parent = parent.parent
        return False

    # the walk

    def _row(self, page: Any, node: Node) -> bool:
        """Whether ``node`` is content the map reads into rows (left without blocks)."""
        return node.start in self.rows.get(page.path, ())

    def _inline(self, node: Node, page: Any) -> bool:
        """Whether ``node`` can be inside a text block as it is."""
        if node.kind == "text":
            return True
        if node.kind != "element" or self._row(page, node):
            return False
        attrs = node.attrs(page.text)
        allowed = INLINE.get(node.tag)
        if self.highlight and node.tag == self.highlight[0] and attrs.get("class") is not None:
            if set(attrs) != {"class"} or (attrs.get("class") or "").split() != [self.highlight[1]]:
                return False
        elif allowed is None or not set(attrs) <= allowed:
            return False
        if node.tag == "a":
            href = attrs.get("href")
            if href is None or self._special(href, page) is not None:
                return False
            if re.match(r"\s*javascript:", href, re.IGNORECASE):
                return False
        return all(self._inline(child, page) for child in node.children)

    def _special(self, href: str, page: Any) -> tuple[str, str] | None:
        """``("phone"|"email"|"map"|"social", value)`` for a link the site's details hold."""
        value = href.strip()
        lower = value.lower()
        if lower.startswith("tel:"):
            return "phone", value[4:]
        if lower.startswith("mailto:"):
            return "email", value[7:]
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https"):
            return None
        host = (parts.hostname or "").lower().removeprefix("www.")
        path = parts.path.lower()
        if (
            host.startswith("maps.")
            or (host.startswith("google.") and path.startswith("/maps"))
            or (host == "goo.gl" and path.startswith("/maps"))
            or host.endswith("openstreetmap.org")
            or (host == "bing.com" and path.startswith("/maps"))
        ):
            return "map", value
        for known, name in SOCIAL_HOSTS.items():
            if host == known or host.endswith("." + known):
                return "social", name
        return None

    def _walk(
        self,
        page: Any,
        node: Node,
        prefix: str,
        section: str,
        region: str,
        root: Node,
        in_layout: bool,
        group: Any,
    ) -> None:
        if node.kind != "element" or node.tag in SKIP:
            return
        if node.start in self.hours_parts.get(page.path, ()):
            return  # a row of opening hours: rendered from site.hours
        if self._row(page, node):
            self.left_out[page.path] = self.left_out.get(page.path, 0) + 1
            return
        menu = self._menu(page, node, prefix, section, root, in_layout, group)
        if menu is not None:
            return
        if node.tag in ("img", "picture"):
            self._image(page, node, prefix, section, region, root, in_layout)
            return
        self._style_images(page, node, prefix, section, region, root)
        if node.tag == "a":
            special = self._special(node.attr(page.text, "href") or "", page)
            if special is not None:
                self._special_link(
                    page, node, special, prefix, section, region, root, in_layout, group
                )
                return
        run: list[Node] = []
        index = 0

        def flush() -> None:
            nonlocal index
            if run:
                self._text_run(
                    page, list(run), prefix, section, f"{region}|{_path(root, node)}#{index}"
                )
                index += 1
                run.clear()

        for child in node.children:
            if child.kind == "text" or (child.kind == "element" and self._inline(child, page)):
                run.append(child)
                continue
            flush()
            if child.kind == "element":
                self._walk(page, child, prefix, section, region, root, in_layout, group)
        flush()

    def _text_run(self, page: Any, nodes: list[Node], prefix: str, section: str, path: str) -> None:
        text = page.text
        raw = text[nodes[0].start : nodes[-1].end]
        plain = collapse(unescape(re.sub(r"<[^>]*>", " ", raw)))
        if not _HAS_WORD.search(plain):
            return
        start = nodes[0].start
        end = nodes[-1].end
        if nodes[0].kind == "text":
            start += len(raw) - len(raw.lstrip())
        if nodes[-1].kind == "text":
            end -= len(raw) - len(raw.rstrip())
        if start >= end:
            return
        overlay: Overlay = page.overlay
        single = len(nodes) == 1 and nodes[0].kind == "text"
        if single and self.site_name and plain == self.site_name:
            overlay.text_replace[start] = (end, "{{ site.name }}")
            return

        literal = [
            offset
            for node in nodes
            for token in _text_tokens(node)
            for offset in _marker_offsets(text, token.start, token.end)
            if start <= offset and offset + len(MARKER) <= end
        ]

        def apply(key: str) -> None:
            overlay.wrap(start, end, '{% editable "' + key + '" %}', "{% endeditable %}")
            for offset in literal:  # the design's own "==", kept as text (karni_site: \\==)
                overlay.text_replace[offset] = (offset + len(MARKER), "\\" + MARKER)

        self.items.append(
            _Item(page, path, prefix, section, short_name(plain, "text"), apply, text=raw)
        )
        self.report.blocks += 1

    def _image(
        self,
        page: Any,
        node: Node,
        prefix: str,
        section: str,
        region: str,
        root: Node,
        in_layout: bool,
    ) -> None:
        img = node if node.tag == "img" else node.find("img")
        if img is None:
            return
        attrs = img.attrs(page.text)
        src = attrs.get("src") or ""
        ref = self.mapped.resolve(src, page.dir)
        overlay: Overlay = page.overlay
        if ref.kind == "asset" and self.logo_src is not None and ref.path == self.logo_src:
            overlay.wrap(node.start, node.end, '{% site_image "logo" %}', "{% endsite_image %}")
            alt = collapse(attrs.get("alt") or "")
            if self.site_name and alt == self.site_name:
                overlay.tag_transform(
                    img.start, lambda text: _set_attribute(text, "alt", "{{ site.name }}")
                )
            return
        alt = collapse(attrs.get("alt") or "")
        stem = posixpath.splitext(posixpath.basename(ref.path or src))[0]
        short = short_name(alt, "") or key_part(stem, "image")

        def apply(key: str) -> None:
            overlay.wrap(
                node.start,
                node.end,
                '{% editable_image "' + key + '" %}',
                "{% endeditable_image %}",
            )

        self.items.append(
            _Item(
                page,
                f"{region}|{_path(root, node)}#img",
                prefix,
                section,
                short,
                apply,
                text=page.text[node.start : node.end],
            )
        )
        self.report.images += 1

    def _style_images(
        self, page: Any, node: Node, prefix: str, section: str, region: str, root: Node
    ) -> None:
        style = node.attr(page.text, "style")
        if not style or "url(" not in style:
            return
        found = [m for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)", style)]
        assets = [
            ref.path
            for m in found
            if (ref := self.mapped.resolve(m.group(1), page.dir)).kind == "asset"
        ]
        if not assets:
            return
        overlay: Overlay = page.overlay
        keys: list[str] = []

        def make_apply(position: int) -> Callable[[str], None]:
            def apply(key: str) -> None:
                keys.append(key)
                if position == 0:
                    overlay.tag_transform(node.start, lambda text: _wrap_style_urls(text, keys))

            return apply

        for position, asset in enumerate(assets):
            stem = posixpath.splitext(posixpath.basename(asset))[0]
            self.items.append(
                _Item(
                    page,
                    f"{region}|{_path(root, node)}#style{position}",
                    prefix,
                    section,
                    key_part(stem, "background"),
                    make_apply(position),
                    text=asset,
                )
            )
            self.report.images += 1

    def _special_link(
        self,
        page: Any,
        node: Node,
        special: tuple[str, str],
        prefix: str,
        section: str,
        region: str,
        root: Node,
        in_layout: bool,
        group: Any,
    ) -> None:
        kind, value = special
        overlay: Overlay = page.overlay
        text_nodes = [child for child in node.children if child.kind == "text"]
        only_text = len(node.children) == len(text_nodes) == 1
        shown = collapse(unescape(text_nodes[0].text(page.text))) if only_text else ""
        handled = False
        if kind == "phone":
            number = value.split("?")[0].strip()
            mine = self.defaults.get("phone_link") or self.defaults.get("phone")
            if mine is None or _same_number(mine, number):
                if "phone" not in self.defaults:
                    same = bool(shown) and _same_number(shown, number)
                    self.defaults["phone"] = shown if same else number
                    if _digits(self.defaults["phone"]) != _digits(number):
                        self.defaults["phone_link"] = number
                overlay.tag_transform(
                    node.start, lambda text: _set_attribute(text, "href", "{{ site.phone_href }}")
                )
                if shown and _same_number(shown, number):
                    self._replace_text(page, text_nodes[0], "{{ site.phone }}")
                    handled = True
        elif kind == "email":
            address, _, query = value.partition("?")
            if self.defaults.setdefault("email", address) == address:
                suffix = f"?{query}" if query else ""
                overlay.tag_transform(
                    node.start,
                    lambda text: _set_attribute(text, "href", "mailto:{{ site.email }}" + suffix),
                )
                if shown == address:
                    self._replace_text(page, text_nodes[0], "{{ site.email }}")
                    handled = True
        elif kind == "map":
            if self.defaults.setdefault("map_url", value) == value:
                overlay.tag_transform(
                    node.start, lambda text: _set_attribute(text, "href", "{{ site.map_url }}")
                )
        elif kind == "social":
            name = f"social_{value}"
            href = (node.attr(page.text, "href") or "").strip()
            if self.defaults.setdefault(name, href) == href:
                overlay.tag_transform(
                    node.start,
                    lambda text: _set_attribute(
                        text, "href", "{{ site.social." + value + ".url }}"
                    ),
                )
                overlay.wrap(
                    node.start, node.end, "{% if site.social." + value + " %}", "{% endif %}"
                )
        if not handled:
            # The link's own words (an icon has none) stay editable.
            run: list[Node] = []
            index = 0
            for child in node.children:
                if child.kind == "text" or (child.kind == "element" and self._inline(child, page)):
                    run.append(child)
                    continue
                if run:
                    self._text_run(
                        page, list(run), prefix, section, f"{region}|{_path(root, node)}#{index}"
                    )
                    index += 1
                    run.clear()
                if child.kind == "element":
                    self._walk(page, child, prefix, section, region, root, in_layout, group)
            if run:
                self._text_run(
                    page, list(run), prefix, section, f"{region}|{_path(root, node)}#{index}"
                )

    def _replace_text(self, page: Any, node: Node, value: str) -> None:
        raw = node.text(page.text)
        start = node.start + len(raw) - len(raw.lstrip())
        end = node.end - (len(raw) - len(raw.rstrip()))
        page.overlay.text_replace[start] = (end, value)

    def _head(self, reference: Any, layout: compare.Layout, by_key: Mapping[str, Any]) -> None:
        """The favicon: the first ``<link rel="icon">`` of the layout's page."""
        head = reference.doc.head
        if head is None:
            return
        for node in head.elements():
            rels = set((node.attr(reference.text, "rel") or "").lower().split())
            if node.tag == "link" and "icon" in rels:
                ref = self.mapped.resolve(node.attr(reference.text, "href") or "", reference.dir)
                if ref.kind == "asset":
                    self.defaults.setdefault("favicon", f"{self.app}/{ref.path}")
                    reference.overlay.tag_transform(
                        node.start,
                        lambda text: _wrap_attribute(
                            text, "href", '{% site_image "favicon" url %}', "{% endsite_image %}"
                        ),
                    )
                return

    # menus

    def _menu(
        self,
        page: Any,
        node: Node,
        prefix: str,
        section: str,
        root: Node,
        in_layout: bool,
        group: Any,
    ) -> _Menu | None:
        if not in_layout and node.tag != "nav" and not _inside(node, "nav"):
            return None
        shape = self._menu_shape(page, node)
        if shape is None:
            return None
        kind, items, nested = shape
        if not self._uniform(page, kind, items, nested):
            self.report.notes.append(
                f"{page.path}:{page.line(node.start)}: a navigation whose links differ in "
                "markup stays as written, its link texts are blocks"
            )
            return None
        name = self._menu_name(page, node, prefix, section, in_layout)
        menu = _Menu(page, node, name, kind, items, nested, group)
        self.menus.append(menu)
        self.report.menus.append(name)
        page.overlay.replace[node.start] = (node.end, _menu_renderer(self, menu))
        return menu

    def _menu_shape(self, page: Any, node: Node) -> tuple[str, list[Node], dict[int, Node]] | None:
        text = page.text
        loose = [c for c in node.children if c.kind == "text" and c.text(text).strip()]
        if loose or any(c.kind == "comment" for c in node.children):
            return None
        elements = node.elements()
        if len(elements) < 2:
            return None
        if all(e.tag == "a" and e.attr(text, "href") is not None for e in elements):
            return "flat", elements, {}
        if node.tag not in ("ul", "ol") or not all(e.tag == "li" for e in elements):
            return None
        nested: dict[int, Node] = {}
        for li in elements:
            if any(c.kind == "text" and c.text(text).strip() for c in li.children):
                return None
            kids = li.elements()
            if not kids or kids[0].tag != "a" or kids[0].attr(text, "href") is None:
                return None
            if len(kids) == 2 and kids[1].tag in ("ul", "ol"):
                inner = self._menu_shape(page, kids[1])
                if inner is None or inner[0] != "list" or inner[2]:
                    return None
                nested[li.start] = kids[1]
            elif len(kids) != 1:
                return None
        return "list", elements, nested

    def _signature(self, page: Any, node: Node, skip: tuple[str, ...] = ()) -> tuple[Any, ...]:
        parts: list[Any] = [node.tag]
        for attr in attributes(node.tag_text(page.text)):
            if attr.name in skip or attr.name in compare.STATE_ATTRIBUTES[1:]:
                continue
            if attr.name == "class":
                tokens = tuple(t for t in (attr.value or "").split() if t not in self.markers)
                if tokens:  # a class of current-page markers only is no class
                    parts.append(("class", tokens))
            else:
                parts.append((attr.name, attr.value))
        return tuple(parts)

    def _link_ok(self, page: Any, a: Node) -> bool:
        return (
            all(child.kind == "text" for child in a.children)
            and _HAS_WORD.search(a.plain_text(page.text)) is not None
        )

    def _uniform(self, page: Any, kind: str, items: list[Node], nested: dict[int, Node]) -> bool:
        if kind == "flat":
            links = items
            return all(self._link_ok(page, a) for a in links) and (
                len({self._signature(page, a, ("href",)) for a in links}) == 1
            )
        groups: dict[bool, set[Any]] = {True: set(), False: set()}
        children: list[Node] = []
        for li in items:
            a = li.elements()[0]
            if not self._link_ok(page, a):
                return False
            sub = nested.get(li.start)
            groups[sub is not None].add(
                (self._signature(page, li), self._signature(page, a, ("href",)))
            )
            if sub is not None:
                children.extend(sub.elements())
        if any(len(signatures) > 1 for signatures in groups.values()):
            return False
        if children:
            child_signatures = set()
            for li in children:
                a = li.elements()[0]
                if not self._link_ok(page, a):
                    return False
                child_signatures.add(
                    (self._signature(page, li), self._signature(page, a, ("href",)))
                )
            if len(child_signatures) > 1:
                return False
        return True

    def _menu_name(self, page: Any, node: Node, prefix: str, section: str, in_layout: bool) -> str:
        if in_layout and prefix == "shared":
            base = section
            heading = _heading_before(node, page.text)
            if heading and section not in ("header", "nav"):
                base = f"{section}-{key_part(heading).replace('_', '-')}"
        else:
            base = f"{prefix}-{section}".replace("_", "-")
        base = base.replace("_", "-").strip("-") or "menu"
        name, counter = base, 2
        while name in self.menu_names:
            name = f"{base}-{counter}"
            counter += 1
        self.menu_names.add(name)
        return name

    # keys

    def _assign_keys(self) -> None:
        used: set[str] = set()
        chosen: dict[int, str] = {}
        for index, item in enumerate(self.items):
            old = self.previous.get(item.path)
            if old and old not in used:
                chosen[index] = old
                used.add(old)
        # A model's detail pages share a key for the same text in the same place: one
        # block, shown on each of them and by the one template that replaces them.
        shared: dict[tuple[str, str], list[tuple[str, set[str]]]] = {}
        for index, item in enumerate(self.items):
            if index in chosen:
                continue
            base = f"{item.prefix}.{item.section}.{item.short}"[:140]
            group = item.page.path in self.shared
            if group:
                taken = next(
                    (
                        entry
                        for entry in shared.get((base, item.text), [])
                        if item.page.path not in entry[1]
                    ),
                    None,
                )
                if taken is not None:
                    chosen[index] = taken[0]
                    taken[1].add(item.page.path)
                    continue
            key, counter = base, 2
            while key in used:
                key = f"{base}_{counter}"
                counter += 1
            chosen[index] = key
            used.add(key)
            if group:
                shared.setdefault((base, item.text), []).append((key, {item.page.path}))
        for index, item in enumerate(self.items):
            item.key = chosen[index]
            self.keys[item.path] = item.key
            item.apply(item.key)


# rendering a menu


def _text_tokens(node: Node) -> Iterable[Node]:
    """The text nodes of ``node`` and inside it."""
    if node.kind == "text":
        yield node
        return
    for child in node.iter():
        if child.kind == "text":
            yield child


def _marker_offsets(source: str, start: int, end: int) -> list[int]:
    """Where the highlight marker starts in ``source[start:end]``, left to right, apart."""
    found: list[int] = []
    at = source.find(MARKER, start, end)
    while at != -1:
        found.append(at)
        at = source.find(MARKER, at + len(MARKER), end)
    return found


def _menu_renderer(editable: Editable, menu: _Menu) -> Render:
    def render(renderer: Any, page: Any, variations: Any, span_start: int) -> str:
        return _menu_markup(editable, renderer, page, variations, span_start, menu)

    return render


def _element_offset(page: Any, node: Node, span_start: int) -> int:
    from bisect import bisect_left

    return bisect_left(page.element_starts, node.start) - bisect_left(
        page.element_starts, span_start
    )


def _generalized(page: Any, node: Node, variations: Any, span_start: int, patterns: Any) -> str:
    text = page.rewriter.tag(node, page.text)
    index = _element_offset(page, node, span_start)
    if variations and index in variations:
        text, _problems = compare.generalize_tag(text, variations[index], patterns)
    return text


def _item_tag(page: Any, node: Node, variations: Any, span_start: int, var: str, link: bool) -> str:
    text = page.rewriter.tag(node, page.text)
    if link:
        text = _set_attribute(text, "href", "{{ " + var + ".url }}")
        if node.attr(page.text, "target") is None:
            point = len(text) - (2 if text.endswith("/>") else 1)
            text = (
                text[:point]
                + "{% if "
                + var
                + '.new_tab %} target="_blank" rel="noopener"{% endif %}'
                + text[point:]
            )
    index = _element_offset(page, node, span_start)
    if variations and index in variations:
        text, _problems = compare.generalize_tag(text, variations[index], lambda pages: [_MARK])
    return text.replace('{% ifactive "' + _MARK + '" %}', "{% if " + var + ".active %}").replace(
        "{% endifactive %}", "{% endif %}"
    )


def _pattern_item(items: list[Node], page: Any, variations: Any, span_start: int) -> Node:
    """The item whose markup the loop repeats: one the design marks as current, if any."""
    if variations:
        for li in items:
            a = li if li.tag == "a" else li.elements()[0]
            for node in (li, a):
                if _element_offset(page, node, span_start) in variations:
                    return li
    return items[0]


def _menu_markup(
    editable: Editable, renderer: Any, page: Any, variations: Any, span_start: int, menu: _Menu
) -> str:
    text = page.text
    esc = rewrite.escape_template_syntax
    var = "menu_" + menu.name.replace("-", "_")
    container = menu.node
    out = [
        '{% get_menu "'
        + menu.name
        + '" seed="'
        + editable._seed(menu.name)
        + '" as '
        + var
        + " %}",
        _generalized(page, container, variations, span_start, renderer.patterns),
    ]
    first, last = menu.items[0], menu.items[-1]
    inner_start, inner_end = container.inner
    lead = esc(text[inner_start : first.start])
    if menu.kind == "flat":
        pattern = _pattern_item(menu.items, page, variations, span_start)
        between = text[menu.items[0].end : menu.items[1].start]
        out.append(lead + "{% for item in " + var + " %}")
        out.append(_link(page, pattern, variations, span_start, "item"))
        out.append("{% if not forloop.last %}" + esc(between) + "{% endif %}{% endfor %}")
    else:
        plain = [li for li in menu.items if li.start not in menu.nested]
        parents = [li for li in menu.items if li.start in menu.nested]
        between = esc(text[menu.items[0].end : menu.items[1].start])
        out.append(lead + "{% for item in " + var + " %}")
        plain_markup = (
            _list_item(
                page,
                _pattern_item(plain, page, variations, span_start),
                None,
                variations,
                span_start,
                "item",
            )
            if plain
            else None
        )
        parent_markup = (
            _list_item(
                page,
                _pattern_item(parents, page, variations, span_start),
                menu,
                variations,
                span_start,
                "item",
            )
            if parents
            else None
        )
        if plain_markup is not None and parent_markup is not None:
            out.append(
                "{% if item.children %}"
                + parent_markup
                + "{% else %}"
                + plain_markup
                + "{% endif %}"
            )
        else:
            out.append(parent_markup or plain_markup or "")
        out.append("{% if not forloop.last %}" + between + "{% endif %}{% endfor %}")
    out.append(esc(text[last.end : inner_end]))
    if container.close_token is not None:
        out.append(text[inner_end : container.end])
    return "".join(out)


def _link(page: Any, a: Node, variations: Any, span_start: int, var: str) -> str:
    _inner_start, inner_end = a.inner
    close = page.text[inner_end : a.end]
    return _item_tag(page, a, variations, span_start, var, True) + "{{ " + var + ".title }}" + close


def _list_item(
    page: Any, li: Node, menu: _Menu | None, variations: Any, span_start: int, var: str
) -> str:
    text = page.text
    esc = rewrite.escape_template_syntax
    a = li.elements()[0]
    li_inner_start, li_inner_end = li.inner
    out = [
        _item_tag(page, li, variations, span_start, var, False),
        esc(text[li_inner_start : a.start]),
        _link(page, a, variations, span_start, var),
    ]
    nested = menu.nested.get(li.start) if menu is not None else None
    if nested is None:
        out.append(esc(text[a.end : li_inner_end]))
    else:
        out.append(esc(text[a.end : nested.start]))
        kids = nested.elements()
        child = _pattern_item(kids, page, variations, span_start)
        n_start, n_end = nested.inner
        between = esc(text[kids[0].end : kids[1].start]) if len(kids) > 1 else ""
        out.append(
            _generalized(page, nested, variations, span_start, lambda pages: [_MARK])
            .replace('{% ifactive "' + _MARK + '" %}', "{% if " + var + ".active %}")
            .replace("{% endifactive %}", "{% endif %}")
        )
        out.append(esc(text[n_start : kids[0].start]))
        out.append("{% for child in " + var + ".children %}")
        out.append(_list_item(page, child, None, variations, span_start, "child"))
        out.append("{% if not forloop.last %}" + between + "{% endif %}{% endfor %}")
        out.append(esc(text[kids[-1].end : n_end]))
        if nested.close_token is not None:
            out.append(text[n_end : nested.end])
        out.append(esc(text[nested.end : li_inner_end]))
    if li.close_token is not None:
        out.append(text[li_inner_end : li.end])
    return "".join(out)


def _slice_rendered(renderer: Any, page: Any, root: Node, node: Node, variations: Any) -> str:
    """The rendered markup of ``node``, a part of the shared block ``root``.

    The variations index the block's elements from its own first element, so
    the whole block is rendered, with markers around the node to cut it out.
    """
    marker_open, marker_close = "\x00karni-seed\x00", "\x01karni-seed\x01"
    overlay = Overlay()
    overlay.opens[node.start] = [marker_open]
    overlay.closes[node.end] = [marker_close]
    page.overlay = overlay
    markup = renderer.span(page, root.start, root.end, variations)
    return markup.split(marker_open, 1)[1].split(marker_close, 1)[0]


# small helpers


def _path(root: Node, node: Node) -> str:
    """Element child indices from ``root`` down to ``node``: where a run lives in its section."""
    parts: list[str] = []
    current = node
    while current is not None and current is not root:
        parent = current.parent
        if parent is None:
            break
        parts.append(str(parent.elements().index(current)) if current.kind == "element" else "t")
        current = parent
    return "/".join(reversed(parts))


def _inside(node: Node, tag: str) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.kind == "element" and parent.tag == tag:
            return True
        parent = parent.parent
    return False


def _heading_before(node: Node, source: str) -> str:
    """The text of the heading just before ``node`` among its siblings, or ``""``."""
    parent = node.parent
    if parent is None:
        return ""
    siblings = parent.elements()
    position = siblings.index(node) if node in siblings else 0
    for sibling in reversed(siblings[:position]):
        if _HEADING.match(sibling.tag):
            return sibling.plain_text(source)
    return ""


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _same_number(shown: str, number: str) -> bool:
    """Whether a phone number as written (``020 7946 0000``) is the one dialled (``+44...``)."""
    written = _digits(shown).lstrip("0")
    dialled = _digits(number).lstrip("0")
    return len(written) >= 6 and dialled.endswith(written)


def _quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _attribute_span(text: str, name: str) -> tuple[int, int, str] | None:
    for attr in attributes(text):
        if attr.name == name and attr.value_start is not None and attr.value_end is not None:
            return attr.value_start, attr.value_end, attr.quote
    return None


def _set_attribute(text: str, name: str, value: str) -> str:
    """A start tag with ``name``'s value replaced by ``value`` (a template expression)."""
    span = _attribute_span(text, name)
    if span is None:
        return text
    start, end, quote = span
    if not quote:
        return f'{text[:start]}"{value}"{text[end:]}'
    return text[:start] + value + text[end:]


def _wrap_attribute(text: str, name: str, before: str, after: str) -> str:
    span = _attribute_span(text, name)
    if span is None:
        return text
    start, end, _quote = span
    return text[:start] + before + text[start:end] + after + text[end:]


def _wrap_style_urls(text: str, keys: list[str]) -> str:
    """The ``{% static %}`` addresses of a style attribute, each in an ``editable_image ... url``."""
    span = _attribute_span(text, "style")
    if span is None:
        return text
    start, end, _quote = span
    value = text[start:end]
    found = iter(keys)

    def wrap(match: re.Match[str]) -> str:
        key = next(found, None)
        if key is None:
            return match.group(0)
        return '{% editable_image "' + key + '" url %}' + match.group(0) + "{% endeditable_image %}"

    return text[:start] + _STATIC.sub(wrap, value) + text[end:]
