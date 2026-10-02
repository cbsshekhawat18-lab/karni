"""Tests for :mod:`karni.schedule`, the beat-schedule merge and ``karni_schedules``.

Declarations made *here* go into private :class:`ScheduleRegistry` instances
so the global registry only ever holds ``tests/testapp/schedules.py`` (found
by autodiscovery, which is what the merge and command tests rely on).
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from io import StringIO
from typing import Any
from unittest import mock

import pytest
from celery import Celery
from celery.schedules import crontab
from celery.schedules import schedule as interval_schedule
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

import karni.celery as karni_celery
import karni.schedule as schedule_mod
from karni.celery import apply_discovered_schedules, create_celery_app
from karni.schedule import (
    SETTINGS_SOURCE,
    Schedule,
    ScheduleError,
    ScheduleRegistry,
    cron,
    describe_schedules,
    discover,
    every,
    merge_beat_schedule,
    run_schedule,
)
from tests.testapp import tasks

TESTAPP = "tests.testapp.schedules"
TESTAPP_NAMES = {
    "testapp-tick",
    "testapp-hourly-tick",
    "testapp-nightly-report",
    "testapp-explode",
}
#: Overrides one testapp declaration by name; settings must win.
SETTINGS_OVERRIDE = {
    "testapp-tick": {"task": "tests.testapp.tasks.tick", "schedule": 60.0, "kwargs": {"step": 9}},
    "settings-only": {"task": "tests.testapp.tasks.tick", "schedule": crontab(minute="5")},
}


@pytest.fixture
def private() -> ScheduleRegistry:
    return ScheduleRegistry()


# --- every() -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "seconds", "timing"),
    [
        ({"interval": "15m"}, 900, "every 15m"),
        ({"interval": "1h30m"}, 5400, "every 90m"),
        ({"interval": "1d"}, 86400, "every 1d"),
        ({"interval": "30s"}, 30, "every 30s"),
        ({"interval": 900}, 900, "every 15m"),
        ({"interval": timedelta(hours=2)}, 7200, "every 2h"),
        ({"minutes": 15}, 900, "every 15m"),
        ({"hours": 1, "minutes": 30}, 5400, "every 90m"),
        ({"days": 1}, 86400, "every 1d"),
        ({"seconds": 45}, 45, "every 45s"),
    ],
)
def test_every_parses_intervals(
    private: ScheduleRegistry, kwargs: dict[str, Any], seconds: int, timing: str
) -> None:
    entry = every(task="tests.testapp.tasks.tick", registry=private, **kwargs)
    assert isinstance(entry.schedule, interval_schedule)
    assert entry.schedule.run_every == timedelta(seconds=seconds)
    assert entry.timing == timing


def test_every_defaults_name_to_task_and_records_source(private: ScheduleRegistry) -> None:
    entry = every("15m", tasks.tick, registry=private, args=[3], options={"queue": "low"})
    assert entry.name == entry.task == "tests.testapp.tasks.tick"
    assert entry.source == __name__
    assert entry.as_beat_entry() == {
        "task": "tests.testapp.tasks.tick",
        "schedule": entry.schedule,
        "args": (3,),
        "kwargs": {},
        "options": {"queue": "low"},
    }
    assert private.entries() == [entry]


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda r: every("15x", "a.b", registry=r), "s, m, h or d"),
        (lambda r: every("", "a.b", registry=r), "can't read the interval"),
        (lambda r: every("15m", "a.b", minutes=5, registry=r), "not both"),
        (lambda r: every(task="a.b", registry=r), "needs an interval"),
        (lambda r: every(0, "a.b", registry=r), "must be positive"),
        (lambda r: every(seconds=0.5, task="a.b", registry=r), "whole seconds"),
        (lambda r: every(True, "a.b", registry=r), "must be a duration"),
        (lambda r: every([1], "a.b", registry=r), "string like '15m'"),  # type: ignore[arg-type]
        (lambda r: every("15m", "not a path", registry=r), "dotted task name"),
        (lambda r: every("15m", None, registry=r), "needs the task to run"),
        (lambda r: every("15m", "a.b", name=" ", registry=r), "non-empty string"),
        (lambda r: every("15m", "a.b", args="ab", registry=r), "list or tuple"),
        (lambda r: every("15m", "a.b", kwargs=[1], registry=r), "must be a dict"),  # type: ignore[arg-type]
        (lambda r: every("15m", "a.b", options=1, registry=r), "apply_async options"),  # type: ignore[arg-type]
        (lambda r: every("15m", "a.b", args=[object()], registry=r), "JSON-serializable"),
        (lambda r: every("15m", "a.b", kwargs={"x": {1, 2}}, registry=r), "JSON-serializable"),
    ],
)
def test_every_validation_names_the_fix(private: ScheduleRegistry, call: Any, match: str) -> None:
    with pytest.raises(ScheduleError, match=match):
        call(private)
    assert len(private) == 0


def test_schedule_error_is_improperly_configured() -> None:
    from django.core.exceptions import ImproperlyConfigured

    assert issubclass(ScheduleError, ImproperlyConfigured)


def test_duplicate_names_are_rejected_identical_redeclaration_is_not(
    private: ScheduleRegistry,
) -> None:
    every("15m", "a.b", name="sync", registry=private)
    every("15m", "a.b", name="sync", registry=private)  # e.g. a module reload
    assert len(private) == 1
    with pytest.raises(ScheduleError, match="declared twice.*distinct name="):
        every("1h", "a.b", name="sync", registry=private)
    private.clear()
    assert "sync" not in private


# --- cron() ------------------------------------------------------------------


def test_cron_builds_a_crontab(private: ScheduleRegistry) -> None:
    entry = cron("0 3 * * *", "tests.testapp.tasks.nightly_report", registry=private)
    assert isinstance(entry.schedule, crontab)
    assert entry.schedule == crontab(minute="0", hour="3")
    assert entry.timing == "cron 0 3 * * *"


def test_cron_field_order_is_standard(private: ScheduleRegistry) -> None:
    entry = cron("*/15 9-17 1 6 mon-fri", "a.b", registry=private)
    assert entry.schedule == crontab(
        minute="*/15", hour="9-17", day_of_month="1", month_of_year="6", day_of_week="mon-fri"
    )


@pytest.mark.parametrize(
    ("expression", "match"),
    [
        ("0 3 * *", "expected 5 fields"),
        ("0 3 * * * *", "expected 5 fields"),
        ("99 * * * *", "invalid minute field '99'"),
        ("0 25 * * *", "invalid hour field '25'"),
        ("0 0 32 * *", "invalid day-of-month field '32'"),
        ("0 0 * 13 *", "invalid month field '13'"),
        ("0 0 * * xyz", "invalid day-of-week field 'xyz'"),
    ],
)
def test_cron_validation_names_the_field(
    private: ScheduleRegistry, expression: str, match: str
) -> None:
    with pytest.raises(ScheduleError, match=match):
        cron(expression, "a.b", registry=private)


def test_cron_rejects_a_non_string(private: ScheduleRegistry) -> None:
    with pytest.raises(ScheduleError, match="must be a string"):
        cron(3, "a.b", registry=private)  # type: ignore[arg-type]


# --- discovery and merging ---------------------------------------------------


def test_discover_imports_app_schedules_modules() -> None:
    entries = discover()
    assert TESTAPP in sys.modules
    assert TESTAPP_NAMES <= {entry.name for entry in entries}
    assert {entry.source for entry in entries if entry.name in TESTAPP_NAMES} == {TESTAPP}


def test_discover_respects_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(schedule_mod, "autodiscover_modules", lambda name: seen.append(name))
    discover(ScheduleRegistry())
    assert seen == ["schedules"]
    with override_settings(KARNI_SCHEDULES_AUTODISCOVER=False):
        assert discover(ScheduleRegistry()) == []
    assert seen == ["schedules"]


def test_merge_settings_win_on_name_conflict(private: ScheduleRegistry) -> None:
    declared = [
        every("15m", "a.b", name="shared", registry=private),
        every("1h", "a.b", name="declared-only", registry=private),
    ]
    configured = {"shared": {"task": "x.y", "schedule": 5.0}, "settings-only": {"task": "x.z"}}
    merged = merge_beat_schedule(configured, declared)
    assert merged["shared"] == {"task": "x.y", "schedule": 5.0}
    assert merged["declared-only"] == declared[1].as_beat_entry()
    assert merged["settings-only"] == {"task": "x.z"}


@override_settings(CELERY_BEAT_SCHEDULE=SETTINGS_OVERRIDE)
def test_apply_discovered_schedules_merges_into_the_app() -> None:
    app = create_celery_app()
    merged = apply_discovered_schedules(app)
    assert app.conf.beat_schedule == merged
    assert app.conf.CELERY_BEAT_SCHEDULE == merged  # namespaced spelling cannot shadow it
    assert merged["testapp-tick"] == SETTINGS_OVERRIDE["testapp-tick"]  # settings win
    assert merged["settings-only"] == SETTINGS_OVERRIDE["settings-only"]
    assert merged["testapp-nightly-report"]["task"] == "tests.testapp.tasks.nightly_report"
    assert merged["testapp-nightly-report"]["kwargs"] == {"days": 1}
    assert apply_discovered_schedules(app) == merged  # idempotent


def test_factory_merges_on_import_modules() -> None:
    with mock.patch.object(karni_celery.signals.import_modules, "connect") as connect:
        app = create_celery_app()
    connect.assert_any_call(karni_celery._merge_schedules_on_import_modules, sender=app, weak=False)
    karni_celery._merge_schedules_on_import_modules(sender=app)
    assert TESTAPP_NAMES <= set(app.conf.beat_schedule)
    assert "karni-flush-expired-tokens" in app.conf.beat_schedule


def test_import_modules_hook_ignores_other_senders() -> None:
    karni_celery._merge_schedules_on_import_modules(sender=object())  # no error, no-op


def test_import_modules_hook_waits_for_django(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from django.apps import apps

    app = Celery("not-ready")
    monkeypatch.setattr(apps, "ready", False)
    karni_celery._merge_schedules_on_import_modules(sender=app)
    assert "not merged" in caplog.text
    assert "testapp-tick" not in (app.conf.beat_schedule or {})


@pytest.mark.django_db
def test_database_scheduler_syncs_merged_entries() -> None:
    from django_celery_beat.models import PeriodicTask
    from django_celery_beat.schedulers import DatabaseScheduler

    app = create_celery_app()
    apply_discovered_schedules(app)
    scheduler = DatabaseScheduler(app=app)
    scheduler._finalize.cancel()  # no sync at interpreter exit
    nightly = PeriodicTask.objects.get(name="testapp-nightly-report")
    assert (nightly.crontab.minute, nightly.crontab.hour) == ("0", "3")
    assert json.loads(nightly.kwargs) == {"days": 1}
    tick = PeriodicTask.objects.get(name="testapp-tick")
    assert (tick.interval.every, tick.interval.period) == (900, "seconds")
    assert "testapp-tick" in scheduler.schedule


# --- describe / run ----------------------------------------------------------


@override_settings(CELERY_BEAT_SCHEDULE=SETTINGS_OVERRIDE)
def test_describe_schedules_rows() -> None:
    rows = {row["name"]: row for row in describe_schedules()}
    assert rows["testapp-nightly-report"] == {
        "name": "testapp-nightly-report",
        "task": "tests.testapp.tasks.nightly_report",
        "timing": "cron 0 3 * * *",
        "source": TESTAPP,
        "overrides": None,
        "args": [],
        "kwargs": {"days": 1},
    }
    assert rows["testapp-tick"]["source"] == SETTINGS_SOURCE
    assert rows["testapp-tick"]["overrides"] == TESTAPP
    assert rows["testapp-tick"]["timing"] == "every 1m"
    assert rows["settings-only"]["timing"] == "cron 5 * * * *"
    assert list(rows) == sorted(rows)


@pytest.mark.parametrize(
    ("value", "timing"),
    [
        (timedelta(days=1), "every 1d"),
        (interval_schedule(run_every=timedelta(minutes=5)), "every 5m"),
        (2.5, "every 2.5s"),
        ("weird", "weird"),
    ],
)
def test_timing_of_settings_values(value: Any, timing: str) -> None:
    assert schedule_mod.timing_of(value) == timing


def test_run_schedule_runs_the_task_with_its_kwargs() -> None:
    result = run_schedule("testapp-nightly-report")
    assert result.successful()
    assert result.result == "report for 1 day(s)"


def test_run_schedule_unknown_name_lists_known() -> None:
    with pytest.raises(ScheduleError, match="No schedule named 'nope'.*testapp-tick"):
        run_schedule("nope")


def test_run_schedule_unknown_task_names_the_fix() -> None:
    configured = {"ghost": {"task": "tests.testapp.tasks.missing", "schedule": 60}}
    with pytest.raises(ScheduleError, match="'ghost'.*@shared_task"):
        run_schedule("ghost", configured=configured)


# --- manage.py karni_schedules -----------------------------------------------


@override_settings(CELERY_BEAT_SCHEDULE=SETTINGS_OVERRIDE)
def test_command_table() -> None:
    out = StringIO()
    call_command("karni_schedules", stdout=out)
    lines = out.getvalue().splitlines()
    assert lines[0].split() == ["NAME", "TASK", "TIMING", "SOURCE"]
    nightly = next(line for line in lines if line.startswith("testapp-nightly-report"))
    assert "tests.testapp.tasks.nightly_report" in nightly
    assert "cron 0 3 * * *" in nightly and TESTAPP in nightly
    tick = next(line for line in lines if line.startswith("testapp-tick "))
    assert f"{SETTINGS_SOURCE} (overrides {TESTAPP})" in tick


@override_settings(CELERY_BEAT_SCHEDULE=SETTINGS_OVERRIDE)
def test_command_json() -> None:
    out = StringIO()
    call_command("karni_schedules", "--json", stdout=out)
    rows = {row["name"]: row for row in json.loads(out.getvalue())}
    assert TESTAPP_NAMES | {"settings-only"} <= set(rows)
    assert rows["testapp-tick"]["kwargs"] == {"step": 9}


def test_command_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import karni.management.commands.karni_schedules as cmd

    monkeypatch.setattr(cmd, "describe_schedules", lambda: [])
    out = StringIO()
    call_command("karni_schedules", stdout=out)
    assert "No schedules" in out.getvalue()


def test_command_run() -> None:
    out = StringIO()
    call_command("karni_schedules", "--run", "testapp-tick", stdout=out)
    assert out.getvalue().strip() == "Ran testapp-tick: 2"


def test_command_run_failure_exits_nonzero() -> None:
    err = StringIO()
    with pytest.raises(CommandError, match="'testapp-explode' failed"):
        call_command("karni_schedules", "--run", "testapp-explode", stderr=err)
    assert "scheduled task failed" in err.getvalue()


def test_command_run_unknown() -> None:
    with pytest.raises(CommandError, match="No schedule named 'nope'"):
        call_command("karni_schedules", "--run", "nope")


def test_schedule_dataclass_is_frozen() -> None:
    entry = Schedule(name="n", task="a.b", schedule=None, timing="every 1s")
    with pytest.raises(AttributeError):
        entry.name = "other"  # type: ignore[misc]
