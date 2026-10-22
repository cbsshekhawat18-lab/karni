---
description: Why Karni generates serializers from models instead of hand-writing them, how a generated serializer is customised, and when to write your own.
---

# Why serializers are generated

In a plain DRF project, every model gets a serializer that restates its
fields, an admin that restates them again, a filter set, a form schema on the
frontend, and a test fixture: five copies of one fact. They drift. Karni
keeps the fact in one place, the model, and generates the rest.

## What `BaseViewSet(model=X)` generates

Given a model, the viewset builds a `KarniModelSerializer` at class-creation
time from the model's fields, with:

- the audit fields (`id`, `created_at`, `updated_at`, `created_by`,
  `updated_by`) read-only, password-named fields never exposed, and
  user-model flags read-only
- a deterministic, app-qualified component name in the OpenAPI schema
  (`EventsEvent`, `EventsEventRequest`), so the frontend's generated types
  never collide
- relation fields that accept only primary keys the requester may read,
  through the target model's own `access` (see [permissions at the
  queryset](queryset-permissions.md))
- `?expand=` variants, nested one level per segment and cached per
  expand-set
- the model's `clean()` run on every create and update, so a domain
  invariant lives on the model and arrives as a 400 keyed by field
- plain model defaults published as `default:` in the schema, so a generated
  form starts from them

The same serializer drives the admin's columns, the filter set, the query
optimiser (it walks the serializer tree to derive `select_related` and
`prefetch_related`) and the frontend's `ResourceTable`, `ResourceForm` and
`ResourceDetail`, which render from the OpenAPI schema at runtime.

## Steering it: `APIMeta`

The model carries the API-facing choices that are not visible from the
fields alone:

```python
class Booking(BaseModel):
    ...

    class APIMeta:
        read_only = ["status", "payment"]   # the API never accepts these
        exclude = ["confirmation_sent_at"]  # never exposed at all
        select = ["tier"]                   # a hint for a property in `fields`
```

`fields` or `exclude`, `read_only`, `write_only`, `schema_name`, `select`,
`prefetch` and `validate` cover what a hand-written serializer usually
changes. Because the declaration is on the model, the admin and the frontend
agree with it without a second declaration.

## When you do write one

Sometimes a serializer needs computed fields, nested writes or a custom
representation. Then write one:

```sh
karni make serializer Booking --reason "nested ticket lines on write"
```

The generator subclasses `KarniModelSerializer` (so relation scoping,
`clean()` and the vendor extensions stay), sets `serializer_class` on the
viewset, and records the reason as a `# karni: allow(redundant-serializer)`
marker. The reason is required because rule K106 flags a serializer that
only restates the model's fields: that one would be a copy, and copies
drift. [Error E122–E125](../errors.md) and `karni explain K106` describe the
boundaries.

## What this buys

- **One fact, one place.** Add a field to the model and it is in the API,
  the admin, the filter set, the form and the table.
- **A schema the frontend can trust.** Component names, enum members,
  defaults, nullability and relation targets come from the same code that
  serves the data, and `assert_schema_snapshot()` fails CI when they change.
- **Less for an agent to get wrong.** The serializer is not a file an agent
  writes, so it cannot omit a read-only field or expose a password hash.

The trade: a serializer is a class you can read in DRF, and here it is a
class you can only inspect (`karni routes`, `/api/schema/`). The escape
hatch is always one command away, and it keeps everything Karni adds.
