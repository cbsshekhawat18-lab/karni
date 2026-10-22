"""``karni trace <request-id>`` — one request's story, in order (``manage.py karni_trace``).

    karni trace 5f0c2e9a-…        the request, its tasks and retries, email, webhooks, audit
    karni trace last              the newest captured request
    karni trace last --json       the same as JSON, for agents

Reads what the development capture wrote under ``.karni/`` (DEBUG only) and
the change log entries carrying the id; the id is every response's
``X-Request-ID`` header.
"""

from __future__ import annotations

import typer

from karni_cli.debugging import run_debug_command
from karni_cli.project import require_project


def trace(
    request_id: str = typer.Argument(
        ..., help="A request id (the X-Request-ID response header), or `last`."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the story as JSON."),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Follow a captured request: tasks, retries, email, webhooks, audit entries — wraps `manage.py karni_trace`."""
    project = require_project()
    args = ["karni_trace", request_id, *(["--json"] if as_json else [])]
    typer.echo(run_debug_command(project, args, docker=docker, service=service))
