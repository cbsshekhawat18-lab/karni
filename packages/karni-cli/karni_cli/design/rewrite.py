"""Rewrite a design's markup for Django without changing what the browser sees.

* A link to another page of the design (``about.html``, ``../index.html``,
  ``services/web.html#team``) becomes ``{% url 'app:name' %}`` plus the
  anchor and query string it had.
* A path to a file of the design (``css/style.css``, ``assets/img/x.jpg``, in
  ``src``, ``href``, ``srcset``, ``poster``, ``content``, ``data-*`` and in
  ``url(...)`` inside ``style`` attributes and ``<style>`` blocks) becomes
  ``{% static 'app/<path>' %}``.
* An inline script becomes ``<script>{% csp_hash %}...{% endcsp_hash %}</script>``
  and an event handler attribute ``onclick="{% csp_hash attribute %}...{% endcsp_hash %}"``,
  so the design runs under Karni's Content-Security-Policy. The origins a
  template loads from (a font service, a CDN script) are collected for a
  ``{% csp_allow %}`` at the top of the template.
* ``{{``, ``{%`` and ``{#`` in the design's own text are escaped so Django
  does not read them as template syntax.

Everything else is the source's bytes. The rewriter works on
:class:`~karni_cli.design.parse.Node` spans and returns pieces, so the
caller decides which spans to emit.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from html import escape, unescape
from typing import Final
from urllib.parse import urlsplit

from karni_cli.design.parse import Attribute, Node, attributes

__all__ = [
    "KNOWN_ORIGINS",
    "Mapped",
    "Policy",
    "Reference",
    "Rewriter",
    "escape_template_syntax",
    "is_inline_script",
    "page_route",
    "page_view_name",
    "split_reference",
    "srcset_parts",
]

#: Origins whose resources come from a second origin: a stylesheet from the first
#: loads fonts from the second (Google Fonts).
KNOWN_ORIGINS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "https://fonts.googleapis.com": (("font-src", "https://fonts.gstatic.com"),),
}
#: Script types that run as script. Anything else (``application/ld+json``) is data.
SCRIPT_TYPES: Final = frozenset({"", "text/javascript", "application/javascript", "module"})
_FONT_SUFFIXES: Final = (".woff2", ".woff", ".ttf", ".otf", ".eot")
_WEB_SCHEMES: Final = frozenset({"http", "https"})
_HTML_SUFFIXES: Final = (".html", ".htm")
_CSS_URL = re.compile(
    r"""url\(\s*(?:(?P<q>&quot;|&#34;|&#39;|"|')(?P<quoted>.*?)(?P=q)|(?P<bare>[^\s)]*))\s*\)""",
    re.DOTALL,
)
_CSS_IMPORT = re.compile(r"""@import\s+(?:url\()?\s*(?P<q>["']?)(?P<url>[^"')\s;]+)(?P=q)""")
_TEMPLATE_SYNTAX = re.compile(r"\{\{|\{%|\{#|%\}|\}\}|#\}")
_RESERVED_NAMES: Final = frozenset(
    {
        "render",
        "request",
        "views",
        "urlpatterns",
        "app_name",
        "home",
        "path",
        "include",
        "RedirectView",
    }
)
_PY_KEYWORDS: Final = frozenset(
    [
        "False",
        "None",
        "True",
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
    ]
)


def escape_template_syntax(text: str) -> str:
    """``{{``, ``{%``, ``{#`` and their closers as ``{% templatetag %}`` tags."""
    names = {
        "{{": "openvariable",
        "}}": "closevariable",
        "{%": "openblock",
        "%}": "closeblock",
        "{#": "opencomment",
        "#}": "closecomment",
    }
    return _TEMPLATE_SYNTAX.sub(lambda m: "{% templatetag " + names[m.group(0)] + " %}", text)


def page_view_name(source: str, taken: Iterable[str] = ()) -> str:
    """The view and URL name for a page path: ``about.html`` → ``about``, ``services/web.html``
    → ``services_web``, ``index.html`` → ``home``, ``blog/index.html`` → ``blog``."""
    stem = source[: -len(suffix)] if (suffix := _suffix(source)) else source
    if stem == "index":
        name = "home"
    else:
        stem = stem.removesuffix("/index")
        name = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_") or "page"
        if name[0].isdigit():
            name = f"page_{name}"
        if name in _RESERVED_NAMES or name in _PY_KEYWORDS:
            name = f"{name}_page"
    used = set(taken)
    candidate, counter = name, 2
    while candidate in used:
        candidate = f"{name}_{counter}"
        counter += 1
    return candidate


def page_route(source: str) -> str:
    """The URL path of a page: ``about.html`` → ``about/``, ``index.html`` → ``""``,
    ``services/web.html`` → ``services/web/``, ``blog/index.html`` → ``blog/``."""
    stem = source[: -len(suffix)] if (suffix := _suffix(source)) else source
    if stem == "index":
        return ""
    stem = stem.removesuffix("/index")
    parts = [
        re.sub(r"[^A-Za-z0-9_.\-]+", "-", part).strip("-") or "page" for part in stem.split("/")
    ]
    return "/".join(parts) + "/"


def _suffix(path: str) -> str:
    lower = path.lower()
    return next((s for s in _HTML_SUFFIXES if lower.endswith(s)), "")


@dataclass(frozen=True)
class Reference:
    """A URL found in the design, split: its path part, query and fragment."""

    raw: str
    kind: str  # page, asset, external, inert, missing, empty
    path: str = ""  # the design-relative path for page/asset/missing
    query: str = ""
    fragment: str = ""
    origin: str = ""  # scheme://host for an external URL


def split_reference(value: str) -> tuple[str, str, str]:
    """``"a.html?x=1#top"`` → ``("a.html", "?x=1", "#top")``."""
    path, hash_sep, fragment = value.partition("#")
    path, query_sep, query = path.partition("?")
    return path, (query_sep + query), (hash_sep + fragment)


def srcset_parts(value: str) -> list[tuple[str, str, str]]:
    """``"a.jpg 1x, b.jpg 2x"`` → ``[(lead, url, descriptor), ...]`` keeping the whitespace."""
    parts: list[tuple[str, str, str]] = []
    for candidate in value.split(","):
        stripped = candidate.strip()
        if not stripped:
            parts.append((candidate, "", ""))
            continue
        lead = candidate[: len(candidate) - len(candidate.lstrip())]
        trail = candidate[len(candidate.rstrip()) :]
        url, _, descriptor = stripped.partition(" ")
        parts.append((lead, url, (" " + descriptor if descriptor else "") + trail))
    return parts


@dataclass
class Mapped:
    """What the design maps to: its pages by path, its files by path, the app label."""

    app: str
    pages: dict[str, str]  # design path (``about.html``) → view name (``about``)
    files: set[str]  # every non-page file of the design, as design-relative paths
    #: Pages that are redirects: design path → the page they go to.
    redirects: dict[str, str] = field(default_factory=dict)

    def resolve(self, value: str, page_dir: str) -> Reference:
        """Classify ``value`` as written in a page under ``page_dir`` (``""`` for the root)."""
        raw = value
        stripped = value.strip()
        if not stripped:
            return Reference(raw, "empty")
        if stripped.startswith("#"):
            return Reference(raw, "inert")
        parts = urlsplit(stripped)
        scheme = parts.scheme.lower()
        if scheme in _WEB_SCHEMES or stripped.startswith("//"):
            origin = f"{scheme or 'https'}://{parts.netloc}" if parts.netloc else ""
            return Reference(raw, "external", origin=origin)
        if scheme or stripped.startswith(("{{", "{%")):
            return Reference(raw, "inert")
        path, query, fragment = split_reference(stripped)
        if not path:
            return Reference(raw, "inert", query=query, fragment=fragment)
        if path.startswith("/"):
            target = posixpath.normpath(path.lstrip("/"))
        else:
            target = posixpath.normpath(posixpath.join(page_dir, path))
        if target == ".":
            target = ""
        if target.startswith(".."):
            return Reference(raw, "missing", path=target, query=query, fragment=fragment)
        for candidate in self._page_candidates(target, path.endswith("/") or not path):
            if candidate in self.pages or candidate in self.redirects:
                return Reference(raw, "page", path=candidate, query=query, fragment=fragment)
        if target in self.files:
            return Reference(raw, "asset", path=target, query=query, fragment=fragment)
        return Reference(raw, "missing", path=target, query=query, fragment=fragment)

    @staticmethod
    def _page_candidates(target: str, directory: bool) -> list[str]:
        if directory:
            return [posixpath.join(target, "index.html") if target else "index.html"]
        candidates = [target]
        if not _suffix(target):
            candidates += [f"{target}.html", posixpath.join(target, "index.html")]
        return candidates

    def view_name(self, path: str) -> str:
        """The view a page link reaches: a redirect's target page, else the page itself."""
        while path in self.redirects and path not in self.pages:
            path = self.redirects[path]
        return self.pages[path]


@dataclass
class Policy:
    """The Content-Security-Policy sources a template needs: directive → origins."""

    sources: dict[str, set[str]] = field(default_factory=dict)

    def add(self, directive: str, origin: str) -> None:
        if origin:
            self.sources.setdefault(directive, set()).add(origin)
            for extra_directive, extra_origin in KNOWN_ORIGINS.get(origin, ()):
                self.sources.setdefault(extra_directive, set()).add(extra_origin)

    def merge(self, other: Policy) -> None:
        for directive, origins in other.sources.items():
            for origin in origins:
                self.sources.setdefault(directive, set()).add(origin)

    def tag(self) -> str:
        """``{% csp_allow "font-src https://..." ... %}``, or ``""`` with nothing to allow."""
        if not self.sources:
            return ""
        specs = [
            f'"{directive} {" ".join(sorted(origins))}"'
            for directive, origins in sorted(self.sources.items())
        ]
        return "{% csp_allow " + " ".join(specs) + " %}"


def is_inline_script(node: Node, source: str) -> bool:
    """A ``<script>`` with content that runs (no ``src``, a script type)."""
    if node.tag != "script" or node.attr(source, "src") is not None:
        return False
    kind = (node.attr(source, "type") or "").strip().lower()
    return kind in SCRIPT_TYPES


@dataclass
class Problem:
    """Something the rewriter could not map, with where it is."""

    what: str
    why: str
    offset: int


def _directive_for(tag: str, attrs: dict[str, str | None], attribute: str) -> str | None:
    """The CSP directive governing a URL in ``attribute`` of ``tag``, or ``None`` if none."""
    if tag == "script":
        return "script-src" if attribute == "src" else None
    if tag == "link":
        rels = set((attrs.get("rel") or "").lower().split())
        if attribute != "href":
            return None
        if "stylesheet" in rels:
            return "style-src"
        if rels & {"icon", "apple-touch-icon", "shortcut"}:
            return "img-src"
        if "manifest" in rels:
            return "manifest-src"
        if "preload" in rels or "modulepreload" in rels:
            kind = (attrs.get("as") or "").lower()
            return {
                "font": "font-src",
                "style": "style-src",
                "script": "script-src",
                "image": "img-src",
                "fetch": "connect-src",
            }.get(kind, "script-src" if "modulepreload" in rels else None)
        if rels & {"preconnect", "dns-prefetch"}:
            return "preconnect"
        return None
    if tag in ("img", "picture") or (tag == "source" and attribute == "srcset"):
        return "img-src"
    if tag == "video" and attribute == "poster":
        return "img-src"
    if tag in ("video", "audio", "source", "track"):
        return "media-src"
    if tag == "iframe":
        return "frame-src"
    if tag in ("embed", "object"):
        return "object-src"
    if tag == "form" and attribute == "action":
        return "form-action"
    if tag == "meta" and attribute == "content":
        return None
    return None


class Rewriter:
    """Rewrites the markup of one page for its template.

    :param mapped: the design's pages and files.
    :param page_dir: the page's directory inside the design (``""`` or ``"services"``).
    :param url_tag: renders ``{% url %}`` for a view name and a quote character.
    :param static_tag: renders ``{% static %}`` for a design path and a quote character.
    """

    def __init__(
        self,
        mapped: Mapped,
        page_dir: str,
        *,
        url_tag: Callable[[str, str], str] | None = None,
        static_tag: Callable[[str, str], str] | None = None,
    ) -> None:
        self.mapped = mapped
        self.page_dir = page_dir
        self.url_tag = url_tag or self._url_tag
        self.static_tag = static_tag or self._static_tag
        self.policy = Policy()
        self.problems: list[Problem] = []
        self.used_files: set[str] = set()
        self.links: set[str] = set()

    # the tags this rewriter writes

    def _url_tag(self, view: str, quote: str) -> str:
        inner = "'" if quote != "'" else '"'
        return f"{{% url {inner}{self.mapped.app}:{view}{inner} %}}"

    def _static_tag(self, path: str, quote: str) -> str:
        inner = "'" if quote != "'" else '"'
        return f"{{% static {inner}{self.mapped.app}/{path}{inner} %}}"

    # single values

    def url(self, value: str, quote: str, offset: int, *, directive: str | None) -> str | None:
        """The template form of a URL value, or ``None`` when it stays as written."""
        ref = self.mapped.resolve(unescape(value), self.page_dir)
        if ref.kind == "page":
            self.links.add(ref.path)
            return self.url_tag(self.mapped.view_name(ref.path), quote) + ref.query + ref.fragment
        if ref.kind == "asset":
            self.used_files.add(ref.path)
            return self.static_tag(ref.path, quote) + ref.query + ref.fragment
        if ref.kind == "external":
            if directive == "preconnect":
                for extra_directive, extra_origin in KNOWN_ORIGINS.get(ref.origin, ()):
                    self.policy.add(extra_directive, extra_origin)
                if ref.origin in {o for pairs in KNOWN_ORIGINS.values() for _, o in pairs}:
                    self.policy.add(self._known_directive(ref.origin), ref.origin)
            elif directive:
                self.policy.add(directive, ref.origin)
                if directive == "style-src" and ref.origin not in KNOWN_ORIGINS:
                    # A stylesheet from another origin usually loads its fonts from there too.
                    self.policy.add("font-src", ref.origin)
            return None
        if ref.kind == "missing":
            self.problems.append(
                Problem(
                    f"{value!r}",
                    f"{ref.path} is not a page or a file of the design, so the link was kept as "
                    "written",
                    offset,
                )
            )
        return None

    @staticmethod
    def _known_directive(origin: str) -> str:
        for pairs in KNOWN_ORIGINS.values():
            for directive, known in pairs:
                if known == origin:
                    return directive
        return "connect-src"

    def srcset(self, value: str, quote: str, offset: int, directive: str | None) -> str | None:
        changed = False
        out: list[str] = []
        for lead, url, descriptor in srcset_parts(value):
            new = self.url(url, quote, offset, directive=directive) if url else None
            if new is not None:
                changed = True
            out.append(lead + (new if new is not None else url) + descriptor)
        return ",".join(out) if changed else None

    def css(self, text: str, offset: int, *, attribute: bool) -> str:
        """CSS with ``url(...)`` and ``@import`` references rewritten.

        ``attribute=True`` for a ``style`` attribute, whose quotes are entities.
        """

        def replace(match: re.Match[str]) -> str:
            quoted = match.group("quoted")
            raw_url = quoted if quoted is not None else match.group("bare")
            url = unescape(raw_url) if attribute else raw_url
            preceding = text[max(0, match.start() - 12) : match.start()]
            lower = url.lower().split("?")[0]
            directive = (
                "style-src"
                if "@import" in preceding
                else "font-src"
                if lower.endswith(_FONT_SUFFIXES)
                else "img-src"
            )
            quote = match.group("q") or ""
            # The quote around the URL, as the tag's inner quote is chosen against it.
            around = "" if not quote else '"' if quote in ('"', "&quot;", "&#34;") else "'"
            new = self.url(url, around, offset + match.start(), directive=directive)
            if new is None:
                return match.group(0)
            if attribute:
                new = escape(new, quote=False)
            return f"url({quote}{new}{quote})"

        text = _CSS_URL.sub(replace, text)

        def replace_import(match: re.Match[str]) -> str:
            url = match.group("url")
            if url.startswith(("{%", "url(")):
                return match.group(0)
            quote = match.group("q") or ""
            new = self.url(url, quote, offset, directive="style-src")
            if new is None:
                return match.group(0)
            return match.group(0).replace(url, new)

        return _CSS_IMPORT.sub(replace_import, text)

    # a start tag

    def tag(self, node: Node, source: str) -> str:
        """The start tag of ``node`` with its URL attributes rewritten."""
        text = node.tag_text(source)
        if not text:
            return text
        attrs = node.attrs(source)
        pieces: list[str] = []
        position = 0
        for attr in attributes(text):
            if attr.value_start is None or attr.value is None:
                continue
            raw = escape_template_syntax(text[attr.value_start : attr.value_end])
            new = self._attribute(node.tag, attrs, attr, raw, node.start + attr.value_start)
            if new is None:
                continue
            pieces.append(escape_template_syntax(text[position : attr.value_start]))
            pieces.append(new)
            position = attr.value_end or position
        pieces.append(escape_template_syntax(text[position:]))
        return "".join(pieces)

    def _attribute(
        self, tag: str, attrs: dict[str, str | None], attr: Attribute, raw: str, offset: int
    ) -> str | None:
        name = attr.name
        quote = attr.quote
        if name.startswith("on"):
            return "{% csp_hash attribute %}" + raw + "{% endcsp_hash %}"
        if name == "style":
            new = self.css(raw, offset, attribute=True)
            return new if new != raw else None
        if name in ("srcset", "imagesrcset"):
            return self.srcset(raw, quote, offset, _directive_for(tag, attrs, name))
        if name in ("href", "src", "poster", "action", "data", "cite", "formaction") or (
            name.startswith("data-") or name == "content"
        ):
            if name == "content" and tag == "meta":
                # og:image and the like: only a value that is a file of the design changes.
                ref = self.mapped.resolve(unescape(raw), self.page_dir)
                if ref.kind != "asset":
                    return None
            if name.startswith("data-"):
                ref = self.mapped.resolve(unescape(raw), self.page_dir)
                if ref.kind not in ("asset", "page"):
                    return None
            mapped = self.url(raw, quote, offset, directive=_directive_for(tag, attrs, name))
            if mapped is None:
                return None
            return escape(mapped, quote=False) if quote else mapped
        return None
