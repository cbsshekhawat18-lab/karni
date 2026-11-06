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

import difflib
import json
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomlkit
import typer
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from karni_cli import agent_data, scaffold
from karni_cli.adapters import MODULES_DIR, sync
from karni_cli.project import (
    CliError,
    compose_service_running,
    require_project,
    venv_python,
)
from karni_cli.settings_edit import MARKER, add_entry, wire_entries

if TYPE_CHECKING:  # karni_cli.generators imports this module: a runtime import would loop
    from karni.catalog import Manifest

    from karni_cli.catalog import Catalog
    from karni_cli.generators.core import Workspace

SETTINGS = "config/settings.py"


def add_dependency_text(text: str, distribution: str) -> str | None:
    """``pyproject.toml`` text with ``distribution`` in [project].dependencies, ``None`` if there.

    ``distribution`` may name extras (``karni-site[images]``). A requirement
    for the same distribution already listed, with or without them, is left
    as it is.

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
    target = canonicalize_name(Requirement(distribution).name)
    for dep in deps:
        try:
            if canonicalize_name(Requirement(str(dep)).name) == target:
                return None
        except InvalidRequirement:
            continue
    deps.append(distribution)
    return tomlkit.dumps(doc)


FRONTEND_PACKAGE = "frontend/package.json"


def _json_indent(text: str) -> str:
    match = re.search(r"^([ \t]+)\S", text, re.MULTILINE)
    return match.group(1) if match else "  "


def _dump_package(data: dict[str, Any], original: str) -> str:
    out = json.dumps(data, indent=_json_indent(original), ensure_ascii=False)
    return out + ("\n" if original.endswith("\n") else "")


def ui_dependency_text(text: str, package: str, spec: str) -> str | None:
    """``frontend/package.json`` text with ``package`` in dependencies, ``None`` if there.

    The module's UI package (``@karni/charts-ui``) at ``spec``. The entry goes
    in sorted place when the table is sorted, else last, and the file keeps
    its indent, so ``karni remove`` gives the original bytes back.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    deps = data.get("dependencies")
    if deps is None:
        deps = {}
    if not isinstance(deps, dict) or package in deps:
        return None
    was_sorted = list(deps) == sorted(deps)
    deps[package] = spec
    data["dependencies"] = dict(sorted(deps.items())) if was_sorted else deps
    return _dump_package(data, text)


def _ui_package(ws: Workspace, manifest: Manifest) -> list[str]:
    """Add the module's UI package to frontend/package.json, when the project has a frontend."""
    package = manifest.provides.ui
    text = ws.read(FRONTEND_PACKAGE)
    if not package or text is None:
        return []
    updated = ui_dependency_text(text, package, scaffold.UI_REGISTRY_SPEC)
    if updated is None:
        return [f"{package}: already in {FRONTEND_PACKAGE}"]
    ws.write(FRONTEND_PACKAGE, updated)
    return [
        f"{package}: added to {FRONTEND_PACKAGE} ({scaffold.UI_REGISTRY_SPEC}), "
        "run npm install in frontend/ (or rebuild the frontend image)"
    ]


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


def _unknown_module_message(module: str, loaded: Catalog) -> str:
    names = sorted(m.name for m in loaded.modules)
    close = difflib.get_close_matches(module, names, n=3, cutoff=0.5)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    return (
        f"{module} is not a module Karni knows: it is not in the catalog and no installed "
        f"distribution ships a module manifest for it.{hint} `karni modules list` shows the "
        "names. A third-party module is installed first (pip install <distribution>), then "
        "added. Nothing was changed."
    )


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


def _wire(text: str, manifest: Manifest) -> tuple[str, list[str]]:
    """Settings ``text`` with the middleware and context processors the manifest asks for.

    Entries marked ``manual`` are only named, for the user to add by hand.
    """
    wiring = manifest.wiring
    middleware = [(entry.path, entry.why) for entry in wiring.middleware if not entry.manual]
    processors = [
        (entry.path, entry.why) for entry in wiring.context_processors if not entry.manual
    ]
    lines: list[str] = []
    if middleware or processors:
        text, lines = wire_entries(
            text,
            SETTINGS,
            middleware=middleware,
            processors=processors,
            heading=f"# --- {manifest.title} ({manifest.distribution})",
        )
    for entry in (*wiring.middleware, *wiring.context_processors):
        if entry.manual and entry.path not in text:
            setting = "MIDDLEWARE" if entry in wiring.middleware else "the context processors"
            lines.append(f"Add {entry.path!r} to {setting} in {SETTINGS}: {entry.why}.")
    return text, lines


def plan_module(
    ws: Workspace,
    module: str,
    *,
    found: tuple[Manifest | None, Catalog] | None = None,
) -> list[str]:
    """Plan ``karni add <module>``'s file edits into ``ws``; returns the lines it reports.

    What to wire comes from the module's manifest (:func:`find_manifest`):
    the dependency in ``pyproject.toml``, its apps in the ``# karni:apps``
    block, its middleware and context processors, and for a site module the
    kind (an app becomes a site+app). A module without a manifest is wired by
    convention. ``karni build`` plans its modules the same way, so
    ``--dry-run`` shows them. Recording the module's agent guidance needs it
    installed, so :func:`record_guidance` runs after the write.
    """
    manifest, loaded = found if found is not None else find_manifest(ws.root, module)
    if manifest is None:
        raise CliError(_unknown_module_message(module, loaded), code="C840")
    _refuse_conflicts(loaded, manifest)
    app_name = manifest.app
    distribution = manifest.distribution
    pyproject = ws.read("pyproject.toml")
    if pyproject is None:
        raise CliError("No pyproject.toml in the project root.", code="C207")
    # karni-site's images extra (Pillow) makes the smaller copies of uploaded images.
    requirement = f"{distribution}[images]" if module == "site" else distribution
    with_dependency = add_dependency_text(pyproject, requirement)
    if with_dependency is not None:
        ws.write("pyproject.toml", with_dependency)
    settings = ws.read(SETTINGS)
    if settings is None:
        raise CliError(f"{ws.path(SETTINGS)} not found.", code="C001")
    apps = list(manifest.wiring.apps) if manifest else [app_name]
    if app_name not in apps:
        apps.insert(0, app_name)
    app_added = False
    for index, app in enumerate(apps):
        with_app = add_entry(
            settings, app, setting="INSTALLED_APPS", marker=MARKER, filename="settings.py"
        )
        if with_app is not None:
            settings = with_app
            app_added = app_added or index == 0
    lines = [
        f"{distribution}: {'added to' if with_dependency else 'already in'} pyproject.toml",
        f"{app_name}: {'wired into' if app_added else 'already in'} INSTALLED_APPS",
    ]
    settings, notes = _wire(settings, manifest)
    lines += notes
    if settings != ws.read(SETTINGS):
        ws.write(SETTINGS, settings)
    lines += _ui_package(ws, manifest)
    if manifest is not None and manifest.wiring.kind == "site":
        from karni_cli import kinds

        adopted = kinds.adopt_site_text(ws.read("pyproject.toml") or "", ws.root)
        if adopted is not None:
            ws.write("pyproject.toml", adopted[0])
            lines.append(kinds.adoption_note(adopted[1], adopted[2]))
        lines += _site_urls(ws)
    return lines


def _site_urls(ws: Workspace) -> list[str]:
    """karni_site's own URLs (robots.txt, sitemap.xml, the form view) in config/urls.py."""
    from karni_cli.generators.site import SITE_URLS, with_site_urls

    text = ws.read("config/urls.py")
    if text is None:
        return []
    try:
        wired = with_site_urls(text, "config/urls.py")
    except CliError as exc:
        return [f"robots.txt and sitemap.xml: {exc.message}"]
    if wired is None:
        return []
    ws.write("config/urls.py", wired)
    return [f"{SITE_URLS}: included in config/urls.py (robots.txt, sitemap.xml, the form view)"]


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


def _site_next(project: Path) -> None:
    """After karni add site: the site app is the next step, unless the project has one."""
    from karni_cli.commands.context import site_line

    if site_line(project) is None:
        typer.echo(
            "Next, the site app: karni make site website, or for a designer's pages the "
            "site-from-design procedure (karni rules --procedure site-from-design)."
        )


def add(module: str = typer.Argument(..., help='Module short name, e.g. "payments"')) -> None:
    from karni_cli.generators.core import Workspace

    project = require_project()
    manifest, loaded = find_manifest(project, module)
    if manifest is not None:
        module = manifest.name
    app_name = manifest.app if manifest else f"karni_{module.replace('-', '_')}"
    ws = Workspace(project)
    lines = plan_module(ws, module, found=(manifest, loaded))
    for path, _before, after in ws.changes():
        path.write_text(after, encoding="utf-8")
    for line in lines:
        typer.echo(line)
    if manifest is not None and manifest.wiring.kind == "site":
        _site_next(project)

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
