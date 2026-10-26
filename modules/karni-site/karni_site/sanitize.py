"""The inline markup an edited block may keep, and the text a client edits it as.

:func:`sanitize` keeps the elements ``KARNI_SITE_INLINE_TAGS`` names (bold,
emphasis, links and line breaks by default) and the highlight element, each
with only its listed attributes. Every other element is removed and its
text kept, except ``script``, ``style`` and the like, whose content goes
too. Event attributes (``onclick``) never survive, and a link whose scheme
``KARNI_SITE_LINK_SCHEMES`` does not list (``javascript:``, ``data:``) loses
its address. It is built on the standard library's ``html.parser``: Karni
needs no sanitising dependency.

A client never edits HTML they cannot read. :func:`to_editing` shows a
block with its line breaks as new lines and the highlight element as the
marker (``==fresh every morning==``), and :func:`from_editing` turns the edited text
back into clean HTML.

Override / escape hatch: ``KARNI_SITE_SANITIZER`` names another
``(html) -> html`` function (a library such as nh3 behind it, for example),
``KARNI_SITE_INLINE_TAGS`` and ``KARNI_SITE_LINK_SCHEMES`` change what is
kept, and ``KARNI_SITE_HIGHLIGHT`` the highlight convention.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from html import escape, unescape
from html.parser import HTMLParser

from django.utils.module_loading import import_string

from karni_site import conf

__all__ = [
    "Highlight",
    "allowed_tags",
    "apply_highlight",
    "clean",
    "from_editing",
    "highlight",
    "safe_url",
    "sanitize",
    "to_editing",
]

#: Elements removed together with everything inside them.
DROP_CONTENT = frozenset(
    {
        "script",
        "style",
        "template",
        "iframe",
        "object",
        "embed",
        "noscript",
        "svg",
        "math",
        "textarea",
        "select",
        "title",
        "head",
    }
)
_VOID = frozenset({"br", "wbr", "img", "hr", "input", "meta", "link", "source", "area", "col"})
_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
_INVISIBLE = re.compile(r"[\x00-\x20\x7f-\x9f]+")


@dataclass(frozen=True)
class Highlight:
    """The highlight convention: ``marker`` text marker ``marker`` renders as ``<tag class>``."""

    marker: str
    tag: str
    css_class: str

    def start_tag(self) -> str:
        return (
            f'<{self.tag} class="{escape(self.css_class)}">' if self.css_class else f"<{self.tag}>"
        )

    def end_tag(self) -> str:
        return f"</{self.tag}>"


def highlight() -> Highlight:
    """The convention ``KARNI_SITE_HIGHLIGHT`` configures."""
    raw: Mapping[str, str] = conf.get("KARNI_SITE_HIGHLIGHT") or {}
    return Highlight(
        marker=str(raw.get("marker") or ""),
        tag=str(raw.get("tag") or "").strip().lower(),
        css_class=str(raw.get("class") or "").strip(),
    )


def allowed_tags() -> dict[str, frozenset[str]]:
    """Element -> the attributes it keeps: ``KARNI_SITE_INLINE_TAGS`` and the highlight."""
    found = {
        str(tag).lower(): frozenset(str(name).lower() for name in names)
        for tag, names in (conf.get("KARNI_SITE_INLINE_TAGS") or {}).items()
    }
    mark = highlight()
    if mark.tag:
        found[mark.tag] = found.get(mark.tag, frozenset()) | (
            frozenset({"class"}) if mark.css_class else frozenset()
        )
    return found


def safe_url(value: str) -> bool:
    """Whether a link may point at ``value``: a relative URL or an allowed scheme."""
    compact = _INVISIBLE.sub("", value)
    match = _SCHEME.match(compact)
    if match is None:
        return True
    schemes = {str(scheme).lower() for scheme in conf.get("KARNI_SITE_LINK_SCHEMES") or ()}
    return match.group(1).lower() in schemes


class _Cleaner(HTMLParser):
    def __init__(self, tags: Mapping[str, frozenset[str]], mark: Highlight) -> None:
        super().__init__(convert_charrefs=True)
        self.tags = tags
        self.mark = mark
        self.out: list[str] = []
        self.open: list[str] = []
        self.skipping = ""
        self.depth = 0

    def _attributes(self, tag: str, attrs: list[tuple[str, str | None]]) -> list[str] | None:
        """The attributes kept, rendered, or ``None`` when the element itself goes."""
        allowed = self.tags[tag]
        kept: list[str] = []
        names: dict[str, str] = {}
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            value = raw_value or ""
            if name.startswith("on") or name not in allowed or name in names:
                continue
            if name in ("href", "src", "cite", "action", "formaction") and not safe_url(value):
                continue
            if name == "class":
                if tag != self.mark.tag or value.split() != [self.mark.css_class]:
                    continue
            if name == "target" and value not in ("_blank", "_self"):
                continue
            names[name] = value
        if tag == self.mark.tag and self.mark.css_class and "class" not in names:
            # Without the class it is not the highlight: plain text, if the tag is not
            # also allowed on its own.
            if tag not in (conf.get("KARNI_SITE_INLINE_TAGS") or {}):
                return None
        if names.get("target") == "_blank":
            rel = set(names.get("rel", "").split()) | {"noopener", "noreferrer"}
            names["rel"] = " ".join(sorted(rel))
        for name, value in names.items():
            kept.append(f' {name}="{escape(value, quote=True)}"')
        return kept

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skipping:
            if tag == self.skipping:
                self.depth += 1
            return
        if tag in DROP_CONTENT:
            if tag not in _VOID:
                self.skipping, self.depth = tag, 1
            return
        if tag not in self.tags:
            return
        kept = self._attributes(tag, attrs)
        if kept is None:
            return
        self.out.append(f"<{tag}{''.join(kept)}>")
        if tag not in _VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skipping or tag in DROP_CONTENT:
            return
        before = len(self.open)
        self.handle_starttag(tag, attrs)
        if len(self.open) > before:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skipping:
            if tag == self.skipping:
                self.depth -= 1
                if self.depth == 0:
                    self.skipping = ""
            return
        if tag not in self.open:
            return
        while self.open:
            last = self.open.pop()
            self.out.append(f"</{last}>")
            if last == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.out.append(escape(data, quote=False))

    def result(self) -> str:
        self.close()
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def sanitize(html: str) -> str:
    """``html`` with only the allowed inline markup (see the module docstring)."""
    cleaner = _Cleaner(allowed_tags(), highlight())
    cleaner.feed(str(html))
    return cleaner.result()


def clean(html: str) -> str:
    """``html`` through the function ``KARNI_SITE_SANITIZER`` names."""
    configured = conf.get("KARNI_SITE_SANITIZER")
    function: Callable[[str], str] = (
        configured if callable(configured) else import_string(str(configured))
    )
    return function(html)


def apply_highlight(text: str) -> str:
    """``==words==`` (the configured marker) as the highlight element."""
    mark = highlight()
    if not mark.marker or not mark.tag:
        return text
    pattern = re.compile(re.escape(mark.marker) + r"(.+?)" + re.escape(mark.marker), re.S)
    return pattern.sub(lambda m: mark.start_tag() + m.group(1) + mark.end_tag(), text)


def _highlight_pattern(mark: Highlight) -> re.Pattern[str]:
    tag = re.escape(mark.tag)
    if mark.css_class:
        start = rf"""<{tag}\s+class\s*=\s*(["']){re.escape(mark.css_class)}\1\s*>"""
    else:
        start = rf"<{tag}\s*>"
    return re.compile(start + r"(?P<inner>.*?)" + rf"</{tag}\s*>", re.S | re.I)


_ENTITY = re.compile(r"&(#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
_AMP = re.compile(r"&amp;(?![#A-Za-z0-9]+;)")


def _readable(text: str) -> str:
    """Entities as the characters they are (``&copy;`` as ``©``), except ``<`` and ``>``."""
    text = _ENTITY.sub(
        lambda m: m.group(0) if m.group(1) in ("lt", "gt", "amp") else unescape(m.group(0)), text
    )
    return _AMP.sub("&", text)


def to_editing(html: str) -> str:
    """A block's HTML as the text a client edits: new lines for ``<br>``, markers, characters."""
    text = _readable(re.sub(r"\s+", " ", str(html)).strip())
    text = re.sub(r"\s*<br\s*/?>\s*", "\n", text, flags=re.I)
    mark = highlight()
    if mark.marker and mark.tag:
        text = _highlight_pattern(mark).sub(
            lambda m: mark.marker + m.group("inner") + mark.marker, text
        )
    return text


def from_editing(text: str) -> str:
    """The edited text back as clean HTML: lines joined with ``<br>``, markers applied."""
    lines = str(text).replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")
    joined = "<br>\n".join(line.strip() for line in lines)
    return clean(apply_highlight(joined))
