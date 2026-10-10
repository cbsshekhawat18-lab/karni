"""Project overrides: ``karni.rules.py`` at the project root.

The file is read **statically** — parsed with :mod:`ast`, every value
evaluated with :func:`ast.literal_eval` — and never imported or executed, so
the CLI and the MCP server can honour it without running project code.
Schema (every name optional)::

    # karni.rules.py
    ADD = [  # project rules; codes are yours (any prefix except K), e.g. P001
        {"code": "P001", "rule": "Money is always a Decimal, never a float.",
         "summary": "Money is Decimal, never float.",      # optional (defaults to rule)
         "category": "project", "severity": "must",          # optional
         "rationale": "...", "fix": "..."},                  # optional
    ]
    OVERRIDE = {"K202": {"summary": "Page files stay at 80 lines or fewer."}}
    DISABLE = ["K304"]
    ADAPTERS = {"disable": ["copilot"], "paths": {"windsurf": ".devin/rules/karni.md"}}

``ADD += [...]`` and ``DISABLE += [...]`` are accepted (the upgrade codemod
appends that way). Anything else at top level is an error that names the line.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .rules import CATEGORIES, RULES, SEVERITIES, Rule

OVERRIDE_FILE = "karni.rules.py"

_NAMES = ("ADD", "OVERRIDE", "DISABLE", "ADAPTERS")
_EXTENDABLE = ("ADD", "DISABLE")
#: Fields a project may change on a Karni rule. ``code`` / ``enforced_by`` are fixed.
OVERRIDABLE_FIELDS = frozenset({"summary", "rule", "rationale", "fix", "severity", "category"})
_ADD_FIELDS = OVERRIDABLE_FIELDS | {"code"}
#: Project codes: 1-3 capitals (never a bare K…, which is Karni's) + 3 digits.
PROJECT_CODE_RE = re.compile(r"^(?!K\d)[A-Z]{1,3}\d{3}$")


class OverrideError(ValueError):
    """``karni.rules.py`` is malformed; the message says where and why (code ``E701``)."""

    code = "E701"

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()} (karni explain {self.code})"


@dataclass
class ProjectOverrides:
    path: Path | None = None
    add: list[dict[str, Any]] = field(default_factory=list)
    override: dict[str, dict[str, Any]] = field(default_factory=dict)
    disable: list[str] = field(default_factory=list)
    adapters: dict[str, Any] = field(default_factory=dict)


def _literal(node: ast.expr, name: str, path: Path) -> Any:
    try:
        return ast.literal_eval(node)
    except ValueError:
        raise OverrideError(
            f"{path}:{node.lineno}: {name} must be a literal (strings, lists, dicts) — "
            "karni.rules.py is read statically and never executed."
        ) from None


def parse_overrides(source: str, path: Path) -> ProjectOverrides:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise OverrideError(f"{path}:{exc.lineno}: syntax error: {exc.msg}") from None
    values: dict[str, Any] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstrings / bare strings
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id in _NAMES
        ):
            name = stmt.targets[0].id
            values[name] = _literal(stmt.value, name, path)
            continue
        if (
            isinstance(stmt, ast.AugAssign)
            and isinstance(stmt.op, ast.Add)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id in _EXTENDABLE
        ):
            name = stmt.target.id
            extra = _literal(stmt.value, name, path)
            if not isinstance(extra, list):
                raise OverrideError(f"{path}:{stmt.lineno}: {name} += expects a list.")
            values[name] = [*values.get(name, []), *extra]
            continue
        raise OverrideError(
            f"{path}:{stmt.lineno}: only literal assignments to {', '.join(_NAMES)} "
            "(and ADD/DISABLE +=) are allowed in karni.rules.py."
        )
    return _validate(values, path)


def _validate(values: dict[str, Any], path: Path) -> ProjectOverrides:
    known = {rule.code for rule in RULES}
    add = values.get("ADD", [])
    override = values.get("OVERRIDE", {})
    disable = values.get("DISABLE", [])
    adapters = values.get("ADAPTERS", {})
    if not isinstance(add, list) or not all(isinstance(e, dict) for e in add):
        raise OverrideError(f"{path}: ADD must be a list of dicts.")
    if not isinstance(override, dict) or not all(isinstance(v, dict) for v in override.values()):
        raise OverrideError(f"{path}: OVERRIDE must map codes to dicts of fields.")
    if not isinstance(disable, list) or not all(isinstance(c, str) for c in disable):
        raise OverrideError(f"{path}: DISABLE must be a list of codes.")
    if not isinstance(adapters, dict) or set(adapters) - {"disable", "paths"}:
        raise OverrideError(f'{path}: ADAPTERS accepts only "disable" and "paths".')

    seen: set[str] = set()
    for entry in add:
        code = entry.get("code")
        if not isinstance(code, str) or not PROJECT_CODE_RE.match(code):
            raise OverrideError(
                f"{path}: ADD code {code!r} must look like P001 (K codes are Karni's)."
            )
        if code in seen:
            raise OverrideError(f"{path}: ADD code {code} is defined twice.")
        seen.add(code)
        if not isinstance(entry.get("rule"), str) or not entry["rule"].strip():
            raise OverrideError(f"{path}: ADD {code} needs a non-empty 'rule'.")
        _check_fields(entry, _ADD_FIELDS, f"ADD {code}", path)
    for code, fields in override.items():
        if code not in known:
            raise OverrideError(f"{path}: OVERRIDE {code} is not a Karni rule code.")
        _check_fields(fields, OVERRIDABLE_FIELDS, f"OVERRIDE {code}", path)
    for code in disable:
        if code not in known:
            raise OverrideError(f"{path}: DISABLE {code} is not a Karni rule code.")
    return ProjectOverrides(
        path=path, add=add, override=override, disable=disable, adapters=adapters
    )


def _check_fields(entry: dict[str, Any], allowed: frozenset[str], where: str, path: Path) -> None:
    unknown = set(entry) - allowed
    if unknown:
        raise OverrideError(f"{path}: {where} has unknown field(s): {', '.join(sorted(unknown))}.")
    for key, value in entry.items():
        if not isinstance(value, str):
            raise OverrideError(f"{path}: {where}.{key} must be a string.")
    if "severity" in entry and entry["severity"] not in SEVERITIES:
        raise OverrideError(f"{path}: {where}.severity must be one of {', '.join(SEVERITIES)}.")


def read_overrides(root: Path | str | None) -> ProjectOverrides:
    """Overrides from ``<root>/karni.rules.py``; empty when there is no file."""
    if root is None:
        return ProjectOverrides()
    path = Path(root) / OVERRIDE_FILE
    if not path.is_file():
        return ProjectOverrides()
    return parse_overrides(path.read_text(encoding="utf-8"), path)


def resolve_rules(overrides: ProjectOverrides) -> list[Rule]:
    """Karni's rules with the project's DISABLE / OVERRIDE / ADD applied, in render order."""
    rules: list[Rule] = []
    for rule in RULES:
        if rule.code in overrides.disable:
            continue
        changes = overrides.override.get(rule.code)
        rules.append(replace(rule, **changes) if changes else rule)
    for entry in overrides.add:
        rules.append(
            Rule(
                code=entry["code"],
                category=entry.get("category", "project"),
                severity=entry.get("severity", "must"),
                summary=entry.get("summary", entry["rule"]),
                rule=entry["rule"],
                rationale=entry.get("rationale", ""),
                fix=entry.get("fix", ""),
            )
        )
    order = {name: i for i, name in enumerate(CATEGORIES)}
    extra = [r.category for r in rules if r.category not in order]
    for name in dict.fromkeys(extra):
        order[name] = len(order)
    return sorted(rules, key=lambda r: (order[r.category], r.code))
