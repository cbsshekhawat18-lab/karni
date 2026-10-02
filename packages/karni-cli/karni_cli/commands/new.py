"""``karni new <name>`` — scaffold a project from templates/project.

The template carries no agent guidance files: they are generated afterwards
by the same code as ``karni rules sync`` (AGENTS.md, CLAUDE.md, Cursor,
Windsurf, Copilot, Cline, Aider, Junie adapters + slash commands).
"""

from __future__ import annotations

from pathlib import Path

import typer

from karni_cli import agent_data
from karni_cli.adapters import sync
from karni_cli.scaffold import resolve_template, validate_name


def write_agent_adapters(project: Path) -> int:
    """Generate the agent adapter files into a freshly rendered project."""
    result = sync(project, agent_data.load(project))
    return len(result.written)


def new(
    name: str = typer.Argument(..., help="Project name (slug is derived from it)"),
    output_dir: Path = typer.Option(Path("."), "--output-dir", "-o"),
    domain: str = typer.Option("example.com", "--domain", help="Production domain for Caddy"),
) -> None:
    from cookiecutter.main import cookiecutter  # lazy: heavy import

    slug = validate_name(name)
    template = resolve_template()
    cookiecutter(
        str(template),
        no_input=True,
        extra_context={"project_name": name, "domain": domain},
        output_dir=str(output_dir),
    )
    adapters = write_agent_adapters(output_dir / slug)
    typer.echo(f"Created {output_dir / slug} ({adapters} agent adapter files)")
    typer.echo("Next steps:")
    typer.echo(f"  cd {slug}")
    typer.echo("  cp .env.example .env")
    typer.echo("  docker compose up -d")
    typer.echo("  karni check")
