"""A design's content as a ``karni load`` file, read with a map: ``karni design extract``.

``karni design analyze --map design-map.json`` writes the map, and the agent
edits it: model and field names, which structure is which model, which
element is which field. This module reads the pages with it and writes the
content in the format :mod:`karni.transfer.loading` loads, image paths
relative to the output file. Nothing is retyped and nothing is made up.

The map (JSON)::

    {
      "version": 1,
      "design": "../design",            # the design folder, relative to the map file
      "app": "website",                 # rows go to "<app>.<Model>"
      "marker": "==",                   # around highlighted words: KARNI_SITE_HIGHLIGHT's marker
      "models": [
        {
          "name": "Course",
          "fields": {"slug": "slug:title", "title": "str:80", "price": "money:USD", ...},
          "key": "slug",                # the field each row is matched on
          "highlight": {"tagline": "em"},  # fields that keep ==marked== words
          "sources": [
            {
              "pages": ["courses/pottery.html", ...],  # or "page": "courses.html"
              "items": "li.course-list__item",          # absent: the page is the item
              "within": "section.menu",                 # items are inside these parents
              "parent": {"field": "menu", "key": {...}},  # ...and the row points at its parent
              "key": {"from": "page"},                  # how each item's key is read
              "position": true,                         # write the item's place in its list
              "create": false,                          # only add values to rows made elsewhere
              "set": {"page": "home"},                  # constant values ({page}: the page's key)
              "values": {"title": "h1", "image": "img@src", ...}
            }
          ]
        },
        {"name": "CourseImage", "parent": "Course", "accessor": "courseimage_set",
         "fields": {...}, "key": "position"}
      ]
    }

A *place* is a CSS selector relative to the item, with ``@attribute`` for an
attribute's value (``img@src``), ``@data-tags`` for the item's own attribute
and ``:scope`` for the item's own text (:mod:`karni_cli.design.select`).

Keys (``"key"``):

* ``{"from": "page"}``: the page's file name (``courses/pottery.html`` →
  ``pottery``).
* ``{"from": "link", "select": place, "strip": "p-"}``: the page or
  ``#anchor`` a link points at.
* ``{"from": "attr", "name": "id", "strip": "p-"}``: an attribute of the item.
* ``{"from": "field", "field": "title"}``: a field's value as a slug.
* ``{"from": "position", "prefix": "home"}``: ``home-1``, ``home-2`` and so on
  (``{page}`` in the prefix is the page's key).

The same item read from two sources gets one key, so its values merge into
one row: the first source that has a value wins.

A value is a place, or an object with ``select`` (the place) and one of:

* ``all``: every match's text, joined by blank lines (paragraphs).
* ``list``: a JSON list, one entry per match (``true``: the match's text,
  a place: that place inside each match).
* ``fields``: a list of objects, ``{name: place}`` inside each match.
* ``pairs``: a definition list as ``[term, definition]`` pairs.
* ``to``: a relation to that model. The place names the row by a link (an
  ``href``), by its key (``"by": "key"``, an attribute such as
  ``data-type="houses"``) or by its title (``"by": "title"``). ``many`` makes
  it a list, ``split`` reads an attribute that holds several keys
  (``data-tags="a b"``).
* ``rows``: child rows, ``{field: place}`` inside each match (the value's
  name is the parent's accessor, ``courseimage_set``).
* ``present``: ``true`` when the place matches anything.
* ``drop``: markup left out of the text (``["span.arrow"]``).
* ``pattern``: a regular expression whose last group is the value
  (``01 — Design`` → ``Design``).
* ``link``: ``"path"`` writes a link to a page of the design as its URL path.
* ``decide``: a question the analysis left for the agent. Extract refuses to
  run until every ``decide`` is answered (removed, or the value deleted).

The value is parsed by the field's type: a number from ``"12 weeks"``, an
amount from ``"€4.50"``, a date from ``"14 March 2026"`` or a ``datetime``
attribute, a path for an image.

Override / escape hatch: :func:`extract` takes ``reader=``, a
:class:`Reader` subclass, to read values another way.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any, Final

from karni_cli.design import site as design_site
from karni_cli.design.analyze import attr_key, link_key, page_slug, parse_value
from karni_cli.design.parse import Document, Node, collapse, parse
from karni_cli.design.rewrite import Mapped, page_route
from karni_cli.design.select import Place, SelectorError, parse_place
from karni_cli.design.values import HIGHLIGHT_MARKER, slugify, text_of

__all__ = ["ExtractResult", "MapError", "Reader", "extract", "read_map"]

MAP_VERSION: Final = 1
_SOURCE_KEYS: Final = frozenset(
    {"page", "pages", "items", "within", "parent", "key", "position", "create", "set", "values"}
)
_VALUE_KEYS: Final = frozenset(
    {
        "select",
        "all",
        "list",
        "fields",
        "pairs",
        "to",
        "many",
        "split",
        "by",
        "rows",
        "present",
        "drop",
        "pattern",
        "link",
        "decide",
    }
)


class MapError(ValueError):
    """The map cannot be used: what is wrong and where. ``pending`` lists open decisions."""

    def __init__(self, message: str, *, pending: list[str] | None = None) -> None:
        super().__init__(message)
        self.pending = list(pending or [])


def read_map(path: Path) -> dict[str, Any]:
    """The map file at ``path``, checked for its shape (see the module docstring)."""
    if not path.is_file():
        raise MapError(
            f"{path}: no such file. Write one with karni design analyze <design> --map {path}."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MapError(f"{path}: not valid JSON at line {exc.lineno}: {exc.msg}.") from exc
    check_map(data, str(path))
    return data


def check_map(data: Any, where: str = "the map") -> None:
    """Raise :class:`MapError` for anything extract cannot follow, decisions left open first."""
    if not isinstance(data, Mapping) or not isinstance(data.get("models"), list):
        raise MapError(f'{where}: the map is an object with a "models" list.')
    marker = data.get("marker", HIGHLIGHT_MARKER)
    if not isinstance(marker, str) or not marker.strip() or marker != marker.strip():
        raise MapError(
            f'{where}: "marker" is the text around highlighted words, such as "==" (the '
            f"default, KARNI_SITE_HIGHLIGHT's), not {marker!r}."
        )
    if data.get("version", MAP_VERSION) != MAP_VERSION:
        raise MapError(
            f"{where}: map version {data.get('version')!r}, this karni reads {MAP_VERSION}."
        )
    names = {str(m.get("name")) for m in data["models"] if isinstance(m, Mapping)}
    pending: list[str] = []
    problems: list[str] = []
    for model in data["models"]:
        if not isinstance(model, Mapping) or not model.get("name"):
            problems.append('every model is an object with a "name".')
            continue
        name = str(model["name"])
        fields = model.get("fields")
        if not isinstance(fields, Mapping):
            problems.append(f'{name}: "fields" maps field names to types.')
            continue
        if model.get("parent") and str(model["parent"]) not in names:
            problems.append(f"{name}: parent {model['parent']!r} is not a model of the map.")
        accessors = {
            str(m.get("accessor"))
            for m in data["models"]
            if isinstance(m, Mapping) and m.get("parent") == name and m.get("accessor")
        }
        for index, source in enumerate(model.get("sources", []) or [], start=1):
            label = f"{name} source {index}"
            if not isinstance(source, Mapping):
                problems.append(f"{label}: a source is an object.")
                continue
            unknown = set(source) - _SOURCE_KEYS
            if unknown:
                problems.append(f"{label}: unknown key(s) {', '.join(sorted(unknown))}.")
            if not source.get("page") and not source.get("pages"):
                problems.append(f'{label}: give "page" or "pages".')
            for place_name in ("items", "within"):
                if source.get(place_name):
                    _check_selector(str(source[place_name]), f"{label} {place_name}", problems)
            for value_name, rule in (source.get("values") or {}).items():
                where_ = f"{name}.{value_name} ({label})"
                if value_name not in fields and value_name not in accessors:
                    problems.append(
                        f"{where_}: not a field of {name} (fields: {', '.join(fields)})."
                    )
                if isinstance(rule, Mapping):
                    if rule.get("decide"):
                        pending.append(f"{where_}: {rule['decide']}")
                    extra = set(rule) - _VALUE_KEYS
                    if extra:
                        problems.append(f"{where_}: unknown option(s) {', '.join(sorted(extra))}.")
                    target = rule.get("to")
                    if target and str(target) not in names:
                        problems.append(
                            f"{where_}: relation to {target!r}, not a model of the map."
                        )
                    place = str(rule.get("select", ":scope"))
                else:
                    place = str(rule)
                try:
                    parse_place(place)
                except SelectorError as exc:
                    problems.append(f"{where_}: {exc}")
    if problems:
        listed = "\n".join(f"  - {problem}" for problem in problems)
        raise MapError(f"{where}: {len(problems)} problem(s):\n{listed}")
    if pending:
        listed = "\n".join(f"  - {item}" for item in pending)
        raise MapError(
            f"{where}: {len(pending)} decision(s) left. Answer each one in the map: remove the "
            f'"decide" to keep the value, or delete the value (and the field).\n{listed}',
            pending=pending,
        )


def _check_selector(text: str, where: str, problems: list[str]) -> None:
    try:
        parse_place(text)
    except SelectorError as exc:
        problems.append(f"{where}: {exc}")


@dataclass
class ExtractResult:
    """The content (``"app.Model"`` → rows) and what extract noticed."""

    content: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {label: len(rows) for label, rows in self.content.items()}

    def render(self, output: str) -> str:
        lines = [f"Wrote {output}:"]
        width = max((len(label) for label in self.content), default=0)
        for label, rows in self.content.items():
            children = sum(
                len(value)
                for row in rows
                for name, value in row.items()
                if name.endswith("_set") and isinstance(value, list)
            )
            extra = f" ({children} child row(s))" if children else ""
            lines.append(f"  {label:<{width}}  {len(rows)} row(s){extra}")
        if self.problems:
            lines.append(f"Check ({len(self.problems)}):")
            lines.extend(f"  - {problem}" for problem in self.problems)
        return "\n".join(lines)


@dataclass
class _Ref:
    """A relation value waiting for every row to exist: the raw names and how to read them."""

    model: str
    key: str
    field: str
    target: str
    raw: list[str]
    page: str
    many: bool
    by: str
    split: bool


class Reader:
    """Reads values out of the design's pages for :func:`extract`.

    Override / escape hatch: subclass it and pass ``reader=`` to
    :func:`extract`, for a value the map's options do not cover (override
    :meth:`text` or :meth:`value`).
    """

    def __init__(
        self, design: Path, output: Path, mapped: Mapped, marker: str = HIGHLIGHT_MARKER
    ) -> None:
        self.design = design
        self.output = output
        self.mapped = mapped
        #: What goes around highlighted words: the map's "marker", "==" by default.
        self.marker = marker
        self.docs: dict[str, tuple[str, Document]] = {}
        self.problems: list[str] = []

    def page(self, path: str) -> tuple[str, Document]:
        if path not in self.docs:
            file = self.design / path
            if not file.is_file():
                raise MapError(f"{path}: not a page of the design {self.design}.")
            text = file.read_bytes().decode("utf-8-sig", errors="surrogateescape")
            self.docs[path] = (text, parse(text))
        return self.docs[path]

    def nodes(self, root: Node, place: Place, source: str) -> list[Node]:
        return place.nodes(root, source)

    def text(self, node: Node, source: str, *, highlight: bool, drop: Iterable[str] = ()) -> str:
        return text_of(node, source, highlight=highlight, drop=drop, marker=self.marker)[0]

    def raw(
        self, node: Node, place: Place, source: str, rule: Mapping[str, Any], highlight: bool
    ) -> str:
        """One element's value as written: an attribute, or its text."""
        if place.attribute:
            value = node.attr(source, place.attribute)
            if value is None:
                return ""
            if place.attribute == "style":
                found = re.search(r"""url\(\s*(["']?)([^"')]+)\1\s*\)""", value)
                return found.group(2) if found else ""
            return value.strip()
        text = self.text(node, source, highlight=highlight, drop=rule.get("drop", ()))
        pattern = rule.get("pattern")
        if pattern:
            match = re.match(str(pattern), text, re.DOTALL)
            if match and match.lastindex:
                text = match.group(match.lastindex)
        return text

    def image(self, value: str, page: str) -> str:
        """An image path as the content file names it: relative to the output file."""
        if not value:
            return ""
        ref = self.mapped.resolve(unescape(value), posixpath.dirname(page))
        if ref.kind == "external":
            self.problems.append(f"{page}: the image {value!r} is on another site, not loaded.")
            return ""
        target = self.design / (ref.path or value)
        if not target.is_file():
            self.problems.append(f"{page}: the image {value!r} is not in the design.")
            return ""
        return Path(os.path.relpath(target.resolve(), self.output.parent.resolve())).as_posix()

    def link(self, value: str, page: str) -> str:
        """A link as a URL path when it reaches a page of the design, else as written."""
        ref = self.mapped.resolve(unescape(value), posixpath.dirname(page))
        if ref.kind == "page":
            target = self.mapped.redirects.get(ref.path, ref.path)
            return "/" + page_route(target) + ref.query + ref.fragment
        return value


class _Extractor:
    def __init__(self, spec: Mapping[str, Any], reader: Reader) -> None:
        self.spec = spec
        self.reader = reader
        self.models = {str(m["name"]): m for m in spec["models"]}
        self.rows: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in self.models}
        self.refs: list[_Ref] = []
        self.child_refs: list[tuple[str, dict[str, Any], _Ref]] = []

    # keys

    def strips(self, model: str) -> list[str]:
        """Prefixes a model's keys lose (``p-``), from its sources' key rules."""
        found: list[str] = []
        for source in self.models.get(model, {}).get("sources", []) or []:
            strip = (source.get("key") or {}).get("strip")
            if strip and strip not in found:
                found.append(str(strip))
        return found

    def key(self, rule: Mapping[str, Any], item: Node, page: str, source: str, index: int) -> str:
        how = str(rule.get("from", "position"))
        strip = str(rule.get("strip") or "")
        if how == "page":
            return page_slug(page)
        if how == "link":
            place = parse_place(str(rule.get("select") or "@href"))
            nodes = place.nodes(item, source)
            value = nodes[0].attr(source, place.attribute or "href") if nodes else None
            if not value:
                return ""
            ref = self.reader.mapped.resolve(unescape(value), posixpath.dirname(page))
            return slugify(link_key(ref, strip))
        if how == "attr":
            value = item.attr(source, str(rule.get("name", "id"))) or ""
            return slugify(attr_key(value.strip(), strip))
        if how == "field":
            return ""  # filled from the field's value once read
        prefix = str(rule.get("prefix", "row")).replace("{page}", page_slug(page))
        return f"{prefix}-{index}"

    # values

    def value(
        self,
        model: Mapping[str, Any],
        name: str,
        rule: Any,
        item: Node,
        page: str,
        source: str,
    ) -> Any:
        options: Mapping[str, Any] = rule if isinstance(rule, Mapping) else {"select": rule}
        place = parse_place(str(options.get("select", ":scope")))
        nodes = self.reader.nodes(item, place, source)
        kind = str(model["fields"].get(name, "json"))
        base = kind.rstrip("?").split(":", 1)[0]
        highlight = name in (model.get("highlight") or {})
        if options.get("present"):
            return bool(nodes)
        if options.get("to"):
            raws: list[str] = []
            for node in nodes:
                raw = self.reader.raw(node, place, source, options, highlight=False)
                if options.get("split"):
                    raws.extend(raw.split())
                elif raw:
                    raws.append(raw)
            return _Ref(
                str(model["name"]),
                "",
                name,
                str(options["to"]),
                raws,
                page,
                bool(options.get("many") or options.get("split") or base == "m2m"),
                str(options.get("by", "")),
                bool(options.get("split")),
            )
        if options.get("pairs"):
            pairs: list[list[str]] = []
            for node in nodes:
                term = ""
                for element in node.iter_elements():
                    if element.tag == "dt":
                        if term:
                            pairs.append([term, ""])
                        term = self.reader.text(element, source, highlight=False)
                    elif element.tag == "dd":
                        pairs.append([term, self.reader.text(element, source, highlight=False)])
                        term = ""
                if term:
                    pairs.append([term, ""])
            return pairs
        if "list" in options:
            inner = options["list"]
            found: list[str] = []
            for node in nodes:
                if inner is True:
                    text = self.reader.text(node, source, highlight=False)
                else:
                    inner_place = parse_place(str(inner))
                    hits = inner_place.nodes(node, source)
                    text = self.reader.raw(hits[0], inner_place, source, {}, False) if hits else ""
                if text:
                    found.append(text)
            return found
        if "fields" in options:
            objects: list[dict[str, str]] = []
            for node in nodes:
                entry: dict[str, str] = {}
                for field_name, inner in (options.get("fields") or {}).items():
                    inner_place = parse_place(str(inner))
                    hits = inner_place.nodes(node, source)
                    entry[str(field_name)] = (
                        self.reader.raw(hits[0], inner_place, source, {}, False) if hits else ""
                    )
                objects.append(entry)
            return objects
        if not nodes:
            return None
        if options.get("all"):
            texts = [self.reader.raw(node, place, source, options, highlight) for node in nodes]
            return parse_value("text", kind, "\n\n".join(t for t in texts if t))
        raw = self.reader.raw(nodes[0], place, source, options, highlight)
        if base == "image":
            return self.reader.image(raw, page)
        if options.get("link") == "path" or (place.attribute == "href" and base == "str"):
            return self.reader.link(raw, page)
        if base == "bool":
            return True
        if base in ("datetime",):
            return raw or None
        return parse_value("text", kind.rstrip("?"), raw)

    def children(
        self,
        model: Mapping[str, Any],
        accessor: str,
        rule: Mapping[str, Any],
        item: Node,
        page: str,
        source: str,
    ) -> list[dict[str, Any]]:
        child = next(
            (
                m
                for m in self.models.values()
                if m.get("parent") == model["name"] and m.get("accessor") == accessor
            ),
            None,
        )
        if child is None:
            raise MapError(f"{model['name']}.{accessor}: no model with this parent and accessor.")
        place = parse_place(str(rule.get("select", ":scope")))
        rows: list[dict[str, Any]] = []
        for index, node in enumerate(place.nodes(item, source), start=1):
            row: dict[str, Any] = {}
            for name, inner in (rule.get("rows") or {}).items():
                value = self.value(child, str(name), inner, node, page, source)
                if isinstance(value, _Ref):
                    self.child_refs.append((str(child["name"]), row, value))
                elif value not in (None, "", []):
                    row[str(name)] = value
            if "position" in child.get("fields", {}):
                row["position"] = index
            rows.append(row)
        return rows

    # the run

    def run(self) -> None:
        # Sources that create rows first, then those that only add values to them.
        for creating in (True, False):
            for model in self.spec["models"]:
                if model.get("parent"):
                    continue
                for source_spec in model.get("sources", []) or []:
                    if bool(source_spec.get("create", True)) is creating:
                        self.source(model, source_spec)
        self.relations()

    def source(self, model: Mapping[str, Any], spec: Mapping[str, Any]) -> None:
        pages = [str(spec["page"])] if spec.get("page") else [str(p) for p in spec.get("pages", [])]
        name = str(model["name"])
        rows = self.rows[name]
        create = spec.get("create", True)
        key_rule = spec.get("key") or {"from": "position", "prefix": slugify(name)}
        for page in pages:
            text, doc = self.reader.page(page)
            root = doc.root
            parents: list[tuple[Node | None, int]] = [(None, 0)]
            if spec.get("within"):
                parents = [
                    (node, index)
                    for index, node in enumerate(
                        parse_place(str(spec["within"])).nodes(root, text), start=1
                    )
                ]
                if not parents:
                    self.reader.problems.append(
                        f"{name}: {spec['within']!r} finds nothing on {page}."
                    )
            for parent_node, parent_index in parents:
                scope = parent_node if parent_node is not None else root
                if spec.get("items"):
                    items = parse_place(str(spec["items"])).nodes(scope, text)
                    if not items and parent_node is None:
                        self.reader.problems.append(
                            f"{name}: {spec['items']!r} finds nothing on {page}."
                        )
                else:
                    items = [scope]
                for index, item in enumerate(items, start=1):
                    self.item(
                        model,
                        spec,
                        key_rule,
                        item,
                        page,
                        text,
                        index,
                        parent_node,
                        parent_index,
                        rows,
                        create,
                    )

    def item(
        self,
        model: Mapping[str, Any],
        spec: Mapping[str, Any],
        key_rule: Mapping[str, Any],
        item: Node,
        page: str,
        text: str,
        index: int,
        parent_node: Node | None,
        parent_index: int,
        rows: dict[str, dict[str, Any]],
        create: bool,
    ) -> None:
        name = str(model["name"])
        values: dict[str, Any] = {}
        refs: list[_Ref] = []
        for field_name, rule in (spec.get("values") or {}).items():
            if isinstance(rule, Mapping) and rule.get("rows") is not None:
                values[str(field_name)] = self.children(
                    model, str(field_name), rule, item, page, text
                )
                continue
            value = self.value(model, str(field_name), rule, item, page, text)
            if isinstance(value, _Ref):
                refs.append(value)
            elif value is not None and value != "":
                values[str(field_name)] = value
        key = self.key(key_rule, item, page, text, index)
        if key_rule.get("from") == "field":
            key = slugify(str(values.get(str(key_rule.get("field", "title")), "")))
        if not key:
            self.reader.problems.append(
                f"{name}: an item on {page} has no key, so it was left out."
            )
            return
        row = rows.get(key)
        if row is None:
            if not create:
                return
            row = rows[key] = {str(model.get("key", "slug")): key}
        if spec.get("position") and "position" in model["fields"]:
            row.setdefault("position", index)
        for field_name, constant in (spec.get("set") or {}).items():
            row.setdefault(str(field_name), str(constant).replace("{page}", page_slug(page)))
        parent = spec.get("parent")
        if parent and parent_node is not None:
            parent_key = self.key(parent.get("key") or {}, parent_node, page, text, parent_index)
            row.setdefault(str(parent["field"]), parent_key)
        for field_name, value in values.items():
            if row.get(field_name) in (None, "", []):
                row[field_name] = value
            elif row[field_name] != value and not isinstance(value, list):
                self.reader.problems.append(
                    f"{name} {key!r}: {field_name} keeps {_short(row[field_name])!r}, read "
                    f"first. {page} shows {_short(value)!r}."
                )
        for ref in refs:
            ref.key = key
            self.refs.append(ref)

    def relations(self) -> None:
        for ref in self.refs:
            row = self.rows[ref.model].get(ref.key)
            if row is None:
                continue
            resolved = self.resolve(ref)
            if ref.many:
                if not row.get(ref.field):
                    row[ref.field] = resolved
            elif row.get(ref.field) in (None, ""):
                row[ref.field] = resolved[0] if resolved else None
        for _, row, ref in self.child_refs:
            resolved = self.resolve(ref)
            row[ref.field] = resolved if ref.many else (resolved[0] if resolved else None)

    def resolve(self, ref: _Ref) -> list[str]:
        target = self.rows.get(ref.target, {})
        found: list[str] = []
        for raw in ref.raw:
            key = self.name_of(ref, raw, target)
            if key is None:
                self.reader.problems.append(
                    f"{ref.model} {ref.key!r}: {ref.field} names {raw!r} on {ref.page}, which is "
                    f"not a {ref.target} row. Left out."
                )
            elif key not in found:
                found.append(key)
        return found

    def name_of(self, ref: _Ref, raw: str, target: Mapping[str, dict[str, Any]]) -> str | None:
        if ref.by == "title":
            wanted = collapse(raw).casefold()
            return next(
                (
                    key
                    for key, row in target.items()
                    if collapse(str(row.get("title", ""))).casefold() == wanted
                ),
                None,
            )
        candidates: list[str] = []
        if ref.split or ref.by == "key":
            candidates.append(raw)
            candidates.extend(attr_key(raw, strip) for strip in self.strips(ref.target))
        else:
            mapped = self.reader.mapped.resolve(unescape(raw), posixpath.dirname(ref.page))
            for strip in [*self.strips(ref.target), ""]:
                candidates.append(link_key(mapped, strip))
            if mapped.kind == "page":
                candidates.append(page_slug(mapped.path))
        for candidate in candidates:
            slug = slugify(candidate)
            if slug in target:
                return slug
        return None

    # the content file

    def content(self) -> dict[str, list[dict[str, Any]]]:
        app = str(self.spec.get("app") or "website")
        out: dict[str, list[dict[str, Any]]] = {}
        for model in self.spec["models"]:
            if model.get("parent"):
                continue
            name = str(model["name"])
            rows = list(self.rows[name].values())
            if model.get("order") == "position" or "position" in model["fields"]:
                rows.sort(key=lambda row: (row.get("position") is None, row.get("position") or 0))
            fields = model["fields"]
            if "position" in fields:
                last = max((int(row["position"]) for row in rows if "position" in row), default=0)
                for row in rows:
                    if "position" not in row:
                        last += 1
                        row["position"] = last
            for row in rows:
                for field_name, kind in fields.items():
                    optional = str(kind).endswith("?")
                    base = str(kind).rstrip("?").split(":", 1)[0]
                    if optional or field_name in row or base in ("bool", "json", "m2m", "slug"):
                        continue
                    self.reader.problems.append(
                        f"{name} {row.get('slug')!r}: no value for {field_name}, which the model "
                        "requires. Make it optional (add ? to the field) or give it a value."
                    )
            out[f"{app}.{name}"] = rows
        return out


def _short(value: Any) -> str:
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "..."


def extract(
    design: Path,
    spec: Mapping[str, Any],
    output: Path,
    *,
    reader: type[Reader] = Reader,
) -> ExtractResult:
    """The content of ``design`` read with the map ``spec``, for a file at ``output``.

    :raises MapError: the map is not usable or has decisions left.
    """
    check_map(spec)
    texts, files = design_site.scan(design)
    if not texts:
        raise MapError(f"{design} has no .html page.")
    _, mapped = design_site._read_pages(texts, files, str(spec.get("app") or "website"))
    marker = str(spec.get("marker") or HIGHLIGHT_MARKER)
    extractor = _Extractor(spec, reader(design, output, mapped, marker))
    extractor.run()
    content = extractor.content()
    return ExtractResult(content, extractor.reader.problems)
