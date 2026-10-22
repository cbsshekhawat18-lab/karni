"""Static reading of JavaScript/TypeScript object literals (theme definitions).

``karni ui detect`` never runs a project's MUI, Chakra or Mantine theme: it
reads the literal values in the source. Strings, numbers, booleans, objects
and arrays come back as Python values; anything else (a variable, a function
call, an arrow function, a template with ``${}``, a spread) comes back as a
:class:`NonLiteral` holding its source text, so the report can say exactly
what was not read and why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_NUMBER = re.compile(r"-?(?:\d[\d_]*(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?", re.IGNORECASE)
_MEMBER = re.compile(r"^[A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*|\[[^\]]*\])*$")


@dataclass(frozen=True)
class NonLiteral:
    """A value the source computes (``raw`` is its text, shortened)."""

    raw: str

    @property
    def kind(self) -> str:
        text = self.raw.strip()
        if text.startswith("..."):
            return "spread"
        if "=>" in text or text.startswith(("function", "async ")):
            return "function"
        if text.startswith("`"):
            return "template"
        if _MEMBER.match(text):
            return "variable"
        if text.endswith(")") and "(" in text:
            return "call"
        return "expression"

    def describe(self) -> str:
        """Plain words for the report: why this value was not read."""
        shown = self.raw if len(self.raw) <= 60 else self.raw[:57] + "..."
        return {
            "spread": f"a spread ({shown}), merged at runtime",
            "function": "a function, evaluated by the library at runtime",
            "template": f"a template string with ${{}} ({shown})",
            "variable": f"a variable ({shown}), not a literal value",
            "call": f"a function call ({shown}), computed at runtime",
            "expression": f"an expression ({shown}), computed at runtime",
        }[self.kind]


class _Parser:
    def __init__(self, source: str, pos: int, resolving: frozenset[str] = frozenset()) -> None:
        self.src = source
        self.pos = pos
        #: Names being resolved (``const brand = [...]`` read through ``colors: { brand }``).
        self.resolving = resolving

    def variable(self, name: str) -> Any:
        """A bare name: the literal it is bound to in this file (``const name = ...``), if any."""
        if name in self.resolving or len(self.resolving) >= 3:
            return NonLiteral(name)
        start = resolve_identifier(self.src, name)
        if start is None:
            return NonLiteral(name)
        value = _Parser(self.src, start, self.resolving | {name}).value()
        return NonLiteral(name) if isinstance(value, NonLiteral) else value

    def peek(self) -> str:
        return self.src[self.pos] if self.pos < len(self.src) else ""

    def ws(self) -> None:
        while self.pos < len(self.src):
            if self.src[self.pos].isspace():
                self.pos += 1
            elif self.src.startswith("//", self.pos):
                newline = self.src.find("\n", self.pos)
                self.pos = len(self.src) if newline == -1 else newline
            elif self.src.startswith("/*", self.pos):
                close = self.src.find("*/", self.pos + 2)
                self.pos = len(self.src) if close == -1 else close + 2
            else:
                return

    def string(self) -> str:
        quote = self.src[self.pos]
        self.pos += 1
        out: list[str] = []
        while self.pos < len(self.src) and self.src[self.pos] != quote:
            if self.src[self.pos] == "\\" and self.pos + 1 < len(self.src):
                out.append(self.src[self.pos + 1])
                self.pos += 2
                continue
            out.append(self.src[self.pos])
            self.pos += 1
        self.pos += 1
        return "".join(out)

    def skip_expression(self) -> str:
        """Advance to the next ``,`` or closing bracket at depth 0; return the text skipped."""
        start = self.pos
        depth = 0
        while self.pos < len(self.src):
            char = self.src[self.pos]
            if char in "\"'`":
                self._skip_quoted()
                continue
            if self.src.startswith("//", self.pos) or self.src.startswith("/*", self.pos):
                self.ws()
                continue
            if char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif char == "," and depth == 0:
                break
            self.pos += 1
        return " ".join(self.src[start : self.pos].split())

    def _skip_quoted(self) -> None:
        quote = self.src[self.pos]
        self.pos += 1
        depth = 0
        while self.pos < len(self.src):
            char = self.src[self.pos]
            if char == "\\":
                self.pos += 2
                continue
            if quote == "`" and self.src.startswith("${", self.pos):
                depth += 1
                self.pos += 2
                continue
            if quote == "`" and char == "}" and depth:
                depth -= 1
            elif char == quote and not depth:
                self.pos += 1
                return
            self.pos += 1

    def at_value_end(self) -> bool:
        self.ws()
        return self.peek() in ("", ",", "}", "]", ")", ";")

    def finish(self, start: int, value: Any) -> Any:
        """After a literal: accept ``as const`` / ``satisfies T``; anything else is an expression."""
        if self.at_value_end():
            return value
        match = _IDENT.match(self.src, self.pos)
        if match and match.group(0) in ("as", "satisfies"):
            self.skip_expression()
            return value
        self.pos = start
        return NonLiteral(self.skip_expression())

    def value(self) -> Any:
        self.ws()
        start = self.pos
        char = self.peek()
        if char == "{":
            return self.finish(start, self.object())
        if char == "[":
            return self.finish(start, self.array())
        if char in "\"'":
            return self.finish(start, self.string())
        if char == "`":
            self._skip_quoted()
            text = self.src[start : self.pos]
            if "${" in text:
                self.pos = start
                return NonLiteral(self.skip_expression())
            return self.finish(start, text[1:-1])
        number = _NUMBER.match(self.src, self.pos)
        if number and (char.isdigit() or char in "-."):
            self.pos = number.end()
            text = number.group(0).replace("_", "")
            parsed: float | int = float(text) if any(c in text for c in ".eE") else int(text)
            return self.finish(start, parsed)
        ident = _IDENT.match(self.src, self.pos)
        if ident and ident.group(0) in ("true", "false", "null", "undefined"):
            self.pos = ident.end()
            literal = {"true": True, "false": False, "null": None, "undefined": None}
            return self.finish(start, literal[ident.group(0)])
        raw = self.skip_expression()
        if _IDENT.fullmatch(raw):
            return self.variable(raw)
        return NonLiteral(raw)

    def array(self) -> list[Any]:
        self.pos += 1
        items: list[Any] = []
        while True:
            self.ws()
            char = self.peek()
            if char in ("]", ""):
                self.pos += 1
                return items
            if char == ",":
                self.pos += 1
                continue
            if self.src.startswith("...", self.pos):
                items.append(NonLiteral(self.skip_expression()))
                continue
            items.append(self.value())

    def object(self) -> dict[str, Any]:
        self.pos += 1
        items: dict[str, Any] = {}
        spreads = 0
        while True:
            self.ws()
            char = self.peek()
            if char in ("}", ""):
                self.pos += 1
                return items
            if char == ",":
                self.pos += 1
                continue
            if self.src.startswith("...", self.pos):
                items[f"...{spreads}"] = NonLiteral(self.skip_expression())
                spreads += 1
                continue
            key = self.key()
            self.ws()
            if self.peek() == ":":
                self.pos += 1
                items[key] = self.value()
            elif self.peek() in ("(", "<"):  # method shorthand: foo() { ... }
                start = self.pos
                self.skip_expression()
                items[key] = NonLiteral(f"{key}{self.src[start : self.pos].strip()[:40]}")
            else:  # shorthand property { foo }
                items[key] = self.variable(key)

    def key(self) -> str:
        char = self.peek()
        if char in "\"'":
            return self.string()
        if char == "[":
            start = self.pos
            depth = 0
            while self.pos < len(self.src):
                if self.src[self.pos] == "[":
                    depth += 1
                elif self.src[self.pos] == "]":
                    depth -= 1
                    if depth == 0:
                        self.pos += 1
                        break
                self.pos += 1
            return self.src[start : self.pos]
        match = _IDENT.match(self.src, self.pos) or _NUMBER.match(self.src, self.pos)
        if match is None:  # unreadable: skip the entry
            self.skip_expression()
            return f"?{self.pos}"
        self.pos = match.end()
        word = match.group(0)
        if word in ("get", "set", "async"):  # get foo() { ... }: the key is foo
            save = self.pos
            self.ws()
            inner = _IDENT.match(self.src, self.pos)
            if inner and self.src[inner.end() :].lstrip().startswith("("):
                self.pos = inner.end()
                return inner.group(0)
            self.pos = save
        return word


def parse_value(source: str, pos: int) -> Any:
    """The value starting at ``pos`` (an object literal, usually)."""
    return _Parser(source, pos).value()


def call_arguments(source: str, open_paren: int) -> list[tuple[int, str]]:
    """``(start, text)`` of each top-level argument of the call whose ``(`` is at ``open_paren``."""
    parser = _Parser(source, open_paren + 1)
    found: list[tuple[int, str]] = []
    while parser.pos < len(source):
        parser.ws()
        if parser.peek() in (")", ""):
            break
        start = parser.pos
        text = parser.skip_expression()
        found.append((start, text))
        if parser.peek() == ",":
            parser.pos += 1
    return found


def find_calls(source: str, name: str) -> list[int]:
    """Positions of ``(`` for each call of ``name`` (``createTheme(``, ``createTheme<T>(``)."""
    pattern = re.compile(rf"(?<![\w$.]){re.escape(name)}\s*(?:<[^>()]*>)?\s*\(")
    return [match.end() - 1 for match in pattern.finditer(source)]


def resolve_identifier(source: str, name: str) -> int | None:
    """Where ``const name = <value>`` (or ``let``/``var``, typed or not) starts its value."""
    pattern = re.compile(
        rf"(?:const|let|var)\s+{re.escape(name)}\s*(?::\s*[^=]+?)?=\s*(?!=)", re.MULTILINE
    )
    match = pattern.search(source)
    return match.end() if match else None


def lookup(tree: Any, *path: str) -> Any:
    """``tree[path[0]][path[1]]...``, or None when a step is missing or not an object."""
    node = tree
    for step in path:
        if not isinstance(node, dict) or step not in node:
            return None
        node = node[step]
    return node
