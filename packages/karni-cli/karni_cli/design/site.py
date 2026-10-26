"""The site app for a design: what ``karni import design`` writes, planned as data.

:func:`plan` reads a design folder and returns a :class:`SitePlan`: every
template (the layout, one per page, the partials, the error pages), the
views and routes, the redirects, the files to copy, the unused files, what
could not be mapped, and the ``.karni/design.json`` record. It touches no
project file. The command applies the plan to the project through the
generators' workspace.

How a page becomes a template:

* its ``<title>`` and ``<meta name="description">`` fill the layout's
  ``title`` and ``description`` blocks, a ``<link rel="canonical">`` is
  replaced by one built from the request, and any other ``<head>`` element
  that not every page has goes into ``{% block head %}``;
* the shared prefix and suffix of its body (see :mod:`karni_cli.design.compare`)
  live in the layout, each in a named block the page can override;
* the rest of its body is ``{% block content %}``, where a block that two or
  more pages share is an ``{% include %}`` of a partial;
* every link, path and inline script is rewritten by :mod:`karni_cli.design.rewrite`;
  everything else is the page's own bytes.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass, field
from html import escape, unescape
from pathlib import Path
from typing import Any, Final

from karni_cli.design import compare, rewrite
from karni_cli.design.compare import Block, Group, Layout, Variation
from karni_cli.design.forms import forms_in
from karni_cli.design.parse import Document, Node, parse
from karni_cli.design.rewrite import Mapped, Policy, Rewriter

__all__ = ["DESIGN_RECORD", "Redirect", "SitePlan", "plan", "scan"]

#: Where the record of an import lives in the project.
DESIGN_RECORD: Final = Path(".karni") / "design.json"
_HTML: Final = (".html", ".htm")
_SKIP_DIRS: Final = frozenset({"node_modules", "__pycache__"})
_ERROR_PAGES: Final = {"404.html": "404", "500.html": "500"}
_CSS_REF = re.compile(r"""url\(\s*(["']?)([^"')]*)\1\s*\)|@import\s+(["'])([^"']+)\3""")
_JS_STRING = re.compile(r"""["'`]([^"'`\n]{1,200}?)["'`]""")
_META_REFRESH = re.compile(r"^\s*\d+\s*;\s*url\s*=\s*['\"]?([^'\"]+)['\"]?\s*$", re.IGNORECASE)
_URL_ATTRIBUTES: Final = frozenset({"href", "src", "srcset", "imagesrcset", "poster", "action"})


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scan(design: Path) -> tuple[dict[str, str], dict[str, Path]]:
    """The pages (design path → text) and the other files (design path → file) of a folder."""
    pages: dict[str, str] = {}
    files: dict[str, Path] = {}
    for path in sorted(design.rglob("*")):
        rel = path.relative_to(design)
        if any(part.startswith(".") or part in _SKIP_DIRS for part in rel.parts):
            continue
        if not path.is_file():
            continue
        key = rel.as_posix()
        if path.suffix.lower() in _HTML:
            pages[key] = path.read_bytes().decode("utf-8-sig", errors="surrogateescape")
        else:
            files[key] = path
    return pages, files


@dataclass
class PageSource:
    """One page of the design, parsed, with what the plan learns about it."""

    path: str
    text: str
    doc: Document
    name: str = ""
    route: str = ""
    error: str = ""
    redirect: rewrite.Reference | None = None
    rewriter: Rewriter | None = None
    blocks: list[Block] = field(default_factory=list)
    tail_start: int = 0
    head_items: list[tuple[int, Node, str]] = field(default_factory=list)  # lead start, node, sig
    title: Node | None = None
    description: Node | None = None
    canonical: Node | None = None
    nodes_by_start: dict[int, Node] = field(default_factory=dict)
    token_starts: list[int] = field(default_factory=list)

    @property
    def dir(self) -> str:
        return posixpath.dirname(self.path)

    def line(self, offset: int) -> int:
        return self.text.count("\n", 0, offset) + 1


@dataclass
class Redirect:
    source: str
    route: str
    name: str
    to: str  # a view name, or an absolute URL
    external: bool = False


@dataclass
class SitePlan:
    """Everything the import writes, as data."""

    app: str
    #: template path relative to the app directory → content.
    templates: dict[str, str] = field(default_factory=dict)
    #: (view name, template name) for every page.
    views: list[tuple[str, str]] = field(default_factory=list)
    #: (route, view name) for every page.
    routes: list[tuple[str, str]] = field(default_factory=list)
    redirects: list[Redirect] = field(default_factory=list)
    #: The URLs for the page test.
    page_urls: list[str] = field(default_factory=list)
    #: design path → file, for every file to copy under static/<app>/.
    assets: dict[str, Path] = field(default_factory=dict)
    unused_assets: list[str] = field(default_factory=list)
    #: ``what: why`` lines for the report.
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: The ``.karni/design.json`` record (without the ``files`` hashes the command adds).
    design: dict[str, Any] = field(default_factory=dict)


# reading


def _normalizer(mapped: Mapped, page_dir: str) -> compare.Normalize:
    def normalize(tag: str, name: str, value: str) -> str:
        if name not in _URL_ATTRIBUTES and not name.startswith("data-"):
            return value
        if name.endswith("srcset"):
            return ",".join(
                _resolved(mapped, url, page_dir) + descriptor
                for _, url, descriptor in rewrite.srcset_parts(value)
            )
        return _resolved(mapped, value, page_dir)

    return normalize


def _resolved(mapped: Mapped, value: str, page_dir: str) -> str:
    ref = mapped.resolve(value, page_dir)
    if ref.kind in ("page", "asset"):
        return f"{ref.kind}:{ref.path}{ref.query}{ref.fragment}"
    return value


def _meta_refresh(doc: Document, text: str) -> str | None:
    for meta in doc.root.find_all("meta"):
        if (meta.attr(text, "http-equiv") or "").strip().lower() == "refresh":
            match = _META_REFRESH.match(meta.attr(text, "content") or "")
            if match:
                return match.group(1).strip()
    return None


def _read_pages(
    texts: dict[str, str], files: Iterable[str], app: str
) -> tuple[list[PageSource], Mapped]:
    """Parse every page, name the ones that get a route, find the redirects."""
    order = sorted(texts, key=lambda p: (p != "index.html", p.count("/"), p))
    pages = [PageSource(path, texts[path], parse(texts[path])) for path in order]
    mapped = Mapped(app, {}, set(files))
    taken: set[str] = set()
    for page in pages:
        page.nodes_by_start = {n.start: n for n in page.doc.root.iter() if n.kind == "element"}
        page.token_starts = [t.start for t in page.doc.tokens]
        if page.path in _ERROR_PAGES:
            page.error = _ERROR_PAGES[page.path]
            continue
        target = _meta_refresh(page.doc, page.text)
        if target is not None:
            page.redirect = rewrite.Reference(target, "pending")
            continue
        page.name = rewrite.page_view_name(page.path, taken)
        taken.add(page.name)
        page.route = rewrite.page_route(page.path)
        mapped.pages[page.path] = page.name
    for page in pages:
        if page.redirect is None:
            continue
        ref = mapped.resolve(page.redirect.raw, page.dir)
        page.redirect = ref
        if ref.kind == "page" and ref.path in mapped.pages:
            mapped.redirects[page.path] = ref.path
        page.name = rewrite.page_view_name(page.path, taken)
        taken.add(page.name)
        page.route = rewrite.page_route(page.path)
    return pages, mapped


def _read_structure(page: PageSource, mapped: Mapped) -> None:
    normalize = _normalizer(mapped, page.dir)
    page.rewriter = Rewriter(mapped, page.dir)
    container = page.doc.body_or_root()
    page.blocks, page.tail_start = compare.blocks(container, page.text, normalize)
    head = page.doc.head
    if head is None:
        return
    lead_start = head.inner[0]
    for child in head.children:
        if child.kind != "element":
            continue
        attrs = child.attrs(page.text)
        if child.tag == "title" and page.title is None:
            page.title = child
        elif (
            child.tag == "meta"
            and (attrs.get("name") or "").strip().lower() == "description"
            and page.description is None
        ):
            page.description = child
        elif (
            child.tag == "link"
            and "canonical" in (attrs.get("rel") or "").lower().split()
            and page.canonical is None
        ):
            page.canonical = child
        page.head_items.append((lead_start, child, compare.signature(child, page.text, normalize)))
        lead_start = child.end


# rendering


class _Renderer:
    def __init__(self, pages: list[PageSource], mapped: Mapped, app: str) -> None:
        self.pages = pages
        self.by_key = {page.path: page for page in pages}
        self.mapped = mapped
        self.app = app
        self.problems: list[str] = []
        self.order = [page.path for page in pages]
        self.routed = [page.path for page in pages if page.path in mapped.pages]

    def begin(self) -> None:
        """Start collecting the origins the pieces rendered from now on need."""
        self._snapshots = {
            page.path: {d: set(o) for d, o in page.rewriter.policy.sources.items()}
            for page in self.pages
            if page.rewriter is not None
        }

    def finish(self) -> Policy:
        """The origins added since :meth:`begin`, over every page."""
        delta = Policy()
        for page in self.pages:
            if page.rewriter is None:
                continue
            before = self._snapshots.get(page.path, {})
            for directive, origins in page.rewriter.policy.sources.items():
                for origin in origins - before.get(directive, set()):
                    delta.sources.setdefault(directive, set()).add(origin)
        return delta

    def patterns(self, keys: set[str]) -> list[str]:
        """``{% ifactive %}`` patterns for a set of pages: URL names, a folder as a path."""
        chosen = [key for key in self.routed if key in keys]
        found: list[str] = []
        by_dir: dict[str, list[str]] = {}
        for key in chosen:
            by_dir.setdefault(posixpath.dirname(key), []).append(key)
        for directory, members in by_dir.items():
            everything = [key for key in self.routed if posixpath.dirname(key) == directory]
            if directory and set(members) == set(everything) and len(members) > 1:
                found.append("/" + rewrite.page_route(directory + "/index.html") + "*")
            else:
                found.extend(f"{self.app}:{self.mapped.pages[key]}" for key in members)
        return found or [f"{self.app}:__none__"]

    def span(
        self,
        page: PageSource,
        start: int,
        end: int,
        variations: dict[int, Variation] | None = None,
    ) -> str:
        """The template text for ``page.text[start:end]``: rewritten tags, escaped text."""
        assert page.rewriter is not None
        tokens = page.doc.tokens
        out: list[str] = []
        index = -1
        i = bisect_left(page.token_starts, start)
        while i < len(tokens) and tokens[i].start < end:
            token = tokens[i]
            if token.kind in ("start", "startend"):
                node = page.nodes_by_start[token.start]
                index += 1
                text = page.rewriter.tag(node, page.text)
                if variations and index in variations:
                    text, problems = compare.generalize_tag(text, variations[index], self.patterns)
                    self.problems.extend(
                        f"{page.path}:{page.line(node.start)}: <{node.tag}>: {problem}"
                        for problem in problems
                    )
                out.append(text)
                if (
                    token.kind == "start"
                    and node.tag in ("script", "style")
                    and node.close_token is not None
                ):
                    inner_start, inner_end = node.inner
                    # The design's own text first, so Django never reads it as a tag.
                    inner = rewrite.escape_template_syntax(page.text[inner_start:inner_end])
                    if node.tag == "style":
                        out.append(page.rewriter.css(inner, inner_start, attribute=False))
                    elif rewrite.is_inline_script(node, page.text) and inner.strip():
                        out.append("{% csp_hash %}" + inner + "{% endcsp_hash %}")
                    else:
                        out.append(inner)
                    while i + 1 < len(tokens) and tokens[i + 1].start < node.close_token.start:
                        i += 1
            else:
                out.append(rewrite.escape_template_syntax(token.text(page.text)))
            i += 1
        return "".join(out)

    def group(self, group: Group) -> str:
        """The markup of a shared block, from its reference page, markers generalized."""
        page = self.by_key[group.reference]
        block = group.instances[group.reference]
        variations = compare.element_variations(
            group, {k: self.by_key[k].text for k in group.instances}
        )
        return self.span(page, block.node.start, block.node.end, variations)

    def block(self, page: PageSource, block: Block) -> str:
        return self.span(page, block.node.start, block.node.end)


def _title_text(page: PageSource) -> str:
    return page.title.inner_text(page.text) if page.title is not None else ""


def _description_text(page: PageSource) -> str:
    if page.description is None:
        return ""
    for attr in rewrite.attributes(page.description.tag_text(page.text)):
        if attr.name == "content" and attr.value_start is not None:
            raw = page.description.tag_text(page.text)[attr.value_start : attr.value_end]
            return raw.replace('"', "&quot;") if attr.quote != '"' else raw
    return ""


def _body_variation(pages: list[PageSource]) -> Variation | None:
    """How the ``<body>`` start tags differ across pages, or ``None`` when they do not."""
    bodies = [(page, page.doc.body) for page in pages if page.doc.body is not None]
    if len({body.tag_text(page.text) for page, body in bodies}) <= 1:
        return None
    variation = Variation(pages={page.path for page, _ in bodies})
    for page, body in bodies:
        attrs = body.attrs(page.text)
        if "class" in attrs:
            variation.has_class = True
            for token in (attrs["class"] or "").split():
                variation.class_tokens.setdefault(token, set()).add(page.path)
        for name in compare.STATE_ATTRIBUTES[1:]:
            if name in attrs:
                value = attrs[name] or ""
                previous, members = variation.attributes.get(name, (value, set()))
                members.add(page.path)
                variation.attributes[name] = (previous if previous == value else None, members)
    return variation


def _lead(page: PageSource, block: Block) -> str:
    return rewrite.escape_template_syntax(block.lead(page.text))


def plan(design: Path, app: str, *, source_label: str | None = None) -> SitePlan:
    """Plan the site app ``app`` for the design folder ``design``."""
    texts, files = scan(design)
    result = SitePlan(app)
    if not texts:
        raise ValueError(f"{design} has no .html page.")
    pages, mapped = _read_pages(texts, files, app)
    for page in pages:
        _read_structure(page, mapped)
    renderer = _Renderer(pages, mapped, app)
    content_pages = [page for page in pages if page.redirect is None]
    reference = content_pages[0] if content_pages else None
    if reference is None:
        raise ValueError(f"{design}: every page is a redirect, so there is nothing to show.")
    layout = compare.layout(
        {page.path: page.blocks for page in content_pages},
        {page.path: page.text for page in pages},
        renderer.order,
    )
    partial_template = {
        group.name: f"{app}/partials/{group.name}.html" for group in layout.partials
    }

    # the layout
    head_counts: dict[str, int] = {}
    for page in content_pages:
        for sig in {sig for _, _, sig in page.head_items}:
            head_counts[sig] = head_counts.get(sig, 0) + 1
    shared_head = {sig for sig, count in head_counts.items() if count == len(content_pages)}
    site = compare.site_name(_title_text(page) for page in content_pages)
    base = _render_base(reference, content_pages, layout, renderer, shared_head, site, result)
    base_name = f"{app}/base.html"
    result.templates[f"templates/{base_name}"] = base

    # partials
    for group in layout.partials:
        renderer.begin()
        markup = renderer.group(group)
        head = "{% load static karni_site %}" + renderer.finish().tag()
        result.templates[f"templates/{partial_template[group.name]}"] = head + "\n" + markup + "\n"

    # pages
    page_records: list[dict[str, Any]] = []
    error_records: list[dict[str, Any]] = []
    for page in content_pages:
        assert page.rewriter is not None
        renderer.begin()
        own_head = [
            (lead, node)
            for lead, node, sig in page.head_items
            if sig not in shared_head
            and node is not page.title
            and node is not page.description
            and node is not page.canonical
        ]
        plan_for = layout.pages[page.path]
        parts = [f'{{% extends "{base_name}" %}}{{% load static karni_site %}}']
        pieces: list[str] = []
        title = _title_text(page)
        if page.title is not None:
            pieces.append(
                "{% block title %}" + rewrite.escape_template_syntax(title) + "{% endblock %}"
            )
        if page.description is not None:
            pieces.append(
                "{% block description %}"
                + rewrite.escape_template_syntax(_description_text(page))
                + "{% endblock %}"
            )
        else:
            result.problems.append(
                f'{page.path}: no <meta name="description">. The page test fails until the '
                "page's template fills {% block description %}."
            )
        if own_head:
            head_markup = "".join(
                rewrite.escape_template_syntax(page.text[lead : node.start])
                + renderer.span(page, node.start, node.end)
                for lead, node in own_head
            )
            pieces.append("{% block head %}" + head_markup + "{% endblock %}")
        for group in [*layout.prefix, *layout.suffix]:
            if group.name in plan_for.overrides:
                override = plan_for.overrides[group.name]
                markup = renderer.block(page, override) if override is not None else ""
                pieces.append(f"{{% block {_block_id(group.name)} %}}{markup}{{% endblock %}}")
        content: list[str] = []
        for item in plan_for.content:
            if isinstance(item, str):
                instance = next(g for g in layout.partials if g.name == item).instances[page.path]
                content.append(
                    _lead(page, instance) + f'{{% include "{partial_template[item]}" %}}'
                )
            else:
                content.append(_lead(page, item) + renderer.block(page, item))
        # The page's own origins go inside a block: a child template renders only its
        # blocks, so a tag outside one would never run.
        pieces.append(
            "{% block content %}" + renderer.finish().tag() + "".join(content) + "{% endblock %}"
        )
        template_rel = (
            f"templates/{page.path}" if page.error else f"templates/{app}/{page.name}.html"
        )
        result.templates[template_rel] = "\n".join([*parts, *pieces]) + "\n"
        record = {
            "source": page.path,
            "template": page.path if page.error else f"{app}/{page.name}.html",
            "route": "" if page.error else f"/{page.route}",
            "name": "" if page.error else page.name,
            "title": unescape(compare.collapse(title)),
            "description": unescape(compare.collapse(_description_text(page))),
            "head_hash": _sha256(
                "".join(compare.collapse(node.text(page.text)) for _, node in own_head).encode()
            ),
            "overrides": sorted(plan_for.overrides),
            "sections": [
                compare.section_record(item, page.text)
                for item in plan_for.content
                if isinstance(item, Block)
            ],
            "partials": [item for item in plan_for.content if isinstance(item, str)],
            # Each <form> of the page (lines of the design's file): karni make form names the
            # one its {% karni_form %} replaces.
            "forms": [form.as_record() for form in forms_in(page.text)],
        }
        if page.error:
            error_records.append({"source": page.path, "template": page.path})
            continue
        page_records.append(record)
        result.views.append((page.name, f"{app}/{page.name}.html"))
        result.routes.append((page.route, page.name))
        result.page_urls.append(f"/{page.route}")

    # redirects
    redirect_records: list[dict[str, Any]] = []
    for page in pages:
        if page.redirect is None:
            continue
        ref = page.redirect
        if ref.kind == "page":
            target = mapped.view_name(ref.path)
            result.redirects.append(Redirect(page.path, page.route, page.name, target))
            redirect_records.append(
                {"source": page.path, "route": f"/{page.route}", "name": page.name, "to": target}
            )
        elif ref.kind == "external":
            result.redirects.append(
                Redirect(page.path, page.route, page.name, ref.raw.strip(), external=True)
            )
            redirect_records.append(
                {"source": page.path, "route": f"/{page.route}", "name": page.name, "to": ref.raw}
            )
        else:
            result.problems.append(
                f"{page.path}: a redirect to {ref.raw!r}, which is not a page of the design. "
                "It was not routed."
            )

    # assets
    used: set[str] = set()
    for page in pages:
        if page.rewriter is not None:
            used |= page.rewriter.used_files
    used |= _css_references(files, used)
    scripted = _script_references(files, set(files) - used)
    result.assets = dict(files)
    result.unused_assets = sorted(set(files) - used - scripted)
    for page in pages:
        if page.rewriter is None:
            continue
        for problem in page.rewriter.problems:
            result.problems.append(
                f"{page.path}:{page.line(problem.offset)}: {problem.what}: {problem.why}"
            )
    result.problems.extend(renderer.problems)

    # the record
    active_classes: set[str] = set()
    active_attributes: dict[str, str] = {}
    for group in layout.groups():
        for variation in compare.element_variations(
            group, {k: renderer.by_key[k].text for k in group.instances}
        ).values():
            for token, members in variation.class_tokens.items():
                if len(members) != len(variation.pages):
                    active_classes.add(token)
            for name, (value, members) in variation.attributes.items():
                if len(members) != len(variation.pages) and value is not None:
                    active_attributes[name] = value
    result.design = {
        "version": 1,
        "source": source_label or str(design),
        "app": app,
        "site": {"name": site},
        "base": {"template": base_name, "reference": reference.path},
        "shared": [
            {
                "name": group.name,
                "tag": group.tag,
                "place": "prefix" if group in layout.prefix else "suffix",
                "pages": sorted(group.instances),
                "hash": _sha256(group.signature.encode()),
            }
            for group in [*layout.prefix, *layout.suffix]
        ],
        "pages": page_records,
        "partials": [
            {
                "name": group.name,
                "template": partial_template[group.name],
                "tag": group.tag,
                "pages": sorted(group.instances),
                "hash": _sha256(group.signature.encode()),
            }
            for group in layout.partials
        ],
        "redirects": redirect_records,
        "error_pages": error_records,
        "active": {
            "class": sorted(active_classes),
            "attributes": dict(sorted(active_attributes.items())),
        },
        "assets": {
            "files": {
                path: {
                    "sha256": _sha256(file.read_bytes()),
                    "size": file.stat().st_size,
                    "used": path not in result.unused_assets,
                }
                for path, file in sorted(files.items())
            },
            "unused": result.unused_assets,
        },
        "unmapped": list(result.problems),
    }
    _notes(result, layout, content_pages)
    _form_notes(result, content_pages)
    return result


def _block_id(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "block"


def _render_base(
    reference: PageSource,
    pages: list[PageSource],
    layout: Layout,
    renderer: _Renderer,
    shared_head: set[str],
    site: str,
    result: SitePlan,
) -> str:
    """The layout: the reference page's skeleton, the shared head, the shared blocks."""
    text = reference.text
    assert reference.rewriter is not None
    renderer.begin()
    doc = reference.doc
    head, body = doc.head, doc.body
    esc = rewrite.escape_template_syntax
    out: list[str] = []
    title_block = "<title>{% block title %}" + escape(site, quote=False) + "{% endblock %}</title>"
    description_block = '<meta name="description" content="{% block description %}{% endblock %}">'
    canonical_block = (
        '<link rel="canonical" href="{{ request.scheme }}://{{ request.get_host }}'
        '{{ request.path }}">'
    )
    container = doc.body_or_root()
    body_start = body.start if body is not None else container.inner[0]
    if head is not None:
        out.append(esc(text[: head.start]))
        out.append(reference.rewriter.tag(head, text))
        inner_start, inner_end = head.inner
        has_title = has_description = False
        last_end = inner_start
        for lead, node, sig in reference.head_items:
            lead_text = esc(text[lead : node.start])
            if node is reference.title:
                out.append(lead_text + title_block)
                has_title = True
            elif node is reference.description:
                out.append(lead_text + description_block)
                has_description = True
            elif node is reference.canonical:
                out.append(lead_text + canonical_block)
            elif sig in shared_head:
                out.append(lead_text + renderer.span(reference, node.start, node.end))
            last_end = node.end
        first = reference.head_items[0][1].start if reference.head_items else inner_end
        indent = _indent(text, inner_start, first)
        if not has_title:
            out.append(indent + title_block)
        if not has_description:
            out.append(indent + description_block)
        if reference.canonical is None and any(p.canonical is not None for p in pages):
            out.append(indent + canonical_block)
        out.append("{% block head %}{% endblock %}")
        out.append(esc(text[last_end:inner_end]))
        if head.close_token is not None:
            out.append(text[inner_end : head.end])
        out.append(esc(text[head.end : body_start]))
    else:
        result.problems.append(
            f"{reference.path}: no <head>, so the layout got a plain one with the title and "
            "description blocks."
        )
        out.append(
            '<!DOCTYPE html>\n<html>\n<head>\n  <meta charset="utf-8">\n  '
            + title_block
            + "\n  "
            + description_block
            + "\n{% block head %}{% endblock %}</head>\n"
        )
        out.append(esc(text[:body_start]) if body is not None else "")
    if body is not None:
        body_tag = reference.rewriter.tag(body, text)
        variation = _body_variation(pages)
        if variation is not None:
            body_tag, problems = compare.generalize_tag(body_tag, variation, renderer.patterns)
            result.problems.extend(f"{reference.path}: <body>: {p}" for p in problems)
        out.append(body_tag)
    inner_start, inner_end = container.inner
    cursor = inner_start
    for group in layout.prefix:
        instance = group.instances.get(reference.path)
        if instance is not None:
            out.append(esc(text[cursor : instance.node.start]))
            cursor = instance.node.end
        else:
            ref_page = renderer.by_key[group.reference]
            out.append(esc(group.instances[group.reference].lead(ref_page.text)))
        out.append(
            f"{{% block {_block_id(group.name)} %}}" + renderer.group(group) + "{% endblock %}"
        )
    out.append("{% block content %}{% endblock %}")
    last_end = reference.tail_start
    for group in layout.suffix:
        instance = group.instances.get(reference.path)
        if instance is not None:
            out.append(esc(instance.lead(text)))
            last_end = instance.node.end
        else:
            ref_page = renderer.by_key[group.reference]
            out.append(esc(group.instances[group.reference].lead(ref_page.text)))
        out.append(
            f"{{% block {_block_id(group.name)} %}}" + renderer.group(group) + "{% endblock %}"
        )
    out.append(esc(text[last_end:inner_end]))
    if body is not None:
        if body.close_token is not None:
            out.append(text[inner_end : body.end])
        out.append(esc(text[body.end :]))
    else:
        out.append(esc(text[inner_end:]))
    return "{% load static karni_site %}" + renderer.finish().tag() + "".join(out)


def _indent(text: str, start: int, end: int) -> str:
    segment = text[start:end]
    return segment if segment.strip() == "" and segment else "\n  "


def _css_references(files: dict[str, Path], used: set[str]) -> set[str]:
    """Files that CSS files reference with ``url(...)`` or ``@import``, resolved from the CSS file."""
    found: set[str] = set()
    pending = [path for path in files if path.lower().endswith(".css")]
    seen: set[str] = set()
    while pending:
        css = pending.pop()
        if css in seen:
            continue
        seen.add(css)
        try:
            text = files[css].read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        base = posixpath.dirname(css)
        for match in _CSS_REF.finditer(text):
            raw = (match.group(2) or match.group(4) or "").strip()
            if not raw or raw.startswith(("data:", "http:", "https:", "//", "#")):
                continue
            target = raw.split("?")[0].split("#")[0]
            resolved = posixpath.normpath(
                posixpath.join(base, target) if not target.startswith("/") else target.lstrip("/")
            )
            if resolved in files:
                found.add(resolved)
                if resolved.lower().endswith(".css"):
                    pending.append(resolved)
    return found


def _script_references(files: dict[str, Path], candidates: set[str]) -> set[str]:
    """Files whose path or name a script mentions in a string: a script may load them."""
    found: set[str] = set()
    names = {path: posixpath.basename(path) for path in candidates}
    for path, file in files.items():
        if not path.lower().endswith((".js", ".mjs")):
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        strings = {match.group(1) for match in _JS_STRING.finditer(text)}
        for candidate, name in names.items():
            if any(name in s for s in strings):
                found.add(candidate)
    return found


def _notes(result: SitePlan, layout: Layout, pages: list[PageSource]) -> None:
    shared = [
        f"{g.name} (<{g.tag}>, {len(g.instances)} of {len(pages)} pages)"
        for g in [*layout.prefix, *layout.suffix]
    ]
    if shared:
        result.notes.append("shared by every page, in base.html: " + ", ".join(shared))
    else:
        result.notes.append(
            "no header or footer shared by every page: base.html holds the <head> only and "
            "each page its whole body."
        )
    for group in [*layout.prefix, *layout.suffix]:
        missing = [key for key in layout.pages if key not in group.instances]
        if missing:
            overrides = [
                k for k in missing if layout.pages[k].overrides.get(group.name) is not None
            ]
            empties = [k for k in missing if k not in overrides]
            if overrides:
                result.notes.append(
                    f"{group.name}: {', '.join(overrides)} keep their own in a block override"
                )
            if empties:
                result.notes.append(
                    f"{group.name}: not on {', '.join(empties)} (the block is empty there)"
                )
    for group in layout.partials:
        result.notes.append(
            f"partial {group.name} (<{group.tag}>): {', '.join(sorted(group.instances))}"
        )


def _form_notes(result: SitePlan, pages: list[PageSource]) -> None:
    """A note per ``<form>``: it posts where the design said, until a tag replaces it."""
    for page in pages:
        for form in forms_in(page.text):
            fields = ", ".join(form.names) or "no named fields"
            target = f' to "{form.action}"' if form.action else ""
            result.notes.append(
                f"form: {page.path}:{form.line} posts{target} ({fields}). Make it a working "
                "form: karni make form <name> <field:type> ... prints the {% karni_form %} "
                "that replaces it."
            )
