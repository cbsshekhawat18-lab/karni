"""``manage.py karni_why`` — explain an access decision (``karni why``, ``karni why-empty``).

Targets::

    karni_why 403 <request-id>                    a request the dev server recorded
    karni_why events/<id> --as alice [--action update]
    karni_why events.internal_note --as alice     a hidden or read-only field
    karni_why events --empty --as alice [--param status=draft]

``--as`` takes an email, username, primary key or ``anonymous``; resources
are named as the API names them (the route prefix, the router basename or
the model label). ``--json`` prints the verdict as one JSON object.

Override / escape hatch: :mod:`karni.why` is importable (``explain_row``,
``explain_field``, ``explain_list``, ``explain_record``).
"""

from __future__ import annotations

import json
import re
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni.exceptions import KarniCommandError

_STATUS = re.compile(r"^[1-5]\d\d$")


def _query(params: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for param in params:
        key, sep, value = param.partition("=")
        if not sep or not key:
            raise KarniCommandError(
                f"--param {param!r} must look like key=value (e.g. --param status=draft).",
                code="E908",
            )
        found.setdefault(key, []).append(value)
    return found


class Command(BaseCommand):
    help = (
        "Explain an access decision: why a row, field or action is refused or missing for a "
        "user (--json for agents)."
    )
    # An explanation must print even when system checks fail; `karni check` owns checks.
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "target",
            help="403 <request-id> | <resource>/<id> | <resource>.<field> | <resource>",
        )
        parser.add_argument("request_id", nargs="?", help="The request id after a status.")
        parser.add_argument("--as", dest="user", help="Email, username, pk, or anonymous.")
        parser.add_argument(
            "--action", help="view (default), update, delete, create, list, or an @action."
        )
        parser.add_argument(
            "--method", help="The HTTP method, for an @action that answers several."
        )
        parser.add_argument(
            "--param",
            action="append",
            default=[],
            help="A query parameter the request carries (key=value, repeatable).",
        )
        parser.add_argument(
            "--empty", action="store_true", help="Explain the user's list (why-empty)."
        )
        parser.add_argument("--json", action="store_true", help="Print the verdict as JSON.")

    def handle(self, *args: Any, **options: Any) -> None:
        from karni.why import WhyError

        try:
            verdict = self._verdict(options)
        except WhyError as exc:
            raise KarniCommandError(exc.message, code=exc.code) from None
        if options["json"]:
            self.stdout.write(json.dumps(verdict.to_dict(), indent=2, default=str))
        else:
            self.stdout.write(verdict.text())

    def _verdict(self, options: dict[str, Any]) -> Any:
        from karni.why import (
            WhyError,
            explain_field,
            explain_list,
            explain_record,
            explain_row,
            resolve_resource,
            resolve_user,
        )

        target = str(options["target"]).strip()
        request_id = options.get("request_id")
        if _STATUS.match(target):
            if not request_id:
                raise WhyError(
                    f"`karni why {target}` needs the request id: karni why {target} <request-id> "
                    "(the dev server records each request under .karni/requests/).",
                    code="E908",
                )
            return explain_record(str(request_id), asked=int(target))
        if request_id:
            raise WhyError(
                f"Unexpected {request_id!r} after {target!r}: a request id follows a status "
                "(karni why 403 <request-id>), and a row is <resource>/<id>.",
                code="E908",
            )
        if not options.get("user"):
            raise WhyError(
                f"`karni why {target}` needs --as <user>: an email, username or primary key, or "
                "--as anonymous for a request that is not signed in.",
                code="E908",
            )
        user = resolve_user(str(options["user"]))
        query = _query(options.get("param") or [])
        if options.get("empty"):
            return explain_list(target.split("/", 1)[0], user, query=query)
        if "/" in target:
            name, _, pk = target.partition("/")
            if not pk.strip("/"):
                raise WhyError(
                    f"{target!r} names no row: write <resource>/<id>, e.g. events/42.",
                    code="E908",
                )
            return explain_row(
                name,
                pk.strip("/"),
                user,
                options.get("action"),
                method=options.get("method"),
                query=query,
            )
        try:
            resource = resolve_resource(target)
        except WhyError:
            if "." not in target:
                raise
            name, _, field = target.rpartition(".")
            return explain_field(name, field, user)
        action = options.get("action")
        if action:
            return explain_row(
                resource, None, user, action, method=options.get("method"), query=query
            )
        return explain_list(resource, user, query=query)
