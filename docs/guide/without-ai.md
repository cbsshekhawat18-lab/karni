---
description: "The same Karni project built from the terminal without an agent: the karni commands that replace boilerplate and the domain code you write yourself."
---

# Building without an AI agent

Karni is a framework you drive from a terminal, like Django or Laravel. Every
repeated piece of a web app is a command, so a project is a sequence of
`karni` calls plus the domain code only you can write. This is the same
project as [Building with an AI agent](with-ai.md), by hand.

## The commands

| Need | Command |
|---|---|
| A project | `karni new "Ticket Shop"` |
| A Django app | `karni make app events` |
| A model (+ viewset, pages, test) | `karni make model Event title:str:200 … -a --access owned:organizer` |
| An API resource for an existing model | `karni make viewset Event --access public-read --search title` |
| A migration | `karni make migration --app events` then `karni migrate` |
| A frontend page | `karni make page events --resource events`, `--kind detail`, `--kind form`, `--kind login` |
| A component | `karni make component StatusBadge` |
| A background task | `karni make task send_digest --retry 3` |
| A schedule | `karni make schedule nightly_report --every 1d --task events.tasks.send_digest` |
| An event and a listener | `karni make event order_shipped`, `karni make listener notify --on Event.created --queued` |
| A management command | `karni make command send_reminders` |
| A service (the only place for HTTP clients) | `karni make service stripe_client` |
| Middleware | `karni make middleware RequestTiming` |
| A test, factory or seeder | `karni make test Event`, `karni make factory Event`, `karni make seeder Event` |
| An optional module | `karni add payments` |
| A reusable module of your own | `karni make module live-chat` |

Runners: `karni serve` (`--local` for a host run), `karni migrate`,
`karni test`, `karni shell`, `karni routes`, `karni worker`, `karni beat`,
`karni schedule list|run`, `karni seed`, `karni createsuperuser`,
`karni manage <any django command>`. All of them run through the project's
`.venv` or its docker compose stack, whichever exists.

Every command has `--help` and `--dry-run` (generators print the diff and
write nothing). The full reference is [The karni command](../cli.md).

## A project, by hand

```sh
pip install karni karni-cli
karni new "Ticket Shop" && cd ticket_shop
cp .env.example .env            # PostgreSQL by default. sqlite:///data/db.sqlite3 for a no-Docker start
karni make app events
karni make model Venue name:str:200 city:str:100 capacity:int --with viewset,test --access public-read
karni make model Event title:str:200 description:text starts_at:datetime ends_at:datetime \
    "status:choice:draft|published" organizer:fk:User venue:fk:Venue -a --access owned:organizer
karni make migration --app events && karni migrate
karni seed
karni test
karni serve --local             # http://127.0.0.1:8000, /admin, /api/docs
(cd frontend && npm install && npm run dev)   # http://localhost:5173
```

What you wrote: nothing yet. What you have: two models, two routed API
resources with filtering, search and pagination, admin pages, list/detail/form
screens, seed data and a test file per resource.

## Where your code goes

| Kind of code | Where | Example |
|---|---|---|
| Fields and invariants | `events/models.py` | `Booking.clean()` for a capacity rule |
| Who may read and write | the `access` on the viewset | `Access(read=Public(), write=Owned("organizer"))` |
| Custom API operations | `@action` methods on the viewset | a `pay` action calling a service |
| Reactions to data changes | `events/listeners.py` | `@on_updated(Booking, queued=True)` |
| Periodic work | `events/schedules.py` | `every("1d", send_digest)` |
| External services | `events/services/` | the only place for HTTP clients |
| Screens | `frontend/src/pages/` | compose `ResourceTable`, `ResourceForm`, `ResourceDetail` |
| Demo data | `events/seeds.py` | field overrides and `seed()` |
| Tests | `events/tests/` | `assert_crud`, `assert_isolated`, plus your flows |

The architecture rules (`karni rules`) say where things go.
`karni rules --check <file>` says when something is in the wrong place, and
`karni check` runs all of it before a commit.

## Reading an error

Every error Karni raises starts with a code and ends with a link:

```text
E104: EventViewSet: Owned('organiser') does not lead from Event to the user model
(Event has no field 'organiser'). Name a relation path ending at the user, e.g.
Owned("organizer") or Owned("event__organizer"). See …/errors/#e104
```

`karni explain E104` prints the same entry in the terminal, with why Karni
objects and the general fix. [Error codes](../errors.md) lists them all.

## Upgrading

Karni is a dependency. Run `pip install -U karni karni-cli`, then
`karni upgrade --dry-run` shows every change between your version and the new
one as a diff. `karni upgrade` applies the mechanical ones and lists the rest
with a link to its migration note. See the [stability promise](../stability.md).
