"""``karni context`` — the token-efficiency mechanism.

Backend inventory comes from ``manage.py karni_context``; COMPONENTS/HOOKS
come from @karni/ui's build-generated dist/manifest.json. Absent manifest →
those lines are omitted entirely (never stale, never guessed). Two lines are
read statically from the project tree (no Django): APPS — the local apps in
the ``# karni:apps`` block that live in this project — and PAGES — the files
under ``frontend/src/pages/``. Together with ``karni rules`` this is enough
for an agent to start work without reading files.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project
from karni_cli.settings_edit import MARKER

_PAGE_SUFFIXES = (".tsx", ".ts", ".jsx", ".js")
_QUOTED = re.compile(r"""["']([^"']+)["']""")


def find_manifest(project: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None
    for base in (project / "frontend", project):
        candidate = base / "node_modules" / "@karni" / "ui" / "dist" / "manifest.json"
        if candidate.is_file():
            return candidate
    return None


def manifest_lines(manifest_path: Path) -> list[str]:
    try:
        data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    lines: list[str] = []
    if data.get("components"):
        lines.append("COMPONENTS: " + " ".join(sorted(data["components"])))
    if data.get("hooks"):
        lines.append("HOOKS: " + " ".join(sorted(data["hooks"])))
    return lines


def apps_line(project: Path) -> str | None:
    """Local apps wired in the ``# karni:apps`` block, as ``label(path/)``."""
    settings = project / "config" / "settings.py"
    if not settings.is_file():
        return None
    lines = settings.read_text().splitlines()
    end = next((i for i, line in enumerate(lines) if MARKER in line), None)
    if end is None:
        return None
    start = next(
        (i for i in range(end, -1, -1) if "INSTALLED_APPS" in lines[i] and "[" in lines[i]), end
    )
    names: list[str] = []
    for line in lines[start : end + 1]:
        code = line.split("#", 1)[0]
        names += _QUOTED.findall(code)
    found = []
    for name in names:
        module = name.split(".apps.", 1)[0]
        path = Path(*module.split("."))
        if (project / path).is_dir():
            found.append(f"{module.rsplit('.', 1)[-1]}({path.as_posix()}/)")
    return "APPS: " + " ".join(found) if found else None


def pages_line(project: Path) -> str | None:
    pages = project / "frontend" / "src" / "pages"
    if not pages.is_dir():
        return None
    found = sorted(
        path.relative_to(pages).with_suffix("").as_posix()
        for path in pages.rglob("*")
        if path.suffix in _PAGE_SUFFIXES and not path.name.endswith((".test.tsx", ".test.ts"))
    )
    return "PAGES: " + " ".join(found) if found else None


def assemble(backend_output: str, ui_lines: list[str]) -> str:
    """Merge UI lines into the backend sections, keeping the documented order
    (MODELS, VIEWSETS, COMPONENTS, HOOKS, MODULES, BASES)."""
    sections = [line for line in backend_output.split("\n") if line.strip()]
    insert_at = next(
        (i for i, line in enumerate(sections) if line.startswith(("MODULES:", "BASES:"))),
        len(sections),
    )
    sections[insert_at:insert_at] = ui_lines
    return "\n".join(sections)


def build_context_text(
    project: Path,
    *,
    docker: bool | None = None,
    service: str = "django",
    manifest: Path | None = None,
) -> str:
    """The full inventory: APPS, MODELS, VIEWSETS, COMPONENTS, HOOKS, PAGES, MODULES, BASES.

    Raises :class:`CliError` when the backend inventory command fails.
    """
    proc = project_mod.run_manage(project, ["karni_context"], docker=docker, service=service)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise CliError(f"manage.py karni_context failed (exit {proc.returncode}).")
    found = find_manifest(project, manifest)
    ui_lines = manifest_lines(found) if found else []
    pages = pages_line(project)
    if pages:
        ui_lines.append(pages)
    text = assemble(proc.stdout, ui_lines)
    apps = apps_line(project)
    return f"{apps}\n{text}" if apps else text


def context(
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
    manifest: Path | None = typer.Option(None, "--manifest", help="Explicit manifest.json path"),
) -> None:
    project = require_project()
    try:
        text = build_context_text(project, docker=docker, service=service, manifest=manifest)
    except CliError as exc:
        sys.stderr.write(f"{exc}\n")
        raise typer.Exit(1) from None
    typer.echo(text)
