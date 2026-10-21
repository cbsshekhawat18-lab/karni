---
description: karni.accounts: email-based users, the auth endpoints, one-time-token email flows, roles as data, two-factor and social login, mounted with one include.
---

# karni.accounts

Email-based users, auth endpoints, one-time-token email flows, roles, 2FA and
social login — mounted with one line:

```python
# config/urls.py
path("api/auth/", include("karni.accounts.urls")),
```

Endpoints (all under the mount point): `register/`, `login/`, `logout/`,
`refresh/`, `csrf/`, `me/`, `password/change/`, `password/reset/`,
`password/reset/confirm/`, `email/verify/`, `email/verify/resend/`,
`email/change/`, `email/change/confirm/`, and `2fa/…` when `KARNI_2FA` is on.

## Swapping the user model

`AUTH_USER_MODEL` defaults to `"karni_accounts.User"` — a concrete, swappable
model. To add fields:

```python
# myapp/models.py
from karni.accounts.models import AbstractKarniUser

class User(AbstractKarniUser):
    display_name = models.CharField(max_length=120, blank=True)
```

```python
# settings.py — BEFORE the first migrate of the project
AUTH_USER_MODEL = "myapp.User"
karni_settings(globals())
```

Swap **before the first `migrate`**; Django cannot re-point a user model
afterwards. Notes:

- `karni.accounts` ships real migrations; `OneTimeToken`'s FK uses
  `migrations.swappable_dependency(settings.AUTH_USER_MODEL)`, so it follows
  your swapped model automatically.
- Every Karni model (including `AbstractKarniUser`) inherits
  `karni.models.BaseModel` (UUID pk, `created_at`, `updated_at`). Changes to
  `BaseModel` fields in a future Karni release ripple migrations into every
  project's swapped user model — expect a generated migration on upgrade.
- The user model declares `APIMeta` (see [docs/api.md](api.md)) exposing
  `id`, `email`, `first_name`, `last_name`, `email_verified`, `date_joined`,
  `created_at`, `updated_at`, with `email`, `email_verified` and
  `date_joined` read-only. Redeclare `APIMeta` on your subclass to change it.

## Auth modes

`KARNI_AUTH_MODE` (env or setting) is `"jwt"` (default) or `"session"`.

- The URLconf is mode-independent and **the mode is read per request**, so
  `override_settings(KARNI_AUTH_MODE=...)` works in tests. In session mode
  `refresh/` answers 405 with an explanatory detail.
- Both authenticators (`JWTAuthentication`, `SessionAuthentication`) are
  installed in every mode, and `rest_framework_simplejwt.token_blacklist` is
  always in `INSTALLED_APPS` — switching modes never adds or removes
  migrations.

### JWT mode

`login/` returns a SimpleJWT token pair plus the serialized user;
`refresh/` rotates the refresh token (rotation + blacklist-after-rotation are
on); `logout/` blacklists the posted refresh token. Lifetimes come from env:
`KARNI_JWT_ACCESS_LIFETIME` (minutes, default 15) and
`KARNI_JWT_REFRESH_LIFETIME` (days, default 7); override anything else by
defining `SIMPLE_JWT` yourself.

**Password change and reset revoke refresh tokens.** Both flows blacklist all
of the user's outstanding refresh tokens. Access tokens already issued stay
valid until they expire — with the 15-minute default that window is at most
15 minutes. This is by design: revoking access tokens would require a
per-request blacklist lookup.

### Session mode

`login/` uses Django's session auth and sets the CSRF cookie
(`ensure_csrf_cookie`); SPAs that render before login can bootstrap CSRF via
`GET …/csrf/` (204, sets the cookie). `karni_settings()` derives:

- `CSRF_TRUSTED_ORIGINS` += the origin of `KARNI_FRONTEND_URL`,
- `CORS_ALLOW_CREDENTIALS = True`.

Password change keeps the user's own session alive
(`update_session_auth_hash`) while still revoking their refresh tokens.

Session mode is also what makes a plain link to an authenticated endpoint
work — a CSV export action, a file behind `access` — because the browser
sends the cookie with the navigation. In JWT mode a link cannot carry the
token; fetch the body through the `KarniClient` instead.

Cookie constraints: same-site setups (frontend and API on one origin, or the
Vite dev proxy) work out of the box. Cross-site setups (SPA on a different
registrable domain) additionally need `SESSION_COOKIE_SAMESITE = "None"` and
`CSRF_COOKIE_SAMESITE = "None"` plus HTTPS (`Secure` cookies) — assign them
after `karni_settings()`. Prefer a shared parent domain where possible.

## Email flows

All account mail goes through one interface:

- `KARNI_ACCOUNTS_EMAIL_BACKEND` (default
  `"karni.accounts.emails.DjangoEmailBackend"`) — a dotted path to an
  `AccountsEmailBackend` subclass. `DjangoEmailBackend` renders Django
  templates and sends through your `EMAIL_BACKEND`;
  `karni.accounts.emails.InMemoryEmailBackend` collects into a class-level
  `outbox` for tests.
- **Template override**: the backend renders
  `karni_accounts/email/<template>_subject.txt`, `<template>_body.txt` and
  optionally `<template>_body.html` for `verify_email`, `reset_password` and
  `change_email`. Put files at the same paths in your project's template
  dirs to replace them — normal Django template resolution is the override
  mechanism.
- **Links**: built from `KARNI_FRONTEND_URL` (env, default
  `http://localhost:5173`) and the `KARNI_ACCOUNTS_LINKS` format strings —
  override either to change where users land.
- **Token TTLs**: `KARNI_ACCOUNTS_TOKEN_TTL` (seconds), default
  `{"verify_email": 86400, "reset_password": 3600, "change_email": 86400}`.
  A new token for the same (user, purpose) invalidates prior unused ones.

Expired/blacklisted JWT bookkeeping is flushed daily by the
`karni-flush-expired-tokens` entry in `CELERY_BEAT_SCHEDULE` (task
`karni.accounts.tasks.flush_expired_tokens`). Remove or override that key in
your settings to opt out or reschedule.

## Enumeration posture

Only `password/reset/` is enumeration-silent (always 200, mail sent only when
the account exists). `email/verify/resend/` requires authentication and may
respond honestly. `register/` and `email/change/` necessarily reveal address
existence through unique-email 400s — documented and accepted.

## Bots and security events

`register/` carries a honeypot: a request that fills the field named by
`KARNI_ACCOUNTS_HONEYPOT_FIELD` (default `website`) is answered `202
Accepted` and creates nothing — a person never sees the field, so put it in
your registration form hidden from view (`tabindex="-1"`, `autocomplete="off"`,
visually hidden, never `display: none` alone, which some bots honour). Set
the setting to `""` to turn it off.

Every auth outcome is a structlog event on the `karni.accounts` logger:
`accounts.login.ok` / `.failed` / `.2fa_required`, `accounts.logout`,
`accounts.register.ok` / `.honeypot`, `accounts.email.verified`,
`accounts.password_reset.requested` / `.confirmed`. Successes carry
`user_id`; failures carry `email`, a 16-character SHA-256 fingerprint of
the address, so logs correlate without holding addresses. Alert on a burst
of `accounts.login.failed` with one fingerprint (credential stuffing) or
many (password spraying).

## Roles as data

A project declares its roles once, in `KARNI_ROLES`, and Karni keeps the
database in step. Membership stays a Django group (so the admin's group
widget, `assign_role` and every `HasRole` check keep working); the role adds
what a group cannot hold — a slug, a name, a description, and *grants*: what
members may do, on which rows.

```python
# settings.py
KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "organizer": {
        "name": "Organizer",
        "grants": {"events.event:*": "own", "events.event:add": "all", "events.venue:view": "all"},
    },
    "venue_manager": {
        "description": "Approves events at their venue.",
        "grants": {"events.event:view": "related:venue", "events.event:approve": "related:venue"},
    },
}
```

A grant maps a **permission pattern** to a **scope**. Permissions are
`app_label.model:action` — `view`, `add`, `change`, `delete` for every model,
plus the actions a model declares; `*` stands for the model or the action
(`"*"` alone is everything). A later, more specific pattern wins over an
earlier wildcard. Scopes:

| scope | rows the action reaches |
|---|---|
| `all` | every row |
| `own` | rows whose `Karni.owner_field` is the user (`created_by` by default); the field may be a path, through foreign keys and many-to-manys |
| `related:<key>` | rows whose `Karni.scope_paths[key]` equals `user.<key>` (`user.venue` → `event.venue`) |
| `custom:<name>` | the `Q` a scope registered with `karni.accounts.roles.register_scope(name, fn)` returns |

The model side lives in `class Karni`, next to `Meta` and `APIMeta`:

```python
class Event(BaseModel):
    ...

    class Karni:
        owner_field = "organizer"          # the `own` scope (default: created_by)
        scope_paths = {"venue": "venue"}   # keys `related:` may use
        actions = ["approve"]              # permissions besides view/add/change/delete
        field_roles = {"internal_note": ["staff"]}   # who sees / changes a field
```

`field_roles` is field-level visibility ([API reference](api.md#field-visibility)):
a role can see a row without seeing every field of it, on the API, in
`?expand=`, in the schema and in the admin.

### Membership: workspaces, teams, client accounts

"A member sees the rows of every workspace they belong to" is `own` with an
owner *path* that ends at the user through the membership many-to-many — no
custom scope, and `assert_isolated` drives it like any other grant:

```python
class Workspace(BaseModel):
    members = models.ManyToManyField(settings.AUTH_USER_MODEL)

    class Karni:
        owner_field = "members"


class Lead(BaseModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)

    class Karni:
        owner_field = "workspace__members"


class LeadActivity(BaseModel):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE)

    class Karni:
        owner_field = "lead__workspace__members"


KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "member": {"grants": {"crm.*:*": "own"}},
}
```

Someone in two workspaces sees both; creating a row in a workspace you do not
belong to is refused (the relation only accepts workspaces you can read). A
model that joins the wildcard later without its own `owner_field` falls back
to `created_by` — give it the membership path too. Every path a grant filters
on is resolved at boot: one that does not exist on a model the grant covers
fails `karni check` with [`E214`](errors.md#e214), never a 500 at request time.

The defaults are deliberately boring: a model with no `Karni` class is owned
by whoever created it, has no scope paths and the four standard actions. The
shipped `KARNI_ROLES` is `staff` (everything), `user` and `customer` (their own
rows); replace it entirely. A wildcard `own` grant simply skips models that
cannot be owned; an explicit one on such a model is an error (`E206`), as is
a pattern that matches nothing — a typo must not grant silently.

`karni sync-roles` (and every `karni migrate`, unless
`KARNI_ROLES_AUTOSYNC = False`) expands the declaration into `Role`,
`Permission` and `RolePermission` rows: it creates, updates and *reports*
roles the database holds that the declaration no longer names — it never
deletes a role. `--dry-run` shows the plan; `--json` is for scripts.

Asking the question:

- `user.can("events.event:approve")` — the gate; `user.can("approve", obj=event)`
  also checks that the row is inside the grant's scope. `user.has_role("organizer")`,
  `user.roles` (the `Role` rows). Grants are resolved once per user instance,
  so a request pays one query however many checks it makes.
- `access = Granted()` on a viewset — the default `karni make viewset`
  writes: `Can` for the viewset's own model and the current action, so the
  roles decide who reaches which rows and the viewset names nothing; see
  [Access control](api.md#access-control). The [admin](admin.md#row-scope)
  applies the same grants to its rows.
- `Can("events.event:approve")` in an `access` declaration: the gate *and* the
  row filter (the union of the scopes); see [Access control](api.md#access-control).
  It must name the viewset's own model (`E209`); to gate on another model's
  permission use `HasRole`.
- `@requires("events.event:approve")` on a view method (the request's user) or a
  service function (the current user from `CurrentUserMiddleware`); denial is a
  403 with code `E208`.

Nothing in Karni compares a role to a string: `staff`, `user` and `customer`
exist only as the default value of `KARNI_ROLES`.

### Permission matrix

`KARNI_ROLES` is the baseline; the **permission matrix** is how it changes
after the project ships, with no deploy and no developer. In the admin it is
Roles → *Permission matrix*: roles across, models down (every model the
project has, minus the framework internals in `KARNI_MATRIX_EXCLUDE`), one
selector per action — `view`, `add`, `change`, `delete` and the model's own
`Karni.actions` — holding the scope that role reaches (`all`, `own`,
`related:<key>`, `custom:<name>`, or nothing). Bulk selectors set a whole
row or column. Nothing is saved until the confirmation page has shown the
diff.

What the matrix writes and what the declaration writes share one table, and
`origin` says which is which:

- a grant set in the matrix is `origin = "matrix"`: `karni sync-roles` keeps
  it whatever the declaration says and lists it as *overridden*;
- a declared grant revoked in the matrix stays as a row with scope `none`,
  so the next sync does not quietly restore it;
- a cell set to the value the declaration gives (the *Declared (…)* option)
  is handed back: `origin = "declared"`, managed by the sync again.

Four guard rails, in `karni.accounts.matrix.plan_changes`, refuse a change
with the reason shown on the confirmation page (and as a 400 with code
`E213` on the API); a refused batch writes nothing:

1. **A system role keeps its declared grants.** Cells `KARNI_ROLES` gives a
   `system: True` role are locked; change the declaration.
2. **Nobody grants what they do not hold.** Touching `app.model:action` needs
   the operator to hold that permission; granting a scope needs them to hold
   it at that scope (`all` covers every scope).
3. **Nobody removes their own last permission to change permissions**
   (`karni_accounts.rolepermission:change`) — locking yourself out of
   production is a support ticket, not a feature.
4. **The diff comes first.** The admin confirms; the API has `dry_run`.

Every change is history: `Role` and `RolePermission` are audited
(`karni.audit`), so the matrix page lists who changed which grant from what,
and the `RolePermission` admin's History tab has the rest. The `Permission`
and `RolePermission` admins are read-only — a grant row edited by hand would
skip the rails.

**Effective permissions** — Roles → *Effective permissions*, or the button on
a user's change page — is the read-only answer to "why can this person see
this?": every permission, the rows it reaches, and each role that grants it
with its scope and origin (a superuser holds everything; a revoked cell is
shown as revoked). Anyone may look at their own; someone else's needs
`karni_accounts.rolepermission:view`. For one row, field or list in
development, `karni why events/<id> --as <user>` gives the same answer for
that row, with the predicate that decided and the fix
([debugging](debugging/why.md)).

The same thing as an API, for a project's own UI and for fixtures and tests:

| route | does |
|---|---|
| `GET api/auth/permissions/matrix/` | `roles`, `models` (each with its `actions` and the `scopes` it may take) and `grants[role][permission]` → `{scope, origin, declared, locked}` |
| `POST api/auth/permissions/matrix/` | `{"changes": [{"role", "permission", "scope"}], "dry_run": false}` — `scope` is a value, `null` to revoke or `"declared"` to hand the cell back; the answer is the plan (`changes`, `refusals`), a refused request is a 400 `E213` and nothing is written |
| `GET api/auth/permissions/effective/` | the requester's own effective permissions |
| `GET api/auth/permissions/effective/<user id>/` | anyone's (needs `rolepermission:view`) |

In code: `build_matrix()`, `plan_changes(operator, changes)`,
`apply_changes(operator, changes)` (raises `MatrixRefused`, whose `.plan`
says why) and `effective_permissions(user)` in `karni.accounts.matrix` take
the operator explicitly, so a seed script or a test can drive them without
a request:

```python
from karni.accounts.matrix import apply_changes

apply_changes(admin, [("support", "shop.order:view", "related:branch")])
```

### Role helpers and object permissions

Membership helpers in `karni.accounts.permissions`: `assign_role(user, slug)`,
`remove_role(user, slug)`, `user_roles(user)`, `has_role(user, *slugs)`.
On a `karni.api.BaseViewSet` use the `access` declaration —
`HasRole("staff")` and `Owned("user")` there are backed by these helpers (role
names are looked up once per request); see
[Access control](api.md#access-control). For plain DRF views:

- `RolePermission.for_roles("staff", "editor")` → a permission class.
- `IsOwner` — object permission comparing `obj.<view.owner_field>`
  (default `"user"`, `user_id` fallback) to `request.user`.
- `ObjectPermissionsMixin` — `owner_field`, `object_permission_classes` and a
  `filter_queryset_for_user(qs)` hook. `BaseViewSet` still inherits it: the
  hook runs after the access read scope (overriding it needs
  `# karni: allow(access-override): <reason>`), and `object_permission_classes`
  on a `BaseViewSet` is deprecated (removed in 1.0; it still runs after the
  access object check). (A deliberate staged exception to the
  three-occurrences rule.)

`me/` includes `roles: list[str]` (read-only) so frontends can gate UI on
roles without a second request.

## Rate limiting

Every auth endpoint is scope-throttled (DRF `ScopedRateThrottle`, backed by
the default cache — Redis in the Karni stack). Defaults:

| scope | rate | endpoints |
|---|---|---|
| `auth.login` | `10/min` | login (per client IP) |
| `auth.login_account` | `10/hour` | login + 2fa/login, keyed on the posted email |
| `auth.register` | `10/hour` | register |
| `auth.password_reset` | `5/hour` | reset request + confirm |
| `auth.token` | `30/min` | refresh |
| `auth.verify` | `10/hour` | verify + resend |
| `auth.email_change` | `5/hour` | change + confirm |
| `auth.2fa` | `10/min` | 2FA endpoints |

Tune via `KARNI_AUTH_THROTTLE_RATES` — a partial dict (setting, or JSON env
var) merged over the defaults before landing in
`REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`; set a rate to `None` to disable
that scope. The per-account login throttle keys on the normalized posted
email, so distributed attempts against one account are still limited.
Throttling resolves the client IP honouring `NUM_PROXIES` (env
`KARNI_NUM_PROXIES`, default 1 — Caddy fronts the stack).

## Two-factor auth (TOTP)

```bash
pip install 'karni[2fa]'
```

Set `KARNI_2FA=True`. This installs `django_otp` +
`django_otp.plugins.otp_totp` (and, in session mode only, `OTPMiddleware`
after `AuthenticationMiddleware`). Endpoints: `2fa/setup/` (unconfirmed
device + `otpauth_url`), `2fa/confirm/`, `2fa/disable/`, `2fa/login/`.

Login gate: when the account has a confirmed TOTP device, `login/` returns
`{"requires_2fa": true, "ephemeral_token": …}` and no credentials. The
ephemeral token is signed, expires after 300 seconds and is single-use
(replays are rejected). `POST 2fa/login/ {ephemeral_token, code}` completes
the login (token pair in jwt mode, session login + `django_otp.login` in
session mode).

## Social login (django-allauth)

```bash
pip install 'karni[social]'
```

Set `KARNI_SOCIAL_AUTH=True` and list providers, e.g.
`KARNI_SOCIAL_PROVIDERS=google,github`. `karni_settings()` wires the allauth
apps, provider apps, middleware, `SITE_ID`, authentication backends and the
email-only account settings.

**v0.1 limitation: social auth is session-mode only.** Only the provider /
socialaccount URLs are exposed (no parallel allauth HTML account surface),
and `KARNI_SOCIAL_AUTH=True` with `KARNI_AUTH_MODE="jwt"` fails startup
validation (an allauth-headless JWT strategy is future work). Verified social
signups mirror into `User.email_verified` — Karni's field stays the single
source of truth.

## Admin

`KarniUserAdmin` (email-based `UserAdmin` with working add/change forms,
styled by `karni.admin`) is registered automatically while
`AUTH_USER_MODEL == "karni_accounts.User"`. After swapping the user model,
reuse it:

```python
# myapp/admin.py
from django.contrib import admin
from karni.accounts.admin import KarniUserAdmin
from myapp.models import User

@admin.register(User)
class UserAdmin(KarniUserAdmin):
    pass
```

## Overriding a single endpoint

URL resolution is first-match-wins — declare yours before the include:

```python
urlpatterns = [
    path("api/auth/register/", MyRegisterView.as_view()),
    path("api/auth/", include("karni.accounts.urls")),
]
```

For behaviour changes, subclass the serializers/views and call your own
service functions; the shipped views stay thin on purpose.
