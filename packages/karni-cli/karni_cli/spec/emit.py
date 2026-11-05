"""Experimental. Write spec data as YAML that reads like a hand-written ``karni.yaml``.

Block style for the structure, flow style (``[list, detail]``, ``{name: Staff}``)
for a short list or mapping of plain values that fits on its line, and each
string plain unless YAML would read it as something else, then double-quoted.
Every choice is checked by reading the text back, so :func:`dump` always
round-trips through ``yaml.safe_load``.

:func:`entry` and :func:`flow` write one part in the same style, for
:mod:`karni_cli.spec.edit`, which changes one key of an existing file.

Override / escape hatch: the data is plain, so ``yaml.safe_dump`` writes it
too, without the flow style and the comments.
"""

from __future__ import annotations

import json
from typing import Any

import yaml

__all__ = ["dump", "entry", "flow"]

WIDTH = 96
#: Mappings always written one key per line (they are what a reader scans).
_BLOCK_KEYS = frozenset({"apps", "entities", "fields", "roles", "modules", "features", "app"})


def _scalar(value: Any, *, flow: bool) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    plain = text and text == text.strip() and not any(ch in text for ch in "#\n\t\"'")
    if plain and flow and any(ch in text for ch in ",[]{}:"):
        plain = False
    if plain:
        probe = f"k: [{text}]" if flow else f"k: {text}"
        try:
            loaded = yaml.safe_load(probe)
        except yaml.YAMLError:
            loaded = None
        expected = {"k": [text]} if flow else {"k": text}
        if loaded == expected:
            return text
    return json.dumps(text, ensure_ascii=False)


def _key(key: str) -> str:
    return _scalar(key, flow=True)


def _flow(value: Any) -> str | None:
    """``value`` in flow style, or ``None`` when it holds a nested collection."""
    if isinstance(value, list):
        if any(isinstance(item, dict | list) for item in value):
            return None
        return "[" + ", ".join(_scalar(item, flow=True) for item in value) + "]"
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            inner = _flow(item) if isinstance(item, dict | list) else _scalar(item, flow=True)
            if inner is None:
                return None
            parts.append(f"{_key(key)}: {inner}")
        return "{" + ", ".join(parts) + "}"
    return _scalar(value, flow=True)


def _lines(value: Any, indent: int, key: str | None) -> list[str]:
    pad = " " * indent
    out: list[str] = []
    if isinstance(value, dict):
        for name, item in value.items():
            head = f"{pad}{_key(name)}:"
            out += _entry(head, item, indent, name)
        return out
    for item in value:
        if isinstance(item, dict) and len(item) == 1:
            ((name, inner),) = item.items()
            out += _entry(f"{pad}- {_key(name)}:", inner, indent + 2, name)
        else:
            flow = _flow(item)
            out.append(f"{pad}- {flow}")
    return out


def _entry(head: str, item: Any, indent: int, name: str) -> list[str]:
    if not isinstance(item, dict | list):
        return [f"{head} {_scalar(item, flow=False)}"]
    if not item:
        return [f"{head} {'{}' if isinstance(item, dict) else '[]'}"]
    flow = None if name in _BLOCK_KEYS else _flow(item)
    if flow is not None and len(head) + 1 + len(flow) <= WIDTH:
        return [f"{head} {flow}"]
    return [head, *_lines(item, indent + 2, name)]


def entry(key: str, value: Any, indent: int = 0) -> list[str]:
    """Experimental. The lines of one ``key: value`` entry at ``indent``, as :func:`dump` writes it."""
    return _entry(f"{' ' * indent}{_key(key)}:", value, indent, key)


def flow(value: Any) -> str:
    """Experimental. ``value`` in flow style, as :func:`dump` writes it inside ``{...}``."""
    written = _flow(value)
    return json.dumps(value, ensure_ascii=False) if written is None else written


def dump(data: dict[str, Any], *, header: list[str] | None = None) -> str:
    """Experimental. ``data`` as YAML text, with ``header`` lines as comments on top."""
    lines = [f"# {line}" if line else "#" for line in header or []]
    body = _lines(data, 0, None)
    text = "\n".join([*lines, *body]) + "\n"
    if yaml.safe_load(text) != data:  # pragma: no cover - a bug here must never write a file
        raise AssertionError("the YAML writer does not round-trip this spec")
    return text
