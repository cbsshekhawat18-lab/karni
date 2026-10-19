"""``manage.py karni_check`` — Django system checks plus Karni check hooks.

Extension point: entry points in the ``karni.checks`` group. Each entry point
loads to a zero-arg callable returning ``list[str]`` failure messages (empty
means pass). An exception from loading or calling a hook is recorded as one
failure and never aborts the remaining hooks. Exit code is 1 when Django's
checks fail or any hook reports failures.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, SystemCheckError

from karni.exceptions import KarniCommandError


class Command(BaseCommand):
    help = "Run Django system checks and Karni architecture check hooks."
    # We invoke `check` ourselves so hooks always run, even when checks fail.
    requires_system_checks: list[Any] = []

    def handle(self, *args: Any, **options: Any) -> None:
        failures: list[str] = []
        try:
            call_command("check")
        except SystemCheckError:
            failures.append("django: system checks failed (see output above)")

        for ep in sorted(entry_points(group="karni.checks"), key=lambda e: e.name):
            try:
                messages = ep.load()()
                failures.extend(f"{ep.name}: {message}" for message in messages)
            except Exception as exc:  # noqa: BLE001 - a broken hook is a failure, not a crash
                failures.append(f"{ep.name}: {exc}")

        # Row-scope exemptions are not failures, but they are printed on every
        # run so they never accumulate quietly (ADR 0002, P2).
        from karni.scoping import render_exemptions, scope_exemptions

        exemptions = scope_exemptions()
        if exemptions:
            self.stdout.write(render_exemptions(exemptions))

        if failures:
            for failure in failures:
                self.stderr.write(failure)
            raise KarniCommandError(
                f"karni check found {len(failures)} problem(s), listed above. Fix each one "
                "(each names its K or E code; `karni explain <code>` explains it).",
                code="E702",
            )
        self.stdout.write("karni check: ok")
