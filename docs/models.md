---
description: "karni.models: BaseModel and its four mixins (UUID primary key, timestamps, soft delete, audit fields), the managers, related lookups and what each mixin does alone."
---

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
Event.objects.all()                    # excludes deleted rows (the soft_delete scope)
Event.objects.without("soft_delete", reason="restore screen")         # everything
Event.objects.without("soft_delete", reason="restore screen").dead()  # deleted only
event.restore()                        # instance; queryset.restore() for bulk
event.hard_delete()                    # real DELETE, Django cascade applies
```

- **Related lookups.** `venue.event_set.all()` hides deleted events, because
  the default manager filters them. So do prefetches and the admin.
  Accessing a foreign key directly (`booking.event`) still resolves even when
  the target is soft-deleted, so existing references never break.
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

## Scopes: the filters every default manager applies

Hiding deleted rows is a **scope**: a named, ordered filter that Karni's
default managers apply to every queryset they build. Core registers one,
`soft_delete` (order 10, every model with a `deleted_at` column). Installed
modules can add more. The planned `karni-tenancy` module adds `tenant`
(order 20) to every `BaseModel`, without any change to project code.

A scope reaches everything built from a model's default manager:
`Model.objects`, related managers (`venue.event_set`, M2M), `prefetch_related`,
the admin, and DRF relation fields. It does not reach Django's base manager
(forward FK access, `refresh_from_db`, deletion cascades), joins across
relations (`Venue.objects.filter(event__title=...)`, so add
`event__deleted_at__isnull=True` yourself), or raw SQL.

**Lift one scope, never all of them.**

```python
Event.objects.without("soft_delete", reason="restore screen")
venue.event_set.without("soft_delete", reason="venue history")  # keeps the relation
# with karni-tenancy installed: lift both, for a cross-tenant report
Event.objects.without("tenant", "soft_delete", reason="nightly billing export")
```

- `reason` is required, and is logged on the `karni.scopes` logger: DEBUG for
  `soft_delete`, INFO for other scopes. A missing or blank reason raises.
- Only the named scopes are lifted. Every other scope still applies, so
  showing deleted rows never also shows another tenant's rows.
- An unknown name raises `UnknownScope`, which lists the registered names.
  A registered scope that does not cover the model is a no-op.
- `without()` lives on managers, because a scope cannot be removed from a
  queryset after it was applied. For another database, use
  `Event.objects.db_manager("replica").without(...)`.

**`karni context`** prints a `SCOPES:` line when the pipeline differs from
this default: any scope besides `soft_delete`, with the models it covers, or
`soft_delete(off)`.

**Escape hatches**, least to most drastic:

| Need | Do |
|---|---|
| One query sees hidden rows | `objects.without("<scope>", reason=...)` |
| A model is exempt from a scope | `class ScopeMeta: tenant = "shared"`. Each scope reads its own `ScopeMeta` attribute through `karni.scopes.scope_option()`. |
| Different behaviour for a scope | Subclass it and register yours under a new name |
| Disable or reorder scopes project-wide | `KARNI_SCOPES = ["soft_delete"]`: the active scopes, in pipeline order. Unset means every registered scope by `order`. A registered scope left out raises system-check warning `karni.W001`, so silence it when that is deliberate. |

**Writing a scope** (modules): subclass `karni.scopes.Scope`, set `name` and
`order`, and implement `applies_to(model)` and `filter(queryset)`. Then
register the class through the `karni.scopes` entry-point group (see
[modules.md](modules.md#7b-optional-karniscopes-model-scopes)). `filter()` runs
when a queryset is *built*, which can be import time for a class-level
`queryset = Model.objects.all()`. A scope that depends on the current request
or task must read that context when the SQL is compiled, from an expression
whose `as_sql` reads it. If nothing is bound there, it must raise
`karni.scopes.ScopeContextMissing(model, name, fix=...)` so the query fails
closed, never open.

**Custom managers** must run the pipeline. Build them on
`karni.managers.ScopedManagerMixin`:

```python
from django.db.models import Manager
from karni.managers import BaseQuerySet, ScopedManagerMixin

class EventQuerySet(BaseQuerySet):
    def upcoming(self): ...

class EventManager(ScopedManagerMixin, Manager.from_queryset(EventQuerySet)):
    pass
```

System check `karni.E001` rejects a soft-delete model whose default manager
does not apply `soft_delete`. `karni.E002` reports a scope that fails to load
or a malformed `KARNI_SCOPES`.

## Deprecated soft-delete aliases

Deprecated in 0.2 and removed in 1.0. Each emits a
`karni.deprecation.KarniDeprecationWarning` that names its replacement and
links its [migration note](migrations/0.2.md#deprecated-in-02-removed-in-10).
`karni upgrade` rewrites every use.

| Deprecated | Use instead |
|---|---|
| `Model.all_objects` | `Model.objects.without("soft_delete", reason=...)` |
| `objects.all_with_deleted()` | `objects.without("soft_delete", reason=...)` |
| `objects.deleted_only()` | `objects.without("soft_delete", reason=...).dead()` |
| `karni.managers.SoftDeleteManagerMixin` | `karni.managers.ScopedManagerMixin` (the same class) |

Until 1.0 the aliases still work, with one change. `all_objects` used to
drop every filter. It now lifts only `soft_delete`, so it can never bypass a
scope a module adds later. To find every caller, run your tests with
`-W error::karni.deprecation.KarniDeprecationWarning`.

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
`BaseManager` is built (see *Custom managers* above):
`class EventManager(ScopedManagerMixin, Manager.from_queryset(EventQuerySet))`.
Then assign `objects = EventManager()` on the model.

## Write interception

Every `BaseModel` `save()` and `delete()` first sends `karni.signals.pre_write`
with `instance`, `action` (`create`, `update`, `delete`) and `update_fields`
— before any SQL, outside any transaction the save would open, once per
`delete()` (not again for the `deleted_at` save a soft delete performs). A
receiver may stop the write by raising `karni.exceptions.KarniWriteDeferred`
with a `payload` and a `status` (202 by default): a `BaseViewSet` then
answers that status with the payload instead of writing, a Karni admin shows
the message and returns to the changelist (inlines and bulk deletes
included), and plain code gets the exception. Nothing is written and nothing
needs rolling back.

That is the hook the `karni-approvals` module is built on — a guarded change
becomes a pending change a second person decides — and any module can use it
the same way. Bulk SQL (`QuerySet.update()`, `bulk_create()`), raw saves and
fixture loading never send it; `karni check`'s `audited-bulk-write` rule is
the guard for those on audited models.
