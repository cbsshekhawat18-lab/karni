"""What a design's pages share, how they mark the current page, and what changed.

**Shared markup.** Each page's ``<body>`` is a sequence of blocks (its
top-level elements, each with the comments and whitespace before it). A
block's *signature* is its markup with whitespace collapsed, comments
dropped, URLs resolved to the page or file they reach, and the attributes
that mark state (``class``, ``aria-current``, ...) left out. Two blocks with
one signature are the same block. The shared prefix (the header, a
navigation bar) and suffix (a call to action, the footer) are the longest
runs of signatures that most pages (half of them, at least two) start and end
with. A page that lacks one of them, or has a different one in its place,
overrides that block of the layout. A block that is not in the prefix or
suffix but appears on two or more pages becomes a partial.

**The current page.** Inside a shared block, the only attributes that can
differ between pages are the state attributes. For each element, the class
tokens and attributes present on some pages and not others are collected
with the pages that have them: a designer marks the current menu item on
exactly the page it links to, so each marker becomes
``{% ifactive <those pages> %}``. Whatever the design uses, ``class="active"``,
``class="is-current"`` or ``aria-current="page"``, is reproduced on the
pages where it was, and only there.

**Versions.** :func:`diff` compares two ``.karni/design.json`` records: pages
and sections added, removed and changed, partials and assets likewise.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Final

from karni_cli.design.parse import Node, attributes, collapse

__all__ = [
    "STATE_ATTRIBUTES",
    "Block",
    "Group",
    "Layout",
    "Variation",
    "block_name",
    "blocks",
    "diff",
    "element_variations",
    "generalize_tag",
    "layout",
    "section_record",
    "signature",
    "site_name",
]

#: Attributes a design changes per page to mark state: left out of signatures, generalized.
STATE_ATTRIBUTES: Final = ("class", "aria-current", "aria-selected", "aria-expanded")
#: Blocks named after their tag, whatever their class or comment says.
_LANDMARKS: Final = frozenset({"header", "nav", "footer", "main", "aside"})
_SEPARATORS: Final = (" — ", " – ", " | ", " - ", " · ", " • ", " :: ", ": ")

Normalize = Callable[[str, str, str], str]


def _default_normalize(tag: str, name: str, value: str) -> str:
    return value


def signature(node: Node, source: str, normalize: Normalize = _default_normalize) -> str:
    """The markup of ``node`` with the per-page noise removed (see the module docstring)."""
    parts: list[str] = []
    for child in node.iter():
        if child.kind == "text":
            text = collapse(unescape(child.text(source)))
            if text:
                parts.append(text)
        elif child.kind == "element":
            parts.append(f"<{child.tag}")
            for attr in attributes(child.tag_text(source)):
                if attr.name in STATE_ATTRIBUTES:
                    continue
                if attr.value is None:
                    parts.append(f" {attr.name}")
                else:
                    parts.append(f' {attr.name}="{normalize(child.tag, attr.name, attr.value)}"')
            parts.append(">")
    return "".join(parts)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Block:
    """A top-level element of a page's body with the comments and whitespace before it."""

    node: Node
    lead_start: int
    signature: str
    name: str = ""
    page: str = ""  # the page key, set by :func:`layout`

    @property
    def start(self) -> int:
        return self.lead_start

    @property
    def end(self) -> int:
        return self.node.end

    def lead(self, source: str) -> str:
        return source[self.lead_start : self.node.start]


def _label(comment: str) -> str:
    text = re.sub(r"[=\-_*#~]{2,}", " ", comment).strip()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text if text and len(text.split("-")) <= 4 else ""


def block_name(node: Node, source: str, lead: str) -> str:
    """A name for a block: its landmark tag, else the comment before it, its id, its class."""
    if node.tag in _LANDMARKS:
        return node.tag
    comments = re.findall(r"<!--(.*?)-->", lead, re.DOTALL)
    if comments:
        label = _label(comments[-1])
        if label:
            return label
    identifier = node.attr(source, "id")
    if identifier:
        return re.sub(r"[^a-z0-9]+", "-", identifier.lower()).strip("-") or node.tag
    classes = node.classes(source)
    if classes:
        return re.sub(r"[^a-z0-9]+", "-", classes[0].lower()).strip("-") or node.tag
    return node.tag


def blocks(
    container: Node, source: str, normalize: Normalize = _default_normalize
) -> tuple[list[Block], int]:
    """The blocks of ``container`` (its element children) and where its tail starts."""
    found: list[Block] = []
    lead_start = container.inner[0]
    for child in container.children:
        if child.kind != "element":
            continue
        lead = source[lead_start : child.start]
        block = Block(child, lead_start, signature(child, source, normalize))
        block.name = block_name(child, source, lead)
        found.append(block)
        lead_start = child.end
    return found, lead_start


@dataclass
class Group:
    """One shared block: its signature and its instance on each page that has it."""

    signature: str
    name: str
    instances: dict[str, Block] = field(default_factory=dict)  # page key → block
    reference: str = ""  # the page key whose markup is written

    @property
    def tag(self) -> str:
        return self.instances[self.reference].node.tag


@dataclass
class PagePlan:
    """How one page maps onto the layout."""

    #: Layout block name → the page's own block in its place (``None`` leaves it empty).
    overrides: dict[str, Block | None] = field(default_factory=dict)
    #: The page's own content, in order: a block, or a partial group name.
    content: list[Block | str] = field(default_factory=list)


@dataclass
class Layout:
    """The shared prefix and suffix, the partials, and each page's plan."""

    prefix: list[Group]
    suffix: list[Group]
    partials: list[Group]
    pages: dict[str, PagePlan]

    def groups(self) -> list[Group]:
        return [*self.prefix, *self.suffix, *self.partials]


def _looks_like(block: Block, group: Group, source_of: Mapping[str, str]) -> bool:
    """``block`` stands where ``group`` stands: the same landmark, id or first class."""
    reference = group.instances[group.reference].node
    node = block.node
    if node.tag != reference.tag:
        return False
    if node.tag in _LANDMARKS:
        return True
    ref_source = source_of[group.reference]
    own_source = source_of[block.page]
    ref_id, own_id = reference.attr(ref_source, "id"), node.attr(own_source, "id")
    if ref_id and own_id:
        return ref_id == own_id
    ref_classes, own_classes = reference.classes(ref_source), node.classes(own_source)
    return bool(ref_classes and own_classes and ref_classes[0] == own_classes[0])


def _unique(name: str, taken: set[str]) -> str:
    candidate, counter = name, 2
    while candidate in taken:
        candidate = f"{name}-{counter}"
        counter += 1
    taken.add(candidate)
    return candidate


def _run(
    pages: Mapping[str, list[Block]], cursors: dict[str, tuple[int, int]], *, from_end: bool
) -> list[str]:
    """Signatures most pages share at their start (or end): the prefix (or suffix)."""
    count = len(pages)
    threshold = max(2, math.ceil(count / 2))
    matching = set(pages)
    found: list[str] = []
    while matching:
        candidates: Counter[str] = Counter()
        for key in matching:
            low, high = cursors[key]
            if low >= high:
                continue
            index = high - 1 if from_end else low
            candidates[pages[key][index].signature] += 1
        if not candidates:
            break
        sig, number = candidates.most_common(1)[0]
        if number < threshold:
            break
        found.append(sig)
        still: set[str] = set()
        for key in matching:
            low, high = cursors[key]
            index = high - 1 if from_end else low
            if low < high and pages[key][index].signature == sig:
                still.add(key)
                cursors[key] = (low, high - 1) if from_end else (low + 1, high)
        matching = still
    return found


def layout(
    pages: Mapping[str, list[Block]], source_of: Mapping[str, str], order: Iterable[str]
) -> Layout:
    """Find the shared prefix, suffix and partials of ``pages`` (page key → blocks)."""
    keys = [key for key in order if key in pages]
    for key in keys:
        for block in pages[key]:
            block.page = key
    cursors = {key: (0, len(pages[key])) for key in keys}
    prefix_sigs = _run(pages, cursors, from_end=False) if len(keys) > 1 else []
    suffix_sigs = _run(pages, cursors, from_end=True) if len(keys) > 1 else []
    suffix_sigs.reverse()
    taken: set[str] = set()
    groups_by_sig: dict[str, Group] = {}

    def group_for(sig: str) -> Group:
        if sig not in groups_by_sig:
            first = next(b for key in keys for b in pages[key] if b.signature == sig)
            group = Group(sig, _unique(first.name, taken), reference=first.page)
            group.instances[first.page] = first
            groups_by_sig[sig] = group
        return groups_by_sig[sig]

    prefix = [group_for(sig) for sig in prefix_sigs]
    suffix = [group_for(sig) for sig in suffix_sigs]
    # Pages consumed by the runs: record their instances and cursors. Pages that
    # diverged keep the whole sequence and are matched block by block below.
    plans: dict[str, PagePlan] = {}
    remaining: dict[str, list[Block]] = {}
    for key in keys:
        plan = PagePlan()
        sequence = pages[key]
        low, high = 0, len(sequence)
        for group in prefix:
            if low < high and sequence[low].signature == group.signature:
                group.instances[key] = sequence[low]
                low += 1
            elif low < high and _looks_like(sequence[low], group, source_of):
                plan.overrides[group.name] = sequence[low]
                low += 1
            else:
                plan.overrides[group.name] = None
        for group in reversed(suffix):
            if low < high and sequence[high - 1].signature == group.signature:
                group.instances[key] = sequence[high - 1]
                high -= 1
            elif low < high and _looks_like(sequence[high - 1], group, source_of):
                plan.overrides[group.name] = sequence[high - 1]
                high -= 1
            else:
                plan.overrides[group.name] = None
        remaining[key] = sequence[low:high]
        plans[key] = plan
    # Partials: a block left over on two or more pages.
    counts: Counter[str] = Counter()
    for key in keys:
        for sig in {block.signature for block in remaining[key]}:
            counts[sig] += 1
    partials: list[Group] = []
    for key in keys:
        for block in remaining[key]:
            if counts[block.signature] >= 2:
                group = group_for(block.signature)
                if group not in partials:
                    partials.append(group)
                group.instances[key] = block
                plans[key].content.append(group.name)
            else:
                plans[key].content.append(block)
    return Layout(prefix, suffix, partials, plans)


# the current page


@dataclass
class Variation:
    """How one element's state attributes differ across the pages of a group."""

    #: class tokens in order of first appearance → the pages that have the token.
    class_tokens: dict[str, set[str]] = field(default_factory=dict)
    #: whether any page has a class attribute at all.
    has_class: bool = False
    #: other state attributes: name → (value, pages that have it); ``None`` value = mixed.
    attributes: dict[str, tuple[str | None, set[str]]] = field(default_factory=dict)
    pages: set[str] = field(default_factory=set)

    @property
    def varies(self) -> bool:
        return any(len(pages) != len(self.pages) for pages in self.class_tokens.values()) or any(
            len(pages) != len(self.pages) for _, pages in self.attributes.values()
        )


def element_variations(group: Group, source_of: Mapping[str, str]) -> dict[int, Variation]:
    """Per element position in the group's markup, how its state attributes vary."""
    elements = {key: list(block.node.iter_elements()) for key, block in group.instances.items()}
    count = len(elements[group.reference])
    found: dict[int, Variation] = {}
    for index in range(count):
        variation = Variation(pages=set(group.instances))
        for key, nodes in elements.items():
            if index >= len(nodes):
                continue
            attrs = nodes[index].attrs(source_of[key])
            if "class" in attrs:
                variation.has_class = True
                for token in (attrs["class"] or "").split():
                    variation.class_tokens.setdefault(token, set()).add(key)
            for name in STATE_ATTRIBUTES[1:]:
                if name in attrs:
                    value = attrs[name] or ""
                    previous, pages = variation.attributes.get(name, (value, set()))
                    pages.add(key)
                    variation.attributes[name] = (
                        previous if previous == value else None,
                        pages,
                    )
        if variation.varies:
            found[index] = variation
    return found


def _wrap(patterns: list[str], text: str) -> str:
    quoted = " ".join(f'"{pattern}"' for pattern in patterns)
    return "{% ifactive " + quoted + " %}" + text + "{% endifactive %}"


def generalize_tag(
    text: str, variation: Variation, patterns: Callable[[set[str]], list[str]]
) -> tuple[str, list[str]]:
    """``text`` (a start tag) with each varying marker inside ``{% ifactive %}``.

    Returns the new tag text and the problems (a marker whose value differs
    between pages is kept as written).
    """
    problems: list[str] = []
    attrs = {attr.name: attr for attr in attributes(text)}
    everyone = variation.pages
    insertions: list[tuple[int, int, str]] = []  # (start, end, replacement)
    # class
    tokens = list(variation.class_tokens.items())
    if any(len(pages) != len(everyone) for _, pages in tokens):
        common = [token for token, pages in tokens if len(pages) == len(everyone)]
        varying = [(token, pages) for token, pages in tokens if len(pages) != len(everyone)]
        class_attr = attrs.get("class")
        handled = False
        if class_attr is not None and class_attr.value_start is not None and not common:
            # The reference's class attribute holds markers only: on the pages without
            # them the attribute is absent, so the whole attribute comes and goes.
            start = class_attr.name_start
            while start > 0 and text[start - 1].isspace():
                start -= 1
            end = (class_attr.value_end or 0) + (1 if class_attr.quote else 0)
            marker_sets: dict[frozenset[str], list[str]] = {}
            for token, pages in varying:
                marker_sets.setdefault(frozenset(pages), []).append(token)
            groups = list(marker_sets)
            if all(not (a & b) for i, a in enumerate(groups) for b in groups[i + 1 :]):
                quote = class_attr.quote or '"'
                added = "".join(
                    _wrap(patterns(set(pages)), f" class={quote}{' '.join(names)}{quote}")
                    for pages, names in marker_sets.items()
                )
                insertions.append((start, end, added))
                handled = True
        if handled:
            pass
        elif class_attr is not None and class_attr.value_start is not None:
            ordered = class_attr.value.split() if class_attr.value else []
            ordered += [token for token, _ in varying if token not in ordered]
            pieces: list[str] = []
            absorbed = False  # the previous marker took the space that separates the tokens
            for position, token in enumerate(ordered):
                pages = dict(tokens).get(token, everyone)
                following = ordered[position + 1] if position + 1 < len(ordered) else None
                if token in common:
                    pieces.append(("" if position == 0 or absorbed else " ") + token)
                    absorbed = False
                elif position == 0 and following in common:
                    pieces.append(_wrap(patterns(pages), token + " "))
                    absorbed = True
                else:
                    pieces.append(_wrap(patterns(pages), ("" if position == 0 else " ") + token))
                    absorbed = False
            insertions.append((class_attr.value_start, class_attr.value_end or 0, "".join(pieces)))
        else:
            by_pages: dict[frozenset[str], list[str]] = {}
            for token, pages in varying:
                by_pages.setdefault(frozenset(pages), []).append(token)
            sets = list(by_pages)
            disjoint = all(not (a & b) for i, a in enumerate(sets) for b in sets[i + 1 :])
            end = _insert_point(text)
            if disjoint and not common:
                added = "".join(
                    _wrap(patterns(set(pages)), f' class="{" ".join(names)}"')
                    for pages, names in by_pages.items()
                )
            else:
                inner = " ".join(common)
                for token, pages in varying:
                    inner += _wrap(patterns(pages), (" " if inner else "") + token)
                added = f' class="{inner}"'
            insertions.append((end, end, added))
    # other state attributes
    for name, (value, pages) in variation.attributes.items():
        if len(pages) == len(everyone):
            continue
        attr = attrs.get(name)
        if value is None:
            problems.append(
                f"{name} differs between pages in a way that is not present or absent, so the "
                "first page's value was kept"
            )
            continue
        rendered = f' {name}="{value}"' if value else f" {name}"
        if attr is not None:
            start = attr.name_start
            while start > 0 and text[start - 1].isspace():
                start -= 1
            end = (
                attr.value_end + 1
                if attr.value_end is not None and attr.quote
                else (attr.value_end if attr.value_end is not None else attr.name_end)
            )
            insertions.append((start, end, _wrap(patterns(pages), text[start:end])))
        else:
            point = _insert_point(text)
            insertions.append((point, point, _wrap(patterns(pages), rendered)))
    out = text
    for start, end, replacement in sorted(insertions, reverse=True):
        out = out[:start] + replacement + out[end:]
    return out, problems


def _insert_point(text: str) -> int:
    point = len(text) - (2 if text.endswith("/>") else 1)
    while point > 0 and text[point - 1].isspace():
        point -= 1
    return point


# records and versions


def section_record(block: Block, source: str) -> dict[str, Any]:
    """What ``.karni/design.json`` keeps about one block of a page."""
    node = block.node
    heading = next(
        (n.plain_text(source) for n in node.iter_elements() if re.match(r"h[1-6]$", n.tag)), ""
    )
    return {
        "name": block.name,
        "tag": node.tag,
        "id": node.attr(source, "id") or "",
        "classes": node.classes(source),
        "heading": heading,
        "hash": _digest(collapse(node.text(source))),
    }


def site_name(titles: Iterable[str]) -> str:
    """The site's name from its page titles: the part most titles share around a separator.

    ``"About — Studio"``, ``"Contact — Studio"`` and ``"Studio — Home"`` give
    ``"Studio"``. Without a shared part, the first title.
    """
    cleaned = [collapse(title) for title in titles if collapse(title)]
    if not cleaned:
        return ""
    best, best_count = "", 0
    for separator in _SEPARATORS:
        counts: Counter[str] = Counter()
        for title in cleaned:
            if separator not in title:
                continue
            head = title.partition(separator)[0].strip()
            tail = title.rpartition(separator)[2].strip()
            for segment in {head, tail}:
                if segment:
                    counts[segment] += 1
        if counts:
            segment, count = counts.most_common(1)[0]
            if count > best_count:
                best, best_count = segment, count
    if best_count >= max(2, math.ceil(len(cleaned) / 2)):
        return best
    return cleaned[0]


def _by_name(items: Iterable[Mapping[str, Any]], key: str = "name") -> dict[str, Mapping[str, Any]]:
    return {str(item[key]): item for item in items}


def diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """What changed between two design records, one line per change."""
    lines: list[str] = []
    old_pages = _by_name(old.get("pages", []), "source")
    new_pages = _by_name(new.get("pages", []), "source")
    for source in sorted(set(new_pages) - set(old_pages)):
        lines.append(f"page {source}: added ({new_pages[source].get('route', '')})")
    for source in sorted(set(old_pages) - set(new_pages)):
        lines.append(f"page {source}: removed from the design")
    for source in sorted(set(old_pages) & set(new_pages)):
        before, after = old_pages[source], new_pages[source]
        if before.get("title") != after.get("title"):
            lines.append(f"page {source}: title changed to {after.get('title')!r}")
        if before.get("description") != after.get("description"):
            lines.append(f"page {source}: description changed")
        if before.get("head_hash") != after.get("head_hash"):
            lines.append(f"page {source}: its own <head> elements changed")
        old_sections = _by_name(before.get("sections", []))
        new_sections = _by_name(after.get("sections", []))
        for name in sorted(set(new_sections) - set(old_sections)):
            lines.append(f"page {source}: section {name!r} added")
        for name in sorted(set(old_sections) - set(new_sections)):
            lines.append(f"page {source}: section {name!r} removed")
        for name in [n for n in new_sections if n in old_sections]:
            if old_sections[name].get("hash") != new_sections[name].get("hash"):
                lines.append(f"page {source}: section {name!r} changed")
    for kind in ("shared", "partials"):
        old_items = _by_name(old.get(kind, []))
        new_items = _by_name(new.get(kind, []))
        for name in sorted(set(new_items) - set(old_items)):
            lines.append(f"{kind.removesuffix('s')} {name!r}: added")
        for name in sorted(set(old_items) - set(new_items)):
            lines.append(f"{kind.removesuffix('s')} {name!r}: removed")
        for name in sorted(set(old_items) & set(new_items)):
            if old_items[name].get("hash") != new_items[name].get("hash"):
                lines.append(f"{kind.removesuffix('s')} {name!r}: changed")
    old_assets = old.get("assets", {}).get("files", {})
    new_assets = new.get("assets", {}).get("files", {})
    for path in sorted(set(new_assets) - set(old_assets)):
        lines.append(f"asset {path}: added")
    for path in sorted(set(old_assets) - set(new_assets)):
        lines.append(f"asset {path}: removed from the design")
    for path in sorted(set(old_assets) & set(new_assets)):
        if old_assets[path].get("sha256") != new_assets[path].get("sha256"):
            lines.append(f"asset {path}: changed")
    old_redirects = {r["source"]: r for r in old.get("redirects", [])}
    new_redirects = {r["source"]: r for r in new.get("redirects", [])}
    for source in sorted(set(new_redirects) - set(old_redirects)):
        lines.append(f"redirect {source}: added")
    for source in sorted(set(old_redirects) - set(new_redirects)):
        lines.append(f"redirect {source}: removed from the design")
    for source in sorted(set(old_redirects) & set(new_redirects)):
        if old_redirects[source].get("to") != new_redirects[source].get("to"):
            lines.append(f"redirect {source}: now goes to {new_redirects[source].get('to')}")
    return lines
