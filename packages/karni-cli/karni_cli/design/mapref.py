"""Every key of a content map (``karni design analyze --map``), in one place.

``karni explain map`` lists them and ``karni explain map.items`` (or
``map.source.key``) prints one. The tables in docs/design-content.md (*The
content map*) are rendered from :func:`markdown` by
``scripts/gen_reference.py``, and :mod:`karni_cli.design.extract` refuses a
source or value key that is not listed here, so the docs, ``karni explain``
and the check cannot disagree.

Stdlib only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final

__all__ = [
    "DOCS_ANCHOR",
    "DOCS_PAGE",
    "KEYS",
    "LEVELS",
    "MapKey",
    "lookup",
    "markdown",
    "names",
    "render",
]

#: Where the docs describe the map (``docs/design-content.md#the-content-map``).
DOCS_PAGE: Final = "design-content"
DOCS_ANCHOR: Final = "the-content-map"

#: Where a key is written, outermost first, and what each level is.
LEVELS: Final[dict[str, str]] = {
    "map": "The map itself, the top-level object",
    "model": 'A model, each object in "models"',
    "source": "Where a model's items are, each object in a model's \"sources\"",
    "key": "How an item's key is read, a source's \"key\" (or its parent's)",
    "value": 'A value given as an object, in a source\'s "values"',
}


@dataclass(frozen=True)
class MapKey:
    """One key: the level it is written at, an example, and what it does."""

    level: str
    name: str
    syntax: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


KEYS: Final[tuple[MapKey, ...]] = (
    # --- the map -------------------------------------------------------------------
    MapKey("map", "version", '"version": 1', "The map's format. This karni reads version 1."),
    MapKey(
        "map", "design", '"design": "../design"', "The design folder, relative to the map file."
    ),
    MapKey("map", "app", '"app": "website"', "The Django app the rows go to, as <app>.<Model>."),
    MapKey(
        "map",
        "marker",
        '"marker": "=="',
        "What extract writes around highlighted words: \"==\" by default, KARNI_SITE_HIGHLIGHT's default. Change it only together with the setting's marker, so the site keeps one convention.",
    ),
    MapKey(
        "map",
        "decimal",
        '"decimal": ","',
        'The decimal mark every page writes, "," or ".". Left out, each page\'s <html lang> decides: 4.000 is 4000 and 1.234,5 is 1234.5 where the language writes a decimal comma (de, fr, es and most of Europe), and a page without a language is read the English way. A separator between groups of three digits is dropped (4,000, 1 234).',
    ),
    MapKey(
        "map",
        "models",
        '"models": [{"name": "Course", ...}]',
        "One object per model: its name, fields, key and sources.",
    ),
    # --- a model -------------------------------------------------------------------
    MapKey(
        "model",
        "name",
        '"name": "Course"',
        "The model's class name. Rename it here and in every relation's \"to\" that names it.",
    ),
    MapKey(
        "model",
        "fields",
        '"fields": {"title": "str:80", "slug": "slug:title", "teacher": "fk:Teacher?"}',
        'The model\'s fields, in karni make model\'s field types. A value reads into the field of its name, parsed by the field\'s type: a number from "12 weeks", an amount from "€4.50", a date from "14 March 2026" or a datetime attribute, a path for an image.',
    ),
    MapKey(
        "model",
        "key",
        '"key": "slug"',
        "The field each row is matched on, so a second load updates the rows instead of adding new ones.",
    ),
    MapKey("model", "order", '"order": "position"', "The field the rows are ordered by."),
    MapKey(
        "model",
        "highlight",
        '"highlight": {"tagline": "em"}',
        "Fields that keep the words a heading sets apart, as ==marked== words, with the markup the design wrote them in.",
    ),
    MapKey(
        "model",
        "parent",
        '"parent": "Course"',
        'A child model: each row belongs to a row of the parent, read by a value named after "accessor" (see "rows").',
    ),
    MapKey(
        "model",
        "accessor",
        '"accessor": "courseimage_set"',
        "The name a child model's rows are read under in the parent's values.",
    ),
    MapKey(
        "model",
        "sources",
        '"sources": [{"pages": [...], "values": {...}}]',
        "Where the model's items are: one object per page or list that shows them.",
    ),
    # --- a source ------------------------------------------------------------------
    MapKey("source", "page", '"page": "courses.html"', "The page the items are on."),
    MapKey(
        "source",
        "pages",
        '"pages": ["courses/pottery.html", "courses/drawing.html"]',
        "Several pages read the same way: the detail pages, or lists that repeat on every page.",
    ),
    MapKey(
        "source",
        "items",
        '"items": "li.course-list__item"',
        "A selector for the items on the page. Left out, the page itself is the item (a detail page).",
    ),
    MapKey(
        "source",
        "within",
        '"within": "section.menu"',
        'Items inside these parents: with "parent", each row points at the parent it is in.',
    ),
    MapKey(
        "source",
        "parent",
        '"parent": {"field": "menu", "key": {"from": "attr", "name": "id"}}',
        'With "within": the field that points at the parent, and how the parent\'s key is read.',
    ),
    MapKey(
        "source",
        "key",
        '"key": {"from": "page"}',
        'How each item\'s key is read, an object whose "from" says from what (karni explain map.key.from). An item read from several sources gets one key everywhere, so its values merge into one row: the first source with a value wins, and extract says where two pages disagree.',
    ),
    MapKey(
        "source",
        "position",
        '"position": true',
        "Write each item's place in its list into the model's order field.",
    ),
    MapKey(
        "source",
        "create",
        '"create": false',
        "Only add values to rows another source makes, never a row of its own.",
    ),
    MapKey(
        "source",
        "set",
        '"set": {"page": "{page}"}',
        "Constant values for every item. {page} is the page's key.",
    ),
    MapKey(
        "source",
        "values",
        '"values": {"title": "h1", "image": "img@src", "topics": {"select": "ul > li", "list": true}}',
        "What each field reads. A value is a place: a CSS selector relative to the item, @attribute for an attribute (img@src, @data-tags for the item's own), :scope for the item's own text. Or an object with \"select\" and the options of the value level.",
    ),
    # --- a key ---------------------------------------------------------------------
    MapKey(
        "key",
        "from",
        '"from": "link"',
        'What the key is read from: "page" (the page\'s file name, courses/pottery.html is pottery), "link" (the page or #anchor a link points at, with "select"), "attr" (an attribute of the item, with "name"), "field" (a field\'s value as a slug, with "field") or "position" (home-1, home-2, with "prefix"). Any other value is refused with C124.',
    ),
    MapKey(
        "key",
        "select",
        '"select": "a.course-list__link@href"',
        'With "from": "link": the place of the link.',
    ),
    MapKey("key", "name", '"name": "id"', 'With "from": "attr": the attribute.'),
    MapKey(
        "key",
        "field",
        '"field": "title"',
        'With "from": "field": the field whose value, as a slug, is the key.',
    ),
    MapKey(
        "key",
        "prefix",
        '"prefix": "home"',
        'With "from": "position": the text before the number. {page} is the page\'s key.',
    ),
    MapKey(
        "key",
        "strip",
        '"strip": "p-"',
        "Text taken off the front of the key read (p-whitening is whitening).",
    ),
    # --- a value -------------------------------------------------------------------
    MapKey(
        "value",
        "select",
        '"select": "ul.course__topics > li"',
        "The place, as in a value given as a string. Selectors support types, classes, ids, attributes, :nth-of-type(), :first-of-type, :last-of-type, :has(), :not() of one compound (p:not(.role)), the child and descendant combinators and comma groups.",
    ),
    MapKey(
        "value", "all", '"all": true', "Every match's text, joined by blank lines (paragraphs)."
    ),
    MapKey(
        "value",
        "list",
        '"list": true',
        "A list, one entry per match: true for the match's text, a place for that place inside each match.",
    ),
    MapKey(
        "value",
        "fields",
        '"fields": {"name": "dt", "price": "dd"}',
        "A list of objects, {name: place} inside each match.",
    ),
    MapKey("value", "pairs", '"pairs": true', "A definition list as [term, definition] pairs."),
    MapKey(
        "value",
        "to",
        '"to": "Teacher"',
        'A relation to that model of the map. "by" says how the place names the row.',
    ),
    MapKey(
        "value",
        "by",
        '"by": "key"',
        'How a relation\'s place names the row: "link" (the default: a link to the row\'s page or #anchor), "key" (the row\'s key, as text or an attribute such as data-type="houses") or "title" (the row\'s title as text, <p>Mia Chen</p>). Analyze writes it when a text names the row. Any other value is refused with C124.',
    ),
    MapKey("value", "many", '"many": true', "A relation to several rows: a many-to-many field."),
    MapKey(
        "value",
        "split",
        '"split": true',
        'A relation read from an attribute that holds several keys (data-tags="a b").',
    ),
    MapKey(
        "value",
        "rows",
        '"rows": {"image": "img@src", "caption": "figcaption"}',
        "Child rows, {field: place} inside each match. The value's name is the child model's accessor (courseimage_set).",
    ),
    MapKey(
        "value", "present", '"present": true', "true when the place matches anything, else false."
    ),
    MapKey("value", "drop", '"drop": ["span.arrow"]', "Markup left out of the text."),
    MapKey(
        "value",
        "pattern",
        '"pattern": "^\\\\d+\\\\s+(.+)$"',
        'A regular expression whose last group is the value ("01 Design" gives "Design").',
    ),
    MapKey(
        "value",
        "link",
        '"link": "path"',
        "A link to a page of the design, written as that page's URL path. Any other value is refused with C124.",
    ),
    MapKey(
        "value",
        "decide",
        '"decide": "Is the price per visit or per course?"',
        "A question the analysis left open. Extract refuses to run until every decide is answered: remove it to keep the value, or delete the value (and the field).",
    ),
)


def names(level: str) -> frozenset[str]:
    """The keys written at ``level`` (what extract accepts there)."""
    return frozenset(key.name for key in KEYS if key.level == level)


def lookup(text: str) -> list[MapKey]:
    """``map`` (every key), ``map.items`` (every key of that name, else every key of that
    level: ``map.value``) or ``map.source.key``."""
    words = text.strip().lower().split(".")
    if not words or words[0] != "map":
        return []
    if len(words) == 1:
        return list(KEYS)
    if len(words) == 2:
        named = [key for key in KEYS if key.name == words[1]]
        return named or [key for key in KEYS if key.level == words[1]]
    if len(words) == 3:
        return [key for key in KEYS if key.level == words[1] and key.name == words[2]]
    return []


def render(keys: list[MapKey], url: str = "") -> str:
    """The text ``karni explain map...`` prints: one key in full, or a list."""
    docs = url or f"{DOCS_PAGE}.md#{DOCS_ANCHOR}"
    if len(keys) <= 3:
        blocks = [
            "\n".join(
                [
                    f'"{key.name}"  (a content map key: {LEVELS[key.level].lower()})',
                    "",
                    f"Write:  {key.syntax}",
                    f"What:   {key.text}",
                ]
            )
            for key in keys
        ]
        return "\n\n".join([*blocks, f"Docs:   {docs}"])
    lines = [
        "The content map (karni design analyze --map writes a draft, karni design extract reads it)."
    ]
    for level, what in LEVELS.items():
        found = [key for key in keys if key.level == level]
        if found:
            path = "map.<key>" if level == "map" else f"map.{level}.<key>"
            lines += ["", f"{what} ({path}):"]
            lines += [f"  {key.name:<10} {key.syntax}" for key in found]
    lines += ["", "karni explain map.<key> says what one does.", f"Docs:   {docs}"]
    return "\n".join(lines)


def _cell(text: str) -> str:
    """A table cell: ``<`` and ``>`` outside code spans as entities, every pipe escaped."""
    parts = text.split("`")
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("<", "&lt;").replace(">", "&gt;")
    return "`".join(parts).replace("|", "\\|")


def markdown() -> list[str]:
    """The tables docs/design-content.md shows: one per level, every key as here."""
    lines: list[str] = []
    for level, what in LEVELS.items():
        lines += [f"**{what}.**", "", "| Key | Write | What it does |", "| --- | --- | --- |"]
        for key in KEYS:
            if key.level == level:
                lines.append(f"| `{key.name}` | {_cell(f'`{key.syntax}`')} | {_cell(key.text)} |")
        lines.append("")
    return lines[:-1]
