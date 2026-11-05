## General rules

- JSON in and out. Every URL ends with a slash. Paths below are under `/api/`.
- A list endpoint answers a JSON array or an object with a `results` array (a paginated list is fine).
- Every object has an `id` (a number or a string, any scheme). Money fields are decimals with two places, as a string (`"12.50"`) or a number. Times are ISO 8601.
- Create answers 201 with the new object. A bad request answers 400. A role that may not do something gets 403. An object the user may not see answers 404 or 403. Without a valid token every endpoint except sign-in answers 401 or 403.

## Sign-in and accounts

- `POST /api/auth/login/` with `{"email", "password"}` answers 200 with JSON that has a token in `access` (or `token`). The client sends it as `Authorization: Bearer <token>`. A wrong password answers 400 or 401.
- The management command `python manage.py create_account EMAIL PASSWORD ROLE` creates the account with that role, or, when the email exists, sets its password and role. It exits 0. The checks use it to make their accounts.
- Roles: `member` and `staff`.

## Resources

- `GET /api/resources/` lists resources (any signed-in user). `GET /api/resources/<id>/` shows one.
- `POST /api/resources/` (staff only) with `{"name", "description"?, "price"}` creates one. `price` is the price of one booking and is not negative. A missing name answers 400. Staff may also `PATCH` and `DELETE` a resource.
- A resource shows `id`, `name`, `description`, `price`.

## Slots

- `GET /api/slots/` lists slots (any signed-in user), `?resource=<id>` filters by resource.
- `POST /api/slots/` (staff only) with `{"resource", "starts_at", "ends_at", "capacity"}`. `capacity` is at least 1 and `ends_at` is after `starts_at`, else 400.
- A slot shows `id`, `resource` (the resource id), `starts_at`, `ends_at`, `capacity` and `remaining`, the places still free. `remaining` starts at `capacity` and is read-only.

## Bookings

- `POST /api/bookings/` (member) with `{"slot", "note"?}` creates a booking for the signed-in user. It answers 201 and the booking has `status: "pending"`. It takes one place: the slot's `remaining` drops by 1. A slot with no place left answers 409 and nothing changes. Staff may not create bookings (403).
- A booking shows `id`, `slot` (the slot id), `member` (the user id), `note`, `status` and `payment` (null, or the payment id).
- `GET /api/bookings/` lists the signed-in member's own bookings. Staff see every booking. `GET /api/bookings/<id>/` shows one. Another member's booking answers 404 or 403.
- `POST /api/bookings/<id>/cancel/` (the booking's member, or staff) sets `status` to `"cancelled"` and gives the place back (`remaining` goes up by 1). A booking already cancelled answers 400 or 409 and changes nothing.
- Statuses: `pending`, `confirmed`, `cancelled`.

## Payments (test provider)

- `POST /api/bookings/<id>/pay/` (the booking's member) opens a payment for the booking. It answers 200 or 201 with a payment object. A cancelled booking, or a booking that already has a payment, answers 400 or 409.
- A payment shows `id`, `status` (`pending`, `succeeded`, `failed`), `amount` (the resource's price) and `currency`. The booking's `payment` is then the payment's id. The pay response is either the payment itself or `{"payment": {...}}`.
- `POST /api/payments/<id>/confirm/` (the payment's owner, or staff) is what the test provider calls when the customer has paid. It sets the payment to `succeeded` and its booking to `confirmed`. Confirming twice is harmless (200). A real provider would send a webhook, the confirm endpoint stands in for it.
- `GET /api/payments/<id>/` shows a payment to its owner and to staff.
