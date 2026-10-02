"""Karni's agent guidance: rules, procedures, project overrides and file checks.

Stdlib-only and Django-free so the ``karni`` CLI can use it without a project
(in-process when karni is importable, otherwise via
``python -m karni.agent`` in the project's interpreter, otherwise from the
snapshot bundled into karni-cli). :func:`dump` and :func:`check_paths` return
plain JSON-able data — the one contract all three paths share.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .check import check_file, check_source, supported
from .history import active_conditions
from .overrides import OVERRIDE_FILE, OverrideError, read_overrides, resolve_rules
from .rules import CATEGORIES, PROCEDURES, RULES, Procedure, Rule

#: Bumped when the shape of :func:`dump` changes incompatibly.
SCHEMA_VERSION = 1

__all__ = [
    "CATEGORIES",
    "OVERRIDE_FILE",
    "PROCEDURES",
    "RULES",
    "SCHEMA_VERSION",
    "OverrideError",
    "Procedure",
    "Rule",
    "check_file",
    "check_paths",
    "check_source",
    "dump",
    "supported",
]


def _karni_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("karni")
    except PackageNotFoundError:
        return "unknown"


def dump(root: str | Path | None = None) -> dict[str, Any]:
    """Rules (with ``<root>/karni.rules.py`` applied), procedures and adapter overrides.

    A rule with ``when`` set is included only while that condition holds for
    ``root`` (``conditions`` lists the active ones; see
    :func:`karni.agent.history.active_conditions`).
    """
    overrides = read_overrides(root)
    conditions = active_conditions(root)
    rules = [r for r in resolve_rules(overrides) if not r.when or r.when in conditions]
    categories = list(dict.fromkeys([*CATEGORIES, *(r.category for r in rules)]))
    return {
        "schema": SCHEMA_VERSION,
        "karni_version": _karni_version(),
        "categories": [c for c in categories if any(r.category == c for r in rules)],
        "rules": [rule.to_dict() for rule in rules],
        "procedures": [procedure.to_dict() for procedure in PROCEDURES],
        "adapters": overrides.adapters,
        "overrides_file": str(overrides.path) if overrides.path else None,
        "conditions": sorted(conditions),
    }


def check_paths(
    paths: Iterable[str | Path], root: str | Path | None = None
) -> list[dict[str, Any]]:
    """Findings for each path as dicts (``path`` added), honouring DISABLE in overrides."""
    enabled = {rule.code for rule in resolve_rules(read_overrides(root))}
    results: list[dict[str, Any]] = []
    for path in paths:
        for finding in check_file(path, enabled, root):
            results.append({"path": str(path), **finding.to_dict()})
    return results
