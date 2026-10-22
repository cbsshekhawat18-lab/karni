"""``karni why`` / ``karni why-empty`` — explain an access decision (``manage.py karni_why``).

    karni why 403 <request-id>                         a request the dev server recorded
    karni why events/<id> --as alice@x.test [--action update|delete|<action>]
    karni why events.internal_note --as alice@x.test   a hidden or read-only field
    karni why-empty events --as alice@x.test [--param status=draft]

The CLI only checks the question's shape (C310, C311) and runs the project's
``manage.py karni_why`` through the project interpreter; the decision is
computed in the project, by the code that enforces it (``karni.why``).
"""

from __future__ import annotations

import re
from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project

__all__ = ["run_why", "why", "why_args", "why_empty", "why_empty_args"]

_STATUS = re.compile(r"^[1-5]\d\d$")

TARGET_HELP = (
    "What to explain: `<resource>/<id>` (a row), `<resource>.<field>` (a field), "
    "`<resource>` (its list), or a status followed by a request id (`403 <request-id>`). "
    "Resources are named as the API names them: `events`, `events-event` or `events.Event`."
)
AS_HELP = "The user: email, username, primary key, or anonymous."
ACTION_HELP = (
    "For a row: view (default), update, delete, or an @action name. For a resource: create or list."
)
PARAM_HELP = "A query parameter the request carries, key=value (repeatable)."


def why_args(
    target: str,
    request_id: str | None = None,
    *,
    user: str | None = None,
    action: str | None = None,
    method: str | None = None,
    params: list[str] | None = None,
    as_json: bool = False,
) -> list[str]:
    """The ``manage.py karni_why`` argv for a ``karni why`` question, or a coded CliError."""
    text = target.strip()
    if not text:
        raise CliError(f"karni why needs a target. {TARGET_HELP}", code="C310")
    if _STATUS.match(text):
        if not request_id:
            raise CliError(
                f"`karni why {text}` needs the request id: karni why {text} <request-id>. Records "
                "are written by the dev server under .karni/requests/ (DEBUG only); without "
                "one, ask about the row: karni why <resource>/<id> --as <user>.",
                code="C310",
            )
        args = ["karni_why", text, request_id]
    else:
        if request_id:
            raise CliError(
                f"Unexpected {request_id!r} after {text!r}: only a status takes a request id "
                "(karni why 403 <request-id>); a row is <resource>/<id>.",
                code="C310",
            )
        if text.endswith("/") or text.startswith("/"):
            raise CliError(
                f"karni why {text!r}: not a target. Write <resource>/<id> (events/42), "
                "<resource>.<field> or <resource>.",
                code="C310",
            )
        if not user:
            raise CliError(
                f"`karni why {text}` needs --as <user>: an email, username or primary key, or "
                "--as anonymous for a request that is not signed in.",
                code="C311",
            )
        args = ["karni_why", text, "--as", user]
        if action:
            args += ["--action", action]
        if method:
            args += ["--method", method]
    for param in params or []:
        args += ["--param", param]
    if as_json:
        args.append("--json")
    return args


def why_empty_args(
    resource: str, *, user: str | None, params: list[str] | None = None, as_json: bool = False
) -> list[str]:
    """The ``manage.py karni_why --empty`` argv for a ``karni why-empty`` question."""
    name = resource.strip().strip("/")
    if not name:
        raise CliError(
            "karni why-empty needs the resource, e.g. karni why-empty events.", code="C310"
        )
    if not user:
        raise CliError(
            f"`karni why-empty {name}` needs --as <user>: an email, username or primary key, or "
            "--as anonymous.",
            code="C311",
        )
    args = ["karni_why", name, "--empty", "--as", user]
    for param in params or []:
        args += ["--param", param]
    if as_json:
        args.append("--json")
    return args


def run_why(
    args: list[str],
    *,
    project: Path | None = None,
    docker: bool | None = None,
    service: str = "django",
) -> tuple[int, str, str]:
    """Run ``manage.py <args>`` in the project; ``(returncode, stdout, stderr)``."""
    project = project or require_project()
    proc = project_mod.run_manage(
        project, args, docker=docker, service=service, capture=True, database="connect"
    )
    stderr = proc.stderr or ""
    if proc.returncode != 0 and "Unknown command: 'karni_why'" in stderr:
        raise CliError(
            "The project's karni has no karni_why command: it is older than this karni-cli. "
            "Upgrade karni in the project (pip install -U karni, or rebuild the image), then "
            "run the question again.",
            code="C312",
        )
    return proc.returncode, proc.stdout or "", stderr


def _emit(code: int, out: str, err: str) -> None:
    if out:
        typer.echo(out.rstrip("\n"))
    if err:
        typer.echo(err.rstrip("\n"), err=True)
    raise typer.Exit(code)


def why(
    target: str = typer.Argument(..., help=TARGET_HELP),
    request_id: str | None = typer.Argument(None, help="The request id, after a status."),
    user: str | None = typer.Option(None, "--as", help=AS_HELP),
    action: str | None = typer.Option(None, "--action", help=ACTION_HELP),
    method: str | None = typer.Option(
        None, "--method", help="The HTTP method, for an @action that answers several."
    ),
    param: list[str] = typer.Option([], "--param", help=PARAM_HELP),
    as_json: bool = typer.Option(False, "--json", help="Print the verdict as JSON (for agents)."),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Explain an access decision — wraps `manage.py karni_why`.

    Says what the API does for one user and why, computed by the code that
    enforces it: the user and roles, the grants that applied and where each
    comes from, the predicate that decided, the row's values for the fields it
    reads (sensitive ones redacted), the result, the file:line of the access
    declaration and the predicate, and one concrete fix.

    Examples: karni why events/42 --as alice@example.com;
    karni why events/42 --as alice@example.com --action update;
    karni why events.internal_note --as alice@example.com;
    karni why 403 <request-id>
    """
    args = why_args(
        target,
        request_id,
        user=user,
        action=action,
        method=method,
        params=param,
        as_json=as_json,
    )
    _emit(*run_why(args, docker=docker, service=service))


def why_empty(
    resource: str = typer.Argument(..., help="The resource, named as the API names it."),
    user: str | None = typer.Option(None, "--as", help=AS_HELP),
    param: list[str] = typer.Option([], "--param", help=PARAM_HELP),
    as_json: bool = typer.Option(False, "--json", help="Print the verdict as JSON (for agents)."),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Explain an empty list — wraps `manage.py karni_why --empty`.

    Counts the rows each step of the read pipeline leaves: the table, each
    model scope (soft delete), the viewset's queryset, access.read part by
    part, filter_queryset_for_user and the request's filters (--param) — and
    names the step that empties the list, with the fix.

    Example: karni why-empty bookings --as organizer@example.com
    """
    args = why_empty_args(resource, user=user, params=param, as_json=as_json)
    _emit(*run_why(args, docker=docker, service=service))
