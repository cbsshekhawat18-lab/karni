"""``karni add <module>`` — wire an optional Karni module into the project.

What to wire comes from the module's manifest in the catalog
(``karni.module.toml``, :mod:`karni_cli.catalog`): its distribution, its
apps, the middleware and context processors it needs, whether the project's
kind gains a site, and the URL include, extras and services it prints. A
module without a manifest is wired by convention (``karni_<module>``,
``karni-<module>``). ``karni remove`` reverses it.

Wiring: dependency in ``pyproject.toml`` + app in the ``# karni:apps``
marker block + the module's ``AGENTS.fragment.md`` recorded as
``.karni/modules/<module>.md`` (project-owned, committed), from which
``karni rules`` and the generated adapters (``karni rules sync``: AGENTS.md
between ``<!-- karni:module:<module> -->`` markers) take the module's
guidance. The fragment is read **through the project's interpreter** — the
CLI never imports project code itself — so it is only recorded once the
module is actually installed; until then the command says to run again
after installing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit
import typer
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from karni_cli import agent_data
from karni_cli.adapters import MODULES_DIR, sync
from karni_cli.project import (
    CliError,
    compose_service_running,
    require_project,
    venv_python,
)
from karni_cli.settings_edit import add_app, wire_entries

if TYPE_CHECKING:
    from karni.catalog import Manifest

    from karni_cli.catalog import Catalog


def add_dependency_text(text: str, distribution: str) -> str | None:
    """``pyproject.toml`` text with ``distribution`` in [project].dependencies, ``None`` if there.

    Parsed with tomlkit, never string-matched. ``karni make site`` uses it
    through the generators' workspace, ``karni add`` on the file.
    """
    doc = tomlkit.parse(text)
    try:
        deps = doc["project"]["dependencies"]
    except (KeyError, TypeError):
        raise CliError(
            "pyproject.toml has no [project].dependencies table. "
            "karni add only manages that table, so add the dependency manually.",
            code="C207",
        ) from None
    target = canonicalize_name(distribution)
    for dep in deps:
        try:
            if canonicalize_name(Requirement(str(dep)).name) == target:
                return None
        except InvalidRequirement:
            continue
    deps.append(distribution)
    return tomlkit.dumps(doc)


def _add_dependency(project_root: str, distribution: str) -> bool:
    """Add the distribution to [project].dependencies. Returns False when present."""
    pyproject = Path(project_root) / "pyproject.toml"
    if not pyproject.is_file():
        raise CliError("No pyproject.toml in the project root.", code="C207")
    updated = add_dependency_text(pyproject.read_text(), distribution)
    if updated is None:
        return False
    pyproject.write_text(updated)
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


def record_module_fragment(project: Path, module: str, fragment: str) -> bool:
    """Store the module's guidance under ``.karni/modules/``. Returns True when changed."""
    target = project / MODULES_DIR / f"{module}.md"
    content = fragment.strip() + "\n"
    if target.is_file() and target.read_text(encoding="utf-8") == content:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return True


def _refresh_adapters(project: Path) -> None:
    try:
        result = sync(project, agent_data.load(project))
    except CliError as exc:
        typer.echo(f"Agent adapters not refreshed ({exc}). Run `karni rules sync`.")
        return
    for rel in result.written:
        typer.echo(f"{rel}: refreshed")
    for rel in result.blocked:
        typer.echo(
            f"{rel}: not generated by karni, left untouched. Run `karni upgrade` or "
            "`karni rules sync --force`."
        )


def record_guidance(project: Path, module: str, app: str | None = None) -> bool:
    """Record the installed module's agent guidance and refresh the adapters.

    Returns ``False``, after saying to run ``karni add <module>`` again, when
    the module is not importable through the project interpreter yet.
    ``karni make site`` calls this for karni-site after wiring it.
    """
    app_name = app or f"karni_{module.replace('-', '_')}"
    fragment = _read_agents_fragment(project, app_name)
    if fragment is None:
        typer.echo(
            f"{app_name} is not importable yet. Run `karni add {module}` again "
            "after installing to record its agent guidance."
        )
        _refresh_adapters(project)  # the rest of what they say may have changed (the kind)
        return False
    if record_module_fragment(project, module, fragment):
        typer.echo(f"{(MODULES_DIR / f'{module}.md').as_posix()}: recorded agent guidance")
    _refresh_adapters(project)
    return True


def find_manifest(project: Path, module: str) -> tuple[Manifest | None, Catalog]:
    """The module's manifest (``None``: not in the catalog) and the catalog it came from.

    The bundled catalog first, then the modules installed in the project's
    interpreter. A built-in feature is refused (``C318``).
    """
    from karni_cli import catalog

    loaded = catalog.load(project, ask_project=False)
    if loaded.get(module) is None:
        loaded = catalog.load(project)
    found = loaded.get(module)
    if found is not None and found.kind != "module":
        raise CliError(
            f"{found.name} is a built-in feature, not a module: its setting {found.switch} "
            "turns it on and off (or its key under features: in karni.yaml).",
            code="C318",
        )
    return found, loaded


def _refuse_conflicts(loaded: Catalog, manifest: Manifest) -> None:
    clash = sorted(
        name
        for name in loaded.added
        if name != manifest.name
        and (
            name in manifest.conflicts
            or manifest.name in (getattr(loaded.get(name), "conflicts", ()) or ())
        )
    )
    if clash:
        raise CliError(
            f"{manifest.name} cannot be added next to {', '.join(clash)} (the manifests say they "
            f"conflict). Remove {clash[0]} first: karni remove {clash[0]}.",
            code="C315",
        )


def _wire(settings_path: Path, manifest: Manifest) -> None:
    """The middleware and context processors the manifest asks for (karni-site's)."""
    wiring = manifest.wiring
    middleware = [(entry.path, entry.why) for entry in wiring.middleware if not entry.manual]
    processors = [
        (entry.path, entry.why) for entry in wiring.context_processors if not entry.manual
    ]
    if middleware or processors:
        text = settings_path.read_text()
        updated, notes = wire_entries(
            text,
            "config/settings.py",
            middleware=middleware,
            processors=processors,
            heading=f"# --- {manifest.title} ({manifest.distribution})",
        )
        if updated != text:
            settings_path.write_text(updated)
        for note in notes:
            typer.echo(note)
    for entry in (*wiring.middleware, *wiring.context_processors):
        if entry.manual and entry.path not in settings_path.read_text():
            setting = "MIDDLEWARE" if entry in wiring.middleware else "the context processors"
            typer.echo(f"Add {entry.path!r} to {setting} in config/settings.py: {entry.why}.")


def _next_steps(loaded: Catalog, manifest: Manifest) -> None:
    """What the manifest says comes next: the URL include, extras, services, requirements."""
    wiring = manifest.wiring
    if wiring.urls:
        typer.echo("Add its URLs to config/urls.py:")
        typer.echo(f"  {wiring.urls}")
    if wiring.extras:
        extras = ", ".join(f"{name} ({why})" for name, why in wiring.extras.items())
        typer.echo(f"Extras, e.g. {manifest.distribution}[{next(iter(wiring.extras))}]: {extras}")
    for service in manifest.services:
        typer.echo(f"It needs {service}.")
    for other in manifest.requires:
        if other not in loaded.added:
            typer.echo(f"It requires {other}: karni modules show {other}.")
    if manifest.asks:
        typer.echo(f"Its options and questions: karni modules show {manifest.name}")


def _adopt_site(project: Path) -> None:
    """The project's kind gets its site: an app becomes a site+app (and says how to go back)."""
    from karni_cli import kinds

    pyproject = project / "pyproject.toml"
    adopted = kinds.adopt_site_text(pyproject.read_text(encoding="utf-8"), project)
    if adopted is not None:
        pyproject.write_text(adopted[0], encoding="utf-8")
        typer.echo(kinds.adoption_note(adopted[1], adopted[2]))
    from karni_cli.commands.context import site_line

    if site_line(project) is None:
        typer.echo(
            "Next, the site app: karni make site website, or for a designer's pages the "
            "site-from-design procedure (karni rules --procedure site-from-design)."
        )


def add(module: str = typer.Argument(..., help='Module short name, e.g. "payments"')) -> None:
    project = require_project()
    manifest, loaded = find_manifest(project, module)
    if manifest is not None:
        _refuse_conflicts(loaded, manifest)
        module = manifest.name
    app_name = manifest.app if manifest else f"karni_{module.replace('-', '_')}"
    distribution = manifest.distribution if manifest else f"karni-{module.replace('_', '-')}"
    settings_path = project / "config" / "settings.py"

    dep_added = _add_dependency(str(project), distribution)
    app_added = add_app(settings_path, app_name)
    for extra_app in manifest.wiring.apps[1:] if manifest else ():
        add_app(settings_path, extra_app)

    typer.echo(f"{distribution}: {'added to' if dep_added else 'already in'} pyproject.toml")
    typer.echo(f"{app_name}: {'wired into' if app_added else 'already in'} INSTALLED_APPS")
    if manifest is not None:
        _wire(settings_path, manifest)
        if manifest.wiring.kind == "site":
            _adopt_site(project)

    record_guidance(project, module, app_name)

    if manifest is not None:
        _next_steps(loaded, manifest)
    else:
        typer.echo("If the module ships URLs, add the include to config/urls.py:")
        typer.echo(f'  path("{module}/", include("{app_name}.urls"))')
    typer.echo("Install it, then migrate:")
    typer.echo("  docker compose build        # container workflow")
    typer.echo("  uv pip install -r pyproject.toml   # host venv workflow")
    typer.echo("  make migrate")
