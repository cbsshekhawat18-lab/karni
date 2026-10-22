---
description: karni why explains why a row, field or action is refused or missing for a user, computed by the same code that enforces the decision, with file:line and one concrete fix.
---

# Why is it missing? `karni why`

Permission and scope bugs are the hardest to debug because nothing fails: the
row is just absent, the list is empty, the field is not in the response.
Reconstructing the decision means reading the viewset's `access`, the role
grants in `KARNI_ROLES`, the model's `class Karni`, the vetoes and the row
itself. `karni why` does that in one call, and computes the answer with the
code that enforces it.

```sh
karni why events/<id> --as alice@example.com                 # can alice see this row?
karni why events/<id> --as alice@example.com --action update # ...change it? (delete, an @action)
karni why events.internal_note --as alice@example.com        # a field hidden or read-only
karni why-empty events --as alice@example.com                # why is her list empty?
karni why 403 <request-id>                                   # a request the dev server recorded
```

`--as` takes an email, username, primary key or `anonymous`. Resources are
named as the API names them: the route prefix (`events`), the router basename
(`events-event`) or the model label (`events.Event`). `--action` takes `view`
(the default), `update`, `delete`, `create`, `list` or an `@action` name.
`--param key=value` adds a query parameter (a page's `params={...}`, a filter).
`--json` prints the same verdict as one JSON object.

## Reading the answer

An organizer opens another organizer's draft event in
[EventHub](https://github.com/cbsshekhawat18-lab/karni/tree/main/examples/eventhub) and gets a 404:

```text
$ karni why events/ff9ab5c2-9f04-4aed-b552-332702627f73 --as organizer2@example.com
user     organizer2@example.com  (pk 32e70629-8fad-41a6-86cb-0fb39a1de644)
roles    organizer
request  GET /api/events/ff9ab5c2-9f04-4aed-b552-332702627f73/ → EventViewSet.retrieve (access.read)
access   EventViewSet.access  events/viewsets.py:28
           read   = Where(<lambda>) | Owned('organizer') | HasRole('staff')
           write  = Owned('organizer') | HasRole('staff')
           create = HasRole('organizer', 'staff')
gate     passed: Where(<lambda>) | Owned('organizer') | HasRole('staff')
           yes  Where(<lambda>): returns a row filter, so the gate passes and the rows decide
           yes  Owned('organizer'): signed in (the row decides)
           no   HasRole('staff'): needs one of staff; holds organizer
grants   not consulted: this access names no Granted()/Can(), so KARNI_ROLES grants do not apply here (roles count only through HasRole)
read     access.read = Where(<lambda>) | Owned('organizer') | HasRole('staff')
           no   Where(<lambda>): status = 'published'; row has status='draft'
           no   Owned('organizer'): organizer = you; row has organizer=organizer@example.com
           no   HasRole('staff'): no row (role not held)
row      Event ff9ab5c2-9f04-4aed-b552-332702627f73  status='draft'  organizer=organizer@example.com
where    events/viewsets.py:28  EventViewSet.access
         events/viewsets.py:16  Where(<lambda>)
         karni/api/access.py:340  Owned('organizer')
         karni/api/access.py:444  HasRole('staff')
         karni/api/viewsets.py:490  BaseViewSet.read_scope (the filter)
result   404 Not Found — the row exists but access.read filters it out at queryset level (BaseViewSet.get_queryset): the API answers 404, never 403, so it does not confirm the row exists
fix      the row must match status = 'published' (events/viewsets.py:16); it has status='draft'
         or: make organizer2@example.com the row's organizer (now organizer@example.com)
```

| Label | What it says |
|---|---|
| `user`, `roles` | Who is asking, and the roles (Django groups) they hold. A superuser holds every grant at scope `all`. |
| `request` | The method, path and viewset action, and which part of `access` governs it. |
| `access` | The declaration and its `file:line`. For `Granted()`, also the permission it binds to (`Can('events.event:view')`). An `@action(access=...)` or an overridden `get_access()` is shown too. |
| `gate` | The request gate (`AccessPermission.has_permission`), part by part: who passes and why. |
| `veto` | A [veto](../api.md#vetoes) that refused after the gate passed, with its name and `file:line`. |
| `grants` | For `Granted()`/`Can()`: each grant consulted, its scope, the role that gives it and where (`KARNI_ROLES` and its line, the permission matrix, superuser), and the rows it reaches. |
| `read`, `write` | The row filter, part by part, for this row: `yes`/`no`, what the part needs, what the row has. |
| `row` | The row's values for the fields the predicates read. Sensitive fields are redacted with the [change history's rules](../change-history.md) (`Karni.sensitive`, `KARNI_AUDIT_REDACT`). |
| `steps` | `why-empty` only: the rows each step of the read pipeline leaves. |
| `where` | `file:line` of the declaration, of each deciding predicate (a `Where` function's own line) and of the enforcement point. |
| `result` | The status the API answers and the decision, in one line. |
| `fix` | One concrete change, or two alternatives. |
| `note` | Anything the verdict must not hide, such as a replay that no longer gets the recorded answer. |

The cases it tells apart: a row filtered out by the read scope (404), a
request refused at the gate (no grant for the action, a role not held, not
signed in: 401 or 403), a veto (403), a write refused on a readable row (403),
a row that does not exist, a soft-deleted row (hidden by the `soft_delete`
model scope, which no access rule can lift), a row the viewset's own
`queryset`/`get_queryset()` leaves out, a `filter_queryset_for_user` override,
the request's filters, a `permission_classes` entry ANDed after the gate, and
an `Unscoped` viewset.

A write refused on a readable row:

```text
$ karni why events/877409a9-77d2-4e02-bf01-cf99988c24c9 --as attendee@example.com --action update
...
read     access.read = Where(<lambda>) | Owned('organizer') | HasRole('staff')
           yes  Where(<lambda>): status = 'published'; row has status='published'
           no   Owned('organizer'): organizer = you; row has organizer=organizer@example.com
           no   HasRole('staff'): no row (role not held)
write    access.write = Owned('organizer') | HasRole('staff')
           no   Owned('organizer'): organizer = you; row has organizer=organizer@example.com
           no   HasRole('staff'): no row (role not held)
...
result   403 Forbidden — the row is readable (found through access.read) but access.write refuses it (AccessPermission.has_object_permission)
fix      make attendee@example.com the row's organizer (now organizer@example.com)
         or: give attendee@example.com the role 'staff': assign_role(user, 'staff') or the admin
```

A grant scope, under `access = Granted()`, from Karni's own test app. In a
project, `KARNI_ROLES` is followed by the settings line that declares the
role:

```text
access   GrantedEvents.access  tests/why/routes.py:51
           read   = Granted()  (binds to Can('testapp.event:view'))
           write  = Granted()  (binds to testapp.event:change / :delete, or a declared @action's own)
           create = Granted()  (binds to Can('testapp.event:add'))
gate     passed: Can('testapp.event:view')
           yes  Can('testapp.event:view'): holds testapp.event:view through role 'organizer' (scope own)
grants   testapp.event:view  scope own  (role 'organizer', KARNI_ROLES)  → organizer = you
read     access.read = Can('testapp.event:view')
           no   Can('testapp.event:view'): organizer = you; row has organizer=bob@example.com
...
fix      make alice@example.com the row's organizer (now bob@example.com) — the 'own' scope
         or: grant role 'organizer' 'testapp.event:view' at scope 'all' in KARNI_ROLES
```

## Empty lists: `karni why-empty`

`why-empty` counts the rows each step of the [read pipeline](../api.md#access-control)
leaves: the table, each model scope, the viewset's queryset, `access.read`
part by part, `filter_queryset_for_user` and each filter backend with the
request's parameters. Then it names the step that empties the list:

```text
$ karni why-empty bookings --as organizer@example.com
...
steps    rows  removed  step
           10           table events_booking  [every row, soft-deleted included]
           10           model scope soft_delete  (karni/scopes.py:154)
           10           BookingViewSet base queryset  [Booking._default_manager.all(): no queryset or get_queryset() declared]
            0      -10  access.read = Owned('attendee') | Owned('event__created_by') | HasRole('staff')  (events/viewsets.py:80)
                             0 rows: Owned('attendee'): attendee = you
                             0 rows: Owned('event__created_by'): event__created_by = you
                             0 rows: HasRole('staff'): no row (role not held)
            0           KarniFilterBackend  [no parameters]
            0           KarniOrderingFilter  [no parameters]
            0           KarniSearchFilter  [no parameters]
near     Owned('event__organizer') would match 10 row(s) where Owned('event__created_by') matches none — EventViewSet.access owns Event through organizer
...
result   empty: access.read removes all 10 row(s) the viewset's queryset holds — none is readable by organizer@example.com
fix      change Owned('event__created_by') to Owned('event__organizer') in BookingViewSet.access.read (events/viewsets.py:80)
         or: rows appear once organizer@example.com is the attendee of some Booking
```

`near` lists, for each `Owned(...)` part that matches no row, the other
foreign keys to the user on the same model that do. The ones a routed
viewset (or `Karni.owner_field`) owns that model through come first. Here the rule walks
to `created_by`, the audit stamp, while the events belong to their
`organizer`. The list is in `--json` as `near_misses`, and it is printed even
when the list is not empty, for a list that is merely missing rows.

With `--param status=draft` the same command names the filter instead:
`empty: the request's parameters (status=draft) match none of the 5 readable
row(s) (KarniFilterBackend)`. A list refused at the gate is reported as a
refusal, not as an empty list.

## Fields

`karni why <resource>.<field>` says whether the user sees the field and may
change it, and why. The reason is one of [`Karni.field_roles`](../api.md#field-visibility),
`APIMeta.exclude`/`fields`/`read_only`/`write_only`, an owner field stamped
from the request, the always-read-only key and timestamps, or an explicit
`serializer_class`:

```text
$ karni why venues.capacity --as attendee@example.com
user     attendee@example.com  (pk 01a9e71f-de8a-474b-8f36-d58b47378190)
roles    attendee
access   VenueViewSet.access  events/viewsets.py:22
           ...
field    Venue.capacity on venues (VenueViewSet, the generated serializer)
rows     list: 200 OK; update: gate refuses (403 Forbidden)
rule     Venue.Karni.field_roles['capacity']: read needs one of organizer, staff; attendee@example.com holds attendee
where    events/viewsets.py:22  VenueViewSet.access
         events/models.py:19  Venue.Karni.field_roles
result   hidden — capacity is absent from every response, ?expand= and the schema for this user (never null), and is ignored in filters, ordering and search
fix      give attendee@example.com one of the roles organizer, staff
         or: add a role attendee@example.com holds to field_roles['capacity']['read'] in Venue.Karni (events/models.py:19)
```

## Recorded requests: `karni why 403 <request-id>`

While `DEBUG` is on, the dev server records each request as
`.karni/requests/<request id>.json` under the project root: method, path,
query, the user, the view and action, and the status. `karni why <status>
<request-id>` reads that record and replays its access decision now, for the
same user, method, path and query:

```text
record   7f3c2a9e4b1d at 2026-10-21T10:41:07+00:00: PATCH /api/events/877409a9-.../ → 403 Forbidden
         replayed now with the same user, method, path and query: 403 Forbidden (the same answer)
user     attendee@example.com  ...
```

When the answer differs from the recorded one, a `note` says so: roles,
grants or the row changed since, or the refusal depended on request state a
replay does not have. For example, a request refused while impersonating
(`IMP006`) is not impersonated when replayed. No record ([`E903`](../errors.md#e903))
means the request was not made against the dev server with `DEBUG` on. Reproduce it
there, or ask about the row directly with `karni why <resource>/<id> --as
<user>`.

## For agents

`--json` prints the verdict as one object: `outcome` (`filtered`, `gate`,
`unauthenticated`, `veto`, `write-refused`, `missing`, `model-scope`,
`allowed`, `hidden`, `read-only`, `empty`, ...), `status`, `summary`, `user`,
`roles`, `request`, `access`, `gate`, `grants`, `read`, `write`, `row`,
`steps`, `field`, `where` (each with `file`, `line` and the absolute `path`)
and at most two `fix` strings.

[`karni mcp`](../agents.md#mcp) serves the same as two tools, `why(target,
user, action, method, params, as_json)` and `why_empty(resource, user, params,
as_json)`, and rule `K015` tells an agent to ask `karni why` before reading
the access layer when a row, field or action is unexpectedly missing or
refused.

## How it stays honest

`karni why` never re-implements the rules beside them:

- **The decision is the API's.** It builds the viewset the way the router
  does (same class, initkwargs and method map), wraps a request for the user
  as DRF's test client does, and runs DRF's own `initial()` (authentication,
  then `check_permissions` with `AccessPermission` first) and the action's
  lookup (`get_object()`, or `filter_queryset(get_queryset())` for a list).
  Exceptions go through the view's own `handle_exception`, so 401 versus 403
  is the API's answer too. The handler body never runs, nothing is written
  (everything happens in a transaction that is rolled back), and no rate
  limit is used up.
- **The explanation is the enforcement, part by part.** While the probe runs,
  the access layer records each decision it makes (`karni.api.access.trace`).
  `karni why` takes each recorded predicate apart with `Predicate.explain()`,
  which evaluates every leaf with the leaf's own `allows()`/`rows()` and
  recombines them with the same folds `|` and `&` use, then applies each
  leaf's row filter to the row with the read pipeline's `apply_rows`. If an
  explanation ever disagreed with the recorded decision (a `Where` reading
  the clock), a `note` would say so. The status shown is always the API's.
- **A test matrix proves it.** `packages/karni/tests/why/test_matrix.py`
  compares the verdict with what the API actually returns (the router's own
  view, dispatched for real) for every combination of eight users (anonymous,
  owners, staff, a reader, a `related:` scope, no role, a superuser), four
  viewsets (`Granted()`, a hand-written rule with an `@action(access=...)`, a
  veto, `Unscoped`), six rows (one soft-deleted) and every action: status,
  list membership and count, and field presence and writability.

## Limits

- It explains Karni's access layer on `BaseViewSet` routes. A plain DRF view
  or an `Unscoped` viewset is decided by its `permission_classes`: `karni
  why` names the one that refused, nothing more ([`E907`](../errors.md#e907)).
- An `@action`'s own code, and validation of the body (a 400), are not access
  decisions and do not run.
- `--as` loads the user from the database. A `related:<key>` scope reads
  `user.<key>`. An attribute that only middleware sets on the request's user
  is absent, and the verdict says the scope reaches no row.
- Like the rest of the dev tooling, it reads the database it is pointed at.
  Run it against development data.

Errors: `E901` to `E908` (core) and `C310` to `C312` (the command), all in
[error codes](../errors.md).
