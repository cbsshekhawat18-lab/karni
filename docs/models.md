---
description: "karni.models: BaseModel and its four mixins (UUID primary key, timestamps, soft delete, audit fields), the managers, related lookups, and external tables, SQL views and a second database."
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
| `SoftDeleteModel` | `deleted_at` | `delete()` hides the row, and `hard_delete()` removes it |
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

## External tables, views and a second database

!!! warning "Experimental"
    Everything in this section is [experimental](stability.md#experimental-names):
    the `class Karni` options `external`, `writable` and `database`,
    `karni.db` (with `DatabaseRouter`, `karni.db.checks` and
    `karni.db.introspection`), `BaseViewSet.is_read_only` and
    `read_only_refused_actions`, `KarniModelAdmin.is_read_only`,
    `assert_crud(..., read_only=...)`, `karni.testing.create_external_tables`,
    the pytest option `--karni-external-tables`, `manage.py karni_inspect` and
    `karni make model --external`. They may change in a minor release.

Some tables belong to another system: a reporting schema a warehouse fills, a
SQL view over your own tables, a second database with sales figures. Karni
reads them as models without owning them.

### An external table or view

Two declarations go together: `class Karni: external = True` and
`Meta.managed = False`. The model may inherit plain `models.Model`, so it
needs no UUID key, soft delete or audit columns:

```python
from django.db import models


class Sale(models.Model):
    id = models.IntegerField(primary_key=True)
    region = models.CharField(max_length=40)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    sold_on = models.DateField()

    class Meta:
        managed = False
        db_table = "sales"

    class Karni:
        external = True
```

What Karni then does:

- **No DDL, ever.** `makemigrations` records the model with `managed=False`
  (so other models can point at it), and no migration creates, alters or
  drops its table. Karni's router never migrates it.
- **Read-only by default.** Its `BaseViewSet` answers `POST`, `PUT`,
  `PATCH` and `DELETE` (and the import endpoints) with 405, to everyone,
  before authentication, and the OpenAPI document leaves those operations
  out. The admin lists the rows and shows each one read-only: no add, change
  or delete, no import page. Export works.
- **Everything else works as on any model.** `access` declarations, role
  grants (`app.sale:view` is a permission key like any other), row scope in
  the API and the admin, `Karni.field_roles`, filters, search, ordering,
  `?expand=` and export.
- **No change history**, even with `Karni.audit`, because Karni writes
  nothing to the table.
- **Skipped by seeding and by the query-scaling check.** Another system
  fills the table, so neither can seed it the way it really is.
- **The `model-base` rule accepts it**, and only with both declarations.
  `external = True` without `managed = False` is `karni.E270`.

`class Karni: writable = True` lets the API and the admin write the table
(a mapping table admins edit, a table both systems share). Change history
then follows `Karni.audit` as usual. A primary key the database does not
generate (no auto-increment, no default) is sent in the create body and
cannot change afterwards.

`BaseViewSet.is_read_only()` and `KarniModelAdmin.is_read_only()` decide
per viewset or admin. Override them to change one surface only.

### A SQL view

A view is an external model too. Give it a column whose values are unique as
the primary key (Django needs one), and create the view where your project
creates its other SQL, for example a `RunSQL` migration:

```python
class RegionTotal(models.Model):
    region = models.CharField(primary_key=True, max_length=40)
    total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        managed = False
        db_table = "region_totals"

    class Karni:
        external = True
```

### A table in another PostgreSQL schema

Django quotes `db_table` as one identifier, so a schema and a table are
written with the quoting trick:

```python
class Meta:
    managed = False
    db_table = 'reporting"."sales'   # the table "sales" in the schema "reporting"
```

Filters, ordering, `select_related`, the admin changelist and export work
on it. SQLite has no schemas, so such a model works on PostgreSQL only.

### A second database

`class Karni: database = "<alias>"` sends a model's reads, writes and
migrations to that alias of `DATABASES`. It applies to external models and
to models Karni manages there:

```python
DATABASES["warehouse"] = env.db_url("WAREHOUSE_DATABASE_URL")


class Stock(models.Model):
    sku = models.CharField(primary_key=True, max_length=20)
    quantity = models.IntegerField()

    class Meta:
        managed = False
        db_table = "stock"

    class Karni:
        external = True
        database = "warehouse"


class ProductMapping(UUIDModel, TimestampedModel):  # Karni migrates it, on warehouse only
    sku = models.CharField(max_length=20, unique=True)
    label = models.CharField(max_length=80)

    class Karni:
        database = "warehouse"
```

`karni_settings()` lists `karni.db.DatabaseRouter` in `DATABASE_ROUTERS`. It
answers from `Karni.database`:

- reads and writes of the model go to its alias;
- a model Karni manages migrates only on its own alias (`python manage.py
  migrate --database warehouse`), an external model never. On an alias some model
  names, nothing else migrates, so `migrate --database warehouse` creates no
  user or session tables there. A `RunPython` or `RunSQL` meant for that
  alias passes `hints={"model_name": "<model>"}`;
- relations between models on different aliases are refused. Django joins
  related tables in one database, so a foreign key across them cannot work,
  and `karni.E276` reports one at startup. This is why `ProductMapping`
  above composes `UUIDModel` and `TimestampedModel` instead of `BaseModel`:
  `AuditedModel`'s `created_by` and `updated_by` point at the user table on
  `default`.

A project with one database is unaffected. Routers a project lists before
Karni's win, because Django takes the first router that answers:

```python
DATABASE_ROUTERS = ["myproject.routers.ReplicaRouter", *DATABASE_ROUTERS]
```

### Checks

At startup (every `manage.py` command):

| Code | When |
|---|---|
| `karni.E270` | `external = True` without `Meta.managed = False` |
| `karni.E271` | `Karni.database` names an alias `DATABASES` does not have |
| `karni.E275` | `external` or `writable` is not a bool, or `database` not a non-empty string |
| `karni.E276` | a relation joins models on different databases |
| `karni.W541` | `writable = True` on a model that is not external |
| `karni.W542` | a model declares `Karni.database` but `DATABASE_ROUTERS` lacks Karni's router |

`karni check` also connects to every database that holds an external model
and compares each model with its table or view:

| Code | When |
|---|---|
| `karni.E272` | the table or view does not exist |
| `karni.E273` | a field's column is missing from it |
| `karni.E274` | a field's type clearly does not match its column (numbers, text, dates, times, booleans, UUIDs, JSON and binary compared as kinds, columns of unknown type skipped) |
| `karni.W540` | the database did not answer, so nothing was compared |

The comparison runs in `karni check` and not at startup, because `migrate`
runs the startup checks, and a view your own migration creates does not
exist before it runs. For the same reason `karni check --deploy`, which the
production image runs before its command, leaves it out. Silence a code with `SILENCED_SYSTEM_CHECKS` where the
table cannot exist (a CI database), and the comparison leaves it out too.

### Writing the model from the table

```sh
karni make model Sale --external --table reporting.sales --database warehouse
karni make model Target --external --table targets --writable
```

`karni make model --external` reads the table's columns from the database
with Django's `inspectdb` machinery (field types, `null`, `max_length`, the
primary key) and writes the model with `Meta.managed = False`,
`Meta.db_table` (schema-qualified for `schema.table`) and `class Karni:
external = True`, plus `database` and `writable` when given. A view gets its
`id` column, else its first unique column, else its first column as the
primary key, with a comment saying so. A foreign key column becomes a plain
field with a comment, because the model it points at may not exist yet. It
also writes the viewset with an `access` declaration to edit, as `karni make
model` does. The database must be reachable (`C140` says so when it is
not), and the table must be in it (`C141`).

### Tests

Karni's pytest plugin creates the table of every external model in each
test database once it is migrated, from the model's fields, and on
PostgreSQL the schema a `'schema"."table'` name points at. A table or view
that already exists (a view your migration creates) is left alone. So
factories, `assert_crud` and your own tests can write rows. `pytest
--karni-external-tables=off` (or `karni_external_tables = off` in the pytest
ini file) turns it off, and `karni.testing.create_external_tables(using,
models)` does it by hand. See [testing](testing.md#external-tables).
