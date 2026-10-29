---
description: "karni.models: BaseModel and its four mixins (UUID primary key, timestamps, soft delete, audit fields), BigIntBaseModel for integer keys, the managers, related lookups and what each mixin does alone."
---

# Models

Every project model inherits `karni.models.BaseModel`, or `BigIntBaseModel` for an integer key:

```python
from django.db import models
from karni.models import BaseModel

class Event(BaseModel):
    title = models.CharField(max_length=200)
```

`BaseModel` combines four abstract mixins. Each one also works on its own.

| Mixin | Adds | Behaviour |
|---|---|---|
| `UUIDModel` | `id` (uuid4 primary key) | No sequential IDs to enumerate, safe in URLs. `IntegerKeyModel` puts an integer key in its place ([choosing the key type](#choosing-the-key-type)) |
| `TimestampedModel` | `created_at` (indexed), `updated_at` | Maintained by Django (`auto_now_add` / `auto_now`) |
| `SoftDeleteModel` | `deleted_at` | `delete()` hides the row, and `hard_delete()` removes it |
| `AuditedModel` | `created_by`, `updated_by` | Stamped from the current user on save |

Compose the mixins directly when a model should not have all four. For
example, an append-only log should never be soft-deleted:

```python
class AccessLog(UUIDModel, TimestampedModel): ...
```

## Choosing the key type

!!! warning "Experimental"
    Everything in this section is [experimental](stability.md#experimental-names):
    `karni.models.BigIntBaseModel`, `karni.models.IntegerKeyModel`, the
    `KARNI_PK` setting, `karni make model --pk`, `karni.api.filters.IntegerFilter`,
    the import options `match_ids` and `keep_ids`, and the `KEYS:` line of
    `karni context`.

`BaseModel` gives every row a random UUID. `BigIntBaseModel` is the same
base with a 64-bit integer that the database counts up (`BigAutoField`):
timestamps, soft delete, audit users, the guards, the managers and
`pre_write` are identical. The key type shows in each model's class line,
so one project can mix both:

```python
from karni.models import BaseModel, BigIntBaseModel

class Sensor(BaseModel):            # id: a UUID
    name = models.CharField(max_length=100)

class Reading(BigIntBaseModel):     # id: 1, 2, 3, ...
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE)
    value = models.FloatField()
```

`IntegerKeyModel` is the mixin on its own, next to `UUIDModel`, for a
composition such as `class Tick(IntegerKeyModel, TimestampedModel)`.

| | UUID (`BaseModel`) | Integer (`BigIntBaseModel`) |
|---|---|---|
| In a URL | Safe to show: nobody can guess the next one | Guessable: `/readings/1/`, `/readings/2/`, ... |
| Size and joins | 16 bytes, random order | 8 bytes, insertion order |
| Other systems | Generated anywhere, merges without clashes | Matches an existing system's integer ids |
| Created when | At `Model()` (before the insert) | At the insert (`pk` is `None` until then) |

Choose integers for a table that grows large, is joined a lot, or holds ids
another system already uses. Keep UUIDs for anything a visitor reaches by
URL. Integer keys can be guessed, so `karni check` warns (`karni.W530`) for
a resource whose model has an integer key and whose read access lets
anonymous callers in. Look such rows up by a slug (`lookup_field = "slug"`
on the viewset), keep the model on UUIDs, or say why the ids may be public
with `# karni: allow(public-integer-key): <reason>` above the viewset class
(see [enforcement](enforcement.md#integer-keys-on-a-public-resource)).

**Karni's own models keep their UUIDs.** The accounts, change history,
imports and every module's models are on `BaseModel`, and their migrations
do not change whatever your models use. Your models choose their key one
by one.

**`karni make model`** writes `BaseModel`. Set `KARNI_PK = "bigint"` in
`config/settings.py` (a plain assignment, which the CLI reads without
importing your project) to make it write `BigIntBaseModel`, and pass
`--pk uuid` or `--pk bigint` to choose for one model. Nothing else reads the
setting.

**Ids stay JSON numbers.** The API writes an integer id as a number
(`"id": 1234`), so mind two limits:

- **JavaScript** holds integers exactly up to 2^53 - 1
  (9 007 199 254 740 991). A sequence that starts at 1 stays far below it,
  but an id from another system above it loses digits in the browser. Keep
  such a value in a string field next to the key.
- **Excel** keeps 15 significant digits. An exported id longer than that
  comes back changed. Format the column as text before you edit and import
  the file.

**Switching an existing model's key type** while it holds data is out of
scope. Every foreign key, many-to-many table, change-history row and import
file that names those rows would have to be rewritten in one data migration,
and Karni does not write it for you. Choose the key type when you create the
model.

### An integer-keyed user

A project can give its own user model an integer key by redeclaring `id` on
a subclass of `AbstractKarniUser`:

```python
from django.db import models
from karni.accounts.models import AbstractKarniUser

class User(AbstractKarniUser):
    id = models.BigAutoField(primary_key=True)
```

Point `AUTH_USER_MODEL` at it before the first `migrate`, as for any custom
user model. Login, JWT and session mode, `me/`, roles, the 2FA gate,
sign-in with an ID token or a code, and the terms gate all work with it, and
Karni's suite runs those flows with such a user.

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
- **No manager-level delete.** `Event.objects.delete()` does not exist. Start
  from a queryset (`Event.objects.filter(...).delete()`).
- **Unique fields.** A plain `unique=True` (or `UniqueConstraint`) counts
  soft-deleted rows, so a deleted row keeps its value reserved until it is
  restored or hard-deleted. Unique [Karni fields](fields.md) (`SlugField`,
  `EmailField(unique=True)`, ...) and `LiveUniqueConstraint(fields=[...])`
  count live rows only, so a deleted row frees its value.
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

- JWT users authenticated inside DRF views are seen, as well as session users.
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
are nullable, use `SET_NULL`, and have no reverse accessor. Query them with
`Event.objects.created_by(user)` or `.touched_by(user)`. They are never
auto-expanded by `?expand=`, which would embed user records in every
response. List them in a viewset's `expandable_fields` to opt in.

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
with `instance`, `action` (`create`, `update`, `delete`) and `update_fields`.
It is sent before any SQL, outside any transaction the save would open, and
once per `delete()` (not again for the `deleted_at` save a soft delete performs). A
receiver may stop the write by raising `karni.exceptions.KarniWriteDeferred`
with a `payload` and a `status` (202 by default): a `BaseViewSet` then
answers that status with the payload instead of writing, a Karni admin shows
the message and returns to the changelist (inlines and bulk deletes
included), and plain code gets the exception. Nothing is written and nothing
needs rolling back.

That is the hook the `karni-approvals` module is built on (a guarded change
becomes a pending change a second person decides), and any module can use it
the same way. Bulk SQL (`QuerySet.update()`, `bulk_create()`), raw saves and
fixture loading never send it. `karni check`'s `audited-bulk-write` rule is
the guard for those on audited models.

## The staff dashboard

A model that should be counted and listed on the staff app's home page says
so next to its other `class Karni` options: `dashboard = True`, or a dict
that picks the counts and the columns. The keys, the defaults and what the
page shows are in [API: the staff dashboard](api.md#the-staff-dashboard).
