"""``karni types`` — OpenAPI schema → TS types + typed hooks."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project
from karni_cli.typegen import load_schema, write_hooks

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


def _run_openapi_typescript(project: Path, schema: Path, types_file: Path) -> None:
    try:
        ts = subprocess.run(
            _openapi_typescript_cmd(project, schema, types_file),
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


def _write_schema(
    project: Path,
    schema_out: Path,
    fmt: str,
    *,
    docker: bool | None,
    service: str,
    api_version: str | None = None,
) -> None:
    (project / schema_out).parent.mkdir(parents=True, exist_ok=True)
    args = ["spectacular", "--format", fmt, "--file", str(schema_out)]
    if api_version:
        args += ["--api-version", api_version]
    proc = project_mod.run_manage(project, args, docker=docker, service=service)
    if proc.returncode != 0:
        raise SchemaFailed(proc.returncode, proc.stderr or proc.stdout or "")


def api_versions(schema: Path) -> list[str]:
    """Experimental. The API versions a schema file lists (``x-karni-api-versions``), in order.

    Empty for an unversioned API. The current version's document is the project's
    ``schema`` file, and each version, the current one included, has its own.
    """
    entries = load_schema(schema).get("x-karni-api-versions") or []
    return [str(entry["name"]) for entry in entries if isinstance(entry, dict) and "name" in entry]


def write_types(
    project: Path,
    schema_out: Path = Path("frontend/src/api/schema.yml"),
    out: Path = Path("frontend/src/api"),
    *,
    docker: bool | None = None,
    service: str = "django",
) -> str:
    """Write the schema, ``types.ts`` and ``hooks.ts``; returns what was written.

    With API versions mounted (``KARNI_API_VERSION``), it also writes the same three files for
    each version, in ``<out>/<version>/`` (experimental). ``karni build`` calls it for its
    types step. Raises :class:`CliError` (``C006`` when openapi-typescript fails, ``C106`` for a
    bad suffix), or :class:`SchemaFailed` when the backend cannot print its schema.
    """
    fmt = _FORMATS.get(schema_out.suffix)
    if fmt is None:
        raise CliError(
            f"--schema-out must end in .yml/.yaml/.json, got {schema_out.suffix}", code="C106"
        )

    _write_schema(project, schema_out, fmt, docker=docker, service=service)
    types_file = project / out / "types.ts"
    _run_openapi_typescript(project, project / schema_out, types_file)
    hooks = write_hooks(project / schema_out, project / out)
    written = f"Wrote {types_file} and {hooks}"

    for name in api_versions(project / schema_out):
        version_schema = out / name / schema_out.name
        _write_schema(
            project, version_schema, fmt, docker=docker, service=service, api_version=name
        )
        version_types = project / out / name / "types.ts"
        _run_openapi_typescript(project, project / version_schema, version_types)
        try:
            version_hooks = write_hooks(project / version_schema, project / out / name)
        except CliError:  # a version that serves no Karni resource has types only
            written += f"\nWrote {version_types} ({name})"
        else:
            written += f"\nWrote {version_types} and {version_hooks} ({name})"
    return written


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
