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
karni seed --json                  # machine-readable report
```

It wraps `manage.py karni_seed` through the project interpreter, like the
other runners. `karni.seeding.seed()` is the importable form. It refuses to
run with `DEBUG = False` (a production database) unless you pass `--force`.

## What you get

- **Every model of your own apps**, plus the user model and any model a
  seeder names. Relation targets are seeded first, so foreign keys point at
  real rows, to-many relations get a few rows each, and one-to-one targets
  are used once.
- **Values inferred from field names and types**, from the same engine the
  test factories use (`karni.testing.values`):
  - a field called `email` gets an email at example.com;
  - `price` gets money;
  - `starts_at` gets a near-future datetime, and `ends_at` falls after it;
  - `slug` follows `title`.

  Optional fields are mostly filled.
- **Constraints hold.** Unique values embed the row's number, and a clash on
  a multi-field constraint is retried.
- **A demo login.** The first user is `demo@example.com` with password
  `karni-password`. It is staff and superuser, and holds every role your
  `access` declarations name. About half of the user-owned rows belong to it,
  so every screen has data when you sign in. Users are matched by email, so
  re-running never duplicates them and `--reset` never deletes them.
- **Known logins.** `KARNI_SEED_LOGINS = {"organizer@example.com": ["organizer"],
  "attendee@example.com": ["attendee"]}` (env: JSON) creates those users with
  the demo password and the roles listed — the accounts a demo script or an
  end-to-end suite signs in with. Re-runs reuse them.
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
factory-boy declaration. Override `seed()` for full control; `context.create()`
builds rows with everything inferred except what you pass.

## Escape hatches

| Need | Do |
|---|---|
| A model never seeded | `class Meta: count = 0` in its seeder |
| Different values for one field | A class attribute on the seeder |
| Different inference everywhere | Subclass `karni.testing.values.ValueInference`, change its `rules`, and pass it to the builder |
| Seed from your own code | `karni.seeding.seed(count=..., seed=..., models=...)` |
