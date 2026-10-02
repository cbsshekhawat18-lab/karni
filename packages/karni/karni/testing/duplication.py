"""AST-based duplicate detection for project Python code.

Function/method bodies are normalized (names, docstrings and constants
folded) and hashed; groups of ``min_statements`` or more identical
statements across different locations fail ``karni check``. When one side
of a clone lives in ``karni.*`` the message names the Karni API to reuse.

Opt-out, on either clone's ``def`` line (or the line above)::

    # karni: allow(duplicate): <reason>

Config: ``KARNI_ARCHITECTURE["dup"] = {"min_statements": 8,
"exclude": ["*/migrations/*"]}``.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import karni
from karni.testing._source import (
    Violation,
    check_optout,
    config,
    matches_any,
    project_app_configs,
    project_sources,
    relative,
)


class _Normalizer(ast.NodeTransformer):
    """Fold identifiers, constants and docstrings so only shape remains."""

    def visit_Name(self, node: ast.Name) -> ast.AST:
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        return ast.copy_location(ast.Attribute(value=node.value, attr="_", ctx=node.ctx), node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        return ast.copy_location(ast.Constant(value="_"), node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        return ast.copy_location(ast.arg(arg="_", annotation=None), node)


def _function_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, int] | None:
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # drop the docstring
    if len(body) < 2:
        return None
    module = ast.Module(body=[_Normalizer().visit(stmt) for stmt in body], type_ignores=[])
    ast.fix_missing_locations(module)
    # Statement count includes nested statements (loop/branch bodies), so a
    # function's real size — not just its top level — meets the threshold.
    statements = sum(isinstance(n, ast.stmt) for n in ast.walk(module))
    return ast.dump(module), statements


def _collect(paths: list[Path], origin: str) -> dict[str, list[tuple[str, Path, int]]]:
    groups: dict[str, list[tuple[str, Path, int]]] = defaultdict(list)
    min_statements = int(config("dup")["min_statements"])
    for path in paths:
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                printed = _function_fingerprint(node)
                if printed is None:
                    continue
                fingerprint, statements = printed
                if statements >= min_statements:
                    groups[fingerprint].append((origin, path, node.lineno))
    return groups


def run_check() -> list[str]:
    """``karni.checks`` entry point (reports rule id "duplicate")."""
    exclude = config("dup")["exclude"]
    project_paths = [
        path
        for cfg in project_app_configs()
        for path in project_sources(cfg)
        if not matches_any(path, exclude)
    ]
    karni_paths = list(Path(karni.__file__).parent.rglob("*.py"))

    groups = _collect(project_paths, "project")
    for fingerprint, members in _collect(karni_paths, "karni").items():
        if fingerprint in groups:
            groups[fingerprint].extend(members)

    failures: list[str] = []
    for members in groups.values():
        project_members = [m for m in members if m[0] == "project"]
        if len(members) < 2 or not project_members:
            continue
        karni_members = [m for m in members if m[0] == "karni"]
        remaining: list[Violation] = []
        for _origin, path, lineno in project_members:
            hint = (
                f"reuse {karni_members[0][1].name}:{karni_members[0][2]} from karni"
                if karni_members
                else "extract one shared implementation"
            )
            others = ", ".join(
                f"{relative(p)}:{ln}" for o, p, ln in members if (p, ln) != (path, lineno)
            )
            remaining += check_optout(
                path,
                "duplicate",
                [lineno, lineno - 1],
                Violation(
                    rule="duplicate",
                    location=f"{relative(path)}:{lineno}",
                    message=f"duplicate implementation (also at {others})",
                    hint=hint,
                ),
            )
        failures += [v.render() for v in remaining]
    return failures
