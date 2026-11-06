"""``manage.py karni_check`` — Django system checks plus Karni check hooks.

Extension point: entry points in the ``karni.checks`` group. Each entry point
loads to a zero-arg callable returning ``list[str]`` failure messages (empty
means pass). An exception from loading or calling a hook is recorded as one
failure and never aborts the remaining hooks. Exit code is 1 when Django's
checks fail or any hook reports failures.

``--deploy`` adds the deploy checks (Django's and Karni's ``karni.W510`` to
``karni.W520``, :mod:`karni.security.checks`) and fails on warnings too, so a
deployment with ``DEBUG`` on or the scaffold's ``SECRET_KEY`` does not pass.
A Django deploy warning that a Karni check covers is hidden then, so each
problem is printed once, with the Karni code and fix.

``--seo`` also runs the hooks of the ``karni.checks.seo`` entry-point group,
the same zero-argument callables returning failure messages. They may be
slow (karni-site's renders every page of the site), so they run only when
asked for.

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
``--deploy``, which the production image runs before ``migrate``. In the same
place it prints ``karni.W590`` for a field ``class Karni: search`` searches
whose table has no trigram index on PostgreSQL (experimental).

Suggestions (experimental, :mod:`karni.suggestions`) print last, after the errors
and warnings: what Karni could do that the project does by hand, each with its
file, line and fix. They never fail the run. ``--no-suggestions`` leaves them out,
``--suggestions-file PATH`` (or the ``KARNI_SUGGESTIONS_FILE`` variable) writes them there
as JSON instead of printing them (``karni check`` merges them with its own), and
``KARNI_SUGGESTIONS = False`` turns them off for the project.

While ``KARNI_NAVIGATION`` is set (experimental), it compares the menu with
the frontend's pages and the project's permissions
(:func:`karni.navigation.checks.check_navigation`): ``karni.E533`` and
``E534`` fail, ``W630`` and ``W631`` are printed. Not with ``--deploy``
either.
"""

from __future__ import annotations

import os
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
            "--seo",
            action="store_true",
            help="Also run the SEO checks of installed modules (karni.checks.seo hooks), such "
            "as karni-site's: every page rendered and its titles, images, links and sitemap "
            "checked.",
        )

        parser.add_argument(
            "--no-cache",
            action="store_true",
            help="Check every file again: do not read or write the check cache. Experimental.",
        )
        parser.add_argument(
            "--no-suggestions",
            action="store_true",
            help="Do not print suggestions (karni.suggestions). Experimental.",
        )
        parser.add_argument(
            "--suggestions-file",
            metavar="PATH",
            help="Write the suggestions to PATH as JSON instead of printing them. Experimental.",
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
            self._run(
                bool(options.get("deploy")),
                cache,
                seo=bool(options.get("seo")),
                suggestions=not options.get("no_suggestions"),
                suggestions_file=options.get("suggestions_file")
                or os.environ.get("KARNI_SUGGESTIONS_FILE"),
            )

    def _suggest(self, to_file: str | None) -> None:
        """Experimental. Print the suggestions, or write them to ``to_file``. Never fails."""
        import json
        from pathlib import Path

        from karni import suggestions

        found = [item.as_dict() for item in suggestions.detect()]
        if to_file:
            data = {
                "version": suggestions.VERSION,
                "enabled": suggestions.enabled(),
                "suggestions": found,
            }
            try:
                Path(to_file).parent.mkdir(parents=True, exist_ok=True)
                Path(to_file).write_text(json.dumps(data, indent=2), encoding="utf-8")
            except OSError as exc:
                self.stderr.write(f"warning: could not write the suggestions to {to_file}: {exc}")
        elif found:
            self.stdout.write(suggestions.render(found))

    def _run(
        self,
        deploy: bool,
        cache: Any,
        *,
        seo: bool = False,
        suggestions: bool = True,
        suggestions_file: str | None = None,
    ) -> None:
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

            # The menu (experimental): each route has a page, each requirement a
            # permission. The database menu is read where the database answers.
            from karni.navigation.checks import navigation_check_failures

            errors, warnings = navigation_check_failures()
            for warning in warnings:
                self.stdout.write(f"navigation: {warning}")
            failures.extend(f"navigation: {error}" for error in errors)

            # Experimental: a field Karni.search searches whose table lacks its
            # trigram index on PostgreSQL (karni.W590). Printed, not failed.
            from karni.global_search import search_index_failures

            for warning in search_index_failures():
                self.stdout.write(f"search indexes: {warning}")

        groups = ["karni.checks", *(["karni.checks.seo"] if seo else [])]
        for group in groups:
            hooks = sorted(entry_points(group=group), key=lambda e: e.name)
            if group == "karni.checks.seo" and not hooks:
                self.stdout.write(
                    "karni check --seo: no public site to check. No installed module has SEO "
                    "checks. Add the site module with `karni add site` to have pages to check."
                )
            for ep in hooks:
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
            if suggestions or suggestions_file:
                self._suggest(suggestions_file)
            raise KarniCommandError(
                f"karni check found {len(failures)} problem(s), listed above. Fix each one. "
                "Each names its code (K, E or W), and `karni explain <code>` explains it.",
                code="E702",
            )
        # A stage of `karni check`, which prints the overall verdict once every
        # stage (this one, ESLint, duplication) has run.
        included = [name for name, on in (("deploy", deploy), ("SEO", seo)) if on]
        self.stdout.write(
            "backend checks: ok"
            + (f" ({' and '.join(included)} checks included)" if included else "")
        )
        if suggestions or suggestions_file:
            self._suggest(suggestions_file)
