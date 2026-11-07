"""``karni rules`` — the conventions, file checks, and AGENTS.md sync.

    karni rules                       conventions (code + one line each)
    karni rules --explain K101        full statement, rationale, fix, enforcement
    karni rules --procedure new-model the steps of a standard procedure
    karni rules --check FILE...       static violations with fixes (exit 1 if any)
    karni rules --json                the raw data (rules, procedures)
    karni rules sync [--check] [--force]
                                      regenerate AGENTS.md (CI: --check)

Works without Django and, except ``sync``, without a project; inside one,
``karni.rules.py`` overrides and ``.karni/modules/`` guidance apply.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from typer.core import TyperGroup

from karni_cli import agent_data
from karni_cli.adapters import deprecation_warning, module_fragments, sync
from karni_cli.project import CliError, find_project, require_project
from karni_cli.rules_render import (
    render_explain,
    render_findings,
    render_procedure,
    render_prompts_doc,
    render_rules,
)


def more_checks(args: list[str], commands: set[str]) -> list[str]:
    """``--check a.py b.py`` as ``--check a.py --check b.py``: the words after a checked file.

    A word that is not an option or a subcommand, after ``--check FILE``, is one more
    file to check, until the next option.
    """
    out: list[str] = []
    checking = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--check" and index + 1 < len(args):
            out += [arg, args[index + 1]]
            checking = True
            index += 2
            continue
        if arg.startswith("--check="):
            checking = True
        elif checking and not arg.startswith("-") and arg not in commands:
            out += ["--check", arg]
            index += 1
            continue
        elif arg.startswith("-"):
            checking = False
        out.append(arg)
        index += 1
    return out


class _RulesGroup(TyperGroup):
    """``karni rules``: ``--check`` takes one file or several (``--check a.py b.py``)."""

    # ctx: Typer >= 0.20 vendors its own click (typer._click), older ones use click
    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        return super().parse_args(ctx, more_checks(list(args), set(self.commands)))


rules_app = typer.Typer(
    cls=_RulesGroup,
    help="Karni's conventions for humans and AI agents (no Django needed).",
    no_args_is_help=False,
    add_completion=False,
)


def rules_text(project: Path | None) -> str:
    data = agent_data.load(project)
    return render_rules(data, module_fragments(project) if project else {})


def check_text(paths: list[Path], project: Path | None) -> tuple[str, int]:
    """Rendered findings and their count for ``paths``."""
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise CliError(f"No such file: {', '.join(missing)}", code="C010")
    findings = agent_data.check(paths, project)
    if not findings:
        return f"ok: no violations in {len(paths)} file(s)", 0
    return render_findings(findings), len(findings)


@rules_app.callback(invoke_without_command=True)
def rules(
    ctx: typer.Context,
    check: list[Path] | None = typer.Option(
        None,
        "--check",
        help="Statically check FILE and exit 1 on violations. Several files: --check a.py b.py "
        "(or --check repeated).",
    ),
    explain: str | None = typer.Option(None, "--explain", help="Show one rule in full."),
    procedure: str | None = typer.Option(None, "--procedure", help="Show a procedure's steps."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    prompts_doc: bool = typer.Option(False, "--prompts-doc", hidden=True),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    project = find_project()
    if check:
        if as_json:
            typer.echo(json.dumps(agent_data.check(list(check), project), indent=2))
            return
        text, count = check_text(list(check), project)
        typer.echo(text)
        raise typer.Exit(1 if count else 0)

    data = agent_data.load(project)
    if explain:
        rule = data.rule(explain)
        if rule is None:
            raise CliError(f"No rule {explain!r}. `karni rules` lists the codes.", code="C204")
        typer.echo(json.dumps(rule, indent=2) if as_json else render_explain(rule))
        return
    if procedure:
        found = data.procedure(procedure)
        if found is None:
            names = ", ".join(p["name"] for p in data.procedures)
            raise CliError(f"No procedure {procedure!r} (available: {names}).", code="C204")
        typer.echo(json.dumps(found, indent=2) if as_json else render_procedure(found))
        return
    if prompts_doc:
        typer.echo(render_prompts_doc(data))
        return
    if as_json:
        typer.echo(json.dumps(data.raw, indent=2))
        return
    typer.echo(render_rules(data, module_fragments(project) if project else {}))


@rules_app.command("sync")
def sync_command(
    check: bool = typer.Option(
        False, "--check", help="Only compare, and exit 1 if any adapter is stale (for CI)."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite hand-written files (backed up under .karni/backup/)."
    ),
) -> None:
    """Regenerate AGENTS.md (and any deprecated tool-specific agent file) from the rules."""
    project = require_project()
    data = agent_data.load(project)
    result = sync(project, data, check=check, force=force)
    if result.deprecated:
        typer.echo(f"warning: {deprecation_warning(result.deprecated)}", err=True)
    if check:
        if result.stale:
            for rel in result.stale:
                typer.echo(f"stale: {rel}", err=True)
            typer.echo("Agent adapters are stale. Run `karni rules sync`.", err=True)
            raise typer.Exit(1)
        typer.echo(f"Agent adapters up to date ({len(result.unchanged)} files).")
        return
    for rel in result.backed_up:
        typer.echo(f"backed up: {rel}")
    for rel in result.written:
        typer.echo(f"wrote {rel}")
    for rel in result.removed:
        typer.echo(f"removed {rel}")
    if result.blocked:
        for rel in result.blocked:
            typer.echo(f"skipped {rel}: not generated by karni (hand-written?)", err=True)
        typer.echo(
            "Move project-specific guidance into karni.rules.py (`karni upgrade` does this "
            "for Karni's old scaffold files), then re-run. To overwrite with a backup "
            "instead, pass `--force`.",
            err=True,
        )
        raise typer.Exit(1)
    if not result.written and not result.removed:
        typer.echo(f"Agent adapters up to date ({len(result.unchanged)} files).")
