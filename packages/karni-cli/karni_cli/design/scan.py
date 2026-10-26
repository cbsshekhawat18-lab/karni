"""The values inside a piece of markup, and the structures that repeat in it.

:func:`scan` walks an element and returns its :class:`Slot` values (a text,
an image, a link, a data attribute), each at a *path* of steps from the
element (``div.card-body`` → ``h``), and the :class:`Collection` structures
in it: sibling elements with the same step and a similar inside, two or
more times (cards, list items, gallery images). An item of a collection is
scanned the same way, so a project card's gallery is a collection nested in
the card.

The steps leave out what varies between copies of one structure: utility
classes (``col-md-4``, ``mt-3``), a class only one item has (the slider's
``is-active``), the level of a heading (``h1`` and ``h2`` are both ``h``).
A run of plain paragraphs is one value, joined by blank lines, and a
definition list is one value, its terms and definitions in pairs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from karni_cli.design.parse import Node
from karni_cli.design.values import INLINE, is_utility_class, text_of

__all__ = ["Collection", "Hint", "Item", "Scan", "Slot", "hints_of", "scan", "step_of"]

#: Never content: their subtree is skipped.
SKIP: Final = frozenset(
    {
        "script",
        "style",
        "noscript",
        "svg",
        "form",
        "input",
        "select",
        "textarea",
        "iframe",
        "canvas",
        "video",
        "audio",
        "object",
        "embed",
        "head",
        "link",
        "meta",
    }
)
#: May sit inside a line of text without breaking it into two values.
_PHRASING: Final = INLINE | {"button", "label", "img", "picture", "source"}
_HEADINGS: Final = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
#: Attributes whose value is content (the rest is behaviour or styling).
_LINK_TAGS: Final = frozenset({"a", "area"})
_SIMILAR: Final = 0.5

Hint = tuple[tuple[str, ...], str]


@dataclass
class Slot:
    """One value: where it is (``path``), what it is (``kind``) and the value as written.

    Kinds: ``text`` (an element's text), ``image`` (an ``<img>`` or a CSS
    ``url()``), ``alt``, ``link`` (an ``href``), ``datetime``, ``data`` (a
    ``data-*`` attribute), ``id``, ``pairs`` (a definition list) and ``flag``
    (a class token some items of a collection have).
    """

    path: tuple[str, ...]
    kind: str
    attr: str
    node: Node
    value: str
    highlight: tuple[str, ...] = ()
    pairs: tuple[tuple[str, str], ...] = ()
    run: bool = False  # several paragraphs, joined
    nodes: tuple[Node, ...] = ()  # every paragraph of a run

    @property
    def key(self) -> tuple[tuple[str, ...], str, str]:
        return (self.path, self.kind, self.attr)

    @property
    def elements(self) -> tuple[Node, ...]:
        """The element(s) the value is read from."""
        return self.nodes or (self.node,)

    def prefixed(self, step: str) -> Slot:
        return Slot(
            (step, *self.path),
            self.kind,
            self.attr,
            self.node,
            self.value,
            self.highlight,
            self.pairs,
            self.run,
            self.nodes,
        )


@dataclass
class Item:
    """One copy of a repeated structure: its root and what is inside it."""

    node: Node
    slots: list[Slot] = field(default_factory=list)
    collections: list[Collection] = field(default_factory=list)

    def shape(self) -> set[tuple[tuple[str, ...], str, str]]:
        found = {slot.key for slot in self.slots}
        found |= {(c.path, "collection", c.step) for c in self.collections}
        return found


@dataclass
class Collection:
    """Sibling elements with one step, two or more times: the items of a structure."""

    container: Node
    path: tuple[str, ...]  # the container's path from the scanned root
    step: str  # the items' step
    items: list[Item]

    def prefixed(self, step: str) -> Collection:
        return Collection(self.container, (step, *self.path), self.step, self.items)


@dataclass
class Scan:
    slots: list[Slot] = field(default_factory=list)
    collections: list[Collection] = field(default_factory=list)


def _classes(node: Node, source: str) -> list[str]:
    return [token for token in node.classes(source) if not is_utility_class(token)]


def step_of(node: Node, source: str, drop: Iterable[str] = ()) -> str:
    """``div.card-body``: the tag (``h`` for any heading) and its lasting classes."""
    tag = "h" if node.tag in _HEADINGS else node.tag
    dropped = set(drop)
    classes = [token for token in _classes(node, source) if token not in dropped]
    return tag + "".join(f".{token}" for token in classes)


def _has_text(node: Node, source: str) -> bool:
    return any(child.kind == "text" and child.text(source).strip() for child in node.iter())


def _own_text(node: Node, source: str) -> bool:
    return any(child.kind == "text" and child.text(source).strip() for child in node.children)


#: Elements that hold a line of text even when an inline element carries all of it.
_TEXT_TAGS: Final = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "li",
        "dt",
        "dd",
        "figcaption",
        "blockquote",
        "td",
        "th",
        "label",
        "caption",
        "summary",
        "address",
        "q",
        "cite",
    }
)


def is_holder(node: Node, source: str) -> bool:
    """A line of text: only phrasing inside, and its text in one piece.

    ``<p>Call <a>us</a></p>`` and ``<h3><button>Name</button></h3>`` are one
    value each. ``<div class="stat"><b>20+</b><span>Years</span></div>`` is
    two: it has no text of its own and two children that carry text. A
    ``<div>`` around one link is not a line: the link is.
    """
    if node.tag in SKIP or node.tag in ("img", "br", "hr", "dl"):
        return False
    if not _has_text(node, source):
        return False
    for descendant in node.iter_elements():
        if descendant is not node and descendant.tag not in _PHRASING:
            return False
    if _own_text(node, source):
        return True
    carriers = [child for child in node.elements() if _has_text(child, source)]
    return (
        node.tag in _TEXT_TAGS
        and len(carriers) == 1
        and (is_holder(carriers[0], source) or carriers[0].tag == "br")
    )


def _style_urls(value: str) -> list[str]:
    import re

    return [
        match.group(2).strip()
        for match in re.finditer(r"""url\(\s*(["']?)([^"')]+)\1\s*\)""", value)
    ]


def _attribute_slots(node: Node, source: str, path: tuple[str, ...]) -> list[Slot]:
    """The content attributes of one element (not its text)."""
    found: list[Slot] = []
    attrs = node.attrs(source)
    if node.tag == "img":
        src = attrs.get("src")
        if src:
            found.append(Slot(path, "image", "src", node, src))
        if "alt" in attrs:
            found.append(Slot(path, "alt", "alt", node, attrs.get("alt") or ""))
    if node.tag in _LINK_TAGS:
        href = (attrs.get("href") or "").strip()
        if href and not href.lower().startswith("javascript:") and href != "#":
            found.append(Slot(path, "link", "href", node, href))
    if node.tag == "time" and attrs.get("datetime"):
        found.append(Slot(path, "datetime", "datetime", node, attrs.get("datetime") or ""))
    for name, value in attrs.items():
        if name.startswith("data-") and value and value.strip():
            found.append(Slot(path, "data", name, node, value.strip()))
    if attrs.get("id"):
        found.append(Slot(path, "id", "id", node, attrs.get("id") or ""))
    style = attrs.get("style") or ""
    if "url(" in style:
        urls = _style_urls(style)
        if urls:
            found.append(Slot(path, "image", "style", node, urls[0]))
    return found


def _pairs(node: Node, source: str) -> tuple[tuple[str, str], ...]:
    """A definition list's terms and definitions, wrapped in ``<div>`` or not."""
    found: list[tuple[str, str]] = []
    term: str | None = None
    for element in node.iter_elements():
        if element.tag == "dt":
            if term is not None:
                found.append((term, ""))
            term = text_of(element, source, highlight=False)[0]
        elif element.tag == "dd":
            found.append((term or "", text_of(element, source, highlight=False)[0]))
            term = None
    if term is not None:
        found.append((term, ""))
    return tuple(found)


class _Scanner:
    def __init__(self, source: str, hints: set[Hint]) -> None:
        self.source = source
        self.hints = hints

    def element(self, node: Node, path: tuple[str, ...] = ()) -> Scan:
        """Scan ``node`` itself: its attributes, its text or its children."""
        result = Scan()
        result.slots.extend(_attribute_slots(node, self.source, ()))
        if node.tag == "dl":
            pairs = _pairs(node, self.source)
            if pairs:
                result.slots.append(Slot((), "pairs", "", node, "", pairs=pairs))
            return result
        if is_holder(node, self.source):
            text, highlight = text_of(node, self.source)
            result.slots.append(Slot((), "text", "", node, text, tuple(highlight)))
            for inner in node.iter_elements():
                if inner is node:
                    continue
                result.slots.extend(
                    _attribute_slots(inner, self.source, self._inline_path(node, inner))
                )
            return result
        self.children(node, path, result)
        return result

    def _inline_path(self, holder: Node, inner: Node) -> tuple[str, ...]:
        steps: list[str] = []
        current: Node | None = inner
        while current is not None and current is not holder:
            steps.append(step_of(current, self.source))
            current = current.parent
        return tuple(reversed(steps))

    def children(self, node: Node, path: tuple[str, ...], result: Scan) -> None:
        kids = [child for child in node.elements() if child.tag not in SKIP]
        groups: dict[str, list[Node]] = {}
        for child in kids:
            groups.setdefault(step_of(child, self.source), []).append(child)
        # A class only some siblings of one tag have (``is-active`` on the first
        # slide) is state, not structure: regroup those siblings without it.
        by_tag: dict[str, list[Node]] = {}
        for child in kids:
            by_tag.setdefault(child.tag, []).append(child)
        steps: dict[int, str] = {}
        for members in by_tag.values():
            if len(members) < 2:
                continue
            counts: Counter[str] = Counter()
            for member in members:
                counts.update(set(_classes(member, self.source)))
            rare = {token for token, count in counts.items() if count * 2 < len(members)}
            if not rare:
                continue
            # Only a class next to one the siblings share is state (``slide slide--current``).
            # A paragraph with its own class among plain ones is a value of its own.
            for member in members:
                own = _classes(member, self.source)
                lasting = [token for token in own if token not in rare]
                if rare & set(own) and lasting:
                    steps[id(member)] = step_of(member, self.source, rare)
        if steps:
            groups = {}
            for child in kids:
                key = steps.get(id(child)) or step_of(child, self.source)
                groups.setdefault(key, []).append(child)
        same_tag: Counter[str] = Counter(child.tag for child in kids)
        for step, members in groups.items():
            forced = (path, step) in self.hints
            if (len(members) >= 2 or forced) and len({member.tag for member in members}) == 1:
                if self._run(members):
                    result.slots.append(self._run_slot(step, members))
                    continue
                scans = [self.element(member, ()) for member in members]
                items = [
                    Item(member, scan.slots, scan.collections)
                    for member, scan in zip(members, scans, strict=True)
                    if scan.slots or scan.collections
                ]
                similar = _similar(items)
                if len(similar) >= 2 or (forced and similar):
                    result.collections.append(Collection(node, (), step, similar))
                    kept = {id(i.node) for i in similar}
                    rest = [member for member in members if id(member) not in kept]
                else:
                    rest = members
            else:
                rest = members
            for member in rest:
                member_step = step
                if same_tag[member.tag] > 1 and len(members) > 1:
                    position = [c for c in kids if c.tag == member.tag].index(member) + 1
                    member_step = f"{step}:nth-of-type({position})"
                inner = self.element(member, (*path, member_step))
                result.slots.extend(slot.prefixed(member_step) for slot in inner.slots)
                result.collections.extend(c.prefixed(member_step) for c in inner.collections)

    def _run(self, members: list[Node]) -> bool:
        """Plain paragraphs in a row: one value, not a list."""
        return all(
            member.tag == "p"
            and is_holder(member, self.source)
            and not _classes(member, self.source)
            for member in members
        )

    def _run_slot(self, step: str, members: list[Node]) -> Slot:
        texts: list[str] = []
        highlight: list[str] = []
        for member in members:
            text, found = text_of(member, self.source)
            if text:
                texts.append(text)
            highlight.extend(spec for spec in found if spec not in highlight)
        return Slot(
            (step,),
            "text",
            "",
            members[0],
            "\n\n".join(texts),
            tuple(highlight),
            run=True,
            nodes=tuple(members),
        )


def _similar(items: list[Item]) -> list[Item]:
    """The items whose inside matches what most of them share."""
    if len(items) < 2:
        return items
    counts: Counter[tuple[tuple[str, ...], str, str]] = Counter()
    shapes = [item.shape() for item in items]
    for shape in shapes:
        counts.update(shape)
    core = {key for key, count in counts.items() if count * 2 >= len(items)}
    if not core:
        return []
    kept: list[Item] = []
    for item, shape in zip(items, shapes, strict=True):
        union = shape | core
        if union and len(shape & core) / len(union) >= _SIMILAR:
            kept.append(item)
    return kept


def hints_of(found: Scan) -> set[Hint]:
    """Every (container path, item step) of the collections in ``found``, at every depth.

    Paths are relative to the root each one was found under (the scanned
    element, or the item that holds a nested collection).
    """
    keys: set[Hint] = set()
    pending = list(found.collections)
    while pending:
        collection = pending.pop()
        keys.add((collection.path, collection.step))
        for item in collection.items:
            pending.extend(item.collections)
    return keys


def scan(node: Node, source: str, *, hints: set[Hint] | None = None) -> Scan:
    """The slots and collections inside ``node`` (``node``'s own attributes included).

    A structure that repeats in some copies of an item and not in others (a
    project with one gallery picture next to projects with three) is read
    as a collection in all of them: the scan runs twice, the second time
    with the collections the first found. ``hints`` adds more such pairs
    from elsewhere (the same gallery on another detail page).
    """
    first = _Scanner(source, set(hints or ())).element(node)
    found = hints_of(first) | set(hints or ())
    if not found - set(hints or ()):
        return first
    return _Scanner(source, found).element(node)
