"""Sources into models: the step-by-step work behind :func:`karni_cli.design.analyze.analyze`.

The builder clusters the sources that hold the same items into models, keeps
lists of one or two values as page copy, folds a list's twin (a slider's
captions) into it, turns nested lists into child models or JSON fields,
finds the relations and the decisions, keys every row, and writes the
selectors the content map reads.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any, Final

from karni_cli.design.parse import Node
from karni_cli.design.proposal import (
    _NUMBERED,
    _RESERVED,
    Binding,
    Decision,
    Field,
    HighlightAdvice,
    Model,
    Namer,
    PageCopy,
    Rule,
    _decorations,
    _derived,
    _numbered,
    _position_like,
    _step_classes,
    _str_size,
    infer_type,
)
from karni_cli.design.rewrite import Mapped
from karni_cli.design.scan import SKIP, Scan, Slot, scan, step_of
from karni_cli.design.select import Target, write_selector
from karni_cli.design.sources import (
    Entity,
    Entry,
    Identity,
    Page,
    SlotKey,
    Source,
    _all_collections,
    _constant,
    _identity,
    _jaccard,
    _norm,
    _resolve,
    _Sources,
    _title_key,
    _tokens_of,
    _Union,
    attr_key,
    identity_tokens,
    link_key,
    page_slug,
    same_items,
)
from karni_cli.design.values import (
    HIGHLIGHT_MARKER,
    decimal_mark,
    is_utility_class,
    page_language,
    pascal,
    singular,
    slugify,
    snake,
    words,
)

#: The reason a row of figures stays in its template.
FIGURES: Final = "figures (a number and a short label per item) on this page"
#: A figure as a design writes it: ``25``, ``4,000``, ``4.9``, ``98%``, ``10k+``, ``24/7``, ``$2M``.
_FIGURE: Final = re.compile(r"\d")
_FIGURE_REST: Final = re.compile(r"[\d\s.,'’/%+×*★$€£¥₹:-]")
#: Elements that make a part of a page on their own.
_SECTIONS: Final = frozenset({"section", "article", "aside", "header", "footer", "main", "nav"})


def _is_figure(text: str) -> bool:
    """A number written for show, with at most a short unit (``k``, ``M``, ``yrs``)."""
    value = text.strip()
    if not value or len(value) > 12 or not _FIGURE.search(value):
        return False
    return len(_FIGURE_REST.sub("", value)) <= 3


def _figures(source: Source) -> bool:
    """A short run of figures: each item one number and one or two short labels, nothing else.

    A row of statistics (``25`` *years in town*, ``4,000`` *customers*) is
    page copy: its numbers are the page's own words, not rows a client adds
    to. A list with pictures, links, nested lists or longer texts is not.
    """
    if not 2 <= len(source.entries) <= 8:
        return False
    for entry in source.entries:
        if entry.collections:
            return False
        texts = [slot.value for slot in entry.slots if slot.kind == "text"]
        if any(slot.kind not in ("text", "id", "data", "flag") for slot in entry.slots):
            return False
        numbers = [text for text in texts if _is_figure(text)]
        labels = [text for text in texts if not _is_figure(text)]
        if len(numbers) != 1 or not 1 <= len(labels) <= 2:
            return False
        if any(len(label.split()) > 8 for label in labels):
            return False
    return True


def _section(node: Node | None) -> Node | None:
    """The nearest section-like element holding ``node`` (itself included)."""
    current = node
    while current is not None and current.kind == "element":
        if current.tag in _SECTIONS:
            return current
        current = current.parent
    return None


def _strong(sources: Sequence[Source]) -> bool:
    """Content worth a model: a picture that changes, or three or more values that do."""
    varying: set[tuple[str, str]] = set()
    for source in sources:
        for key in source.slot_keys():
            path, kind, _ = key
            if kind in ("id", "alt"):
                continue
            values = {s.value for s in source.values(key) if s is not None}
            if len(values) > 1 or (len(source.entries) == 1 and values):
                if kind == "image":
                    return True
                varying.add((path[-1] if path else "", kind))
        if any(c for e in source.entries for c in e.collections):
            varying.add(("", "collection"))
    return len(varying) >= 3


class _Builder:
    def __init__(
        self,
        pages: list[Page],
        sources: list[Source],
        mapped: Mapped,
        namer: Namer,
        app: str,
        configured: str | None = None,
    ) -> None:
        #: The highlight markup KARNI_SITE_HIGHLIGHT already holds (``span.accent``), when
        #: ``karni import design --editable`` recorded one.
        self.configured = configured
        self.highlight: HighlightAdvice | None = None
        self.pages = pages
        self.sources = sources
        self.mapped = mapped
        self.namer = namer
        self.app = app
        self.models: list[Model] = []
        self.model_of: dict[int, Model] = {}
        self.identity: dict[int, Identity] = {}
        self.decisions: list[Decision] = []
        self.page_copy: list[PageCopy] = []
        self.notes: list[str] = []
        self.links: list[tuple[Model, Source, SlotKey]] = []
        self.token_slots: list[tuple[Model, Source, SlotKey]] = []
        self.index: dict[str, tuple[Model, Entity] | None] = {}
        self.rows_from: dict[
            int, Field
        ] = {}  # id(nested source) → the foreign key its nesting sets
        self.reference: set[int] = set()  # sources that show rows other sources create
        self.places: dict[tuple[int, SlotKey], str] = {}
        #: id(lone source) → the list whose items it looks like.
        self.lone: dict[int, Source] = {}
        self.later: list[tuple[Model, Field, Source]] = []  # detail lists, decided once all exist
        #: The decimal mark the design's pages write (their ``<html lang>``), ``None`` unknown.
        languages = Counter(page_language(page.doc, page.text) for page in pages)
        languages.pop("", None)
        self.decimal = decimal_mark(languages.most_common(1)[0][0]) if languages else None

    # clusters

    def run(self) -> None:
        for source in self.sources:
            identity_tokens(source, self.mapped)
            self.identity[id(source)] = _identity(source, self.mapped)
        live = [s for s in self.sources if not _constant(s)]
        union = _Union(len(live))
        for i, first in enumerate(live):
            for j in range(i + 1, len(live)):
                if same_items(first, live[j]):
                    union.join(i, j)
        clusters: dict[int, list[Source]] = {}
        for i, source in enumerate(live):
            clusters.setdefault(union.find(i), []).append(source)
        multi = [c for c in clusters.values() if len(c) > 1 or c[0].kind == "detail"]
        single = [c[0] for c in clusters.values() if len(c) == 1 and c[0].kind != "detail"]
        for cluster in multi:
            self.items_model(cluster)
        page_level = [s for s in single if s.parent is None or s.parent.kind == "detail"]
        inner = [s for s in single if s.parent is not None and s.parent.kind != "detail"]
        for group in self.groups(page_level):
            self.group(group)
        self.zip()
        self.name_models()
        for source in sorted(inner, key=lambda s: len(s.ancestors())):
            self.inner(source)
        self.loners()
        self.build_index()
        for model in list(self.models):
            self.fields_of(model)
        self.relations()
        self.keys()
        self.bind()
        self.types()
        self.highlights()
        self.decide()
        self.order()

    def add_model(self, model: Model) -> Model:
        model.listing = model.listing or self._listing(model)
        if model.name:
            model.name = self._model_name(model.name)
        self.models.append(model)
        for source in model.sources:
            self.model_of[id(source)] = model
        return model

    def _model_name(self, name: str) -> str:
        taken = {m.name for m in self.models}
        candidate, counter = name, 2
        while candidate in taken:
            candidate = f"{name}{counter}"
            counter += 1
        return candidate

    def _name_child(self, model: Model) -> None:
        assert model.parent is not None
        model.name = self._model_name(pascal(f"{model.parent.name} {model.noun}"))
        model.accessor = model.name.lower() + "_set"

    def name_models(self) -> None:
        """Name the models: from their own markup first, then after the model they sit in."""
        waiting: list[Model] = []
        for model in self.models:
            if model.name or model.kind == "child":
                continue
            name = self.namer.model_name(model)
            if name == "Item":
                waiting.append(model)
            else:
                model.name = self._model_name(name)
        for model in waiting:
            listing = model.listing
            parent = self.model_of.get(id(listing.parent)) if listing and listing.parent else None
            if parent is not None and parent.name:
                model.name = self._model_name(f"{parent.name}Item")
            else:
                model.name = self._model_name("Item")
        for model in self.models:
            if model.kind == "child" and not model.name:
                self._name_child(model)

    def _listing(self, model: Model) -> Source | None:
        ranked = sorted(
            (s for s in model.sources if s.kind != "detail"),
            key=lambda s: (
                -len({id(e.entity) for e in s.entries}),
                s.kind != "list",
                s.page.name == "home",
                s.id,
            ),
        )
        if ranked:
            return ranked[0]
        return next((s for s in model.sources if s.kind == "detail"), None)

    def items_model(self, cluster: list[Source]) -> Model:
        model = Model("", "items", list(cluster))
        model.family = next((s.family for s in cluster if s.family is not None), None)
        order = sorted(
            cluster, key=lambda s: (s.kind != "detail", s.kind == "nested", -len(s.entries), s.id)
        )
        index: dict[str, Entity] = {}
        for source in order:
            for entry in source.entries:
                found = {id(index[t]): index[t] for t in entry.tokens if t in index}
                entity = next(iter(found.values())) if len(found) == 1 else None
                if entity is None:
                    entity = Entity()
                    model.entities.append(entity)
                entity.entries.append(entry)
                entity.tokens |= entry.tokens
                entry.entity = entity
                for token in entry.tokens:
                    index.setdefault(token, entity)
        return self.add_model(model)

    # page-level lists that hold their own items

    def groups(self, sources: list[Source]) -> list[list[Source]]:
        groups: list[tuple[str, set[Any], list[Source]]] = []
        for source in sources:
            shape = source.shape()
            for step, known, members in groups:
                if step == source.step and _jaccard(shape, known) >= 0.6:
                    members.append(source)
                    known |= shape
                    break
            else:
                groups.append((source.step, set(shape), [source]))
        return [members for _, _, members in groups]

    def group(self, group: list[Source]) -> None:
        fixed = [s for s in group if s.parent is None]
        detail = []
        for source in group:
            if source.parent is None:
                continue
            covered = {e.page.path for e in source.entries}
            if len(covered) * 2 < len(source.parent.entries):
                family = self.model_of.get(id(source.parent))
                if family is not None:
                    family.notes.append(
                        f"the list {source.step} in section {source.block!r} is only on "
                        f"{', '.join(sorted(covered))}: kept in that page's template (or an "
                        "editable block), not a field."
                    )
                continue
            detail.append(source)
        if not fixed and not detail:
            return
        if fixed and not detail and all(_figures(source) for source in fixed):
            for source in fixed:
                self.page_copy.append(
                    PageCopy(source.page.path, source.step, len(source.entries), FIGURES, source)
                )
            return
        strong = _strong(group)
        if not strong:
            for source in fixed:
                self.page_copy.append(
                    PageCopy(
                        source.page.path,
                        source.step,
                        len(source.entries),
                        "one or two short values per item on this page",
                        source,
                    )
                )
            for source in detail:
                self.json_field(source)
            return
        families = {id(s.parent): s.parent for s in detail if s.parent is not None}
        if detail and not fixed and len(families) == 1:
            for source in detail:
                self.child_model(source)
            return
        if not detail and len({s.page.path for s in fixed}) == 1:
            model = Model("", "items", list(fixed))
            for source in fixed:
                for entry in source.entries:
                    entity = Entity([entry], set(entry.tokens))
                    entry.entity = entity
                    model.entities.append(entity)
            model.by_position = True
            self.add_model(model)
            return
        model = Model("", "pages", list(group))
        for source in group:
            for entry in source.entries:
                entity = Entity([entry])
                entry.entity = entity
                model.entities.append(entity)
        model.by_position = True
        self.add_model(model)

    def zip(self) -> None:
        """A list next to another with as many items, in the same part of a page, holds the
        same rows.

        A slider's pictures and its captions are often two lists. They are read
        as one: the captions' fields join the pictures' model, item by item. Two
        lists in sections of their own are two things (a slider and a row of
        figures below it), and a row of figures is never a model's other half.
        """
        copies = {(c.where, c.step): c for c in self.page_copy}
        for model in list(self.models):
            if model.kind not in ("items", "pages") or not model.by_position:
                continue
            for source in list(model.sources):
                if source.parent is not None:
                    continue
                for other in self.sources:
                    if (
                        other is source
                        or other.parent is not None
                        or other.page is not source.page
                        or other.block != source.block
                        or len(other.entries) != len(source.entries)
                        or other in model.zipped
                    ):
                        continue
                    owner = self.model_of.get(id(other))
                    copy = copies.get((other.page.path, other.step))
                    if owner is not None and (owner is model or len(owner.sources) > 1):
                        continue
                    if owner is None and copy is None:
                        continue
                    if copy is not None and copy.reason == FIGURES:
                        continue
                    if _section(source.container) is not _section(other.container):
                        continue
                    if owner is not None:
                        self.models.remove(owner)
                    if copy is not None and copy in self.page_copy:
                        self.page_copy.remove(copy)
                    for mine, theirs in zip(source.entries, other.entries, strict=True):
                        theirs.entity = mine.entity
                        if mine.entity is not None:
                            mine.entity.entries.append(theirs)
                    model.sources.append(other)
                    model.zipped.append(other)
                    self.model_of[id(other)] = model
                    model.notes.append(
                        f"{other.step} on {other.page.path} has as many items as {source.step} "
                        "in the same block: read as the same rows, item by item. Check it."
                    )

    def inner(self, source: Source) -> None:
        parent = self.model_of.get(id(source.parent)) if source.parent else None
        if parent is None or parent.kind == "child":
            return
        if _strong([source]):
            self.child_model(source)
        else:
            self.json_field(source)

    def child_model(self, source: Source) -> None:
        parent_source = source.parent
        parent = self.model_of.get(id(parent_source)) if parent_source else None
        if parent is None:
            return
        tag = source.step.split(".", 1)[0]
        noun = "image" if tag in ("img", "figure", "picture") else ""
        if not noun:
            noun = (
                singular(words(self.namer.list_name(source))[-1])
                if self.namer.list_name(source)
                else "item"
            )
        existing = next(
            (m for m in self.models if m.kind == "child" and m.parent is parent and m.noun == noun),
            None,
        )
        model = existing or Model("", "child", parent=parent, noun=noun)
        if existing is None:
            self.add_model(model)
            if parent.name:
                self._name_child(model)
        model.sources.append(source)
        self.model_of[id(source)] = model
        for entry in source.entries:
            entity = Entity([entry])
            entry.entity = entity
            model.entities.append(entity)

    def loners(self) -> None:
        """One element styled like a list's items (a founder's card above the team's) is a
        candidate row: proposed, with a flag named after its class, as a decision."""
        for model in list(self.models):
            if model.kind != "items":
                continue
            for source in list(model.sources):
                if source.kind != "list" or len(source.entries) < 2 or source.parent is not None:
                    continue
                found = self._loner(source)
                if found is None:
                    continue
                node, scanned = found
                page = source.page
                loner = Source(
                    len(self.sources),
                    "list",
                    [page],
                    (),
                    step_of(node, page.text),
                    None,
                    container=node.parent,
                )
                entry = Entry(loner, page, node, scanned.slots, 1, None, scanned.collections)
                loner.entries.append(entry)
                loner.title_key = _title_key(loner)
                identity_tokens(loner, self.mapped)
                self.identity[id(loner)] = _identity(loner, self.mapped)
                self.sources.append(loner)
                entity = Entity([entry], set(entry.tokens))
                entry.entity = entity
                model.entities.append(entity)
                model.sources.append(loner)
                self.model_of[id(loner)] = model
                self.lone[id(loner)] = source
                # A list inside the card is the card's now, not page copy.
                self.page_copy = [
                    c
                    for c in self.page_copy
                    if c.source is None
                    or c.source.container is None
                    or not (c.source.container is node or _within(c.source.container, node))
                ]
                holder = _Sources()
                holder.nested(loner)
                for nested in holder.all:
                    nested.id = len(self.sources)
                    nested.title_key = _title_key(nested)
                    identity_tokens(nested, self.mapped)
                    self.identity[id(nested)] = _identity(nested, self.mapped)
                    self.sources.append(nested)
                    if nested.parent is loner:
                        self.inner(nested)

    def _loner(self, source: Source) -> tuple[Node, Scan] | None:
        page = source.page
        text = page.text
        counts: Counter[tuple[str, str, str]] = Counter()
        for entry in source.entries:
            counts.update({_shape_key(slot.key) for slot in entry.slots})
        item_shape = {k for k, n in counts.items() if n * 2 >= len(source.entries)}
        classed = {k for k in item_shape if "." in k[2] and not k[2].startswith("h")}
        if not classed or source.container is None:
            return None
        inside: set[int] = set()
        for collection in _all_collections(page.found.collections):
            for item in collection.items:
                inside |= {id(n) for n in item.node.iter_elements()}
        around: set[int] = set()
        current: Node | None = source.container
        while current is not None:
            around.add(id(current))
            current = current.parent
        candidates: list[tuple[Node, Scan]] = []
        for _, block in page.blocks:
            for node in block.iter_elements():
                if id(node) in inside or id(node) in around or node.tag in SKIP:
                    continue
                scanned = scan(node, text)
                shape = {_shape_key(slot.key) for slot in scanned.slots}
                if not classed & shape:
                    continue
                if len(item_shape & shape) < 0.75 * len(item_shape):
                    continue
                candidates.append((node, scanned))
        if not candidates:
            return None
        # The element that holds most of what any item has (a photo some items lack too),
        # then the deepest such element.
        union = set(counts)

        def cover(found: Scan) -> int:
            return len(union & {_shape_key(slot.key) for slot in found.slots})

        best = max(cover(scanned) for _, scanned in candidates)
        top = [(n, sc) for n, sc in candidates if cover(sc) == best]
        deepest = [
            (node, scanned)
            for node, scanned in top
            if not any(other is not node and _within(other, node) for other, _ in top)
        ]
        return deepest[0] if len(deepest) == 1 else None

    def json_field(self, source: Source) -> None:
        parent_source = source.parent
        parent = self.model_of.get(id(parent_source)) if parent_source else None
        if parent is None:
            return
        wanted = self.namer.list_name(source)
        f = next(
            (
                g
                for g in parent.fields
                if g.kind == "json"
                and g.name == wanted
                and not any(r.source is parent_source for r in g.rules)
            ),
            None,
        )
        if f is None:
            f = Field(self._unique(parent, wanted), "json", kind="json", slot_kind="list")
            parent.fields.append(f)
        assert parent_source is not None
        f.rules.append(Rule(parent_source, None, "", {"_list": source}))  # placed in bind()
        seen = set(f.values)
        for entry in source.entries:
            parent_entity = entry.parent.entity if entry.parent is not None else None
            if parent_entity is not None and id(parent_entity) not in seen:
                f.values.setdefault(id(parent_entity), []).append(
                    ", ".join(s.value for s in entry.slots if s.kind == "text")
                )
        self.model_of.setdefault(id(source), parent)

    # fields

    def build_index(self) -> None:
        for model in self.models:
            if model.kind != "items":
                continue
            for entity in model.entities:
                for token in entity.tokens:
                    if token in self.index and self.index[token] != (model, entity):
                        self.index[token] = None
                    else:
                        self.index[token] = (model, entity)

    def _unique(self, model: Model, name: str, context: str = "") -> str:
        taken = {f.name for f in model.fields}
        if name not in taken and name not in _RESERVED and name != "position":
            return name
        if context:
            candidate = f"{snake(context)}_{name}"
            if candidate not in taken and candidate not in _RESERVED:
                return candidate
        counter = 2
        while f"{name}_{counter}" in taken:
            counter += 1
        return f"{name}_{counter}"

    def _title(self, entity: Entity | None) -> str:
        if entity is None:
            return ""
        for entry in entity.entries:
            key = entry.source.title_key
            slot = entry.value(key) if key else None
            if slot is not None and slot.value:
                return slot.value
        return ""

    def _context(self, source: Source) -> str:
        found = self.namer.class_words(source.step.split(".")[1:])
        if not found and source.container is not None and source.kind != "detail":
            found = self.namer.class_words(source.container.classes(source.page.text))
        if not found and source.kind == "nested" and source.path:
            found = (
                words(source.path[0])[:2]
                if source.parent and source.parent.kind == "detail"
                else []
            )
        if found:
            return "_".join(found)
        return snake(source.page.name)

    def fields_of(self, model: Model) -> None:
        by_key = model.kind == "pages" or (model.by_position and len(model.sources) > 1)
        keyed: dict[SlotKey, Field] = {}
        order = sorted(
            model.sources,
            key=lambda s: (s.kind != "detail", s is not model.listing, s.kind == "nested", s.id),
        )
        for source in order:
            if self.model_of.get(id(source)) is not model:
                continue
            partner = self.lone.get(id(source))
            if partner is not None:
                self.consider_lone(model, source, partner)
                continue
            for key in source.slot_keys():
                self.consider(model, source, key, keyed if by_key else None)
        if model.kind == "items":
            self._choose_title(model)

    def consider_lone(self, model: Model, source: Source, partner: Source) -> None:
        """A lone item's values go to the fields its look-alike list's items fill."""
        like: dict[tuple[str, str, str], Field] = {}
        for f in model.fields:
            for rule in f.rules:
                if rule.source is partner and rule.key is not None:
                    like.setdefault(_shape_key(rule.key), f)
        keyed: dict[SlotKey, Field] = {}
        for key in source.slot_keys():
            match = like.get(_shape_key(key))
            if match is not None:
                keyed[key] = match
        for key in source.slot_keys():
            self.consider(model, source, key, keyed)
        node = source.entries[0].node
        words_ = self.namer.class_words(node.classes(source.page.text))
        name = self._unique(model, snake(" ".join(words_)) if words_ else "featured")
        flag = Field(name, "bool", kind="bool", slot_kind="bool")
        flag.rules.append(Rule(source, None, ":scope", {"present": True}))
        if source.entries[0].entity is not None:
            flag.values[id(source.entries[0].entity)] = True
        model.fields.append(flag)

    def _choose_title(self, model: Model) -> None:
        """The field that names the rows: the one most sources name their items by."""
        candidates = [
            f
            for f in model.fields
            if f.kind == "value"
            and f.slot_kind in ("text", "data")
            and f.title_votes > 0
            and f.values
            and all(
                isinstance(v, str) and "\n" not in v and len(v) <= 120 for v in f.values.values()
            )
            and len(set(f.values.values())) == len(f.values)
        ]
        if not candidates:
            return

        def score(f: Field) -> tuple[int, int, int, int]:
            detail = any(r.source.kind == "detail" for r in f.rules)
            listing = any(r.source is model.listing for r in f.rules)
            return (int(detail), len({id(r.source) for r in f.rules}), len(f.values), int(listing))

        best = max(candidates, key=score)
        best.kind = "title"
        if best.name != "title":
            holder = model.field_named("title")
            if holder is not None:
                holder.name = self._unique(model, "heading")
            best.name = "title"

    def consider(
        self, model: Model, source: Source, key: SlotKey, keyed: dict[SlotKey, Field] | None
    ) -> None:
        """Make one slot of one source a field of ``model``, merge it, or leave it out."""
        path, kind, _ = key
        entries = [e for e in source.entries if e.entity is not None]
        present = [(e, s) for e in entries if (s := e.value(key)) is not None]
        if not present or kind == "id":
            return
        identity = self.identity.get(id(source), Identity())
        if key == identity.attr:
            return
        detail = source.kind == "detail"
        if detail and len(present) * 2 < len(entries):
            self._page_specific(model, path, present)
            return
        if kind == "link":
            pointed = [self._points_at(e, s) for e, s in present]
            if all(p == "self" for p in pointed):
                return
            if any(isinstance(p, tuple) for p in pointed):
                self.links.append((model, source, key))
                return
        if kind == "data":
            values = [s.value for _, s in present]
            tokens = all(
                re.fullmatch(r"[a-z0-9][a-z0-9_-]*( [a-z0-9][a-z0-9_-]*)*", v.strip())
                for v in values
            )
            if tokens and len(set(values)) > 1 and not _position_like(values):
                self.token_slots.append((model, source, key))
                return
        if kind == "image":
            present = [(e, self._asset(e, s)) for e, s in present]
        if kind == "text" and all(
            s.node.tag == "time" and s.node.attr(e.page.text, "datetime") for e, s in present
        ):
            return  # the datetime attribute is the value, the text its formatting
        if kind == "text" and self._around_link(source, key, present):
            return
        options: dict[str, Any] = {}
        texts = {id(e): s.value for e, s in present}
        if kind == "text":
            texts, dropped = _decorations(present)
            if dropped:
                options["drop"] = dropped
        values = [texts[id(e)] if kind != "pairs" else repr(s.pairs) for e, s in present]
        if len(set(values)) == 1 and (
            len(entries) >= 2 and (len(present) == len(entries) or detail)
        ):
            return
        is_title = key == source.title_key
        if (
            not is_title
            and kind in ("text", "alt", "data")
            and _derived([(texts[id(e)], self._title(e.entity)) for e, _ in present])
        ):
            return
        if kind == "text" and len(present) == len(entries):
            if _position_like(values):
                model.by_position = True
                return
            if _numbered(values):
                model.by_position = True
                options["pattern"] = _NUMBERED.pattern
                texts = {k: _NUMBERED.match(v).group(2) for k, v in texts.items()}  # type: ignore[union-attr]
                values = list(texts.values())
        boolean = (
            kind == "text"
            and not detail
            and not is_title
            and len(present) < len(entries)
            and len(set(values)) == 1
        )
        by_entity: dict[int, Any] = {}
        for entry, slot in present:
            assert entry.entity is not None
            if kind == "pairs":
                by_entity[id(entry.entity)] = [list(pair) for pair in slot.pairs]
            elif boolean:
                by_entity[id(entry.entity)] = True
            else:
                by_entity[id(entry.entity)] = texts[id(entry)]
        target: Field | None = None
        if keyed is not None and key in keyed:
            target = keyed[key]
        if target is None and kind == "alt":
            target = self._alt_of(model, source, path)
        if target is None and not boolean:
            target = self._same_values(model, kind, by_entity)
        if target is None:
            image = ""
            if kind == "alt":
                image_field = next(
                    (
                        f
                        for f in model.fields
                        if f.slot_kind == "image"
                        and any(
                            r.source is source and r.key == (path, "image", "src") for r in f.rules
                        )
                    ),
                    None,
                )
                image = image_field.name if image_field else ""
            name = self.namer.field_name(source, key, title=False, image=image)
            if boolean and 0 < len(words(values[0])) <= 3:
                name = snake(values[0])
            name = self._unique(model, name, self._context(source))
            target = Field(
                name, kind="bool" if boolean else "value", slot_kind="bool" if boolean else kind
            )
            model.fields.append(target)
        if keyed is not None:
            keyed[key] = target
        if boolean:
            options = {"present": True}
        target.rules.append(Rule(source, key, "", options))
        for entity_id, value in by_entity.items():
            target.values.setdefault(entity_id, value)
        if is_title:
            target.title_votes += 1
        for _, slot in present:
            for spec in slot.highlight:
                if (
                    spec not in target.highlight
                    and spec not in options.get("drop", [])
                    and kind == "text"
                    and target.kind in ("value", "title")
                ):
                    target.highlight.append(spec)

    def _page_specific(
        self, model: Model, path: tuple[str, ...], present: list[tuple[Entry, Slot]]
    ) -> None:
        pages = sorted({e.page.path for e, _ in present})
        block = path[0] if path else ""
        note = (
            f"some values of section {block!r} are only on {', '.join(pages)}: kept in that "
            "page's template (or an editable block), not fields."
        )
        if note not in model.notes:
            model.notes.append(note)

    def _alt_of(self, model: Model, source: Source, path: tuple[str, ...]) -> Field | None:
        """The alt field of the image field this source's image at ``path`` merged into."""
        image = next(
            (
                f
                for f in model.fields
                if f.slot_kind == "image"
                and any(r.source is source and r.key == (path, "image", "src") for r in f.rules)
            ),
            None,
        )
        if image is None:
            return None
        companions = {(id(r.source), r.key[0]) for r in image.rules if r.key is not None}
        for f in model.fields:
            if f.slot_kind == "alt" and any(
                r.key is not None and (id(r.source), r.key[0]) in companions for r in f.rules
            ):
                return f
        return None

    def _asset(self, entry: Entry, slot: Slot) -> Slot:
        """The image's path in the design (``../img/a.jpg`` and ``img/a.jpg`` are one file)."""
        ref = _resolve(self.mapped, slot.value, entry.page)
        if ref.kind in ("asset", "missing") and ref.path:
            return Slot(slot.path, slot.kind, slot.attr, slot.node, ref.path, slot.highlight)
        return slot

    def _around_link(self, source: Source, key: SlotKey, present: list[tuple[Entry, Slot]]) -> bool:
        """The text of a line whose link names another model's row: ``Taught by <a>Mia</a>``."""
        path = key[0]
        link_keys = [
            k
            for k in source.slot_keys()
            if k[1] == "link" and k[0][: len(path)] == path and len(k[0]) > len(path)
        ]
        if not link_keys:
            return False
        pairs: list[tuple[str, str]] = []
        for entry, slot in present:
            title = ""
            for link in link_keys:
                linked = entry.value(link)
                if linked is None:
                    continue
                found = self._points_at(entry, linked)
                if isinstance(found, tuple):
                    title = self._title(found[1])
                    break
            if not title:
                return False
            pairs.append((slot.value, title))
        return _derived(pairs)

    def _same_values(self, model: Model, kind: str, by_entity: dict[int, Any]) -> Field | None:
        family = "image" if kind == "image" else ("pairs" if kind == "pairs" else "text")
        for f in model.fields:
            if f.kind not in ("value", "title"):
                continue
            own = (
                "image"
                if f.slot_kind == "image"
                else ("pairs" if f.slot_kind == "pairs" else "text")
            )
            if own != family:
                continue
            overlap = [e for e in by_entity if e in f.values]
            if not overlap:
                continue
            if all(_norm(str(by_entity[e])) == _norm(str(f.values[e])) for e in overlap):
                return f
        return None

    def _points_at(self, entry: Entry, slot: Slot) -> str | tuple[Model, Entity] | None:
        ref = _resolve(self.mapped, slot.value, entry.page)
        tokens = _tokens_of(ref)
        if entry.entity is not None and tokens & entry.entity.tokens:
            return "self"
        for token in tokens:
            found = self.index.get(token)
            if found is not None:
                return found
        return None

    # relations

    def relations(self) -> None:
        for model in list(self.models):
            if model.kind != "items":
                continue
            for source in model.sources:
                if source.kind != "nested" or source.parent is None:
                    continue
                parent = self.model_of.get(id(source.parent))
                if parent is None or parent.kind == "child":
                    continue
                self.nested_relation(model, source, parent)
        for model, source, key in self.links:
            self.link_relation(model, source, key)
        for model, source, key in self.token_slots:
            self.token_relation(model, source, key)
        for model in self.models:
            if model.kind == "items":
                self.subsets(model)
        self.derived_titles()
        self.reverse_relations()

    def reverse_relations(self) -> None:
        """A link to another row that only shows the rows pointing back is no field.

        A treatment page that links to its stories, while each story names its
        treatment, holds one relation seen from both ends: the story's foreign
        key stays, and the page loops over ``treatment.story_set``.
        """
        for model in self.models:
            for f in list(model.fields):
                if f.kind != "relation" or f.many or f.target is None or f.target is model:
                    continue
                other = f.target
                back = next(
                    (
                        g
                        for g in other.fields
                        if g.kind == "relation" and not g.many and g.target is model
                    ),
                    None,
                )
                if back is None:
                    continue
                pointing: dict[int, set[int]] = {}
                for eid, row in back.values.items():
                    if isinstance(row, Entity):
                        pointing.setdefault(id(row), set()).add(eid)
                shown = {eid: row for eid, row in f.values.items() if isinstance(row, Entity)}
                if not shown or any(
                    id(row) not in pointing.get(eid, set()) for eid, row in shown.items()
                ):
                    continue
                model.fields.remove(f)
                accessor = other.name.lower() + "_set"
                model.notes.append(
                    f"{f.name} shows the {other.name} rows whose {back.name} is this "
                    f"{model.name}: loop over {snake(model.name)}.{accessor}.all in the "
                    "template, not a field."
                )

    def derived_titles(self) -> None:
        """A text that always names another model's row shows that row: a relation, not a field.

        The text is the row's title ("Taught by Mia Chen") or its key (a tag
        ``whitening`` naming the ``whitening`` treatment). When the model
        already points at that row another way (a link), the text is read
        through that relation and dropped. Otherwise the text becomes the
        relation, and the map reads it ``"by": "title"`` or ``"by": "key"``.
        """
        titles = {
            id(m): {_norm(self._title(e)): e for e in m.entities if _norm(self._title(e))}
            for m in self.models
            if m.kind == "items"
        }
        keys = {
            id(m): {t[4:]: e for e in m.entities for t in e.tokens if t.startswith("key:")}
            for m in self.models
            if m.kind == "items"
        }
        for model in self.models:
            for f in list(model.fields):
                if f.kind != "value" or f.slot_kind != "text":
                    continue
                raw = {eid: str(v) for eid, v in f.values.items() if v}
                shown = {_norm(v) for v in raw.values()}
                if len(shown) < 2:
                    continue
                for other in self.models:
                    if other is model or id(other) not in titles:
                        continue
                    by_title, by_key = titles[id(other)], keys[id(other)]
                    if shown <= set(by_title):
                        by, rows = "title", {eid: by_title[_norm(v)] for eid, v in raw.items()}
                    elif all(slugify(v) in by_key for v in raw.values()):
                        by, rows = "key", {eid: by_key[slugify(v)] for eid, v in raw.items()}
                    else:
                        continue
                    linked = any(
                        g is not f and g.kind == "relation" and g.target is other and not g.many
                        for g in model.fields
                    )
                    if linked:
                        model.fields.remove(f)
                        model.notes.append(
                            f"{f.name} always shows a {other.name} {by}: read it through the "
                            f"relation to {other.name} in the template, not as a field."
                        )
                        break
                    wanted = snake(other.name)
                    if f.name != wanted:
                        f.name = self._unique(model, wanted)
                    f.kind, f.type, f.optional, f.target = (
                        "relation",
                        f"fk:{other.name}",
                        True,
                        other,
                    )
                    f.values = dict(rows)
                    for rule in f.rules:
                        rule.options.update({"to": other.name, "by": by})
                    f.note = (
                        f"the text names a {other.name} by its {by}: a relation, read "
                        f'"by": "{by}" in the map'
                    )
                    break

    def nested_relation(self, model: Model, source: Source, parent: Model) -> None:
        parents: dict[int, set[int]] = {}
        lists: dict[int, list[Entity]] = {}
        parent_entities: dict[int, Entity] = {}
        for entry in source.entries:
            if entry.entity is None or entry.parent is None or entry.parent.entity is None:
                continue
            parents.setdefault(id(entry.entity), set()).add(id(entry.parent.entity))
            lists.setdefault(id(entry.parent.entity), []).append(entry.entity)
            parent_entities[id(entry.parent.entity)] = entry.parent.entity
        everyone = {id(entity) for entity in model.entities}
        covers = set(parents) == everyone
        single = all(len(p) == 1 for p in parents.values())
        if parent is not model and covers and single:
            name = self._unique(model, snake(parent.name))
            f = Field(
                name,
                f"fk:{parent.name}",
                optional=True,
                kind="relation",
                target=parent,
                slot_kind="link",
            )
            for child_id, parent_ids in parents.items():
                f.values[child_id] = parent_entities[next(iter(parent_ids))]
            model.fields.append(f)
            self.rows_from[id(source)] = f
            return
        self.reference.add(source.id)
        name = self._unique(parent, self.namer.list_name(source, model.name))
        # "self" would make Django's many-to-many symmetrical: a hand-picked list is one-way.
        target = f"{self.app}.{model.name}" if model is parent else model.name
        f = Field(
            name,
            f"m2m:{target}",
            optional=True,
            kind="relation",
            target=model,
            many=True,
            slot_kind="link",
        )
        f.values = {pid: list(items) for pid, items in lists.items()}
        assert source.parent is not None
        f.rules.append(Rule(source.parent, None, "", {"_relation": source}))
        parent.fields.append(f)
        if source.parent.kind == "detail":
            self.later.append((parent, f, source))

    def link_relation(self, model: Model, source: Source, key: SlotKey) -> None:
        path, _, _ = key
        targets: dict[int, Entity] = {}
        target_model: Model | None = None
        for entry in source.entries:
            slot = entry.value(key)
            if slot is None or entry.entity is None:
                continue
            found = self._points_at(entry, slot)
            if isinstance(found, tuple):
                target_model = target_model or found[0]
                if found[0] is target_model:
                    targets[id(entry.entity)] = found[1]
        present = [e for e in source.entries if e.value(key) is not None and e.entity is not None]
        if target_model is None or len(targets) < 0.8 * len(present):
            name = self._unique(
                model, self.namer.field_name(source, key, title=False), self._context(source)
            )
            f = Field(name, kind="value", slot_kind="link")
            f.rules.append(Rule(source, key))
            for entry in present:
                slot = entry.value(key)
                if slot is not None and entry.entity is not None:
                    f.values.setdefault(id(entry.entity), slot.value)
            model.fields.append(f)
            return
        words_ = self.namer.class_words(_step_classes(path[-1]) if path else [])
        if not words_ and len(path) >= 2:
            words_ = self.namer.class_words(_step_classes(path[-2]))
        name = snake(" ".join(words_)) if words_ else snake(target_model.name)
        existing = next(
            (
                f
                for f in model.fields
                if f.kind == "relation" and f.target is target_model and not f.many
            ),
            None,
        )
        if existing is None:
            existing = Field(
                self._unique(model, name),
                f"fk:{target_model.name}",
                optional=True,
                kind="relation",
                target=target_model,
                slot_kind="link",
            )
            model.fields.append(existing)
        existing.rules.append(Rule(source, key, "", {"to": target_model.name}))
        for entity_id, entity in targets.items():
            existing.values.setdefault(entity_id, entity)
        if len(targets) < len([e for e in model.entities]):
            existing.optional = True

    def token_relation(self, model: Model, source: Source, key: SlotKey) -> None:
        _, _, attr = key
        tokens: dict[int, list[str]] = {}
        for entry in source.entries:
            slot = entry.value(key)
            if slot is not None and entry.entity is not None:
                tokens[id(entry.entity)] = slot.value.split()
        everything = [t for values in tokens.values() for t in values]
        best: tuple[Model, dict[str, Entity]] | None = None
        for other in self.models:
            if other is model or other.kind != "items":
                continue
            known = {t[4:]: e for e in other.entities for t in e.tokens if t.startswith("key:")}
            hits = sum(1 for t in everything if t in known)
            if (
                everything
                and hits >= 0.8 * len(everything)
                and (best is None or hits > sum(1 for t in everything if t in best[1]))
            ):
                best = (other, known)
        name = self._unique(model, snake(attr.removeprefix("data-")))
        if best is None:
            best = self.promote(everything)
        if best is None:
            many = any(len(v) > 1 for v in tokens.values())
            f = Field(
                name,
                "json" if many else _str_size(everything),
                kind="json" if many else "value",
                slot_kind="tokens" if many else "data",
            )
            f.rules.append(Rule(source, key, "", {"split": True} if many else {}))
            for entity_id, values in tokens.items():
                f.values[entity_id] = values if many else " ".join(values)
            model.fields.append(f)
            if many:
                f.note = "a list of tags"
            return
        other, known = best
        many = any(len(v) > 1 for v in tokens.values())
        f = Field(
            name,
            f"{'m2m' if many else 'fk'}:{other.name}",
            optional=True,
            kind="relation",
            target=other,
            many=many,
            slot_kind="tokens",
        )
        f.rules.append(
            Rule(
                source, key, "", {"to": other.name, **({"split": True} if many else {"by": "key"})}
            )
        )
        for entity_id, values in tokens.items():
            found = [known[t] for t in values if t in known]
            f.values[entity_id] = found if many else (found[0] if found else None)
        model.fields.append(f)

    def promote(self, tokens: list[str]) -> tuple[Model, dict[str, Entity]] | None:
        """A list kept as page copy whose keys another model's attribute names is a model."""
        for copy in list(self.page_copy):
            source = copy.source
            identity = self.identity.get(id(source)) if source is not None else None
            if source is None or identity is None or identity.attr is None:
                continue
            keys: dict[str, Entry] = {}
            for entry in source.entries:
                slot = entry.value(identity.attr)
                if slot is not None:
                    keys[attr_key(slot.value, identity.prefix)] = entry
            if not tokens or sum(1 for t in tokens if t in keys) < 0.8 * len(tokens):
                continue
            self.page_copy.remove(copy)
            model = Model("", "items", [source])
            for entry in source.entries:
                entity = Entity([entry], set(entry.tokens))
                entry.entity = entity
                model.entities.append(entity)
            self.add_model(model)
            model.name = self._model_name(self.namer.model_name(model))
            for entity in model.entities:
                for token in entity.tokens:
                    self.index.setdefault(token, (model, entity))
            self.fields_of(model)
            known = {
                attr_key(slot.value, identity.prefix): entry.entity
                for entry in source.entries
                if (slot := entry.value(identity.attr)) is not None and entry.entity is not None
            }
            return model, known
        return None

    def subsets(self, model: Model) -> None:
        listing = model.listing
        if listing is None:
            return
        everyone = {id(e) for e in model.entities}
        for source in model.sources:
            if source is listing or source.kind != "list" or source in model.zipped:
                continue
            if id(source) in self.lone:
                continue
            shown = {id(e.entity) for e in source.entries if e.entity is not None}
            if not shown or shown >= everyone:
                continue
            self.reference.add(source.id)
            page = source.page
            name = self._unique(model, "featured" if page.name == "home" else f"on_{page.name}")
            f = Field(name, "bool", kind="bool", slot_kind="bool")
            f.rules.append(Rule(source, None, ":scope", {"present": True}))
            for entity_id in shown:
                f.values[entity_id] = True
            f.decide = (
                f"{page.path} shows {len(shown)} of the {len(everyone)} {model.name} rows. Keep "
                f"{name} if someone picks them (remove this decide), or delete the field if the "
                "page shows the first ones or the newest (a query does it)."
            )
            model.fields.append(f)
            titles = [self._title(e) for e in model.entities if id(e) in shown]
            self.decisions.append(
                Decision(
                    model.name,
                    name,
                    f"{page.path} shows some {model.name} rows: chosen by hand, or by a rule?",
                    f"It shows {len(shown)} of {len(everyone)}: "
                    + ", ".join(t for t in titles[:5] if t)
                    + ".",
                    [
                        (
                            f"chosen by hand: add `{name}:bool` to the {model.name} command and "
                            "keep the field in the map (remove its decide)"
                        ),
                        (
                            f"a rule (the first, the newest, a category): delete `{name}` from "
                            "the map and filter in the view"
                        ),
                    ],
                )
            )

    # keys

    def _attr_prefix(self, model: Model) -> str:
        for source in model.sources:
            identity = self.identity.get(id(source))
            if identity is not None and identity.attr is not None and identity.prefix:
                return identity.prefix
        return ""

    def entity_key(self, model: Model, entity: Entity, position: int) -> str:
        for entry in entity.entries:
            if entry.source.kind == "detail":
                return entry.page.slug
        strip = self._attr_prefix(model)
        for entry in entity.entries:
            identity = self.identity.get(id(entry.source), Identity())
            slot = entry.value(identity.link) if identity.link else None
            if slot is not None:
                ref = _resolve(self.mapped, slot.value, entry.page)
                if ref.kind == "page" and not ref.fragment:
                    return page_slug(ref.path)
        for entry in entity.entries:
            identity = self.identity.get(id(entry.source), Identity())
            slot = entry.value(identity.attr) if identity.attr else None
            if slot is not None:
                return slugify(attr_key(slot.value, identity.prefix))
        for entry in entity.entries:
            identity = self.identity.get(id(entry.source), Identity())
            slot = entry.value(identity.link) if identity.link else None
            if slot is not None:
                key = link_key(_resolve(self.mapped, slot.value, entry.page), strip)
                if key:
                    return slugify(key)
        title = self._title(entity)
        return slugify(title) if title else f"{slugify(model.name)}-{position}"

    def keys(self) -> None:
        for model in self.models:
            if model.kind == "child":
                continue
            if model.kind == "pages":
                for source in model.sources:
                    if source in model.zipped:
                        continue
                    for entry in source.entries:
                        if entry.entity is not None:
                            entry.entity.key = f"{self._prefix(model, source, entry)}-{entry.index}"
                continue
            taken: set[str] = set()
            for position, entity in enumerate(model.entities, start=1):
                key = (
                    self.entity_key(model, entity, position) or f"{slugify(model.name)}-{position}"
                )
                base, counter = key, 2
                while key in taken:
                    key = f"{base}-{counter}"
                    counter += 1
                if key != base:
                    model.notes.append(f"two rows had the key {base!r}: one is {key!r} now")
                taken.add(key)
                entity.key = key

    def _prefix(self, model: Model, source: Source, entry: Entry | None = None) -> str:
        if source.parent is not None and source.parent.kind == "detail":
            family = self.model_of.get(id(source.parent))
            name = slugify(family.name) if family else "page"
            return f"{name}-{entry.page.slug}" if entry is not None else f"{name}-{{page}}"
        return slugify(source.page.name.replace("_", "-"))

    def key_rule(self, model: Model, source: Source) -> dict[str, Any]:
        if source.kind == "detail":
            return {"from": "page"}
        if model.kind == "pages" or (source in model.zipped and model.kind == "pages"):
            partner = source
            if source in model.zipped:
                partner = next(
                    (s for s in model.sources if s.page is source.page and s not in model.zipped),
                    source,
                )
            return {"from": "position", "prefix": self._prefix(model, partner)}
        entries = [e for e in source.entries if e.entity is not None]
        want = {id(e): e.entity.key for e in entries if e.entity is not None}
        identity = self.identity.get(id(source), Identity())
        strip = self._attr_prefix(model)
        candidates: list[tuple[dict[str, Any], Any]] = []
        if identity.link is not None:
            link = identity.link
            rule: dict[str, Any] = {"from": "link", "select": self.place(source, link)}
            if strip:
                rule["strip"] = strip

            def by_link(entry: Entry, link: SlotKey = link) -> str:
                slot = entry.value(link)
                if slot is None:
                    return ""
                return slugify(link_key(_resolve(self.mapped, slot.value, entry.page), strip))

            candidates.append((rule, by_link))
        if identity.attr is not None:
            attr_slot = identity.attr
            rule = {"from": "attr", "name": attr_slot[2]}
            if identity.prefix:
                rule["strip"] = identity.prefix

            def by_attr(entry: Entry, key: SlotKey = attr_slot) -> str:
                slot = entry.value(key)
                return slugify(attr_key(slot.value, identity.prefix)) if slot else ""

            candidates.append((rule, by_attr))
        title = next((f for f in model.fields if f.kind == "title"), None)
        if title is not None and any(r.source is source for r in title.rules):
            title_rule = next(r for r in title.rules if r.source is source)

            def by_title(entry: Entry, key: SlotKey | None = title_rule.key) -> str:
                slot = entry.value(key) if key else None
                return slugify(slot.value) if slot else ""

            candidates.append(({"from": "field", "field": title.name}, by_title))
        for rule, compute in candidates:
            if all(compute(e) == want[id(e)] for e in entries):
                return rule
        if candidates:
            model.notes.append(
                f"the keys of {source.describe()} could not be read the same way as the "
                "other sources'. Check its key rule in the map."
            )
            return candidates[0][0]
        model.by_position = True
        return {"from": "position", "prefix": self._prefix(model, source)}

    # places

    def place(self, source: Source, key: SlotKey) -> str:
        cached = self.places.get((id(source), key))
        if cached is not None:
            return cached
        path, kind, attr = key
        if path == ("meta",):
            return 'meta[name="description"]@content'
        targets = []
        for entry in source.entries:
            slot = entry.value(key)
            targets.append(Target(entry.node, slot.elements if slot else (), entry.page.text))
        anchors = self.anchors(source.pages, path[0]) if source.kind == "detail" and path else []
        selector = ":scope" if path == () else write_selector(targets, anchors)
        attribute = {
            "image": attr,
            "alt": "alt",
            "link": "href",
            "datetime": "datetime",
            "data": attr,
            "id": "id",
        }.get(kind, "")
        if attribute:
            text = (selector if selector != ":scope" else "") + "@" + attribute
        else:
            text = selector
        self.places[(id(source), key)] = text
        return text

    def items_place(self, source: Source) -> str:
        if source.kind == "list":
            return write_selector(
                [Target(source.page.root, tuple(e.node for e in source.entries), source.page.text)]
            )
        by_parent: dict[int, list[Entry]] = {}
        for entry in source.entries:
            by_parent.setdefault(id(entry.parent), []).append(entry)
        targets: list[Target] = []
        parent_source = source.parent
        for parent in parent_source.entries if parent_source else []:
            children = by_parent.get(id(parent), [])
            targets.append(Target(parent.node, tuple(e.node for e in children), parent.page.text))
        anchors: list[str] = []
        if parent_source is not None and parent_source.kind == "detail" and source.path:
            anchors = self.anchors(parent_source.pages, source.path[0])
        return write_selector(targets, anchors)

    def anchors(self, pages: list[Page], block: str) -> list[str]:
        """Selectors for one section of detail pages, wherever it sits on each page: its id,
        a class only it has, or a class only found inside it."""
        found: list[str] = []
        present: list[tuple[Page, Node]] = []
        for page in pages:
            node = dict(page.blocks).get(block)
            if node is not None:
                present.append((page, node))
        if not present:
            return found
        tags = {node.tag for _, node in present}
        tag = tags.pop() if len(tags) == 1 else "*"
        ids = {node.attr(page.text, "id") or "" for page, node in present}
        if len(ids) == 1 and (ident := ids.pop()) and re.match(r"^[A-Za-z][-\w]*$", ident):
            found.append(f"#{ident}")
        own: set[str] | None = None
        inside: set[str] | None = None
        elsewhere: set[str] = set()
        others_own: set[str] = set()
        for page, node in present:
            classes = set(node.classes(page.text))
            subtree = {
                c for n in node.iter_elements() if n is not node for c in n.classes(page.text)
            }
            own = classes if own is None else own & classes
            inside = subtree if inside is None else inside & subtree
            for _, other in page.blocks:
                if other is node:
                    continue
                others_own |= set(other.classes(page.text))
                elsewhere |= {c for n in other.iter_elements() for c in n.classes(page.text)}
        for token in sorted(own or set(), key=lambda t: (is_utility_class(t), t)):
            if token not in others_own and re.match(r"^-?[_A-Za-z][-\w]*$", token):
                found.append(f"{tag}.{token}")
        distinct = sorted((inside or set()) - elsewhere, key=lambda t: (is_utility_class(t), t))
        for token in distinct[:3]:
            if re.match(r"^-?[_A-Za-z][-\w]*$", token):
                found.append(f"{tag}:has(.{token})")
        return found

    # bindings

    def bind(self) -> None:
        for model in self.models:
            if model.kind == "child":
                continue
            for source in model.sources:
                binding = Binding(source, self.key_rule(model, source))
                if source.kind != "detail":
                    binding.items = self.items_place(source)
                rows = self.rows_from.get(id(source))
                if rows is not None and source.parent is not None:
                    parent_model = self.model_of.get(id(source.parent))
                    binding.within = (
                        self.items_place(source.parent) if source.parent.kind != "detail" else None
                    )
                    binding.parent = {
                        "field": rows.name,
                        "key": self.key_rule(parent_model, source.parent) if parent_model else {},
                    }
                binding.position = (
                    source is model.listing or model.kind == "pages" or (rows is not None)
                )
                binding.create = source.id not in self.reference
                if source in model.zipped:
                    binding.zipped = True
                    binding.position = False
                if model.kind == "pages":
                    partner = source
                    if source in model.zipped:
                        partner = next(
                            (
                                s
                                for s in model.sources
                                if s.page is source.page and s not in model.zipped
                            ),
                            source,
                        )
                    if partner.parent is not None and partner.parent.kind == "detail":
                        family = self.model_of.get(id(partner.parent))
                        if family is not None and not binding.zipped:
                            binding.constants = {
                                "page": snake(family.name),
                                snake(family.name): "{page}",
                            }
                    elif not binding.zipped:
                        binding.constants = {"page": partner.page.name}
                model.bindings.append(binding)
            for f in model.fields:
                for rule in f.rules:
                    self.place_rule(model, f, rule)
            model.bindings = sorted(
                (
                    b
                    for b in model.bindings
                    if b.create or any(r.source is b.source for f in model.fields for r in f.rules)
                ),
                key=lambda b: not b.create,
            )
        for model in self.models:
            if model.kind == "child" and model.parent is not None:
                self.child_rule(model)

    def place_rule(self, model: Model, f: Field, rule: Rule) -> None:
        nested = rule.options.pop("_list", None) or rule.options.pop("_relation", None)
        if isinstance(nested, Source):
            self.nested_rule(model, f, rule, nested)
            return
        if rule.key is None:
            rule.place = rule.place or ":scope"
            return
        kind = rule.key[1]
        rule.place = self.place(rule.source, rule.key)
        if kind == "text" and any(
            (slot := e.value(rule.key)) is not None and slot.run for e in rule.source.entries
        ):
            rule.options["all"] = True
        if kind == "pairs":
            rule.options["pairs"] = True
        if kind == "link" and f.kind != "relation":
            rule.options["link"] = "path"

    def nested_rule(self, model: Model, f: Field, rule: Rule, nested: Source) -> None:
        items = self.items_place(nested)
        if f.kind == "relation":
            identity = self.identity.get(id(nested), Identity())
            target = f.target.name if f.target else ""
            if identity.link is not None:
                rule.place = _join(items, self.place(nested, identity.link))
            elif identity.attr is not None:
                rule.place = _join(items, self.place(nested, identity.attr))
            elif nested.title_key is not None:
                rule.place = _join(items, self.place(nested, nested.title_key))
                rule.options["by"] = "title"
            else:
                rule.place = items
            rule.options = {"to": target, "many": True, **rule.options}
            return
        texts = [k for k in nested.slot_keys() if k[1] == "text"]
        varying = [
            k for k in texts if len({s.value for s in nested.values(k) if s is not None}) > 1
        ] or texts
        rule.place = items
        if len(varying) == 1 and varying[0][0] == ():
            rule.options["list"] = True
        elif len(varying) == 1:
            rule.options["list"] = self.place(nested, varying[0])
        else:
            fields: dict[str, str] = {}
            for key in varying:
                name = self.namer.field_name(nested, key, title=key == nested.title_key)
                while name in fields:
                    name += "_2"
                fields[name] = self.place(nested, key)
            rule.options["fields"] = fields

    def child_rule(self, model: Model) -> None:
        parent = model.parent
        assert parent is not None
        for source in model.sources:
            if source.parent is None:
                continue
            rows: dict[str, str] = {}
            for f in model.fields:
                for rule in f.rules:
                    if rule.source is source and rule.key is not None:
                        rows[f.name] = self.place(source, rule.key)
            holder = Field(model.accessor, kind="child")
            holder.rules.append(Rule(source.parent, None, self.items_place(source), {"rows": rows}))
            parent.fields.append(holder)

    # types

    def types(self) -> None:
        for model in self.models:
            creating = self._creating(model)
            for f in model.fields:
                if f.kind == "child":
                    continue
                values = [f.values.get(id(e)) for e in creating]
                missing = any(v in (None, "", []) for v in values)
                if f.kind in ("value", "title"):
                    raw = [str(v) for v in f.values.values() if v not in (None, "")]
                    if f.slot_kind == "alt":
                        f.type = _str_size(raw)
                    elif f.slot_kind == "data":
                        f.type, f.note = infer_type("text", raw, self.decimal)
                    else:
                        f.type, note = infer_type(f.slot_kind, raw, self.decimal)
                        f.note = f.note or note
                elif f.kind == "bool":
                    f.type = "bool"
                    missing = False
                elif f.kind == "json":
                    f.type = "json"
                    missing = False
                if f.kind != "relation" or not f.many:
                    f.optional = f.optional or missing
                example = next((v for v in f.values.values() if v not in (None, "", [])), "")
                if isinstance(example, Entity):
                    example = example.key
                elif isinstance(example, list):
                    example = ", ".join(
                        e.key if isinstance(e, Entity) else str(e) for e in example[:4]
                    )
                f.example = str(example)
            self._structural_fields(model)

    def _creating(self, model: Model) -> list[Entity]:
        if model.kind != "items":
            return list(model.entities)
        found = []
        for entity in model.entities:
            if any(e.source.id not in self.reference for e in entity.entries):
                found.append(entity)
        if len(found) < len(model.entities):
            model.notes.append(
                f"{len(model.entities) - len(found)} item(s) appear only where other rows are "
                "shown (a list on another page): they are not created."
            )
            model.entities = found
        return found

    def _structural_fields(self, model: Model) -> None:
        head: list[Field] = []
        tail: list[Field] = []
        if model.kind == "items":
            title = next((f for f in model.fields if f.kind == "title"), None)
            slug = Field("slug", f"slug:{title.name}" if title else "slug", kind="key")
            slug.example = model.entities[0].key if model.entities else ""
            if title is not None:
                # The title first: karni make model names a row by its first text field.
                model.fields.remove(title)
                head.append(title)
            head.append(slug)
            if model.listing is not None and model.listing.kind != "detail" or model.by_position:
                tail.append(Field("position", "int", kind="position", example="1"))
        elif model.kind == "pages":
            choices: list[str] = []
            family_field: Field | None = None
            for binding in model.bindings:
                page = binding.constants.get("page")
                if page and page not in choices:
                    choices.append(page)
                for name in binding.constants:
                    if name != "page" and family_field is None:
                        family = next((m for m in self.models if snake(m.name) == name), None)
                        family_field = Field(
                            name,
                            f"fk:{family.name}" if family else "str:80",
                            optional=True,
                            kind="relation",
                            target=family,
                        )
            slug = Field(
                "slug", "slug", kind="key", example=model.entities[0].key if model.entities else ""
            )
            head.append(slug)
            if len(choices) > 1:
                head.append(
                    Field("page", "choice:" + "|".join(choices), kind="page", example=choices[0])
                )
            elif choices:
                model.notes.append(f"every row is on {choices[0]}")
                for binding in model.bindings:
                    binding.constants.pop("page", None)
            if family_field is not None:
                head.append(family_field)
            tail.append(Field("position", "int", kind="position", example="1"))
        else:
            parent = model.parent
            assert parent is not None
            head.append(
                Field(snake(parent.name), f"fk:{parent.name}", kind="relation", target=parent)
            )
            tail.append(Field("position", "int", kind="position", example="1"))
        model.fields = [*head, *model.fields, *tail]

    # highlighted words

    def highlights(self) -> None:
        """One markup for the site's highlighted words: the one KARNI_SITE_HIGHLIGHT holds
        (``karni import design --editable`` wrote it), else the one most fields use. A field
        with another markup names it in the filter."""
        fields = [(m, f) for m in self.models for f in m.columns if f.highlight]
        if not fields:
            return
        uses: dict[str, list[str]] = {}
        for model, f in fields:
            uses.setdefault(f.highlight[0], []).append(f"{model.name}.{f.name}")
        default = self.configured or max(uses, key=lambda spec: len(uses[spec]))
        marked = f"{HIGHLIGHT_MARKER}marked{HIGHLIGHT_MARKER}"
        for _, f in fields:
            spec = f.highlight[0]
            how = (
                "{{ value|highlight }}"
                if spec == default
                else (f'{{{{ value|highlight:"{spec}" }}}}')
            )
            f.note = f"highlighted words are {marked}: render with {how}"
        self.highlight = HighlightAdvice(HIGHLIGHT_MARKER, default, self.configured, uses)

    # decisions

    def decide_lone(self) -> None:
        for model in self.models:
            for source in model.sources:
                partner = self.lone.get(id(source))
                if partner is None:
                    continue
                own = sorted(
                    (
                        f
                        for f in model.fields
                        if f.rules and all(r.source is source for r in f.rules)
                    ),
                    key=lambda f: f.kind != "bool",
                )
                node = source.entries[0].node
                where = f"{source.page.path}: {step_of(node, source.page.text)}"
                tokens = " ".join(f.token for f in own)
                text = (
                    f"{where} looks like a {model.name} item but is not one of the list: one "
                    "more row? Keep it (remove the decide on its fields) or delete this source "
                    "and its fields."
                )
                for f in own:
                    f.decide = text
                title = self._title(source.entries[0].entity)
                self.decisions.append(
                    Decision(
                        model.name,
                        own[0].name if own else "",
                        f"{where} has the values of a {model.name} item ({title or 'no title'}), "
                        "styled on its own: one more row, or page copy?",
                        f"It fills the fields {partner.step} items fill on the same page, and "
                        f"adds {', '.join(f.name for f in own) or 'nothing'}.",
                        [
                            (
                                f"one more row: add {tokens} to the {model.name} command and "
                                "remove the decides on those fields in the map"
                            ),
                            "page copy: delete the source and those fields from the map",
                        ],
                    )
                )

    def decide(self) -> None:
        self.decide_lone()
        for parent, f, source in self.later:
            target = f.target
            if target is None:
                continue
            listed = {pid: {id(e) for e in items} for pid, items in f.values.items()}
            inverse = next(
                (
                    g
                    for g in target.fields
                    if g.kind == "relation" and g.target is parent and g is not f
                ),
                None,
            )
            if inverse is not None:
                agree = 0
                for entity in parent.entities:
                    derived = {
                        id(k)
                        for k in target.entities
                        if entity in _as_list(inverse.values.get(id(k)))
                    }
                    if listed.get(id(entity), set()) == derived:
                        agree += 1
                evidence = (
                    f"{agree} of {len(parent.entities)} {parent.name} pages list exactly the "
                    f"{target.name} rows whose {inverse.name} name them."
                )
                lean = "hand-picked" if agree < len(parent.entities) else "derived"
            else:
                shared = self._shared_value(parent, target, f)
                evidence = (
                    f"Every listed {target.name} has the same {shared} as its page."
                    if shared
                    else f"No other field of {target.name} names the {parent.name} rows, so "
                    "nothing derives these lists."
                )
                lean = "derived" if shared else "hand-picked"
            f.decide = (
                f"{parent.name}.{f.name}: hand-picked or derived? Remove this decide to keep the "
                "list, or delete the field to derive it in the view."
            )
            pages = len(source.pages)
            self.decisions.append(
                Decision(
                    parent.name,
                    f.name,
                    f"the {target.name} rows each {parent.name} page shows ({pages} page(s)): "
                    "a hand-picked list, or derived from other fields?",
                    f"{evidence} It looks {lean}.",
                    [
                        (
                            f"hand-picked: add `{f.token}` to the {parent.name} command "
                            + ("" if parent is target else f"(after {target.name} exists) ")
                            + "and remove the decide from the map"
                        ),
                        f"derived: delete `{f.name}` from the map and query the rows in the view",
                    ],
                )
            )

    def _shared_value(self, parent: Model, target: Model, f: Field) -> str:
        if parent is not target:
            return ""
        for g in target.fields:
            if g.kind not in ("value", "relation") or g is f or g.many:
                continue
            pairs = [
                (g.values.get(id(entity)), g.values.get(id(item)))
                for entity in parent.entities
                for item in f.values.get(id(entity), [])
            ]
            if pairs and all(a is not None and a == b for a, b in pairs):
                return g.name
        return ""

    # order

    def order(self) -> None:
        placed: list[Model] = []
        remaining = list(self.models)
        while remaining:
            ready = [
                m for m in remaining if all(dep in placed or dep is m for dep in self._deps(m))
            ]
            if not ready:
                stuck = min(
                    remaining, key=lambda m: len([d for d in self._deps(m) if d not in placed])
                )
                for f in stuck.fields:
                    if (
                        f.many
                        and f.target is not None
                        and f.target not in placed
                        and f.target is not stuck
                    ):
                        f.later = True
                ready = [stuck]
            for model in ready:
                placed.append(model)
                remaining.remove(model)
        self.models[:] = placed

    def _deps(self, model: Model) -> list[Model]:
        found = [
            f.target
            for f in model.fields
            if f.target is not None and f.in_model and not f.decide and not f.later
        ]
        if model.parent is not None:
            found.append(model.parent)
        return [m for m in found if m is not None]


def _shape_key(key: SlotKey) -> tuple[str, str, str]:
    """A slot by what it is, not where: ``(text, "", "p.role")``, ``(image, src, img)``."""
    path, kind, attr = key
    last = path[-1].split(":", 1)[0] if path else ""
    return (kind, attr, last)


def _within(node: Node, ancestor: Node) -> bool:
    current = node.parent
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _join(outer: str, inner: str) -> str:
    """``inner`` (relative to an item) under ``outer`` (the items)."""
    selector, at, attribute = inner.partition("@")
    tail = f"@{attribute}" if at else ""
    if selector in ("", ":scope"):
        return outer + tail
    parts = [f"{o.strip()} {i.strip()}" for o in outer.split(",") for i in selector.split(",")]
    return ", ".join(parts) + tail
