---
description: karni queries runs one endpoint in-process as a user and reports every SQL query it ran, groups the repeated ones by the serializer field and relation behind them, and prints the optimiser's reason and the fix.
---

# Find an N+1: `karni queries`

A query budget failure (E117) or the scaling check (E129) tells you an
endpoint repeats a query. `karni queries` tells you which field repeats it,
why the [optimiser](../api.md#query-optimisation) did not fetch it, and the
line to add:

```sh
karni queries /api/events/ --as organizer@example.com
karni queries events                      # a routed resource
karni queries events/<id>                 # its detail route
karni queries EventViewSet.retrieve       # a viewset action (a row the user can read)
karni queries 'events?expand=venue&page=2'
karni queries events --method POST --data '{"title": "Launch"}'   # rolled back
karni queries events --json               # for agents
karni queries events --explain            # each query's plan (EXPLAIN ANALYZE on PostgreSQL)
karni queries events --all                # every statement, not only the repeated ones
```

It runs `manage.py karni_queries` in the project's interpreter, as the other
runners do: one request through the test client, force-authenticated as the
user (`--as` takes an email, a username or a primary key, and without it the
request is anonymous), inside a transaction that is rolled back. The response
cache and the query budget are off for the request, so every statement is
counted. Agents use the MCP tool `queries(endpoint, as_user, method, data,
explain)`, and rule K014 tells them to run it before hunting an N+1 in
serializers.

## What it prints

EventHub with a slow `EventSerializer` added for the demonstration: a
`SerializerMethodField` that reads `obj.venue.city`, another that reads
`obj.organizer.email`, and nested tiers whose `remaining` is
`TicketTier.remaining`, a property that sums bookings:

```text
GET /api/events/ as organizer@example.com → 200 · EventViewSet.list
28 queries: 12 from TicketTier.booking_set (an aggregate per row), 6 from Event.venue not prefetched, 6 from Event.organizer not prefetched
4.1 ms in SQL, budget 8 (20 over)

12× TicketTier.booking_set (an aggregate per row)
  field  EventSerializer.tiers → TicketTierSerializer.remaining
  where  events/models.py:56 in remaining
  why    TicketTierSerializer.remaining is a model property, TicketTier.remaining (events/models.py:52): the optimiser follows relations, not code, so it cannot see what TicketTier.remaining reads (karni/api/optimizer.py).
  fix    no prefetch can serve a per-row aggregate, so annotate it where the TicketTier rows are fetched: prefetch_related = [Prefetch("tickettier_set", queryset=TicketTier.objects.annotate(sum_quantity=Sum("booking__quantity", filter=~Q(booking__status=Booking.Status.CANCELLED))))] on EventViewSet, then render it from that value: a field with source="sum_quantity" (read_only=True), or compute from it what the property returned
  sql    12× SELECT SUM("events_booking"."quantity") AS "total" FROM "events_booking" WHERE ("events_booking"."deleted_at" IS NULL AND "events_booking".…

6× Event.venue not prefetched
  field  EventSerializer.venue_city
  where  events/serializers.py:26 in get_venue_city
  why    EventSerializer.venue_city is a SerializerMethodField (get_venue_city, events/serializers.py:25): the optimiser treats a SerializerMethodField as opaque and cannot see what get_venue_city() reads (karni/api/optimizer.py).
  fix    select_related = ["venue"] on EventViewSet. Or, if get_venue_city() only reads venue.<attr>, declare serializers.CharField(source="venue.<attr>", read_only=True) instead and the optimiser joins venue itself
  sql    6× SELECT … FROM "events_venue" WHERE "events_venue"."id" = %s LIMIT 21

6× Event.organizer not prefetched
  field  EventSerializer.organizer_email
  where  events/serializers.py:29 in get_organizer_email
  why    EventSerializer.organizer_email is a SerializerMethodField (get_organizer_email, events/serializers.py:28): the optimiser treats a SerializerMethodField as opaque and cannot see what get_organizer_email() reads (karni/api/optimizer.py).
  fix    select_related = ["organizer"] on EventViewSet. Or, if get_organizer_email() only reads organizer.<attr>, declare serializers.CharField(source="organizer.<attr>", read_only=True) instead and the optimiser joins organizer itself
  sql    6× SELECT … FROM "karni_accounts_user" WHERE "karni_accounts_user"."id" = %s LIMIT 21

Ran once each (4):
  SELECT … FROM "auth_group" INNER JOIN "karni_accounts_user_groups" ON ("auth_group"."id" = "karni_accounts_us…  ← karni/accounts/permissions.py:74 in user_roles
  SELECT COUNT(*) AS "__count" FROM "events_event" WHERE ("events_event"."deleted_at" IS NULL AND ("events_even…  ← karni/api/viewsets.py:892 in list
  SELECT … FROM "events_event" WHERE ("events_event"."deleted_at" IS NULL AND ("events_event"."status" = %s OR …  ← karni/api/viewsets.py:892 in list
  SELECT … FROM "events_tickettier" INNER JOIN "events_event" ON ("events_tickettier"."event_id" = "events_even…  ← karni/api/viewsets.py:892 in list

note: force-authenticated: a real request also runs its session or token and user lookups (1-2 queries).
```

The headline counts each cause. Every cause then gives the chain of
serializer fields that were rendering, the line that issued the statement,
why the optimiser did not fetch it and the fix. Note what does not appear:
the tiers themselves (`EventSerializer.tiers`) are one prefetch, because the
optimiser derived it from the nested serializer.

## How a query is attributed

Every statement is recorded with the Python stack that issued it
(`karni.api.diagnose.StackRecorder`, built on the recorder behind query
budgets and the dev query log). For each one:

1. **The fields.** Walking the stack outward, every DRF field that was
   rendering (`EventSerializer.tiers`, then `TicketTierSerializer.remaining`)
   and the row it rendered. A many-row serializer's child is resolved to the
   row being rendered. The innermost project frame inside the innermost
   field is the `where`.
2. **The relation.** The statement's table and its `WHERE "table"."column" =
   %s` name the relation from the rendered row: a forward FK when the column
   is the target's primary key (two FKs to one model are told apart by the
   value the row holds), a reverse FK or an M2M otherwise.
3. **The shape.** An aggregate (`SELECT SUM(…)`, `COUNT(*)`), an `EXISTS`, or
   a filtered related manager (conditions besides the relation itself and the
   soft-delete scope) cannot be served by any prefetch. The fix says so and
   gives the annotation or the `Prefetch(…, to_attr=…)` to use instead.
   Simple equality filters are translated into the `Q(...)` to write.
4. **The optimiser's reason.** `karni.api.optimizer` records what its walk
   could not see as **blind spots** (`blind_spots(serializer, model)`):

   | Blind spot | The field |
   |---|---|
   | `method` | a `SerializerMethodField`: the walker cannot see what `get_x()` reads |
   | `property` / `callable` | `source` names a model property or method |
   | `representation` | the serializer overrides `to_representation` |
   | `object` | a field given the whole object (`source="*"`) |
   | `attribute` | any other non-field attribute (a `GenericForeignKey`, an annotation) |

   With no blind spot, the reason is the view: `optimize = False` on the
   viewset (only its hints apply), or a custom action, which is not
   optimised unless it returns `self.paginated_response(qs)` or calls
   `self.optimize_queryset(qs)`. If the optimiser did plan the relation
   (`planned_lookups`), the code re-reads it outside the prefetch. A
   statement issued outside serializer rendering, such as a loop in a view,
   is attributed to its line.

The fix is the declaration that closes the gap:

| Where the field renders | To-one relation | To-many relation |
|---|---|---|
| the top level | `select_related = ["venue"]` on the viewset | `prefetch_related = ["tickettier_set"]` on the viewset |
| below to-one levels only | `select_related = ["writer__publisher"]` on the viewset | `APIMeta.prefetch` on that model, or the full path in `prefetch_related` |
| below a to-many level | `APIMeta.select` on that model, or the full path in `prefetch_related` | `APIMeta.prefetch` on that model, or the full path in `prefetch_related` |

`APIMeta.select` / `APIMeta.prefetch` apply wherever the model is rendered,
at any depth.

For a method field that only reads attributes, the better fix is often a
dotted `source=` (`CharField(source="venue.city")`), which the optimiser
follows by itself.

## Query plans: `--explain`

!!! warning "Experimental"
    The analysis `--explain` runs on PostgreSQL, its findings (`seq_scans`
    in `--json`), `karni.api.explain` and the setting
    `KARNI_EXPLAIN_SEQ_SCAN_ROWS` are [experimental](../stability.md#experimental-names).

On PostgreSQL, `--explain` runs `EXPLAIN (ANALYZE, FORMAT JSON)` of each
distinct `SELECT` the endpoint ran, each in a savepoint inside the request's
transaction, which is rolled back: `ANALYZE` runs the query, and nothing it
does stays. Each plan prints with the actual rows, loops and time of every
node. Each sequential scan on a table of `KARNI_EXPLAIN_SEQ_SCAN_ROWS` rows
or more (default 1000) is a [W611](../errors.md#w611) finding that names the
index that would serve its filter or its sort, as the line to add to the
model's `Meta.indexes`:

```text
EXPLAIN SELECT … FROM "events_event" WHERE ("events_event"."deleted_at" IS NULL AND UPPER("events_event"."title"::…
  Limit (actual rows=50 loops=1 time=1.500ms)
    Sort (actual rows=50 loops=1 time=1.497ms)
      Sort Key: created_at DESC
      Seq Scan on events_event (actual rows=111 loops=1 time=1.477ms)
        Filter: ((deleted_at IS NULL) AND (upper((title)::text) ~~ '%GALA%'::text))
        Rows Removed by Filter: 4889
  Execution Time: 1.512ms

Sequential scans on large tables (1):
  W611 Seq Scan on events_event (5,000 rows, 5,000 read, 111 kept) for ((deleted_at IS NULL) AND (upper((title)::text) ~~ '%GALA%'::text)): add GinIndex(OpClass(Upper("title"), name="gin_trgm_ops"), name="event_title_trgm_idx", condition=Q(deleted_at__isnull=True)) to Event.Meta.indexes (GinIndex and OpClass come from django.contrib.postgres, Upper from django.db.models.functions, and the index needs the pg_trgm extension)
```

The suggestion puts the equality columns of the filter first, then one range
column. Without either, a `LIKE` (a search, `icontains`) asks for a trigram
index, and a sort asks for an index on its keys. The soft-delete filter
becomes the index's `condition`. When the filter keeps most of the rows it
reads, the finding says an index would not help: narrow the filter or
paginate. When an index on the column exists and the planner read the table
anyway, it says to run `ANALYZE` on the table.

Only PostgreSQL has a plan Karni reads. On another database `--explain`
keeps its plain `EXPLAIN` of the three slowest statements and says so
([W610](../errors.md#w610)). Run it against PostgreSQL with data at volume
([`karni seed --volume`](../seeding.md#volume-seeding)) to see where an index
is missing.

## Notes

- **Development only.** It runs your view against your database. Writes are
  rolled back and `on_commit` callbacks never fire, but other side effects of
  a write view (an HTTP call, a file written) are real.
- **Force-authenticated.** A real request also runs its session or token
  lookup and user lookup (1 or 2 queries). The report says so.
- **A refused request** (401, 403, 404) runs the access check's queries, not
  the response's. The note points at `karni why`.
- **A view that raises** gives E943 with the traceback and what
  [`karni explain -`](explain.md) recognises in it.
- **The budget** shown is the action's (`query_budget` on the viewset, else
  `KARNI_QUERY_BUDGET`). See [query budgets](../api.md#query-budgets).

## JSON

`--json` returns `request`, `status`, `view` (`EventViewSet.list`), `budget`,
`queries`, `time_ms`, `repeated`, `headline`, `causes` (each with `count`,
`summary`, `field`, `chain`, `relation`, `kind`, `why`, `fix`, `where` and
`statements`), `once` (the statements that ran once, with their origin) and
`notes`. `--explain` adds `explain` (each statement with its plan) and
`seq_scans` (each finding with `code`, `table`, `model`, `rows`, `scanned`,
`kept`, `filter`, `sort`, `index`, `why` and `sql`), and `--all` adds
`statements` (every statement with its time and origin).

## Errors

| Code | When |
|---|---|
| [E940](../errors.md#e940) | the endpoint resolves to no URL (the message lists the routed resources or viewsets) |
| [E941](../errors.md#e941) | `--as` matches no single user (the message shows a few) |
| [E942](../errors.md#e942) | `--method` is not one the view answers there, or `--data` is not JSON |
| [E943](../errors.md#e943) | the view raised, and the traceback and its explanation follow |
| [C341](../errors.md#c341) | the project's karni predates `karni_queries` |

The Python API is `karni.api.diagnose.run(endpoint, user=…, method=…,
data=…, explain=…)`, which returns a `Report` (`.render()`, `.as_dict()`).
