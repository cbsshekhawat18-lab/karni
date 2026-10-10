"""``karni new <name>`` — scaffold a project from templates/project.

The template carries no agent guidance files: they are generated afterwards
by the same code as ``karni rules sync`` (AGENTS.md, CLAUDE.md, Cursor,
Windsurf, Copilot, Cline, Aider, Junie adapters + slash commands).

@karni/ui is resolved like the template: ``KARNI_UI_SRC`` > the monorepo
checkout's ``packages/karni-ui`` > the npm release. A local source becomes
``"@karni/ui": "file:<abs path>"`` in frontend/package.json (installed as a
packed copy via the scaffold's ``.npmrc``), and its ``dist/`` is built here
when missing — package.json ``exports`` point into dist/.
"""

from __future__ import annotations

from pathlib import Path

import typer

from karni_cli import agent_data, scaffold
from karni_cli.adapters import sync
from karni_cli.scaffold import resolve_template, validate_name


def write_agent_adapters(project: Path) -> int:
    """Generate the agent adapter files into a freshly rendered project."""
    result = sync(project, agent_data.load(project))
    return len(result.written)


def prepare_ui_source(source: Path) -> None:
    """Make sure a local @karni/ui has the dist/ a ``file:`` install ships."""
    rebuild = f"(cd {source} && npm install && npm run build)"
    if not scaffold.ui_dist_missing(source):
        if scaffold.ui_dist_stale(source):
            typer.echo(
                f"warning: {source}/dist is older than its sources — rebuild it with "
                f"{rebuild} before `npm install` in frontend/.",
                err=True,
            )
        return
    typer.echo(f"Building @karni/ui in {source} (dist/ is missing; file: installs ship dist/)...")
    failure = scaffold.build_ui_dist(source)
    if failure is not None:
        typer.echo(
            f"warning: could not build @karni/ui: {failure}\n"
            f"Build it yourself before `npm install` in frontend/: {rebuild}",
            err=True,
        )


def new(
    name: str = typer.Argument(..., help="Project name (slug is derived from it)"),
    output_dir: Path = typer.Option(Path("."), "--output-dir", "-o"),
    domain: str = typer.Option("example.com", "--domain", help="Production domain for Caddy"),
) -> None:
    from cookiecutter.main import cookiecutter  # lazy: heavy import

    slug = validate_name(name)
    template = resolve_template()
    ui_source = scaffold.resolve_ui_source()
    if ui_source is not None:
        prepare_ui_source(ui_source)
    cookiecutter(
        str(template),
        no_input=True,
        extra_context={
            "project_name": name,
            "domain": domain,
            "karni_ui": (ui_spec := scaffold.ui_spec(ui_source, output_dir / slug)),
            "karni_ui_mount": scaffold.ui_mount_target(ui_spec),
        },
        output_dir=str(output_dir),
    )
    adapters = write_agent_adapters(output_dir / slug)
    typer.echo(f"Created {output_dir / slug} ({adapters} agent adapter files)")
    if ui_source is not None:
        typer.echo(f"@karni/ui: {ui_spec} (local checkout)")
    else:
        typer.echo(
            f"@karni/ui: {scaffold.UI_REGISTRY_SPEC} from npm — until it is published, "
            "set KARNI_UI_SRC=/path/to/Karni/packages/karni-ui and re-run karni new."
        )
    typer.echo("Next steps:")
    typer.echo(f"  cd {slug}")
    typer.echo("  cp .env.example .env")
    typer.echo("  docker compose up -d")
    typer.echo(
        "  (cd frontend && npm install)  # editor, lint, type-check and `karni check` on the host"
    )
    typer.echo("  karni check")
