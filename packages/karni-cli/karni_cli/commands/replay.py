"""``karni replay <request-id>`` — re-run a captured request now (``manage.py karni_replay``).

    karni replay last                         same user, same request, current code
    karni replay 5f0c… --as ops@example.com   as someone else (email, username or pk)
    karni replay 5f0c… --set password=s3cret  supply a value capture redacted
    karni replay 5f0c… --commit               keep the writes (default: rolled back)

In-process (no server), DEBUG only; prints the status, a body excerpt and the
change against the captured status (``was 403, now 200``).
"""

from __future__ import annotations

import typer

from karni_cli.debugging import replay_args, run_debug_command
from karni_cli.project import require_project


def replay(
    request_id: str = typer.Argument(..., help="A captured request id, or `last`."),
    as_user: str | None = typer.Option(
        None, "--as", help="Replay as this user: an email, a username or a primary key."
    ),
    anonymous: bool = typer.Option(False, "--anonymous", help="Replay without a user."),
    sets: list[str] = typer.Option(
        [],
        "--set",
        help="Supply a redacted value: FIELD=VALUE (dotted body path, or query:NAME). Repeatable.",
    ),
    drop_redacted: bool = typer.Option(
        False, "--drop-redacted", help="Leave redacted values out instead of supplying them."
    ),
    commit: bool = typer.Option(
        False, "--commit", help="Keep the writes. By default the replay is rolled back."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Re-run a captured request against the current code, as its user or --as another — wraps `manage.py karni_replay`."""
    project = require_project()
    args = replay_args(
        request_id,
        as_user=as_user,
        anonymous=anonymous,
        sets=sets,
        drop_redacted=drop_redacted,
        commit=commit,
        as_json=as_json,
    )
    output = run_debug_command(project, args, docker=docker, service=service, database="connect")
    typer.echo(output)
