# EventHub — the Karni reference application

An event ticketing platform built with nothing but Karni's documented surface:
organizers create events with venues, ticket tiers, capacity and cover images;
attendees browse, search, book and pay; organizers get a dashboard with
bookings, revenue and an attendee export; the admin covers everything; a
confirmation email goes out through Celery; four roles (anonymous, attendee,
organizer, staff) decide who sees what.

It lives in the Karni repository and runs in CI, so a framework change that
breaks a real app breaks the build. Read it instead of the reference docs:
each section below names the Karni feature and the file that uses it.

**Project code: 597 lines** (models 81, viewsets 86, pages 291, other 139),
measured with `python scripts/loc.py --pristine <karni new output>` —
non-blank, non-comment lines of everything EventHub wrote, excluding tests,
migrations, lockfiles and the untouched scaffold. The first build measured
656; the framework fixes that [FRICTION.md](FRICTION.md) asked for brought it
to 582, declaring the roles in `KARNI_ROLES` added eleven, moving seat
capacity and the booking lifecycle into the database (below) added four, and
the 97 lines still over Karni's 500-line target are attributed there.

## Run it

```sh
cd examples/eventhub
python3.12 -m venv .venv
.venv/bin/pip install -e '../../packages/karni[images]' -e ../../modules/karni-payments \
    'psycopg[binary]' gunicorn uvicorn-worker pytest pytest-django
cp .env.example .env            # then: DATABASE_URL=sqlite:///data/db.sqlite3, REDIS_URL=redis://127.0.0.1:6379/0,
                                #       KARNI_AUTH_MODE=session, KARNI_PAYMENTS_PROVIDER=test, MEDIA_ROOT=data/media,
                                #       KARNI_ACCOUNTS_DEFAULT_ROLES=attendee,
                                #       KARNI_SEED_LOGINS={"organizer@example.com": ["organizer"], "attendee@example.com": ["attendee"]}
karni migrate && karni seed --reset --seed 42
karni serve --local             # Django on :8000
karni worker                    # Celery: the payment webhook and the confirmation email
cd frontend && npm install && npm run dev   # http://localhost:5173
```

`karni seed` prints the demo login (`demo@example.com`, every role) and the
two `KARNI_SEED_LOGINS` (`organizer@example.com`, `attendee@example.com`,
password `karni-password`); the seeds add three venues, six events (five
published), two tiers each and ten bookings — the same rows on every machine. Docker Compose works too
(`cp .env.example .env && karni serve`), with the webhook worker included.

## The walkthrough

### Models — `events/models.py`

Four `karni make model` calls produced the whole data layer:

```sh
karni make model Venue name:str:200 address:text city:str:100 capacity:int --with viewset,test --access public-read
karni make model Event title:str:200 description:text starts_at:datetime ends_at:datetime \
    "status:choice:draft|published|cancelled" organizer:fk:User venue:fk:Venue 'cover_image:image?' \
    -a --access owned:organizer --search title,description
karni make model TicketTier event:fk:Event name:str:100 price:decimal:10:2 quantity:int --with viewset,test --access owned:event__organizer
karni make model Booking event:fk:Event tier:fk:TicketTier attendee:fk:User quantity:int \
    "status:choice:pending|confirmed|cancelled" 'payment:fk:karni_payments.Payment?' -a --access owned:attendee
```

Every model is a `karni.models.BaseModel`: UUID keys, timestamps, soft delete
and audit stamps come for free, and `DELETE` on the API hides rows instead
of removing them. The hand-written parts are `Booking.total`, two status
columns (the booking's a `StateField`), a `CapacityField` for the seats left,
an `APIMeta` that keeps `status` and `payment` read-only, `Booking.save()`
reserving the seats, and `Booking.clean()` — the tier/event cross-check, which
the generated serializer runs on every create and update.

### Access — `events/viewsets.py`

One declaration per viewset is the whole permission system
([docs/api.md](../../docs/api.md#access-control)); it compiles into the
request gate *and* the row filter, so a list, a detail, `?expand=` and a
relation field all agree:

```python
class EventViewSet(BaseViewSet):
    model = Event
    access = Access(
        read=PUBLISHED | Owned("organizer") | STAFF,   # anyone sees published; organizers their drafts
        write=Owned("organizer") | STAFF,
        create=HasRole("organizer", "staff"),           # organizer is stamped server-side
    )
```

`Owned("event__organizer")` lets organizers manage tiers of their events.
A booking is readable by its attendee *and* the event's organizer, but
writable only by the attendee (the organizer gets a 403, as the tests prove).
Roles are Django groups; `KARNI_ACCOUNTS_DEFAULT_ROLES=attendee` gives every
new user the `attendee` role.

### Custom actions

Three `@action`s cover what CRUD does not: `POST /api/bookings/{id}/pay/`
opens a checkout, `GET /api/events/{id}/dashboard/` aggregates confirmed
bookings, `GET /api/events/{id}/attendees/` streams a CSV. Each takes its own
`access=` predicate, and the row lookup still goes through `read`.

### Payments — `karni add payments`

`karni add payments` wired the module (dependency, `INSTALLED_APPS`, agent
guidance). `pay` calls `karni_payments.services.create_checkout()` with the
booking's own total; `events/payments.py` is the
`KARNI_PAYMENTS_CHECKOUT_VALIDATOR`, so no client can charge another amount.
When the provider's webhook moves the payment to `succeeded`, the module saves
the `Payment` and `events/listeners.py::confirm_paid_booking`
(`@on_updated(Payment)`) confirms the booking. Locally and in CI the in-memory
`test` provider plays the gateway.

### Events and email — `events/listeners.py`

`@on_updated(Booking, queued=True)` runs `send_booking_confirmation` in a
Celery worker after the commit: Django's `send_mail`, stamped once with
`confirmation_sent_at`. No signal wiring, no `AppConfig.ready()`: Karni
imports `listeners.py` for every app at startup.

### Domain rules — `Booking.clean()`, capacity and the booking lifecycle

The tier/event cross-check lives in the model's `clean()`. Karni's generated
serializer runs it before every create and update, with the values the
viewset stamps (the attendee), and turns its `ValidationError` into the 400
response, so no serializer is written for a domain rule.

Seats are not a `clean()` rule: two requests would pass the check together.
`TicketTier.remaining` is a `CapacityField(total="quantity")` the database
keeps between 0 and the quantity; `Booking.save()` takes the seats with
`karni.capacity.reserve(tier, quantity)` in the same transaction as the row,
so the last seat goes to exactly one buyer and the other gets a 409 naming
what is left. `Booking.status` is a `StateField` (pending → confirmed →
cancelled): the payments listener and the `cancel` action call
`booking.transition(...)`, an illegal move is refused everywhere, and
`events/listeners.py` gives the seats back on cancellation (`@on_transition`)
or deletion. See [docs/lifecycle-and-capacity.md](../../docs/lifecycle-and-capacity.md).

### Admin

There is no `admin.py`. Every model is registered with derived list columns,
filters, search and soft-delete actions at `/admin/`.

### Frontend — `frontend/src/pages/*.tsx`

`karni make model ... -a` generated the list, detail and form pages; each is
a few lines composing `ResourceTable`, `ResourceDetail` and `ResourceForm`,
which render from the OpenAPI schema (columns, labels, validation, relation
pickers). EventHub adds:

- `events.tsx` — the public catalogue with server-side search, "New event"
  only for `usePermission().hasRole("organizer")`;
- `event-detail.tsx` + `components/TierList.tsx` — tiers with a Book button
  (`karni make component TierList`);
- `booking-detail.tsx` — "Pay now" calls the `pay` action and follows the
  checkout URL;
- `event-dashboard.tsx` — three `Stat` tiles, this event's bookings
  (`ResourceTable params={{ event: id }}`) and the CSV export link;
- `login.tsx` — `karni make page login --kind login`: @karni/ui's `LoginForm`.

Every page stays under the 50-line cap enforced by `karni/max-page-lines`.

### Tests — `events/tests/`

`karni make test` wrote one file per resource; the Booking one shows the whole
API surface in two calls:

```python
class BookingAPITests(APITestCase):
    def test_crud(self):
        self.assert_crud(BookingViewSet, values=..., payload=...)   # list/retrieve/create/update/delete,
                                                                    # every promised denial, pagination,
                                                                    # filtering, owner stamping, the schema
    def test_owners_cannot_reach_each_others_rows(self):
        self.assert_isolated(BookingViewSet)                        # one line against the leak everyone forgets
```

`test_booking_flow.py` drives the money path end to end — book, pay, signed
webhook, confirmed, email in `mail.outbox` — plus the sold-out 409, seats
returned on cancellation, the checkout validator and the organizer's view. `tests/test_api_schema.py` pins
the OpenAPI contract: `karni test` fails on an accidental API break.

### Seeds — `events/seeds.py`

`karni make seeder` wrote one class per model. Attribute overrides give the
venues and events names; `seed()` overrides make tiers and bookings consistent.
The known logins come from `KARNI_SEED_LOGINS`. `karni seed --seed 42`
reproduces the same rows, UUIDs included.

### End to end — `frontend/e2e/`

`scripts/e2e.sh` builds the frontend, migrates, seeds, starts Django and a
Celery worker, and runs Playwright against the production build
(`vite preview` proxying to Django). Three journeys: anonymous browse and
search; attendee books, pays (the test provider's hosted page is mocked) and
is confirmed by a signed webhook processed by the worker; organizer creates an
event through the schema-driven form, reads the dashboard numbers and
downloads the attendee CSV. CI runs the same script (`eventhub` job).

### Agent guidance

`karni new` wrote `AGENTS.md`, `CLAUDE.md` and the editor adapters; `karni
add payments` appended the module's guidance; `karni rules sync --check`
keeps them current. `karni check` (architecture rules, duplication, the
ESLint preset) is clean.

## Commands used

| Step | Command |
|---|---|
| Project | `karni new "EventHub" -o examples` |
| App | `karni make app events` |
| Models, viewsets, pages, tests | the four `karni make model` lines above |
| Payments | `karni add payments` |
| Listeners | `karni make listener send_booking_confirmation --on Booking.updated --queued` |
| Factories, seeds | `karni make factory Event`, `karni make factory Booking`, `karni make seeder <Model>` ×4 |
| Extra pages | `karni make page login --kind login`, `karni make page event-dashboard --path '/events/$id/dashboard'`, `karni make component TierList` |
| Migrations | `karni make migration --app events && karni migrate` |
| Verify | `karni test`, `karni check`, `karni rules sync --check`, `scripts/e2e.sh` |
