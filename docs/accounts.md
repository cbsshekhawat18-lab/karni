---
description: "karni.accounts: email-based users, the auth endpoints, one-time-token email flows, roles as data, per-user grants, two-factor and social login, mounted with one include."
---

# karni.accounts

Email-based users, auth endpoints, one-time-token email flows, roles, 2FA and
social login, all mounted with one line:

```python
# config/urls.py
path("api/auth/", include("karni.accounts.urls")),
```

Endpoints (all under the mount point): `register/` (unless
`KARNI_ACCOUNTS_REGISTRATION` is off, see [closing
registration](#closing-registration)), `login/`, `logout/`, `refresh/`,
`csrf/`, `me/`, `password/change/`, `password/reset/`,
`password/reset/confirm/`, `email/verify/`, `email/verify/resend/`,
`email/change/`, `email/change/confirm/`, `2fa/…` when `KARNI_2FA` is on,
`social/<provider>/` for each provider in `KARNI_SOCIAL_TOKEN_PROVIDERS`
([sign-in with an ID token](#sign-in-with-an-id-token-google-microsoft-apple)),
`otp/send/` and `otp/verify/` when `KARNI_EMAIL_OTP` is on ([sign-in with
a code](#sign-in-with-a-code-sent-by-email)), and `terms/` and `terms/accept/`
when `KARNI_TERMS` is set ([terms acceptance](#terms-acceptance)).

## Swapping the user model

`AUTH_USER_MODEL` defaults to `"karni_accounts.User"`, a concrete, swappable
model. To add fields:

```python
# myapp/models.py
from karni.accounts.models import AbstractKarniUser

class User(AbstractKarniUser):
    display_name = models.CharField(max_length=120, blank=True)
```

```python
# settings.py, BEFORE the first migrate of the project
AUTH_USER_MODEL = "myapp.User"
karni_settings(globals())
```

Swap **before the first `migrate`**. Django cannot re-point a user model
afterwards. Notes:

- `karni.accounts` ships real migrations. `OneTimeToken`'s FK uses
  `migrations.swappable_dependency(settings.AUTH_USER_MODEL)`, so it follows
  your swapped model automatically.
- Every Karni model (including `AbstractKarniUser`) inherits
  `karni.models.BaseModel` (UUID pk, `created_at`, `updated_at`). Changes to
  `BaseModel` fields in a future Karni release ripple migrations into every
  project's swapped user model, so expect a generated migration on upgrade.
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
  always in `INSTALLED_APPS`. Switching modes never adds or removes
  migrations.

### JWT mode

`login/` returns a SimpleJWT token pair plus the serialized user.
`refresh/` rotates the refresh token (rotation + blacklist-after-rotation are
on). `logout/` blacklists the posted refresh token. Lifetimes come from env:
`KARNI_JWT_ACCESS_LIFETIME` (minutes, default 15) and
`KARNI_JWT_REFRESH_LIFETIME` (days, default 7). Override anything else by
defining `SIMPLE_JWT` yourself.

**Password change and reset revoke refresh tokens.** Both flows blacklist all
of the user's outstanding refresh tokens. Access tokens already issued stay
valid until they expire. With the 15-minute default, that window is at most
15 minutes. This is by design: revoking access tokens would require a
per-request blacklist lookup.

### Session mode

`login/` uses Django's session auth and sets the CSRF cookie
(`ensure_csrf_cookie`). SPAs that render before login can bootstrap CSRF via
`GET …/csrf/` (204, sets the cookie). `karni_settings()` derives:

- `CSRF_TRUSTED_ORIGINS` += the origin of `KARNI_FRONTEND_URL`,
- `CORS_ALLOW_CREDENTIALS = True`.

Password change keeps the user's own session alive
(`update_session_auth_hash`) while still revoking their refresh tokens.

Session mode is also what makes a plain link to an authenticated endpoint
work (a CSV export action, a file behind `access`), because the browser
sends the cookie with the navigation. In JWT mode a link cannot carry the
token, so fetch the body through the `KarniClient` instead.

Cookie constraints: same-site setups (frontend and API on one origin, or the
Vite dev proxy) work out of the box. Cross-site setups (SPA on a different
registrable domain) additionally need `SESSION_COOKIE_SAMESITE = "None"` and
`CSRF_COOKIE_SAMESITE = "None"` plus HTTPS (`Secure` cookies). Assign them
after `karni_settings()`. Prefer a shared parent domain where possible.

## Email flows

All account mail goes through one interface:

- `KARNI_ACCOUNTS_EMAIL_BACKEND` (default
  `"karni.accounts.emails.DjangoEmailBackend"`) is a dotted path to an
  `AccountsEmailBackend` subclass. `DjangoEmailBackend` renders Django
  templates and sends through your `EMAIL_BACKEND`.
  `karni.accounts.emails.InMemoryEmailBackend` collects into a class-level
  `outbox` for tests.
- **Template override**: the backend renders
  `karni_accounts/email/<template>_subject.txt`, `<template>_body.txt` and
  optionally `<template>_body.html` for `verify_email`, `reset_password`,
  `change_email` and `login_code` ([sign-in with a
  code](#sign-in-with-a-code-sent-by-email)). Put files at the same paths in your project's template
  dirs to replace them. Normal Django template resolution is the override
  mechanism.
- **Links**: built from `KARNI_FRONTEND_URL` (env, default
  `http://localhost:5173`) and the `KARNI_ACCOUNTS_LINKS` format strings.
  Override either to change where users land.
- **Token TTLs**: `KARNI_ACCOUNTS_TOKEN_TTL` (seconds), default
  `{"verify_email": 86400, "reset_password": 3600, "change_email": 86400}`.
  A new token for the same (user, purpose) invalidates prior unused ones.

Expired/blacklisted JWT bookkeeping is flushed daily by the
`karni-flush-expired-tokens` entry in `CELERY_BEAT_SCHEDULE` (task
`karni.accounts.tasks.flush_expired_tokens`). Remove or override that key in
your settings to opt out or reschedule.

## Enumeration posture

`password/reset/` is enumeration-silent (always 200, mail sent only when
the account exists), and so is [sign-in with a
code](#sign-in-with-a-code-sent-by-email) (`otp/send/` and `otp/verify/`).
`email/verify/resend/` requires authentication and may respond honestly. `register/` and `email/change/` necessarily reveal address
existence through unique-email 400s. This is documented and accepted.

## Bots and security events

`register/` carries a honeypot. A request that fills the field named by
`KARNI_ACCOUNTS_HONEYPOT_FIELD` (default `website`) is answered `202
Accepted` and creates nothing. A person never sees the field, so put it in
your registration form hidden from view (`tabindex="-1"`, `autocomplete="off"`,
visually hidden, never `display: none` alone, which some bots honour). Set
the setting to `""` to turn it off.

Your own public forms get the same protection without a registration form.
A viewset with `create=Public()` has a honeypot of its own,
`KARNI_PUBLIC_CREATE_HONEYPOT_FIELD` (default `homepage`), which `@karni/ui`'s
`ResourceForm` renders hidden, and a default rate limit,
`KARNI_PUBLIC_CREATE_RATE` (10 an hour per caller). It is a separate setting
because registration's default, `website`, is a common model field. A filled
one logs `karni.api.honeypot` on the `karni.api` logger. See
[rate limits](api.md#rate-limits).

`@karni/ui` has no sign-up form and its `LoginForm` shows no sign-up link,
so closing registration (below) needs no frontend change. A project that
wants self-registration adds its own page that posts to `register/`.

Every auth outcome is a structlog event on the `karni.accounts` logger:
`accounts.login.ok` / `.failed` / `.2fa_required`, `accounts.logout`,
`accounts.register.ok` / `.honeypot`, `accounts.email.verified`,
`accounts.password_reset.requested` / `.confirmed`, and for sign-in with an
ID token `accounts.social.ok` / `.created` / `.linked` / `.2fa_required` /
`.refused` (with a `reason` and the `code`), and for sign-in with a code
`accounts.otp.sent` / `.created` / `.verified` / `.2fa_required` / `.locked` /
`.refused` / `.email_failed`. Successes carry
`user_id`. Failures carry `email`, a 16-character SHA-256 fingerprint of
the address, so logs correlate without holding addresses. Alert on a burst
of `accounts.login.failed` with one fingerprint (credential stuffing) or
many (password spraying).

## Closing registration

Anyone may open an account through `register/` by default. That suits an app
whose users sign themselves up. A site where staff create every account (a
brochure site with a CMS, an internal tool) turns it off:

```python
# config/settings.py, after karni_settings(globals())
KARNI_ACCOUNTS_REGISTRATION = False
```

or `KARNI_ACCOUNTS_REGISTRATION=False` in `.env`. The `register/` route is
then not mounted, so it answers 404 and is absent from the OpenAPI schema
and the generated TypeScript client. Every other endpoint stays. Create
accounts in the admin or with `createsuperuser`, and give them roles there.

Open registration means "signed in" proves nothing about trust. While it is
on, `karni check` reports [karni.W102](errors.md#w102-any-self-registered-user-may-change-and-delete-every-row-of-a-resource)
for every routed viewset whose `write` is `Authenticated()` or `Public()`
without a narrowing `HasRole`, `Granted`, `Owned` or `Can`: anyone who signs
up could change and delete every row. Tighten `write`, or close
registration. `create=Authenticated()` with an `Owned(...)` write is the
pattern for content users create, and is not reported.

## Roles as data

A project declares its roles once, in `KARNI_ROLES`, and Karni keeps the
database in step. Membership stays a Django group, so the admin's group
widget, `assign_role` and every `HasRole` check keep working. The role adds
what a group cannot hold: a slug, a name, a description, and *grants*, which
say what members may do and on which rows.

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
`app_label.model:action`. The actions are `view`, `add`, `change`, `delete`
for every model, plus the actions a model declares. `*` stands for the model
or the action (`"*"` alone is everything). A later, more specific pattern
wins over an earlier wildcard. Scopes:

| scope | rows the action reaches |
|---|---|
| `all` | every row |
| `own` | rows whose `Karni.owner_field` is the user (`created_by` by default). The field may be a path, through foreign keys and many-to-manys |
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

`field_roles` is field-level visibility ([API reference](api.md#field-visibility)).
A role can see a row without seeing every field of it, on the API, in
`?expand=`, in the schema and in the admin.

### Membership: workspaces, teams, client accounts

"A member sees the rows of every workspace they belong to" is `own` with an
owner *path* that ends at the user through the membership many-to-many. It
needs no custom scope, and `assert_isolated` drives it like any other grant:

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

Someone in two workspaces sees both. Creating a row in a workspace you do not
belong to is refused (the relation only accepts workspaces you can read). A
model that joins the wildcard later without its own `owner_field` falls back
to `created_by`, so give it the membership path too. Every path a grant
filters on is resolved at boot. One that does not exist on a model the grant
covers fails `karni check` with [`E214`](errors.md#e214), never a 500 at
request time.

A module can declare a role too, through the `karni.roles` entry point
([the module contract](modules.md#7c-optional-karniroles-roles-a-module-declares)).
karni-site declares `editor`, for the people who change a public site's
content. Module roles join the declaration under `KARNI_ROLES`: name the
same slug there to replace one, and the module's own setting turns it off
(`KARNI_SITE_EDITOR_ROLE = None`). `karni sync-roles`, the permission
matrix and `karni context` treat them like the project's own.

The defaults are deliberately boring. A model with no `Karni` class is owned
by whoever created it, has no scope paths and has the four standard actions.
The shipped `KARNI_ROLES` is `staff` (everything), `user` and `customer`
(their own rows). Replace it entirely with your own. A wildcard `own` grant
simply skips models that cannot be owned. An explicit one on such a model is
an error (`E206`), and so is a pattern that matches nothing, because a typo
must not grant silently.

`karni sync-roles` (and every `karni migrate`, unless
`KARNI_ROLES_AUTOSYNC = False`) expands the declaration into `Role`,
`Permission` and `RolePermission` rows. It creates and updates roles, and it
*reports* roles the database holds that the declaration no longer names. It
never deletes a role. `--dry-run` shows the plan, and `--json` is for scripts.

Asking the question:

- `user.can("events.event:approve")` is the gate. `user.can("approve", obj=event)`
  also checks that the row is inside the grant's scope. There are also
  `user.has_role("organizer")` and `user.roles` (the `Role` rows). Grants are
  resolved once per user instance, so a request pays one query however many
  checks it makes.
- `access = Granted()` on a viewset is the default that `karni make viewset`
  writes. It means `Can` for the viewset's own model and the current action,
  so the roles decide who reaches which rows and the viewset names nothing.
  See [Access control](api.md#access-control). The [admin](admin.md#row-scope)
  applies the same grants to its rows.
- `Can("events.event:approve")` in an `access` declaration is the gate *and*
  the row filter (the union of the scopes). See [Access control](api.md#access-control).
  It must name the viewset's own model (`E209`). To gate on another model's
  permission, use `HasRole`.
- `@requires("events.event:approve")` goes on a view method (the request's
  user) or a service function (the current user from `CurrentUserMiddleware`).
  Denial is a 403 with code `E208`.

Nothing in Karni compares a role to a string. `staff`, `user` and `customer`
exist only as the default value of `KARNI_ROLES`.

### Permission matrix

`KARNI_ROLES` is the baseline. The **permission matrix** is how it changes
after the project ships, with no deploy and no developer. In the admin it is
Roles → *Permission matrix*. It has roles across and models down (every model
the project has, minus the framework internals in `KARNI_MATRIX_EXCLUDE`),
with one selector per action. The actions are `view`, `add`, `change`,
`delete` and the model's own `Karni.actions`, and each selector holds the
scope that role reaches (`all`, `own`, `related:<key>`, `custom:<name>`, or
nothing). Bulk selectors set a whole row or column. Nothing is saved until
the confirmation page has shown the diff.

What the matrix writes and what the declaration writes share one table, and
`origin` says which is which:

- A grant set in the matrix is `origin = "matrix"`. `karni sync-roles` keeps
  it whatever the declaration says and lists it as *overridden*.
- A declared grant revoked in the matrix stays as a row with scope `none`,
  so the next sync does not quietly restore it.
- A cell set to the value the declaration gives (the *Declared (…)* option)
  is handed back: `origin = "declared"`, managed by the sync again.

Four guard rails, in `karni.accounts.matrix.plan_changes`, refuse a change
with the reason shown on the confirmation page (and as a 400 with code
`E213` on the API). A refused batch writes nothing:

1. **A system role keeps its declared grants.** Cells `KARNI_ROLES` gives a
   `system: True` role are locked. Change the declaration instead.
2. **Nobody grants what they do not hold.** Touching `app.model:action` needs
   the operator to hold that permission. Granting a scope needs them to hold
   it at that scope (`all` covers every scope).
3. **Nobody removes their own last permission to change permissions**
   (`karni_accounts.rolepermission:change`). Locking yourself out of
   production is a support ticket, not a feature.
4. **The diff comes first.** The admin confirms, and the API has `dry_run`.

Every change is history. `Role` and `RolePermission` are audited
(`karni.audit`), so the matrix page lists who changed which grant from what,
and the `RolePermission` admin's History tab has the rest. The `Permission`
and `RolePermission` admins are read-only, because a grant row edited by hand
would skip the rails.

**Effective permissions** (Roles → *Effective permissions*, or the button on
a user's change page) is the read-only answer to "why can this person see
this?". It shows every permission, the rows it reaches, and each role that
grants it with its scope and origin. A superuser holds everything, and a
revoked cell is shown as revoked. Anyone may look at their own. Someone
else's needs `karni_accounts.rolepermission:view`. For one row, field or list
in development, `karni why events/<id> --as <user>` gives the same answer for
that row, with the predicate that decided and the fix
([debugging](debugging/why.md)).

The same thing as an API, for a project's own UI and for fixtures and tests:

| route | does |
|---|---|
| `GET api/auth/permissions/matrix/` | `roles`, `models` (each with its `actions` and the `scopes` it may take) and `grants[role][permission]` → `{scope, origin, declared, locked}` |
| `POST api/auth/permissions/matrix/` | `{"changes": [{"role", "permission", "scope"}], "dry_run": false}`. `scope` is a value, `null` to revoke or `"declared"` to hand the cell back. The answer is the plan (`changes`, `refusals`). A refused request is a 400 `E213` and nothing is written |
| `GET api/auth/permissions/effective/` | the requester's own effective permissions |
| `GET api/auth/permissions/effective/<user id>/` | anyone's (needs `rolepermission:view`) |

In code, `build_matrix()`, `plan_changes(operator, changes)`,
`apply_changes(operator, changes)` (raises `MatrixRefused`, whose `.plan`
says why) and `effective_permissions(user)` in `karni.accounts.matrix` take
the operator explicitly. So a seed script or a test can drive them without
a request:

```python
from karni.accounts.matrix import apply_changes

apply_changes(admin, [("support", "shop.order:view", "related:branch")])
```

### Role helpers and object permissions

Membership helpers in `karni.accounts.permissions`: `assign_role(user, slug)`,
`remove_role(user, slug)`, `user_roles(user)`, `has_role(user, *slugs)`.
On a `karni.api.BaseViewSet`, use the `access` declaration.
`HasRole("staff")` and `Owned("user")` there are backed by these helpers (role
names are looked up once per request). See
[Access control](api.md#access-control). For plain DRF views:

- `RolePermission.for_roles("staff", "editor")` → a permission class.
- `IsOwner`: an object permission comparing `obj.<view.owner_field>`
  (default `"user"`, `user_id` fallback) to `request.user`.
- `ObjectPermissionsMixin`: `owner_field`, `object_permission_classes` and a
  `filter_queryset_for_user(qs)` hook. `BaseViewSet` still inherits it. The
  hook runs after the access read scope (overriding it needs
  `# karni: allow(access-override): <reason>`). `object_permission_classes`
  on a `BaseViewSet` is deprecated (removed in 1.0), and it still runs after
  the access object check. (A deliberate staged exception to the
  three-occurrences rule.)

`me/` includes `roles: list[str]` (read-only) so frontends can gate UI on
roles without a second request.

## Per-user grants

!!! warning "Experimental"
    Everything in this section is [experimental](stability.md#experimental-names):
    the `KARNI_USER_GRANTS` setting, the `UserGrant` model, `karni.accounts.grants`,
    the `targets` and `grant_id` of `karni.accounts.roles.Grant`, the user-grant
    fields of `GrantSource` and of the effective permissions, the
    `permissions/grants/` endpoints, the grants inline and admin, and
    `features: user_grants` in `karni.yaml`. They may change in a minor
    release, and each change is in the CHANGELOG. The error codes keep their
    meaning.

A role grant reaches everyone who holds the role. Many apps also give access
user by user: this customer sees these regions, this analyst sees these
report sections until the end of the quarter. Written by hand, each such need
becomes a table of its own and a check of its own. A per-user grant is one
row of `UserGrant`, written like a `KARNI_ROLES` grant, and every check that
reads the role grants reads it too.

```python
# config/settings.py, after karni_settings(globals())
KARNI_USER_GRANTS = True
```

or `KARNI_USER_GRANTS=True` in `.env`, or `features: {user_grants: true}` in
`karni.yaml` and `karni build`. Off (the default), Karni reads no grant row
and a request pays nothing for the feature. Startup validation refuses a
value that is not a bool ([`E504`](errors.md#e504)).

### The grant

| Field | What it holds |
|---|---|
| `user` | Who the grant is for. |
| `permission` | A pattern as in `KARNI_ROLES`: `app_label.model:action`, with `*` for either part, or `*` alone. |
| `scope` | A scope a role grant takes: `all`, `own`, `related:<key>` or `custom:<name>`. |
| `targets` | Row ids, stored as text, for a scope that points at rows. A `related:<key>` grant with targets reaches the rows whose `Karni.scope_paths[key]` is one of them, in place of `user.<key>`. |
| `expires_at` | When the grant ends. Empty means never. |
| `granted_by` | Who gave it. Karni fills it in from the operator. |
| `reason` | Why, in a few words. |

`created_at` says when. Every change to a grant is in the
[change history](change-history.md), with who made it.

```python
from datetime import timedelta

from django.utils import timezone

from karni.accounts import grants

# A customer who sees the orders of two regions, for one quarter
grants.grant(
    request.user,                      # the operator: granted_by, and checked
    customer,
    "shop.order:view",
    "related:region",
    targets=[north.pk, west.pk],
    expires_at=timezone.now() + timedelta(days=90),
    reason="pilot in two regions",
)
```

The model needs the scope path, as for a role grant:
`class Karni: scope_paths = {"region": "region"}` on `Order`.

### How checks take the union

While the switch is on, `grants_for(user)` loads the user's live grants
(not deleted, not expired) together with their role grants and returns the
union. So `Granted()`, `Can(...)`, `user.can(...)`, `@requires(...)`, the
admin's row scope and imports all answer with roles and user grants alike.
The grants load once per request: one more query, however many checks the
request makes. A superuser holds everything already and pays nothing.

An expired grant counts for nothing from `expires_at` on. Revoking is
deleting the grant (a soft delete, recorded in the history) or setting
`expires_at`. Both are history, so you can always see who had what, and when.

### Writing grants

`karni.accounts.grants` writes grants and checks them first:

| Function | Does |
|---|---|
| `grant(operator, user, permission, scope="all", *, targets, expires_at, reason)` | One grant. |
| `bulk_grant(operator, users, permission, scope="all", ...)` | The same grant to many users, all of them or none. |
| `change(operator, row, **fields)` | A new `permission`, `scope`, `targets`, `expires_at` or `reason`. Any other field is [`E365`](errors.md#e365). |
| `expire(operator, row, at=None)` | Ends the grant now (or at `at`). The row stays. |
| `revoke(operator, row)` | Deletes the grant, with the operator in the history. |
| `check(permission, scope, targets)` | The checks alone, raising the codes below. |

The checks refuse a pattern that matches no permission
([`E360`](errors.md#e360)), a scope the permissions cannot take
([`E361`](errors.md#e361): `own` on a model with no owner field, a
`related:<key>` the model has no scope path for, an unregistered `custom:`),
and bad targets ([`E362`](errors.md#e362): targets for a scope that points at
no row, or an id the scope path's field does not take). A wildcard skips the
models that cannot take the scope, as a `KARNI_ROLES` wildcard does.

Nobody grants what they do not hold, as in the permission matrix: the
operator must hold every permission the pattern reaches, at scope `all` or at
the same scope, and for a grant with targets, their own targets under that
scope must include each one. Otherwise the grant is refused with
[`E363`](errors.md#e363) and nothing is written. A change that gives more
(another permission, scope or targets, a later expiry or none) is checked the
same way. Expiring sooner, a new reason and revoking are not. A superuser,
and code that passes `operator=None` (a seed, a data migration, a test), are
not checked. `full_clean()` on a `UserGrant` runs the pattern, scope and
targets checks for one row. A row saved without them that names no
permission grants nothing.

### The interface for scopes that point at rows

```python
from karni.accounts.grants import scope_targets

for item in scope_targets(user, "related:region", permission="shop.order:view"):
    item.target           # "7", the id as text
    item.permission       # "shop.order:view"
    item.source.origin    # "declared" or "matrix" (a role), "user_grant"
    item.source.role      # the role slug, for a role
    item.source.grant_id  # the UserGrant id, for a user grant
```

`scope_targets(user, scope, *, permission=None)` answers which target ids a
user holds under one scope, from their roles and their user grants, and which
grant gives each. A role grant of that scope gives the id `user.<key>` holds.
A user grant gives its targets, or `user.<key>` when it has none. Expired,
deleted and switched-off grants give nothing. A scope that points at no row,
and a superuser, give an empty list: ask `rows_for` or `user_can` for
`all`. This is the interface a tree scope and a menu built from grants read,
so they never query the grant tables themselves. It costs one query for the
roles' side, and the user grants come from the request's cache. Each item is
a `TargetGrant`, and `to_dict()` gives it as JSON. The scopes that take
targets are listed in `karni.accounts.grants.TARGETED_SCOPES` (`related`
now), which a new scope that points at rows joins.

### In the admin

While the switch is on, each user's change page lists their grants in an
editable inline: add one, edit it, tick *Expire now*, or delete it. The
*targets* field takes ids separated by commas. *User grants* in the admin
lists every grant, with a *Status* filter (live, expired), *Expire selected*,
`?user=<id>` for one user's, and the History tab of each grant. Both fill in
`granted_by` and refuse a grant the operator does not hold (`E363`). They need
the grants `karni_accounts.usergrant:view`, `:add`, `:change` and `:delete`
(staff with `"*": "all"` hold them). Their scope on `UserGrant` limits the
rows too: `own` means the grants you received.

[Effective permissions](#permission-matrix) shows each user's own rows of
the matrix with every source: the roles, then the user grants, each with its
id, targets, expiry and reason, and a link to the user's grants.

### The API for grants

| Route | Does |
|---|---|
| `GET api/auth/permissions/grants/` | The grants you may view, paginated. Filters: `?user=<id>`, `?active=true` or `false`, `?permission=` |
| `POST api/auth/permissions/grants/` | `{user, permission, scope, targets, expires_at, reason}`: one grant (201) |
| `GET`, `PATCH`, `DELETE api/auth/permissions/grants/<id>/` | One grant, a change, a revoke (204) |
| `POST api/auth/permissions/grants/bulk/` | `{users: [ids], permission, scope, targets, expires_at, reason}`: the same grant to each user, at most 1000, all or none (201) |

Each answer carries `granted_by` and `active`. The gate is
`karni_accounts.usergrant:view` for reads, `:add`, `:change` and `:delete`
for the rest, and rows outside your scope on `UserGrant` answer 404. A bad
pattern, scope or targets is a 400 with the code and the `field`. A grant you
do not hold is a 403 `E363` with the `reasons`. While the switch is off, the
routes are not mounted, so they answer 404 and are absent from the OpenAPI
schema. A URLconf built while it was on answers 404
[`E364`](errors.md#e364). `GET permissions/effective/` lists user grants
among the sources, with `origin: "user_grant"`, `grant`, `targets`,
`expires_at` and `reason`.

### Why a user sees a row

`karni why` and `karni why-empty` say which grant decided. The `roles` line
counts the user's live grants, the gate names each source, and the `grants`
section lists role grants and user grants, each with the rows it reaches.
For one row, the grant that reaches it is marked:

```text
roles    organizer + 1 user grant
grants   testapp.event:view  scope own  (role 'organizer', KARNI_ROLES)  → organizer = you
         testapp.event:view  scope related:venue on 7  (user grant 4b1c..., reason 'cover', expires 2026-12-31 18:00)  → venue in ['7']  ← reaches this row
```

`--json` carries the same: `origin`, `grant`, `reason`, `expires_at`,
`targets` and `reaches_row` for each grant. When no grant reaches the row,
one fix names the user grant to widen.

### Switching it off

`KARNI_USER_GRANTS = False` stops reading the rows. Nothing is deleted, and
the grants count again when it is back on. To stop using the feature, revoke
the grants first, then turn it off.

## Rate limiting

Every auth endpoint is scope-throttled (DRF `ScopedRateThrottle`, backed by
the default cache, which is Redis in the Karni stack). Defaults:

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
| `auth.social` | `10/min` | sign-in with an ID token (`social/<provider>/`) |
| `auth.otp_send` | `10/hour` | sign-in with a code: `otp/send/` (per client IP) |
| `auth.otp_send_email` | `5/hour` | `otp/send/`, keyed on the posted email |
| `auth.otp_verify` | `20/min` | `otp/verify/` (per client IP) |

Tune via `KARNI_AUTH_THROTTLE_RATES`, a partial dict (setting, or JSON env
var) merged over the defaults before landing in
`REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`. Set a rate to `None` to disable
that scope. The per-account login throttle keys on the normalized posted
email, so distributed attempts against one account are still limited.
Throttling resolves the client IP honouring `NUM_PROXIES` (env
`KARNI_NUM_PROXIES`, default 1, because Caddy fronts the stack).

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

**allauth's redirect flow is session-mode only.** Only the provider /
socialaccount URLs are exposed (no parallel allauth HTML account surface),
and `KARNI_SOCIAL_AUTH=True` with `KARNI_AUTH_MODE="jwt"` fails startup
validation. Verified social signups mirror into `User.email_verified`, and
Karni's field stays the single source of truth. For a mobile app, a
single-page app or JWT mode, use [sign-in with an ID
token](#sign-in-with-an-id-token-google-microsoft-apple) instead: it works in
both modes and needs neither `KARNI_SOCIAL_AUTH` nor allauth.

## Sign in with an ID token (Google, Microsoft, Apple)

!!! warning "Experimental"
    Everything in this section is [experimental](stability.md#experimental-names):
    the `social/<provider>/` endpoint, the `KARNI_SOCIAL_TOKEN_*` settings,
    `karni.accounts.social_token`, the `SocialIdentity` model, and
    `useSocialLogin` and `SocialButton` in `@karni/ui`. They may change in a
    minor release, and each change is in the CHANGELOG. The error codes keep
    their meaning.

The app signs the user in with the provider's own SDK (Google Identity
Services, MSAL, Sign in with Apple) and gets an OpenID Connect ID token. It
posts the token to Karni, which verifies it offline against the provider's
published keys and answers exactly like `login/`: a token pair in JWT mode, a
session in session mode, or the 2FA gate. It works in both auth modes and
does not need `KARNI_SOCIAL_AUTH` or django-allauth.

```bash
pip install 'karni[social-token]'
```

```python
# config/settings.py, after karni_settings(globals())
KARNI_SOCIAL_TOKEN_PROVIDERS = {
    "google": {"client_ids": ["<web client id>", "<iOS client id>", "<Android client id>"]},
    "microsoft": {"client_ids": ["<application id>"], "tenants": ["organizations"]},
    "apple": {"client_ids": ["<service id>", "<bundle id>"]},
}
```

Each provider listed gets `POST api/auth/social/<provider>/`. A provider the
setting does not list has no route and answers 404. Without the extra,
startup fails with [`E509`](errors.md#e509).

### Settings

| Setting | Default | What it does |
|---|---|---|
| `KARNI_SOCIAL_TOKEN_PROVIDERS` | `{}` | The providers, each `{"client_ids": [...]}` plus the keys below. |
| `KARNI_SOCIAL_TOKEN_SIGNUP` | `None` | `"open"`, `"approval"` or `"existing"` (see [sign-up and linking](#sign-up-and-linking)). `None` is `"open"` while `KARNI_ACCOUNTS_REGISTRATION` is on, else `"existing"`. |
| `KARNI_SOCIAL_TOKEN_LINK_VERIFIED` | `True` | Link a token to the existing account with its email when the provider verified the address. |
| `KARNI_SOCIAL_TOKEN_LEEWAY` | `60` | Seconds of clock skew allowed on `exp`, `iat` and `nbf` (0 to 300). |
| `KARNI_SOCIAL_TOKEN_JWKS_TTL` | `21600` | Seconds a provider's key set stays in the default cache (6 hours). |
| `KARNI_SOCIAL_TOKEN_JWKS_FETCHER` | `"karni.accounts.social_token.fetch_jwks"` | The function `(url) -> dict` that fetches a key set. Tests and proxies swap it. |

A provider's entry takes:

- `client_ids` (required): every client id a token may be issued to. For
  Google, the web client id and each iOS and Android client id. For
  Microsoft, the application (client) id of each app registration. For
  Apple, the service id (the web) and the bundle id (iOS).
- `require_nonce` (default `False`): refuse a request without a nonce.
- `tenants` (Microsoft, default `["common"]`): `common` (any tenant),
  `organizations` (any work or school tenant), `consumers` (personal
  Microsoft accounts) or tenant ids.
- `trusted_tenants` (Microsoft, default `[]`): tenant ids whose email
  addresses count as verified.
- `class`: the dotted path of your own `IdTokenProvider` subclass, to add a
  provider or replace a built-in one.

Startup validation checks every entry: a missing or empty `client_ids`, a
key the provider does not read, a tenant that is not a tenant id or one of
the three names, a provider name that is not a lowercase slug or is
allauth's (`login`, `signup`), and an unknown provider without `class`.

### The request and the answer

```http
POST /api/auth/social/google/
Content-Type: application/json

{"id_token": "<the ID token>", "nonce": "<the raw nonce>", "name": {"first_name": "Ada", "last_name": "Lovelace"}}
```

`nonce` and `name` are optional. `name` is for Apple, which sends the user's
name to the app once, on the first sign-in, and never in the token. Karni
uses it only when the token creates an account and carries no name of its
own, and never for an existing user.

| Answer | Status | Body |
|---|---|---|
| Signed in, JWT mode | 200 | `{"access", "refresh", "user"}`, as `login/` |
| Signed in, session mode | 200 | `{"user"}` and the session cookie |
| The account has 2FA | 200 | `{"requires_2fa": true, "ephemeral_token"}`: finish at `2fa/login/` |
| A new account awaits approval | 202 | `{"code": "E224", "detail", "awaiting_approval": true}`, nothing signed in |
| Refused | 400, 401, 404 or 503 | `{"code", "detail"}` (codes below) |

### A web app

`@karni/ui` has the button and the hook. Karni bundles no provider SDK:
`getIdToken` is your call into Google Identity Services, MSAL or Sign in with
Apple JS, and resolves with the ID token and the nonce you generated.

```tsx
import { SocialButton } from "@karni/ui";

<SocialButton
  provider="google"
  getIdToken={async () => ({ idToken: await askGoogleForAnIdToken(nonce), nonce })}
  onSuccess={(user) => navigate("/")}
  on2FA={(ephemeralToken) => navigate(`/2fa?token=${ephemeralToken}`)}
/>;
```

It shows progress, says in plain words why a sign-in was refused, and shows a
new account that waits for approval as its own state. For your own button,
`useSocialLogin("google")` returns `{ signIn(idToken, { nonce, name }),
status, error }`: in JWT mode it adopts the token pair, in session mode it
re-syncs the session user, and a `requires_2fa` answer goes to the same 2FA
step `LoginForm`'s `on2FA` uses ([UI guide](ui.md)).

### A mobile app

A native app calls the endpoint directly with the token its SDK returned
(Google Sign-In for iOS or Android, MSAL, `ASAuthorizationAppleIDCredential`):

```bash
curl -X POST https://api.example.com/api/auth/social/apple/ \
  -H "Content-Type: application/json" \
  -d '{"id_token": "<identity token>", "nonce": "<raw nonce>", "name": {"first_name": "Ada", "last_name": "Lovelace"}}'
```

In JWT mode the answer carries `access` and `refresh`. Send `Authorization:
Bearer <access>` and rotate with `refresh/`, exactly as after `login/`.

### Sign-up and linking

A verified token finds its account in this order:

1. **An identity already linked.** `SocialIdentity` holds one row per
   provider and subject (the provider's id for the person: `sub`, or
   `<tid>:<oid>` for Microsoft). A linked identity signs in by subject, so
   the link survives a change of the user's email.
2. **An account with the token's email.** The token is linked to it when the
   provider verified the address ([`E222`](errors.md#e222) otherwise). An
   account whose own address was never verified becomes verified, and its
   password is cleared and its refresh tokens revoked: whoever opened it may
   not own the address (see the security notes). Tick *Email verified* when
   you create an account in the admin to keep its password. With
   `KARNI_SOCIAL_TOKEN_LINK_VERIFIED = False`, an account that has a password
   is never linked ([`E227`](errors.md#e227)): the user signs in with the
   password. Linking a provider from a signed-in session is not built yet.
3. **Nobody.** A new account needs an address the provider verified
   ([`E222`](errors.md#e222)), and `KARNI_SOCIAL_TOKEN_SIGNUP` decides:
    - `"open"` creates the account, verified, with no password and the
      `KARNI_ACCOUNTS_DEFAULT_ROLES`, and signs it in.
    - `"approval"` creates it inactive and answers 202
      [`E224`](errors.md#e224) with no credentials, again on each attempt. An
      administrator ticks *Active* on the user's page, and the next sign-in
      succeeds.
    - `"existing"` refuses ([`E223`](errors.md#e223)): only accounts that
      exist may sign in. Staff create them first.

An inactive user never signs in ([`E226`](errors.md#e226)).

The admin lists each user's linked identities read-only on the user's page,
and all of them under *Social identities*. django-allauth's redirect flow
(`KARNI_SOCIAL_AUTH`) keeps its own `SocialAccount` table: the two are
separate, and neither reads the other's links.

### Error codes

| Code | Status | Meaning |
|---|---|---|
| [`E215`](errors.md#e215) | 401 | The token is malformed, signed with another key or algorithm, lacks a required claim, or is not valid yet. |
| [`E216`](errors.md#e216) | 401 | Its `aud` is not one of the configured client ids. |
| [`E217`](errors.md#e217) | 401 | Its issuer is not the provider's, or the Microsoft tenant is not allowed. |
| [`E218`](errors.md#e218) | 401 | It has expired. |
| [`E219`](errors.md#e219) | 401, 503 | Its signing key is not in the provider's key set (401), or the key set cannot be fetched (503). |
| [`E220`](errors.md#e220) | 401 | Its nonce matches neither the nonce sent nor its SHA-256, or a required nonce is missing. |
| [`E221`](errors.md#e221) | 400 | It carries no email address. |
| [`E222`](errors.md#e222) | 400 | The provider did not verify the address, so nothing is created or linked. |
| [`E223`](errors.md#e223) | 400 | Sign-up is closed (`"existing"`). |
| [`E224`](errors.md#e224) | 202 | The new account awaits an administrator's approval. |
| [`E225`](errors.md#e225) | 404 | The provider is not configured. |
| [`E226`](errors.md#e226) | 401 | The account is inactive. |
| [`E227`](errors.md#e227) | 400 | An account with the address exists and has a password, and linking is off. |

`karni explain E222` prints the fix for each one.

### Security notes

- **List every client id, and only yours.** The `aud` check is what keeps a
  token issued to another app (any app that signs its users in with Google)
  from signing them in to yours.
- **Send a nonce.** Generate a new random value for every sign-in, pass it
  (or, for Apple, its SHA-256) to the provider and post the raw value to
  Karni. A token copied from somewhere else then carries the wrong nonce.
  `require_nonce` makes it mandatory for a provider.
- **Microsoft email is not verified by default.** A Microsoft tenant's
  administrator can put any address in a user's `email` or
  `preferred_username`, so Karni counts it as verified only when the token
  has the optional `xms_edov` claim true (add it in the app registration's
  token configuration) or comes from a tenant in `trusted_tenants`, such as
  your own organisation's. Without one of them, a Microsoft token creates no
  account and links to none ([`E222`](errors.md#e222)), and only an identity
  already linked signs in.
- **An unverified account is not trusted with a link.** With open
  registration, someone can register a password account under another
  person's address before that person ever signs in. When the person later
  signs in with a provider that verified the address, Karni links the
  identity and clears the password the other party set, so they cannot sign
  in with it.
- **Keys are fetched, tokens are not sent anywhere.** Karni fetches each
  provider's public keys (JWKS) over HTTPS and keeps them in the default
  cache for `KARNI_SOCIAL_TOKEN_JWKS_TTL` seconds. A token signed with a key
  that is not in the cached set fetches the set again, at most once a minute
  per provider, so a rotated key works within a minute and a flood of made-up
  key ids costs one fetch a minute.
- **Only the provider's algorithms.** Built-in providers accept RS256 only,
  so a token signed with `none` or an HMAC key is refused.
- **Rate limit and logs.** The endpoint has its own throttle scope,
  `auth.social`. The log events carry the provider, the user id or an email
  fingerprint and the refusal's `reason`, never the token or the address.

## Sign in with a code sent by email

!!! warning "Experimental"
    Everything in this section is [experimental](stability.md#experimental-names):
    the `otp/send/` and `otp/verify/` endpoints, the `KARNI_EMAIL_OTP*`
    settings, the `auth.otp_*` throttle scopes, `karni.accounts.otp`, the
    `LoginCode` model, `karni.accounts.services.prove_address`, and
    `useOtpLogin`, `OtpLoginForm` and `LoginForm`'s `codeSignIn` in
    `@karni/ui`. They may change in a minor release, and each change is in the
    CHANGELOG. The error codes keep their meaning.

The user types an address and gets a short numeric code by email. They type
the code back and are signed in, with no password. Karni answers exactly like
`login/`: a token pair in JWT mode, a session in session mode, or the 2FA
gate. It works in both auth modes and needs no extra package.

```python
# config/settings.py, after karni_settings(globals())
KARNI_EMAIL_OTP = True
```

or `KARNI_EMAIL_OTP=True` in `.env`. Then `POST api/auth/otp/send/` and
`POST api/auth/otp/verify/` exist. While the setting is off, both answer 404
and are absent from the OpenAPI schema and the generated TypeScript client,
like `register/` when registration is closed.

### Settings for codes

| Setting | Default | What it does |
|---|---|---|
| `KARNI_EMAIL_OTP` | `False` | Mounts `otp/send/` and `otp/verify/`. |
| `KARNI_EMAIL_OTP_TTL` | `600` | Seconds a code lives (60 to 3600). |
| `KARNI_EMAIL_OTP_LENGTH` | `6` | Digits in a code (4 to 10). |
| `KARNI_EMAIL_OTP_MAX_ATTEMPTS` | `5` | Guesses a code takes (1 to 10). A wrong guess that reaches the cap kills the code. |
| `KARNI_EMAIL_OTP_SIGNUP` | `None` | `"open"`, `"approval"` or `"existing"` (see [who gets in](#who-gets-in)). `None` is `"open"` while `KARNI_ACCOUNTS_REGISTRATION` is on, else `"existing"`. |

Startup validation checks each one: a value that is not a bool, an integer
outside its range, or a policy that is not one of the three fails with
[`E504`](errors.md#e504), which names the setting.

### The requests and the answers

```http
POST /api/auth/otp/send/
Content-Type: application/json

{"email": "ada@example.com"}
```

The answer is always the same 200, whether the address has an account, is
inactive, or may not sign up:

```json
{"detail": "If this address may sign in, a sign-in code is on its way to it.", "length": 6, "expires_in": 600}
```

`length` and `expires_in` come from the settings, so a client can size its
code input. Only an address that is not an address at all is a 400.

```http
POST /api/auth/otp/verify/
Content-Type: application/json

{"email": "ada@example.com", "code": "042917"}
```

Spaces inside the code are ignored.

| Answer | Status | Body |
|---|---|---|
| Signed in, JWT mode | 200 | `{"access", "refresh", "user"}`, as `login/` |
| Signed in, session mode | 200 | `{"user"}` and the session cookie |
| The account has 2FA | 200 | `{"requires_2fa": true, "ephemeral_token"}`: finish at `2fa/login/` |
| A new account awaits approval | 202 | `{"code": "E224", "detail", "awaiting_approval": true}`, nothing signed in |
| The code is wrong or has expired | 401 | `{"code": "E235", "detail"}`, for every failure of the code |
| The account is inactive | 401 | `{"code": "E226", "detail"}`, only after a right code |
| The setting is off | 404 | `{"code": "E236", "detail"}` from a URLconf built while it was on |

### Codes in a web app

`@karni/ui` has the form and the hook ([UI guide](ui.md)):

```tsx
import { OtpLoginForm } from "@karni/ui";

<OtpLoginForm
  onSuccess={(user) => navigate("/")}
  on2FA={(ephemeralToken) => navigate(`/2fa?token=${ephemeralToken}`)}
/>;
```

The email step sends the code. The code step has one input for the whole code,
sized to `length` (`inputMode="numeric"`, `autocomplete="one-time-code"`), a
button for a new code that waits `resendCooldown` seconds (30 by default), and
a way back to the email step. It says in plain words why a code was refused
and shows a new account that waits for an administrator as its own state.

To offer it next to the password, pass `codeSignIn` to `LoginForm`. A "Sign in
with a code" switch then shows `OtpLoginForm` in place of the password fields.
For a form of your own, `useOtpLogin()` returns `{ step, send(email),
verify(code), resend, back, status, error, cooldown, length }`. `verify`
adopts the token pair in JWT mode, re-syncs the session user in session mode,
and hands a `requires_2fa` answer to the same 2FA step `LoginForm`'s `on2FA`
uses.

### Codes in a mobile app

A native app calls the two endpoints directly:

```bash
curl -X POST https://api.example.com/api/auth/otp/send/ \
  -H "Content-Type: application/json" \
  -d '{"email": "ada@example.com"}'

curl -X POST https://api.example.com/api/auth/otp/verify/ \
  -H "Content-Type: application/json" \
  -d '{"email": "ada@example.com", "code": "042917"}'
```

In JWT mode the second answer carries `access` and `refresh`. Send
`Authorization: Bearer <access>` and rotate with `refresh/`, exactly as after
`login/`.

### Who gets in

A right code proves that whoever typed it reads the mailbox. Then:

1. **An account with the address signs in**, if it is active. Its address
   becomes verified. An account whose address was never verified also loses
   its password and its refresh tokens: whoever opened it may not own the
   address, and the same rule applies to [sign-in with an ID
   token](#sign-up-and-linking). Tick *Email verified* when you create an
   account in the admin to keep its password.
2. **An inactive account is refused** with [`E226`](errors.md#e226). It still
   gets a code, so the refusal comes only after the right code and tells
   nothing to someone who does not read that mailbox. A deleted account gets
   no code.
3. **An address without an account** follows `KARNI_EMAIL_OTP_SIGNUP`:
    - `"open"` emails it a code. The account is created when the code is
      verified, never when it is sent: verified, active, with no password and
      the `KARNI_ACCOUNTS_DEFAULT_ROLES`.
    - `"approval"` emails it a code. The verified code creates the account
      inactive and answers 202 [`E224`](errors.md#e224) with no credentials.
      An administrator ticks *Active* on the user's page, and the next code
      signs in. Until then a code for the account answers `E226`.
    - `"existing"` emails nothing. Only accounts that exist may sign in.
      Staff create them first.

### The code's email

The code goes through `KARNI_ACCOUNTS_EMAIL_BACKEND`, like every account
email, with the template `login_code`: `karni_accounts/email/login_code_subject.txt`,
`login_code_body.txt` and `login_code_body.html`. Put files at the same paths
in your project's template dirs to replace them. The context has `code`,
`ttl_minutes` and `user`, which is `None` for an address without an account.
A custom backend receives the same `AccountsEmail`.

The email is sent after the transaction commits, as registration's is. A
backend that raises is logged as `accounts.otp.email_failed` and does not
change the answer: the user asks for a new code.

### Refusals and their codes

| Code | Status | Meaning |
|---|---|---|
| [`E235`](errors.md#e235) | 401 | The code is wrong, expired, used, replaced by a newer one or locked, or no code was sent to the address, or the address may not sign up. |
| [`E226`](errors.md#e226) | 401 | The account is inactive (answered after a right code). |
| [`E224`](errors.md#e224) | 202 | The new account awaits an administrator's approval. The same code sign-in with an ID token uses. |
| [`E236`](errors.md#e236) | 404 | `KARNI_EMAIL_OTP` is off. |

`karni explain E235` prints the fix for each one. The precise reason for an
`E235` is in the `accounts.otp.refused` log event: `wrong_code`, `expired`,
`used`, `locked`, `no_code`, `deleted` or `signup_closed`.

### Security of codes

- **Only a hash is stored.** `LoginCode` keeps an HMAC-SHA256, keyed by
  `SECRET_KEY`, over the lower-cased address and the code. The code is never
  stored or logged, and it is compared with `hmac.compare_digest`. A stolen
  table is useless without `SECRET_KEY`. Changing `SECRET_KEY` invalidates the
  codes in flight, which live minutes.
- **The code is random and short-lived.** It comes from `secrets`, uniform
  over every string of `KARNI_EMAIL_OTP_LENGTH` digits, and dies after
  `KARNI_EMAIL_OTP_TTL` seconds, after one use, or after
  `KARNI_EMAIL_OTP_MAX_ATTEMPTS` wrong guesses. Each guess takes an attempt
  before the code is compared, with a filtered `UPDATE`, so parallel guesses
  cannot exceed the cap. A new code for an address deletes the earlier ones,
  so only the newest works.
- **Throttles on top of the cap.** `otp/send/` has a per-IP scope,
  `auth.otp_send` (`10/hour`), and a per-address one, `auth.otp_send_email`
  (`5/hour`), keyed on the hashed, lower-cased address, so nobody floods one
  mailbox from many IPs. `otp/verify/` has `auth.otp_verify` (`20/min` per
  IP). With the defaults, one address takes at most 25 guesses an hour, against
  a million codes.
- **Nothing says whether an address exists.** `otp/send/` gives the same
  status and body on every path and does the same work: the account lookup,
  the HMAC and one stored row (an address that gets no email gets a row
  nobody has the code for, so `otp/verify/` behaves the same for it). Every
  failure of a code is the same `E235`. With the default backend the email
  itself is sent inside the request, so a slow mail server makes a send that
  emails slower than one that does not. Use a backend that queues the mail
  (a Celery task) when that matters.
- **A code is as strong as the mailbox.** Whoever reads the user's email can
  sign in as them, as with a password reset link. Turn on [2FA](#two-factor-auth-totp)
  for accounts that need more.
- **Dead codes are deleted.** Each send deletes the address's earlier codes
  and every expired one. While `KARNI_EMAIL_OTP` is on, the schedule
  `karni-flush-login-codes` (task `karni.accounts.tasks.flush_login_codes`)
  deletes the rest every hour. The admin lists codes read-only under *Login
  codes*, without the hash, and the permission matrix leaves them out.
- **Logs.** `accounts.otp.sent`, `.created`, `.verified`, `.2fa_required`,
  `.locked`, `.refused` (with the `reason`) and `.email_failed` carry an
  email fingerprint or the user id, never the address or the code.

## Terms acceptance

!!! warning "Experimental"
    Everything in this section is [experimental](stability.md#experimental-names):
    the `terms/` and `terms/accept/` endpoints, the `KARNI_TERMS` setting,
    `karni.accounts.terms` (with `TermsGateMiddleware`), the `TermsAcceptance`
    model, the `terms` field of `me/`, and `TermsGate` and `useAuth()`'s
    `terms`, `termsRequired` and `acceptTerms` in `@karni/ui`. They may change
    in a minor release, and each change is in the CHANGELOG. The error codes
    keep their meaning.

Ask every signed-in user to accept the current version of your terms (terms
of service, an end-user licence agreement) before they use the API. Until they
do, the API refuses them with a 403 that says which version to accept and
where it is. Karni records who accepted which version, when, from which IP,
with which user agent, and what the app said about itself. Change the version
and everyone accepts again. It works in both auth modes and needs no extra
package.

```python
# config/settings.py, after karni_settings(globals())
KARNI_TERMS = {"version": "2026-11", "url": "/terms/", "required": True}
```

or `KARNI_TERMS={"version": "2026-11", "url": "/terms/"}` (JSON) in `.env`.
Then `GET api/auth/terms/` and `POST api/auth/terms/accept/` exist, `me/`
carries `terms`, and the gate runs. Unset (the default), there are no routes,
no `terms` in `me/` and no gate, and the OpenAPI schema is the same as
without the feature.

### Settings for terms

`KARNI_TERMS` is a dict with these keys:

| Key | Default | What it does |
|---|---|---|
| `version` | required | The version every signed-in user must accept, e.g. `"2026-11"` (at most 100 characters). |
| `url` | required | Where the terms are, for the client to show: a path or a full URL. |
| `required` | `True` | `False` gates nothing: the routes and the record stay, and users may still accept. |
| `paths` | `["/api/"]` | The URL path prefixes the gate covers. |
| `exempt` | `[]` | More prefixes the gate leaves open. |

Startup validation checks the value: a `version` that is empty or not a
string, a `url` that is not a string, a `required` that is not a bool, or
`paths` and `exempt` entries that are not strings starting with `/` fail with
[`E504`](errors.md#e504), which names the key. So does an unknown key.

### What is gated

The gate is `karni.accounts.terms.TermsGateMiddleware`. `karni_settings()`
lists it in `MIDDLEWARE` after Django's `AuthenticationMiddleware`, and it
removes itself from the chain at startup unless `KARNI_TERMS` requires
acceptance, so it costs nothing otherwise. It runs once the URL is resolved:

- **Covered:** every request whose path starts with one of `paths`. With the
  default, that is the whole API: your viewsets, plain DRF views, plain
  Django views under `/api/`, and every module's endpoints there.
- **Always open:** the auth mount and every route under it (`login/`,
  `refresh/`, `logout/`, `me/`, `terms/`, `terms/accept/`, the password,
  email, 2FA, social and code routes), Karni's account views wherever they
  are mounted, drf-spectacular's schema and docs views (the schema is
  metadata, and `@karni/ui` reads the auth mode from it), and the `exempt`
  prefixes.
- **Who:** the user of a Bearer token, validated by the JWT class DRF
  authenticates with, else the session user. An anonymous request passes and
  the view decides, so a view that needs a user still answers 401. A token
  DRF would refuse passes too, and the view answers 401.
- **Everyone signed in:** staff and superusers are gated like everyone. A
  legal acceptance applies to every person who uses the service.
- **Not gated by default:** the Django admin, a public site (`karni-site`),
  `/health/` and media are not under `/api/`. Add `"/admin/"` to `paths` to
  gate the admin too. A staff member who has not accepted then gets the 403
  on admin pages, and accepts in the app first.

To keep one endpoint open before acceptance (a status page your app calls
before sign-in completes, for example), add its prefix to `exempt`:

```python
KARNI_TERMS = {
    "version": "2026-11",
    "url": "/terms/",
    "exempt": ["/api/app-config/"],
}
```

A project that replaces `MIDDLEWARE` after `karni_settings()` loses the gate.
The system check [`karni.E248`](errors.md#e248) fails startup when
`KARNI_TERMS` requires acceptance and the gate is missing, or listed before
`AuthenticationMiddleware`.

### Terms requests and answers

```http
GET /api/auth/terms/
Authorization: Bearer <access>
```

```json
{"version": "2026-11", "url": "/terms/", "required": true, "accepted": false, "accepted_at": null}
```

```http
POST /api/auth/terms/accept/
Authorization: Bearer <access>
Content-Type: application/json

{"version": "2026-11", "client": {"platform": "ios", "app_version": "2.4.0", "device": "iPhone15,2"}}
```

`client` is optional: a JSON object of at most 4096 bytes, stored with the
acceptance. The IP is read the way the throttles read it, honouring
`NUM_PROXIES`, and the `User-Agent` header is kept up to 1024 characters.

| Answer | Status | Body |
|---|---|---|
| Accepted now | 201 | The `terms/` body, with `accepted: true` and `accepted_at` |
| Accepted before (same version) | 200 | The same body. Nothing changes |
| Another version | 400 | `{"code": "E246", "detail", "version", "url"}` with the current terms. Nothing is recorded |
| Not signed in | 401 | DRF's answer |
| `KARNI_TERMS` unset | 404 | `{"code": "E249", "detail"}` from a URLconf built while it was set |

While the user has not accepted, every covered request answers:

```json
{
  "code": "E245",
  "detail": "E245: Accept the terms (version 2026-11) to continue. Read them at /terms/, then accept them with POST /api/auth/terms/accept/ and {\"version\": \"2026-11\"}. See …",
  "version": "2026-11",
  "url": "/terms/"
}
```

with status 403 and `Cache-Control: no-store`. `me/` (and so `login/`, whose
`user` is the same payload) carries the same facts, so a client knows before
its first refused request:

```json
{"id": "…", "email": "ada@example.com", "roles": [], "terms": {"required": true, "version": "2026-11", "url": "/terms/", "accepted": false}}
```

### Terms in a web app

`@karni/ui`'s `TermsGate` renders its children only once the user has
accepted ([UI guide](ui.md)). The scaffold's frontend does not include it.
Wrap the router in `frontend/src/App.tsx`, inside `AuthProvider`:

```tsx
import { AuthProvider, KarniProvider, TermsGate } from "@karni/ui";

<KarniProvider client={client}>
  <AuthProvider>
    <TermsGate>
      <RouterProvider router={router} />
    </TermsGate>
    <Toaster />
  </AuthProvider>
</KarniProvider>;
```

Until the user accepts, `TermsGate` shows the terms (a link to `url`, or the
page in a frame with `embed`), the version, and an "Accept and continue"
button. It knows from `me/`, and from the gate's 403 on any request the app
makes through its client, so a version changed mid-session brings the gate
back at the next request. If the version changed again before the user
accepts, the server answers `E246` and the gate shows the new version.
`client={{ platform: "web" }}` (or a function) sends what the app says about
itself. `title`, `description`, `acceptLabel`, `loading` and the `Panel` slot
change its look, and `useAuth()` gives `terms`, `termsRequired` and
`acceptTerms(client)` for a gate of your own.

`embed` needs a page that may be framed. Karni's own pages send
`X-Frame-Options: DENY` and `frame-ancestors 'none'`, so a terms page served
by the project (a `karni-site` page, for example) needs
`X_FRAME_OPTIONS = "SAMEORIGIN"`, which makes the policy `frame-ancestors
'self'` too. A terms page on another origin needs that origin in the
app's `frame-src`.

### Terms in a mobile app

A native app signs in as usual, then checks `user.terms` in the answer (or
`GET terms/`). When `required` is true and `accepted` false, or when any
request answers 403 with `"code": "E245"`, it shows the terms at `url` and
accepts the version it showed:

```bash
curl https://api.example.com/api/auth/terms/ \
  -H "Authorization: Bearer $ACCESS"

curl -X POST https://api.example.com/api/auth/terms/accept/ \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -d '{"version": "2026-11", "client": {"platform": "android", "app_version": "2.4.0", "device": "Pixel 9"}}'
```

The next request passes. An app that sends the version it showed, not the one
it read last, never records acceptance of terms the user did not see: a
version that moved on in between answers `E246` with the new one.

### A new version

Change `KARNI_TERMS["version"]` (in the settings or the environment) and
deploy. At their next request every signed-in user gets the 403 again, until
they accept the new version. Nothing needs clearing: the gate's cache is keyed
by version. Earlier acceptances stay in the record, one row per version.

### The record

`TermsAcceptance` (table `karni_accounts_termsacceptance`, migration
`karni_accounts.0008_terms_acceptance`) holds one row per user and version
among live rows: `user`, `version`, `accepted_at`, `ip`, `user_agent` and
`client`. It is append-only. Saving an existing row, `delete()`,
`hard_delete()`, `restore()`, and `update()` or `delete()` on a queryset raise
[`E247`](errors.md#e247). A user's rows go only with the user:
`user.hard_delete()` deletes them, and a soft-deleted user keeps them.

The admin lists the record read-only under *Terms acceptances*, with a filter
by version, a search by email, and the changelist's *Export selected as CSV /
XLSX* actions (there is no import). Each user's page shows their acceptances
while `KARNI_TERMS` is set. The permission matrix leaves the table out.

`ip` and `user_agent` are personal data. Say in your privacy policy that you
keep them as the record of acceptance.

### How it stays fast

Whether a user accepted a version is cached per (user, version) in the
default cache: for 7 days once they have, for 60 seconds while they have not.
The gate runs one query for a user's first covered request and none for the
next ones. A Bearer token is validated without a query (the user's id comes
from its claim), and `me/` reads the same cache. A new acceptance clears the cached
answer at once and stores it when its transaction commits, so a rolled-back
acceptance is never cached.

### Terms refusals and their codes

| Code | Status | Meaning |
|---|---|---|
| [`E245`](errors.md#e245) | 403 | The signed-in user has not accepted the current version (the gate). |
| [`E246`](errors.md#e246) | 400 | `terms/accept/` got another version than the current one. |
| [`E247`](errors.md#e247) | exception | Code tried to change or delete a `TermsAcceptance` row. |
| [`E248`](errors.md#e248) | system check | The gate is missing from `MIDDLEWARE`, or comes before authentication. |
| [`E249`](errors.md#e249) | 404 | `KARNI_TERMS` is unset. |

`karni explain E245` prints the fix for each one. Accepting logs
`accounts.terms.accepted` (with `created`) and a refused version logs
`accounts.terms.refused`, both with the user id.

### Changing the gate

Subclass `TermsGateMiddleware` and list the subclass in `MIDDLEWARE` in its
place (`karni.E248` accepts a subclass). Each step is a method: `covers`
(the paths), `is_exempt` (what stays open), `user_pk` (who is asking),
`accepted` (the cached check) and `refuse` (the 403). To accept from a view of
your own, call `karni.accounts.terms.accept(user, version, ip=..., user_agent=...,
client=...)`, and `karni.accounts.terms.status(user)` for the `terms/` body.

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

URL resolution is first-match-wins, so declare yours before the include:

```python
urlpatterns = [
    path("api/auth/register/", MyRegisterView.as_view()),
    path("api/auth/", include("karni.accounts.urls")),
]
```

For behaviour changes, subclass the serializers/views and call your own
service functions. The shipped views stay thin on purpose.
