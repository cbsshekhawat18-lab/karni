"""Shared plumbing for the debugging commands: ``karni trace``, ``karni replay``, ``karni explain --failure``.

Each runs a ``karni_*`` management command (``karni_trace``,
``karni_replay``, ``karni_failure``) through the project interpreter and
returns its output: the captures live under the project's ``.karni/`` and
the change log in its database, both read Django-side. A project whose
karni predates the commands gets ``C322``; the command's own errors
(``E920``–``E924``) pass through with their codes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from karni_cli import project as project_mod
from karni_cli.project import CliError, DatabaseUse

__all__ = ["explain_failure", "parse_sets", "replay_args", "run_debug_command"]

#: Django prints a command error as "<ExceptionClass>: <message>".
_MANAGEMENT_ERROR = re.compile(r"^\w*(?:Error|Exception): ")
_CODED = re.compile(r"^([A-Z]{1,5}\d{3}): (.*?)(?:\s+See https?://\S+)?$", re.DOTALL)


def run_debug_command(
    project: Path,
    args: list[str],
    *,
    docker: bool | None = None,
    service: str | None = None,
    database: DatabaseUse = "load",
) -> str:
    """Run ``manage.py <args>`` and return its output; a failure becomes a :class:`CliError`."""
    proc = project_mod.run_manage(
        project,
        args,
        docker=docker,
        service=service or os.environ.get("KARNI_COMPOSE_SERVICE", "django"),
        capture=True,
        database=database,
    )
    if proc.returncode == 0:
        return (proc.stdout or "").rstrip("\n")
    stderr = (proc.stderr or "").strip()
    if f"Unknown command: '{args[0]}'" in stderr:
        raise CliError(
            f"The project's karni has no `{args[0]}` command: `karni trace`, `karni replay` and "
            "`karni explain --failure` need a newer karni in the project. Upgrade it "
            "(`karni upgrade`, or bump karni in pyproject.toml and reinstall).",
            code="C322",
        )
    lines = [line for line in stderr.splitlines() if line.strip()]
    tail = lines[-1] if lines else ""
    # A coded management error reads "KarniCommandError: E921: <message> See <url>":
    # keep its code.
    coded = _CODED.match(_MANAGEMENT_ERROR.sub("", tail, count=1))
    if coded:
        raise CliError(coded.group(2), code=coded.group(1))
    raise CliError(
        f"manage.py {args[0]} failed (exit {proc.returncode}): {tail or 'no output'}. Run "
        f"`karni manage {' '.join(args)}` to see its full output.",
        code="C323",
    )


def parse_sets(values: list[str]) -> list[str]:
    """Validate ``--set FIELD=VALUE`` items (``C321`` names the bad one)."""
    for item in values:
        name, sep, _value = item.partition("=")
        if not sep or not name.strip():
            raise CliError(
                f"--set {item!r} is not FIELD=VALUE. Write the body path and the value, e.g. "
                "--set password=s3cret, --set card.token=tok_1, or --set query:token=abc for a "
                "query parameter.",
                code="C321",
            )
    return values


def replay_args(
    request_id: str,
    *,
    as_user: str | None = None,
    anonymous: bool = False,
    sets: list[str] | None = None,
    drop_redacted: bool = False,
    commit: bool = False,
    as_json: bool = False,
) -> list[str]:
    """The ``manage.py karni_replay`` argv for these options."""
    args = ["karni_replay", request_id]
    if as_user:
        args += ["--as", as_user]
    if anonymous:
        args.append("--anonymous")
    for item in parse_sets(list(sets or [])):
        args += ["--set", item]
    if drop_redacted:
        args.append("--drop-redacted")
    if commit:
        args.append("--commit")
    if as_json:
        args.append("--json")
    return args


def explain_failure(failure_id: str, *, as_json: bool = False) -> str:
    """``karni explain --failure``: the failure brief (``--json``: the whole snapshot)."""
    project = project_mod.require_project()
    args = ["karni_failure", failure_id, *(["--json"] if as_json else [])]
    return run_debug_command(project, args)
