"""``karni explain CODE`` — what an error code means and how to fix it, offline.

    karni explain E104        a Karni error or system check (E/W codes)
    karni explain C101        a karni command error (C codes)
    karni explain PAY004      an installed module's code (asks the project interpreter)
    karni explain K106        an agent rule (same as karni rules --explain K106)

Works without Django and without a project; every error Karni prints starts
with its code, so an agent can run this instead of searching the docs.
"""

from __future__ import annotations

import json
import re

import typer

from karni_cli import agent_data
from karni_cli.errorcodes import lookup
from karni_cli.project import CliError, find_project
from karni_cli.rules_render import render_explain

_RULE = re.compile(r"^[KP]\d{3}$")


def render_entry(entry: dict[str, str]) -> str:
    return "\n".join(
        [
            f"{entry['code']}  {entry['title']}  ({entry['kind']})",
            "",
            f"Why:   {entry['why']}",
            f"Fix:   {entry['fix']}",
            f"From:  {entry['source']}",
            f"Docs:  {entry['url']}",
        ]
    )


def explain(
    code: str = typer.Argument(..., help="An error code such as E104, W101, C101, PAY004 or K106."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Explain an error code: why Karni objects and the exact fix."""
    wanted = code.strip().upper()
    if _RULE.match(wanted):
        rule = agent_data.load(find_project()).rule(wanted)
        if rule is None:
            raise CliError(f"No rule {wanted!r} — `karni rules` lists the codes.", code="C204")
        typer.echo(json.dumps(rule, indent=2) if as_json else render_explain(rule))
        return
    entry = lookup(wanted)
    if entry is None:
        raise CliError(
            f"Unknown code {code!r}. Codes look like E104, W101, C101, PAY004 or K106 and "
            "start every Karni error message; a module's codes are found inside a project "
            "that installs it. docs/errors.md lists every code.",
            code="C204",
        )
    typer.echo(json.dumps(entry, indent=2) if as_json else render_entry(entry))
