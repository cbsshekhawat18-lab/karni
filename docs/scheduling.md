# Scheduling and background work

Declare periodic work next to the app that owns it, in `<app>/schedules.py`.
There's no `CELERY_BEAT_SCHEDULE` dict to maintain by hand:

```python
# shop/schedules.py
from karni.schedule import cron, every

from shop import tasks

every("15m", tasks.sync_inventory)                          # name defaults to the task name
every(hours=1, task="shop.tasks.expire_carts", name="expire-carts")
cron("0 3 * * *", "shop.tasks.nightly_report", name="nightly-report", kwargs={"days": 1})
cron("*/10 8-18 * * mon-fri", tasks.poll_supplier, name="supplier-poll", options={"queue": "low"})
```

```python
# shop/tasks.py
from celery import shared_task


@shared_task
def sync_inventory() -> None:
    ...
```

## Declarations

`every(interval, task, *, name=None, args=None, kwargs=None, options=None, seconds=0, minutes=0, hours=0, days=0)`

- `interval` can be a string such as `"30s"`, `"15m"`, `"1h"`, `"1d"` or
  `"1h30m"`, a number of seconds, or a `timedelta`. You can also leave it out
  and use the keywords: `every(minutes=15, task=...)`.
- Intervals are whole, positive seconds. django-celery-beat stores intervals
  as integer seconds.

`cron(expression, task, *, name=None, args=None, kwargs=None, options=None)`

- The expression has the five standard fields `minute hour day-of-month
  month day-of-week`, with `*`, ranges, steps, lists and day names
  (`mon-fri`).
- Times are in the Celery app's timezone (`CELERY_TIMEZONE`, otherwise
  `TIME_ZONE`).

Both take the same remaining arguments:

- `task` is the task object or its dotted name.
- `name` is the schedule's unique name. It becomes the beat entry key and
  the django-celery-beat `PeriodicTask` name. It defaults to the task name,
  so give two schedules of the same task distinct names.
- `args` and `kwargs` must be JSON-serializable, because django-celery-beat
  stores them as JSON. Pass ids, not objects.
- `options` are `apply_async` options, such as `queue` or `priority`.

Mistakes fail loudly with a `karni.schedule.ScheduleError` (an
`ImproperlyConfigured`) that names the fix. For example, `cron("0 25 * * *")`
fails with `invalid hour field '25'`, `every("15x")` lists the accepted
units, and a duplicate name names both declaring modules.

## How schedules reach beat

1. `karni.celery.create_celery_app()` hooks the app's `import_modules`
   signal. Worker and beat processes send it after Celery's Django fixup has
   run `django.setup()` and before beat builds its scheduler.
2. On that signal, `apply_discovered_schedules(app)` imports every installed
   app's `schedules` module and merges the declarations into
   `app.conf.beat_schedule`.
3. django-celery-beat's `DatabaseScheduler` (Karni's default) syncs every
   entry into its `PeriodicTask` table, by name, each time beat starts. The
   default `PersistentScheduler` reads the same merged schedule.

**Settings win.** If `CELERY_BEAT_SCHEDULE` (or a `beat_schedule=` factory
override) has an entry with the same name as a declaration, the settings
entry is used. That is how you retime or swap a declared schedule in one
environment without editing code. `karni schedule list` shows such a row as
`settings.CELERY_BEAT_SCHEDULE (overrides shop.schedules)`.

Karni's own daily `karni-flush-expired-tokens` entry lives in
`CELERY_BEAT_SCHEDULE` (see `karni.conf`).

Removing a declaration does not delete its `PeriodicTask` row; beat simply
stops refreshing it. Disable or delete the row in the admin
(*Periodic tasks*). The same applies to any row you disabled there: beat
never re-enables it.

## Commands

| Command | Wraps | What it does |
|---|---|---|
| `karni schedule list [--json]` | `manage.py karni_schedules` | every merged schedule: name, task, timing, source |
| `karni schedule run <name>` | `manage.py karni_schedules --run <name>` | runs the task once, synchronously, with its args; exits non-zero if it raised |
| `karni worker [ARGS]` | `python -m celery -A config worker -l info` | a worker (`-Q`, `--concurrency` … pass through) |
| `karni beat [ARGS]` | `python -m celery -A config beat -l info` | the scheduler; run exactly one |

All four run through the project interpreter: the project's `.venv` if there
is one, otherwise the running compose service. With `docker compose up`, the
scaffold's `worker` and `beat` services already run. `karni worker` and
`karni beat` are for `.venv` development (`karni serve --local`) or a one-off
extra worker; use `-A/--app` (or `KARNI_CELERY_APP`) if your Celery app is
not `config`.

`karni schedule run` executes in-process with Celery's `Task.apply()`, so no
broker or worker is needed. It is the quickest way to check that a scheduled
task works.

## Escape hatches

- `CELERY_BEAT_SCHEDULE` entries win on a name conflict, and you can keep
  using it for everything.
- `KARNI_SCHEDULES_AUTODISCOVER = False` stops the import of
  `<app>/schedules.py`. Import the modules you want yourself; their
  declarations still merge.
- `every(..., registry=ScheduleRegistry())` declares into your own registry,
  and `merge_beat_schedule(configured, entries)` builds a `beat_schedule`
  from it.
- Building the Celery app without the factory? Call
  `karni.celery.apply_discovered_schedules(app)` once Django is set up.
- Need the entries in code? `karni.schedule.describe_schedules()` returns the
  rows that `karni schedule list` prints, and `run_schedule(name)` runs one.
