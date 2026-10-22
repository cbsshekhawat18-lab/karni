---
description: StateField (declared states and legal transitions), CapacityField with karni.capacity.reserve(), and no_overlap EXCLUDE constraints, all enforced by the database, with the SQL each one creates.
---

# Lifecycle and capacity

The correct thing should be the default thing. Two bugs pass every test and
then show up in production:

- **A status that is a free `CharField`.** Any code path writes any value in
  any order, so a booking ends up `refunded` without ever being `paid`.
- **A capacity check that reads, compares, then writes.** Two requests read
  "1 seat left" at the same moment and both book it.

Karni moves both rules into the database and names the refusal:

| You declare | The database enforces | The refusal |
|---|---|---|
| `status = StateField(states=[...], transitions={...})` | `CHECK ("status" IN (...))`, and each `UPDATE` is conditional on the state it was loaded with | `E980` illegal move (400), `E982` wrong initial state (400), `E981` changed concurrently (409) |
| `remaining = CapacityField(total="quantity")` + `karni.capacity.reserve(row, n)` | `CHECK ("remaining" >= 0)`, `CHECK ("remaining" <= "quantity")`, a locked conditional `UPDATE` | `E985` not enough left (409) |
| `class Karni: no_overlap = NoOverlap("room", "during", ...)` | `EXCLUDE USING gist ("room_id" WITH =, "during" WITH &&) WHERE (...)` (PostgreSQL) | `E984` the slot is taken (409) |

Every model that inherits `karni.models.BaseModel` gets the model half
(`karni.models.GuardedModel`) without asking. The examples below are the
models of Karni's own test suite (`packages/karni/tests/lifecycleapp`), and
the SQL is what those models generate. A test compares this page with it.

## StateField: declared states and legal transitions

```python
from karni.fields import StateField
from karni.models import BaseModel


class Order(BaseModel):
    status = StateField(
        states=["draft", "confirmed", "cancelled", "refunded"],
        transitions={
            "draft": ["confirmed", "cancelled"],
            "confirmed": ["cancelled", "refunded"],
        },
    )
```

| Part | Rule |
|---|---|
| `states` | Every value the column may hold, in display order: names, `(value, label)` pairs, or a `TextChoices` class. Letters, digits, `_` and `-` only, because they go into a CHECK constraint. |
| `transitions` | `{state: [states it may move to]}`. A state that is not a key is **terminal**: nothing leaves it (`cancelled`, `refunded` above). |
| default | `default=`, else the first state. |
| `initial` | The states a new row may start in. The default is just the default state. `initial=["open", "triaged"]` widens it. |
| derived | `choices`, and `max_length` (the longest state, at least 20). |

A declaration that cannot work fails at import with `E983`. Examples: a
transition to an undeclared state, a state moving to itself, or a state that
no transition reaches.

The column carries a CHECK, so raw SQL cannot write an undeclared state either:

<!-- karni:sql:Order -->
```sql
"status" varchar(20) NOT NULL CHECK ("status" IN ('draft', 'confirmed', 'cancelled', 'refunded'))
```

### Moving a row

```python
order.transition("status", "confirmed")                        # the explicit API
order.transition("status", "confirmed", confirmed_at=now)       # other fields in the same write
order.allowed_transitions("status")                             # ('cancelled', 'refunded')

order.status = "cancelled"                                      # plain assignment ...
order.save()                                                    # ... is checked the same way
```

Both paths check the move against the state the row had **when it was
loaded**. That state is tracked per instance by `from_db()` and
`refresh_from_db()`, not taken from a stale copy. The `UPDATE` is then
conditional on that state:

```sql
UPDATE "lifecycleapp_order" SET "updated_at" = '...', "status" = 'confirmed'
 WHERE ("lifecycleapp_order"."status" = 'draft' AND "lifecycleapp_order"."id" = '...'::uuid)
```

In PostgreSQL, a second transaction that runs the same `UPDATE` waits on the
first one's row lock. When the first commits, the second re-checks the
`WHERE` against the new row, matches nothing, and writes nothing. Karni then
raises `StateConflict` (`E981`, HTTP 409), which names the state the row is in
now. So two concurrent transitions from one state never both succeed. The
suite proves this with two real connections, and checks in `pg_stat_activity`
that the second one waited on the first one's lock.

The same rule protects a save that does not mean to change the state. An
instance loaded as `draft` and saved after someone else confirmed the order
raises `E981`. It does not silently write `draft` back.
`save(update_fields=[...])` without the state field is never checked.

| What | Error | Where it surfaces |
|---|---|---|
| Illegal move: backwards, out of a terminal state, or an undeclared value | `IllegalTransition`, `E980` | ORM and commands: the exception. Admin: a form error. API: a 400 on the field |
| A new row in a non-initial state | `IllegalTransition`, `E982` | Same as above |
| The state changed since the row was loaded | `StateConflict`, `E981` (an `IntegrityError`) | API: 409. Admin: an error message on the same form |

The message names the current state, the requested one and the legal ones:

```text
E980: Order 3f2a…: status cannot go from 'confirmed' to 'draft'. From 'confirmed' the legal
transitions are: 'cancelled', 'refunded'. Move it to one of those, or add 'draft' to
transitions['confirmed'] on Order.status if the lifecycle should allow it. See …/errors/#e980
```

### History and events

Every transition writes a change-log entry (`karni.audit`) with action
`transition`, the actor and `{"status": ["draft", "confirmed"]}`. This happens
whether or not the model opts into `Karni.audit`. When it does opt in, the
regular `update` entries leave the state out, so nothing is recorded twice.
`StateField(audit=False)` turns the entry off.

Each transition also sends `karni.lifecycle.state_changed` (`sender`,
`instance`, `field`, `source`, `target`, `using`) inside the save's
transaction, so a listener that raises undoes it. The decorator:

```python
# shop/listeners.py
from karni.events import on_transition


@on_transition(Order, "status", to="cancelled")      # also source=..., queued=True
def refund(order: Order) -> None:
    ...
```

### The API, the admin and the schema

- **API.** The generated serializer checks the move before saving. An illegal
  one is a 400, `{"status": ["E980: … See …"]}`. A custom action that calls
  `transition()` gets the same answer, because `BaseViewSet.handle_exception`
  translates it.
- **Admin.** The status menu offers the current state and its legal next
  states only (the initial states on the add form). `Field.validate` turns an
  illegal move into a form error.
- **OpenAPI.** The field is an enum, plus two vendor extensions that
  `@karni/ui` can use to offer only the legal actions:

```json
"status": {
  "allOf": [{"$ref": "#/components/schemas/StatusEnum"}],
  "x-karni-transitions": {
    "draft": ["confirmed", "cancelled"],
    "confirmed": ["cancelled", "refunded"],
    "cancelled": [],
    "refunded": []
  },
  "x-karni-initial": ["draft"]
}
```

The server still enforces every rule. The extensions are display hints.

### Escape hatches

- `karni.lifecycle.any_initial_state(reason="importing legacy orders")`
  creates rows in any declared state inside the block. Karni's factories and
  seeders use it, so test data can start `confirmed`.
- `QuerySet.update()`, `bulk_create()` and raw SQL bypass the transition rules,
  the same way they bypass `save()`. They never bypass the CHECK.
- Override `GuardedModel.save` / `_do_update`, or use a plain `CharField`.

## Capacity: "N of this exists, do not oversell it"

```python
from django.db import models, transaction
from karni.capacity import release, reserve
from karni.fields import CapacityField


class Stock(BaseModel):
    name = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField()
    remaining = CapacityField(total="quantity")


with transaction.atomic():
    reserve(stock, 2)                 # or CapacityExceeded (E985, HTTP 409)
    Order.objects.create(stock=stock, quantity=2)

with transaction.atomic():
    release(stock, 2)                 # a cancellation gives them back
```

The database keeps the counter between zero and the total:

<!-- karni:sql:Stock -->
```sql
"remaining" integer NOT NULL CHECK ("remaining" >= 0)
CONSTRAINT "lifecycleapp_stock_remaining_lte_quantity" CHECK ("remaining" <= ("quantity"))
```

`reserve()` locks the row, refuses when too few units remain, and
decrements in SQL:

```sql
SELECT "remaining", "quantity" FROM "lifecycleapp_stock" WHERE "id" = '...' FOR UPDATE;
UPDATE "lifecycleapp_stock" SET "remaining" = ("remaining" - 2)
 WHERE ("id" = '...' AND "remaining" >= 2);
```

Concurrent buyers queue on the row lock. With capacity K and N buyers, exactly
K succeed and the count never goes below zero. The suite runs this with 12,
16 and 20 real connections. The `>= 2` guard and the CHECK also hold on a
backend without row locks (SQLite).

- **A new row starts full.** `remaining` is filled from `total`. Without a
  `total` the counter has no ceiling: pass `default=` (stock replenished with
  `release()`).
- **Resizing.** Change the total and save. `remaining` moves by the same
  amount in SQL: `SET "quantity" = 5, "remaining" = ("remaining" + 2)`. Lowering
  the total below what is reserved is refused by the CHECK, and the error
  (`E985`) names how many are reserved.
- **Never an absolute write.** `save()` writes `remaining = remaining + <shift>`,
  never a number. A stale instance cannot undo reservations made since it was
  loaded. Assigning `stock.remaining = 5` and saving is refused (`E986`).
- **Inside a transaction.** `reserve()` and `release()` raise `E986` outside
  `transaction.atomic()`. The counter and the rows that hold it must commit
  together.
- `release()` never goes above `total`. Releasing more than was reserved is a
  bug (`E986`), not a refund.
- The field is `editable=False`, so it is read-only in the API and the admin.

`CapacityExceeded` is an `IntegrityError`. The API answers 409:

```json
{"detail": "E985: Stock 'VIP' (…) is sold out (remaining = 0), but 1 was requested. …",
 "code": "E985", "field": "remaining",
 "conflict": {"resource": "lifecycleapp.Stock", "id": "…", "field": "remaining",
              "remaining": 0, "requested": 1}}
```

## no_overlap: one live booking per resource and slot

Use this for rooms, guides, vehicles and appointments:

```python
from karni.constraints import NoOverlap
from karni.fields import DateTimeRangeField, StateField


class Reservation(BaseModel):
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    during = DateTimeRangeField()
    status = StateField(
        states=["held", "confirmed", "cancelled"],
        transitions={"held": ["confirmed", "cancelled"], "confirmed": ["cancelled"]},
    )

    class Karni:
        no_overlap = NoOverlap("room", "during", ignore={"status": ["cancelled"]})
```

The model's migration creates the constraint. The first time it is applied,
it also creates the `btree_gist` extension it needs, for `=` on a uuid
column inside a GiST index:

<!-- karni:sql:Reservation -->
```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
"during" tstzrange NOT NULL
CONSTRAINT "lifecycleapp_reservation_room_during_no_overlap" EXCLUDE USING GIST ("room_id" WITH =, "during" WITH &&) WHERE (("deleted_at" IS NULL AND NOT ("status" IN ('cancelled'))))
```

- **Resource, then range.** Every field but the last is compared with `=`.
  The last is a range field, or a pair of plain fields compared as a range:

<!-- karni:sql:Slot -->
```sql
CONSTRAINT "lifecycleapp_slot_room_starts_at_ends_at_no_overlap" EXCLUDE USING GIST ("room_id" WITH =, (TSTZRANGE("starts_at", "ends_at", '[)')) WITH &&) WHERE (("deleted_at" IS NULL AND NOT ("status" IN ('cancelled'))))
```

- **Who does not block.** Soft-deleted rows never block. The `ignore=` states
  free the slot. `condition=Q(...)` exempts anything else, and
  `include_deleted=True` lets deleted rows block too.
- **Touching is not overlapping.** Ranges are half-open (`[)`), so 10:00–11:00
  and 11:00–12:00 are both fine. `bounds="[]"` makes a pair inclusive.
- **The refusal is named.** A conflicting save raises `OverlapConflict`
  (`E984`, an `IntegrityError`, and the API answers 409). Its message and its
  `conflict.existing` name the row in the way: `Reservation 7c1e… (room …,
  during [10:00, 12:00), status 'held')`. The admin catches it as a form
  error before saving (`full_clean()` runs the same query). A raw SQL `INSERT`
  is refused by the database just the same.
- **Shorthand.** `no_overlap = ("room", "nights")` is a `NoOverlap` with the
  defaults. A list declares several. `NoOverlap` is also a plain Django
  constraint, so `Meta.constraints = [NoOverlap(...)]` works the same.

**Range fields.** `karni.fields.DateRangeField` (`daterange`) and
`DateTimeRangeField` (`tstzrange`) are Django's PostgreSQL range fields. Karni
adds two things: a lower bound after the upper one is a validation error, and
the API shape is `{"lower": "…", "upper": "…", "bounds": "[)"}`, in and out,
documented in the schema (`x-karni-range`). They need psycopg (`E501`
otherwise). PostgreSQL has no time-of-day range type, so a bookable slot is a
`DateTimeRangeField`.

### Off PostgreSQL

SQLite has no `EXCLUDE`. On SQLite, `NoOverlap` creates nothing, and system
check `karni.W980` warns on every boot that overlaps are **not** enforced.
Silence it only for a development database. On SQLite, the CHECK constraints
of `StateField` and `CapacityField`, the conditional updates and `reserve()`
all work. Range columns do not, because SQLite cannot store range values. A
`(start, end)` pair of plain fields works everywhere, and PostgreSQL enforces it.

## Generating it

```sh
karni make model Booking room:fk:Room during:datetimerange \
    "status:state:held>confirmed|held>cancelled|confirmed>cancelled" \
    seats:int left:capacity:seats --with viewset
```

`status:state:a,b,c` lists the states. The generated transitions move each
state to the next one, ready to edit. `>` declares the moves instead. The
first state is the default. `during:datetimerange` and `nights:daterange`
create the range columns. `left:capacity:seats` creates
`CapacityField(total="seats")`. Mistakes are `C370` to `C372` ([the CLI
reference](cli.md)).

The agent rules say the same thing (`karni rules --explain K115`, `K116`): a
lifecycle column is a `StateField` with declared transitions, and anything
with a limited quantity or a time slot uses `karni.capacity` or `no_overlap`,
never read-then-write.

## Codes

`E980`–`E988` and `W980` ([error codes](errors.md#e980)): `E980` illegal
move, `E981` concurrent change, `E982` initial state, `E983` StateField
declaration, `E984` overlap, `E985` capacity exceeded, `E986` capacity
misuse, `E987` NoOverlap declaration, `E988` a guarded field on a model
without `GuardedModel`, and `W980` no_overlap not enforced on this database.
