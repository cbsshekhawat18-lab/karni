"""``karni explain CODE`` — what an error code means and how to fix it, offline.

    karni explain E104        a Karni error or system check (E/W codes)
    karni explain C101        a karni command error (C codes)
    karni explain PAY004      an installed module's code (asks the project interpreter)
    karni explain K106        an agent rule (same as karni rules --explain K106)
    karni explain KARNI_SITE_HIGHLIGHT   a setting: its default, variable and docs link
    karni explain image       a karni-site template tag or filter ("{% image %}" works too)
    karni explain map.items   a content map key (karni explain map lists every one)
    karni explain access      a reference: karni.yaml's access words and the common rules
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

from karni_cli import agent_data, settingref, templateref
from karni_cli import explain_text as explain_text_mod
from karni_cli.design import mapref
from karni_cli.errorcodes import lookup
from karni_cli.project import CliError, find_project
from karni_cli.rules_render import render_explain, render_topic

_RULE = re.compile(r"^[KP]\d{3}$")
#: A word that may name a reference (``karni explain access``): letters and dashes only.
_TOPIC = re.compile(r"^[A-Za-z][A-Za-z-]*$")
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


def _explain_map(text: str, as_json: bool) -> None:
    """``karni explain map`` (every key) or ``map.<key>`` / ``map.<level>.<key>`` (one)."""
    keys = mapref.lookup(text)
    if not keys:
        raise CliError(
            f"No content map key {text.strip()!r}. `karni explain map` lists every key, by "
            "where it is written: map.items, map.source.key, map.value.by.",
            code="C375",
        )
    url = templateref.docs_url(mapref.DOCS_PAGE, mapref.DOCS_ANCHOR)
    if as_json:
        typer.echo(json.dumps([{**key.to_dict(), "url": url} for key in keys], indent=2))
    else:
        typer.echo(mapref.render(keys, url))


def _explain_tag(text: str, as_json: bool, *, required: bool) -> bool:
    """Print the template tag ``text`` names. ``required``: no such tag is an error."""
    found = templateref.explain(text, as_json=as_json)
    if found is not None:
        typer.echo(found)
        return True
    if not required:
        return False
    reachable = templateref.tag_reference() is not None
    raise CliError(
        f"No template tag {text.strip()!r} in karni-site. "
        + (
            "`karni explain` names each of its tags and filters, docs/public-site.md lists them."
            if reachable
            else "Run it inside a project that installs karni-site, which has the tag list."
        ),
        code="C374",
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
        help="An error code such as E104, W101, C101, PAY004 or K106, a setting such as "
        "KARNI_SITE_HIGHLIGHT, a template tag such as image, a content map key such as "
        "map.items, or a reference such as access. Pass - to read a traceback or log line "
        "from stdin.",
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
    """Explain an error code, a setting (its default, environment variable and docs), a
    template tag, a content map key, a reference (access: karni.yaml's access rules), a
    captured failure (--failure), or the failure in a pasted traceback or log line (-)."""
    if failure is not None:
        _explain_failure(code, failure, as_json)
        return
    if code is None or code == "-":
        explain_text(_stdin_text(), as_json)
        return
    written = code.strip()
    if written.lower() == "map" or written.lower().startswith("map."):
        _explain_map(written, as_json)
        return
    if _TOPIC.match(written):
        topic = agent_data.load(find_project()).topic(written)
        if topic is not None:
            typer.echo(json.dumps(topic, indent=2) if as_json else render_topic(topic))
            return
    if written.startswith(("{%", "{{")) and templateref.TAG.match(written):
        _explain_tag(written, as_json, required=True)
        return
    if templateref.TAG.match(written) and _explain_tag(written, as_json, required=False):
        return
    if _TEXT.search(written):
        explain_text(code, as_json)
        return
    wanted = code.strip().upper()
    if _RULE.match(wanted):
        rule = agent_data.load(find_project()).rule(wanted)
        if rule is None:
            raise CliError(f"No rule {wanted!r}. `karni rules` lists the codes.", code="C204")
        typer.echo(json.dumps(rule, indent=2) if as_json else render_explain(rule))
        return
    if settingref.SETTING.match(wanted):
        setting = settingref.lookup(wanted)
        if setting is None:
            raise CliError(
                f"No setting {wanted}: neither Karni nor a module installed here or in the "
                "project declares it. docs/settings.md lists every setting, module settings "
                "included. A project's own settings are in config/settings.py.",
                code="C373",
            )
        typer.echo(json.dumps(setting, indent=2) if as_json else settingref.render(setting))
        return
    entry = lookup(wanted)
    if entry is None:
        raise CliError(
            f"Unknown code {code!r}. Codes look like E104, W101, C101, PAY004 or K106 and "
            "start every Karni error message. A third-party module's codes are found inside a "
            "project that installs it. docs/errors.md lists every code. karni explain also takes a "
            "setting (KARNI_SITE_HIGHLIGHT), a template tag (image), a content map key "
            "(map.items) and a reference (access). To explain a traceback or a log line, pipe it "
            "in: "
            "karni explain - < traceback.txt",
            code="C204",
        )
    typer.echo(json.dumps(entry, indent=2) if as_json else render_entry(entry))
