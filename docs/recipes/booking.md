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
| Resource | name, slug (the import key), description, price (`money:USD`) | | anyone reads, staff write |
| Slot | resource, starts_at, ends_at, capacity, remaining (`capacity:capacity`) | | anyone reads, staff write |
| Booking | slot, member, status (`state`), note, payment | member | the member and staff read, the member writes |

`remaining` is a [capacity field](../lifecycle-and-capacity.md): it starts
at `capacity` and the database never lets it drop below zero. A booking's
status moves `pending > confirmed`, `pending > cancelled` and
`confirmed > cancelled`, each move in its change history.

Roles: `staff` (a system role, everything) and `member`, the role every
account that signs up gets, with an `own` grant on bookings.

## Modules and settings

- `payments` (karni-payments) with `provider: stripe` and `currency: usd`.
- `email_code_login`: members sign in with a code sent by email.

Pages: the staff dashboard, resources (list, detail, form), slots (list,
form) and bookings (list, detail). Demo data: 4 resources, 30 slots and 60
bookings.

## Domain code

- `bookings/models.py`: a new booking takes a place in its slot
  (`karni.capacity.reserve`) in the same transaction, so a full slot
  refuses it with a 409 (`E985`). Cancelling, deleting and restoring give
  the place back or take it again. A slot ends after it starts. `status`
  and `payment` are read-only in the API, and a listener confirms the
  pending booking when its payment succeeds.
- `bookings/viewsets.py`: `POST /api/bookings/<id>/pay/` opens the payment
  for the resource's price, and `POST /api/bookings/<id>/cancel/` cancels.
- `bookings/tests/test_capacity.py`: the capacity and the paid booking.

## What people usually change

| Change | In karni.yaml |
|---|---|
| what a resource is, and its fields | rename the entity with `was:` (`Room: {was: Resource, ...}`), and its fields under `fields` |
| the booking states | `apps.bookings.entities.Booking.fields.status`, for example `"state:requested>confirmed\|requested>declined\|confirmed>cancelled"` (keep `cancelled`: the domain code gives the place back on it) |
| whether a booking is paid | leave `payments` out of `modules`, remove the `payment` field, and delete the `pay` action and the payment listener |
| the payment provider and the currency | `modules.payments: {provider: razorpay, currency: inr}`, and `money:INR` on the price |

Then run `karni build`.
