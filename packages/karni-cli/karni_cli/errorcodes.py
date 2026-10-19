"""Error codes: the CLI's own (``C``), and lookup across every registry for ``karni explain``.

Every :class:`~karni_cli.project.CliError` carries a ``C`` code (or passes
through a Karni code such as ``E704``). :func:`lookup` finds any code offline:

- ``E``/``W`` codes: Karni's registry (``karni.errorcodes``), read from the
  monorepo source or the copy bundled into this wheel (``karni_cli/_errorcodes``)
  — no Django, no project needed;
- ``C`` codes: :data:`CODES` below;
- module codes (``PAY001``): ``karni.errorcodes`` entry points installed next to
  karni-cli, else the project interpreter (``python -m karni.errorcodes``);
- ``K`` codes: the agent rules (``karni rules --explain``).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from importlib import resources
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType
from typing import Any, Final, NamedTuple

__all__ = ["CODES", "CliCode", "core_module", "docs_url", "lookup"]

_MODULE_NAME = "karni_cli._bundled_karni_errorcodes"
_FALLBACK_BASE = "https://cbsshekhawat18-lab.github.io/karni/"


class CliCode(NamedTuple):
    code: str
    title: str
    why: str
    fix: str
    source: str
    kind: str = "cli"

    def as_dict(self) -> dict[str, str]:
        return {**self._asdict(), "url": docs_url(self.code)}


def _c(code: str, title: str, source: str, why: str, fix: str) -> CliCode:
    return CliCode(code=code, title=title, why=why, fix=fix, source=source)


CODES: Final[tuple[CliCode, ...]] = (
    # C0xx project and environment
    _c(
        "C001",
        "Not inside a Karni project",
        "karni_cli.project.require_project and every project command",
        "Project commands find the project by walking up to the directory with manage.py "
        "(and config/settings.py).",
        "cd into the project (or a directory below it), or create one: karni new <name>.",
    ),
    _c(
        "C002",
        "No way to run the project's Python",
        "karni_cli.project (runners: serve, migrate, test, shell, seed, ...)",
        "Project commands run in the project's own interpreter: its .venv, else the "
        "active virtualenv (VIRTUAL_ENV), else the running docker compose stack.",
        "Create the venv (python -m venv .venv && .venv/bin/pip install -e .), activate "
        "one that has the project's dependencies, or start the stack (docker compose up "
        "-d). The message says which one the command looked for.",
    ),
    _c(
        "C003",
        "Docker is not installed",
        "karni_cli.project",
        "Without --local, karni runs the project through docker compose.",
        "Install Docker with the compose plugin, or run on the host: karni serve --local "
        "(with a .venv).",
    ),
    _c(
        "C004",
        "These options cannot be combined",
        "karni serve, karni make model/page/schedule",
        "Some options only apply in a particular mode (for example --host needs --local).",
        "Drop one of the options as the message says, or add the option it needs.",
    ),
    _c(
        "C005",
        "This karni-cli install is incomplete",
        "karni_cli (bundled templates, agent rules, changelog, error codes)",
        "The wheel bundles the project template, agent rules, changelog and error codes; "
        "one is missing, so the install is broken.",
        "Reinstall karni-cli (pipx reinstall karni-cli, or pip install --force-reinstall "
        "karni-cli).",
    ),
    _c(
        "C006",
        "An optional tool is not installed",
        "karni mcp, karni types",
        "Some commands need extra tools: the MCP SDK for karni mcp, Node and "
        "openapi-typescript for karni types.",
        "Install what the message names, e.g. pip install 'karni-cli[mcp]', or add "
        "openapi-typescript to frontend devDependencies (Node 20+).",
    ),
    _c(
        "C007",
        "A configuration value is invalid",
        "karni config, KARNI_AGENT_SOURCE, KARNI_TEMPLATES, KARNI_UI_SRC",
        "karni reads its settings from karni config files and a few environment variables.",
        "Use a value the message lists (karni config shows the known settings), or unset "
        "the environment variable.",
    ),
    _c(
        "C008",
        "A file cannot be written",
        "karni config",
        "The file or its directory is not writable.",
        "Check the path's permissions, or set the value per project instead of --global.",
    ),
    _c(
        "C009",
        "A command in the project failed",
        "karni context, karni upgrade, karni rules (project interpreter)",
        "karni ran manage.py or Python in the project and it exited with an error.",
        "Read the project's error in the message (often a settings or import error), fix "
        "it, and re-run. `karni doctor` checks the environment.",
    ),
    _c(
        "C010",
        "The path is not a file inside the project",
        "karni rules --check, karni context --with-history",
        "These commands read files of the current project only.",
        "Pass an existing file path inside the project.",
    ),
    _c(
        "C011",
        "pytest is not installed in the project interpreter",
        "karni test",
        "karni test runs `python -m pytest` through the project's interpreter (its .venv, the "
        "active virtualenv, or the compose service); pytest and pytest-django are in the "
        "project's dev dependency group, not in karni.",
        "Install them there: pip install pytest pytest-django (or `uv sync` for the dev "
        "group), then run karni test again.",
    ),
    # C1xx karni make
    _c(
        "C101",
        "The file karni make would write already exists",
        "karni make (every generator)",
        "Generators never overwrite your code silently.",
        "Pass --force to overwrite (or, for multi-file generators, to create only the "
        "missing files), or remove the file first.",
    ),
    _c(
        "C102",
        "Which app? (none, unknown, or several)",
        "karni make (generators that write into an app)",
        "Generators write into a local app listed in the `# karni:apps` block of "
        "config/settings.py.",
        "Create one (karni make app <name>), or choose one with --app <label>.",
    ),
    _c(
        "C103",
        "The name is not valid here",
        "karni make, karni new",
        "Names become Python modules, classes, URLs or task names, each with its own rules, "
        "and must not shadow existing modules or Django/Karni commands.",
        "Use the form the message shows (snake_case module, CamelCase model, kebab-case "
        "module or route) and a name nothing else uses.",
    ),
    _c(
        "C104",
        "A field spec is invalid",
        "karni make model (name:type[:arg][?] fields)",
        "Fields are written as name:type[:arg][?], e.g. title:str:200 or "
        "starts_at:datetime?; relations name their target model.",
        "Fix the field the message names; `karni make model --help` lists the types.",
    ),
    _c(
        "C105",
        "Something the generator builds on does not exist yet",
        "karni make (viewset, test, serializer, listener, schedule, ...)",
        "Generators wire new code into existing code: a viewset needs its model, a test its "
        "viewset, a listener its event.",
        "Run the karni make command the message names first, then re-run this one.",
    ),
    _c(
        "C106",
        "An option value is invalid",
        "karni make, karni types",
        "The option accepts specific values (the message lists them).",
        "Use one of the values shown, e.g. --access owned:organizer or --every 15m.",
    ),
    _c(
        "C107",
        "The new code would clash with existing code",
        "karni make (component, viewset, schedule, page, service)",
        "Two components claiming one role, two viewsets for one model, or two schedules "
        "or routes with one name would shadow each other.",
        "Extend or edit the existing code the message names, or choose another name.",
    ),
    _c(
        "C108",
        "A karni marker is missing from a project file",
        "karni make, karni add (settings.py and routes.tsx markers)",
        "Generators insert code at `# karni:` / `// karni:` markers that karni new writes; "
        "older or hand-edited projects may lack them.",
        "Add the change by hand as the message shows, or restore the marker from a fresh "
        "karni new project.",
    ),
    _c(
        "C109",
        "An explicit serializer needs a reason",
        "karni make serializer",
        "BaseViewSet generates the serializer from the model (rule K106); a hand-written one "
        "must say why it exists.",
        'Pass --reason "<why>", or tune the generated serializer with APIMeta instead.',
    ),
    _c(
        "C110",
        "A project file cannot be parsed",
        "karni make (reads your Python before editing it)",
        "karni make edits your files structurally and stops rather than guess.",
        "Fix the syntax error at the file and line in the message, then re-run.",
    ),
    _c(
        "C199",
        "Internal error in karni",
        "karni make, karni upgrade",
        "A generator or codemod hit a case it does not handle; nothing was written.",
        "Report it with the command and the file it stopped on. Meanwhile, make the change "
        "by hand.",
    ),
    # C2xx upgrade, rules, types, add
    _c(
        "C201",
        "karni upgrade needs a clean git work tree",
        "karni upgrade",
        "Codemods rewrite many files; a clean tree lets you review and undo them with git.",
        "Commit or stash first, preview with --dry-run, or pass --allow-dirty to write anyway.",
    ),
    _c(
        "C202",
        "karni upgrade does not downgrade",
        "karni upgrade",
        "Codemods only move code forward.",
        "Pass a --to version newer than the project's karni, or check --from.",
    ),
    _c(
        "C203",
        "That is not a version number",
        "karni upgrade (--to / --from)",
        "Versions are MAJOR.MINOR[.PATCH].",
        "Write e.g. --to 0.2 or --to 0.2.0.",
    ),
    _c(
        "C204",
        "No such rule or procedure",
        "karni rules, karni explain",
        "Rules (K codes) and procedures are listed by karni rules.",
        "Run `karni rules` for the codes and procedures, then use one of them.",
    ),
    _c(
        "C205",
        "The agent adapter configuration is invalid",
        "karni rules sync (karni.rules.py ADAPTERS)",
        "Adapters are the generated agent guidance files; each has an id and a line cap.",
        "Use the adapter ids the message lists, and shorten project rules feeding an adapter "
        "that exceeds its cap.",
    ),
    _c(
        "C206",
        "The OpenAPI schema cannot be turned into types",
        "karni types",
        "karni types reads the backend's schema (x-karni-resource operations) to generate "
        "typed hooks.",
        "Make sure the backend serves Karni viewsets (karni routes) and the schema uses only "
        "local $refs.",
    ),
    _c(
        "C207",
        "karni add cannot edit pyproject.toml",
        "karni add",
        "karni add manages the [project].dependencies table of the project's pyproject.toml.",
        "Add the table (or the dependency) by hand, then re-run.",
    ),
)


def core_source_dir() -> Path | None:
    """``karni/errorcodes``: the monorepo source, else the wheel's bundled copy."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "karni" / "karni" / "errorcodes"
        if (candidate / "__init__.py").is_file():
            return candidate
    packaged = resources.files("karni_cli") / "_errorcodes"
    with resources.as_file(packaged) as path:
        if (path / "__init__.py").is_file():
            return path
    return None


def core_module() -> ModuleType | None:
    """``karni.errorcodes`` loaded by path under a private name (no Django needed)."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    directory = core_source_dir()
    if directory is None:
        return None
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, directory / "__init__.py")
    if spec is None or spec.loader is None:  # pragma: no cover - importlib contract
        return None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = loaded
    try:
        spec.loader.exec_module(loaded)
    except Exception:
        del sys.modules[_MODULE_NAME]
        raise
    return loaded


def docs_url(code: str) -> str:
    """The docs link for any code (Karni's single DOCS_BASE_URL)."""
    core = core_module()
    if core is not None:
        return str(core.docs_url(code))
    return f"{_FALLBACK_BASE}errors/#{code.lower()}"


def _module_entries() -> list[Any]:
    found: list[Any] = []
    for entry_point in entry_points(group="karni.errorcodes"):
        try:
            found.extend(entry_point.load())
        except Exception:  # noqa: BLE001, S112 - a broken module must not break explain
            continue
    return found


def _from_project(code: str) -> dict[str, str] | None:
    """Ask the project interpreter (it has the project's modules installed)."""
    from karni_cli import project as project_mod

    project = project_mod.find_project()
    python = project_mod.venv_python(project) if project is not None else None
    if python is None:
        return None
    try:
        proc = subprocess.run(
            [str(python), "-m", "karni.errorcodes", code, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=project,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    data = json.loads(proc.stdout)
    return data if isinstance(data, dict) else None


def lookup(code: str) -> dict[str, str] | None:
    """The entry for ``code`` as a dict (code, title, kind, why, fix, source, url), or None.

    ``K`` codes are not handled here (``karni explain`` renders the rule).
    """
    wanted = code.strip().upper()
    for cli in CODES:
        if cli.code == wanted:
            return cli.as_dict()
    core = core_module()
    if core is not None:
        for entry in (*core.CODES, *_module_entries()):
            if entry.code == wanted:
                return dict(entry.as_dict())
    return _from_project(wanted)
