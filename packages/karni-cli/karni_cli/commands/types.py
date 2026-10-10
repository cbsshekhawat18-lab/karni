"""``karni types`` — OpenAPI schema → TS types + typed hooks."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project
from karni_cli.typegen import write_hooks

_FORMATS = {".yml": "openapi", ".yaml": "openapi", ".json": "openapi-json"}


def _openapi_typescript_cmd(project: Path, schema: Path, out: Path) -> list[str]:
    """Project-pinned binary first; pinned-major npx fallback (E2)."""
    local = project / "frontend" / "node_modules" / ".bin" / "openapi-typescript"
    if local.exists():
        return [str(local), str(schema), "-o", str(out)]
    return ["npx", "--yes", "openapi-typescript@^7", str(schema), "-o", str(out)]


def types(
    schema_out: Path = typer.Option(Path("frontend/src/api/schema.yml"), "--schema-out"),
    out: Path = typer.Option(Path("frontend/src/api"), "--out"),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    project = require_project()
    fmt = _FORMATS.get(schema_out.suffix)
    if fmt is None:
        raise CliError(
            f"--schema-out must end in .yml/.yaml/.json, got {schema_out.suffix}", code="C106"
        )

    (project / schema_out).parent.mkdir(parents=True, exist_ok=True)
    proc = project_mod.run_manage(
        project,
        ["spectacular", "--format", fmt, "--file", str(schema_out)],
        docker=docker,
        service=service,
    )
    if proc.returncode != 0:
        typer.echo(proc.stderr or proc.stdout, err=True)
        raise typer.Exit(proc.returncode)

    types_file = project / out / "types.ts"
    ts = subprocess.run(
        _openapi_typescript_cmd(project, project / schema_out, types_file),
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
    )
    if ts.returncode != 0:
        typer.echo(ts.stderr, err=True)
        raise CliError(
            "openapi-typescript failed — is Node available? "
            "Add openapi-typescript to frontend devDependencies to pin it.",
            code="C006",
        )

    hooks = write_hooks(project / schema_out, project / out)
    typer.echo(f"Wrote {types_file} and {hooks}")

    pkg = project / "frontend" / "package.json"
    if pkg.is_file() and '"@karni/ui"' not in pkg.read_text():
        typer.echo(
            "Hint: frontend/package.json lacks @karni/ui — `npm i @karni/ui` to use hooks.ts"
        )
