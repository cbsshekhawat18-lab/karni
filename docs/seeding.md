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

- `--reset` deletes the project models' rows first, and the rows of every
  other model a seeder in `seeds.py` names (a module's table, `UserGrant`).
  Users are kept. It restarts the id sequences of the tables it wiped, then
  seeds. This is what
  a demo or end-to-end script runs every time.
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
  a multi-field constraint is retried. A `SlugField(populate_from="name")` is
  the exception: the field makes it from its source on save, so a region named
  Europe gets `europe`, and only a second Europe gets `europe-2`. Such a slug
  is often the import key, so an import file names the row as a person
  would. A seeder or an explicit factory that declares the slug wins, and a
  [volume run](#volume-seeding) keeps the numbered values.
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
  fixed anchor rather than "now". [Integer keys](models.md#choosing-the-key-type)
  come from the database's sequence, not the seed, so for them the promise
  holds after `--reset`: it restarts the sequence of every table it wipes, so
  the same seed gives ids 1, 2, 3, ... again. Without `--reset`, new rows
  continue the sequence.

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

## Volume seeding

!!! warning "Experimental"
    `karni seed --volume` and `--batch-size`, `karni.bulk_seeding`, the
    `volume`, `bulk` and `batch_size` arguments of `karni.seeding.seed()`,
    the seed ledger (`.karni/local/seeded.json`) and the settings
    `KARNI_SEED_BULK_THRESHOLD`, `KARNI_SEED_BATCH_SIZE` and
    `KARNI_SEED_LEDGER` are [experimental](stability.md#experimental-names).

Ten rows per table make the screens look used. A query that slows down at a
hundred thousand rows needs a hundred thousand rows:

```sh
karni seed --volume 100000                        # 100,000 rows per model
karni seed --volume 100000 --model shop.Order     # only these models, and what they need
karni seed --volume 20000 --batch-size 5000
```

The models are seeded in the same order, the targets of a relation before
the model that points at them. Each model's rows are built with the same
factories, so the inferred values and every override in `<app>/seeds.py`
apply, then written with `bulk_create` in batches (`--batch-size`, else
`KARNI_SEED_BATCH_SIZE`, default 2000). A foreign key is drawn from the
target's existing rows, a one-to-one target is used once, a relation to the
model itself points at rows of earlier batches (so a tree gets depth), and a
many-to-many gets zero to three targets per row. Free text repeats from a
pool of a thousand values per field, because text is the costly value to
make. The `auto_now` timestamps are spread over the last 60 days. The user
model gets one user per hundred rows, the demo way, with the demo login. The
report has the rows, the time and the rate per model:

```text
Seeded 3 model(s) with seed 0 (volume 100000) in 74.6s:
  testapp.Tag    100000  (bulk, 16.4s, 6,102 rows/s)
  testapp.Venue  100000  (bulk, 15.5s, 6,451 rows/s)
  testapp.Event  100000  (bulk, 38.7s, 2,584 rows/s)
```

That run is on PostgreSQL on a laptop. `Event` has two foreign keys and a
many-to-many, so its 100,000 rows bring about 200,000 links.

Bulk rows skip `save()`: no `post_save` is sent, listeners do not run and no
change history is written for them. A seeder that overrides `Seeder.seed()`
keeps full control, and its model is seeded row by row through that method.

Volume rows never mix with real content. Every `karni seed` run records, per
database, how many rows each table holds when it is done, in
`.karni/local/seeded.json`. `karni seed --volume` refuses
([E473](errors.md#e473)) when a table holds another number of rows than the
ledger recorded, because someone else wrote to it, unless `--reset` wipes
the project's tables first or `--force` adds rows anyway. So a demo seed
followed by a volume seed, or two volume runs in a row, go through, while a
table with real rows stops the run. `KARNI_SEED_LEDGER = False` turns the
ledger off, and a volume run then needs empty tables, as the demo seed does.

A model whose seed count reaches `KARNI_SEED_BULK_THRESHOLD` (default 1000)
takes the bulk path in a plain `karni seed` too: a seeder's `Meta.count`, or
a large count in [`karni.yaml`](app-spec.md#seed), which `karni plan` shows
with how long it takes.

## Escape hatches

| Need | Do |
|---|---|
| A model never seeded | `class Meta: count = 0` in its seeder |
| Different values for one field | A class attribute on the seeder |
| Different inference everywhere | Subclass `karni.testing.values.ValueInference`, change its `rules`, and pass it to the builder |
| Seed from your own code | `karni.seeding.seed(count=..., seed=..., models=...)`. It does not refuse: check `karni.seeding.occupied(seed_plan())` yourself |
| Volume rows of your own | Subclass `karni.bulk_seeding.BulkSeeder` (`rows`, `insert`, `pick_key`, ...) and pass `bulk=` to `karni.seeding.seed(volume=...)` (experimental) |
| Bulk from another count, or other batches | `KARNI_SEED_BULK_THRESHOLD`, `KARNI_SEED_BATCH_SIZE` (experimental) |
| Real content, not demo data | A content file and [`karni load`](content-loading.md) |
