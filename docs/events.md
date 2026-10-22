---
description: "Events and listeners: react to model changes from an app's listeners.py, loaded in web, worker and beat processes, without wiring Django signals by hand."
---

# Events and listeners

React to things that happen to your data without wiring signals by hand.
Put listeners in `<app>/listeners.py`; Karni imports that module for every
installed app at startup (`KarniAppConfig.ready()`), in web, worker and beat
processes alike. There's no `AppConfig.ready()` boilerplate and no import to
remember. Generate them: `karni make listener <name> --on Order.created
[--queued]`, `karni make event <name>` (see [the CLI reference](cli.md)).

```python
# shop/listeners.py
from karni.events import on_created, on_deleted, on_updated

from shop.models import Order


@on_created(Order)
def assign_reference(order: Order) -> None:
    ...


@on_updated(Order, queued=True)  # runs in a Celery worker after the commit
def sync_to_crm(order: Order) -> None:
    ...


@on_deleted(Order)
def release_stock(order: Order) -> None:
    ...
```

Each listener receives the model instance and nothing else. The decorator
returns your function unchanged, so you can still call it directly in tests.
The model can be the class or a lazy `"app_label.ModelName"` string, which
avoids import cycles.

## What fires when

| Operation | `on_created` | `on_updated` | `on_deleted` | `on_restored` |
|---|---|---|---|---|
| `Model.objects.create(...)`, first `save()` | ✓ | | | |
| later `save()` | | ✓ | | |
| `instance.delete()` on a soft-delete model (`BaseModel`, `SoftDeleteModel`) | | | ✓ | |
| `instance.restore()` | | ✓ | | ✓ |
| `instance.delete()` on a plain model, `hard_delete()` of a live row, cascades | | | ✓ | |
| `hard_delete()` of a row that was already soft-deleted (a purge) | | | no, it fired at the soft delete | |
| the admin's delete and restore actions | | ✓ (restore) | ✓ | ✓ |
| fixture loading (`loaddata`, `raw=True` saves) | no | no | no | no |
| `QuerySet.update()`, `bulk_create`, `bulk_update`, soft `QuerySet.delete()` and `QuerySet.restore()` | no | no | no | no |

The rules behind the table:

- **A restore takes back what a delete gave.** `on_restored` runs inside
  the restore's transaction. If it raises, the restore is undone and the row
  stays deleted. EventHub uses this to take a restored booking's seats again,
  and a sold-out tier refuses the restore with E985. The admin restores and
  deletes row by row so these listeners run. It reports a refused row and
  restores the rest.

- **A soft delete is a delete, not an update.** `SoftDeleteModel.delete()`
  saves with `update_fields` that include `deleted_at`. `karni.events.is_soft_delete(instance, update_fields)`
  recognises that, and plain receivers can call it too. A full `save()` of
  a row that already has `deleted_at` set counts as an update.
- **`on_deleted` fires once per row.** A row that was soft-deleted and is
  later purged with `hard_delete()` was already reported, so the purge does
  not fire it again. For purge-time cleanup (files, search indexes), use a
  plain `post_delete` receiver.
- **Bulk operations send no signals,** as in plain Django. The soft
  `QuerySet.delete()` is a single `UPDATE`, so it fires nothing either.
- **The sender is the exact class.** A listener on a parent model does not
  hear its subclasses or proxies, just like `@receiver(..., sender=...)`.

## Queued listeners (`ShouldQueue`)

Plain listeners run inline, inside the caller's transaction. If a listener
raises, so does the `save()`. Slow or external work belongs in a worker:

```python
from karni.events import on_created, on_deleted, queued

from shop import tasks
from shop.models import Order


@on_created(Order, queued=True)
def send_receipt(order: Order) -> None:          # runs in the worker
    ...


@on_created(Order)
@queued(queue="emails")                            # apply_async options
def notify_warehouse(order: Order) -> None:
    ...


on_deleted(Order)(queued(tasks.purge_invoice_pdf))      # an existing task gets order.pk
on_deleted(Order)(queued("shop.tasks.reindex_order"))   # …or its dotted name
```

How it behaves:

- **Dispatch happens on commit** (`transaction.on_commit`). The worker
  always sees committed rows, and a rolled-back save queues nothing.
- **A function becomes its own Celery task,** named
  `"<module>.<function>"` (for example `shop.listeners.send_receipt`). The
  worker imports `listeners.py` at startup, so it already knows the task. It
  re-fetches the row by primary key, including soft-deleted rows, and calls
  your function with it. A queued function must be defined at module level.
- **After a hard delete the row is gone,** so a snapshot of its field values
  travels with the message and the worker rebuilds an unsaved instance from
  it. Many-to-many data is not included.
- **An existing task** (`queued(task)` or `queued("dotted.name")`) receives
  the primary key. UUIDs arrive as strings.
- **If the row vanishes** before the worker runs (created, then hard-deleted
  at once), the call is skipped and a warning is logged on `karni.events`.

In tests, run Celery eagerly (`CELERY_TASK_ALWAYS_EAGER = True`) and execute
commit callbacks with pytest-django's `django_capture_on_commit_callbacks(execute=True)`
or `TestCase.captureOnCommitCallbacks(execute=True)`.

## Custom events

A custom event is a plain Django `Signal` declared in `<app>/events.py`. That
module is autodiscovered together with the listeners, before them in each
app:

```python
# shop/events.py
from django.dispatch import Signal

order_shipped = Signal()  # sent with order=<Order>
```

```python
# shop/services/shipping.py
from shop.events import order_shipped

order_shipped.send(sender=Order, order=order)
```

```python
# shop/listeners.py (or any app's listeners.py)
from django.dispatch import receiver

from shop.events import order_shipped


@receiver(order_shipped)
def email_tracking_link(sender, order, **kwargs) -> None:
    ...
```

To queue the work from a custom event, have the receiver call a Celery task
inside `transaction.on_commit(...)`.

## Escape hatches

- **Plain receivers keep working.** `@receiver(post_save, sender=Order)` in
  `listeners.py` is autodiscovered too. Use one when you need `update_fields`,
  `using` or the raw signal kwargs.
- **`KARNI_EVENTS_AUTODISCOVER = False`** stops the startup import of
  `events.py` and `listeners.py`. Import your listener modules yourself, for
  example from your own `AppConfig.ready()`.
- **`karni.events.autodiscover()`** is the function Karni calls. You can call
  it yourself after disabling the setting; it is idempotent.
