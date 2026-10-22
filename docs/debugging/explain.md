---
description: karni explain - names the Karni failure in a pasted traceback, test failure or log line, with its cause, the file and line it happened at, the fix and the docs link, and says plainly when it does not know the failure.
---

# Explain a traceback: `karni explain -`

The expensive part of debugging is rebuilding context from a 60-line
traceback: which frame is yours, which line is the cause, what the framework
expected. `karni explain -` does that step. Paste a traceback, a test failure
or a log line into it, and it answers with the failure class, the specific
cause, the first project frame (`file:line`), the fix and the docs link:

```sh
karni explain - < traceback.txt
pbpaste | karni explain -
python manage.py migrate 2>&1 | karni explain -
karni explain "django.db.utils.OperationalError: no such table: shop_order"
karni explain - --json        # for agents
```

With no code and stdin not a terminal, `karni explain` reads stdin too. An
argument that cannot be a code (it has a space or a colon) is read as a log
line. `karni explain E104` still explains a code. Agents use the MCP tool
`explain_text(text)` (see [agents](../agents.md#mcp)), and rule K013 tells
them to run it before reading a traceback by hand.

It needs neither Django nor a project. The catalogue is
`karni.errorcodes.failures`, standard library only, and karni-cli carries a
copy. Inside a project, frames under the project root count as project frames
and are shown relative to the root.

## What it prints

A real `manage.py check` traceback, from an `Owned("organiser")` typo in
EventHub's `events/viewsets.py`:

```text
Class: E104  Owned() does not name a path to the user
Cause: EventViewSet: Owned('organiser') does not lead from Event to the user model (Event has no field 'organiser'). Name a relation path ending at the user, e.g. Owned("organizer") or Owned("event__organizer").
Where: events/viewsets.py:26 in <module>
Why:   Owned('path') filters rows to those whose path leads to request.user, and stamps the owner on create; a path that does not end at the user model would match nothing or the wrong rows.
Fix:   Name the owner relation as a string, following relations with __ and ending at the user model: Owned('organizer') or Owned('event__organizer').
Docs:  https://cbsshekhawat18-lab.github.io/karni/errors/#e104
```

| Line | What it is |
|---|---|
| `Class` | the failure class: a registered code and its title, an agent rule, or a class from the catalogue below |
| `Cause` | the specific cause, read from your text (your class, field, table, host) |
| `Where` | the innermost project frame (`file:line in function`); for a query report, the line that issued the repeated query |
| `Why` | why Karni behaves this way (from the code's registry entry) |
| `Fix` | the fix |
| `Next` | the command that answers the rest: `karni queries …` for a query count, `karni why …` for an access outcome |
| `Docs` | the code's entry in [errors](../errors.md), or the class's section below |

A pytest run whose request went over its query budget hands over to
[`karni queries`](queries.md), which names the cause and the hint:

```text
Class: E117  A request ran more SQL queries than its budget
Cause: EventViewSet.list ran 9 queries; budget is 8. Repeated: 5× events_venue from EventSerializer.venue_city (events/serializers.py:25 in get_venue_city).
Where: events/serializers.py:25 in get_venue_city
Why:   Repeated statements are almost always an N+1: a relation loaded once per row. Budgets turn that into a failing test instead of a slow production page.
Fix:   Run the `karni queries` command below: it attributes every repeated query to the serializer field, method or property that issued it and prints the exact hint (select_related / prefetch_related on the viewset, APIMeta.select / prefetch on the model, or an annotation for an aggregate). Raise the budget only for work that is real: query_budget = Budget(<action>=N, reason=...).
Next:  karni queries EventViewSet.list --as <user>
Docs:  https://cbsshekhawat18-lab.github.io/karni/errors/#e117
```

## When it does not know

It never guesses. Text that no pattern recognises gets the exception line,
the innermost project frame and the generic next step:

```text
Not a failure Karni recognises: ZeroDivisionError: division by zero
Where: events/serializers.py:33 in get_capacity_ratio
Next:  Karni does not know this failure, so it will not guess. Read the innermost project frame (Where) and the exception's own message; `karni doctor` checks the environment and `karni check` the declarations.
```

A log line printed beside a traceback, such as the dev query log, does not
explain the traceback. It is listed under `Also in the text:`.

## The catalogue

Patterns are tried most specific first, and every match is reported (five at
most). The patterns that identify a failure:

1. **A registered code in the text**: `E104: …`, `(karni.E101)` from a system
   check, `error: C012: …` from the CLI, `PAY004: …` from a module, or a
   `…/errors/#e117` link. The answer is the code's entry, with your message
   as the cause. The query budget codes (E117, E129) also list the repeated
   statements and the `karni queries` command.
2. **An agent rule or a lint id**: `K101 [model-base]` (`karni rules
   --check`), `[model-base] path:12:` (`karni check`), `karni/no-raw-elements`
   (ESLint). The answer is the rule.
3. **A Karni exception class without its code**, such as
   `QueryBudgetExceeded: …` from an older release.
4. **Query counts**, **CSRF and CORS**, **access outcomes** and
   **framework-adjacent failures**, the classes below.

A summary code (`E702` "karni check found violations", `C009` "a command in
the project failed") is listed after the failures it summarises.

### Query counts

<a id="query-count"></a>

#### A query-count assertion failed

Django's `assertNumQueries` (`AssertionError: 9 != 4 : 9 queries executed, 4
expected`) or pytest-django's `django_assert_num_queries` (`Expected to
perform 4 queries but 9 were done`). The cause groups the captured queries
by statement (`5× events_venue`). Fix: run `karni queries` on the endpoint
the test requests.

<a id="query-budget-warning"></a>

#### The dev server's query-budget warning

`EventViewSet.list ran 28 queries; budget is 8.`, logged in warn mode (the
dev profile) without a code. It is E117. The answer lists the repeated
statements with the field that issued each and hands over to `karni queries
EventViewSet.list`.

<a id="query-log-duplicates"></a>

#### Repeated statements in the dev query log

`GET /api/events/ 200 — 30 queries, 24 duplicated …` from
`karni.middleware.QueryLogMiddleware`. Fix: `karni queries /api/events/`.

### CSRF and CORS

<a id="csrf"></a>

#### A CSRF refusal (session mode)

`CSRF Failed: CSRF token missing.`, `Forbidden (CSRF cookie not set.)` or
`CSRF Failed: Origin checking failed - http://localhost:3000 does not match
any trusted origins.` In session mode every unsafe request needs the
`csrftoken` cookie and the same value in `X-CSRFToken`, from an origin in
`CSRF_TRUSTED_ORIGINS`, which Karni derives from `KARNI_FRONTEND_URL` (see
[session mode](../accounts.md#session-mode)). The fix names your origin:
set `KARNI_FRONTEND_URL` to it, serve the SPA from that origin, or let
`KarniClient` bootstrap the cookie.

<a id="cors"></a>

#### The browser blocked a cross-origin call

Chromium's `has been blocked by CORS policy: No 'Access-Control-Allow-Origin'
header is present`, or Firefox's `Cross-Origin Request Blocked`. The dev
profile allows every origin. Outside dev, CORS is closed unless
`CORS_ALLOWED_ORIGINS` lists the origin. Fix: list the SPA's origin there, or
serve the SPA and the API from one origin.

### Access outcomes

Each one hands over to `karni why`, which evaluates the access rule for the
user and row.

<a id="access-404"></a>

#### 404 from a Karni viewset

`No Event matches the given query. Rows are limited by EventViewSet.access
read=…`. A row outside the requester's read scope answers 404, exactly like a
row that does not exist. The cause quotes the read rule.

<a id="access-403"></a>

#### 403 from a Karni viewset

`Access denied: this row is readable but the action requires Owned('organizer')
| HasRole('staff').` The user can read the row; the write rule refuses the
action.

<a id="access-unauthenticated"></a>

#### A request without credentials

`Authentication credentials were not provided.` (401 in jwt mode, 403 in
session mode). Fix: sign in first (`KarniClient` keeps the session or the
tokens), or authenticate the test client.

<a id="access-denied"></a>

#### 403 from a viewset's access rule

DRF's `You do not have permission to perform this action.` from a viewset.

<a id="access-401"></a>

#### A 401, 403 or 404 in the dev server's log

`Not Found: /api/…`, `Forbidden: /api/…` or the access log line, without a
body to say more. From a Karni viewset, a 404 can also mean a row outside the
read scope. `karni routes` lists every route.

### Database and migrations

<a id="db-driver"></a>

#### The database driver is not installed (C012)

`ImproperlyConfigured: Error loading psycopg2 or psycopg module`, or `No
module named 'psycopg'`. Fix: `pip install "psycopg[binary]"` into the
project interpreter, run in Docker, or use SQLite.

<a id="db-unreachable"></a>

#### The database cannot be reached (C013)

`OperationalError: connection failed: connection to server at "127.0.0.1",
port 5432 failed: Connection refused`, `failed to resolve host 'db'`,
`password authentication failed`. The cause quotes the driver's error and
points out the compose-only host `db`. Fix: start the database (`karni serve
-d`), or point `DATABASE_URL` at one that runs.

<a id="migrations-not-applied"></a>

#### A table is missing, or migrations are not applied

`no such table: events_event` (SQLite), `relation "events_event" does not
exist` (PostgreSQL), or runserver's `You have 1 unapplied migration(s)`. Fix:
`karni migrate`, after `karni make migration` when the model has none.

<a id="migration-missing"></a>

#### A model change has no migration

`no such column: events_event.subtitle`, `column … does not exist`, or
`makemigrations --check` listing `Migrations for 'events':`. Fix: `karni make
migration && karni migrate`, then `karni types` (rule K003).

### Settings and services

<a id="settings-not-configured"></a>

#### Django code ran before the settings were loaded

`Requested setting INSTALLED_APPS, but settings are not configured` or `Apps
aren't loaded yet`. Fix: run it through `karni shell` or a management
command, or set `DJANGO_SETTINGS_MODULE` and call `django.setup()` first.
Karni's own settings validation fails with E504, a registered code.

<a id="env-missing"></a>

#### An environment variable is not set

`Set the SECRET_KEY environment variable` (django-environ). Fix: `cp
.env.example .env` and set it.

<a id="disallowed-host"></a>

#### The host is not in ALLOWED_HOSTS

`Invalid HTTP_HOST header: 'evil.example'. You may need to add 'evil.example'
to ALLOWED_HOSTS.` Fix: add it to `ALLOWED_HOSTS` in `.env`.

<a id="redis-unreachable"></a>

#### Redis is not reachable

`redis.exceptions.ConnectionError: Error 61 connecting to 127.0.0.1:6379.
Connection refused.` The default cache (throttle counters, the response
cache) and the Celery broker are Redis. Fix: start it (`karni serve -d`), or
for a host run without Redis set `KARNI_CACHE=locmem` and run Celery tasks
eagerly.

### The OpenAPI schema

<a id="schema-method-type"></a>

#### A SerializerMethodField has no return type

`Warning [EventViewSet > EventSerializer]: unable to resolve type hint for
function "get_organizer_email"` from `manage.py spectacular`. The field is
documented as a string, and [`karni types`](../cli.md#karni-types) generates
the wrong TypeScript type from it. Fix: annotate the method's return type, or
use `@extend_schema_field`.

<a id="schema-warning"></a>

#### Another schema warning on a viewset

Any other `Warning [<View> > <Serializer>]: …` or `Error [<View>]: …` from
drf-spectacular, with the message as the cause.

## JSON

`--json` (and nothing else on stdout) for agents:

```json
{
  "recognised": true,
  "exception": "karni.performance.QueryBudgetExceeded: E117: EventViewSet.list ran 28 queries; budget is 8.",
  "where": "events/tests/test_scratch_listing.py:19",
  "raised_in": "karni/api/viewsets.py:870",
  "findings": [
    {
      "class": "code-e117",
      "code": "E117",
      "title": "A request ran more SQL queries than its budget",
      "cause": "EventViewSet.list ran 28 queries; budget is 8. Repeated: 12× events_venue from EventSerializer.venue_city (events/serializers.py:25 in get_venue_city); 12× events_booking from TicketTierSerializer.remaining (events/models.py:56 in remaining).",
      "where": "events/serializers.py:25 in get_venue_city",
      "fix": "Run the `karni queries` command below: …",
      "next": "karni queries EventViewSet.list --as <user>",
      "why": "Repeated statements are almost always an N+1: …",
      "docs": "https://cbsshekhawat18-lab.github.io/karni/errors/#e117"
    }
  ],
  "also": [],
  "next": ""
}
```

`recognised` is `false` (and `findings` empty) for a failure Karni does not
know. `next` then holds the generic next step.

## Extending the catalogue

`karni.errorcodes.failures.diagnose(text, patterns=…)` takes the catalogue as
an argument. A pattern is any callable `(Text, context) -> list[Finding]`.
Extend `PATTERNS` to add a class, for example in your own tooling.
`lookup=` (code to entry) and `rules=` (the agent rules) are the other two
escape hatches. A new class in Karni comes with a real captured failure as
its test fixture (`packages/karni/tests/debugging/fixtures/`), an anchor on
this page and an entry in `CLASSES`.
