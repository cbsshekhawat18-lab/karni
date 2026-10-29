"""What the analysis proposes: models, fields, rules, decisions, names and types.

Part of :mod:`karni_cli.design.analyze`. The data a proposal is made of
(:class:`Model`, :class:`Field`, :class:`Rule`, :class:`Binding`,
:class:`Decision`), the :class:`Namer` that names models and fields from the
design's own words, and how a value's type is inferred (:func:`infer_type`)
and parsed (:func:`parse_value`).
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Final

from karni_cli.design.parse import Node, collapse
from karni_cli.design.scan import Slot
from karni_cli.design.sources import (
    Entity,
    Entry,
    Family,
    SlotKey,
    Source,
    _norm,
)
from karni_cli.design.values import (
    HIGHLIGHT_MARKER,
    UI_WORDS,
    date,
    is_utility_class,
    mark_pattern,
    number,
    pascal,
    plural,
    price,
    singular,
    snake,
    words,
)

#: Field names Karni's base model or the map already uses.
_RESERVED: Final = frozenset(
    {
        "id",
        "pk",
        "slug",
        "page",
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
        "updated_by",
        "objects",
        "all_objects",
        "is_deleted",
        "delete",
        "hard_delete",
        "restore",
        "save",
        "clean",
        "class",
        "def",
        "for",
        "from",
        "global",
        "import",
        "in",
        "is",
        "lambda",
        "not",
        "or",
        "pass",
        "return",
        "with",
        "yield",
        "and",
        "as",
        "if",
        "else",
        "try",
        "while",
        "none",
        "true",
        "false",
    }
)

#: Words for a position, a style variant or a widget: never a field's whole name.
_VARIANTS: Final = frozenset(
    {
        "top",
        "bottom",
        "left",
        "right",
        "center",
        "middle",
        "fluid",
        "responsive",
        "cover",
        "inline",
        "btn",
        "button",
        "light",
        "dark",
        "lg",
        "sm",
        "md",
        "xl",
        "xs",
        "img",
        "image",
        "pic",
        "picture",
        "text",
        "copy",
        "display",
        "outline",
    }
)

#: Widget words that still name a field well (a project's badge, a hero's chip).
_FIELD_WORDS: Final = frozenset({"badge", "chip", "pill", "tag"})

#: A number written before an item's label: ``01 — Design``, ``2. Planning``.
_NUMBERED: Final = re.compile(r"^\s*(\d{1,3})\s*[—–\-·.:/|)]+\s*(\S.*)$", re.DOTALL)

_TAG_NAMES: Final = {
    "p": "text",
    "span": "label",
    "li": "item",
    "blockquote": "quote",
    "q": "quote",
    "cite": "cite",
    "time": "date",
    "b": "value",
    "strong": "value",
    "dt": "term",
    "dd": "value",
    "figcaption": "caption",
    "small": "note",
    "label": "label",
    "button": "label",
    "td": "value",
    "th": "label",
    "address": "address",
    "em": "label",
    "i": "label",
}


# --- models ------------------------------------------------------------------


@dataclass(eq=False)
class Rule:
    """How one source reads one field: a place (``"h3"``, ``"img@src"``) and options."""

    source: Source
    key: SlotKey | None = None
    place: str = ""
    options: dict[str, Any] = field(default_factory=dict)

    def to_map(self) -> str | dict[str, Any]:
        if not self.options:
            return self.place
        return {"select": self.place, **self.options}


@dataclass(eq=False)
class Field:
    """A field of a proposed model, the values found for it and where each source reads it."""

    name: str
    type: str = ""  # the karni make model type after ``name:`` (``str:200``, ``fk:Teacher``)
    optional: bool = False
    kind: str = "value"  # value | title | key | position | page | relation | json | child | bool
    slot_kind: str = "text"
    values: dict[int, Any] = field(default_factory=dict)  # id(entity) → value
    rules: list[Rule] = field(default_factory=list)
    example: str = ""
    decide: str = ""
    note: str = ""
    target: Model | None = None
    many: bool = False
    highlight: list[str] = field(default_factory=list)
    later: bool = False  # a many-to-many field added once its target exists
    title_votes: int = 0  # sources whose items are named by this field

    @property
    def token(self) -> str:
        """``name:type`` (``?`` when optional), as ``karni make model`` reads it."""
        return f"{self.name}:{self.type}{'?' if self.optional else ''}"

    @property
    def in_model(self) -> bool:
        """Whether the field is a column of the model (child rows are not)."""
        return self.kind != "child"


@dataclass(eq=False)
class Binding:
    """One source of a model in the map: where its items are and how each is keyed."""

    source: Source
    key: dict[str, Any] = field(default_factory=dict)
    items: str | None = None  # None: the page itself (a detail page)
    within: str | None = None
    parent: dict[str, Any] | None = None
    position: bool = False
    constants: dict[str, str] = field(default_factory=dict)
    create: bool = True
    zipped: bool = False


@dataclass(eq=False)
class Model:
    """A proposed model: its sources, rows (entities) and fields."""

    name: str
    kind: str  # items | pages (a list per page) | child
    sources: list[Source] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)
    bindings: list[Binding] = field(default_factory=list)
    parent: Model | None = None
    family: Family | None = None
    listing: Source | None = None
    notes: list[str] = field(default_factory=list)
    accessor: str = ""
    zipped: list[Source] = field(default_factory=list)
    by_position: bool = False
    noun: str = ""  # a child model's name after its parent's (``Image`` in ``ProjectImage``)

    def field_named(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)

    @property
    def columns(self) -> list[Field]:
        return [f for f in self.fields if f.in_model]

    @property
    def rows(self) -> int:
        return len(self.entities)


@dataclass
class Decision:
    """Something the markup cannot settle: the question, the evidence and the choices."""

    model: str
    field: str
    question: str
    evidence: str
    choices: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "field": self.field,
            "question": self.question,
            "evidence": self.evidence,
            "choices": self.choices,
        }


@dataclass
class HighlightAdvice:
    """How the site renders highlighted words: one ``KARNI_SITE_HIGHLIGHT`` for every field.

    ``default`` is the markup ``{{ value|highlight }}`` renders (``span.accent``):
    the one the setting holds (``configured``) or, without one, the one most
    fields use. ``uses`` lists the fields per markup.
    """

    marker: str
    default: str
    configured: str | None
    uses: dict[str, list[str]]

    def setting(self) -> dict[str, str]:
        tag, *classes = self.default.split(".")
        return {"marker": self.marker, "tag": tag, "class": " ".join(classes)}

    def setting_line(self) -> str:
        values = ", ".join(f'"{key}": "{value}"' for key, value in self.setting().items())
        return f"KARNI_SITE_HIGHLIGHT = {{{values}}}"

    def lines(self) -> list[str]:
        """The advice for a person, one line per markup."""
        found: list[str] = []
        own = ", ".join(self.uses.get(self.default, []))
        element = _element(self.default)
        if self.configured is not None and self.default in self.uses:
            found.append(
                f"{own} set words apart with {element}, the markup karni import design "
                "--editable already wrote to KARNI_SITE_HIGHLIGHT: render them with "
                "{{ value|highlight }}."
            )
        elif self.configured is not None:
            found.append(
                f"KARNI_SITE_HIGHLIGHT renders {element} (karni import design --editable "
                "wrote it), and no field here uses it."
            )
        else:
            found.append(
                f"{own} set words apart with {element}. Set `{self.setting_line()}` in "
                "config/settings.py: then {{ value|highlight }} renders them, and a client "
                f"types {self.marker}words{self.marker} for the same in an editable block."
            )
        for spec, names in self.uses.items():
            if spec != self.default:
                found.append(
                    f"{', '.join(names)} set words apart with {_element(spec)}: render them "
                    f'with {{{{ value|highlight:"{spec}" }}}}.'
                )
        return found

    def to_dict(self) -> dict[str, Any]:
        return {
            "marker": self.marker,
            "setting": self.setting(),
            "configured": self.configured,
            "fields": {spec: list(names) for spec, names in self.uses.items()},
        }


def _element(spec: str) -> str:
    tag, *classes = spec.split(".")
    return f'<{tag} class="{" ".join(classes)}">' if classes else f"<{tag}>"


@dataclass
class PageCopy:
    """A repeated structure left in the template, and why."""

    where: str
    step: str
    items: int
    reason: str
    source: Source | None = None


# --- names -------------------------------------------------------------------


class Namer:
    """Names models, fields and lists from the design's own words.

    Override / escape hatch: subclass it and pass ``namer=`` to
    :func:`analyze`. Every name can also be changed in the map.
    """

    stop_words: frozenset[str] = frozenset(
        {"our", "the", "a", "an", "of", "and", "all", "your", "my", "we", "us", "for", "to"}
    )

    def class_words(
        self,
        classes: Iterable[str],
        strip: Iterable[str] = (),
        *,
        block: bool = True,
        field: bool = False,
    ) -> list[str]:
        """The words of the first class that says what an element is.

        A BEM class (``course__image``) gives its element's words, else (with
        ``block``) its block's: a field is named by its element, a list or a
        model may be named by its block.
        """
        prefixes = sorted({p for p in strip if p}, key=len, reverse=True)
        for token in classes:
            if is_utility_class(token):
                continue
            name = token
            for prefix in prefixes:
                if name != prefix and name.startswith(prefix) and name[len(prefix)] in "-_":
                    name = name[len(prefix) :].lstrip("-_")
                    break
            name = name.split("--", 1)[0]
            parts = list(reversed(name.split("__"))) if "__" in name else [name]
            if not block:
                parts = parts[:1]
            skip = (UI_WORDS - _FIELD_WORDS) if field else UI_WORDS
            for part in parts:
                found = [
                    w
                    for w in words(part)
                    if w not in skip and w not in _VARIANTS and len(w) > 2 and not w.isdigit()
                ]
                if found:
                    return found
        return []

    def label_words(self, text: str, limit: int = 3) -> list[str]:
        """A short label's words (``"Key services"``), or nothing when it is a sentence."""
        found = [w for w in words(unescape(text)) if not w.isdigit() and w not in self.stop_words]
        return found if 0 < len(found) <= limit else []

    def model_name(self, model: Model) -> str:
        candidates: list[list[str]] = []
        if model.family is not None:
            if model.family.folder:
                candidates.append(words(posixpath.basename(model.family.folder)))
            listed = model.family.listed_on
            if listed is not None and listed.name != "home":
                candidates.append(words(listed.name))
        ordered = sorted(
            (s for s in model.sources if s.kind != "detail" and s not in model.zipped),
            key=lambda s: (s is not model.listing, s.kind == "nested", -len(s.entries), s.id),
        )
        for source in ordered:
            if source.container is not None:
                label = source.container.attr(source.page.text, "aria-label") or ""
                found = self.label_words(label)
                if found:
                    candidates.append(found)
        for source in ordered:
            found = self.class_words(source.step.split(".")[1:])
            if found:
                candidates.append(found)
        for source in ordered:
            if source.container is not None:
                found = self.class_words(source.container.classes(source.page.text))
                if found:
                    candidates.append(found)
        for source in ordered:
            if source.kind == "list" and source.page.name != "home":
                candidates.append([*words(source.page.name), "item"])
        for found in candidates:
            if found:
                return pascal(" ".join([*found[:-1], singular(found[-1])]))
        return "Item"

    def list_name(self, source: Source, target: str = "") -> str:
        """A nested list's name: its container's label or class, the label before it, or
        its items' class, else the target model's plural."""
        container = source.container
        text = source.page.text
        if container is not None:
            found = self.label_words(container.attr(text, "aria-label") or "")
            if not found:
                found = self.class_words(container.classes(text))
            if not found:
                found = self.label_words(_label_before(container, text))
            if found:
                return snake(" ".join([*found[:-1], plural(found[-1])]))
            found = self.class_words(source.step.split(".")[1:])
            if found:
                return snake(" ".join([*found[:-1], plural(found[-1])]))
        if target:
            parts = words(target)
            return snake(" ".join([*parts[:-1], plural(parts[-1])]))
        return "items"

    def field_name(self, source: Source, key: SlotKey, *, title: bool, image: str = "") -> str:
        """A field's name: the element's own class (BEM and prefixes stripped), else its role."""
        path, kind, attr = key
        context = ""
        steps = list(path)
        if source.kind == "detail" and steps:
            block = steps.pop(0)
            if not _is_first_block(source, block) and block != "meta":
                context = block
        strip = [c for step in [source.step, *path] for c in _step_classes(step)]
        last = steps[-1] if steps else source.step
        tag = last.split(":", 1)[0].split(".", 1)[0]
        classes = _step_classes(last)
        others = [c for c in strip if c not in classes]
        own = self.class_words(classes, others, block=False, field=True)
        item_words = {w for c in _step_classes(source.step) for w in words(c)}
        if kind == "data":
            base = attr.removeprefix("data-")
        elif kind == "datetime":
            base = "_".join(own) or "date"
        elif kind == "image":
            base = "_".join(own) or "image"
        elif kind == "alt":
            base = f"{image or 'image'}_alt"
        elif kind == "link":
            base = ("_".join(own) or "link") + "_url"
        elif kind == "pairs":
            base = "_".join(own) or "facts"
        elif attr == "description":
            base = "description"
        elif title:
            base = "title"
        elif tag == "h":
            shared = any(c.startswith(p) for c in classes for p in others if p)
            base = "_".join(own) if own and (shared or "__" in "".join(classes)) else "heading"
        elif tag in ("a", "button"):
            base = ("_".join(own) + "_label") if own else "label"
        else:
            if not own and len(steps) >= 2:
                parent = self.class_words(_step_classes(steps[-2]), others, block=False, field=True)
                own = [w for w in parent if w not in item_words]
            base = "_".join(own) or _TAG_NAMES.get(tag, "text")
        name = snake(base)
        if context and kind != "alt":
            context_words = words(context)[:2]
            if not set(words(name)) <= set(context_words):
                name = f"{snake(' '.join(context_words))}_{name}"
        return name


def _step_classes(step: str) -> list[str]:
    head = step.split(":", 1)[0]
    return [c for c in head.split(".")[1:] if c]


def _is_first_block(source: Source, block: str) -> bool:
    page = source.page
    return bool(page.blocks) and page.blocks[0][0] == block


def _label_before(container: Node, source: str) -> str:
    """The text of a short label or heading just before ``container`` (or its parent)."""
    current: Node | None = container
    for _ in range(2):
        if current is None or current.parent is None:
            return ""
        siblings = current.parent.elements()
        index = next((i for i, s in enumerate(siblings) if s is current), -1)
        for sibling in reversed(siblings[:index]):
            text = sibling.plain_text(source)
            if text:
                return text if len(text) <= 40 else ""
        current = current.parent
    return ""


# --- values and types --------------------------------------------------------


def _str_size(values: list[str]) -> str:
    longest = max((len(v) for v in values), default=0)
    for size in (80, 120, 200, 255):
        if longest * 1.5 <= size:
            return f"str:{size}"
    return "text"


def infer_type(kind: str, values: list[str]) -> tuple[str, str]:
    """The ``karni make model`` type for the values of one slot kind, and a note."""
    present = [v for v in values if v != ""]
    if kind == "image":
        return "image", ""
    if kind == "pairs":
        return "json", "a list of [term, definition] pairs"
    if kind == "datetime":
        if present and all(len(v) == 10 and date(v) is not None for v in present):
            return "date", ""
        return "datetime", ""
    if kind == "link":
        if present and all(v.startswith(("http://", "https://")) for v in present):
            return "url", ""
        if present and all(v.lower().startswith("mailto:") for v in present):
            return "email", "the address without mailto:"
        return "str:200", "a page's path or a URL"
    if not present:
        return "str:200", ""
    if any("\n" in v for v in present):
        return "text", ""
    prices = [price(v) for v in present]
    if all(p is not None for p in prices):
        codes = sorted({p[1] for p in prices if p is not None})
        arounds = {p[2] for p in prices if p is not None}
        note = f"a price in {', '.join(codes)}: the symbol stays in the template"
        if arounds != {"|"}:
            note += ", and so do the words around the amount"
        return "decimal:10:2", note + " (money:<code> if the project computes with it)"
    numbers = [number(v) for v in present]
    if len(present) >= 2 and all(n is not None for n in numbers):
        affixes = {(n[1], n[2]) for n in numbers if n is not None}
        if len(affixes) == 1:
            before, after = affixes.pop()
            note = ""
            if before or after:
                around = (before + " " + after).strip()
                note = f"the text around the number ({around!r}) stays in the template"
            if all(n is not None and n[0] == n[0].to_integral_value() for n in numbers):
                return "int", note
            return "decimal:10:2", note
    if all(date(v) is not None for v in present):
        return "date", ""
    return _str_size(present), ""


def parse_value(kind: str, dsl: str, raw: str) -> Any:
    """``raw`` (text as the design shows it) as a content file holds it for the type ``dsl``.

    ``"12 weeks"`` is 12 for ``int``, ``"€4.50"`` is ``"4.50"`` for ``money``,
    ``"14 March 2026"`` is ``"2026-03-14"`` for ``date``. A value that does not
    parse is ``None`` (the field is left out), an empty one too.
    """
    base = dsl.rstrip("?").split(":", 1)[0]
    if raw == "":
        return None
    if base == "int":
        found = number(raw)
        return int(found[0]) if found is not None else None
    if base in ("decimal", "money"):
        found = price(raw) or number(raw)
        return str(found[0]) if found is not None else None
    if base == "date":
        parsed = date(raw)
        return parsed.isoformat() if parsed is not None else None
    if base == "bool":
        return True
    if base == "email":
        return raw[7:] if raw.lower().startswith("mailto:") else raw
    return raw


def _position_like(values: list[str]) -> bool:
    """``01``, ``02``, ``03``: the items' own order written out."""
    found = [number(v) for v in values]
    if len(values) < 2 or any(n is None for n in found):
        return False
    # Only a bare number ("01", "2.", "3)") is a place in the list, not "1 week ahead".
    if any(n is not None and (n[1].strip() or n[2].strip() not in ("", ".", ")")) for n in found):
        return False
    return [int(n[0]) for n in found if n is not None] == list(range(1, len(values) + 1))


_MARKED = mark_pattern(HIGHLIGHT_MARKER)


def _decorations(present: list[tuple[Entry, Slot]]) -> tuple[dict[int, str], list[str]]:
    """Each text without the highlighted bits every item has (an arrow, an icon), and their
    markup: those are the template's, not the content's."""
    texts = {id(e): s.value for e, s in present}
    if len(present) < 2:
        return texts, []
    per_item = [(_MARKED.findall(s.value), s.highlight) for _, s in present]
    common: list[str] = []
    first_marks, first_specs = per_item[0]
    for mark in first_marks:
        if all(mark in marks for marks, _ in per_item):
            common.append(mark)
    if not common:
        return texts, []
    dropped: list[str] = []
    for mark, spec in zip(first_marks, first_specs, strict=False):
        if mark in common and spec not in dropped:
            dropped.append(spec)
    for key, value in texts.items():
        for mark in common:
            value = value.replace(f"{HIGHLIGHT_MARKER}{mark}{HIGHLIGHT_MARKER}", "")
        texts[key] = collapse(value)
    return texts, dropped


def _numbered(values: list[str]) -> bool:
    """``01 — Design``, ``02 — Engineering``: the items' order, then a label."""
    found = [_NUMBERED.match(v) for v in values]
    if len(values) < 2 or any(m is None for m in found):
        return False
    return [int(m.group(1)) for m in found if m is not None] == list(range(1, len(values) + 1))


def _derived(values: list[tuple[str, str]]) -> bool:
    """Every value is its item's title, or the title in the same words around it (two or
    more values: one value shows no pattern)."""
    if len(values) < 2 or any(not title for _, title in values):
        return False
    rests: set[str] = set()
    for value, title in values:
        v, t = _norm(value), _norm(title)
        if t not in v:
            return False
        rests.add(re.sub(r"\d+", "#", v.replace(t, "\0")))
    return len(rests) == 1
