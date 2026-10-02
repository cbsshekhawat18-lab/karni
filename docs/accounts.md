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

## Roles and object permissions

Roles are plain Django groups with thin helpers in
`karni.accounts.permissions`: `assign_role(user, name)`,
`remove_role(user, name)`, `user_roles(user)`, `has_role(user, *names)`.
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
