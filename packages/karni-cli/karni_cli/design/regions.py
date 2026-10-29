"""What a content map reads into rows, as elements of the pages: ``karni import design --map``.

``karni design analyze --map`` writes a map of the content that repeats: the
items of a list (the cards on a page), and the values of a model's detail
pages (a title, an image, a gallery). Once ``karni design extract`` and
``karni load`` put that content in rows, the templates loop over the rows
and render each value from its row. A block over the same text would be a
second copy the client could edit, and the page would never show it. So
``karni import design --editable --map <file>`` leaves those elements
without blocks: the client edits the rows in the admin, and everything else
on the page (its headings, its own text and images) stays a block.

:func:`row_regions` reads a map the way extract reads it (the same
selectors, scoped the same way) and returns, per page, the start offsets of
the elements to leave alone:

* a source with ``items``: every item, inside each ``within`` parent when
  given;
* a source without (the page is the item, as on a detail page): every
  element one of its values reads, a relation's links and a child model's
  rows included. A value read from the page itself (``:scope``, ``@attr``,
  ``body``) leaves nothing out.

:func:`detail_pages` names the pages that are one model's detail pages (a
source with two or more ``pages`` and no ``items``). They become one template
with a slug, so what stays a block on them (the copy every detail page
shares, "From past classes") gets one key per place, named after the model,
on every one of those pages: the template that replaces them keeps it.

Override / escape hatch: edit the map (delete a source, and the import makes
its markup editable again), or import without ``--map``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from karni_cli.design.parse import Document, Node
from karni_cli.design.select import SelectorError, parse_place

__all__ = ["detail_pages", "row_regions"]

#: Elements that are the whole page: a value read from one leaves nothing out.
_WHOLE_PAGE = frozenset({"html", "head", "body"})


def _places(values: Mapping[str, Any]) -> Iterable[str]:
    for rule in values.values():
        if isinstance(rule, Mapping):
            yield str(rule.get("select", ":scope"))
        else:
            yield str(rule)


def _nodes(place: str, root: Node, source: str) -> list[Node]:
    try:
        return parse_place(place).nodes(root, source)
    except SelectorError:
        return []  # extract reports a selector it cannot read: the import only leaves less out


def row_regions(
    spec: Mapping[str, Any], docs: Mapping[str, tuple[str, Document]]
) -> dict[str, set[int]]:
    """Page path → start offsets of the elements the map ``spec`` reads into rows.

    ``docs`` holds each page's text and parsed document. A page the map names
    that ``docs`` lacks is skipped.
    """
    found: dict[str, set[int]] = {}
    for model in spec.get("models", []) or []:
        if not isinstance(model, Mapping) or model.get("parent"):
            continue  # a child model's rows are read inside its parent's items or pages
        for source in model.get("sources", []) or []:
            if not isinstance(source, Mapping):
                continue
            pages = (
                [str(source["page"])]
                if source.get("page")
                else [str(p) for p in source.get("pages", []) or []]
            )
            for page in pages:
                if page not in docs:
                    continue
                text, doc = docs[page]
                scopes = (
                    _nodes(str(source["within"]), doc.root, text)
                    if source.get("within")
                    else [doc.root]
                )
                starts = found.setdefault(page, set())
                for scope in scopes:
                    if source.get("items"):
                        starts.update(n.start for n in _nodes(str(source["items"]), scope, text))
                        continue
                    for place in _places(source.get("values") or {}):
                        starts.update(
                            n.start
                            for n in _nodes(place, scope, text)
                            if n is not scope and n.tag not in _WHOLE_PAGE
                        )
    return {page: starts for page, starts in found.items() if starts}


def detail_pages(spec: Mapping[str, Any]) -> dict[str, str]:
    """Page path → the model whose detail page it is, for the map ``spec``."""
    found: dict[str, str] = {}
    for model in spec.get("models", []) or []:
        if not isinstance(model, Mapping) or model.get("parent") or not model.get("name"):
            continue
        for source in model.get("sources", []) or []:
            if not isinstance(source, Mapping) or source.get("items"):
                continue
            pages = [str(p) for p in source.get("pages", []) or []]
            if len(pages) < 2:
                continue
            for page in pages:
                found.setdefault(page, str(model["name"]))
    return found
