---
description: "The booking recipe: resources, time slots with a capacity, bookings members own and pay for. A slot never takes more bookings than its capacity. Entities, roles, modules and changes."
---

# Recipe: booking

!!! warning "Experimental"
    Recipes are [experimental](../stability.md#experimental-names). See
    [recipes](index.md).

Resources (a class, a room, a court, a person) with time slots, and
bookings that members make, pay for and cancel. A slot never takes more
bookings than its capacity: the database refuses the one too many.

```sh
karni new "Harbour Studio" --recipe booking
```

## Entities and roles

The app `bookings`:

| Entity | Fields | Owner | Who reads, who writes |
|---|---|---|---|
| Resource | name, slug (the import key), description, price (`money`, in `app.currency`) | | anyone reads, staff write |
| Slot | resource, starts_at, ends_at, capacity, remaining (`capacity:capacity`) | | anyone reads, staff write |
| Booking | slot, member, status (`state`), note, payment | member | the member and staff read and write, staff delete and book for a member |

`remaining` is a [capacity field](../lifecycle-and-capacity.md): it starts
at `capacity` and the database never lets it drop below zero. A booking's
status moves `pending > confirmed`, `pending > cancelled` and
`confirmed > cancelled`, each move in its change history.

Roles: `admin` (a system role, everything), `bookings-staff` (every
resource, slot and booking) and `customer`, named Member, the role every
account that signs up gets, with an `own` grant on bookings. Staff rights in
`access` name `role:bookings-staff` and `role:admin`.

## Rules

Declared in `karni.yaml` ([rules](../rules.md)), so a rebuild keeps them:

- A resource's price is not negative, a slot holds at least one place and
  does not start in the past, and a resource with slots or a slot with live
  bookings is not deleted (`E990`, `E995`).
- A member books a slot once while the booking is not cancelled (`E991`),
  never a slot that has started (`E993`), and the booking's slot never
  changes (`E994`). The member is the signed-in user, unless staff book for
  a member (`E135`). Members cancel, staff delete.
- Row actions: `pay` while pending (a second call returns the open payment,
  a paid booking is refused), `cancel` while pending or confirmed (a paid
  booking is refunded in full), and `confirm` by staff for a free one. In
  another state they answer 409 (`E997`).

## Modules and settings

- `payments` (karni-payments) with `provider: stripe`. Its currency follows
  `app.currency` (`USD`). recipe.toml lists it under `requires`.
- `email_code_login`: members sign in with a code sent by email.

Pages: the staff dashboard, and under the app's route `/bookings`:
resources (list, detail, form), slots (list, form) and bookings (list,
detail). Demo data: 4 resources, 30 slots and 60
bookings.

## Domain code

- `bookings/models.py`: a new booking takes a place in its slot
  (`karni.capacity.reserve`) in the same transaction, so a full slot
  refuses it with a 409 (`E985`). Cancelling, deleting and restoring give
  the place back or take it again. A slot ends after it starts. `status`
  and `payment` are read-only in the API, and a listener confirms the
  pending booking when its payment succeeds.
- `bookings/viewsets.py`: `POST /api/bookings/<id>/pay/` opens the payment
  for the resource's price (or returns the open one), and
  `POST /api/bookings/<id>/cancel/` cancels and refunds a paid booking.
- `bookings/tests/test_rules.py`: each rule above, as the request a member or
  staff would send.
- `bookings/tests/test_capacity.py`: the capacity and the paid booking.
- `bookings/seeds.py`: four bookable spaces (a meeting room, a workshop
  studio, a podcast booth, a courtyard) with a price, slots in the hours,
  length and size that fit each, and bookings spread over the slots that
  have room. The spaces come from `RESOURCES`.
- `bookings/tests/test_seeds.py`: the demo data is the same for one seed, has
  the counts of `karni.yaml`, and never overbooks a slot.

## What people usually change

| Change | In karni.yaml |
|---|---|
| what a resource is, and its fields | rename the entity with `was:` (`Room: {was: Resource, ...}`), and its fields under `fields` |
| the booking states | `apps.bookings.entities.Booking.fields.status`, for example `"state:requested>confirmed\|requested>declined\|confirmed>cancelled"` (keep `cancelled`: the domain code gives the place back on it) |
| whether a booking is paid | leave `payments` out of `modules`, remove the `payment` field, and delete the `pay` action and the payment listener |
| the payment provider and the currency | `modules.payments: {provider: razorpay}` and `app.currency: INR` |

Then run `karni build`.
