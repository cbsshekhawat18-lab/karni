"""Experimental. Suggestions from code, the part that reads karni.yaml, the README and the catalog.

``karni check``, ``karni doctor`` and ``karni suggest`` print suggestions: what
Karni could do that the project does by hand, each with its file, line and the
exact command or change. They never fail a run. The detectors that read the
running project (SUG001 to SUG005) live in :mod:`karni.suggestions` and run in
the project's interpreter (``manage.py karni_suggest``). This module adds the
two that need no Django:

* ``SUG006``: a phrase of a module's ``use_when`` list appears in
  ``karni.yaml`` or the README while the module is not added, so
  ``karni add <name>``.
* ``SUG007``: ``karni plan`` is not empty, so ``karni build`` (the project
  follows the spec) or ``karni spec export -o karni.yaml`` (the spec follows
  the code).

and merges both lists (:func:`collect`), renders the compact block
(:func:`render`) and defines the ``--json`` output, whose schema is published
as ``docs/assets/karni-suggestions.schema.json`` (:func:`json_schema`,
``python -m karni_cli.suggest``).

Silencing is the architecture rules' comment form, a reason required:
``# karni: allow(suggest-add-module): <reason>`` on the matching line or the
line above (inside ``<!-- ... -->`` in a README), and for SUG007 on the first
line of ``karni.yaml``. ``KARNI_SUGGESTIONS = False`` as a plain line in
``config/settings.py`` turns every suggestion off, and the CLI reads that
line without starting Django.

Override / escape hatch: the marker per line and the setting per project.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from karni_cli import project as project_mod
from karni_cli.project import CliError

__all__ = [
    "SUGGESTIONS_FILE",
    "SUGGESTIONS_SCHEMA_URL",
    "SUGGESTIONS_VERSION",
    "checked_output",
    "collect",
    "core_suggestions",
    "drift_suggestions",
    "json_schema",
    "module_suggestions",
    "render",
    "turned_off",
]

SUGGESTIONS_VERSION = 1
SUGGESTIONS_SCHEMA_URL = (
    "https://cbsshekhawat18-lab.github.io/karni/assets/karni-suggestions.schema.json"
)
#: Where ``manage.py karni_check --suggestions-file`` writes the project side (never committed).
SUGGESTIONS_FILE = Path(".karni") / "local" / "suggestions.json"

_OFF = re.compile(r"^\s*KARNI_SUGGESTIONS\s*=\s*False\b", re.MULTILINE)
#: The comment form of the architecture rules (karni.testing._source), and its HTML form.
_ALLOW = re.compile(r"(?:#|<!--)\s*karni:\s*allow\(([^)]+)\)\s*:\s*(.*?)\s*(?:-->)?$")
_RULES = {
    "SUG006": "suggest-add-module",
    "SUG007": "suggest-sync-spec",
}
_NO_REASON = " (A karni: allow marker without a reason does not silence it.)"
_SPEC_FILE = "karni.yaml"


def turned_off(project: Path) -> bool:
    """Whether ``config/settings.py`` has a plain ``KARNI_SUGGESTIONS = False`` line."""
    try:
        text = (project / "config" / "settings.py").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return _OFF.search(text) is not None


def _marker(lines: list[str], rule: str, candidates: tuple[int, ...]) -> str | None:
    """``"silenced"``, ``"no-reason"`` or ``None``, as :func:`karni.suggestions.marker`."""
    found: str | None = None
    for number in candidates:
        if not 1 <= number <= len(lines):
            continue
        match = _ALLOW.search(lines[number - 1])
        if match is None or rule not in [name.strip() for name in match.group(1).split(",")]:
            continue
        if match.group(2).strip():
            return "silenced"
        found = "no-reason"
    return found


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _spec_modules(spec_lines: list[str]) -> set[str]:
    """The module names ``karni.yaml`` already lists under ``modules`` (``set()`` if unreadable)."""
    import yaml

    try:
        data = yaml.safe_load("\n".join(spec_lines))
    except yaml.YAMLError:
        return set()
    modules = data.get("modules") if isinstance(data, dict) else None
    if isinstance(modules, dict):
        return {str(name) for name in modules}
    if isinstance(modules, list):
        return {str(name) for name in modules}
    return set()


def module_suggestions(project: Path) -> list[dict[str, Any]]:
    """SUG006: a module's ``use_when`` phrase in karni.yaml or the README, the module not added."""
    from karni_cli import catalog

    texts: list[tuple[str, list[str]]] = []
    spec_lines = _lines(project / _SPEC_FILE)
    if spec_lines:
        texts.append((_SPEC_FILE, spec_lines))
    for name in sorted(path.name for path in project.glob("README*") if path.is_file()):
        texts.append((name, _lines(project / name)))
    if not texts:
        return []
    cat = catalog.load(project, ask_project=False)
    listed = _spec_modules(spec_lines)
    found: list[dict[str, Any]] = []
    for manifest in cat.modules:
        if manifest.name in cat.added or manifest.name in listed:
            continue
        hit = _first_phrase(manifest.use_when, texts)
        if hit is None:
            continue
        file, number, phrase, lines = hit
        state = _marker(lines, _RULES["SUG006"], (number, number - 1))
        if state == "silenced":
            continue
        found.append(
            {
                "code": "SUG006",
                "rule": _RULES["SUG006"],
                "file": file,
                "line": number,
                "message": f"{file} says {phrase!r}, which the module {manifest.name} is for "
                f"({manifest.purpose.rstrip('.')}), and it is not added."
                + (_NO_REASON if state == "no-reason" else ""),
                "fix": f"read karni modules show {manifest.name}, then karni add {manifest.name}",
                "command": f"karni add {manifest.name}",
            }
        )
    return found


def _first_phrase(
    phrases: tuple[str, ...], texts: list[tuple[str, list[str]]]
) -> tuple[str, int, str, list[str]] | None:
    """The first line of the first text that holds one of ``phrases`` as whole words."""
    patterns = [
        (phrase, re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE))
        for phrase in phrases
        if phrase.strip()
    ]
    for file, lines in texts:
        for number, line in enumerate(lines, start=1):
            for phrase, pattern in patterns:
                if pattern.search(line):
                    return file, number, phrase, lines
    return None


def drift_suggestions(
    project: Path, *, docker: bool | None = None, service: str = "django"
) -> list[dict[str, Any]]:
    """SUG007: ``karni plan`` has changes, so the project and karni.yaml disagree.

    Nothing when there is no karni.yaml, when it has problems (``karni spec validate``
    reports them), or when the project cannot be read.
    """
    from karni_cli.builder import record as build_record
    from karni_cli.spec import plan as plan_mod
    from karni_cli.spec.export import read_facts
    from karni_cli.spec.validate import validate_text

    path = project / _SPEC_FILE
    if not path.is_file():
        return []
    spec_lines = _lines(path)
    if _marker(spec_lines, _RULES["SUG007"], (1, 2)) == "silenced":
        return []
    text = "\n".join(spec_lines)
    report = validate_text(text)
    if not report.ok or report.spec is None:
        return []
    try:
        facts = read_facts(project, docker=docker, service=service, command="karni suggest")
        report = validate_text(text, databases=facts.get("databases"))
        if not report.ok or report.spec is None:
            return []
        managed = build_record.load(project).managed()
        result = plan_mod.plan_project(report.spec, facts, project, file=path.name, managed=managed)
    except CliError:
        return []
    if not result.changes:
        return []
    state = _marker(spec_lines, _RULES["SUG007"], (1, 2))
    count, left = len(result.changes), len(result.not_managed)
    kept = f", {left} of them in the project's own code" if left else ""
    return [
        {
            "code": "SUG007",
            "rule": _RULES["SUG007"],
            "file": path.name,
            "line": 1,
            "message": f"karni plan has {count} change{'s' if count != 1 else ''}{kept}: "
            "the project and karni.yaml disagree." + (_NO_REASON if state == "no-reason" else ""),
            "fix": "read karni plan, then karni build to bring the project to the spec, or "
            "karni spec export -o karni.yaml --force to take the code's side",
            "command": "karni plan",
        }
    ]


def core_suggestions(
    project: Path, *, docker: bool | None = None, service: str = "django"
) -> tuple[bool, list[dict[str, Any]]]:
    """``manage.py karni_suggest --json`` in the project: ``(enabled, suggestions)``.

    :raises CliError: ``C780`` for a karni without the command, ``C781`` for a command that failed.
    """
    proc = project_mod.run_manage(
        project, ["karni_suggest", "--json"], docker=docker, service=service
    )
    if proc.returncode != 0:
        if "Unknown command" in (proc.stderr or ""):
            raise CliError(
                "The project's karni predates suggestions (manage.py has no karni_suggest). "
                "Upgrade karni in the project (pip install -U karni).",
                code="C780",
            )
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise CliError(
            "manage.py karni_suggest failed, so there are no suggestions "
            f"({' '.join(detail) or f'exit {proc.returncode}'}). Run it directly to see why.",
            code="C781",
        )
    try:
        data = json.loads(proc.stdout)
        return bool(data["enabled"]), list(data["suggestions"])
    except (ValueError, KeyError, TypeError):
        raise CliError(
            "manage.py karni_suggest did not print its JSON. Something in the project prints to "
            "stdout at startup.",
            code="C781",
        ) from None


def collect(
    project: Path,
    core: tuple[bool, list[dict[str, Any]]] | None,
    *,
    docker: bool | None = None,
    service: str = "django",
) -> dict[str, Any]:
    """The merged output: the project's own suggestions (``core``) and this module's.

    ``core`` is ``(enabled, suggestions)`` from the project's interpreter, ``None`` when it
    could not be asked (this module's suggestions still run, unless the project turned
    them off in ``config/settings.py``).
    """
    enabled = core[0] if core is not None else True
    if turned_off(project):
        enabled = False
    items: list[dict[str, Any]] = []
    if enabled:
        items = list(core[1]) if core is not None else []
        items += module_suggestions(project)
        items += drift_suggestions(project, docker=docker, service=service)
        items.sort(key=lambda row: (row["code"], row["file"], row["line"] or 0))
    return checked_output(
        {"version": SUGGESTIONS_VERSION, "enabled": enabled, "suggestions": items}
    )


def render(data: dict[str, Any]) -> str:
    """The compact block: one entry per suggestion, ``""`` when there is none."""
    rows = data["suggestions"]
    if not rows:
        return ""
    lines = [f"suggestions ({len(rows)}), they never fail the run:"]
    for row in rows:
        where = row["file"] if row["line"] is None else f"{row['file']}:{row['line']}"
        lines.append(f"  [{row['code']}] {where}: {row['message']}")
        lines.append(f"      fix: {row['fix']}")
    lines.append(
        "  Silence one with `# karni: allow(<rule>): <reason>`, see `karni explain <code>`."
    )
    return "\n".join(lines)


# the JSON output's schema ---------------------------------------------------------


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _SuggestionOut(_Out):
    """One suggestion."""

    code: str = Field(description="The code, SUG001 to SUG007 (karni explain <code>).")
    rule: str = Field(
        description="The rule id a `# karni: allow(<rule>): <reason>` marker names to silence it."
    )
    file: str = Field(description="The file, relative to the project root.")
    line: int | None = Field(description="The 1-based line, null when the whole file.")
    message: str = Field(description="What the project does by hand.")
    fix: str = Field(description="The exact change or command.")
    command: str | None = Field(
        description="The command to run when the fix is one (karni remove charts), else null."
    )


class _SuggestionsOut(_Out):
    """Experimental. The output of karni suggest --json."""

    version: Literal[1] = Field(description="The version of this output: 1.")
    enabled: bool = Field(
        description="false when the project turned suggestions off (KARNI_SUGGESTIONS = False)."
    )
    suggestions: list[_SuggestionOut] = Field(
        description="The suggestions, by code, then file and line. They never fail a run."
    )


def json_schema() -> dict[str, Any]:
    """Experimental. The JSON Schema of ``karni suggest --json``, as published at the URL."""
    from karni_cli.spec.schema import _tidy

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SUGGESTIONS_SCHEMA_URL,
        "title": "karni suggest --json",
        "description": (
            "Experimental. What Karni could do that the project does by hand. Generated by "
            "python -m karni_cli.suggest. Never edit it by hand."
        ),
        **_tidy(_SuggestionsOut.model_json_schema()),
    }


def checked_output(data: dict[str, Any]) -> dict[str, Any]:
    """``data`` checked against the published schema's models (raises when they disagree)."""
    return _SuggestionsOut.model_validate(data).model_dump(mode="json")


if __name__ == "__main__":  # pragma: no cover - python -m karni_cli.suggest
    print(json.dumps(json_schema(), indent=2, sort_keys=False))
