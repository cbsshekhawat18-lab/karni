"""AST-located edits and ruff-clean rendering of generated Python.

Generators never regex-rewrite Python. They parse the file, locate top-level
statements by AST position, and either append a block or replace one
statement's lines. Imports are merged into the leading import block and
re-rendered the way ruff's isort and formatter lay them out (sections,
straight-before-from, order-by-type, wrapping at the project's line length);
a block that carries comments is never re-rendered — missing imports are
appended after it instead.
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass

from karni_cli.generators.core import Workspace
from karni_cli.project import CliError

_DEF_LIKE = re.compile(r"^(class |def |async def |@)")


@dataclass(frozen=True, order=True)
class Import:
    """``from module import name [as alias]``; ``name=None`` is ``import module [as alias]``."""

    module: str
    name: str | None = None
    alias: str | None = None
    level: int = 0


def parse(ws: Workspace, rel: object, text: str) -> ast.Module:
    try:
        return ast.parse(text)
    except SyntaxError as exc:
        raise CliError(
            f"{rel}:{exc.lineno}: cannot parse ({exc.msg}) — fix the file, then re-run.",
            code="C110",
        ) from None


# locating statements


def top_level(tree: ast.Module, name: str) -> ast.stmt | None:
    """The top-level class, function or simple assignment binding ``name``."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name == name:
                return node
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return node
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return node
    return None


def span(lines: list[str], node: ast.stmt) -> tuple[int, int]:
    """1-based ``(first, last)`` lines of ``node``: decorators and the comments right above."""
    decorators = getattr(node, "decorator_list", [])
    first = min([node.lineno, *(d.lineno for d in decorators)])
    while first > 1 and lines[first - 2].lstrip().startswith("#"):
        first -= 1
    last = node.end_lineno or node.lineno
    # Trailing comments indented into the body belong to it (the AST ends at code).
    while last < len(lines):
        following = lines[last]
        indent = len(following) - len(following.lstrip())
        if not following.lstrip().startswith("#") or indent <= node.col_offset:
            break
        last += 1
    return first, last


def replace_span(text: str, first: int, last: int, block: str) -> str:
    lines = text.splitlines()
    lines[first - 1 : last] = block.rstrip("\n").splitlines()
    return "\n".join(lines) + "\n"


def _def_like(block: str) -> bool:
    for line in block.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return bool(_DEF_LIKE.match(stripped))
    return False


def append(text: str, block: str) -> str:
    """``block`` appended as new top-level code, separated the way ruff formats it."""
    body = text.rstrip()
    block = block.strip("\n")
    if not body:
        return block + "\n"
    tree = ast.parse(text)
    last = tree.body[-1] if tree.body else None
    previous_def = isinstance(last, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    gap = "\n\n\n" if _def_like(block) or previous_def else "\n\n"
    return f"{body}{gap}{block}\n"


def replace_or_append(ws: Workspace, rel: object, text: str, name: str, block: str) -> str:
    """Append ``block``; when ``name`` is already bound at top level, replace it (``--force``)."""
    tree = parse(ws, rel, text)
    existing = top_level(tree, name)
    if existing is None:
        return append(text, block)
    ws.refuse_existing(f"{name} in {rel}")
    first, last = span(text.splitlines(), existing)
    return replace_span(text, first, last, block)


# imports


def _bound(tree: ast.Module) -> set[Import]:
    found: set[Import] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            found |= {Import(a.name, None, a.asname) for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found |= {Import(module, a.name, a.asname, node.level) for a in node.names}
    return found


def _leading_run(tree: ast.Module) -> tuple[list[ast.stmt], bool]:
    """The contiguous top-level import statements at the top, and whether a docstring precedes."""
    body = list(tree.body)
    has_doc = bool(
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    )
    run: list[ast.stmt] = []
    for node in body[1:] if has_doc else body:
        if not isinstance(node, ast.Import | ast.ImportFrom):
            break
        run.append(node)
    return run, has_doc


def _member_key(name: str) -> tuple[int, str, str]:
    """ruff's ``order-by-type``: CONSTANTS, then Classes, then functions/variables."""
    if name.isupper() and len(name) > 1:
        kind = 0
    elif name[:1].isupper():
        kind = 1
    else:
        kind = 2
    return kind, name.lower(), name


def _module_key(module: str) -> tuple[str, str]:
    return module.lower(), module


def render_imports(ws: Workspace, imports: set[Import]) -> str:
    """The import block for ``imports`` laid out as ruff's isort does."""
    sections: dict[int, list[Import]] = {}
    for item in imports:
        sections.setdefault(ws.import_section(item.module, item.level), []).append(item)
    blocks: list[str] = []
    for section in sorted(sections):
        items = sections[section]
        lines: list[str] = []
        straight = sorted((i for i in items if i.name is None), key=lambda i: _module_key(i.module))
        for item in straight:
            alias = f" as {item.alias}" if item.alias else ""
            lines.append(f"import {item.module}{alias}")
        grouped: dict[tuple[int, str], list[Import]] = {}
        for item in items:
            if item.name is not None:
                grouped.setdefault((item.level, item.module), []).append(item)
        for level, module in sorted(grouped, key=lambda k: (_module_key(k[1]), k[0])):
            members = grouped[(level, module)]
            source = "." * level + module
            plain = sorted({m.name for m in members if not m.alias and m.name}, key=_member_key)
            if plain:
                lines.append(_from_line(source, plain, ws.line_length))
            aliased = sorted(
                (m for m in members if m.alias), key=lambda m: _member_key(m.name or "")
            )
            for member in aliased:
                lines.append(f"from {source} import {member.name} as {member.alias}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _from_line(source: str, names: list[str], line_length: int) -> str:
    single = f"from {source} import {', '.join(names)}"
    if len(single) <= line_length:
        return single
    body = "".join(f"    {name},\n" for name in names)
    return f"from {source} import (\n{body})"


def ensure_imports(ws: Workspace, rel: object, text: str, wanted: list[Import]) -> str:
    """``text`` with every import in ``wanted`` present (merged into the leading block)."""
    tree = parse(ws, rel, text)
    present = _bound(tree)
    missing = {item for item in wanted if item not in present}
    if not missing:
        return text
    lines = text.splitlines()
    run, has_doc = _leading_run(tree)
    if run:
        first = run[0].lineno
        last = run[-1].end_lineno or run[-1].lineno
        region = lines[first - 1 : last]
        if any("#" in line for line in region):
            # A commented block is never re-rendered: append after it instead.
            addition = render_imports(ws, missing).replace("\n\n", "\n")
            lines[last:last] = addition.splitlines()
            return "\n".join(lines) + "\n"
        merged = _bound(_module_of(run)) | missing
        lines[first - 1 : last] = render_imports(ws, merged).splitlines()
        return "\n".join(lines) + "\n"
    block = render_imports(ws, missing)
    if has_doc:
        doc_end = tree.body[0].end_lineno or tree.body[0].lineno
        head, rest = lines[:doc_end], lines[doc_end:]
    else:
        head, rest = [], lines
    while rest and not rest[0].strip():
        rest.pop(0)
    parts = [*head, *([""] if head else []), *block.splitlines()]
    if rest:
        gap = ["", ""] if _def_like("\n".join(rest)) else [""]
        parts += [*gap, *rest]
    return "\n".join(parts) + "\n"


def _module_of(nodes: list[ast.stmt]) -> ast.Module:
    return ast.Module(body=nodes, type_ignores=[])


# rendering


def pystr(value: str) -> str:
    """A string literal in ruff format's preferred quotes."""
    if '"' in value and "'" not in value:
        return "'" + value.replace("\\", "\\\\") + "'"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def call(
    head: str,
    args: list[str],
    indent: str,
    line_length: int,
    tail: str = "",
    *,
    collection: bool = False,
) -> str:
    """``{indent}{head}(args){tail}`` split the way ruff format splits it.

    ruff format hugs call arguments on one indented line when they fit; a
    collection literal (``collection=True``) that does not fit is always
    split one element per line, with a trailing comma.
    """
    flat = f"{indent}{head}({', '.join(args)}){tail}"
    if len(flat) <= line_length or not args:
        return flat
    inner = f"{indent}    {', '.join(args)}"
    if len(inner) <= line_length and not collection:
        return f"{indent}{head}(\n{inner}\n{indent}){tail}"
    body = "".join(f"{indent}    {arg},\n" for arg in args)
    return f"{indent}{head}(\n{body}{indent}){tail}"


def tuple_literal(head: str, items: list[str], indent: str, line_length: int) -> str:
    """``{indent}{head}(a, b)``: ``(a,)`` for one item, one item per line when too long."""
    if len(items) == 1:
        flat = f"{indent}{head}({items[0]},)"
        if len(flat) <= line_length:
            return flat
    return call(head, items, indent, line_length, collection=True)


def docstring(text: str, indent: str, line_length: int) -> str:
    """A docstring statement wrapped to the line length."""
    flat = f'{indent}"""{text}"""'
    if len(flat) <= line_length:
        return flat
    wrapped = textwrap.wrap(text, width=max(line_length - len(indent) - 3, 20))
    lines = [f'{indent}"""{wrapped[0]}', *(f"{indent}{line}" for line in wrapped[1:])]
    return "\n".join([*lines, f'{indent}"""'])


def comment(text: str, indent: str, line_length: int, prefix: str = "# ") -> str:
    """A comment wrapped to the line length."""
    width = max(line_length - len(indent) - len(prefix), 20)
    return "\n".join(f"{indent}{prefix}{line}" for line in textwrap.wrap(text, width=width))
