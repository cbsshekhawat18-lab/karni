"""Experimental. ``karni.yaml`` read into plain data, with the line of every key and value.

PyYAML composes the document into nodes, which carry their marks. The data
is rebuilt from those nodes so every key and value keeps its line, which is
what each validation issue points at. Keys are always the text written, so a
field named ``on`` or ``no`` stays a name and does not turn into a boolean.
A key written twice in one mapping is recorded (YAML keeps the last one, and
the first is lost without a word), and anchors and aliases work as usual.

Override / escape hatch: :func:`load` takes any text, so a tool that builds a
spec in memory validates it without a file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

__all__ = ["Loc", "Source", "YamlError", "load"]

#: A location in the document: mapping keys and list indexes, from the top.
Loc = tuple[str | int, ...]


class YamlError(Exception):
    """Experimental. The text is not valid YAML. ``line`` is 1-based, ``None`` when unknown."""

    def __init__(self, message: str, line: int | None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


@dataclass
class Source:
    """Experimental. The document's data, and where each part of it is written."""

    data: Any
    #: path -> line of the value (for a mapping entry, the line of its value).
    lines: dict[Loc, int] = field(default_factory=dict)
    #: path -> line of the key, for mapping entries.
    key_lines: dict[Loc, int] = field(default_factory=dict)
    #: (path of the repeated key, its line, the line of its first occurrence).
    duplicates: list[tuple[Loc, int, int]] = field(default_factory=list)

    def line(self, path: Loc) -> int | None:
        """The line of ``path``, else of its nearest written parent."""
        for end in range(len(path), -1, -1):
            part = path[:end]
            if part in self.key_lines and end == len(path):
                return self.key_lines[part]
            if part in self.lines:
                return self.lines[part]
        return None

    def value_line(self, path: Loc) -> int | None:
        """The line of the value at ``path`` (not of its key), else as :meth:`line`."""
        return self.lines.get(path) or self.line(path)


def load(text: str) -> Source:
    """Experimental. The data of ``text`` with its lines. Raises :class:`YamlError` on a syntax error."""
    loader = yaml.SafeLoader(text)
    try:
        node = loader.get_single_node()
        source = Source(None)
        if node is not None:
            source.data = _build(loader, node, (), source)
        return source
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        line = mark.line + 1 if mark is not None else None
        problem = getattr(exc, "problem", None) or str(exc)
        context = getattr(exc, "context", None)
        message = f"{context}, {problem}" if context else str(problem)
        raise YamlError(message, line) from None
    finally:
        loader.dispose()


def _build(loader: yaml.SafeLoader, node: yaml.Node, path: Loc, source: Source) -> Any:
    source.lines.setdefault(path, node.start_mark.line + 1)
    if isinstance(node, yaml.MappingNode):
        built: dict[str, Any] = {}
        seen: dict[str, int] = {}
        for key_node, value_node in node.value:
            key = str(key_node.value) if isinstance(key_node, yaml.ScalarNode) else "?"
            line = key_node.start_mark.line + 1
            if key in seen:
                source.duplicates.append(((*path, key), line, seen[key]))
            seen[key] = line
            source.key_lines[(*path, key)] = line
            source.lines[(*path, key)] = value_node.start_mark.line + 1
            built[key] = _build(loader, value_node, (*path, key), source)
        return built
    if isinstance(node, yaml.SequenceNode):
        return [
            _build(loader, item, (*path, index), source) for index, item in enumerate(node.value)
        ]
    return loader.construct_object(node, deep=True)
