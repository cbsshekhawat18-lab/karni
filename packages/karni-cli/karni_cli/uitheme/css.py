"""A tolerant CSS reader: the custom properties of each rule, and Tailwind 4 ``@theme`` blocks.

It reads what ``karni ui detect`` needs and nothing more: rules nested in
``@layer``, ``@media`` and ``@supports`` are found; ``@keyframes``,
``@font-face`` and other blocks are skipped. It never raises on odd input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_NESTING_AT_RULES = frozenset(
    {"@media", "@supports", "@layer", "@container", "@scope", "@document", "@starting-style"}
)


@dataclass(frozen=True)
class Rule:
    """One style rule (``selectors``) or one ``@theme`` block (``theme`` holds its prelude)."""

    selectors: tuple[str, ...]
    declarations: dict[str, str]
    context: tuple[str, ...] = ()
    theme: str = ""  # "@theme", "@theme inline", ... ; empty for a style rule


@dataclass
class Stylesheet:
    rules: list[Rule] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)

    def variables(self, selector: str) -> dict[str, str]:
        """Custom properties of every rule whose selector list contains ``selector`` exactly."""
        found: dict[str, str] = {}
        for rule in self.rules:
            if not rule.theme and selector in rule.selectors:
                found.update(rule.declarations)
        return found

    def theme(self) -> dict[str, str]:
        """Every ``@theme`` variable, later blocks winning."""
        found: dict[str, str] = {}
        for rule in self.rules:
            if rule.theme:
                found.update(rule.declarations)
        return found

    def theme_blocks(self) -> list[Rule]:
        return [rule for rule in self.rules if rule.theme]


def strip_comments(text: str) -> str:
    return _COMMENT.sub("", text)


def _skip_string(text: str, i: int) -> int:
    quote = text[i]
    i += 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return i


def _matching_brace(text: str, start: int) -> int:
    """Index of the ``}`` closing the ``{`` at ``start`` (or len(text))."""
    depth = 0
    i = start
    while i < len(text):
        char = text[i]
        if char in "\"'":
            i = _skip_string(text, i)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)


def declarations(body: str) -> dict[str, str]:
    """The custom properties (``--name: value``) declared directly in a block body."""
    found: dict[str, str] = {}
    depth = 0
    start = 0
    i = 0
    parts: list[str] = []
    while i < len(body):
        char = body[i]
        if char in "\"'":
            i = _skip_string(body, i)
            continue
        if char in "({[":
            depth += 1
        elif char in ")}]":
            depth = max(0, depth - 1)
            if char == "}" and depth == 0:
                # A nested rule ends here; whatever came before it is not a declaration.
                start = i + 1
        elif char == ";" and depth == 0:
            parts.append(body[start:i])
            start = i + 1
        i += 1
    parts.append(body[start:])
    for part in parts:
        name, sep, value = part.partition(":")
        name = name.strip()
        if not sep or not name.startswith("--") or "{" in name:
            continue
        found[name] = " ".join(value.split())
    return found


def parse(text: str) -> Stylesheet:
    sheet = Stylesheet()
    _parse_into(sheet, strip_comments(text), ())
    return sheet


def _parse_into(sheet: Stylesheet, text: str, context: tuple[str, ...]) -> None:
    i = 0
    prelude_start = 0
    while i < len(text):
        char = text[i]
        if char in "\"'":
            i = _skip_string(text, i)
            continue
        if char == ";":
            statement = text[prelude_start:i].strip()
            if statement.startswith("@import"):
                match = re.search(r"""["']([^"']+)["']""", statement)
                if match:
                    sheet.imports.append(match.group(1))
            prelude_start = i + 1
        elif char == "{":
            end = _matching_brace(text, i)
            prelude = " ".join(text[prelude_start:i].split())
            body = text[i + 1 : end]
            if prelude.startswith("@"):
                name = prelude.split(" ", 1)[0]
                if name == "@theme":
                    sheet.rules.append(Rule((), declarations(body), context, theme=prelude))
                elif name in _NESTING_AT_RULES:
                    _parse_into(sheet, body, (*context, prelude))
            elif prelude:
                selectors = tuple(s.strip() for s in prelude.split(",") if s.strip())
                sheet.rules.append(Rule(selectors, declarations(body), context))
            i = end + 1
            prelude_start = i
            continue
        elif char == "}":
            prelude_start = i + 1
        i += 1


_HSL_CHANNELS = re.compile(
    r"^-?\d+(\.\d+)?(deg)?\s*,?\s+-?\d+(\.\d+)?%\s*,?\s+-?\d+(\.\d+)?%(\s*/\s*[\d.]+%?)?$"
)
_FULL_COLOUR = re.compile(
    r"^(#[0-9a-f]{3,8}|(rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color|color-mix|light-dark)\(.*\)|"
    r"[a-z]+)$",
    re.IGNORECASE,
)


def is_hsl_channels(value: str) -> bool:
    """``222.2 47.4% 11.2%``: shadcn's Tailwind 3 format (channels for ``hsl()``)."""
    return bool(_HSL_CHANNELS.match(value.strip()))


def is_full_colour(value: str) -> bool:
    return bool(_FULL_COLOUR.match(value.strip())) or value.strip().startswith("var(")


def colour_function(value: str) -> str:
    """The colour notation of a value, for the report: oklch, hsl, hex, ..."""
    value = value.strip().lower()
    if value.startswith("#"):
        return "hex"
    match = re.match(r"([a-z-]+)\(", value)
    return match.group(1) if match else "keyword"
