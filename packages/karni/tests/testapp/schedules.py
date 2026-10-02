"""Schedules autodiscovered by :func:`karni.schedule.discover` (tests/test_schedule.py).

One of each declaration style: interval string with a task object, interval
keywords with a dotted task name, a cron expression with kwargs, and a task
that fails (for ``karni_schedules --run`` error reporting).
"""

from __future__ import annotations

from karni.schedule import cron, every
from tests.testapp import tasks

every("15m", tasks.tick, name="testapp-tick", kwargs={"step": 2})
every(hours=1, task="tests.testapp.tasks.tick", name="testapp-hourly-tick")
cron(
    "0 3 * * *",
    "tests.testapp.tasks.nightly_report",
    name="testapp-nightly-report",
    kwargs={"days": 1},
)
every("1d", tasks.explode, name="testapp-explode")
