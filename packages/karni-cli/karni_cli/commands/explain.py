"""``karni explain CODE`` — what an error code means and how to fix it, offline.

    karni explain E104        a Karni error or system check (E/W codes)
    karni explain C101        a karni command error (C codes)
    karni explain PAY004      an installed module's code (asks the project interpreter)
    karni explain K106        an agent rule (same as karni rules --explain K106)
    karni explain --failure last   a captured failure as a brief (in a project, DEBUG on)
    karni explain -           a pasted traceback, test failure or log line (stdin)

Works without Django and without a project; every error Karni prints starts
with its code, so an agent can run this instead of searching the docs. With
``-`` (or no code while stdin is not a terminal) it reads text and names the
Karni failure in it: class, cause, where, fix and docs (:mod:`karni_cli.explain_text`).
"""

from __future__ import annotations

import json
import re
import sys

import typer

from karni_cli import agent_data
from karni_cli import explain_text as explain_text_mod
from karni_cli.errorcodes import lookup
from karni_cli.project import CliError, find_project
from karni_cli.rules_render import render_explain

_RULE = re.compile(r"^[KP]\d{3}$")
#: An argument that cannot be a code (spaces, a colon): a log line passed inline.
_TEXT = re.compile(r"[\s:]")


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


def _explain_failure(code: str | None, failure: str, as_json: bool) -> None:
    """``--failure ID``: a captured failure as a brief (karni_cli.debugging)."""
    if code:
        raise CliError(
            "Pass an error code or --failure <id>, not both: `karni explain E104`, "
            "`karni explain --failure last`.",
            code="C320",
        )
    from karni_cli.debugging import explain_failure

    typer.echo(explain_failure(failure, as_json=as_json))


def explain_text(text: str, as_json: bool) -> None:
    """``karni explain -``: the failure in ``text`` (or that Karni does not know it)."""
    typer.echo(explain_text_mod.render(text, as_json=as_json))


def _stdin_text() -> str:
    if sys.stdin is None or sys.stdin.isatty():
        raise CliError(
            "Nothing to explain: give a code (karni explain E104), pipe a traceback or log "
            "line into karni explain -, or name a captured failure (karni explain --failure "
            "last).",
            code="C340",
        )
    return sys.stdin.read()


def explain(
    code: str | None = typer.Argument(
        None,
        help="An error code such as E104, W101, C101, PAY004 or K106. Pass - to read a "
        "traceback or log line from stdin.",
        show_default=False,
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    failure: str | None = typer.Option(
        None,
        "--failure",
        help="A captured failure id (.karni/failures/), a failed request's id, or `last`: "
        "print it as a brief (development, DEBUG on).",
    ),
) -> None:
    """Explain an error code, a captured failure (--failure), or the failure in a pasted
    traceback or log line (-)."""
    if failure is not None:
        _explain_failure(code, failure, as_json)
        return
    if code is None or code == "-":
        explain_text(_stdin_text(), as_json)
        return
    if _TEXT.search(code.strip()):
        explain_text(code, as_json)
        return
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
            "that installs it. docs/errors.md lists every code. To explain a traceback or a "
            "log line, pipe it in: karni explain - < traceback.txt",
            code="C204",
        )
    typer.echo(json.dumps(entry, indent=2) if as_json else render_entry(entry))
