# Friction log

Every place EventHub needed something Karni should have provided, found by
building the app with only Karni's documented surface (the docs, the package
READMEs and `karni --help`). No workarounds were written: where Karni fell
short, the project code is listed here with the suggested framework fix.

Severity, most to least: **workaround-needed** (built, but with project code
Karni should own — these are the 156 lines over the 500-line target),
**papercut** (a generator edit, a confusing message, a failed command),
**docs-only** (it exists; the docs do not say so). Nothing was a *blocker*:
every feature in the brief shipped.

Status *done without workaround* means EventHub is unaffected once the
framework fix lands (the project code just gets deleted).

## Workaround-needed

### F1 — No login page or form in @karni/ui
- **Trying to:** let attendees and organizers sign in.
- **Karni offered:** `AuthProvider`, `useAuth().login(email, password)`,
  `AuthGuard` — and the README's `AuthGuard fallback={<LoginPage />}` leaves
  `LoginPage` to the project. `karni make page` has no login kind.
- **Had to write:** `frontend/src/pages/login.tsx` (38 lines), a raw `<form>`
  with an `eslint-disable karni/no-raw-elements` comment, because `<form>` is
  banned and nothing shipped replaces it here.
- **Fix:** `@karni/ui` `LoginForm` (email, password, error, 2FA step) and
  `karni make page login`. Every project has this page.
- **Severity:** workaround-needed. **Status:** done without workaround.

### F2 — No default role on signup
- **Trying to:** give every new user the `attendee` role so `HasRole` works.
- **Karni offered:** `assign_role()`; nothing assigns a role on registration.
- **Had to write:** `events/listeners.py::grant_attendee_role`
  (`on_created("karni_accounts.User")`, 4 lines).
- **Fix:** `KARNI_ACCOUNTS_DEFAULT_ROLES = ["attendee"]` in `karni.accounts`.
- **Severity:** workaround-needed. **Status:** done without workaround.

### F3 — Aggregates and CSV export are hand-written actions
- **Trying to:** the organizer dashboard (bookings, tickets, revenue) and the
  attendee export.
- **Karni offered:** `BaseViewSet`, `@action(access=...)`, `Stat` in the UI.
  Nothing turns a queryset into an aggregate endpoint or a CSV download.
- **Had to write:** `EventViewSet.dashboard` and `EventViewSet.attendees`
  (~45 lines of `aggregate()`, `csv.writer`, `Content-Disposition`), and the
  `useEffect` + `client.request` fetch in `event-dashboard.tsx`.
- **Fix:** `karni.api.exports.csv_action(fields=[...], access=...)` and an
  `aggregate_action({...})` on `BaseViewSet`, published in the schema so
  `Stat` can take `resource="events" id=... action="dashboard"` directly.
- **Severity:** workaround-needed. **Status:** done without workaround.

### F4 — `ResourceTable` cannot be pinned to a parent row
- **Trying to:** "bookings of *this* event" on the event dashboard.
- **Karni offered:** `ResourceTable` `filters={[...]}` (toolbar filters the
  user operates), `useResourceList(..., { filters })` (the hook can pin, but
  rendering its rows needs a raw `<table>`, which is banned).
- **Had to write:** nothing — the dashboard shows all bookings the organizer
  can read and leaves the `event` filter to the toolbar. The screen is worse
  than it should be.
- **Fix:** `ResourceTable params={{ event: id }}` (fixed filters merged into
  every request, hidden from the toolbar).
- **Severity:** workaround-needed. **Status:** done without workaround (the
  per-event view is degraded, not missing).

### F5 — Generated serializers do not run model validation
- **Trying to:** "a booking cannot exceed the tier's remaining seats" and
  "a tier must belong to the booking's event".
- **Karni offered:** `APIMeta` (fields, read-only, hints). `Model.clean()`
  is never called by the generated serializer or `perform_create`.
- **Had to write:** `events/serializers.py` through `karni make serializer
  --reason` — 49 lines, 30 of them a copy of the generated field list,
  plus `validate()`.
- **Fix:** run `full_clean()` in the generated serializer (opt-out via
  `APIMeta.validate = False`), or `APIMeta.validators = [fn]`. A domain
  rule should be 10 lines, not a serializer.
- **Severity:** workaround-needed. **Status:** done without workaround.

### F6 — Seeding cannot express logins or parent/child consistency
- **Trying to:** a demo with known logins per role, events owned by the
  organizer login, bookings whose `event` is their `tier.event`.
- **Karni offered:** `karni seed` (demo superuser with every role, inferred
  rows), `Seeder` attribute overrides and `seed()` with `context.create()`.
- **Had to write:** `events/seeds.py` (80 lines): a `UserSeeder` that creates
  two logins and assigns roles, and `seed()` overrides for `TicketTier` and
  `Booking` because inferred FKs are picked independently (a booking's tier
  came from another event).
- **Fix:** `KARNI_SEED_LOGINS = {"organizer@example.com": ["organizer"]}`;
  and let `karni seed` honour `<app>/factories.py` (the `BookingFactory`
  already says `event = LazyAttribute(lambda b: b.tier.event)` — the seed
  engine ignores it, the test engine does not).
- **Severity:** workaround-needed. **Status:** done without workaround.

## Papercut

### F7 — `karni make listener --on` only knows local-app models
- `karni make listener confirm_paid_booking --on Payment.updated` and
  `--on User.created` fail with `C105: no model Payment — create it first`,
  although `karni.events.on_updated("karni_payments.Payment")` is documented.
- **Fix:** accept `app_label.Model` in `--on` and resolve any installed app.
- **Status:** wrote both listeners by hand.

### F8 — `karni new` writes an absolute `@karni/ui` path
- From a checkout, `frontend/package.json` gets
  `"@karni/ui": "file:/Users/<me>/…/packages/karni-ui"`, which no other
  machine (or CI) can install. Changed by hand to
  `file:../../../packages/karni-ui`.
- **Fix:** write the path relative to the project when both are under one
  tree (`karni_cli.scaffold.ui_spec`).

### F9 — Generated serializer repeats a field
- `karni make serializer Booking` wrote `read_only_fields` with `"attendee"`
  twice (the owner field is added once as audit, once as owner).

### F10 — `karni rules --check` takes one file
- `karni rules --check a.py b.py` reports *No such command 'b.py'*; the
  reference says `--check FILE…`. Works as `--check a.py --check b.py`.
- **Fix:** make the option a variadic argument, or fix the doc.

### F11 — `assert_crud` and cross-field rules
- With the capacity rule, `assert_crud(BookingViewSet)` failed twice: the
  create payload creates a fresh `event` row even with
  `values={"event": tier.event, "tier": tier}` (so the tier belonged to
  another event), and the update payload picked a quantity above capacity.
  `payload={"event": ..., "tier": ..., "quantity": 1}` was the answer; the
  E602 report does not mention `values=` / `payload=`.
- **Fix:** derive FK payload values from the *same* built row (respecting
  factory `LazyAttribute`s), and name `payload=` in the E602 fix text.

### F12 — Downloading an authenticated endpoint
- In JWT mode a plain `<a href="/api/events/…/attendees/">` cannot carry the
  token, so the CSV export 401s. EventHub runs in session mode
  (`KARNI_AUTH_MODE=session`), where the link just works.
- **Fix:** `client.download(path)` / `useDownload()` in `@karni/ui`, or say
  in the auth docs that downloads need session mode.

### F13 — `vite preview` has no API proxy
- The scaffold proxies `/api` only for `vite` (dev). Serving the production
  build (`vite preview`, the shape CI tests) needed a `preview.proxy` block
  added to `vite.config.ts`.
- **Fix:** scaffold the `preview` block too.

### F17 — `karni worker` cannot run tasks on macOS
- The first end-to-end run saw every webhook task fail in Celery's prefork
  pool (`fast_trace_task: not enough values to unpack (expected 3, got 0)`),
  so no booking was ever confirmed. `--pool=solo` works.
- **Fix:** `karni worker` defaults a host worker on macOS to `--pool=solo`
  (done in karni-cli); `scripts/e2e.sh` passes it explicitly.
- **Status:** done without workaround.

### F18 — `ResourceForm` ignored the schema's defaults
- The organizer's "New event" form could not be submitted: `status` has a
  model default (`draft`) that the form did not prefill, and the select's
  "no selection" (`null`) failed the Zod enum, with the drf-spectacular
  enum description rendered as raw markdown under it.
- **Fix:** the schema parser now carries `default`, forms start from it, and
  a cleared optional non-nullable field is omitted rather than rejected
  (done in @karni/ui). The markdown description is still raw.
- **Status:** done without workaround (the form works out of the box now).

### F19 — The browser's origin must match `KARNI_FRONTEND_URL`
- Session mode derives `CSRF_TRUSTED_ORIGINS` from `KARNI_FRONTEND_URL`; a
  frontend served from any other origin (here Vite's preview on :4173) gets
  `CSRF Failed: Origin checking failed`. The message is clear; the setting's
  docs should say it is also the trusted origin.

### F20 — The test payment provider's ids repeat across restarts
- `TestProvider` numbers sessions from 1 in every process, so a second run
  of the stack reuses `test_cs_1`; with payments rows left from the first
  run, the webhook matched the *old* payment and the booking stayed pending.
  `karni seed --reset` resets the project's tables only, so module rows
  carry over. `scripts/e2e.sh` now flushes the database first.
- **Fix:** give test sessions a per-process prefix, and let `karni seed
  --reset` (or a `--reset-all`) include installed modules' tables.

### F21 — Forms sent `null` for an empty optional image
- The parser merged nullability across the response (a nullable URL) and the
  request (a plain upload), so `ResourceForm` sent `cover_image: null` and
  the API answered "This field may not be null". Fixed in the parser: the
  request side decides what a form may send.
- **Status:** done without workaround.

## Docs-only

### F14 — Running queued listeners in project tests
- `docs/events.md` says "run Celery eagerly (`CELERY_TASK_ALWAYS_EAGER`)"
  and use `django_capture_on_commit_callbacks`, but the scaffold has no test
  settings and no example. The pytest `settings` fixture works
  (`events/tests/test_booking_flow.py`); the testing docs should show it,
  or the scaffold's pytest config should set it.

### F15 — An explicit serializer changes the schema
- Switching `BookingViewSet` to `BookingSerializer` renamed the components
  (`EventsBooking` → `Booking`, 45 "breaking" snapshot changes) and dropped
  `x-karni-access.owned` once the read predicate was an OR. Neither is
  mentioned where `karni make serializer` is documented.

### F16 — `karni new` next steps run `karni check` before `npm install`
- `karni check` fails with "jscpd not installed — run `npm install` in
  frontend/". Reorder the printed steps.

## Where the 156 excess lines are

| Lines | Code | Friction |
|---|---|---|
| 38 | `pages/login.tsx` | F1 |
| 45 | dashboard + CSV actions in `viewsets.py`, fetch in `event-dashboard.tsx` | F3 |
| 30 | the copied field list in `serializers.py` | F5 |
| 46 | `UserSeeder` and the `seed()` overrides in `seeds.py` | F6 |
| 4 | `grant_attendee_role` | F2 |

With F1, F3, F5 and F6 in Karni, EventHub is about 495 lines.
