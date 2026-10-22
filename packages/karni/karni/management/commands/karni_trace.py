"""``manage.py karni_trace <request-id>`` — one request's whole story, in order (``karni trace``).

Reads ``.karni/trace/*.jsonl`` (the request, the tasks it enqueued and their
retries, email, webhooks, audit batches) and the change log entries with
that request id, and prints them as a timeline with offsets and durations.
``last`` follows the newest captured request; ``--json`` prints the story as
JSON for agents. Without a capture it says so and how to enable one (exit 1).

Override / escape hatch: :func:`karni.debug.trace.story` and
:func:`karni.debug.trace.render` are the importable equivalents.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni.exceptions import KarniCommandError


class Command(BaseCommand):
    help = "Print a captured request's story: request, tasks, retries, email, webhooks, audit."
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("request_id", help="A request id (X-Request-ID), or `last`.")
        parser.add_argument("--json", action="store_true", help="Print the story as JSON.")

    def handle(self, *args: Any, **options: Any) -> None:
        from karni.debug.store import dumps
        from karni.debug.trace import NO_CAPTURE_HINT, render, resolve_request_id, story

        request_id = resolve_request_id(options["request_id"])
        found = story(request_id)
        if found is None:
            raise KarniCommandError(
                f"Nothing was captured for request {request_id}: no trace events, request "
                f"record or change log entries carry that id. {NO_CAPTURE_HINT}",
                code="E921",
            )
        self.stdout.write(dumps(found, indent=2) if options["json"] else render(found))
