"""CSS selectors over :mod:`karni_cli.design.parse` trees, for the content map.

``karni design analyze`` writes a map of where each model's content is in the
pages, and ``karni design extract`` reads the pages with it. A place is a CSS
selector, optionally followed by ``@attribute``: ``"h3"`` is the text of the
item's ``<h3>``, ``"img@src"`` the ``src`` of its image, ``"@data-tags"`` an
attribute of the item itself.

The supported subset is what a designer's markup needs, and every selector
is *scoped*: it matches elements inside the root it runs on, and its
ancestor parts never look above that root. ``"> img"`` is an image that is
a direct child of the root.

* a type (``h2``, ``*``), classes (``.card.featured``), an id (``#team``),
  attributes (``[data-cat]``, ``[data-cat="cakes"]``, ``[class~="x"]``),
  ``:nth-of-type(2)``, ``:first-of-type``, ``:last-of-type``, ``:has(...)``
  (``section:has(.gallery)``: a section with a gallery inside) and
  ``:not(...)`` of one compound (``p:not(.role)``);
* the descendant (space) and child (``>``) combinators;
* a group of selectors separated by commas (``h1, h2``), matched in
  document order.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from karni_cli.design.parse import Node

__all__ = [
    "Place",
    "Selector",
    "SelectorError",
    "Target",
    "parse_place",
    "parse_selector",
    "select",
    "write_selector",
]


class SelectorError(ValueError):
    """A selector this engine cannot read: the text and what is wrong with it."""


@dataclass(frozen=True)
class Compound:
    """One step of a selector: ``div.card[data-x]:nth-of-type(2)``."""

    tag: str = ""  # "" or "*": any element
    classes: tuple[str, ...] = ()
    ident: str = ""
    attributes: tuple[tuple[str, str, str | None], ...] = ()  # (name, operator, value)
    nth: int = 0  # :nth-of-type(n), counted from 1, and -1 for :last-of-type
    has: tuple[Selector, ...] = ()
    not_: tuple[Compound, ...] = ()

    def matches(self, node: Node, source: str) -> bool:
        if node.kind != "element":
            return False
        if self.tag and self.tag != "*" and node.tag != self.tag:
            return False
        if self.classes:
            own = set(node.classes(source))
            if not all(name in own for name in self.classes):
                return False
        if self.ident and node.attr(source, "id") != self.ident:
            return False
        for name, operator, value in self.attributes:
            attrs = node.attrs(source)
            if name not in attrs:
                return False
            actual = attrs[name] or ""
            if operator == "=" and actual != value:
                return False
            if operator == "~=" and value not in actual.split():
                return False
        if self.nth:
            parent = node.parent
            if parent is None:
                return False
            same = [child for child in parent.elements() if child.tag == node.tag]
            position = same.index(node) + 1 if node in same else 0
            wanted = len(same) if self.nth == -1 else self.nth
            if position != wanted:
                return False
        for inner in self.has:
            if not select(node, inner, source):
                return False
        return not any(excluded.matches(node, source) for excluded in self.not_)


@dataclass(frozen=True)
class Complex:
    """Compounds joined by combinators, read right to left: ``(" ", a), (">", b)``."""

    #: (combinator to the previous compound, compound). The first combinator is
    #: ``""`` (anywhere under the root) or ``">"`` (a child of the root).
    parts: tuple[tuple[str, Compound], ...]

    def matches(self, node: Node, root: Node, source: str) -> bool:
        return self._match(len(self.parts) - 1, node, root, source)

    def _match(self, index: int, node: Node, root: Node, source: str) -> bool:
        combinator, compound = self.parts[index]
        if not compound.matches(node, source):
            return False
        parent = node.parent
        if index == 0:
            return combinator != ">" or parent is root
        if combinator == ">":
            return (
                parent is not None
                and parent is not root
                and (self._match(index - 1, parent, root, source))
            )
        ancestor = parent
        while ancestor is not None and ancestor is not root:
            if self._match(index - 1, ancestor, root, source):
                return True
            ancestor = ancestor.parent
        return False


@dataclass(frozen=True)
class Selector:
    """A parsed selector group."""

    text: str
    group: tuple[Complex, ...] = field(default=())

    def matches(self, node: Node, root: Node, source: str) -> bool:
        return any(complex_.matches(node, root, source) for complex_ in self.group)


_TOKEN = re.compile(
    r"""
    (?P<space>\s*>\s*|\s*,\s*|\s+)
  | (?P<tag>\*|[A-Za-z][A-Za-z0-9-]*)
  | \.(?P<cls>-?[_A-Za-z][-_A-Za-z0-9]*)
  | \#(?P<id>-?[_A-Za-z][-_A-Za-z0-9]*)
  | \[\s*(?P<attr>[^\s~=\]]+)\s*
      (?:(?P<op>~?=)\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^\]\s]+))\s*)?\]
  | :(?P<pseudo>nth-of-type\(\s*(?P<n>\d+)\s*\)|first-of-type|last-of-type|has\(|not\()
    """,
    re.VERBOSE,
)


@dataclass
class _Draft:
    """The compound being read."""

    tag: str = ""
    classes: list[str] = field(default_factory=list)
    ident: str = ""
    attributes: list[tuple[str, str, str | None]] = field(default_factory=list)
    nth: int = 0
    has: list[Selector] = field(default_factory=list)
    not_: list[Compound] = field(default_factory=list)

    def compound(self) -> Compound:
        return Compound(
            self.tag,
            tuple(self.classes),
            self.ident,
            tuple(self.attributes),
            self.nth,
            tuple(self.has),
            tuple(self.not_),
        )


def _skip_space(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def parse_selector(text: str) -> Selector:
    """Read ``text`` (see the module docstring), or raise :class:`SelectorError`."""
    stripped = text.strip()
    if not stripped:
        raise SelectorError("an empty selector")
    group: list[Complex] = []
    parts: list[tuple[str, Compound]] = []
    combinator = ""
    current: _Draft | None = None
    position = 0
    if stripped.startswith(">"):
        combinator = ">"
        position = _skip_space(stripped, 1)
    while position < len(stripped):
        match = _TOKEN.match(stripped, position)
        if match is None:
            raise SelectorError(f"{text!r}: cannot read {stripped[position:]!r}")
        position = match.end()
        space = match.group("space")
        if space is not None:
            if current is None:
                raise SelectorError(f"{text!r}: a combinator with nothing before it")
            parts.append((combinator, current.compound()))
            current = None
            mark = space.strip()
            if mark == ",":
                group.append(Complex(tuple(parts)))
                parts = []
                combinator = ""
                if stripped[position:].startswith(">"):
                    combinator = ">"
                    position = _skip_space(stripped, position + 1)
            else:
                combinator = ">" if mark == ">" else " "
            continue
        if current is None:
            current = _Draft()
        if match.group("tag") is not None:
            if current.tag or current.classes or current.ident or current.attributes:
                raise SelectorError(f"{text!r}: the type must come first in a compound")
            current.tag = match.group("tag").lower()
        elif match.group("cls") is not None:
            current.classes.append(match.group("cls"))
        elif match.group("id") is not None:
            current.ident = match.group("id")
        elif match.group("attr") is not None:
            value = next(
                (v for v in (match.group("dq"), match.group("sq"), match.group("bare")) if v),
                "" if match.group("op") else None,
            )
            current.attributes.append((match.group("attr").lower(), match.group("op") or "", value))
        else:
            pseudo = match.group("pseudo")
            if pseudo in ("has(", "not("):
                depth, end = 1, position
                while end < len(stripped) and depth:
                    depth += {"(": 1, ")": -1}.get(stripped[end], 0)
                    end += 1
                if depth:
                    raise SelectorError(f"{text!r}: :{pseudo} is not closed")
                inner = parse_selector(stripped[position : end - 1])
                if pseudo == "has(":
                    current.has.append(inner)
                else:
                    if any(len(complex_.parts) != 1 for complex_ in inner.group):
                        raise SelectorError(f"{text!r}: :not() takes one compound, such as .role")
                    current.not_.extend(complex_.parts[0][1] for complex_ in inner.group)
                position = end
            elif pseudo == "first-of-type":
                current.nth = 1
            elif pseudo == "last-of-type":
                current.nth = -1
            else:
                current.nth = int(match.group("n"))
    if current is None:
        raise SelectorError(f"{text!r}: ends with a combinator")
    parts.append((combinator, current.compound()))
    group.append(Complex(tuple(parts)))
    return Selector(text, tuple(group))


def select(root: Node, selector: Selector | str, source: str) -> list[Node]:
    """The elements under ``root`` (never ``root`` itself) that ``selector`` matches."""
    parsed = parse_selector(selector) if isinstance(selector, str) else selector
    return [node for node in _descendants(root) if parsed.matches(node, root, source)]


def _descendants(root: Node) -> Iterator[Node]:
    for node in root.iter_elements():
        if node is not root:
            yield node


@dataclass(frozen=True)
class Place:
    """Where a value is: a selector (or the root itself) and an optional attribute."""

    selector: Selector | None
    attribute: str = ""

    def nodes(self, root: Node, source: str) -> list[Node]:
        if self.selector is None:
            return [root]
        return select(root, self.selector, source)

    def __str__(self) -> str:
        head = self.selector.text if self.selector is not None else ""
        if self.attribute:
            return f"{head}@{self.attribute}"
        return head or ":scope"


def parse_place(text: str) -> Place:
    """``"h3"``, ``"img@src"``, ``"@data-tags"`` (the root's own attribute) or ``":scope"``
    (the root's own text)."""
    head, at, attribute = text.rpartition("@") if "@" in text else (text, "", "")
    if not at:
        head = text
    attribute = attribute.strip().lower()
    if at and not attribute:
        raise SelectorError(f"{text!r}: nothing after @ (write img@src)")
    head = head.strip()
    if head in ("", ":scope"):
        return Place(None, attribute)
    return Place(parse_selector(head), attribute)


# writing selectors


@dataclass(frozen=True)
class Target:
    """Under ``root`` (in the page ``source``), a selector must find exactly ``nodes``."""

    root: Node
    nodes: tuple[Node, ...]
    source: str


def _stable_classes(node: Node, source: str, *, every: bool = False) -> list[str]:
    from karni_cli.design.values import is_utility_class

    if every:
        return node.classes(source)
    return [token for token in node.classes(source) if not is_utility_class(token)]


def _compound_text(node: Node, source: str, *, nth: bool = False, every: bool = False) -> str:
    text = node.tag + "".join(f".{token}" for token in _stable_classes(node, source, every=every))
    if nth and node.parent is not None:
        same = [child for child in node.parent.elements() if child.tag == node.tag]
        if len(same) > 1:
            text += f":nth-of-type({same.index(node) + 1})"
    return text


def _chain(node: Node, root: Node) -> list[Node]:
    """``node`` and its ancestors below ``root``, nearest first."""
    found: list[Node] = []
    current: Node | None = node
    while current is not None and current is not root:
        found.append(current)
        current = current.parent
    return found


def _exact(selector: str, targets: Sequence[Target]) -> bool:
    try:
        parsed = parse_selector(selector)
    except SelectorError:
        return False
    for target in targets:
        found = select(target.root, parsed, target.source)
        if {id(node) for node in found} != {id(node) for node in target.nodes}:
            return False
    return True


def _with_tags(selector: str, tags: list[str], tag: str) -> str:
    """``h2.x`` as ``h1.x, h2.x`` when the same element is a different heading elsewhere."""
    if len(tags) < 2 or not selector.split(" ")[-1].startswith(tag):
        return selector
    head, _, last = selector.rpartition(" ")
    variants = []
    for other in tags:
        variants.append((head + " " if head else "") + other + last[len(tag) :])
    return ", ".join(variants)


def _excluded(targets: Sequence[Target], *, every: bool) -> list[str]:
    """Classes of the same-tag siblings a selector must leave out, when no target has one."""
    wanted = {id(n) for t in targets for n in t.nodes}
    theirs: set[str] = set()
    mine: set[str] = set()
    for target in targets:
        for node in target.nodes:
            mine |= set(_stable_classes(node, target.source, every=every))
            parent = node.parent
            if parent is None:
                continue
            for sibling in parent.elements():
                if sibling.tag != node.tag or id(sibling) in wanted:
                    continue
                classes = _stable_classes(sibling, target.source, every=every)
                if not classes:
                    return []
                theirs |= set(classes)
    found = sorted(theirs - mine)
    return [name for name in found if re.match(r"^-?[_A-Za-z][-\w]*$", name)]


def write_selector(targets: Sequence[Target], anchors: Sequence[str] = ()) -> str:
    """The shortest selector that finds exactly each target's nodes under its root.

    Tries the element's own tag and classes, then the nearest ancestors with
    classes (or a section anchor) before it, then a child path from nearer
    ancestors, then leaving out its siblings' own classes (``p:not(.role)``).
    It does all that with the classes that name things, then with every
    class (``col-md-4`` too). Last come a child path from the root that
    numbers the ancestors, and one that numbers every step. Returns the last
    try when nothing is exact.
    """
    first = next((t for t in targets if t.nodes), None)
    if first is None:
        return "*"
    node = first.nodes[0]
    chain = _chain(node, first.root)
    tags = sorted({n.tag for t in targets for n in t.nodes})
    source = first.source
    tried: list[str] = []

    def attempt(selector: str) -> str | None:
        candidate = _with_tags(selector, tags, node.tag)
        tried.append(candidate)
        return candidate if _exact(candidate, targets) else None

    for every in (False, True):
        own = _compound_text(node, source, every=every)
        found = attempt(own)
        if found:
            return found
        for anchor in anchors:
            found = attempt(f"{anchor} {own}")
            if found:
                return found
            for depth in range(1, len(chain)):
                steps = [
                    _compound_text(n, source, every=every) for n in reversed(chain[: depth + 1])
                ]
                found = attempt(f"{anchor} " + " > ".join(steps))
                if found:
                    return found
        for ancestor in chain[1:]:
            compound = _compound_text(ancestor, source, every=every)
            ident = ancestor.attr(source, "id")
            if compound == ancestor.tag and not ident:
                continue
            prefix = f"#{ident}" if ident and re.match(r"^[A-Za-z][-\w]*$", ident) else compound
            for joiner in (" > ", " "):
                if joiner == " > " and ancestor is not node.parent:
                    continue
                found = attempt(prefix + joiner + own)
                if found:
                    return found
        for depth in range(1, len(chain)):
            steps = [_compound_text(n, source, every=every) for n in reversed(chain[: depth + 1])]
            found = attempt(" > ".join(steps))
            if found:
                return found
        # Paragraphs next to one with a class of its own: p:not(.role).
        excluded = _excluded(targets, every=every)
        if excluded:
            mine = own + "".join(f":not(.{name})" for name in excluded)
            for candidate in [mine, *(f"{a} {mine}" for a in anchors)]:
                found = attempt(candidate)
                if found:
                    return found
            if node.parent is not None and node.parent is not first.root:
                found = attempt(f"{_compound_text(node.parent, source, every=every)} > {mine}")
                if found:
                    return found
    ancestors = [_compound_text(n, source, nth=True, every=True) for n in reversed(chain[1:])]
    found = attempt("> " + " > ".join([*ancestors, _compound_text(node, source, every=True)]))
    if found:
        return found
    steps = [_compound_text(n, source, nth=True, every=True) for n in reversed(chain)]
    found = attempt("> " + " > ".join(steps))
    if found:
        return found
    return tried[-1]
