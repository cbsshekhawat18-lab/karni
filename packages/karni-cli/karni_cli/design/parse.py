"""HTML as byte-exact tokens and a tree over them (``html.parser``, no dependency).

:func:`parse` feeds a page to :class:`html.parser.HTMLParser`, turns each
event's line and column into an offset, and records every token as the span
between its own start and the next token's start. Joining the spans gives the
source back unchanged, so a node's markup is always a slice of the file.

The tree is loose on purpose: a stray end tag is kept as a token and ignored,
a ``<p>`` or ``<li>`` left open is closed when its sibling starts, and a void
element never has children. That is enough to find the elements a page is
made of and their exact markup, without re-serializing anything.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Final

__all__ = [
    "VOID",
    "Attribute",
    "Document",
    "Node",
    "Token",
    "attributes",
    "collapse",
    "parse",
    "parse_fragment",
]

#: Elements that never have content (HTML's void elements).
VOID: Final = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
#: Starting one of these closes an open ``<p>``.
_CLOSES_P: Final = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "details",
        "div",
        "dl",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
)
#: An open element closed by a sibling's start tag: (open, {starting tags}).
_IMPLIED_END: Final[dict[str, frozenset[str]]] = {
    "p": _CLOSES_P,
    "li": frozenset({"li"}),
    "dt": frozenset({"dt", "dd"}),
    "dd": frozenset({"dt", "dd"}),
    "tr": frozenset({"tr"}),
    "td": frozenset({"td", "th", "tr"}),
    "th": frozenset({"td", "th", "tr"}),
    "option": frozenset({"option", "optgroup"}),
    "thead": frozenset({"tbody", "tfoot"}),
    "tbody": frozenset({"tbody", "tfoot"}),
}

_WS = re.compile(r"\s+")
_ATTR = re.compile(
    r"""\s*(?P<name>[^\s"'=<>/`]+)"""
    r"""(?:\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<uq>[^\s"'=<>`]+)))?""",
    re.DOTALL,
)


def collapse(text: str) -> str:
    """Whitespace runs as one space, trimmed."""
    return _WS.sub(" ", text).strip()


@dataclass(frozen=True)
class Token:
    """One event of the parser: ``kind`` and its exact span of the source."""

    kind: str  # decl, start, startend, end, text, comment, pi
    start: int
    end: int
    tag: str = ""

    def text(self, source: str) -> str:
        return source[self.start : self.end]


@dataclass(frozen=True)
class Attribute:
    """An attribute in a start tag: its name, decoded value and where the value is.

    ``name_start`` is the offset of the name within the tag's text.
    ``value_start``/``value_end`` bound the value text (without quotes), and
    are ``None`` for a bare attribute. ``quote`` is ``"``, ``'`` or ``""``.
    """

    name: str
    value: str | None
    name_start: int
    name_end: int
    value_start: int | None
    value_end: int | None
    quote: str

    @property
    def raw(self) -> str:
        return self.name


def attributes(tag_text: str) -> list[Attribute]:
    """The attributes of a start tag's text, in order, with their value spans."""
    if not tag_text.startswith("<"):
        return []
    match = re.match(r"<[^\s/>]+", tag_text)
    if match is None:
        return []
    position = match.end()
    limit = len(tag_text) - (2 if tag_text.endswith("/>") else 1)
    found: list[Attribute] = []
    while position < limit:
        attr = _ATTR.match(tag_text, position, limit)
        if attr is None or not attr.group("name"):
            break
        name = attr.group("name").lower()
        position = attr.end()
        if name == "/":
            continue
        quote = ""
        value: str | None = None
        value_span: tuple[int, int] | None = None
        for group, mark in (("dq", '"'), ("sq", "'"), ("uq", "")):
            raw = attr.group(group)
            if raw is not None:
                value = unescape(raw)
                value_span = attr.span(group)
                quote = mark
                break
        found.append(
            Attribute(
                name,
                value,
                attr.start("name"),
                attr.end("name"),
                value_span[0] if value_span else None,
                value_span[1] if value_span else None,
                quote,
            )
        )
    return found


@dataclass
class Node:
    """An element, a text run, a comment or a declaration, as a span of the source."""

    kind: str  # element, text, comment, decl, pi
    start: int
    end: int
    tag: str = ""
    children: list[Node] = field(default_factory=list)
    parent: Node | None = field(default=None, repr=False)
    open_token: Token | None = None
    close_token: Token | None = None
    _attrs: dict[str, str | None] | None = field(default=None, repr=False)

    def text(self, source: str) -> str:
        return source[self.start : self.end]

    def tag_text(self, source: str) -> str:
        """The start tag's text (``<a href="x">``), empty for anything but an element."""
        if self.open_token is None:
            return ""
        return self.open_token.text(source)

    def attrs(self, source: str) -> dict[str, str | None]:
        """Attributes by lowercased name (the first wins), values decoded."""
        if self._attrs is None:
            found: dict[str, str | None] = {}
            for attr in attributes(self.tag_text(source)):
                found.setdefault(attr.name, attr.value)
            self._attrs = found
        return self._attrs

    def attr(self, source: str, name: str) -> str | None:
        return self.attrs(source).get(name)

    def classes(self, source: str) -> list[str]:
        return (self.attr(source, "class") or "").split()

    @property
    def inner(self) -> tuple[int, int]:
        """The span between the start tag and the end tag (the element's content)."""
        if self.open_token is None:
            return (self.start, self.end)
        inner_end = self.close_token.start if self.close_token is not None else self.end
        return (self.open_token.end, inner_end)

    def inner_text(self, source: str) -> str:
        begin, finish = self.inner
        return source[begin:finish]

    def elements(self) -> list[Node]:
        return [child for child in self.children if child.kind == "element"]

    def iter(self) -> Iterator[Node]:
        """This node and every descendant, in document order."""
        yield self
        for child in self.children:
            yield from child.iter()

    def iter_elements(self) -> Iterator[Node]:
        for node in self.iter():
            if node.kind == "element":
                yield node

    def find(self, tag: str) -> Node | None:
        """The first descendant element with ``tag``."""
        for node in self.iter_elements():
            if node.tag == tag and node is not self:
                return node
        return None

    def find_all(self, tag: str) -> list[Node]:
        return [node for node in self.iter_elements() if node.tag == tag and node is not self]

    def plain_text(self, source: str) -> str:
        """The text content with entities decoded and whitespace collapsed."""
        parts = [child.text(source) for child in self.iter() if child.kind == "text"]
        return collapse(unescape("".join(parts)))


class _Events(HTMLParser):
    """Collects the parser's events with the offset each one starts at."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.events: list[tuple[str, int, str]] = []
        self._line_starts = [0]
        for index, char in enumerate(source):
            if char == "\n":
                self._line_starts.append(index + 1)

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.events.append(("start", self._offset(), tag))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.events.append(("startend", self._offset(), tag))

    def handle_endtag(self, tag: str) -> None:
        self.events.append(("end", self._offset(), tag))

    def handle_data(self, data: str) -> None:
        self.events.append(("text", self._offset(), ""))

    def handle_entityref(self, name: str) -> None:
        self.events.append(("text", self._offset(), ""))

    def handle_charref(self, name: str) -> None:
        self.events.append(("text", self._offset(), ""))

    def handle_comment(self, data: str) -> None:
        self.events.append(("comment", self._offset(), ""))

    def handle_decl(self, decl: str) -> None:
        self.events.append(("decl", self._offset(), ""))

    def unknown_decl(self, data: str) -> None:
        self.events.append(("decl", self._offset(), ""))

    def handle_pi(self, data: str) -> None:
        self.events.append(("pi", self._offset(), ""))


def tokenize(source: str) -> list[Token]:
    """Every token of ``source`` as a span. The spans cover the whole source, in order."""
    parser = _Events(source)
    parser.feed(source)
    parser.close()
    events = parser.events
    tokens: list[Token] = []
    for index, (kind, start, tag) in enumerate(events):
        end = events[index + 1][1] if index + 1 < len(events) else len(source)
        end = max(end, start)  # the parser reports events in order, but never trust it
        if tokens and kind == "text" and tokens[-1].kind == "text":
            tokens[-1] = Token("text", tokens[-1].start, end)
            continue
        tokens.append(Token(kind, start, end, tag))
    if tokens and tokens[0].start > 0:
        tokens.insert(0, Token("text", 0, tokens[0].start))
    elif not tokens and source:
        tokens.append(Token("text", 0, len(source)))
    return tokens


def _close(node: Node, end: int, token: Token | None = None) -> None:
    node.end = end
    node.close_token = token


@dataclass
class Document:
    """A parsed page: the source, its tokens and the tree."""

    source: str
    tokens: list[Token]
    root: Node

    @property
    def html(self) -> Node | None:
        return next(
            (n for n in self.root.children if n.kind == "element" and n.tag == "html"), None
        )

    @property
    def head(self) -> Node | None:
        return self.root.find("head")

    @property
    def body(self) -> Node | None:
        return self.root.find("body")

    def body_or_root(self) -> Node:
        """The ``<body>``, or the whole document for a page without one (a fragment)."""
        return self.body or self.root


def parse(source: str) -> Document:
    """Parse a page. The tree's spans slice ``source`` exactly."""
    tokens = tokenize(source)
    root = Node("root", 0, len(source))
    stack: list[Node] = [root]
    for token in tokens:
        if token.kind in ("start", "startend"):
            tag = token.tag
            # A sibling start closes what HTML leaves open (<p>, <li>, <td> ...).
            while len(stack) > 1 and tag in _IMPLIED_END.get(stack[-1].tag, ()):
                _close(stack[-1], token.start)
                stack.pop()
            node = Node("element", token.start, token.end, tag, open_token=token)
            node.parent = stack[-1]
            stack[-1].children.append(node)
            if token.kind == "start" and tag not in VOID:
                stack.append(node)
        elif token.kind == "end":
            depth = next(
                (i for i in range(len(stack) - 1, 0, -1) if stack[i].tag == token.tag), None
            )
            if depth is None:
                continue  # a stray end tag: part of the parent's span, no node of its own
            while len(stack) - 1 > depth:
                _close(stack[-1], token.start)
                stack.pop()
            _close(stack[-1], token.end, token)
            stack.pop()
        else:
            node = Node(token.kind, token.start, token.end)
            node.parent = stack[-1]
            stack[-1].children.append(node)
    while len(stack) > 1:
        _close(stack[-1], len(source))
        stack.pop()
    return Document(source, tokens, root)


def parse_fragment(source: str) -> Document:
    """Parse markup that is not a whole page (a partial): the same tree, no ``<body>``."""
    return parse(source)
