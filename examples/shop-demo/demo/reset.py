"""The demo data reset: back to ``karni seed --reset --seed DEMO_SEED`` every ``DEMO_RESET_HOURS``.

When it runs:

* at boot (``manage.py demo_boot``, before the web server starts): a database
  without the demo account is seeded, and data older than ``DEMO_RESET_HOURS``
  is reset;
* while serving: :class:`demo.middleware.DemoResetMiddleware` asks
  :func:`reset_if_due` at most once a minute per worker process. No outside
  scheduler is needed.

What a reset does, in one database transaction: it deletes every row of the
apps that are not kept (``DEMO_RESET_KEEP_APPS``: the accounts, the roles,
content types, sessions, the token blacklist and the beat schedule stay), the
shop's tables first and their change history after them, then runs ``karni
seed`` with ``reset`` and the fixed seed, then puts the demo account back
(:func:`demo.account.ensure`). So a reset leaves what the first boot left.
Accounts are kept because no visitor can change one (:mod:`demo.guard`), and
keeping them keeps every worker's cached ids right.

Several workers: the last reset's time is a small file (``DEMO_RESET_STAMP``).
A worker that finds it too old takes an exclusive, non-blocking lock on
``<stamp>.lock`` and checks the time again under it. A worker that does not
get the lock skips the reset, so exactly one worker resets. The data changes
in one transaction, so a worker reading meanwhile sees the old rows or the new
ones, never a mix. SQLite runs in WAL mode with ``BEGIN IMMEDIATE`` and a busy
timeout (``config/settings.py``), so a write that arrives during a reset waits
for it instead of failing. The database file is never replaced or deleted.
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

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils import timezone

from demo import account

logger = logging.getLogger("demo")

#: Apps whose rows a reset keeps (the user model's app is always kept too).
KEEP_APPS: tuple[str, ...] = (
    "contenttypes",
    "auth",
    "sessions",
    "token_blacklist",
    "django_celery_beat",
)


def seed_value() -> int:
    """The fixed seed every reset uses (``DEMO_SEED``): the same rows each time."""
    return int(getattr(settings, "DEMO_SEED", 42))


def every() -> dt.timedelta:
    """How old the data may get before a reset (``DEMO_RESET_HOURS``)."""
    return dt.timedelta(hours=account.reset_hours())


def stamp_path() -> Path:
    """The file holding the last reset's time (``DEMO_RESET_STAMP``)."""
    return Path(settings.DEMO_RESET_STAMP)


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
    """Whether the data is older than ``DEMO_RESET_HOURS`` (or its age is unknown)."""
    last = last_reset()
    return last is None or (now or timezone.now()) - last >= every()


def _write_stamp(when: dt.datetime) -> None:
    path = stamp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{os.getpid()}")
    partial.write_text(json.dumps({"reset_at": when.isoformat(), "seed": seed_value()}))
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
    deletes write go too.
    """
    from karni.seeding import seed_plan

    user_model = get_user_model()
    keep = {*getattr(settings, "DEMO_RESET_KEEP_APPS", KEEP_APPS), user_model._meta.app_label}
    plan = seed_plan()
    seeded = [model for model in reversed(plan) if model._meta.app_label not in keep]
    rest = [
        model
        for model in apps.get_models()
        if model._meta.managed
        and not model._meta.proxy
        and model._meta.app_label not in keep
        and model not in plan
    ]
    return [*seeded, *rest]


def reset(now: dt.datetime | None = None) -> str:
    """Reset the data now (no lock: call :func:`reset_if_due`, or hold :func:`exclusive`).

    Returns ``karni seed``'s report. The stamp is written once the transaction
    commits, so a reset that fails is tried again.
    """
    from karni.seeding import seed

    with transaction.atomic():
        for model in wiped_models():
            model._base_manager.all().delete()
        report = seed(seed=seed_value(), reset=True)
        account.ensure()
    when = now or timezone.now()
    _write_stamp(when)
    logger.info(
        "demo data reset (seed %s), the next one is due at %s", seed_value(), when + every()
    )
    return report.render()


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
    """At boot: seed an empty database, reset old data, else put the demo account back."""
    with exclusive() as mine:
        if not mine:
            return "Another process is resetting the demo data: left to it."
        if account.find() is None:
            return f"Empty database, seeded:\n{reset(now)}"
        if due(now):
            return f"Demo data older than {account.reset_hours()} hours, reset:\n{reset(now)}"
        account.ensure()
        return f"Demo data kept: the next reset is due at {next_reset()}."
