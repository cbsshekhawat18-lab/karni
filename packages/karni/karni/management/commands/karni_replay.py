"""``manage.py karni_replay <request-id>`` — re-run a captured request now (``karni replay``).

Same method, path, query and body, force-authenticated as the captured user
(or ``--as <email|username|pk>``, or ``--anonymous``), in-process; prints
the status, a body excerpt and what changed (``was 403, now 200``). Writes
are rolled back unless ``--commit``. Redacted values must be supplied with
``--set field=value`` (``--set query:name=value`` for a query parameter) or
left out with ``--drop-redacted``. Refuses with ``DEBUG`` off.

Override / escape hatch: :func:`karni.debug.replay.replay` is the importable
equivalent.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni.exceptions import KarniCommandError


class Command(BaseCommand):
    help = "Re-run a captured request against the current code (rolled back unless --commit)."
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("request_id", help="A captured request id, or `last`.")
        parser.add_argument(
            "--as", dest="as_user", help="Replay as this user (email, username or pk)."
        )
        parser.add_argument("--anonymous", action="store_true", help="Replay without a user.")
        parser.add_argument(
            "--set",
            dest="sets",
            action="append",
            default=[],
            metavar="FIELD=VALUE",
            help="Supply a redacted value (dotted body path, or query:name). Repeatable.",
        )
        parser.add_argument(
            "--drop-redacted", action="store_true", help="Leave redacted values out instead."
        )
        parser.add_argument(
            "--commit", action="store_true", help="Keep the writes (default: roll back)."
        )
        parser.add_argument("--json", action="store_true", help="Print the result as JSON.")

    def handle(self, *args: Any, **options: Any) -> None:
        from karni.debug import store
        from karni.debug.replay import render, replay
        from karni.debug.trace import NO_CAPTURE_HINT, resolve_request_id

        if options["as_user"] and options["anonymous"]:
            raise KarniCommandError("Pass --as or --anonymous, not both.", code="E924")
        sets: dict[str, str] = {}
        for item in options["sets"]:
            name, sep, value = item.partition("=")
            if not sep or not name:
                raise KarniCommandError(
                    f"--set {item!r}: write FIELD=VALUE, e.g. --set password=s3cret or "
                    "--set query:token=abc.",
                    code="E923",
                )
            sets[name] = value
        request_id = resolve_request_id(options["request_id"])
        record = store.read_request(request_id)
        if record is None:
            raise KarniCommandError(
                f"No request record for {request_id} under .karni/requests/ (the newest "
                f"{store.keep_count()} are kept). {NO_CAPTURE_HINT}",
                code="E921",
            )
        result = replay(
            record,
            as_user=options["as_user"],
            anonymous=options["anonymous"],
            sets=sets,
            drop_redacted=options["drop_redacted"],
            commit=options["commit"],
        )
        self.stdout.write(
            store.dumps(result.as_dict(), indent=2) if options["json"] else render(result)
        )
