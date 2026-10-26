"""``karni ui detect --css``: Karni's tokens from any stylesheet, variables or not.

A design that is not a design system still has a brand: a few custom
properties on ``:root``, or only the ``body``, ``a`` and ``button`` rules of a
hand-written stylesheet, or Bootstrap's ``--bs-*`` variables. :func:`detect_css`
reads the stylesheets it is given (files, or a directory with the pages that
link them) and maps what it finds onto the tokens every @karni/ui component
reads, in three grades the report keeps apart:

* **found**: a custom property whose name means the role (``--brand``,
  ``--bs-body-bg``, ``--text-muted``), its ``var()`` chain resolved to the
  literal value;
* **inferred**: a value read from an ordinary rule (``body { background }``,
  ``a { color }``, ``button { border-radius }``), or derived from another
  token (the ring is the primary colour, the input border is the border, the
  text on a primary button is picked for contrast);
* **defaulted**: nothing in the stylesheet says, so the token keeps Karni's
  default and the report lists it.

Values are written as literals, never as ``var()`` references, so the file
stands alone: the staff app imports it after ``@karni/ui/styles.css`` and the
Django admin loads the same file. Nothing is guessed: a value that cannot be
resolved is reported with the reason instead.

Escape hatches: the generated ``karni-theme.css`` is the project's to edit
(every token has one line), ``--output`` chooses the file, and
:func:`detect_css` is a plain function other tools call (``karni import
design`` does) to get the report without writing anything.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from karni_cli.project import CliError
from karni_cli.uitheme import colour, css, render
from karni_cli.uitheme.model import Detection, Scheme, color_token

__all__ = ["COLOUR_ROLES", "TARGET_TOKENS", "CssDetection", "Provenance", "detect_css"]

Category = Literal["found", "inferred"]

#: The colour roles ``--css`` fills, in the order the report lists them.
COLOUR_ROLES: Final[tuple[str, ...]] = (
    "primary",
    "primary-foreground",
    "background",
    "foreground",
    "border",
    "input",
    "ring",
    "muted",
    "muted-foreground",
    "destructive",
)
#: Every token ``--css`` can set.
TARGET_TOKENS: Final[tuple[str, ...]] = (
    *(color_token(role) for role in COLOUR_ROLES),
    "--karni-radius",
    "--karni-font-sans",
    "--karni-font-mono",
)
_NON_COLOUR_TOKENS: Final[frozenset[str]] = frozenset(
    {"--karni-radius", "--karni-font-sans", "--karni-font-mono"}
)

# --- the files ---------------------------------------------------------------

#: Stylesheets a design loads before its own, when a directory is scanned.
_FRAMEWORK_NAMES: Final[tuple[str, ...]] = (
    "normalize",
    "reset",
    "bootstrap",
    "bulma",
    "foundation",
    "pico",
    "tailwind",
    "milligram",
    "skeleton",
)
_SKIP_DIRS: Final[frozenset[str]] = frozenset({"node_modules", "dist", "build"})
_LINK_TAG = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTRIBUTE = re.compile(r"""([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
_REMOTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)
_IMPORT_URL = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)|["']([^"']+)["']""")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _local_target(href: str, base: Path) -> Path | None:
    """The local file an ``href`` names, or ``None`` for a URL, a ``data:`` or an absolute path."""
    href = href.strip().split("#", 1)[0].split("?", 1)[0]
    if not href or _REMOTE.match(href):
        return None
    if href.startswith("/"):
        # A site-absolute path: relative to the directory being scanned.
        href = href.lstrip("/")
    return (base / href).resolve()


def _linked_stylesheets(page: Path, root: Path, notes: list[str]) -> list[Path]:
    """The local stylesheets a page links, in document order."""
    found: list[Path] = []
    text = _read(page)
    for tag in _LINK_TAG.findall(text):
        attributes = {
            name.lower(): (a or b or c)
            for name, a, b, c in (m.groups() for m in _ATTRIBUTE.finditer(tag))
        }
        rel = attributes.get("rel", "").lower().split()
        href = attributes.get("href")
        if "stylesheet" not in rel or href is None:
            continue
        target = _local_target(href, page.parent)
        if target is None:
            if _REMOTE.match(href.strip()):
                notes.append(f"{_rel(page)} links {href.strip()}: a remote stylesheet is not read.")
            continue
        if target.suffix.lower() != ".css":
            continue
        if not target.is_file():
            alternative = _local_target(href, root)
            if alternative is not None and alternative.is_file():
                target = alternative
            else:
                notes.append(f"{_rel(page)} links {href.strip()}, which is not there.")
                continue
        found.append(target)
    return found


def _walk(directory: Path, suffix: str) -> list[Path]:
    found: list[Path] = []
    for entry in sorted(directory.iterdir()):
        if entry.is_dir():
            if entry.name in _SKIP_DIRS or entry.name.startswith("."):
                continue
            found.extend(_walk(entry, suffix))
        elif entry.is_file() and entry.suffix.lower() == suffix:
            found.append(entry)
    return found


def _is_framework(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".min.css") or any(name.startswith(prefix) for prefix in _FRAMEWORK_NAMES)


def _directory_files(directory: Path, notes: list[str]) -> list[Path]:
    pages = _walk(directory, ".html")
    linked: list[Path] = []
    for page in pages:
        for sheet in _linked_stylesheets(page, directory, notes):
            if sheet not in linked:
                linked.append(sheet)
    if linked:
        return linked
    sheets = _walk(directory, ".css")
    if pages:
        notes.append(
            f"{_rel(directory)}: its pages link no local stylesheet, so every .css file under "
            "it was read."
        )
    return [*(p for p in sheets if _is_framework(p)), *(p for p in sheets if not _is_framework(p))]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CliError(
            f"Cannot read {path}: {exc.strerror or exc}. Check the path and its permissions, "
            "then run karni ui detect --css again.",
            code="C303",
        ) from None


def _with_imports(files: list[Path], notes: list[str]) -> list[Path]:
    """Each file's local ``@import``s before it (the browser loads them first), once each."""
    ordered: list[Path] = []
    visiting: set[Path] = set()

    def add(path: Path) -> None:
        if path in ordered or path in visiting:
            return
        visiting.add(path)
        for statement in css.parse(_read(path)).imports:
            match = _IMPORT_URL.search(statement) or None
            href = statement if match is None else (match.group(1) or match.group(2) or "")
            target = _local_target(href, path.parent)
            if target is None or target.suffix.lower() != ".css":
                continue
            if target.is_file():
                add(target)
            else:
                notes.append(f"{_rel(path)} imports {href}, which is not there.")
        visiting.discard(path)
        ordered.append(path)

    for file in files:
        add(file)
    return ordered


def collect_files(paths: Iterable[str | os.PathLike[str]], notes: list[str]) -> list[Path]:
    """The stylesheets to read, in cascade order (later ones win).

    A ``.css`` file is read as is. A directory is read through its pages: the
    local stylesheets its ``.html`` files link, in document order. Without
    pages (or links), every ``.css`` file under it, framework files first.
    A missing path is ``C303``.
    """
    files: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.exists():
            raise CliError(
                f"--css {path}: no such file or directory. Give it a stylesheet (.css) or the "
                "directory holding the design's pages, e.g. karni ui detect --css design/",
                code="C303",
            )
        if path.is_dir():
            found = _directory_files(path, notes)
            if not found:
                raise CliError(
                    f"--css {path}: no stylesheet found under it (no .css file, and no page "
                    "linking one). Point --css at the directory holding the design's CSS, or "
                    "at a .css file.",
                    code="C303",
                )
        elif path.suffix.lower() != ".css":
            raise CliError(
                f"--css {path}: not a stylesheet. Give it a .css file, or the directory holding "
                "the design's pages and stylesheets.",
                code="C303",
            )
        else:
            found = [path]
        for file in found:
            resolved = file.resolve()
            if resolved not in files:
                files.append(resolved)
    return _with_imports(files, notes)


# --- schemes -----------------------------------------------------------------

_DARK_MARK = re.compile(
    r"\.dark(?:-mode|-theme)?\b|\.theme-dark\b|"
    r"\[data-(?:theme|bs-theme|mode|color-scheme|color-mode|scheme)\s*=\s*['\"]?dark['\"]?\]",
    re.IGNORECASE,
)
_LIGHT_MARK = re.compile(
    r"\.light(?:-mode|-theme)?\b|\.theme-light\b|"
    r"\[data-(?:theme|bs-theme|mode|color-scheme|color-mode|scheme)\s*=\s*['\"]?light['\"]?\]",
    re.IGNORECASE,
)
_ROOTISH = re.compile(r"^(?::root|html|body|:host|\*)(?![\w-])")


def _scheme_of(rule: css.Rule) -> Scheme | None:
    """``dark`` for a rule under a dark marker, ``light`` otherwise, ``None`` for a mixed list."""
    dark = any(_DARK_MARK.search(selector) for selector in rule.selectors) or any(
        "prefers-color-scheme" in ctx and "dark" in ctx for ctx in rule.context
    )
    light = any(_LIGHT_MARK.search(selector) for selector in rule.selectors)
    if dark and light:
        return None
    return "dark" if dark else "light"


def _declares_globally(rule: css.Rule) -> bool:
    """Whether the rule's variables are the page's (``:root``, ``html``, ``body``, a theme marker)."""
    return any(
        _ROOTISH.match(selector)
        or _DARK_MARK.search(selector)
        or _LIGHT_MARK.search(selector)
        or selector.startswith("[data-")
        for selector in rule.selectors
    )


# --- variable names ----------------------------------------------------------

_PREFIXES: Final[tuple[str, ...]] = tuple(
    sorted(
        (
            "wp--preset--color--",
            "wp--preset--font-family--",
            "wp--custom--",
            "md-sys-color-",
            "bs-",
            "pico-",
            "color-",
            "colour-",
            "colors-",
            "clr-",
            "c-",
            "theme-",
            "site-",
            "global-",
            "token-",
            "sys-",
            "app-",
        ),
        key=len,
        reverse=True,
    )
)
_SHADES: Final[dict[str, int]] = {"600": 2, "500": 3}
_NEUTRAL_SUFFIXES: Final[tuple[str, ...]] = ("-default", "-base", "-main", "-md", "-medium")
_CHANNEL_SUFFIXES: Final[tuple[str, ...]] = ("-rgb", "-hsl", "-channels", "-h", "-s", "-l")

#: What a variable's name may be called, per role, best spelling first.
ROLE_NAMES: Final[dict[str, tuple[str, ...]]] = {
    "primary": ("primary", "primary-color", "primary-colour", "brand", "brand-color", "main"),
    "accent": ("accent", "accent-color", "highlight"),
    "link": ("link", "link-color", "link-colour", "anchor"),
    "primary-foreground": (
        "primary-foreground",
        "primary-fg",
        "primary-contrast",
        "primary-text",
        "on-primary",
        "brand-foreground",
        "brand-contrast",
        "brand-text",
        "btn-primary-color",
    ),
    "background": (
        "background",
        "background-color",
        "bg",
        "bg-color",
        "body-bg",
        "body-background",
        "page-bg",
        "page-background",
        "surface",
        "paper",
        "canvas",
    ),
    "foreground": (
        "foreground",
        "fg",
        "text",
        "text-color",
        "text-colour",
        "body-color",
        "body-text",
        "ink",
        "text-primary",
        "text-main",
        "text-base",
        "on-surface",
        "on-background",
    ),
    "border": (
        "border",
        "border-color",
        "border-colour",
        "line",
        "divider",
        "outline",
        "rule",
        "stroke",
    ),
    "input": ("input", "input-border", "input-border-color", "field-border", "form-border"),
    "ring": ("ring", "focus", "focus-ring", "focus-color", "outline-color"),
    "muted": (
        "muted",
        "muted-bg",
        "subtle",
        "secondary-bg",
        "tertiary-bg",
        "bg-muted",
        "bg-secondary",
        "bg-subtle",
        "background-muted",
        "background-secondary",
        "surface-2",
        "surface-secondary",
        "surface-muted",
        "surface-variant",
    ),
    "muted-foreground": (
        "muted-foreground",
        "muted-fg",
        "text-muted",
        "muted-text",
        "secondary-color",
        "secondary-text",
        "text-secondary",
        "text-subtle",
        "subtle-text",
        "fg-muted",
        "foreground-muted",
        "on-surface-variant",
        "caption",
        "hint",
    ),
    "destructive": (
        "destructive",
        "danger",
        "danger-color",
        "error",
        "error-color",
        "negative",
        "critical",
    ),
    "radius": (
        "radius",
        "border-radius",
        "rounded",
        "radius-md",
        "radius-base",
        "radius-default",
        "radius-m",
        "border-radius-md",
    ),
    "font-sans": (
        "font-sans",
        "font-body",
        "body-font",
        "body-font-family",
        "font-family",
        "font-family-base",
        "font-base",
        "ff-body",
        "ff-base",
        "ff-sans",
        "font-sans-serif",
        "font",
        "font-primary",
        "font-text",
        "text-font",
        "font-main",
    ),
    "font-mono": (
        "font-mono",
        "font-monospace",
        "font-family-mono",
        "font-family-monospace",
        "ff-mono",
        "mono",
        "monospace",
        "font-code",
        "code-font",
    ),
    "font-heading": (
        "font-heading",
        "font-headings",
        "font-display",
        "heading-font",
        "headings-font",
        "display-font",
        "ff-heading",
        "ff-display",
        "font-title",
        "title-font",
        "headings-font-family",
        "heading-font-family",
    ),
}
_NAME_TO_ROLE: Final[dict[str, tuple[str, int]]] = {
    name: (role, index) for role, names in ROLE_NAMES.items() for index, name in enumerate(names)
}


def _normalise(variable: str) -> tuple[str, int] | None:
    """``(base name, suffix rank)`` of a variable, or ``None`` for a channel variable."""
    name = variable.lower().lstrip("-").replace("_", "-")
    if name.endswith(_CHANNEL_SUFFIXES) and name.rsplit("-", 1)[0]:
        return None
    for _ in range(3):
        stripped = next((name[len(p) :] for p in _PREFIXES if name.startswith(p)), name)
        if stripped == name:
            break
        name = stripped
    rank = 0
    for suffix in _NEUTRAL_SUFFIXES:
        if name.endswith(suffix) and name != suffix.lstrip("-"):
            name, rank = name[: -len(suffix)], 1
            break
    else:
        match = re.search(r"-(\d{2,3})$", name)
        if match:
            shade = _SHADES.get(match.group(1))
            if shade is None:
                return None
            name, rank = name[: match.start()], shade
    return name, rank


def classify(variable: str) -> tuple[str, int, int] | None:
    """``(role, spelling index, suffix rank)`` for a variable whose name means a role."""
    normalised = _normalise(variable)
    if normalised is None:
        return None
    name, rank = normalised
    role = _NAME_TO_ROLE.get(name)
    if role is None:
        return None
    return role[0], role[1], rank


# --- values ------------------------------------------------------------------

_VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*((?:[^()]|\([^()]*\))*))?\)")
_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"inherit", "initial", "unset", "revert", "none", "currentcolor", "transparent", "auto"}
)
_LENGTH = re.compile(r"^(?:0|-?\d*\.?\d+(?:px|rem|em|%|pt|vw|vh|ch))$")
_FUNCTION_LENGTH = re.compile(r"^(?:calc|min|max|clamp)\(.*\)$")
_FONT_SIZE = re.compile(
    r"^(?:(?:normal|italic|oblique|bold|bolder|lighter|[1-9]00|small-caps|ultra-condensed|"
    r"condensed|expanded)\s+)*"
    r"(?:xx-small|x-small|small|medium|large|x-large|xx-large|larger|smaller|"
    r"\d*\.?\d+(?:px|rem|em|%|pt|vw))(?:\s*/\s*[\w.%]+)?\s+(.+)$",
    re.IGNORECASE,
)
_COLOUR_FUNCTION = re.compile(
    r"^(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix|light-dark)\(", re.IGNORECASE
)


def resolve(value: str, variables: dict[str, str]) -> str | None:
    """``value`` with every ``var()`` replaced through ``variables``, or ``None`` when one is missing."""
    text = value
    for _ in range(8):
        if "var(" not in text:
            return " ".join(text.split())
        missing = False

        def substitute(match: re.Match[str]) -> str:
            nonlocal missing
            name, fallback = match.group(1), match.group(2)
            if name in variables:
                return variables[name]
            if fallback is not None:
                return fallback.strip()
            missing = True
            return match.group(0)

        replaced = _VAR.sub(substitute, text)
        if missing or replaced == text:
            return None
        text = replaced
    return None


def is_colour(value: str) -> bool:
    """A literal colour (hex, a colour function, a named colour), not channels or a keyword."""
    text = value.strip().lower()
    if text in _KEYWORDS or css.is_hsl_channels(text):
        return False
    if re.match(r"^\d+\s*,\s*\d+\s*,\s*\d+$", text):
        return False
    return text.startswith("#") or bool(_COLOUR_FUNCTION.match(text)) or text in colour.NAMED


def is_length(value: str) -> bool:
    text = value.strip().lower()
    return bool(_LENGTH.match(text) or _FUNCTION_LENGTH.match(text))


def is_font_family(value: str) -> bool:
    text = value.strip()
    return (
        bool(re.search(r"[A-Za-z]", text))
        and not is_colour(text)
        and not is_length(text)
        and "url(" not in text
        and text.lower() not in _KEYWORDS
    )


def _tokens(value: str) -> list[str]:
    """Top-level space-separated parts of a shorthand value (parentheses kept whole)."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch.isspace() and depth == 0:
            if current:
                parts.append("".join(current))
                current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def colour_in(value: str) -> str | None:
    """The colour part of a shorthand (``1px solid #ddd``, ``#fff url(...)``), or the value itself."""
    for part in _tokens(value):
        if part.startswith("var("):
            return part
        if is_colour(part):
            return part
    return None


def font_family_in(value: str, shorthand: bool) -> str | None:
    """The family of a ``font-family`` value, or of a ``font`` shorthand."""
    if not shorthand:
        return value if is_font_family(value) else None
    match = _FONT_SIZE.match(value.strip())
    if match is None:
        return None
    family = match.group(1).strip()
    return family if is_font_family(family) else None


# --- rules --------------------------------------------------------------------

#: Selectors read for a role, best first. Lowercased and space-normalised.
_RULES: Final[dict[str, tuple[tuple[str, ...], ...]]] = {
    "page": (("body",), ("html", "html body", ":root")),
    "link": (("a", "a:link", "a:any-link", "a:not([class])"),),
    "button": (
        (
            ".btn-primary",
            ".button-primary",
            ".button--primary",
            ".btn--primary",
            "button.primary",
            ".btn.primary",
            ".button.primary",
            ".primary-button",
            ".cta",
        ),
        (
            "button",
            ".btn",
            ".button",
            "[type=submit]",
            "input[type=submit]",
            "button[type=submit]",
            ".submit",
        ),
    ),
    "input": (
        (
            "input",
            "textarea",
            "select",
            ".form-control",
            ".input",
            ".field",
            "input[type=text]",
            "input[type=email]",
            "input:not([type=submit])",
        ),
    ),
    "hr": (("hr",),),
    "table": (("table", "td", "th", "table td", "table th", ".table"),),
    "muted": (
        (
            ".text-muted",
            ".muted",
            ".text-secondary",
            ".subtle",
            ".text-subtle",
            ".caption",
            ".hint",
            ".help-text",
            ".form-text",
            ".meta",
            "small",
            ".small",
            "figcaption",
        ),
    ),
    "danger": (
        (
            ".error",
            ".danger",
            ".text-danger",
            ".text-error",
            ".alert-danger",
            ".alert-error",
            ".is-invalid",
            ".invalid",
            ".error-message",
            ".form-error",
            ".invalid-feedback",
        ),
    ),
    "heading": (("h1", "h2", "h3", "h4", "h5", "h6"),),
}


def _normalise_selector(selector: str) -> str:
    text = " ".join(selector.lower().split())
    text = re.sub(r"\s*([>+~])\s*", r"\1", text)
    return text.replace('"', "").replace("'", "")


def _selector_group(selector: str, group: str) -> int | None:
    """The priority (0 best) of ``selector`` in a rule group, or ``None`` when it is not in it."""
    text = _normalise_selector(selector)
    if group == "page" and _DARK_MARK.search(text):
        # `.dark body` and `[data-theme=dark] body` set the page's dark colours.
        text = text.split()[-1]
    for priority, names in enumerate(_RULES[group]):
        if text in names:
            return priority
    return None


@dataclass
class _Candidate:
    priority: tuple[int, int]
    value: str
    source: str


@dataclass
class _Rules:
    """The ordinary rules of one scheme that mean a token: ``(group, property) -> best candidate``."""

    found: dict[tuple[str, str], _Candidate] = field(default_factory=dict)

    def offer(
        self, group: str, prop: str, priority: tuple[int, int], value: str, source: str
    ) -> None:
        current = self.found.get((group, prop))
        if current is None or priority < current.priority:
            self.found[(group, prop)] = _Candidate(priority, value, source)

    def get(self, group: str, prop: str) -> _Candidate | None:
        return self.found.get((group, prop))


_COLOUR_PROPERTIES: Final[dict[str, tuple[str, ...]]] = {
    "background": ("background-color", "background"),
    "color": ("color",),
    "border": (
        "border-color",
        "border",
        "border-top",
        "border-bottom",
        "border-left",
        "border-right",
    ),
}


def _read_rules(sheets: list[css.Stylesheet], rules: dict[Scheme, _Rules]) -> None:
    for order, sheet in enumerate(sheets):
        for rule in sheet.rules:
            if rule.theme or not rule.properties:
                continue
            scheme = _scheme_of(rule)
            if scheme is None:
                continue
            for selector in rule.selectors:
                for group in _RULES:
                    priority = _selector_group(selector, group)
                    if priority is None:
                        continue
                    rank = (priority, -order)  # a later stylesheet wins a tie
                    source = _normalise_selector(selector)
                    for role, names in _COLOUR_PROPERTIES.items():
                        for prop in names:
                            raw = rule.properties.get(prop)
                            if raw is None:
                                continue
                            value = colour_in(raw)
                            if value is not None:
                                rules[scheme].offer(
                                    group, role, rank, value, f"{source} {{ {prop} }}"
                                )
                                break
                    radius = rule.properties.get("border-radius")
                    if radius is not None:
                        rules[scheme].offer(
                            group, "radius", rank, radius, f"{source} {{ border-radius }}"
                        )
                    family = rule.properties.get("font-family")
                    prop = "font-family"
                    if family is None and "font" in rule.properties:
                        family = font_family_in(rule.properties["font"], shorthand=True)
                        prop = "font"
                    if family is not None:
                        rules[scheme].offer(group, "font", rank, family, f"{source} {{ {prop} }}")


# --- the detection -----------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """Where one token's value came from."""

    token: str
    scheme: Scheme
    category: Category
    #: ``--brand``, ``body { background }``, or ``derived`` for a value computed from another.
    source: str
    value: str
    note: str = ""

    def as_dict(self) -> dict[str, str]:
        out = {
            "token": self.token,
            "scheme": self.scheme,
            "from": self.source,
            "value": self.value,
        }
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class CssDetection:
    """What ``detect_css`` found: the mappings, each with its grade, and what stayed default."""

    detection: Detection
    found: list[Provenance] = field(default_factory=list)
    inferred: list[Provenance] = field(default_factory=list)
    #: ``(token, reason)`` for every target token the stylesheet did not set.
    defaulted: list[tuple[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """The machine-readable report (the ``--json`` keys of the detection itself)."""
        return {
            "source": self.detection.source,
            "detected": self.detection.label,
            "files_read": list(self.detection.files),
            "mapped": [m.as_dict() for m in self.detection.mappings],
            "found": [p.as_dict() for p in self.found],
            "inferred": [p.as_dict() for p in self.inferred],
            "defaulted": [{"token": token, "reason": reason} for token, reason in self.defaulted],
            "not_mapped": [u.as_dict() for u in self.detection.unmapped],
            "notes": list(self.detection.notes),
        }

    def theme_css(self, date: str) -> str:
        """The ``karni-theme.css`` text, imported after ``@karni/ui/styles.css``."""
        return render.theme_file(self.detection, date=date, import_after="@karni/ui/styles.css")


@dataclass
class _Scheme:
    """One colour scheme's raw material."""

    variables: dict[str, str] = field(default_factory=dict)  # declared in this scheme
    lookup: dict[str, str] = field(default_factory=dict)  # for resolving var(): light under dark
    values: dict[str, Provenance] = field(default_factory=dict)  # by token


_DERIVED: Final = "derived"


def _pick_variables(variables: dict[str, str]) -> dict[str, tuple[str, int, int]]:
    """``role -> (variable, spelling index, suffix rank)``: the best-named variable per role."""
    best: dict[str, tuple[str, int, int]] = {}
    for name in variables:
        classified = classify(name)
        if classified is None:
            continue
        role, spelling, rank = classified
        current = best.get(role)
        if current is None or (rank, spelling) < (current[2], current[1]):
            best[role] = (name, spelling, rank)
    return best


def _variable_value(role: str, name: str, scheme: _Scheme, detection: Detection) -> str | None:
    raw = scheme.variables[name]
    value = resolve(raw, scheme.lookup)
    if value is None:
        detection.skip(
            name,
            f"its value {raw!r} reads a variable the stylesheets do not define, so it cannot "
            "be written as a literal",
        )
        return None
    if role in ("radius",):
        ok = is_length(value)
        kind = "a length"
    elif role.startswith("font"):
        ok = is_font_family(value)
        kind = "a font family"
    else:
        ok = is_colour(value)
        kind = "a colour"
    if not ok:
        detection.skip(name, f"its value {value!r} is not {kind}, so it does not fill {role}")
        return None
    return value


def _fill_from_variables(
    scheme_name: Scheme, scheme: _Scheme, detection: Detection, heading_fonts: list[str]
) -> None:
    picked = _pick_variables(scheme.variables)
    for role, (name, _spelling, _rank) in picked.items():
        if role in ("accent", "link", "font-heading"):
            continue
        value = _variable_value(role, name, scheme, detection)
        if value is None:
            continue
        token = (
            "--karni-radius"
            if role == "radius"
            else f"--karni-{role}"
            if role.startswith("font")
            else color_token(role)
        )
        scheme.values[token] = Provenance(token, scheme_name, "found", name, value)
    primary = color_token("primary")
    if primary not in scheme.values:
        for fallback in ("accent", "link"):
            if fallback in picked:
                name = picked[fallback][0]
                value = _variable_value(fallback, name, scheme, detection)
                if value is not None:
                    scheme.values[primary] = Provenance(
                        primary,
                        scheme_name,
                        "found",
                        name,
                        value,
                        f"the {fallback} colour, since no primary or brand variable exists",
                    )
                    break
    elif "accent" in picked and picked["accent"][0] != scheme.values[primary].source:
        name = picked["accent"][0]
        value = _variable_value("accent", name, scheme, detection)
        if value is not None and scheme_name == "light":
            detection.skip(
                name,
                "Karni's accent is the quiet hover surface, not a second brand colour",
                f"--karni-color-accent: {value};",
            )
    if "font-heading" in picked and scheme_name == "light":
        name = picked["font-heading"][0]
        value = _variable_value("font-heading", name, scheme, detection)
        if value is not None:
            heading_fonts.append(name)


def _infer(scheme_name: Scheme, scheme: _Scheme, rules: _Rules, detection: Detection) -> None:
    """Fill what the variables did not from ``body``, ``a``, ``button`` and the other rules."""

    def take(token: str, candidates: list[tuple[str, str]], check: Any) -> None:
        if token in scheme.values:
            return
        for group, prop in candidates:
            found = rules.get(group, prop)
            if found is None:
                continue
            value = resolve(found.value, scheme.lookup)
            if value is None:
                detection.skip(
                    found.source,
                    f"its value {found.value!r} reads a variable the stylesheets do not define",
                )
                continue
            if not check(value):
                continue
            scheme.values[token] = Provenance(token, scheme_name, "inferred", found.source, value)
            return

    take(color_token("background"), [("page", "background")], is_colour)
    take(color_token("foreground"), [("page", "color")], is_colour)
    take("--karni-font-sans", [("page", "font")], is_font_family)
    take(color_token("primary"), [("button", "background"), ("link", "color")], is_colour)
    primary = scheme.values.get(color_token("primary"))
    button = rules.get("button", "background")
    if (
        primary is not None
        and button is not None
        and resolve(button.value, scheme.lookup) == primary.value
    ):
        # The buttons are painted in the primary colour: their text colour is its foreground.
        take(color_token("primary-foreground"), [("button", "color")], is_colour)
    take("--karni-radius", [("button", "radius"), ("input", "radius")], is_length)
    take(
        color_token("border"),
        [("input", "border"), ("hr", "border"), ("hr", "background"), ("table", "border")],
        is_colour,
    )
    take(color_token("muted-foreground"), [("muted", "color")], is_colour)
    take(color_token("destructive"), [("danger", "color"), ("danger", "border")], is_colour)


def _derive(scheme_name: Scheme, scheme: _Scheme, detection: Detection) -> None:
    """ring from primary, input from border, primary-foreground by contrast."""
    values = scheme.values
    primary = values.get(color_token("primary"))
    if primary is not None and color_token("ring") not in values:
        values[color_token("ring")] = Provenance(
            color_token("ring"),
            scheme_name,
            "inferred",
            _DERIVED,
            primary.value,
            "the primary colour: the focus ring follows it",
        )
    border = values.get(color_token("border"))
    if border is not None and color_token("input") not in values:
        values[color_token("input")] = Provenance(
            color_token("input"),
            scheme_name,
            "inferred",
            _DERIVED,
            border.value,
            "the border colour: inputs share it",
        )
    if primary is not None and color_token("primary-foreground") not in values:
        parsed = colour.parse(primary.value)
        if parsed is None:
            detection.notes.append(
                f"--karni-color-primary-foreground ({scheme_name}): {primary.value} is written "
                "in a notation this tool does not compute, so no text colour was derived for "
                "primary buttons. Karni's default applies: set the token yourself if it does not "
                "read on your primary."
            )
            return
        candidates = [
            values[token].value
            for token in (color_token("background"), color_token("foreground"))
            if token in values
        ]
        chosen = colour.readable_on(parsed, candidates)
        chosen_colour = colour.parse(chosen)
        ratio = colour.contrast(parsed, chosen_colour) if chosen_colour is not None else 1.0
        values[color_token("primary-foreground")] = Provenance(
            color_token("primary-foreground"),
            scheme_name,
            "inferred",
            _DERIVED,
            chosen,
            f"text on the primary colour, picked for contrast ({ratio:.1f}:1)",
        )


_DEFAULT_REASONS: Final[dict[str, str]] = {
    color_token(
        "primary"
    ): "no primary, brand, accent or link variable, and no button or link rule",
    color_token("primary-foreground"): "no primary colour to derive it from",
    color_token("background"): "no background variable and no body rule with a background",
    color_token("foreground"): "no text colour variable and no body rule with a colour",
    color_token("border"): "no border variable and no input, hr or table rule with a border",
    color_token("input"): "no border colour to derive it from",
    color_token("ring"): "no primary colour to derive it from",
    color_token("muted"): "no muted or secondary surface variable",
    color_token("muted-foreground"): "no muted text variable and no .text-muted or small rule",
    color_token("destructive"): "no danger or error colour",
    "--karni-radius": "no radius variable and no button or input rule with a border-radius",
    "--karni-font-sans": "no font variable and no body rule with a font-family",
    "--karni-font-mono": "no monospace font variable",
}


def detect_css(paths: str | os.PathLike[str] | Iterable[str | os.PathLike[str]]) -> CssDetection:
    """Karni's tokens from the stylesheets at ``paths`` (files, or directories with pages).

    Pure: reads the files and returns the report. See the module docstring for
    the grades (found, inferred, defaulted) and :data:`ROLE_NAMES` /
    :data:`_RULES` for what is recognised. Raises ``CliError`` (``C303``) for a
    path that is missing or holds no stylesheet.
    """
    raw_paths: list[str | os.PathLike[str]] = (
        [paths] if isinstance(paths, str | os.PathLike) else list(paths)
    )
    if not raw_paths:
        raise CliError(
            "--css needs at least one stylesheet or directory, e.g. karni ui detect --css "
            "design/styles.css",
            code="C303",
        )
    notes: list[str] = []
    files = collect_files(raw_paths, notes)
    sheets = [css.parse(_read(file)) for file in files]

    schemes: dict[Scheme, _Scheme] = {"light": _Scheme(), "dark": _Scheme()}
    for sheet in sheets:
        for rule in sheet.rules:
            if rule.theme or not rule.declarations or not _declares_globally(rule):
                continue
            scheme = _scheme_of(rule)
            if scheme is not None:
                schemes[scheme].variables.update(rule.declarations)
    schemes["light"].lookup = dict(schemes["light"].variables)
    schemes["dark"].lookup = {**schemes["light"].variables, **schemes["dark"].variables}

    rules: dict[Scheme, _Rules] = {"light": _Rules(), "dark": _Rules()}
    _read_rules(sheets, rules)

    count = len(files)
    bootstrap = any(name.startswith("--bs-") for name in schemes["light"].variables)
    label = (
        f"{'Bootstrap-style CSS variables' if bootstrap else 'plain CSS'} "
        f"({count} stylesheet{'s' if count != 1 else ''})"
    )
    detection = Detection("css", label, files=[_rel(file) for file in files])
    heading_fonts: list[str] = []
    for scheme_name, material in schemes.items():
        _fill_from_variables(scheme_name, material, detection, heading_fonts)
        _infer(scheme_name, material, rules[scheme_name], detection)
        _derive(scheme_name, material, detection)
    for name in heading_fonts:
        detection.skip(
            name,
            "Karni has sans and mono font tokens only (headings use the sans font)",
            f"--karni-font-sans: {resolve(schemes['light'].variables[name], schemes['light'].lookup)};",
        )

    light, dark = schemes["light"], schemes["dark"]
    dark_colours = any(token not in _NON_COLOUR_TOKENS for token in dark.values)
    background = light.values.get(color_token("background"))
    parsed_background = colour.parse(background.value) if background is not None else None
    dark_design = (
        not dark_colours and parsed_background is not None and colour.is_dark(parsed_background)
    )
    if dark_design:
        colour_scheme: Scheme = "both"
        notes.append(
            "The design is dark (its page background is dark) and has no light variant, so its "
            "colours are written for both of Karni's modes."
        )
    elif not dark_colours:
        colour_scheme = "light"
        if light.values:
            notes.append(
                "No dark variant found: dark mode keeps Karni's dark palette. Add a .dark block "
                "to karni-theme.css to change it."
            )
    else:
        colour_scheme = "light"
        notes.append(
            "Dark colours were read from the stylesheets' dark variant (a .dark or "
            "[data-theme=dark] block, or @media (prefers-color-scheme: dark))."
        )

    result = CssDetection(detection)
    for token in TARGET_TOKENS:
        provenance = light.values.get(token)
        if provenance is None and token in _NON_COLOUR_TOKENS:
            provenance = dark.values.get(token)
        if provenance is None:
            result.defaulted.append((token, _DEFAULT_REASONS[token]))
            continue
        scheme_out: Scheme = "light" if token in _NON_COLOUR_TOKENS else colour_scheme
        provenance = Provenance(
            token,
            scheme_out,
            provenance.category,
            provenance.source,
            provenance.value,
            provenance.note,
        )
        (result.found if provenance.category == "found" else result.inferred).append(provenance)
        detection.add(provenance.source, token, provenance.value, scheme_out, provenance.note)
    if dark_colours:
        for token in TARGET_TOKENS:
            if token in _NON_COLOUR_TOKENS:
                continue
            provenance = dark.values.get(token)
            if provenance is None:
                continue
            (result.found if provenance.category == "found" else result.inferred).append(provenance)
            detection.add(provenance.source, token, provenance.value, "dark", provenance.note)
    detection.notes.extend(notes)
    if not light.values and not dark.values:
        detection.notes.append(
            "Nothing in these stylesheets names a colour, radius or font Karni could read: "
            "no custom property with a known name, and no body, a, button or input rule."
        )
    return result
