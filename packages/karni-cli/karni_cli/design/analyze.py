"""Which content repeats in a design, as models: ``karni design analyze``.

A designer's pages hold the site's content as markup: six cards for six
services, a project with its gallery, a page per doctor. This module reads
that markup and proposes the models that hold it, from the markup alone.
Every name comes from the design (a class, a heading, a page or folder),
never from a list of expected names.

How it reads a design:

1. **Pages.** Each page is parsed (:mod:`karni_cli.design.parse`) and the
   markup every page shares (the header, the footer) is set aside
   (:func:`karni_cli.design.compare.layout`): it is the layout, not content.
   The rest of each page is scanned (:mod:`karni_cli.design.scan`) into
   values at paths and *collections*: structures repeated two or more times.
2. **Detail pages.** Pages that one list links to item by item (each card
   to its own page), or the pages of one folder, that share a structure are
   one model's detail pages. The values that differ between them are the
   model's fields. What they share is the template.
3. **Sources.** A source is a list on a page, the set of a model's detail
   pages, or a list nested inside the items of another source (a project's
   gallery, the projects a service page shows).
4. **The same items.** Two sources hold the same items when their items
   point at each other: a card links to a detail page, a link's ``#anchor``
   is a list item's ``id``, a ``data-`` key or a title is the same. Sources
   that hold the same items are one model, and their fields merge: a field
   with the same value for every item is one field.
5. **Relations.** A list nested in another model's items that holds a
   model's items is a relation: a foreign key when each item sits under
   one parent, a many-to-many field otherwise. An attribute whose tokens are
   another model's keys (``data-tags="houses interiors"``) is one too. A
   list of other items on a detail page, and a page that shows some of a
   model's items, are flagged for the agent to decide: a hand-picked list
   (a field) or one a query derives (nothing to store).
6. **One more row.** A single block styled on its own (a founder's card
   above the team's cards) that holds the values a list's items hold is
   proposed as one more row, with a flag named after its class, as a
   decision.
7. **What stays markup.** Lists that hold one or two short values on one
   page (opening hours, a row of statistics) stay in the template, as page
   copy. Nested lists without images become JSON fields, nested lists with
   images child models. A structure found on several pages with different
   items each time (a slider) is one model with a ``page`` field.

The result is an :class:`Analysis`: the models with their fields, types and
relations, ready-to-run ``karni make model`` commands, the decisions left to
the agent, and a draft content map for ``karni design extract``.

Override / escape hatch: the map is a file the agent edits (names, fields,
selectors, keys), and :func:`analyze` takes ``classes=`` to swap the
:class:`Namer` that names models and fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from karni_cli.design.builder import (
    _Builder,
)
from karni_cli.design.proposal import (
    Decision,
    Model,
    Namer,
    PageCopy,
    infer_type,
    parse_value,
)
from karni_cli.design.scan import Hint, hints_of
from karni_cli.design.sources import (
    Page,
    _scan_page,
    attr_key,
    build_sources,
    find_families,
    link_key,
    page_slug,
    read_design,
)

__all__ = [
    "Analysis",
    "Model",
    "Namer",
    "analyze",
    "attr_key",
    "infer_type",
    "link_key",
    "page_slug",
    "parse_value",
]

MAP_VERSION: Final = 1


# --- the analysis --------------------------------------------------------------


def _shell(token: str) -> str:
    return f"'{token}'" if any(ch in token for ch in "?|*$ &;<>()") else token


@dataclass
class Analysis:
    """What :func:`analyze` found: models, decisions, page copy, commands and the draft map."""

    design: str
    app: str
    pages: list[Page]
    models: list[Model]
    decisions: list[Decision]
    page_copy: list[PageCopy]
    notes: list[str] = field(default_factory=list)

    def commands(self) -> list[str]:
        """``karni make model`` commands, each model after the models it points at."""
        lines: list[str] = []
        later: list[Model] = []
        for model in self.models:
            tokens = [f.token for f in model.columns if not f.decide and not f.later]
            lines.append(self._command(model, tokens))
            if any(f.later for f in model.columns):
                later.append(model)
        for model in later:
            tokens = [f.token for f in model.columns if not f.decide]
            lines.append(self._command(model, tokens) + " --force")
        return lines

    def _command(self, model: Model, tokens: list[str]) -> str:
        args = " ".join(_shell(token) for token in tokens)
        extra = ""
        if model.field_named("position") is not None:
            extra += " --order position"
        if model.kind == "child":
            extra += " --key position"
        return f"karni make model {model.name} {args} --app {self.app}{extra}"

    def to_dict(self) -> dict[str, Any]:
        """The analysis as stable JSON: models, decisions, page copy, commands and the map."""
        return {
            "version": MAP_VERSION,
            "design": self.design,
            "app": self.app,
            "pages": [page.path for page in self.pages],
            "models": [_model_dict(model) for model in self.models],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "page_copy": [
                {"page": c.where, "items": c.step, "count": c.items, "reason": c.reason}
                for c in self.page_copy
            ],
            "commands": self.commands(),
            "notes": list(self.notes),
            "map": self.draft_map(),
        }

    def draft_map(self, design: str | None = None) -> dict[str, Any]:
        """The content map ``karni design extract`` reads (see :mod:`karni_cli.design.extract`)."""
        return {
            "version": MAP_VERSION,
            "design": design if design is not None else self.design,
            "app": self.app,
            "models": [_model_map(model) for model in self.models],
        }

    def render(self) -> str:
        """The analysis for a person: models with fields and examples, decisions, commands."""
        lines = [
            (
                f"Design {self.design}: {len(self.pages)} page(s), {len(self.models)} model(s) "
                "proposed from the markup."
            )
        ]
        for model in self.models:
            lines.append("")
            lines.extend(_render_model(model))
        if self.decisions:
            lines.append("")
            lines.append(f"Decide ({len(self.decisions)}), the markup cannot tell:")
            for index, decision in enumerate(self.decisions, start=1):
                lines.append(f"  {index}. {decision.model}.{decision.field}: {decision.question}")
                lines.append(f"     {decision.evidence}")
                lines.extend(f"     - {choice}" for choice in decision.choices)
        if self.page_copy:
            lines.append("")
            lines.append("Left in the templates (page copy, not models):")
            for copy in self.page_copy:
                lines.append(f"  - {copy.where}: {copy.step} x{copy.items}, {copy.reason}")
        if self.notes:
            lines.append("")
            lines.extend(self.notes)
        lines.append("")
        lines.append("Commands (models others point at come first):")
        lines.extend(f"  {command}" for command in self.commands())
        return "\n".join(lines)


def _model_dict(model: Model) -> dict[str, Any]:
    return {
        "name": model.name,
        "kind": model.kind,
        "rows": model.rows,
        "parent": model.parent.name if model.parent is not None else None,
        "detail_pages": [page.path for page in model.family.pages] if model.family else [],
        "shown_on": sorted({page.path for source in model.sources for page in source.pages}),
        "fields": [
            {
                "name": f.name,
                "type": f.type,
                "optional": f.optional,
                "kind": f.kind,
                "example": f.example,
                **({"to": f.target.name} if f.target is not None else {}),
                **({"decide": f.decide} if f.decide else {}),
                **({"note": f.note} if f.note else {}),
            }
            for f in model.columns
        ],
        "notes": list(model.notes),
    }


def _render_model(model: Model) -> list[str]:
    where = sorted({page.path for source in model.sources for page in source.pages})
    shown = ", ".join(where[:4]) + (f" and {len(where) - 4} more" if len(where) > 4 else "")
    kind = {
        "child": f", rows of {model.parent.name if model.parent else '?'}",
        "pages": ", a list per page",
    }.get(model.kind, "")
    lines = [f"{model.name}: {model.rows} row(s){kind}, on {shown}"]
    if model.family is not None:
        lines.append(
            f"  detail pages: {len(model.family.pages)} ({model.family.pages[0].path}, ...)"
        )
    columns = model.columns
    width = max((len(f.name) for f in columns), default=4)
    type_width = max((len(f.type) + 1 for f in columns), default=4)
    for f in columns:
        example = f.example.replace("\n", " ")
        example = example if len(example) <= 50 else example[:47] + "..."
        mark = "  (decide)" if f.decide else ""
        kind_ = f.type + ("?" if f.optional else "")
        lines.append(f"  {f.name:<{width}}  {kind_:<{type_width}}  {example}{mark}")
        if f.note:
            lines.append(f"  {'':<{width}}  {'':<{type_width}}  note: {f.note}")
    for f in model.fields:
        if f.kind == "child":
            lines.append(f"  {f.name:<{width}}  child rows ({f.name.removesuffix('_set')})")
    lines.extend(f"  note: {note}" for note in model.notes)
    return lines


def _model_map(model: Model) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": model.name}
    if model.parent is not None:
        entry["parent"] = model.parent.name
        entry["accessor"] = model.accessor
    entry["fields"] = {f.name: f.type + ("?" if f.optional else "") for f in model.columns}
    entry["key"] = "position" if model.kind == "child" else "slug"
    highlights = {f.name: f.highlight[0] for f in model.columns if f.highlight}
    if highlights:
        entry["highlight"] = highlights
    if model.kind == "child":
        return entry
    sources: list[dict[str, Any]] = []
    for binding in model.bindings:
        source = binding.source
        item: dict[str, Any] = {}
        detail_pages = source.kind == "detail" or (
            source.parent is not None and source.parent.kind == "detail"
        )
        if detail_pages:
            item["pages"] = (
                [page.path for page in source.pages]
                if source.kind == "detail"
                else [
                    page.path for page in (source.parent.pages if source.parent else source.pages)
                ]
            )
        else:
            item["page"] = source.page.path
        if binding.within:
            item["within"] = binding.within
        if binding.items is not None:
            item["items"] = binding.items
        item["key"] = binding.key
        if binding.parent:
            item["parent"] = binding.parent
        if binding.position:
            item["position"] = True
        if not binding.create:
            item["create"] = False
        if binding.constants:
            item["set"] = dict(binding.constants)
        values: dict[str, Any] = {}
        for f in model.fields:
            for rule in f.rules:
                if rule.source is not source:
                    continue
                mapped = rule.to_map()
                if f.decide:
                    mapped = {
                        **(mapped if isinstance(mapped, dict) else {"select": mapped}),
                        "decide": f.decide,
                    }
                values[f.name] = mapped
        item["values"] = values
        sources.append(item)
    entry["sources"] = sources
    return entry


def analyze(
    design: Path, app: str, *, namer: Namer | None = None, label: str | None = None
) -> Analysis:
    """Analyze the design folder ``design`` for models in ``app`` (see the module docstring)."""
    pages, mapped = read_design(design, app)
    for page in pages:
        page.found = _scan_page(page)
    families = find_families(pages, mapped)
    for family in families:
        hints: set[Hint] = set()
        for page in family.pages:
            hints |= hints_of(page.found)
        for page in family.pages:
            page.found = _scan_page(page, hints)
    sources = build_sources(pages, families)
    builder = _Builder(pages, sources, mapped, namer or Namer(), app)
    builder.run()
    return Analysis(
        label if label is not None else str(design),
        app,
        pages,
        builder.models,
        builder.decisions,
        builder.page_copy,
        builder.notes,
    )
