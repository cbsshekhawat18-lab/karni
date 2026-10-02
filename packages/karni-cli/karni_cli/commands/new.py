"""``karni new <name>`` — scaffold a project from templates/project."""

from __future__ import annotations

from pathlib import Path

import typer

from karni_cli.scaffold import resolve_template, validate_name


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
    typer.echo(f"Created {output_dir / slug}")
    typer.echo("Next steps:")
    typer.echo(f"  cd {slug}")
    typer.echo("  cp .env.example .env")
    typer.echo("  docker compose up -d")
    typer.echo("  karni check")
