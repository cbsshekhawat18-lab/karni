"""The demo data reset: back to ``karni seed --reset`` every N hours.

When it runs:

* At boot (``manage.py karni_demo_boot``, before the web server starts): a
  database without the seed's demo user is seeded, and data older than
  ``KARNI_DEMO_RESET_HOURS`` is reset.
* While serving: :class:`karni.demo.middleware.DemoResetMiddleware` asks
  :func:`reset_if_due` at most every ``KARNI_DEMO_RESET_CHECK_SECONDS`` per
  worker process. No outside scheduler is needed.

What a reset does, in one database transaction: it deletes every row of the
apps that are not kept (``KARNI_DEMO_KEEP_APPS``: the accounts, the roles,
content types, sessions, the token blacklist and the beat schedule stay), the
seeded tables first and their change history after them, then runs ``karni
seed`` with ``reset`` and the fixed seed (``KARNI_DEMO_SEED``), then puts every
demo account back (:func:`karni.demo.accounts.ensure`). So a reset leaves what
the first boot left. Accounts are kept because no visitor can change one
(:mod:`karni.demo.guard`), and keeping them keeps every worker's cached ids right.

Several workers: the last reset's time is a small file
(:func:`karni.demo.conf.stamp_path`). A worker that finds it too old takes an
exclusive, non-blocking lock on ``<stamp>.lock`` and checks the time again
under it. A worker that does not get the lock skips the reset, so exactly one
worker resets. The data changes in one transaction, so a worker reading
meanwhile sees the old rows or the new ones, never a mix.

SQLite: the database file is never replaced or deleted. For several workers
use WAL mode, ``BEGIN IMMEDIATE`` and a busy timeout in ``DATABASES`` so a
write that arrives during a reset waits for it instead of failing::

    DATABASES["default"]["OPTIONS"] = {
        "init_command": "PRAGMA journal_mode=WAL",
        "transaction_mode": "IMMEDIATE",
        "timeout": 20,
    }

Override / escape hatch: ``KARNI_DEMO_SEEDER`` replaces the reseed,
``KARNI_DEMO_KEEP_APPS`` changes what is kept, and every function takes ``now``.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from django.apps import apps
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, models, router, transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from karni.demo import accounts, conf
from karni.exceptions import KarniImportError

logger = logging.getLogger("karni.demo")

#: Apps whose rows a reset keeps (the user model's app is always kept too).
KEEP_APPS: tuple[str, ...] = (
    "contenttypes",
    "auth",
    "sessions",
    "token_blacklist",
    "django_celery_beat",
)

__all__ = [
    "KEEP_APPS",
    "boot",
    "due",
    "every",
    "exclusive",
    "last_reset",
    "next_reset",
    "reset",
    "reset_if_due",
    "stamp_path",
    "wiped_models",
]


def every() -> dt.timedelta:
    """How old the data may get before a reset (``KARNI_DEMO_RESET_HOURS``)."""
    return dt.timedelta(hours=conf.reset_hours())


def stamp_path() -> Path:
    """The file holding the last reset's time."""
    return conf.stamp_path()


def last_reset() -> dt.datetime | None:
    """When the data was last reset, or ``None`` (no stamp, or one that cannot be read)."""
    try:
        found = json.loads(stamp_path().read_text())
        return dt.datetime.fromisoformat(found["reset_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def next_reset() -> dt.datetime | None:
    """When the next reset is due, or ``None`` when no reset was recorded."""
    last = last_reset()
    return None if last is None else last + every()


def due(now: dt.datetime | None = None) -> bool:
    """Whether the data is older than ``KARNI_DEMO_RESET_HOURS`` (or its age is unknown)."""
    last = last_reset()
    return last is None or (now or timezone.now()) - last >= every()


def _write_stamp(when: dt.datetime) -> None:
    path = stamp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{os.getpid()}")
    partial.write_text(json.dumps({"reset_at": when.isoformat(), "seed": conf.seed_value()}))
    partial.replace(path)  # a reader sees the old stamp or the new one, never half of one


@contextmanager
def exclusive() -> Iterator[bool]:
    """Hold ``<stamp>.lock`` while the block runs: ``True`` when this process got it.

    Non-blocking: when another worker holds it, this yields ``False`` at once.
    """
    path = stamp_path().with_name(f"{stamp_path().name}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            mine = True
        except BlockingIOError:
            mine = False
        try:
            yield mine
        finally:
            if mine:
                fcntl.flock(handle, fcntl.LOCK_UN)


def wiped_models() -> list[type[models.Model]]:
    """The models whose rows a reset deletes, in order.

    First the seeded ones, leaves first as ``karni seed --reset`` deletes them,
    then every other model outside the kept apps, so the history rows those
    deletes write go too. Only models of the default database: the reset is one
    transaction on it, and a second database's tables are left alone.
    """
    from karni.seeding import seed_plan

    keep = conf.keep_apps(KEEP_APPS)
    plan = seed_plan()

    def mine(model: type[models.Model]) -> bool:
        """Kept apps stay, and so does any table the default database does not hold."""
        label = model._meta.app_label
        return label not in keep and router.db_for_write(model) == DEFAULT_DB_ALIAS

    seeded = [model for model in reversed(plan) if mine(model)]
    rest = [
        model
        for model in apps.get_models()
        if model._meta.managed and not model._meta.proxy and mine(model) and model not in plan
    ]
    return [*seeded, *rest]


def reseed() -> str:
    """Seed the emptied tables: ``KARNI_DEMO_SEEDER(seed)``, else ``karni seed`` with ``reset``."""
    dotted = getattr(settings, "KARNI_DEMO_SEEDER", None)
    if dotted:
        try:
            seeder = import_string(str(dotted))
        except ImportError as exc:
            raise KarniImportError(
                f"KARNI_DEMO_SEEDER = {dotted!r} cannot be imported ({exc}).", code="E952"
            ) from exc
        report: Any = seeder(conf.seed_value())
        return str(report.render()) if hasattr(report, "render") else str(report or "")
    from karni.seeding import seed

    return seed(seed=conf.seed_value(), reset=True).render()


def reset(now: dt.datetime | None = None) -> str:
    """Reset the data now (no lock: call :func:`reset_if_due`, or hold :func:`exclusive`).

    Returns the seed's report. The stamp is written once the transaction
    commits, so a reset that fails is tried again.
    """
    with transaction.atomic():
        for model in wiped_models():
            model._base_manager.all().delete()
        report = reseed()
        accounts.ensure()
    when = now or timezone.now()
    _write_stamp(when)
    logger.info(
        "demo data reset (seed %s), the next one is due at %s", conf.seed_value(), when + every()
    )
    return report


def reset_if_due(now: dt.datetime | None = None) -> bool:
    """Reset when the data is too old and no other worker is resetting it: whether it did."""
    if not due(now):
        return False
    with exclusive() as mine:
        if not mine or not due(now):  # another worker holds the lock, or just reset
            return False
        reset(now)
        return True


def boot(now: dt.datetime | None = None) -> str:
    """At boot: seed an empty database, reset old data, else put the demo accounts back."""
    with exclusive() as mine:
        if not mine:
            return "Another process is resetting the demo data: left to it."
        if not accounts.seeded():
            return f"Empty database, seeded:\n{reset(now)}"
        if due(now):
            return f"Demo data older than {conf.reset_hours()} hours, reset:\n{reset(now)}"
        accounts.ensure()
        return f"Demo data kept: the next reset is due at {next_reset()}."
