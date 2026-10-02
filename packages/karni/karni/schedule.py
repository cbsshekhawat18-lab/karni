"""Declarative Celery beat schedules: ``<app>/schedules.py``.

Declare periodic work next to the app that owns it — no ``CELERY_BEAT_SCHEDULE``
dict to hand-maintain::

    # shop/schedules.py
    from karni.schedule import cron, every

    from shop import tasks

    every("15m", tasks.sync_inventory)                        # name = task name
    every(hours=1, task="shop.tasks.expire_carts", name="expire-carts")
    cron("0 3 * * *", "shop.tasks.nightly_report", name="nightly-report", kwargs={"days": 1})

Each call registers a :class:`Schedule` in :data:`registry`. The modules are
imported by :func:`discover` (``autodiscover_modules("schedules")``), which
the Celery factory runs when a worker/beat process imports its task modules
(:func:`karni.celery.apply_discovered_schedules`) and which
``manage.py karni_schedules`` runs to list them. The merged entries land in
``app.conf.beat_schedule``; django-celery-beat's ``DatabaseScheduler`` syncs
each one into a ``PeriodicTask`` row (by name) every time beat starts.

Precedence: an entry with the same name in the ``CELERY_BEAT_SCHEDULE``
setting wins over a declared one (:func:`merge_beat_schedule`) — the way to
retime or disable a declared schedule in one environment without editing
code.

Every validation error raises :class:`ScheduleError` (an
``ImproperlyConfigured``) whose message names the fix.

Override / escape hatches: ``CELERY_BEAT_SCHEDULE`` (wins on conflict); set
``KARNI_SCHEDULES_AUTODISCOVER = False`` and import your schedule modules
yourself; pass ``registry=`` to declare into your own
:class:`ScheduleRegistry`; build entries without this module at all — the
beat schedule is a plain Celery setting.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from celery.schedules import crontab
from celery.schedules import schedule as interval_schedule
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import autodiscover_modules

__all__ = [
    "Schedule",
    "ScheduleError",
    "ScheduleRegistry",
    "cron",
    "describe_schedules",
    "discover",
    "every",
    "merge_beat_schedule",
    "registry",
    "run_schedule",
]

#: The per-app module :func:`discover` imports.
AUTODISCOVER_MODULE = "schedules"

#: ``source`` reported for entries that come from the ``CELERY_BEAT_SCHEDULE`` setting.
SETTINGS_SOURCE = "settings.CELERY_BEAT_SCHEDULE"

_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_INTERVAL_RE = re.compile(r"(\d+)\s*([dhms])")
_INTERVAL_FULL_RE = re.compile(r"^\s*(?:\d+\s*[dhms]\s*)+$")
_DOTTED_RE = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")

#: Cron fields in crontab-string order → (celery.schedules.crontab kwarg, label).
_CRON_FIELDS = (
    ("minute", "minute"),
    ("hour", "hour"),
    ("day_of_month", "day-of-month"),
    ("month_of_year", "month"),
    ("day_of_week", "day-of-week"),
)


class ScheduleError(ImproperlyConfigured):
    """A schedule declaration is invalid; the message says how to fix it."""


@dataclass(frozen=True)
class Schedule:
    """One declared periodic task (built by :func:`every` / :func:`cron`).

    :ivar name: unique schedule name — the beat entry key and the
        django-celery-beat ``PeriodicTask.name``.
    :ivar task: the registered Celery task name.
    :ivar schedule: the Celery schedule object (interval or crontab).
    :ivar timing: human-readable timing, e.g. ``"every 15m"`` or ``"cron 0 3 * * *"``.
    :ivar source: dotted name of the module that declared it.
    """

    name: str
    task: str
    schedule: Any
    timing: str
    args: tuple[Any, ...] = ()
    kwargs: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""

    def as_beat_entry(self) -> dict[str, Any]:
        """The ``beat_schedule`` value for this schedule."""
        entry: dict[str, Any] = {
            "task": self.task,
            "schedule": self.schedule,
            "args": tuple(self.args),
            "kwargs": dict(self.kwargs),
        }
        if self.options:
            entry["options"] = dict(self.options)
        return entry


class ScheduleRegistry:
    """Ordered, name-unique collection of :class:`Schedule` declarations."""

    def __init__(self) -> None:
        self._entries: dict[str, Schedule] = {}

    def add(self, entry: Schedule) -> Schedule:
        """Register ``entry``; re-registering an identical entry is a no-op.

        :raises ScheduleError: when another declaration already uses the name.
        """
        existing = self._entries.get(entry.name)
        if existing is not None and existing != entry:
            raise ScheduleError(
                f"Schedule name {entry.name!r} is declared twice ({existing.source} and "
                f"{entry.source}). Names must be unique — they become django-celery-beat "
                "PeriodicTask names. Pass a distinct name=... to one of them."
            )
        self._entries[entry.name] = entry
        return entry

    def entries(self) -> list[Schedule]:
        """Every registered schedule, in declaration order."""
        return list(self._entries.values())

    def clear(self) -> None:
        """Forget every declaration (tests; modules already imported are not re-run)."""
        self._entries.clear()

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)


#: The registry :func:`every` / :func:`cron` declare into by default.
registry = ScheduleRegistry()
_default_registry = registry  # reachable inside functions whose parameter is named ``registry``


# --- declarations -------------------------------------------------------------


def _caller_module(depth: int) -> str:
    frame = sys._getframe(depth)
    return str(frame.f_globals.get("__name__", "?"))


def _task_name(task: Any, call: str) -> str:
    if isinstance(task, str):
        if not _DOTTED_RE.match(task):
            raise ScheduleError(
                f"{call}: task {task!r} is not a dotted task name. Pass the task object "
                "or its full dotted name, e.g. 'shop.tasks.sync_inventory'."
            )
        return task
    name = getattr(task, "name", None)
    if task is None or not isinstance(name, str) or not name:
        raise ScheduleError(
            f"{call}: needs the task to run, got {task!r}. Pass a Celery task (decorated "
            "with @shared_task) or its dotted name, e.g. 'shop.tasks.sync_inventory'."
        )
    return name


def _json_safe(value: Any, what: str, call: str) -> None:
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ScheduleError(
            f"{call}: {what} must be JSON-serializable (django-celery-beat stores them as "
            f"JSON): {exc}. Pass ids and plain values, not objects."
        ) from None


def _declare(
    *,
    call: str,
    task: Any,
    schedule: Any,
    timing: str,
    name: str | None,
    args: Sequence[Any] | None,
    kwargs: Mapping[str, Any] | None,
    options: Mapping[str, Any] | None,
    registry_: ScheduleRegistry | None,
) -> Schedule:
    task_name = _task_name(task, call)
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise ScheduleError(f"{call}: name must be a non-empty string, got {name!r}.")
    if args is not None and (isinstance(args, str | bytes) or not isinstance(args, Sequence)):
        raise ScheduleError(f"{call}: args must be a list or tuple, got {args!r}.")
    if kwargs is not None and not isinstance(kwargs, Mapping):
        raise ScheduleError(f"{call}: kwargs must be a dict, got {kwargs!r}.")
    if options is not None and not isinstance(options, Mapping):
        raise ScheduleError(
            f"{call}: options must be a dict of apply_async options (e.g. "
            f"{{'queue': 'low'}}), got {options!r}."
        )
    args_tuple = tuple(args or ())
    kwargs_dict = dict(kwargs or {})
    _json_safe(list(args_tuple), "args", call)
    _json_safe(kwargs_dict, "kwargs", call)
    entry = Schedule(
        name=name or task_name,
        task=task_name,
        schedule=schedule,
        timing=timing,
        args=args_tuple,
        kwargs=kwargs_dict,
        options=dict(options or {}),
        source=_caller_module(3),
    )
    return (registry_ if registry_ is not None else _default_registry).add(entry)


def format_seconds(total: int) -> str:
    """``900`` → ``"15m"``, ``5400`` → ``"90m"``, ``86400`` → ``"1d"``, ``45`` → ``"45s"``."""
    for unit, size in _UNIT_SECONDS.items():
        if total % size == 0:
            return f"{total // size}{unit}"
    return f"{total}s"  # pragma: no cover - the "s" unit always divides


def _interval_seconds(
    interval: str | int | float | timedelta | None,
    units: Mapping[str, float],
    call: str,
) -> int:
    given_units = {key: value for key, value in units.items() if value}
    if interval is not None and given_units:
        raise ScheduleError(
            f"{call}: pass either an interval (every('15m')) or "
            "seconds=/minutes=/hours=/days= keywords, not both."
        )
    if isinstance(interval, str):
        if not _INTERVAL_FULL_RE.match(interval):
            raise ScheduleError(
                f"{call}: can't read the interval {interval!r}. Use a number followed by "
                "s, m, h or d — every('30s'), every('15m'), every('1h30m'), every('1d') — "
                "or keywords: every(minutes=15)."
            )
        seconds: float = sum(
            int(n) * _UNIT_SECONDS[unit] for n, unit in _INTERVAL_RE.findall(interval)
        )
    elif isinstance(interval, timedelta):
        seconds = interval.total_seconds()
    elif isinstance(interval, bool):
        raise ScheduleError(f"{call}: the interval must be a duration, got {interval!r}.")
    elif isinstance(interval, int | float):
        seconds = float(interval)
    elif interval is None:
        if not given_units:
            raise ScheduleError(
                "every() needs an interval: every('15m', task) or every(minutes=15, task=task)."
            )
        seconds = timedelta(
            days=units.get("days", 0),
            hours=units.get("hours", 0),
            minutes=units.get("minutes", 0),
            seconds=units.get("seconds", 0),
        ).total_seconds()
    else:
        raise ScheduleError(
            f"{call}: the interval must be a string like '15m', a number of seconds or a "
            f"timedelta, got {interval!r}."
        )
    if seconds <= 0:
        raise ScheduleError(f"{call}: the interval must be positive, got {seconds:g}s.")
    if seconds != int(seconds):
        raise ScheduleError(
            f"{call}: intervals are whole seconds (django-celery-beat stores integer "
            f"seconds), got {seconds:g}s. Round it, e.g. every(seconds={round(seconds) or 1})."
        )
    return int(seconds)


def every(
    interval: str | int | float | timedelta | None = None,
    task: Any = None,
    *,
    name: str | None = None,
    args: Sequence[Any] | None = None,
    kwargs: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    seconds: float = 0,
    minutes: float = 0,
    hours: float = 0,
    days: float = 0,
    registry: ScheduleRegistry | None = None,
) -> Schedule:
    """Run ``task`` on a fixed interval.

    ``every("15m", tasks.sync)``, ``every("1h30m", "shop.tasks.sync")``,
    ``every(900, ...)`` (seconds), ``every(timedelta(hours=1), ...)`` or
    ``every(minutes=15, task=...)``.

    :param task: a Celery task object or its dotted name.
    :param name: unique schedule name; defaults to the task name.
    :param args: positional task arguments (JSON-serializable).
    :param kwargs: keyword task arguments (JSON-serializable).
    :param options: ``apply_async`` options stored on the entry (``queue``, ``priority`` …).
    :param registry: declare into this registry instead of :data:`registry`.
    :raises ScheduleError: on any invalid argument, naming the fix.
    """
    units = {"seconds": seconds, "minutes": minutes, "hours": hours, "days": days}
    if interval is not None:
        call = f"every({interval!r})"
    else:
        given = ", ".join(f"{key}={value!r}" for key, value in units.items() if value)
        call = f"every({given})"
    total = _interval_seconds(interval, units, call)
    return _declare(
        call=call,
        task=task,
        schedule=interval_schedule(run_every=timedelta(seconds=total)),
        timing=f"every {format_seconds(total)}",
        name=name,
        args=args,
        kwargs=kwargs,
        options=options,
        registry_=registry,
    )


def cron(
    expression: str,
    task: Any = None,
    *,
    name: str | None = None,
    args: Sequence[Any] | None = None,
    kwargs: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    registry: ScheduleRegistry | None = None,
) -> Schedule:
    """Run ``task`` on a five-field crontab: ``"minute hour day-of-month month day-of-week"``.

    ``cron("0 3 * * *", ...)`` is 03:00 daily, ``cron("*/15 * * * mon-fri", ...)``
    every quarter hour on weekdays. Times are in the Celery app's timezone
    (``CELERY_TIMEZONE``, else Django's ``TIME_ZONE``). Other parameters as
    :func:`every`.

    :raises ScheduleError: on a malformed expression, naming the bad field.
    """
    call = f"cron({expression!r})"
    if not isinstance(expression, str):
        raise ScheduleError(f"{call}: the expression must be a string like '0 3 * * *'.")
    parts = expression.split()
    if len(parts) != len(_CRON_FIELDS):
        raise ScheduleError(
            f"{call}: expected 5 fields 'minute hour day-of-month month day-of-week', got "
            f"{len(parts)}. Example: cron('0 3 * * *') runs at 03:00 every day."
        )
    for value, (kwarg, label) in zip(parts, _CRON_FIELDS, strict=True):
        try:
            crontab(**{kwarg: value})
        except (ValueError, TypeError) as exc:
            raise ScheduleError(
                f"{call}: invalid {label} field {value!r} ({exc}). Fields are "
                "'minute hour day-of-month month day-of-week'; e.g. '*/15', '0-30/10', "
                "'mon-fri'."
            ) from None
    spec = dict(zip((kwarg for kwarg, _ in _CRON_FIELDS), parts, strict=True))
    return _declare(
        call=call,
        task=task,
        schedule=crontab(**spec),
        timing=f"cron {' '.join(parts)}",
        name=name,
        args=args,
        kwargs=kwargs,
        options=options,
        registry_=registry,
    )


# --- discovery and merging ----------------------------------------------------


def discover(registry: ScheduleRegistry | None = None) -> list[Schedule]:
    """Import every installed app's ``schedules`` module and return all declarations.

    Skips the import when the ``KARNI_SCHEDULES_AUTODISCOVER`` setting is
    ``False`` (then only modules you imported yourself contribute). Needs
    Django's app registry to be ready.
    """
    from django.conf import settings

    if getattr(settings, "KARNI_SCHEDULES_AUTODISCOVER", True):
        autodiscover_modules(AUTODISCOVER_MODULE)
    return (registry if registry is not None else _default_registry).entries()


def merge_beat_schedule(
    configured: Mapping[str, Any] | None, discovered: Iterable[Schedule]
) -> dict[str, Any]:
    """Discovered entries plus ``configured`` ones; ``configured`` wins on a name conflict."""
    merged: dict[str, Any] = {entry.name: entry.as_beat_entry() for entry in discovered}
    merged.update(dict(configured or {}))
    return merged


def timing_of(value: Any) -> str:
    """Human-readable timing for any ``beat_schedule`` ``schedule`` value."""
    if isinstance(value, crontab):
        fields = (
            value._orig_minute,
            value._orig_hour,
            value._orig_day_of_month,
            value._orig_month_of_year,
            value._orig_day_of_week,
        )
        return "cron " + " ".join(str(part) for part in fields)
    if isinstance(value, interval_schedule):
        value = value.run_every
    if isinstance(value, timedelta):
        value = value.total_seconds()
    if isinstance(value, int | float) and not isinstance(value, bool):
        if value == int(value) and value > 0:
            return f"every {format_seconds(int(value))}"
        return f"every {value:g}s"
    return str(value)


def _configured_schedule(configured: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if configured is not None:
        return configured
    from django.conf import settings

    return getattr(settings, "CELERY_BEAT_SCHEDULE", None) or {}


def describe_schedules(
    configured: Mapping[str, Any] | None = None,
    discovered: Iterable[Schedule] | None = None,
) -> list[dict[str, Any]]:
    """Every merged schedule as a JSON-ready row, sorted by name.

    Row keys: ``name``, ``task``, ``timing``, ``source`` (declaring module or
    ``"settings.CELERY_BEAT_SCHEDULE"``), ``overrides`` (the declaring module
    a settings entry shadows, else ``None``), ``args``, ``kwargs``.

    :param configured: the settings-side schedule; defaults to the
        ``CELERY_BEAT_SCHEDULE`` setting.
    :param discovered: declarations; defaults to :func:`discover`.
    """
    declared = {entry.name: entry for entry in (discover() if discovered is None else discovered)}
    rows: dict[str, dict[str, Any]] = {
        name: {
            "name": name,
            "task": entry.task,
            "timing": entry.timing,
            "source": entry.source,
            "overrides": None,
            "args": list(entry.args),
            "kwargs": dict(entry.kwargs),
        }
        for name, entry in declared.items()
    }
    for name, raw in _configured_schedule(configured).items():
        raw = raw if isinstance(raw, Mapping) else {}
        shadowed = declared.get(name)
        rows[name] = {
            "name": name,
            "task": str(raw.get("task", "")),
            "timing": timing_of(raw.get("schedule")),
            "source": SETTINGS_SOURCE,
            "overrides": shadowed.source if shadowed is not None else None,
            "args": list(raw.get("args") or ()),
            "kwargs": dict(raw.get("kwargs") or {}),
        }
    return [rows[name] for name in sorted(rows)]


def run_schedule(name: str, configured: Mapping[str, Any] | None = None) -> Any:
    """Run the merged schedule ``name``'s task once, synchronously, in this process.

    Uses the entry's own args/kwargs and Celery's ``Task.apply`` (no broker,
    no worker). Exceptions are captured, not raised: inspect the returned
    ``EagerResult`` (``.failed()``, ``.result``, ``.traceback``).

    :raises ScheduleError: when no merged schedule has that name, or its task
        cannot be found (the message lists the known names / the fix).
    """
    from karni.celery import resolve_task

    rows = {row["name"]: row for row in describe_schedules(configured)}
    row = rows.get(name)
    if row is None:
        known = ", ".join(sorted(rows)) or "none"
        raise ScheduleError(
            f"No schedule named {name!r}. Known schedules: {known}. "
            "List them with `karni schedule list` (manage.py karni_schedules)."
        )
    try:
        task = resolve_task(row["task"])
    except ImproperlyConfigured as exc:
        raise ScheduleError(f"Schedule {name!r}: {exc}") from None
    return task.apply(args=row["args"], kwargs=row["kwargs"], throw=False)
