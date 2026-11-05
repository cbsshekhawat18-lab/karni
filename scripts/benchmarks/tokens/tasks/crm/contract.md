## General rules

- JSON in and out. Every URL ends with a slash. Paths below are under `/api/`.
- A list endpoint answers a JSON array or an object with a `results` array (a paginated list is fine).
- Every object has an `id` (a number or a string, any scheme). Money fields are decimals with two places, as a string (`"12.50"`) or a number. Times are ISO 8601.
- Create answers 201 with the new object. A bad request answers 400. A role that may not do something gets 403. An object the user may not see answers 404 or 403. Without a valid token every endpoint except sign-in answers 401 or 403.

## Sign-in and accounts

- `POST /api/auth/login/` with `{"email", "password"}` answers 200 with JSON that has a token in `access` (or `token`). The client sends it as `Authorization: Bearer <token>`. A wrong password answers 400 or 401.
- The management command `python manage.py create_account EMAIL PASSWORD ROLE` creates the account with that role, or, when the email exists, sets its password and role. It exits 0. The checks use it to make their accounts.
- Roles: `sales`, `manager` and `admin`.

## Companies and contacts

All three roles read and write companies and contacts, and all of them see every one.

- `/api/companies/` (list, create, `/<id>/` show, `PATCH`). A company has `id`, `name` (required, unique), `website`. A company has no delete for `sales` (403). `manager` and `admin` may `DELETE`.
- `/api/contacts/` (list, create, show, `PATCH`). A contact has `id`, `company` (a company id, optional), `first_name`, `last_name`, `email` (required, a valid address, unique, 400 otherwise), `phone`. `?company=<id>` filters the list.

## Deals

- `/api/deals/`: a deal has `id`, `title` (required), `company` (a company id), `contact` (a contact id, optional), `value` (not negative), `stage` and `owner` (the user id of the sales person who owns it).
- `POST /api/deals/` (any role) creates a deal. The owner is the signed-in user and `stage` starts as `"lead"`. Neither can be set in the request.
- `sales` sees only the deals they own: list and show. Another sales person's deal answers 404 or 403. A `sales` user may `PATCH` only their own deals and cannot change `stage` or `owner` that way. `manager` and `admin` see and `PATCH` every deal, and may set `owner` to another user's id.
- `DELETE /api/deals/<id>/` is for `admin` only (204). `manager` and `sales` get 403.
- `POST /api/deals/<id>/move/` with `{"stage"}` changes the stage (same visibility as show). Stages: `lead`, `qualified`, `proposal`, `won`, `lost`. Allowed moves: lead to qualified, qualified to proposal, proposal to won, and lost from lead, qualified or proposal. Any other move (a skip, a step back, a move out of won or lost, an unknown stage) answers 400 and changes nothing. It answers 200 with the deal.
- `GET /api/deals/pipeline/` answers a JSON array with one item per stage, in the order lead, qualified, proposal, won, lost: `{"stage", "count", "value"}`, where `value` is the sum of the deals' values at that stage. It counts only the deals the signed-in user may see.

## Contact import

- `POST /api/contacts/import/` (`manager` and `admin`, else 403) takes a multipart upload with the CSV in the field `file`. The first row is the header: `first_name,last_name,email,phone,company`. `company` is a company name: it is created when no company has that name.
- A row whose email is already a contact's updates that contact. A row with an invalid or empty email is skipped. A bad row does not stop the others.
- It answers 200 with `{"created": n, "updated": n, "errors": [...]}` where `errors` has one entry per skipped row.
