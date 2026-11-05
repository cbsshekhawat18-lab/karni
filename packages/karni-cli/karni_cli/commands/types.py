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


class SchemaFailed(Exception):
    """``manage.py spectacular`` failed: its exit status and output."""

    def __init__(self, returncode: int, output: str) -> None:
        super().__init__(output)
        self.returncode = returncode
        self.output = output


def write_types(
    project: Path,
    schema_out: Path = Path("frontend/src/api/schema.yml"),
    out: Path = Path("frontend/src/api"),
    *,
    docker: bool | None = None,
    service: str = "django",
) -> str:
    """Write the schema, ``types.ts`` and ``hooks.ts``; returns what was written.

    ``karni build`` calls it for its types step. Raises :class:`CliError`
    (``C006`` when openapi-typescript fails, ``C106`` for a bad suffix), or
    :class:`SchemaFailed` when the backend cannot print its schema.
    """
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
        raise SchemaFailed(proc.returncode, proc.stderr or proc.stdout or "")

    types_file = project / out / "types.ts"
    try:
        ts = subprocess.run(
            _openapi_typescript_cmd(project, project / schema_out, types_file),
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:  # no npx: Node is not installed
        ts = subprocess.CompletedProcess([], 127, "", "npx not found")
    if ts.returncode != 0:
        raise CliError(
            "openapi-typescript failed. Check that Node is available, and add "
            "openapi-typescript to frontend devDependencies to pin it.",
            code="C006",
        )

    hooks = write_hooks(project / schema_out, project / out)
    return f"Wrote {types_file} and {hooks}"


def types(
    schema_out: Path = typer.Option(Path("frontend/src/api/schema.yml"), "--schema-out"),
    out: Path = typer.Option(Path("frontend/src/api"), "--out"),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    project = require_project()
    try:
        written = write_types(project, schema_out, out, docker=docker, service=service)
    except SchemaFailed as exc:
        typer.echo(exc.output, err=True)
        raise typer.Exit(exc.returncode) from None
    typer.echo(written)

    pkg = project / "frontend" / "package.json"
    if pkg.is_file() and '"@karni/ui"' not in pkg.read_text():
        typer.echo(
            "Hint: frontend/package.json lacks @karni/ui. Run `npm i @karni/ui` to use hooks.ts"
        )
