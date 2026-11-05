"""Experimental. The app-builder flow as functions that return JSON: Karni's MCP tools for it.

``karni mcp`` serves them beside ``context``, ``rules`` and ``check``. Each
does what a command does and returns what that command's ``--json`` prints:

- :func:`spec_validate`: ``karni spec validate --json``.
- :func:`plan`: ``karni plan --json`` (``karni-plan.schema.json``).
- :func:`questions`: ``karni plan --questions --json`` (``karni-questions.schema.json``).
- :func:`answer`: ``karni spec answer``, the keys it set and the questions left.
- :func:`build`: ``karni build --json`` (``karni-build.schema.json``). It never
  takes ``--force`` or ``--adopt``: a Karni-owned file edited by hand returns
  ``C273`` and the three ways on, and the agent asks the user which to take.
- :func:`modules`: the module catalog (``karni modules list|show``), a short
  line per entry, or one entry in full.
- :func:`recipes`: ``karni recipes list|show --json`` (``karni-recipes.schema.json``).

A failure the command reports as an error comes back as ``{"error": {"code",
"message"}}`` (:func:`run`). Every result follows ``$defs/<tool>`` of
``docs/assets/karni-mcp.schema.json`` (regenerate it with ``python -m
karni_cli.agent_tools > docs/assets/karni-mcp.schema.json``).

Karni never calls a language model here: the agent reads these results and
decides. Override / escape hatch: each function is plain and takes the
project root, so a tool other than the MCP server calls it the same way.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import models_json_schema

from karni_cli.project import CliError

__all__ = [
    "MCP_SCHEMA_URL",
    "MCP_VERSION",
    "TOOLS",
    "answer",
    "build",
    "checked",
    "json_schema",
    "modules",
    "plan",
    "questions",
    "recipes",
    "run",
    "spec_validate",
]

#: Experimental. The version of the results that are not another command's output.
MCP_VERSION: Final = 1
#: Experimental. Where the JSON Schema of the tools' results is published.
MCP_SCHEMA_URL: Final = "https://cbsshekhawat18-lab.github.io/karni/assets/karni-mcp.schema.json"
#: Experimental. The tools, in the order of the flow.
TOOLS: Final = (
    "recipes",
    "spec_validate",
    "questions",
    "answer",
    "plan",
    "build",
    "modules",
)
_SPEC: Final = "karni.yaml"


def run(call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Experimental. ``call()``'s result, or ``{"error": {"code", "message"}}`` for a CliError.

    Anything printed meanwhile goes to stderr: on ``karni mcp``, stdout is the
    protocol.
    """
    try:
        with contextlib.redirect_stdout(sys.stderr):
            return call()
    except CliError as exc:
        return {"error": {"code": exc.code, "message": exc.message}}


def _spec_path(root: Path | None, spec: str) -> tuple[Path, str]:
    """The spec file and its name as shown: ``spec`` (relative to the project), else karni.yaml."""
    if spec:
        path = Path(spec)
        if not path.is_absolute():
            path = (root or Path.cwd()) / path
        shown = spec
    else:
        path, shown = (root or Path.cwd()) / _SPEC, _SPEC
    if not path.is_file():
        raise CliError(
            f"No spec at {path}. Write one (docs/app-spec.md), start one from a recipe "
            "(karni recipes list --match), or pass the spec's path.",
            code="C210",
        )
    return path, shown


def _require(root: Path | None) -> Path:
    if root is None:
        raise CliError("No manage.py found here or above. Run inside a Karni project.", code="C001")
    return root


def spec_validate(root: Path | None, path: str = "") -> dict[str, Any]:
    """Experimental. ``karni spec validate --json``: ``{file, valid, issues}``."""
    from karni_cli.spec.validate import validate_text

    found, shown = _spec_path(root, path)
    report = validate_text(found.read_text(encoding="utf-8"))
    return checked(
        "spec_validate",
        {"file": shown, "valid": report.ok, "issues": [i.as_dict() for i in report.issues]},
    )


def _facts_and_report(root: Path, path: Path, command: str) -> tuple[Any, Any]:
    """The spec validated as ``karni plan`` and ``karni build`` do: then with the databases."""
    from karni_cli.spec.export import read_facts
    from karni_cli.spec.validate import validate_text

    text = path.read_text(encoding="utf-8")
    report = validate_text(text)
    facts = None
    if report.ok:
        facts = read_facts(root, docker=None, service="django", command=command, code="C250")
        report = validate_text(text, databases=facts.get("databases"))
    return facts, report


def plan(root: Path | None, spec: str = "") -> dict[str, Any]:
    """Experimental. ``karni plan --json``: what karni build would change. Writes nothing."""
    from karni_cli.builder import record as build_record
    from karni_cli.spec import plan as plan_mod

    project = _require(root)
    path, shown = _spec_path(project, spec)
    facts, report = _facts_and_report(project, path, "karni plan")
    if not report.ok or report.spec is None or facts is None:
        return plan_mod.invalid_output(shown, [issue.as_dict() for issue in report.issues])
    managed = build_record.load(project).managed()
    result = plan_mod.plan_project(report.spec, facts, project, file=shown, managed=managed)
    plan_mod.apply_counts(result, plan_mod.manage_counter(project, docker=None, service="django"))
    return plan_mod.checked_output(result.as_dict())


def questions(root: Path | None, spec: str = "", limit: int = 5) -> dict[str, Any]:
    """Experimental. ``karni plan --questions --json``: the questions for the user, at most ``limit``.

    ``limit`` 0 returns them all. Reads only the spec.
    """
    from karni_cli.spec import questions as questions_mod
    from karni_cli.spec.validate import validate_text

    path, shown = _spec_path(root, spec)
    report = validate_text(path.read_text(encoding="utf-8"))
    if not report.ok or report.spec is None or report.source is None:
        issues = [issue.as_dict() for issue in report.issues]
        return questions_mod.invalid_output(shown, issues, limit)
    found = questions_mod.questions(report.spec, report.source.data)
    return questions_mod.output(found, limit, file=shown)


def answer(root: Path | None, question_id: str, value: str, spec: str = "") -> dict[str, Any]:
    """Experimental. ``karni spec answer``: the answer written into the spec, every other line kept.

    Returns ``{version, file, valid, issues, id, keys, open, next}``. An id
    that is not open (C400), a value the question does not take (C401) and an
    answer that cannot be written (C402) are errors: nothing is written.
    """
    from karni_cli.spec import questions as questions_mod
    from karni_cli.spec.validate import validate_text

    path, shown = _spec_path(root, spec)
    text = path.read_text(encoding="utf-8")
    report = validate_text(text)
    base = {"version": MCP_VERSION, "file": shown, "id": question_id}
    if not report.ok or report.spec is None or report.source is None:
        issues = [issue.as_dict() for issue in report.issues]
        return checked(
            "answer",
            {
                **base,
                "valid": False,
                "issues": issues,
                "keys": [],
                "open": 0,
                "next": "fix the spec's problems (spec_validate), then questions",
            },
        )
    found = questions_mod.questions(report.spec, report.source.data)
    answered = questions_mod.answer(text, found, question_id, value, file=shown)
    path.write_text(answered.text, encoding="utf-8")
    left = answered.open
    return checked(
        "answer",
        {
            **base,
            "valid": True,
            "issues": [],
            "keys": list(answered.keys),
            "open": left,
            "next": (
                f"questions: {left} question{'s are' if left != 1 else ' is'} open"
                if left
                else "plan, then build: no question is open"
            ),
        },
    )


#: What the agent does with the three ways on that a hand edit returns.
_ASK_THE_USER: Final = (
    "ask the user which of the three ways on to take. The MCP tool build never forces or "
    "adopts: 2 and 3 are karni build commands the user runs or approves. "
)


def build(
    root: Path | None, spec: str = "", dry_run: bool = False, allow_destructive: bool = False
) -> dict[str, Any]:
    """Experimental. ``karni build --json``: the project made to match the spec.

    Never ``--force`` or ``--adopt``: a Karni-owned file edited by hand stops
    the build with ``C273``, and ``next`` tells the agent to ask the user
    which of the three ways on to take.
    """
    from karni_cli.builder.run import Options, Result
    from karni_cli.builder.run import build as run_build

    project = _require(root)
    path, shown = _spec_path(project, spec)
    facts, report = _facts_and_report(project, path, "karni build")
    if not report.ok or report.spec is None or facts is None:
        invalid = Result(shown, status="invalid", issues=[i.as_dict() for i in report.issues])
        return invalid.as_dict()
    opts = Options(dry_run=dry_run, allow_destructive=allow_destructive)
    result = run_build(project, report.spec, facts, shown, opts)
    if result.code == "C273" and result.next:
        result.next = _ASK_THE_USER + result.next
    return result.as_dict()


def modules(root: Path | None, name: str = "") -> dict[str, Any]:
    """Experimental. The module catalog: a line per module and feature, or ``name`` in full.

    Without ``name``: ``{version, modules: [{name, kind, status, state, purpose,
    use_when}], problems}``. With it: ``{version, module, problems}``, the
    entry as ``karni modules show --json`` prints it (C313 when there is none).
    """
    from karni_cli import catalog as catalog_mod

    loaded = catalog_mod.load(root)
    if name:
        manifest = loaded.get(name)
        if manifest is None:
            known = ", ".join(sorted(loaded.entries))
            raise CliError(f"The catalog has no {name!r} (it has {known}).", code="C313")
        entry = {**manifest.to_dict(), "state": loaded.state(manifest)}
        return checked(
            "modules",
            {"version": MCP_VERSION, "module": entry, "problems": loaded.problems},
        )
    lines = [
        {
            "name": manifest.name,
            "kind": manifest.kind,
            "status": manifest.status,
            "state": loaded.state(manifest),
            "purpose": manifest.purpose,
            "use_when": list(manifest.use_when),
        }
        for manifest in [*loaded.modules, *loaded.features]
    ]
    return checked(
        "modules", {"version": MCP_VERSION, "modules": lines, "problems": loaded.problems}
    )


def recipes(root: Path | None, match: str = "", name: str = "") -> dict[str, Any]:
    """Experimental. ``karni recipes``: every recipe, the best few for ``match``, or ``name``.

    ``name`` ``blank`` is the blank start. C420 when there is no such recipe, C421 when it
    cannot be used.
    """
    from karni_cli import recipes as recipes_mod
    from karni_cli.recipes import output

    loaded = recipes_mod.load()
    app = recipes_mod.app_name(root)
    if name:
        return output.shown(loaded, name, app_name=app)
    if match:
        return output.matched(loaded, match, app_name=app)
    return output.listing(loaded, app_name=app)


# the results' schema ---------------------------------------------------------------


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ErrorBody(_Out):
    code: str | None = Field(description="The error code (karni explain <code>).")
    message: str = Field(description="What went wrong, and what to do.")


class _ErrorOut(_Out):
    """A failure the command reports as an error. Nothing was written."""

    error: _ErrorBody


class _IssueOut(_Out):
    """A problem in the spec, as karni spec validate --json reports it."""

    code: str = Field(description="The error code (karni explain <code>).")
    line: int | None = Field(description="The 1-based line, when known.")
    path: str = Field(description="The dotted path of the key.")
    message: str = Field(description="What is wrong.")
    fix: str = Field(description="How to fix it.")


class _ValidateOut(_Out):
    """spec_validate: what karni spec validate --json prints."""

    file: str = Field(description="The spec file, as given.")
    valid: bool = Field(description="true when the spec has no problem.")
    issues: list[_IssueOut] = Field(description="Every problem, with its code, line and fix.")


class _AnswerOut(_Out):
    """answer: the answer written into the spec (karni spec answer)."""

    version: Literal[1] = Field(description="The version of this result: 1.")
    file: str = Field(description="The spec file, as given.")
    valid: bool = Field(description="false when the spec has problems: nothing was written.")
    issues: list[_IssueOut] = Field(description="The spec's problems (karni spec validate's).")
    id: str = Field(description="The question answered.")
    keys: list[str] = Field(description="The dotted keys of karni.yaml the answer set.")
    open: int = Field(description="How many questions are open now.")
    next: str = Field(description="What to do next.")


class _AskOut(_Out):
    question: str
    setting: str
    options: list[Any]
    default: Any = None
    multiple: bool


class _EntryOut(_Out):
    path: str
    why: str
    manual: bool


class _ProvidesOut(_Out):
    models: list[str]
    endpoints: list[str]
    pages: list[str]
    settings: dict[str, list[str]]
    ui: str


class _WiringOut(_Out):
    apps: list[str]
    settings: str
    middleware: list[_EntryOut]
    context_processors: list[_EntryOut]
    urls: str
    kind: str
    extras: dict[str, str]


class _ModuleOut(_Out):
    """One module or feature in full, as karni modules show --json prints it."""

    name: str
    kind: Literal["module", "feature"]
    title: str
    purpose: str
    status: str
    use_when: list[str]
    requires: list[str]
    conflicts: list[str]
    services: list[str]
    docs: str
    provides: _ProvidesOut
    asks: list[_AskOut]
    state: Literal["added", "installed", "available", "built in"]
    distribution: str | None = Field(None, description="A module's PyPI name.")
    wiring: _WiringOut | None = Field(None, description="What karni add writes, for a module.")
    switch: str | None = Field(None, description="The setting that turns a feature on.")
    extra: str | None = Field(None, description="The karni extra a feature needs.")
    in_spec: bool | None = Field(None, description="false: karni.yaml has no key for the feature.")


class _ModuleLineOut(_Out):
    """One module or feature in a line."""

    name: str = Field(description="modules(name) shows it in full.")
    kind: Literal["module", "feature"]
    status: str
    state: Literal["added", "installed", "available", "built in"]
    purpose: str
    use_when: list[str]


class _ModulesOut(_Out):
    """modules(): every module and feature in a line."""

    version: Literal[1] = Field(description="The version of this result: 1.")
    modules: list[_ModuleLineOut] = Field(description="Modules first, then features.")
    problems: list[str] = Field(description="Manifests that could not be read (C314).")


class _ModuleShownOut(_Out):
    """modules(name): one module or feature in full."""

    version: Literal[1] = Field(description="The version of this result: 1.")
    module: _ModuleOut
    problems: list[str] = Field(description="Manifests that could not be read (C314).")


#: The models of each result this module defines.
_MODELS: Final[dict[str, tuple[type[BaseModel], ...]]] = {
    "spec_validate": (_ValidateOut,),
    "answer": (_AnswerOut,),
    "modules": (_ModulesOut, _ModuleShownOut),
}


def _published() -> dict[str, str]:
    """The tools whose result is another command's published output, and its schema."""
    from karni_cli.builder.output import BUILD_SCHEMA_URL
    from karni_cli.recipes.output import RECIPES_SCHEMA_URL
    from karni_cli.spec.plan import PLAN_SCHEMA_URL
    from karni_cli.spec.questions import QUESTIONS_SCHEMA_URL

    return {
        "plan": PLAN_SCHEMA_URL,
        "questions": QUESTIONS_SCHEMA_URL,
        "build": BUILD_SCHEMA_URL,
        "recipes": RECIPES_SCHEMA_URL,
    }


def json_schema() -> dict[str, Any]:
    """Experimental. The JSON Schema of the tools' results: ``$defs/<tool>`` for each tool."""
    from karni_cli.spec.schema import _tidy

    models = [model for group in _MODELS.values() for model in group] + [_ErrorOut]
    _, generated = models_json_schema(
        [(model, "validation") for model in models], ref_template="#/$defs/{model}"
    )
    defs: dict[str, Any] = _tidy(generated["$defs"])
    error = {"$ref": "#/$defs/_ErrorOut"}
    published = _published()
    for tool in TOOLS:
        if tool in published:
            own = [{"$ref": published[tool]}]
        else:
            own = [{"$ref": f"#/$defs/{model.__name__}"} for model in _MODELS[tool]]
        defs[tool] = {"anyOf": [*own, error]}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": MCP_SCHEMA_URL,
        "title": "karni mcp: the app-builder tools' results",
        "description": (
            "Experimental. What the MCP tools " + ", ".join(TOOLS) + " return: $defs/<tool> "
            "for each. plan, questions, build and recipes return their command's --json "
            "output, whose schema is published beside this one. Generated by python -m "
            "karni_cli.agent_tools. Never edit it by hand."
        ),
        "anyOf": [{"$ref": f"#/$defs/{tool}"} for tool in TOOLS],
        "$defs": dict(sorted(defs.items())),
    }


def checked(tool: str, data: dict[str, Any]) -> dict[str, Any]:
    """Experimental. ``data`` checked against the models of ``tool``'s result (raises on a mismatch).

    Keys the data leaves out (a feature's ``wiring``) stay out.
    """
    errors: list[Exception] = []
    for model in _MODELS[tool]:
        try:
            return model.model_validate(data).model_dump(mode="json", exclude_unset=True)
        except ValueError as exc:
            errors.append(exc)
    raise errors[0]


if __name__ == "__main__":  # pragma: no cover - python -m karni_cli.agent_tools
    print(json.dumps(json_schema(), indent=2, sort_keys=False))
