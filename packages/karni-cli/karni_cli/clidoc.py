"""Render docs/cli.md from the typer app — the CLI reference is generated, never hand-written.

    python -m karni_cli.clidoc > docs/cli.md

``tests/test_clidoc.py`` fails when docs/cli.md differs from :func:`render`,
so a changed option or help text must be regenerated in the same commit.
Everything comes from the click command tree typer builds (help texts,
arguments, options, defaults) plus :data:`karni_cli.generators.GENERATORS`
and the field DSL reference (:data:`karni_cli.generators.fields.FIELD_DOCS`).
"""

from __future__ import annotations

import textwrap
from pathlib import PurePath
from typing import Any

import typer

from karni_cli.commands.make import list_text
from karni_cli.generators.fields import FIELD_DOCS

#: Section → top-level commands, in reading order. Anything else lands in "Other".
SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Project", ("new", "add", "upgrade", "doctor", "config")),
    ("Agents and checks", ("context", "rules", "check", "explain", "types", "mcp")),
    (
        "Runners",
        (
            "serve",
            "migrate",
            "test",
            "shell",
            "routes",
            "worker",
            "beat",
            "schedule",
            "seed",
            "sync-roles",
            "createsuperuser",
            "manage",
        ),
    ),
    ("Generators", ("make",)),
    # The development capture under .karni/ (docs/debugging/).
    ("Debugging", ("trace", "replay")),
)

HEADER = """---
description: Every karni command with its arguments and options, generated from the CLI's own help text.
---

# The `karni` command

> Generated from the CLI itself — `python -m karni_cli.clidoc > docs/cli.md`;
> `packages/karni-cli/tests/test_clidoc.py` fails when this file is stale.
> Change a command's help, then regenerate; never edit this file by hand.

`karni <command> --help` prints the same information. Runners execute in the
project environment: the project's `.venv`, else the running docker compose
service (`--docker/--no-docker` forces one; `--service` / `KARNI_COMPOSE_SERVICE`
names it). Put `--` before passthrough arguments that clash with karni's own
options.

On the host, a command that starts Django first checks that the database
driver loads, and one that opens the database (`migrate`, `seed`,
`serve --local`, `test`, ...) that the server answers. A missing driver or an
unreachable database is a coded error with the fix
([C012](errors.md#c012), [C013](errors.md#c013)) instead of Django's
traceback; `KARNI_DB_CHECK=false` skips the check.
"""

GENERATOR_RULES = """Every generator follows the same rules:

- It writes project code only — never framework logic.
- It never overwrites: an existing target is an error naming the file and
  `--force` (which replaces it).
- `--dry-run` prints the files and the diff it would write, and writes nothing.
- It prints every created and modified file, then any notes (the chosen
  `access`, the route, the next command).
- The target app is `--app <label>`, else the project's only local app (local
  apps are the `# karni:apps` entries of config/settings.py).
- Existing files change only through marker comments (`# karni:apps`,
  `# karni:middleware`, `// karni:page-imports`, `// karni:routes`) or
  AST-located appends; an unfamiliar layout is an error that names the manual
  step. Generated Python is ruff-clean (isort sections, ruff format layout).
- It never imports Django: `karni make migration` (and `make model --migrate`)
  run `manage.py makemigrations` through the project interpreter.
- Every generator is also available as a hidden Laravel-style alias:
  `karni make:<type>` (e.g. `karni make:model Event title:str`).
"""


def _md(text: str) -> str:
    """Escape ``<`` / ``>`` outside backtick code spans (Markdown would eat ``<field>``)."""
    parts = text.split("`")
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("<", "&lt;").replace(">", "&gt;")
    return "`".join(parts)


def _escape(text: str) -> str:
    """A table cell: Markdown-escaped, pipes escaped, one line."""
    return _md(text).replace("|", "\\|").replace("\n", " ")


def _paragraphs(help_text: str | None) -> str:
    """Help text as Markdown: paragraphs re-flowed, ``Example:`` paragraphs as code."""
    if not help_text:
        return ""
    blocks: list[str] = []
    for raw in textwrap.dedent(help_text).strip().split("\n\n"):
        text = " ".join(line.strip() for line in raw.strip().splitlines())
        if not text or text == "\b":
            continue
        for label in ("Example:", "Examples:"):
            if text.startswith(label):
                code = text[len(label) :].strip()
                blocks.append(f"{label}\n\n```sh\n{code}\n```")
                break
        else:
            blocks.append(_md(text))
    return "\n\n".join(blocks)


# Typer >= 0.20 vendors its own click (typer._click), older ones use click: the
# command tree is read by duck typing, never isinstance against a click import.
Command = Any
Parameter = Any


def _is_argument(param: Parameter) -> bool:
    return getattr(param, "param_type_name", "") == "argument"


def _subcommands(command: Command) -> dict[str, Command]:
    commands = getattr(command, "commands", None)
    return dict(commands) if isinstance(commands, dict) else {}


_TYPE_LABELS = {"str": "TEXT", "string": "TEXT", "text": "TEXT", "int": "INTEGER"}


def _metavar(param: Parameter) -> str:
    """A stable value label (click and typer's vendored click name types differently)."""
    name = str(getattr(param.type, "name", "text")).lower()
    return _TYPE_LABELS.get(name, name.upper())


def _default(param: Parameter) -> str:
    value: Any = param.default
    if callable(value) or value in (None, False, "", (), []):
        return ""
    if value is True:
        return "on"
    if isinstance(value, PurePath):
        value = value.as_posix()
    return f"`{value}`"


def _param_row(param: Parameter) -> str | None:
    if getattr(param, "hidden", False):
        return None
    help_text = _escape(getattr(param, "help", None) or "")
    if _is_argument(param):
        name = (param.name or "").rstrip("_").upper()
        name += "..." if param.nargs == -1 else ""
        label = f"`{name}`" + (" (required)" if param.required else "")
    else:
        flags = list(param.opts)
        if param.secondary_opts:
            flags = [f"{flags[0]}/{param.secondary_opts[0]}", *flags[1:]]
        label = ", ".join(f"`{flag}`" for flag in flags)
        if not param.is_flag:
            label += f" {_metavar(param)}"
        if param.multiple:
            label += " (repeatable)"
        if param.required:
            label += " (required)"
        if param.envvar:
            envvars = [param.envvar] if isinstance(param.envvar, str) else list(param.envvar)
            help_text = f"{help_text} Env: {', '.join(f'`{e}`' for e in envvars)}.".strip()
    return f"| {label} | {_default(param)} | {help_text} |"


def _usage(path: str, command: Command) -> str:
    pieces = [f"karni {path}"]
    if any(not _is_argument(p) and not getattr(p, "hidden", False) for p in command.params):
        pieces.append("[OPTIONS]")
    for param in command.params:
        if _is_argument(param):
            name = (param.name or "").rstrip("_").upper()
            name += "..." if param.nargs == -1 else ""
            pieces.append(name if param.required else f"[{name}]")
    if _subcommands(command):
        pieces.append("COMMAND [ARGS]...")
    return " ".join(pieces)


def _command(path: str, command: Command, level: int) -> list[str]:
    out = [f"{'#' * level} `karni {path}`", ""]
    body = _paragraphs(command.help)
    if body:
        out += [body, ""]
    out += ["```", _usage(path, command), "```", ""]
    rows = [row for row in (_param_row(p) for p in command.params) if row]
    if rows:
        out += ["| Argument / option | Default | Description |", "| --- | --- | --- |", *rows, ""]
    if path == "make":
        out += [
            GENERATOR_RULES,
            "`karni make --list`:",
            "",
            "```",
            list_text(),
            "```",
            "",
            "Field DSL for `karni make model NAME [FIELD...]`:",
            "",
            "| Field | Generates |",
            "| --- | --- |",
            *(f"| `{_escape(syntax)}` | {_escape(result)} |" for syntax, result in FIELD_DOCS),
            "",
        ]
    for name, sub in _subcommands(command).items():
        if not sub.hidden:
            out += _command(f"{path} {name}", sub, level + 1)
    return out


def render(app: typer.Typer | None = None) -> str:
    """docs/cli.md for ``app`` (default: the ``karni`` app)."""
    if app is None:
        from karni_cli.main import app as karni_app

        app = karni_app
    root = typer.main.get_command(app)
    visible = {name: cmd for name, cmd in _subcommands(root).items() if not cmd.hidden}
    placed = {name for _, names in SECTIONS for name in names}
    sections = [*SECTIONS, ("Other", tuple(n for n in visible if n not in placed))]
    out = [HEADER, "## Contents", ""]
    for title, names in sections:
        present = [n for n in names if n in visible]
        if present:
            links = ", ".join(f"[{n}](#karni-{n})" for n in present)
            out.append(f"- **{title}**: {links}")
    out.append("")
    for title, names in sections:
        present = [n for n in names if n in visible]
        if not present:
            continue
        out += [f"## {title}", ""]
        for name in present:
            out += _command(name, visible[name], 3)
    return "\n".join(out).rstrip("\n") + "\n"


def main() -> None:
    typer.echo(render(), nl=False)


if __name__ == "__main__":
    main()
