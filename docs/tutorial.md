---
description: Build EventHub, Karni's reference event-ticketing app, step by step: models, access rules, API, admin, React pages, payments, email and tests.
---

# Tutorial — build EventHub

EventHub is Karni's reference application: an event ticketing platform where
organizers create events with venues, ticket tiers and capacity, attendees
browse, search, book and pay, organizers read a dashboard and export their
attendees, a confirmation email goes out through Celery, and four roles decide
who sees what. It is 608 lines of project code, it lives in the repository
under `examples/eventhub`, and CI builds, seeds, tests and drives it with
Playwright on every change.

This tutorial builds it step by step and explains each Karni concept the first
time it is needed. Every code block marked with a file name is an excerpt of
that file in the repository; a test keeps them identical.

## 0. The project

```sh
karni new "EventHub" && cd eventhub
cp .env.example .env     # DATABASE_URL=sqlite:///data/db.sqlite3 for a no-Docker start
karni make app events
```

`karni new` wrote `config/settings.py` with a single call,
`karni_settings(globals())`, that fills in Django, DRF, Celery, storage,
logging and security from environment variables; anything you assign after
the call wins. It also wrote the frontend, the compose stack and the agent
guidance files. `karni make app` added the app to `INSTALLED_APPS` through a
marker in `settings.py` that every later generator uses.

## 1. The domain, on the command line

```sh
karni make model Venue name:str:200 address:text city:str:100 capacity:int --with viewset,test --access public-read
karni make model Event title:str:200 description:text starts_at:datetime ends_at:datetime \
    "status:choice:draft|published|cancelled" organizer:fk:User venue:fk:Venue 'cover_image:image?' \
    -a --access owned:organizer --search title,description
karni make model TicketTier event:fk:Event name:str:100 price:decimal:10:2 quantity:int --with viewset,test --access owned:event__organizer
karni make model Booking event:fk:Event tier:fk:TicketTier attendee:fk:User quantity:int \
    "status:choice:pending|confirmed|cancelled" 'payment:fk:karni_payments.Payment?' -a --access owned:attendee
karni add payments
karni make migration --app events && karni migrate
```

**Concept: `BaseModel`.** Every generated model inherits
`karni.models.BaseModel`: a UUID primary key, `created_at`/`updated_at`,
soft delete (`delete()` hides the row; the default manager never shows it)
and `created_by`/`updated_by` stamped from the current user. The field
language (`name:type[:arg][?]`) covers strings, numbers, dates, choices,
files and relations, including a relation into an installed module
(`karni_payments.Payment`).

**Concept: the auto-router.** A `BaseViewSet` with a `model` is routed at
`/api/<kebab-plural>/` without a `urls.py` entry. `karni routes` lists them.

What the generators left for you to write is the domain: two properties and
the rules a booking must obey.

<!-- karni:snippet examples/eventhub/events/models.py -->
```python
    @property
    def remaining(self) -> int:
        """Seats not held by a pending or confirmed booking."""
        held = self.booking_set.exclude(status=Booking.Status.CANCELLED)
        return self.quantity - (held.aggregate(total=Sum("quantity"))["total"] or 0)
```

<!-- karni:snippet examples/eventhub/events/models.py -->
```python
    def clean(self) -> None:
        """Only published events; the tier must be the event's; never over capacity."""
        if self.event_id and self.event.status != Event.Status.PUBLISHED:
            raise ValidationError({"event": "Only published events can be booked."})
        if self.tier_id and self.event_id and self.tier.event_id != self.event_id:
            raise ValidationError({"tier": "This ticket tier belongs to another event."})
```

**Concept: model validation runs in the API.** The generated serializer calls
`clean()` before every create and update, with the values the viewset stamps
on save, and turns its `ValidationError` into the 400 response keyed by
field. A domain rule is a method on the model, not a serializer.

## 2. Who sees what: `access`

The generator wrote one `access` per viewset from the `--access` flag; the
domain needs more precise ones. This is the whole permission system:

<!-- karni:snippet examples/eventhub/events/viewsets.py -->
```python
class EventViewSet(BaseViewSet):
    model = Event
    access = Access(
        read=PUBLISHED | Owned("organizer") | STAFF,
        write=Owned("organizer") | STAFF,
        create=HasRole("organizer", "staff"),
    )
    search_fields = ("title", "description")
```

<!-- karni:snippet examples/eventhub/events/viewsets.py -->
```python
class BookingViewSet(BaseViewSet):
    model = Booking
    access = Access(
        read=Owned("attendee") | Owned("event__organizer") | STAFF,
        write=Owned("attendee"),
        create=Authenticated(),
    )
```

**Concept: permissions at the queryset.** Each predicate answers two
questions — may the request proceed, and which rows — and the row answer is
applied in `get_queryset()`, so lists, details, relation fields and
`?expand=` all agree. `PUBLISHED` is `Where(lambda request:
Q(status=Event.Status.PUBLISHED))`: anonymous visitors read published events,
organizers also read their drafts, staff read everything. A booking's
organizer can read it but not change it (403), and nobody can reach a
booking they neither own nor organize (404). `Owned("attendee")` in `write`
also stamps the attendee from `request.user` on create. The concept page
[Permissions at the queryset](concepts/queryset-permissions.md) goes deeper.

## 3. Custom actions: pay, dashboard, export

Three things are not CRUD. Each is an `@action` with its own predicate; the
row lookup still goes through `read`.

<!-- karni:snippet examples/eventhub/events/viewsets.py -->
```python
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Open a checkout for this booking; the webhook confirms it when paid."""
        booking = self.get_object()
        back = f"{settings.KARNI_FRONTEND_URL}/bookings/{booking.pk}"
        payment, session = create_checkout(
            request.user,
            amount=booking.total,
            success_url=f"{back}?paid=1",
            cancel_url=back,
            metadata={"booking": str(booking.pk)},
        )
```

**Concept: modules.** `karni add payments` installed karni-payments: its
models, its `/api/payments/` resources, its webhook endpoint and its agent
guidance, wired through entry points. Project code calls
`karni_payments.services.create_checkout()` and never a provider SDK.
`events/payments.py` sets `KARNI_PAYMENTS_CHECKOUT_VALIDATOR` so only a
booking's own total can ever be charged — the module insists on server-side
pricing.

The dashboard aggregates confirmed bookings (`Sum(F("quantity") *
F("tier__price"))`) and the export streams a CSV; both are gated with
`access=Owned("organizer") | STAFF`. They are the one part of EventHub Karni
does not yet own (FRICTION F3).

## 4. Reacting to data: listeners

<!-- karni:snippet examples/eventhub/events/listeners.py -->
```python
@on_updated(Payment)
def confirm_paid_booking(payment: Payment) -> None:
    """The payments webhook moved a payment to succeeded: confirm its booking."""
    if payment.status != Payment.Status.SUCCEEDED:
        return
    for booking in Booking.objects.filter(payment=payment, status=Booking.Status.PENDING):
        booking.status = Booking.Status.CONFIRMED
        booking.confirmed_at = timezone.now()
        booking.save(update_fields=["status", "confirmed_at", "updated_at"])
```

<!-- karni:snippet examples/eventhub/events/listeners.py -->
```python
@on_updated(Booking, queued=True)
def send_booking_confirmation(booking: Booking) -> None:
```

**Concept: events.** `events/listeners.py` is imported for every app at
startup, in the web, worker and beat processes alike. `@on_updated(Payment)`
runs inline when the webhook task saves the payment; `queued=True` makes the
email listener its own Celery task, dispatched after the commit and re-fetching
the row in the worker. No signal wiring, no `AppConfig.ready()`.

Roles are Django groups: `KARNI_ACCOUNTS_DEFAULT_ROLES=attendee` gives every
new user the `attendee` role, and staff promote organizers.

## 5. Screens

`-a` generated the list, detail and form pages; EventHub adds a catalogue
with search, a tier list with Book buttons, a Pay button, a dashboard and a
sign-in page (`karni make page login --kind login`). A page composes the
schema-driven components and stays under 50 lines:

<!-- karni:snippet examples/eventhub/frontend/src/pages/event-dashboard.tsx -->
```tsx
            <div className="grid gap-4 sm:grid-cols-3">
                <Stat label="Confirmed bookings" value={stats?.bookings ?? "…"} />
                <Stat label="Tickets sold" value={stats ? `${stats.tickets} / ${stats.capacity}` : "…"} />
                <Stat label="Revenue" value={stats ? stats.revenue : "…"} />
            </div>
            <h2 className="mt-6 text-lg font-semibold">Bookings</h2>
            <ResourceTable resource="bookings" params={{ event: id }} filters={["status"]} />
```

**Concept: `@karni/ui` renders from the schema.** `ResourceTable`,
`ResourceForm` and `ResourceDetail` take a resource name and read the OpenAPI
document for columns, labels, validation, defaults and relation pickers.
`params` pins a filter; `usePermission().hasRole("organizer")` decides who
sees the New and Dashboard buttons; `useKarniClient().request()` calls the
`pay` action. The ESLint preset keeps raw `<table>`/`<form>` and ad-hoc
`fetch` out of pages.

## 6. Tests

`karni make model ... -a` wrote one test file per resource. The booking one:

<!-- karni:snippet examples/eventhub/events/tests/test_booking.py -->
```python
class BookingAPITests(APITestCase):
    def test_crud(self) -> None:
        # Rows and payloads must respect the capacity rule: one tier, one seat each.
        tier = create(TicketTier, quantity=50)
        self.assert_crud(
            BookingViewSet,
            values={"event": tier.event, "tier": tier, "quantity": 1},
            payload={"event": str(tier.event_id), "tier": str(tier.pk), "quantity": 1},
        )

    def test_owners_cannot_reach_each_others_rows(self) -> None:
        self.assert_isolated(BookingViewSet)
```

**Concept: `karni.testing`.** `assert_crud` derives every expected outcome
from the `access` declaration and the schema — allowed actions, 403 and 404
denials, pagination, filtering, owner stamping, the response contract — and
checks the live API against it. `assert_isolated` creates rows for two owners
and proves one cannot see, change or reference the other's.
`test_booking_flow.py` then drives the money path: book, pay, a signed
webhook from the in-memory test provider, confirmed, email in `mail.outbox`.

## 7. Demo data

<!-- karni:snippet examples/eventhub/events/seeds.py -->
```python
class VenueSeeder(Seeder):
    class Meta:
        model = Venue
        count = 3

    name = factory.Iterator(["Riverside Hall", "The Foundry", "Hilltop Pavilion"])
```

**Concept: `karni seed`.** Every model gets realistic rows inferred from its
field names and types, relations first; a `<app>/seeds.py` seeder steers a
field or takes over `seed()`. `--seed 42` reproduces the same rows, UUIDs
included; `KARNI_SEED_LOGINS` adds the logins the demo and the end-to-end
suite sign in with.

## 8. Run it, end to end

```sh
karni seed --reset --seed 42
karni test && karni check
karni serve --local & karni worker &
(cd frontend && npm install && npm run build && npm run preview)
```

`scripts/e2e.sh` in the example does exactly this and then runs three
Playwright journeys: anonymous browse and search; attendee books, pays
through the mocked checkout page and is confirmed by a signed webhook the
worker processes; organizer creates an event through the generated form and
reads the dashboard numbers and the CSV. CI runs it against PostgreSQL and
Redis on every push.

## Where the lines went

| Group | Lines | What is in it |
|---|---|---|
| models | 83 | four models, two properties, `Booking.clean()`, `APIMeta` |
| viewsets | 87 | four `access` declarations, `pay`, `cancel`, `dashboard`, `attendees` |
| pages | 291 | nine pages and one component, each under 50 lines |
| other | 121 | two listeners, the checkout validator, seeders, two factories, four lines of settings and URL wiring |

Measured by `scripts/loc.py`; everything else — serializers, permissions,
admin, filters, pagination, the optimizer, forms, tables, auth, the test
scaffolding, seeding, the e-mail dispatch — is Karni. What a real build
found missing is in
[FRICTION.md](https://github.com/cbsshekhawat18-lab/karni/blob/main/examples/eventhub/FRICTION.md).
