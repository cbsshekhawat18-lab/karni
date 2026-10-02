"""``karni add <module>`` — wire an optional Karni module into the project.

Wiring: dependency in ``pyproject.toml`` + app in the ``# karni:apps``
marker block + the module's ``AGENTS.fragment.md`` merged into the
project's ``AGENTS.md`` (idempotent marker replace). The fragment is read
**through the project's interpreter** — the CLI never imports project code
itself — so it only merges once the module is actually installed; until
then the command says to run again after installing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import tomlkit
import typer
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from karni_cli.project import (
    CliError,
    compose_service_running,
    require_project,
    venv_python,
)
from karni_cli.settings_edit import add_app


def _add_dependency(project_root: str, distribution: str) -> bool:
    """Add the distribution to [project].dependencies. Returns False when present."""
    pyproject = Path(project_root) / "pyproject.toml"
    if not pyproject.is_file():
        raise CliError("No pyproject.toml in the project root.")
    doc = tomlkit.parse(pyproject.read_text())
    try:
        deps = doc["project"]["dependencies"]
    except (KeyError, TypeError):
        raise CliError(
            "pyproject.toml has no [project].dependencies table — "
            "karni add only manages that table; add the dependency manually."
        ) from None
    target = canonicalize_name(distribution)
    for dep in deps:
        try:
            if canonicalize_name(Requirement(str(dep)).name) == target:
                return False
        except InvalidRequirement:
            continue
    deps.append(distribution)
    pyproject.write_text(tomlkit.dumps(doc))
    return True


def _read_agents_fragment(project: Path, app_name: str) -> str | None:
    """Read the installed module's ``AGENTS.fragment.md`` via the project interpreter.

    Resolution mirrors the CLI's execution order: the project ``.venv``
    first, then a running compose ``django`` service. Returns ``None`` when
    no interpreter is reachable or the subprocess fails (module not
    installed yet, no fragment shipped) — the caller falls back to the
    "run again after installing" message.
    """
    code = (
        "import importlib.resources as resources; "
        f"print(resources.files({app_name!r}).joinpath('AGENTS.fragment.md')"
        ".read_text(encoding='utf-8'), end='')"
    )
    python = venv_python(project)
    if python is not None:
        command = [str(python), "-c", code]
    elif compose_service_running(project, "django"):
        command = ["docker", "compose", "exec", "-T", "django", "python", "-c", code]
    else:
        return None
    try:
        proc = subprocess.run(command, cwd=project, text=True, capture_output=True, check=False)
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout


def merge_agents_fragment(agents_md: Path, module: str, fragment: str) -> None:
    """Splice ``fragment`` into AGENTS.md between the module's markers.

    Idempotent: an existing ``<!-- karni:module:<name> -->`` block is
    replaced in place; otherwise the block is appended. A missing AGENTS.md
    is created (escape hatch: projects that dropped the file can delete the
    merged one again — karni add only ever touches the marked block).
    """
    start = f"<!-- karni:module:{module} -->"
    end = f"<!-- /karni:module:{module} -->"
    block = f"{start}\n{fragment.strip()}\n{end}\n"
    existing = agents_md.read_text() if agents_md.is_file() else ""
    if start in existing and end in existing:
        head, _, rest = existing.partition(start)
        _, _, tail = rest.partition(end)
        tail = tail.lstrip("\n")
        updated = head + block + ("\n" + tail if tail else "")
    elif existing:
        base = existing if existing.endswith("\n") else existing + "\n"
        updated = base + "\n" + block
    else:
        updated = block
    if updated != existing:
        agents_md.write_text(updated)


def add(module: str = typer.Argument(..., help='Module short name, e.g. "payments"')) -> None:
    project = require_project()
    app_name = f"karni_{module.replace('-', '_')}"
    distribution = f"karni-{module.replace('_', '-')}"

    dep_added = _add_dependency(str(project), distribution)
    app_added = add_app(project / "config" / "settings.py", app_name)

    typer.echo(f"{distribution}: {'added to' if dep_added else 'already in'} pyproject.toml")
    typer.echo(f"{app_name}: {'wired into' if app_added else 'already in'} INSTALLED_APPS")

    fragment = _read_agents_fragment(project, app_name)
    if fragment is None:
        typer.echo(
            f"{app_name} is not importable yet — run `karni add {module}` again "
            "after installing to merge agent guidance into AGENTS.md."
        )
    else:
        merge_agents_fragment(project / "AGENTS.md", module, fragment)
        typer.echo(f"AGENTS.md: merged {app_name} agent guidance")

    typer.echo("If the module ships URLs, add the include to config/urls.py:")
    typer.echo(f'  path("{module}/", include("{app_name}.urls"))')
    typer.echo("Install it, then migrate:")
    typer.echo("  docker compose build        # container workflow")
    typer.echo("  uv pip install -r pyproject.toml   # host venv workflow")
    typer.echo("  make migrate")
