# Models

Every project model inherits `karni.models.BaseModel`:

```python
from django.db import models
from karni.models import BaseModel

class Event(BaseModel):
    title = models.CharField(max_length=200)
```

`BaseModel` combines four abstract mixins. Each one also works on its own.

| Mixin | Adds | Behaviour |
|---|---|---|
| `UUIDModel` | `id` (uuid4 primary key) | No sequential IDs to enumerate, safe in URLs |
| `TimestampedModel` | `created_at` (indexed), `updated_at` | Maintained by Django (`auto_now_add` / `auto_now`) |
| `SoftDeleteModel` | `deleted_at` | `delete()` hides the row; `hard_delete()` removes it |
| `AuditedModel` | `created_by`, `updated_by` | Stamped from the current user on save |

Compose the mixins directly when a model should not have all four. For
example, an append-only log should never be soft-deleted:

```python
class AccessLog(UUIDModel, TimestampedModel): ...
```

## Soft delete

```python
event.delete()                         # sets deleted_at; the row stays
Event.objects.all()                    # excludes deleted rows (default manager)
Event.objects.all_with_deleted()       # everything
Event.objects.deleted_only()           # only deleted rows
event.restore()                        # instance; queryset.restore() for bulk
event.hard_delete()                    # real DELETE, Django cascade applies
```

- **Related lookups.** `venue.event_set.all()` hides deleted events, because
  the default manager filters them. Accessing a foreign key directly
  (`booking.event`) still resolves even when the target is soft-deleted, so
  existing references never break.
- **No cascade on soft delete.** Soft-deleting a parent leaves its children
  in place, and no `pre_delete`/`post_delete` signals are sent. `hard_delete()`
  runs Django's normal cascade, including over soft-deleted children.
- **No manager-level delete.** `Event.objects.delete()` does not exist; start
  from a queryset (`Event.objects.filter(...).delete()`).
- **Unique fields.** A soft-deleted row still occupies its unique values. A
  deleted user's email stays reserved until the user is restored or
  hard-deleted.
- **Admin.** Changelists hide deleted rows by default, with a "deleted" filter
  and restore / hard-delete actions.
- **API.** `DELETE` soft-deletes. `deleted_at` is never exposed by generated
  serializers.

## Audit fields

`karni.middleware.CurrentUserMiddleware` (installed by `karni_settings()`)
records the request in a `ContextVar`. `AuditedModel.save()` then resolves
the user lazily, so:

- JWT users authenticated inside DRF views are seen, not just session users.
- It is correct under ASGI. A context variable is isolated per asyncio task
  and copied into `sync_to_async` threads, which `threading.local` is not.

Outside a request (Celery tasks, management commands), nothing is stamped
unless you set a user explicitly:

```python
from karni.middleware import current_user

with current_user(staff_user):
    Event.objects.create(title="Imported")   # created_by = staff_user
```

`created_by` is set once on insert. `updated_by` is set on every save that
has a current user, including `save(update_fields=[...])`. Both foreign keys
are nullable, use `SET_NULL`, and have no reverse accessor; query them with
`Event.objects.created_by(user)` or `.touched_by(user)`. They are never
auto-expanded by `?expand=`, which would embed user records in every
response; list them in a viewset's `expandable_fields` to opt in.

## Querysets

Every mixin has a matching queryset in `karni.managers`, and they chain:

```python
Event.objects.created_since(monday).created_by(user).newest_first()
```

To customise, subclass `BaseQuerySet` and build the manager the same way
`BaseManager` is built:
`class EventManager(SoftDeleteManagerMixin, Manager.from_queryset(EventQuerySet))`.
Then assign `objects = EventManager()` on the model.
