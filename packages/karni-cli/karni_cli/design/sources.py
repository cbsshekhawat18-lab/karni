"""The pages of a design, its detail pages, and the lists that show the same items.

Part of :mod:`karni_cli.design.analyze` (see its docstring for the whole
algorithm): reading the pages with the layout set aside, finding a model's
detail pages, building the *sources* (a list on a page, a family of detail
pages, a list nested in another's items) and telling which sources hold the
same items (links, anchors, keys and titles that point at each other). The
keys a content map reads (:func:`page_slug`, :func:`link_key`,
:func:`attr_key`) live here too, so analyze and extract compute them alike.
"""

from __future__ import annotations

import posixpath
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any, Final

from karni_cli.design import compare
from karni_cli.design import site as design_site
from karni_cli.design.parse import Document, Node, collapse
from karni_cli.design.rewrite import Mapped, Reference
from karni_cli.design.scan import Collection, Hint, Scan, Slot, scan
from karni_cli.design.values import (
    slugify,
)

#: Share of a source's items that must point at another source's items to be the same items.
_MATCH: Final = 0.6

#: Two pages are one model's detail pages when their structures are this alike: a folder's
#: pages, and pages a list links to item by item (the links say more than the structure).
_ALIKE: Final = 0.5
_ALIKE_LINKED: Final = 0.3

SlotKey = tuple[tuple[str, ...], str, str]


# --- the design --------------------------------------------------------------


@dataclass
class Page:
    """A content page of the design (not a redirect stub, not an error page)."""

    path: str
    name: str
    text: str
    doc: Document
    title: str
    description: str
    description_node: Node | None
    blocks: list[tuple[str, Node]]
    found: Scan = field(default_factory=Scan)
    family: Family | None = None

    @property
    def dir(self) -> str:
        return posixpath.dirname(self.path)

    @property
    def body(self) -> Node:
        return self.doc.body_or_root()

    @property
    def root(self) -> Node:
        """What the map's selectors for this page start from: the whole document."""
        return self.doc.root

    @property
    def slug(self) -> str:
        stem = self.path.rsplit(".", 1)[0]
        stem = stem.removesuffix("/index")
        return slugify(posixpath.basename(stem)) or "page"

    def shape(self) -> set[tuple[tuple[str, ...], str, str]]:
        found = {slot.key for slot in self.found.slots if slot.kind not in ("id", "data")}
        found |= {(c.path, "collection", c.step) for c in self.found.collections}
        return found


@dataclass
class Family:
    """Pages that are one model's detail pages."""

    pages: list[Page]
    folder: str = ""
    listed_on: Page | None = None


def _block_keys(blocks: Sequence[compare.Block]) -> list[str]:
    seen: Counter[str] = Counter()
    keys: list[str] = []
    for block in blocks:
        name = block.name or block.node.tag
        seen[name] += 1
        keys.append(name if seen[name] == 1 else f"{name}-{seen[name]}")
    return keys


def read_design(design: Path, app: str) -> tuple[list[Page], Mapped]:
    """The content pages of ``design`` with their own blocks (the layout set aside)."""
    texts, files = design_site.scan(design)
    if not texts:
        raise ValueError(f"{design} has no .html page.")
    sources, mapped = design_site._read_pages(texts, files, app)
    content = [page for page in sources if page.redirect is None and not page.error]
    for page in content:
        design_site._read_structure(page, mapped)
    layout = compare.layout(
        {page.path: page.blocks for page in content},
        {page.path: page.text for page in sources},
        [page.path for page in content],
    )
    partial_seen: set[str] = set()
    pages: list[Page] = []
    for source in content:
        own: list[compare.Block] = []
        for entry in layout.pages[source.path].content:
            if isinstance(entry, compare.Block):
                own.append(entry)
            else:
                group = next(g for g in layout.partials if g.name == entry)
                # A partial is the same markup on several pages: its content counts once.
                if group.name not in partial_seen and group.reference == source.path:
                    partial_seen.add(group.name)
                    own.append(group.instances[source.path])
        title = ""
        if source.title is not None:
            title = unescape(collapse(source.title.inner_text(source.text)))
        description = ""
        if source.description is not None:
            description = collapse(source.description.attr(source.text, "content") or "")
        pages.append(
            Page(
                source.path,
                source.name,
                source.text,
                source.doc,
                title,
                description,
                source.description,
                list(zip(_block_keys(own), [block.node for block in own], strict=True)),
            )
        )
    return pages, mapped


def _scan_page(page: Page, hints: set[Hint] | None = None) -> Scan:
    found = Scan()
    for key, node in page.blocks:
        # Hints carry the block key as their first step; inside the block they do not.
        own = {(path[1:], step) for path, step in hints or () if path and path[0] == key}
        own |= {(path, step) for path, step in hints or () if not path or path[0] != key}
        inner = scan(node, page.text, hints=own)
        found.slots.extend(slot.prefixed(key) for slot in inner.slots)
        found.collections.extend(c.prefixed(key) for c in inner.collections)
    return found


# --- detail pages ------------------------------------------------------------


def _jaccard(a: set[Any], b: set[Any]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _alike(pages: list[Page], threshold: float = _ALIKE) -> list[Page]:
    """The pages whose structure matches what most of them share."""
    if len(pages) < 2:
        return []
    shapes = [page.shape() for page in pages]
    counts: Counter[Any] = Counter()
    for shape in shapes:
        counts.update(shape)
    core = {key for key, count in counts.items() if count * 2 >= len(pages)}
    return [
        page
        for page, shape in zip(pages, shapes, strict=True)
        if _jaccard(shape, core) >= threshold
    ]


def _resolve(mapped: Mapped, value: str, page: Page) -> Reference:
    return mapped.resolve(unescape(value), page.dir)


def find_families(pages: list[Page], mapped: Mapped) -> list[Family]:
    """Detail pages: the pages one list links to item by item, or a folder's pages, alike."""
    by_path = {page.path: page for page in pages}
    home = next((page for page in pages if page.name == "home"), None)
    candidates: list[tuple[list[Page], str, Page | None]] = []
    for page in pages:
        for collection in _all_collections(page.found.collections):
            targets: list[str] = []
            for item in collection.items:
                linked = {
                    ref.path
                    for slot in item.slots
                    if slot.kind == "link"
                    and (ref := _resolve(mapped, slot.value, page)).kind == "page"
                    and not ref.fragment
                    and ref.path != page.path
                    and ref.path in by_path
                }
                if len(linked) == 1:
                    targets.append(linked.pop())
            if len(targets) >= 2 and len(set(targets)) == len(targets):
                group = [by_path[target] for target in targets if by_path[target] is not home]
                candidates.append((group, "", page))
    folders: dict[str, list[Page]] = {}
    for page in pages:
        folder = page.dir
        if folder and not page.path.endswith("/index.html"):
            folders.setdefault(folder, []).append(page)
    for folder, members in folders.items():
        candidates.append((members, folder, None))
    families: list[Family] = []
    taken: set[str] = set()
    for members, folder, listed_on in sorted(candidates, key=lambda c: -len(c[0])):
        fresh = [page for page in members if page.path not in taken]
        alike = _alike(fresh, _ALIKE_LINKED if listed_on is not None else _ALIKE)
        if len(alike) < 2:
            continue
        family = Family(alike, folder, listed_on)
        for page in alike:
            page.family = family
            taken.add(page.path)
        families.append(family)
    for family in families:
        if not family.folder:
            folders_of = {page.dir for page in family.pages}
            if len(folders_of) == 1 and next(iter(folders_of)):
                family.folder = next(iter(folders_of))
        if family.listed_on is None or family.listed_on is home:
            family.listed_on = next(
                (
                    c[2]
                    for c in candidates
                    if c[2] is not None
                    and c[2] is not home
                    and {p.path for p in c[0]} >= {p.path for p in family.pages}
                ),
                family.listed_on,
            )
    return families


def _all_collections(collections: Iterable[Collection]) -> Iterable[Collection]:
    for collection in collections:
        yield collection
        for item in collection.items:
            yield from _all_collections(item.collections)


# --- sources -----------------------------------------------------------------


@dataclass(eq=False)
class Entry:
    """One item of a source: a card, a list item, a detail page."""

    source: Source
    page: Page
    node: Node
    slots: list[Slot]
    index: int
    parent: Entry | None
    collections: list[Collection]
    tokens: set[str] = field(default_factory=set)
    entity: Entity | None = None

    def value(self, key: tuple[tuple[str, ...], str, str]) -> Slot | None:
        return next((slot for slot in self.slots if slot.key == key), None)


@dataclass(eq=False)
class Source:
    """A list on a page, the detail pages of a family, or a list nested in another's items."""

    id: int
    kind: str  # list | detail | nested
    pages: list[Page]
    path: tuple[str, ...]
    step: str
    parent: Source | None
    entries: list[Entry] = field(default_factory=list)
    family: Family | None = None
    title_key: tuple[tuple[str, ...], str, str] | None = None
    container: Node | None = None

    @property
    def page(self) -> Page:
        return self.pages[0]

    def ancestors(self) -> list[Source]:
        found: list[Source] = []
        current = self.parent
        while current is not None:
            found.append(current)
            current = current.parent
        return found

    def slot_keys(self) -> list[tuple[tuple[str, ...], str, str]]:
        """Every slot key of the entries, in the order they first appear."""
        seen: dict[tuple[tuple[str, ...], str, str], None] = {}
        for entry in self.entries:
            for slot in entry.slots:
                seen.setdefault(slot.key, None)
        return list(seen)

    def values(self, key: tuple[tuple[str, ...], str, str]) -> list[Slot | None]:
        return [entry.value(key) for entry in self.entries]

    def shape(self) -> set[tuple[tuple[str, ...], str, str]]:
        found: set[tuple[tuple[str, ...], str, str]] = set()
        for entry in self.entries:
            found |= {slot.key for slot in entry.slots}
            found |= {(c.path, "collection", c.step) for c in entry.collections}
        return found

    @property
    def block(self) -> str:
        return self.path[0] if self.path else ""

    def describe(self) -> str:
        if self.kind == "detail":
            return f"{len(self.pages)} detail pages ({', '.join(p.path for p in self.pages[:3])}"
        where = (
            self.page.path
            if len({p.path for p in self.pages}) == 1
            else (f"{len({p.path for p in self.pages})} pages")
        )
        return f"{where}: {self.step} x{len(self.entries)}"


@dataclass(eq=False)
class Entity:
    """One row: the entries in every source that show the same item."""

    entries: list[Entry] = field(default_factory=list)
    tokens: set[str] = field(default_factory=set)
    key: str = ""

    def entry_in(self, source: Source) -> Entry | None:
        return next((entry for entry in self.entries if entry.source is source), None)


class _Sources:
    def __init__(self) -> None:
        self.all: list[Source] = []

    def add(self, source: Source) -> Source:
        self.all.append(source)
        return source

    def nested(self, parent: Source) -> None:
        groups: dict[tuple[tuple[str, ...], str], list[tuple[Entry, Collection]]] = {}
        for entry in parent.entries:
            for collection in entry.collections:
                groups.setdefault((collection.path, collection.step), []).append(
                    (entry, collection)
                )
        for (path, step), members in groups.items():
            source = self.add(
                Source(
                    len(self.all),
                    "nested",
                    _unique_pages(entry.page for entry, _ in members),
                    path,
                    step,
                    parent,
                    container=members[0][1].container,
                )
            )
            for entry, collection in members:
                for index, item in enumerate(collection.items, start=1):
                    source.entries.append(
                        Entry(
                            source,
                            entry.page,
                            item.node,
                            item.slots,
                            index,
                            entry,
                            item.collections,
                        )
                    )
            self.nested(source)


def _unique_pages(pages: Iterable[Page]) -> list[Page]:
    seen: dict[str, Page] = {}
    for page in pages:
        seen.setdefault(page.path, page)
    return list(seen.values())


def build_sources(pages: list[Page], families: list[Family]) -> list[Source]:
    sources = _Sources()
    for family in families:
        source = sources.add(
            Source(len(sources.all), "detail", family.pages, (), "page", None, family=family)
        )
        for index, page in enumerate(family.pages, start=1):
            slots = list(page.found.slots)
            if page.description_node is not None and page.description:
                slots.append(
                    Slot(("meta",), "text", "description", page.description_node, page.description)
                )
            source.entries.append(
                Entry(source, page, page.root, slots, index, None, list(page.found.collections))
            )
        sources.nested(source)
    for page in pages:
        if page.family is not None:
            continue
        for collection in page.found.collections:
            source = sources.add(
                Source(
                    len(sources.all),
                    "list",
                    [page],
                    collection.path,
                    collection.step,
                    None,
                    container=collection.container,
                )
            )
            for index, item in enumerate(collection.items, start=1):
                source.entries.append(
                    Entry(source, page, item.node, item.slots, index, None, item.collections)
                )
            sources.nested(source)
    for source in sources.all:
        source.title_key = _title_key(source)
    return sources.all


def _is_heading(key: tuple[tuple[str, ...], str, str]) -> bool:
    path, kind, _ = key
    return kind == "text" and bool(path) and path[-1].split(".", 1)[0].split(":", 1)[0] == "h"


def _norm(text: str) -> str:
    return collapse(text.replace("*", "").replace("\\", "")).casefold()


def _title_key(source: Source) -> tuple[tuple[str, ...], str, str] | None:
    """The slot that names each item: the first heading, else the item's own text."""
    keys = source.slot_keys()
    if source.kind == "detail":
        for key in keys:
            if _is_heading(key) and any(
                (slot := entry.value(key)) is not None and slot.node.tag == "h1"
                for entry in source.entries
            ):
                return key
    candidates = [key for key in keys if _is_heading(key)]
    candidates += [key for key in keys if key[1] == "text" and key[0] == ()]
    candidates += [key for key in keys if key[1] == "data" and key[2] == "data-caption"]
    for key in candidates:
        values = [_norm(slot.value) for slot in source.values(key) if slot is not None]
        present = len(values)
        if present * 2 >= len(source.entries) and len(set(values)) == present and present >= 1:
            return key
    return None


# --- the same items ----------------------------------------------------------


def _common_prefix(values: list[str]) -> str:
    """The prefix every value shares, up to its last ``-`` or ``_`` (``p-``, ``tab-``)."""
    if len(values) < 2:
        return ""
    prefix = posixpath.commonprefix(values)
    cut = max(prefix.rfind("-"), prefix.rfind("_"))
    return prefix[: cut + 1] if cut >= 0 else ""


def _groups(source: Source) -> list[list[Entry]]:
    """The source's entries per parent item (all of them, for a top-level source)."""
    if source.kind != "nested":
        return [source.entries]
    by_parent: dict[int, list[Entry]] = {}
    for entry in source.entries:
        by_parent.setdefault(id(entry.parent), []).append(entry)
    return list(by_parent.values())


def _distinct(
    source: Source, key: tuple[tuple[str, ...], str, str], values: dict[int, str]
) -> bool:
    """Whether ``key``'s values differ between the items of each list of the source."""
    for group in _groups(source):
        seen = [values[id(entry)] for entry in group if id(entry) in values]
        if len(seen) != len(set(seen)):
            return False
    return True


def identity_tokens(source: Source, mapped: Mapped) -> dict[str, str]:
    """Tokens that name each entry, and the key rule each kind comes from.

    Returns the prefixes found (``{"id": "p-"}``) for the key rules.
    """
    prefixes: dict[str, str] = {}
    if source.kind == "detail":
        for entry in source.entries:
            entry.tokens = {f"page:{entry.page.path}", f"key:{entry.page.slug}"}
            title = entry.value(source.title_key) if source.title_key else None
            if title is not None and title.value:
                entry.tokens.add(f"title:{_norm(title.value)}")
        return prefixes
    for entry in source.entries:
        entry.tokens = set()
    for key in source.slot_keys():
        path, kind, attr = key
        if kind == "link":
            refs: dict[int, Reference] = {}
            for entry in source.entries:
                slot = entry.value(key)
                if slot is not None:
                    refs[id(entry)] = _resolve(mapped, slot.value, entry.page)
            values = {k: f"{r.path}{r.fragment}" for k, r in refs.items()}
            if not _distinct(source, key, values):
                continue
            for entry in source.entries:
                ref = refs.get(id(entry))
                if ref is None:
                    continue
                if ref.kind == "page" and not ref.fragment:
                    entry.tokens.add(f"page:{ref.path}")
                if ref.fragment:
                    entry.tokens.add(f"key:{ref.fragment[1:]}")
        elif kind in ("id", "data") and path == ():
            raw = {
                id(entry): slot.value
                for entry in source.entries
                if (slot := entry.value(key)) is not None and " " not in slot.value.strip()
            }
            if len(raw) * 2 < len(source.entries) or not _distinct(source, key, raw):
                continue
            prefix = _common_prefix(list(raw.values()))
            if prefix:
                prefixes[attr] = prefix
            for entry in source.entries:
                value = raw.get(id(entry))
                if value:
                    entry.tokens.add(f"key:{value}")
                    if prefix:
                        entry.tokens.add(f"key:{value[len(prefix) :]}")
    if source.title_key is not None:
        for entry in source.entries:
            slot = entry.value(source.title_key)
            if slot is not None and slot.value:
                entry.tokens.add(f"title:{_norm(slot.value)}")
    return prefixes


def _match(a: Source, b: Source) -> list[tuple[Entry, Entry]]:
    """Entries of ``a`` that point at exactly one entry of ``b``."""
    index: dict[str, set[int]] = {}
    for position, entry in enumerate(b.entries):
        for token in entry.tokens:
            index.setdefault(token, set()).add(position)
    pairs: list[tuple[Entry, Entry]] = []
    for entry in a.entries:
        found: set[int] = set()
        for token in entry.tokens:
            found |= index.get(token, set())
        if len(found) == 1:
            pairs.append((entry, b.entries[found.pop()]))
    return pairs


def same_items(a: Source, b: Source) -> bool:
    """``a`` and ``b`` hold the same items (or one holds some of the other's)."""
    if a is b or a in b.ancestors() or b in a.ancestors():
        return False
    if not a.entries or not b.entries:
        return False
    for first, second in ((a, b), (b, a)):
        pairs = _match(first, second)
        if len(pairs) < min(2, len(first.entries)):
            continue
        if len(pairs) < _MATCH * len(first.entries):
            continue
        if first.kind != "nested" and second.kind != "nested":
            targets = [id(other) for _, other in pairs]
            if len(targets) != len(set(targets)):
                continue
        return True
    return False


class _Union:
    def __init__(self, count: int) -> None:
        self.parent = list(range(count))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def join(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


# --- keys --------------------------------------------------------------------


def page_slug(path: str) -> str:
    """A page's key: ``doctors/ada-okoro.html`` → ``ada-okoro``, ``blog/index.html`` → ``blog``."""
    stem = path.rsplit(".", 1)[0]
    stem = stem.removesuffix("/index")
    return slugify(posixpath.basename(stem)) or "page"


def link_key(ref: Reference, strip: str = "") -> str:
    """The key a link names: its ``#anchor`` (without ``strip``), else its page's key."""
    if ref.fragment and len(ref.fragment) > 1:
        anchor = ref.fragment[1:]
        return anchor[len(strip) :] if strip and anchor.startswith(strip) else anchor
    if ref.kind == "page":
        return page_slug(ref.path)
    return ""


def attr_key(value: str, strip: str = "") -> str:
    return value[len(strip) :] if strip and value.startswith(strip) else value


def _constant(source: Source) -> bool:
    """Template, not content: the same values under every parent, or no value that varies."""
    keys = source.slot_keys()
    if not keys:
        return True
    varying = False
    for key in keys:
        values = {(s.value, s.pairs) if s is not None else None for s in source.values(key)}
        if len(values) > 1:
            varying = True
            break
    if not varying and len(source.entries) > 1:
        return True
    groups = _groups(source)
    if len(groups) >= 2:
        sequences = {
            tuple(
                tuple((s.value if s else None) for s in (e.value(k) for k in keys)) for e in group
            )
            for group in groups
        }
        if len(sequences) == 1:
            return True
    return False


@dataclass
class Identity:
    """Which slot names a source's entries: a link, an ``id``/``data-`` attribute, a title."""

    link: SlotKey | None = None
    attr: SlotKey | None = None
    prefix: str = ""


def _identity(source: Source, mapped: Mapped) -> Identity:
    found = Identity()
    if source.kind == "detail":
        return found
    for key in source.slot_keys():
        path, kind, _ = key
        if kind == "link" and found.link is None:
            values = {
                id(entry): f"{ref.path}{ref.fragment}"
                for entry in source.entries
                if (slot := entry.value(key)) is not None
                and (ref := _resolve(mapped, slot.value, entry.page)).kind in ("page", "inert")
                and (ref.kind == "page" or ref.fragment)
            }
            if len(values) * 2 >= len(source.entries) and _distinct(source, key, values):
                found.link = key
        if kind in ("id", "data") and path == () and found.attr is None:
            raw = {
                id(entry): slot.value
                for entry in source.entries
                if (slot := entry.value(key)) is not None and " " not in slot.value.strip()
            }
            if len(raw) == len(source.entries) and _distinct(source, key, raw):
                found.attr = key
                found.prefix = _common_prefix(list(raw.values()))
    return found


def _tokens_of(ref: Reference) -> set[str]:
    found: set[str] = set()
    if ref.kind == "page" and not ref.fragment:
        found.add(f"page:{ref.path}")
    if ref.fragment and len(ref.fragment) > 1:
        found.add(f"key:{ref.fragment[1:]}")
    return found
