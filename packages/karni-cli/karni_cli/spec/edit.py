"""Experimental. Set one key of a ``karni.yaml`` in its text, keeping every comment and the layout.

``karni spec answer`` writes an answer into the file a person or an agent
wrote. Loading the YAML and dumping it again would lose the comments, the
order and the flow style, so :func:`set_value` changes the text itself:

- A key the file does not have yet is added at the end of its mapping: one
  line at the mapping's indentation in a block mapping, ``, key: value``
  before the ``}`` in a flow mapping.
- An empty value (``payments:`` with nothing after it, or ``null``) becomes
  the new mapping, on the key's own line.
- A value that is there already is replaced where it is written.

The value is written the way :mod:`karni_cli.spec.emit` writes a spec (flow
style for a short mapping, a string quoted only when YAML would read it as
something else). Every other character stays as it was. The result is read
back with :func:`karni_cli.spec.source.load`: when its data is not exactly
the old data with that one key set (an anchor shared with another key, a
layout this module cannot place a key in), :class:`EditError` is raised and
nothing should be written.

Override / escape hatch: :func:`set_value` takes and returns text, so a tool
of your own can change a spec in memory, check it with
:func:`karni_cli.spec.validate.validate_text`, and write it when it wants to.
"""

from __future__ import annotations

import copy
from typing import Any

import yaml

from karni_cli.spec import emit
from karni_cli.spec.source import Loc, YamlError, load

__all__ = ["EditError", "set_value", "set_values"]


class EditError(Exception):
    """Experimental. The key cannot be set in the text without changing anything else."""


def set_values(text: str, writes: list[tuple[Loc, Any]]) -> str:
    """Experimental. ``text`` with each ``(path, value)`` of ``writes`` set, in order."""
    for path, value in writes:
        text = set_value(text, path, value)
    return text


def set_value(text: str, path: Loc, value: Any) -> str:
    """Experimental. ``text`` with the key at ``path`` set to ``value``, every other line kept."""
    if not path or not all(isinstance(part, str) for part in path):
        raise EditError(f"{path!r} is not a path of mapping keys.")
    try:
        before = load(text).data
    except YamlError as exc:
        raise EditError(f"the file is not valid YAML ({exc.message})") from None
    if not isinstance(before, dict):
        raise EditError("the file is not a mapping.")
    changed = _edit(text, _compose(text), path, value)
    expected = copy.deepcopy(before)
    _assign(expected, path, value)
    try:
        after = load(changed).data
    except YamlError as exc:  # pragma: no cover - a bug here must never write a file
        raise EditError(f"the change would not be valid YAML ({exc.message})") from None
    if after != expected:
        raise EditError(
            f"setting {'.'.join(str(p) for p in path)} would change more than that key "
            "(an anchor or alias shares it, or the layout has no place for it)."
        )
    return changed


# reading the nodes -------------------------------------------------------------------


def _compose(text: str) -> yaml.MappingNode:
    loader = yaml.SafeLoader(text)
    try:
        node = loader.get_single_node()
    finally:
        loader.dispose()
    if not isinstance(node, yaml.MappingNode):  # pragma: no cover - load() checked it
        raise EditError("the file is not a mapping.")
    return node


def _child(node: yaml.MappingNode, key: str) -> tuple[yaml.Node, yaml.Node] | None:
    """The last ``(key node, value node)`` for ``key`` (YAML keeps the last of a repeated key)."""
    found = None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and str(key_node.value) == key:
            found = (key_node, value_node)
    return found


def _is_null(node: yaml.Node) -> bool:
    return isinstance(node, yaml.ScalarNode) and node.tag == "tag:yaml.org,2002:null"


def _last_line(node: yaml.Node) -> int:
    """The 0-based line of the last character written for ``node`` (its deepest content)."""
    if isinstance(node, yaml.CollectionNode) and node.flow_style:
        return node.end_mark.line  # the closing bracket
    if isinstance(node, yaml.MappingNode):
        return max(
            (max(_last_line(k), _last_line(v)) for k, v in node.value),
            default=node.start_mark.line,
        )
    if isinstance(node, yaml.SequenceNode):
        return max((_last_line(item) for item in node.value), default=node.start_mark.line)
    end = node.end_mark
    if end.column == 0 and end.index > node.start_mark.index:
        return end.line - 1  # a block scalar ends at the start of the next line
    return end.line


# changing the text ---------------------------------------------------------------------


def _nested(path: Loc, value: Any) -> Any:
    for part in reversed(path):
        value = {part: value}
    return value


def _assign(data: dict[str, Any], path: Loc, value: Any) -> None:
    for part in path[:-1]:
        if not isinstance(data.get(str(part)), dict):
            data[str(part)] = {}
        data = data[str(part)]
    data[str(path[-1])] = value


def _edit(text: str, root: yaml.MappingNode, path: Loc, value: Any) -> str:
    node: yaml.MappingNode = root
    flow = False
    for index, part in enumerate(path):
        key = str(part)
        found = _child(node, key)
        flow = flow or bool(node.flow_style)
        if found is None:
            return _insert(text, node, flow, key, _nested(path[index + 1 :], value))
        key_node, value_node = found
        rest = path[index + 1 :]
        if not rest:
            return _replace(text, key_node, value_node, flow, key, value)
        if _is_null(value_node):
            return _replace(text, key_node, value_node, flow, key, _nested(rest, value))
        if not isinstance(value_node, yaml.MappingNode):
            raise EditError(f"{key} holds a value that is not a mapping.")
        node = value_node
    raise EditError("nothing to set.")  # pragma: no cover - the loop always returns


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _insert(text: str, node: yaml.MappingNode, flow: bool, key: str, value: Any) -> str:
    """``key: value`` added at the end of the mapping ``node``."""
    if node.flow_style or flow:
        close = node.end_mark.index - 1
        if text[close : close + 1] != "}":
            raise EditError(f"the mapping that takes {key} has no closing brace.")
        before = close - 1
        while before >= 0 and text[before] in " \t\r\n":
            before -= 1
        item = emit.flow({key: value})[1:-1]
        if text[before] == "{":
            return text[: before + 1] + item + text[before + 1 :]
        joint = " " if text[before] == "," else ", "
        return text[: before + 1] + joint + item + text[before + 1 :]
    if not node.value:  # pragma: no cover - an empty mapping is always written {}
        raise EditError(f"the mapping that takes {key} is empty.")
    indent = node.value[0][0].start_mark.column
    lines = text.splitlines(keepends=True)
    after = min(_last_line(node) + 1, len(lines))
    newline = _newline(text)
    if after and not lines[after - 1].endswith(("\n", "\r")):
        lines[after - 1] += newline
    added = [line + newline for line in emit.entry(key, value, indent)]
    return "".join(lines[:after] + added + lines[after:])


def _replace(
    text: str, key_node: yaml.Node, value_node: yaml.Node, flow: bool, key: str, value: Any
) -> str:
    """The value of ``key`` written over ``value_node``: a scalar, an empty value or ``{...}``."""
    start, end = value_node.start_mark.index, value_node.end_mark.index
    if isinstance(value_node, yaml.MappingNode | yaml.SequenceNode) and not value_node.flow_style:
        raise EditError(f"{key} holds a block that this writer does not replace.")
    if flow or not isinstance(value, dict | list):
        written = emit.flow(value) if flow else _block_scalar(value)
        head = "" if start > 0 and text[start - 1] in " \t" else " "
        return text[:start] + head + written + text[end:]
    lines = emit.entry(key, value, key_node.start_mark.column)
    first = lines[0].lstrip()
    newline = _newline(text)
    changed = text[: key_node.start_mark.index] + first + text[end:]
    if len(lines) == 1:
        return changed
    line_end = changed.find("\n", key_node.start_mark.index)
    rest = "".join(line + newline for line in lines[1:])
    if line_end < 0:
        return changed + newline + rest
    return changed[: line_end + 1] + rest + changed[line_end + 1 :]


def _block_scalar(value: Any) -> str:
    """``value`` as a block mapping's value: the entry ``k: <value>`` without its ``k: ``."""
    (line,) = emit.entry("k", value)
    return line[len("k: ") :]
