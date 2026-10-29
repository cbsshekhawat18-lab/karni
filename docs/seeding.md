---
description: karni seed fills every table with realistic, connected demo data, the same rows for the same seed value, from per-model seed definitions, and prints a demo login.
---

# Seeding demo data

`karni seed` fills every table of your project with realistic, connected
data, so a fresh project has populated screens the moment you open it:

```sh
karni seed                         # 10 rows per model, seed 0
karni seed --count 20 --seed 42    # the same 20 rows on every machine
karni seed --reset                 # wipe the project's tables first
karni seed --model events.Event    # only these models (repeatable)
karni seed --force                 # add demo rows to tables that already hold rows
karni seed --json                  # machine-readable report
```

It wraps `manage.py karni_seed` through the project interpreter, like the
other runners. `karni.seeding.seed()` is the importable form. It refuses to
run with `DEBUG = False` (a production database) unless you pass `--force`.

Seeding is for demo data: random rows that make an empty development
database look used. A site's real copy, images and team belong in a content
file loaded with [`karni load`](content-loading.md), which creates or updates
exactly the rows the file lists and can run in every environment.

## When seed refuses

Before it writes anything, `karni seed` prints the models it will write to:

```text
Seeding 3 model(s): karni_accounts.User, events.Venue, events.Event
```

It then refuses (`E617`) when one of those tables already holds rows,
because a seeded row carries no mark. Seed cannot tell its own rows from
content someone loaded or typed in, and demo rows added on top would mix
with that content for good. The rule is simple: **any row in a table the run
would write to counts**, soft-deleted rows included. Two exceptions keep a
fresh project seeding without flags:

- **The user table is left out.** Users are matched by their login and never
  deleted, and a fresh project may already have its superuser.
- **`--model` narrows the check** to the tables that run seeds.

To seed anyway:

- `--reset` deletes the project models' rows first (users are kept), then
  seeds. This is what a demo or end-to-end script runs every time.
- `--force` adds demo rows on top of what is there.

So a second plain `karni seed` on the same database refuses. Run
`karni seed --reset` to start over with the same seed.

## What you get

- **Every model of your own apps**, plus the user model and any model a
  seeder names. Models Django does not manage (`Meta.managed = False`) are
  left out, [external tables and views](models.md#external-tables-views-and-a-second-database)
  among them: another system fills them. Relation targets are seeded first, so foreign keys point at
  real rows, to-many relations get a few rows each, and one-to-one targets
  are used once.
- **Values inferred from field names and types**, from the same engine the
  test factories use (`karni.testing.values`):
  - A field called `email` gets an email at example.com.
  - `price` gets money.
  - `starts_at` gets a near-future datetime, and `ends_at` falls after it.
  - `slug` follows `title`.

  Optional fields are mostly filled.
- **Constraints hold.** Unique values embed the row's number, and a clash on
  a multi-field constraint is retried.
- **A demo login.** The first user is `demo@example.com` with password
  `karni-password`. It is staff and superuser, and holds every role your
  `access` declarations name. About half of the user-owned rows belong to it,
  so every screen has data when you sign in. Users are matched by email, so
  a re-run with `--reset` or `--force` never duplicates them, and `--reset`
  never deletes them.
- **Known logins.** `KARNI_SEED_LOGINS = {"organizer@example.com": ["organizer"],
  "attendee@example.com": ["attendee"]}` (env: JSON) creates those users with
  the demo password and the roles listed. These are the accounts a demo script
  or an end-to-end suite signs in with. Re-runs reuse them.
- **Determinism.** `--seed` drives every random choice. The same seed and
  count give the same rows, including UUIDs and dates, which come from a
  fixed anchor rather than "now".

Demo emails and URLs use the reserved `example.com/.org/.net` domains, so
seeded data can never reach a real inbox.

## Per-model overrides: `<app>/seeds.py`

`karni make seeder <Model>` writes one. A seeder is discovered by convention:

```python
# events/seeds.py
import factory

from karni.seeding import SeedContext, Seeder

from events.models import Event, Venue


class VenueSeeder(Seeder):
    class Meta:
        model = Venue
        count = 3                       # always 3 venues (None = --count, 0 = skip)

    name = factory.Iterator(["Main Hall", "Studio B", "Rooftop"])


class EventSeeder(Seeder):
    class Meta:
        model = Event

    def seed(self, context: SeedContext) -> list:
        rows = context.create(context.count - 1)
        return [*rows, *context.create(1, title="Launch party")]
```

Any class attribute other than `Meta` is a field override, using any
factory-boy declaration. Override `seed()` for full control. `context.create()`
builds rows with everything inferred except what you pass.

## Escape hatches

| Need | Do |
|---|---|
| A model never seeded | `class Meta: count = 0` in its seeder |
| Different values for one field | A class attribute on the seeder |
| Different inference everywhere | Subclass `karni.testing.values.ValueInference`, change its `rules`, and pass it to the builder |
| Seed from your own code | `karni.seeding.seed(count=..., seed=..., models=...)`. It does not refuse: check `karni.seeding.occupied(seed_plan())` yourself |
| Real content, not demo data | A content file and [`karni load`](content-loading.md) |
