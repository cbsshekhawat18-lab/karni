"""``manage.py karni_check`` — Django system checks plus Karni check hooks.

Extension point: entry points in the ``karni.checks`` group. Each entry point
loads to a zero-arg callable returning ``list[str]`` failure messages (empty
means pass). An exception from loading or calling a hook is recorded as one
failure and never aborts the remaining hooks. Exit code is 1 when Django's
checks fail or any hook reports failures.

``--deploy`` adds the deploy checks (Django's and Karni's ``karni.W510`` to
``karni.W519``, :mod:`karni.security.checks`) and fails on warnings too, so a
deployment with ``DEBUG`` on or the scaffold's ``SECRET_KEY`` does not pass.
A Django deploy warning that a Karni check covers is hidden then, so each
problem is printed once, with the Karni code and fix.

The checks that read one file at a time keep their results in a cache
(:mod:`karni.testing.checkcache`, experimental): an unchanged file is not
read again. ``--no-cache`` (or ``KARNI_CHECK_CACHE = False``) turns it off.
``--changed FILE ...`` narrows a run to those files (paths relative to the
project root): the file checks read only them and every check reports only
their findings, while the checks that read the whole project (Django's
system checks, the external tables, every other hook) run in full.
``karni check --changed`` passes the files git reports as changed.

It also compares every external model (``class Karni: external = True``,
experimental) with its table or view where the database answers
(:func:`karni.db.checks.check_external_tables`): ``karni.E272`` to ``E274``
fail, ``karni.W540`` (a database that does not answer) is printed. Not with
``--deploy``, which the production image runs before ``migrate``.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser, SystemCheckError
from django.test.utils import override_settings

from karni.exceptions import KarniCommandError


def superseded_django_checks() -> list[str]:
    """Django's deploy warnings to hide: those a Karni check covers, while it is not silenced."""
    from karni.security.checks import SUPERSEDES

    silenced = set(getattr(settings, "SILENCED_SYSTEM_CHECKS", None) or [])
    return [
        django_id
        for karni_id, django_ids in SUPERSEDES.items()
        if karni_id not in silenced
        for django_id in django_ids
    ]


class Command(BaseCommand):
    help = "Run Django system checks and Karni architecture check hooks."
    # We invoke `check` ourselves so hooks always run, even when checks fail.
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--deploy",
            action="store_true",
            help="Also run the deploy checks, and fail on warnings too. Run it with the "
            "production environment (DJANGO_ENV=prod, DEBUG=False, the real SECRET_KEY).",
        )

        parser.add_argument(
            "--no-cache",
            action="store_true",
            help="Check every file again: do not read or write the check cache. Experimental.",
        )
        parser.add_argument(
            "--changed",
            nargs="*",
            default=None,
            metavar="FILE",
            help="Only these files (relative to the project root): the file checks read only "
            "them and every check reports only their findings. Experimental.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from karni.testing import checkcache
        from karni.testing._source import project_root

        cache = checkcache.from_settings(
            project_root(), no_cache=bool(options.get("no_cache")), changed=options.get("changed")
        )
        with checkcache.using(cache):
            self._run(bool(options.get("deploy")), cache)

    def _run(self, deploy: bool, cache: Any) -> None:
        failures: list[str] = []
        # Django's check writes warnings to these streams and raises the
        # failing findings without printing them, so they are printed below.
        streams = {"stdout": self.stdout._out, "stderr": self.stderr._out}
        try:
            if deploy:
                silenced = [
                    *(getattr(settings, "SILENCED_SYSTEM_CHECKS", None) or []),
                    *superseded_django_checks(),
                ]
                with override_settings(SILENCED_SYSTEM_CHECKS=silenced):
                    call_command("check", deploy=True, fail_level="WARNING", **streams)
            else:
                call_command("check", **streams)
        except SystemCheckError as exc:
            self.stderr.write(str(exc))
            failures.append(
                "django: deploy checks failed (see output above)"
                if deploy
                else "django: system checks failed (see output above)"
            )

        if not deploy:
            # Not with --deploy: the production image runs it before migrate, and a
            # view the release's own migration creates does not exist yet.
            from karni.db.checks import external_check_failures

            errors, warnings = external_check_failures()
            for warning in warnings:
                self.stdout.write(f"external tables: {warning}")
            failures.extend(f"external tables: {error}" for error in errors)

        for ep in sorted(entry_points(group="karni.checks"), key=lambda e: e.name):
            try:
                messages = ep.load()()
                failures.extend(f"{ep.name}: {message}" for message in messages)
            except Exception as exc:  # noqa: BLE001 - a broken hook is a failure, not a crash
                failures.append(f"{ep.name}: {exc}")
        if cache.enabled and not cache.save():
            self.stderr.write(f"warning: could not write the check cache {cache.path}")
        if cache.enabled or cache.changed is not None:
            self.stdout.write(cache.summary())

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
                f"karni check found {len(failures)} problem(s), listed above. Fix each one. "
                "Each names its code (K, E or W), and `karni explain <code>` explains it.",
                code="E702",
            )
        # A stage of `karni check`, which prints the overall verdict once every
        # stage (this one, ESLint, duplication) has run.
        self.stdout.write("backend checks: ok" + (" (deploy checks included)" if deploy else ""))
