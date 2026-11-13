---
description: "Demo mode (karni.demo, experimental): put a project online for anyone to try. Demo accounts with one login per role, a write rule that lets only those accounts write, a data reset every N hours, one boot command, the sign-in notice in @karni/ui, every setting, escape hatch and error code."
---

# Demo mode

Demo mode makes a project safe to publish for anyone to try. Visitors sign in
with a public demo login, change data, and the next visitor still finds a
working app, because the data goes back to its starting state on a schedule.

It is **experimental** ([stability](stability.md#experimental-names)). Every
Karni demo shares it: the [shop demo](demo.md) is the first, and a project adds
only its accounts and settings.

## Why it is in core

The repository rule is that a separate service or meaningful memory cost
belongs in a module. Demo mode has neither. It is a few settings, two small
middlewares, a lock file, one management command and two routes, so it lives
in `karni.demo`, and a project without it pays nothing: nothing runs while
`KARNI_DEMO_MODE` is off.

## What it does

| Part | What it gives |
|---|---|
| Demo accounts | One account per role, each with a label and a sentence about what it can do. Made and repaired by the boot and by every reset. |
| Write rule | Only demo accounts write. A demo account never changes its own password, email or roles, and never deletes itself. Sign-in, token refresh, sign-out and accepting the terms stay open to everyone. |
| Reset | The data goes back to `karni seed` with a fixed seed, at boot when it is old and every N hours while serving, by one worker under a lock, safe on SQLite. |
| Boot command | `manage.py karni_demo_boot`: migrate, then seed or reset. |
| Sign-in notice | `GET /api/demo/` lists the accounts. `DemoNotice` and `DemoSignInPrompt` in `@karni/ui` show them above the sign-in form. The admin's sign-in page shows them too. |
| App page | `app_urls()` serves the built React app at `/`, so one service answers the API, the admin and the app. |

## Wire it in

In `config/settings.py`, after `karni_settings(globals())`:

```python
INSTALLED_APPS += ["karni.demo"]
MIDDLEWARE += [
    "karni.demo.middleware.DemoResetMiddleware",
    "karni.demo.middleware.DemoWriteGuardMiddleware",
]

KARNI_DEMO_ACCOUNTS = [
    {
        "login": "demo@example.com",
        "label": "Staff",
        "can": "Manage products and orders, and open the admin.",
        "roles": "all",
        "staff": True,
        "superuser": True,
    },
    {
        "login": "customer@example.com",
        "label": "Customer",
        "can": "Fill a cart and read their own orders.",
        "roles": ["customer"],
    },
]
```

In `config/urls.py`:

```python
from karni.demo.urls import app_urls

urlpatterns = [
    # ...
    path("api/demo/", include("karni.demo.urls")),
    # ... every other route, then last:
    *app_urls(),
]
```

Turn it on with an environment variable: `KARNI_DEMO_MODE=True` (or the short
name `DEMO_MODE=True`). Start the service with the boot command before the web
server:

```sh
python manage.py karni_demo_boot
exec gunicorn config.asgi:application ...
```

The React side needs one line, inside `AuthGuard`:

```tsx
import { AuthGuard, DemoSignInPrompt } from "@karni/ui";

<AuthGuard explain slots={{ Anonymous: DemoSignInPrompt }}>
    <Outlet />
</AuthGuard>
```

`karni check` reports `E953` when demo mode is on and the guard is not in
`MIDDLEWARE`, and `E950` for a malformed account list.

## Demo accounts

`KARNI_DEMO_ACCOUNTS` is a list of dicts. Without it there is one account, the
one `karni seed` makes (`demo@example.com`, staff, superuser, every role the API
names).

| Key | Meaning |
|---|---|
| `login` | Required. The user model's login field, usually an email. |
| `label` | A short name shown on the sign-in pages. Default: the login. |
| `can` | What the account can do, in a sentence. Shown beside the login. |
| `roles` | A list of role names, or `"all"` for every role the API names. Default: none. |
| `staff`, `superuser` | The user's flags. Default: false. |
| `password` | Default: Karni's seed password, `karni-password`. |

Every boot and every reset puts each account back: it is created if missing,
and its password, flags, roles and accepted terms are restored. A project that
adds an account to the list gets it on the next boot, with no migration.
`karni seed` always makes `demo@example.com` with the known password. When that
login is not one of the demo accounts, the boot makes it inactive, so no public
login exists that the sign-in page does not show.

Demo passwords are public by design. The notice shows them.

## Who may write

For every request that is not GET, HEAD, OPTIONS or TRACE:

| Caller | API | Admin |
|---|---|---|
| Anyone | may sign in, refresh a token, sign out and accept the terms | may sign in and sign out |
| Anonymous, or an account that is not a demo account | reads only. A write answers 403 `demo_read_only` | reads only. A change answers 403 |
| A demo account | writes everywhere except the accounts API under `/api/auth/` (password, email, profile, the role matrix): 403 `demo_account_locked` | changes the project's data, not the user and role tables or a password |

Sign-up (`register/`) and sign-in codes (`otp/`) are writes, so they are
closed. A demo account still meets the project's own access rules: a customer
account cannot create a product just because it is a demo account, because the
viewset refuses it as usual.

The caller is the session's user (the admin), else the user of the JWT in the
`Authorization` header (the React app and API clients).

### Escape hatches

- `KARNI_DEMO_OPEN_PATHS`: more paths anyone may write to, for example a contact
  form: `["/api/contact/*"]`. An exact path, or a prefix ending in `*`.
- `KARNI_DEMO_LOCKED_PATHS`: more paths no demo account may write to.
- `KARNI_DEMO_WRITE_RULE`: the dotted path of `f(request) -> Refusal | None` that
  replaces the whole rule (`karni.demo.guard.refusal`). Import `Refusal` from
  `karni.demo.guard`.
- The middleware classes only call the rule, so a project can subclass them or
  list its own in `MIDDLEWARE`. If it does, list the dotted path in
  `KARNI_DEMO_GUARD_MIDDLEWARE` so `E953` knows a guard is installed.

## The reset

The data goes back to `karni seed --reset` with the seed in `KARNI_DEMO_SEED`
(42) every `KARNI_DEMO_RESET_HOURS` hours (24), with no outside scheduler:

1. **At boot.** `karni_demo_boot` runs before the web server starts. A database
   without the seed's demo user is seeded. Data older than the period is reset.
   Otherwise the accounts are put back as they were made.
2. **While serving.** Each worker asks at most every
   `KARNI_DEMO_RESET_CHECK_SECONDS` (60) whether the last reset, recorded in a
   small file, is older than the period.
3. **Once.** A worker that finds the data due takes an exclusive, non-blocking
   lock on `<stamp>.lock` and checks the time again under it. A worker that
   does not get the lock skips. So with any number of workers, one resets.
4. **In one transaction.** The reset deletes the rows of every app it does not
   keep, runs the seed, then restores the accounts. A worker reading meanwhile
   sees the old rows or the new ones, never a mix.

The reset keeps the accounts app, the roles, content types, sessions, the token
blacklist and the beat schedule (`KARNI_DEMO_KEEP_APPS` changes the list). Only
tables of the default database are cleared. With the same seed, rows come back
with the same ids.

On SQLite the database file is never replaced or deleted. For several workers
give `DATABASES` WAL mode, `BEGIN IMMEDIATE` and a busy timeout, so a write that
arrives during a reset waits for it:

```python
DATABASES["default"]["OPTIONS"] = {
    "init_command": "PRAGMA journal_mode=WAL",
    "transaction_mode": "IMMEDIATE",
    "timeout": 20,
}
```

The stamp is a file, so it needs one filesystem that every worker shares. It
defaults to `demo-reset.json` next to the SQLite database, else `data/` in the
project (`KARNI_DEMO_RESET_STAMP`).

Escape hatch: `KARNI_DEMO_SEEDER` is the dotted path of `f(seed: int) -> str`
that reseeds the emptied tables in place of `karni seed --reset`.

## The boot command

`manage.py karni_demo_boot` migrates, then seeds an empty database or resets old
data, and prints which it did. `--no-migrate` skips the migration. It refuses
with `E951` while `KARNI_DEMO_MODE` is off and `DEBUG` is off, because the seed
makes accounts with a known password.

## The sign-in notice

`GET /api/demo/` is public and answers while demo mode is on (404 `E954`
otherwise):

```json
{
  "enabled": true,
  "accounts": [
    {"login": "demo@example.com", "password": "karni-password", "label": "Staff",
     "can": "Manage products and orders.", "roles": ["staff", "customer"]}
  ],
  "reset_hours": 24,
  "next_reset": "2026-11-14T09:00:00+00:00",
  "admin_url": "/admin/"
}
```

`@karni/ui` reads it:

| Name | What it is |
|---|---|
| `useDemo()` | The hook: the body above, cached five minutes, no retry on a 404. |
| `DemoNotice` | The accounts as a list above a sign-in form. Renders nothing when the server is not a demo. `onPick` adds a "Use" button per account, `Notice` replaces the body. Role `demo-notice`. |
| `DemoSignInPrompt` | `AuthGuard`'s `Anonymous` slot: the notice above Karni's own prompt. |
| `createDemoSignInPrompt(props)` | The same slot with your `DemoNotice` props. |

The admin's sign-in page shows the same list (`karni.demo` extends its login
template). Override `DemoInfoView.payload` to add fields.

## Settings

Every setting is read on each call, so a test turns demo mode on with a
settings override. The full table is in [settings](settings.md).

| Setting | Default | Meaning |
|---|---|---|
| `KARNI_DEMO_MODE` | `False` | Whether the rules apply. Env `KARNI_DEMO_MODE` or `DEMO_MODE`. |
| `KARNI_DEMO_ACCOUNTS` | the seed's account | The demo accounts (above). |
| `KARNI_DEMO_SEED` | `42` | The fixed seed. Env `DEMO_SEED` too. |
| `KARNI_DEMO_RESET_HOURS` | `24` | Hours between resets. Env `DEMO_RESET_HOURS` too. |
| `KARNI_DEMO_RESET_CHECK_SECONDS` | `60` | How often a worker asks. |
| `KARNI_DEMO_RESET_STAMP` | next to the SQLite file | Where the last reset is recorded. |
| `KARNI_DEMO_KEEP_APPS` | accounts, roles, sessions, ... | App labels a reset keeps. |
| `KARNI_DEMO_OPEN_PATHS` | `[]` | Extra paths anyone may write to. |
| `KARNI_DEMO_LOCKED_PATHS` | `[]` | Extra paths no demo account may write to. |
| `KARNI_DEMO_WRITE_RULE` | unset | Replacement for the write rule. |
| `KARNI_DEMO_SEEDER` | unset | Replacement for the reseed. |
| `KARNI_DEMO_APP_INDEX` | `frontend/dist/index.html` | The built app's page. Env `DEMO_APP_INDEX` too. |
| `KARNI_DEMO_APP_RESERVED` | `[]` | First path segments the app page never answers, for example `["payments"]`. |

## Error codes

| Code | Raised when |
|---|---|
| [`E950`](errors.md#e950) | `KARNI_DEMO_ACCOUNTS` is malformed. |
| [`E951`](errors.md#e951) | `karni_demo_boot` runs with demo mode and `DEBUG` both off. |
| [`E952`](errors.md#e952) | `KARNI_DEMO_WRITE_RULE` or `KARNI_DEMO_SEEDER` cannot be imported. |
| [`E953`](errors.md#e953) | Demo mode is on and the write guard is not in `MIDDLEWARE`. |
| [`E954`](errors.md#e954) | `GET /api/demo/` while demo mode is off (404). |

The 403 codes `demo_read_only` and `demo_account_locked` are API strings for
clients, not registry codes.

## Testing a demo

Use a settings override and a stamp in a temporary folder:

```python
@pytest.fixture
def demo(settings, tmp_path):
    settings.KARNI_DEMO_MODE = True
    settings.KARNI_DEMO_RESET_STAMP = str(tmp_path / "demo-reset.json")
    settings.KARNI_DEMO_RESET_CHECK_SECONDS = 0
    return settings

def test_boot_seeds(demo, db):
    from karni.demo import reset
    reset.boot()
    assert reset.last_reset() is not None
```

`examples/shop-demo/tests/demo/` proves the rules for the shop: the write rule
for each account, the reset, the boot command and the notice.

## Coming from a copied `demo/` app

`examples/shop-demo` used to carry its own `demo/` app. If you copied it, move to
the shared code and delete the copy:

| Before | Now |
|---|---|
| `"demo"` in `INSTALLED_APPS` | `"karni.demo"` |
| `demo.middleware.*` | `karni.demo.middleware.*` |
| `manage.py demo_boot` | `manage.py karni_demo_boot` |
| `DEMO_MODE`, `DEMO_SEED`, `DEMO_RESET_HOURS` | the same environment variables, read into `KARNI_DEMO_MODE`, `KARNI_DEMO_SEED` and `KARNI_DEMO_RESET_HOURS` |
| `DEMO_RESET_CHECK_SECONDS`, `DEMO_RESET_STAMP`, `DEMO_RESET_KEEP_APPS`, `DEMO_APP_INDEX` | `KARNI_DEMO_RESET_CHECK_SECONDS`, `KARNI_DEMO_RESET_STAMP`, `KARNI_DEMO_KEEP_APPS`, `KARNI_DEMO_APP_INDEX` |
| meta tags `demo-login-email` in the page | `GET /api/demo/` |
| `frontend/src/demo.tsx` | `DemoSignInPrompt` from `@karni/ui` |
| `{% load demo %}` | `{% load karni_demo %}`, `{% demo_info as demo %}` |
| `"payments"` in the app route's reserved list | `KARNI_DEMO_APP_RESERVED = ["payments"]` |

Nothing public in Karni was renamed: the old names were the example's own.
