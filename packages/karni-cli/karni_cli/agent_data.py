"""Where the CLI gets Karni's agent rules from (``karni.agent``).

The CLI never imports project code, but ``karni.agent`` is Karni's own
stdlib-only data module, so it may be imported when available. Resolution
(first that works; force one with ``KARNI_AGENT_SOURCE=local|project|bundled``):

1. ``local``   — ``import karni.agent`` in the CLI's own environment.
2. ``project`` — ``python -m karni.agent`` through the project's interpreter
   (``.venv``, else a running compose service — the same resolution as
   ``karni context``); answers with the project's own karni version.
3. ``bundled`` — the copy of ``karni/agent`` shipped inside karni-cli (the
   monorepo source when run from a checkout), loaded by path. This is what
   ``karni new`` uses on a machine where only karni-cli is installed.

Every path yields the same JSON-able shape (``karni.agent.dump``), so the
renderers below never care which one answered.

History providers (``karni.agent.history``, :func:`history_module`) are the
exception: they always run in the CLI's own environment, and in ``project``
mode the CLI hands its detection to the project interpreter
(``KARNI_AGENT_CONDITIONS``) so conditional rules follow the same providers.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import ModuleType
from typing import Any

from karni_cli import project as project_mod
from karni_cli.project import CliError

SOURCES = ("local", "project", "bundled")
_BUNDLED_NAME = "karni_cli._bundled_karni_agent"


@dataclass(frozen=True)
class AgentData:
    raw: dict[str, Any]
    source: str

    @property
    def rules(self) -> list[dict[str, Any]]:
        return list(self.raw["rules"])

    @property
    def procedures(self) -> list[dict[str, Any]]:
        return list(self.raw["procedures"])

    @property
    def categories(self) -> list[str]:
        return list(self.raw["categories"])

    @property
    def adapter_overrides(self) -> dict[str, Any]:
        return dict(self.raw.get("adapters") or {})

    def rule(self, code: str) -> dict[str, Any] | None:
        return next((r for r in self.rules if r["code"] == code.upper()), None)

    def procedure(self, name: str) -> dict[str, Any] | None:
        return next((p for p in self.procedures if p["name"] == name), None)


def _local() -> ModuleType | None:
    try:
        from karni import agent
    except ImportError:
        return None
    return agent


def _bundled_dir() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "karni" / "karni" / "agent"
        if (candidate / "rules.py").is_file():
            return candidate
    packaged = resources.files("karni_cli") / "_agent"
    with resources.as_file(packaged) as path:
        if (path / "rules.py").is_file():
            return path
    return None


def _bundled() -> ModuleType | None:
    if _BUNDLED_NAME in sys.modules:
        return sys.modules[_BUNDLED_NAME]
    directory = _bundled_dir()
    if directory is None:
        return None
    spec = importlib.util.spec_from_file_location(
        _BUNDLED_NAME, directory / "__init__.py", submodule_search_locations=[str(directory)]
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_BUNDLED_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[_BUNDLED_NAME]
        raise
    return module


def history_module() -> ModuleType | None:
    """``karni.agent.history`` for the CLI's own environment.

    History providers always run in the CLI's environment (third-party
    providers are discovered from its entry points): karni's module when
    importable here (unless ``KARNI_AGENT_SOURCE=bundled``), else the bundled
    copy, which carries the built-in Gigai Chronicle provider by itself.
    """
    if os.environ.get("KARNI_AGENT_SOURCE", "").strip() != "bundled":
        try:
            from karni.agent import history

            return history
        except ImportError:
            pass  # karni absent here, or a karni older than history providers
    bundled = _bundled()
    if bundled is None:
        return None
    try:
        return importlib.import_module(f"{bundled.__name__}.history")
    except ImportError:
        return None


def _conditions_env(project: Path) -> dict[str, str]:
    """The CLI's own condition detection, handed to the project interpreter so a
    conditional rule follows the same providers as ``karni context --with-history``
    (and a compose container that cannot see a store above its mount)."""
    module = history_module()
    if module is None:
        return {}
    return {module.CONDITIONS_ENV: ",".join(sorted(module.active_conditions(project)))}


def _project_command(project: Path, env: dict[str, str] | None = None) -> list[str] | None:
    python = project_mod.venv_python(project)
    if python is not None:
        return [str(python), "-m", "karni.agent"]
    service = os.environ.get("KARNI_COMPOSE_SERVICE", "django")
    if project_mod.compose_service_running(project, service):
        flags = [flag for key, value in (env or {}).items() for flag in ("-e", f"{key}={value}")]
        return ["docker", "compose", "exec", "-T", *flags, service, "python", "-m", "karni.agent"]
    return None


def _run_project(project: Path, args: list[str], env: dict[str, str] | None = None) -> Any | None:
    command = _project_command(project, env)
    if command is None:
        return None
    proc = subprocess.run(
        [*command, *args],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, **env} if env else None,
    )
    if proc.returncode == 2:
        raise CliError(proc.stderr.strip(), code="C009")
    if proc.returncode != 0:
        return None  # e.g. an older karni without karni.agent: try the next source
    return json.loads(proc.stdout)


def _order() -> tuple[str, ...]:
    forced = os.environ.get("KARNI_AGENT_SOURCE", "").strip()
    if not forced:
        return SOURCES
    if forced not in SOURCES:
        raise CliError(
            f"KARNI_AGENT_SOURCE must be one of {', '.join(SOURCES)}, got {forced!r}.", code="C007"
        )
    return (forced,)


def _module_for(source: str) -> ModuleType | None:
    return _local() if source == "local" else _bundled()


def _call(module: ModuleType, name: str, *args: Any) -> Any:
    try:
        return getattr(module, name)(*args)
    except module.OverrideError as exc:
        raise CliError(_bare(exc), code=getattr(exc, "code", "E701")) from None


def load(project: Path | None) -> AgentData:
    """Rules + procedures with ``<project>/karni.rules.py`` applied."""
    for source in _order():
        if source == "project":
            if project is None:
                continue
            raw = _run_project(project, ["dump", "--root", "."], _conditions_env(project))
            if raw is not None:
                return AgentData(raw, source)
            continue
        module = _module_for(source)
        if module is not None:
            return AgentData(_call(module, "dump", project), source)
    raise CliError(
        "Karni's agent rules are unavailable: karni is not importable here, the project "
        "interpreter is unreachable, and no bundled copy ships with this karni-cli.\n"
        "Install karni next to karni-cli, or run inside a project with a .venv.",
        code="C005",
    )


def check(paths: list[Path], project: Path | None) -> list[dict[str, Any]]:
    """Static findings for ``paths`` (each a dict with path/code/rule_id/line/message/fix)."""
    for source in _order():
        if source == "project":
            if project is None:
                continue
            rel = [_relative(p, project) for p in paths]
            found = _run_project(project, ["check", "--root", ".", *rel])
            if found is not None:
                return [{**f, "path": str(p)} for f, p in _rejoin(found, rel, paths)]
            continue
        module = _module_for(source)
        if module is not None:
            try:
                return list(_call(module, "check_paths", paths, project))
            except (OSError, ValueError) as exc:
                raise CliError(_bare(exc), code=getattr(exc, "code", "C010")) from None
    raise CliError("Karni's agent checks are unavailable (see `karni rules`).", code="C005")


def _bare(exc: BaseException) -> str:
    """The message without the code prefix the bundled exception adds to ``str()``."""
    return str(exc.args[0]) if exc.args else str(exc)


def _relative(path: Path, project: Path) -> str:
    try:
        return str(path.resolve().relative_to(project.resolve()))
    except ValueError:
        raise CliError(
            f"{path} is outside the project; the project interpreter can only check "
            "files inside it.",
            code="C010",
        ) from None


def _rejoin(
    found: list[dict[str, Any]], rel: list[str], paths: list[Path]
) -> list[tuple[dict[str, Any], Path]]:
    by_rel = dict(zip(rel, paths, strict=True))
    return [(f, by_rel.get(f["path"], Path(f["path"]))) for f in found]
