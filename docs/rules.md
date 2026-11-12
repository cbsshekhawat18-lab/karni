---
description: "Business rules an app declares instead of writing them: bounds, unique among live rows, which rows a relation may point at, frozen fields, delete rules, what a state change needs and stamps, and row actions with the states and roles where each is legal. In karni.yaml and in class Karni, with the error each refusal carries and the escape hatches."
---

# Rules

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    the `class Karni` options `bounds`, `unique`, `targets`, `frozen`,
    `delete` and `moves` (`karni.rules`), `Access(delete=..., assign=...)`,
    the written-row check, `Matching`, row actions (`karni.api.actions`) and
    the karni.yaml keys that write them.

Most apps need the same few business rules: a price above zero, one booking
per member and slot, a lesson only in your own course, no delete while
children exist, a reason when a deal is lost, a pay button that never
charges twice. Without a declaration each one is hand code in every
project, and the code is usually missing. Karni keeps them as data: a key of
an entity in `karni.yaml`, which `karni build` writes as the `class Karni`
option of the same name, and Karni checks on every write.

```yaml
Order:
  fields:
    listing: fk:Listing
    buyer: fk:User
    quantity: int
    status: "state:pending>paid|pending>cancelled|paid>refunded"
    refund_reason: "text?"
    refunded_at: "datetime?"
  owner: buyer
  bounds: {quantity: {min: 1}}
  unique: [{fields: [listing, buyer], where: {status: pending}}]
  targets: {listing: {active: true, seller__user: {not: $me}}}
  frozen: {listing: true, quantity: true}
  delete: {when: {status__in: [pending, cancelled]}}
  moves: {refunded: {requires: [refund_reason], stamps: [refunded_at]}}
  actions:
    pay: {from: pending, by: "owned:buyer"}
    cancel: {from: pending, to: cancelled, by: ["owned:buyer", "role:staff"]}
    refund: {from: paid, to: refunded, by: "role:staff"}
  access:
    read: ["owned:buyer", "owned:listing__seller__user", "role:staff"]
    write: ["owned:buyer", "role:staff"]
    delete: "role:staff"
```

## The shared pieces

**A row filter** is a mapping of a path to a value, and every entry must
hold. The path is a field, or a path through relations (`seller__user`),
optionally ending in one of the lookups `gt`, `gte`, `lt`, `lte`, `in` and
`isnull` (`starts_at__gt`). A value is:

| Value | Means |
|---|---|
| a literal | text, a number, `true` / `false`, a list for `in` |
| `$me` | the signed-in user |
| `$now`, `$today` | the current time, today's date |
| `$<path>` | a field of the row being written, through relations too (`$company`, `$enrolment__course`) |
| `{not: <value>}` | anything but the value |

An entry that names `$me` is left out when nobody is signed in (a task, a
seed, the shell): a rule about the caller needs a caller. `karni seed` reads
`$now` and `$today` as its anchor (`karni.rules.clock`), so demo data
relative to a fixed day passes the rules the same way on every run.

**A relation reference** names the rows of another entity that point at this
one: `Deal` (its one foreign key to this entity), `Deal.company` (that
foreign key, when it has two) or `crm.Deal` (an entity of another app). Only
live rows count: a soft-deleted one does not.

**Who** is written in the access words: `owned:<path>`, `role:<slug>`,
`granted`, `authenticated`, `public`, or a list of them.

## Where the rules run

`save()` checks every rule before any SQL and writes what a move stamps.
`clean()` turns a refusal into a form error, so the admin, an import and
`full_clean()` show it on the field. `delete()` checks `delete`. The API
answers **400** naming the field (a delete: **409**), with the code. The
unique index also holds against raw SQL, `QuerySet.update()` and
`bulk_create()`. The other rules, like `save()`, do not see those: they are
for the writes an app makes.

## bounds

The lowest and highest value of a number, date or datetime field:

```yaml
bounds:
  price: {min: 0.01}
  year: {min: 1900, max: 2100}
  expected_close: {min: $today}     # not in the past
  completed_at: {max: $now}         # not in the future
```

A value is checked when it is written new or changed, so a date that has
passed since it was stored does not block an edit of another field. `$now`
forgives a few minutes of clock difference between a browser and the server
(`KARNI_RULES_CLOCK_SKEW`, 300 seconds). A number's bounds are published in
the API schema as `minimum` and `maximum`, and generated demo and test values
stay inside them.

Refusal: `E990`, 400 on the field. Uses: the price of a resource or a
listing, the value of a deal, the quantity of an order, the capacity of a
slot, the year of an indicator, the position of a lesson; dates: a slot
that starts later, a deal that closes later, progress not in the future.

## unique

Fields whose values are unique together among the live rows:

```yaml
unique:
  - [user]                                   # one shop per person
  - [dataset, region, sector, year]
  - {fields: [slot, member], where: {status: {not: cancelled}}}
```

Each entry is a partial unique index over the live rows (and, with `where`,
the rows the filter keeps) that PostgreSQL and SQLite both enforce. A
soft-deleted or cancelled row frees its values. `where` takes fixed values
only. Karni checks it before the write, and the index refuses a duplicate
two requests write at the same moment.

Refusal: `E991`, 400 on the first field (409 from the index under a race).
Adding an entry to an entity that holds rows is a risky change in `karni
plan`: rows that already share the values stop the migration. Uses: one
booking per member and slot, one enrolment per student and course, one
progress row per lesson, a lesson position per course, one shop per person,
an indicator per dataset, place, topic and year.

## targets

The rows a foreign key may point at, as a row filter on the target:

```yaml
targets:
  listing: {active: true, seller__user: {not: $me}}   # on sale, not your own
  slot: {starts_at__gt: $now}                          # not started
  contact: {company: $company}                         # two relations agree
  lesson: {course: $enrolment__course}
```

Checked when the key changes, or a `$<path>` it reads does. Refusal: `E993`,
400 on the field. Uses: an order of an active listing and not one's own, an
enrolment in a published course and not one's own, a booking of a slot that
has not started, a deal's contact of the deal's company, progress on a lesson
of the enrolment's course.

A relation must also point at a row the caller may read, as before: an
unreadable key is refused as if it did not exist. Whether the caller *owns*
the target is the [written-row check](#the-written-row-stays-in-scope) below.

## frozen

Fields that do not change:

```yaml
frozen:
  slot: true                  # set on create, never changed
  value: {stage: won}         # not while the stored row matches
```

Refusal: `E994`, 400 on the field. Uses: a booking's slot (its place was
reserved there), an order's listing and quantity (its amount was computed),
an enrolment's course, a progress row's enrolment and lesson; while a deal is
won, its value and company.

## delete

When a row may be deleted:

```yaml
delete:
  when: {status__in: [pending, cancelled]}           # its state
  blocked_by: [Deal, Contact]                        # children that keep it
# or, counting only some children:
delete: {blocked_by: {Booking: {status: {not: cancelled}}}}
```

Who may delete is `access.delete` (below). Refusal: `E995`, **409**, naming
the related rows and their count. Uses: a company with deals, a contact with
deals, a slot with live bookings, a course with enrolments, a dataset with
indicators, a shop with listings; a paid order.

## moves

What a move into a state needs, and what it stamps:

```yaml
moves:
  lost: {requires: [lost_reason], stamps: [closed_at]}
  won: {stamps: [closed_at]}
  published: {needs: [Lesson]}        # a boolean field becoming true
  done: {stamps: [done_at]}
```

A key is a state of the entity's state field, `<field>:<state>` when two
state fields have it, or a boolean field (the move is to `true`). `requires`
lists fields that must hold a value after the move, `needs` relation
references that must have a live row, and `stamps` date or datetime fields
set to now, unless the same write sets them. A row created directly in the
state counts as a move. The first state of a new row stays the
[lifecycle's](lifecycle-and-capacity.md) rule: a row starts in an initial
state (`E982`), and the schema says which (`x-karni-initial`).

Refusal: `E996`, 400 on the missing field. Uses: a lost deal's reason, the
time a deal closed, an activity was done, a payout was paid; publishing a
course that has a lesson.

## actions

Row actions, `POST <resource>/<id>/<name>/`, with the states they run from,
the state they move to and who may:

```yaml
actions:
  pay: {from: pending, by: "owned:buyer"}
  ship: {from: paid, to: shipped, by: ["owned:listing__seller__user", "role:staff"]}
  refund: {from: paid, to: refunded, by: "role:staff"}
```

`karni build` writes them as the viewset's `row_actions`
([API: row actions](api.md#row-actions-experimental)). An action with `to`
is routed by Karni and moves the row (the fields `moves` requires come from
the request body); one without `to` runs the viewset's own method of that
name, in `<app>/viewsets.py`, after Karni checks the state and `by`. Called
in another state it is refused with **409** (`E997`); an action with `to`
whose row is there already answers 200 and changes nothing, so calling it
twice is safe. The schema lists them as `x-karni-actions`, so a client shows
the right buttons. Uses: pay, cancel, confirm, ship, deliver, refund, mark a
payout paid.

## access: delete, assign, and the read word where

`access` takes two more slots and one more word:

| | Means |
|---|---|
| `delete: <who>` | who deletes which rows (default: `write`). A salesperson marks a deal lost, a manager deletes it |
| `assign: <who>` | who may set the owner field (`owned:<field>` in `write` or `create`) to another user (default: nobody, the owner is the caller). Anyone else who sends another user gets a 403 (`E135`). Staff book for a member, a manager reassigns a deal |
| `where:<field>` | in `read`: the rows whose boolean field is true, for anyone. `where:<field>=<value>` for another value. With `owned:` and `role:` in the same list, drafts stay with their author and staff: `read: [where:published, owned:instructor, role:staff]` |

`owned:<path>` may follow a reverse relation by the entity's name in lower
case: `owned:course__enrolment__student` reads a lesson for the students of
its course.

### The written row stays in scope

A create or an update must leave the row inside its own predicate's rows.
With `write: ["owned:seller__user", "role:staff"]`, a listing posted into
someone else's shop, or moved there, is refused with a 403 (`E134`) and
nothing is saved. This holds for every viewset, from the spec or written by
hand, with no key: it is what `owned:` in `write` and `create` means.

## Escape hatches

- Override `check_rules()` or `check_delete_rules()` on the model to skip or
  add a rule; subclass `class Karni` in `<app>/models.py` to change one
  option (`class Karni(karni.Order.Karni): bounds = {...}`).
- `with karni.rules.unchecked(reason="..."):` skips the rules for data
  loading. The unique index still holds.
- Override `check_written_row()`, `may_assign()` or `run_row_action()` on
  the viewset; define the method of a row action yourself.
- `Seeder.Meta.after` seeds a model after others no foreign key names
  (enrolments after the lessons that publish a course).
- `karni check` reports a declaration that cannot work (`E998`, `E136`), and
  `karni spec validate` the same in karni.yaml (`C760` to `C767`).

## Codes

| Code | When |
|---|---|
| [E990](errors.md#e990) | a value outside its bounds |
| [E991](errors.md#e991) | a duplicate of a `unique` rule |
| [E993](errors.md#e993) | a relation to a row its `targets` filter refuses |
| [E994](errors.md#e994) | a `frozen` field changed |
| [E995](errors.md#e995) | a delete `delete` refuses (409) |
| [E996](errors.md#e996) | a move without what `moves` requires or needs |
| [E997](errors.md#e997) | a row action outside its states (409) |
| [E998](errors.md#e998) | a rule declared wrongly (`karni check`) |
| [E134](errors.md#e134) | a written row outside the caller's write scope (403) |
| [E135](errors.md#e135) | an owner set to someone else without `assign` (403) |
| [E136](errors.md#e136) | a row action with nothing to run (`karni check`) |
| [C760](errors.md#c760) to [C767](errors.md#c767) | `karni spec validate`: bounds, unique, targets, frozen, delete, moves, actions, a row filter |
