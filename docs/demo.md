---
description: "The shop demo: the shop recipe built by karni new, deployed with one button as a single free Render service. What runs, the public demo login, the write rule that keeps it usable, the daily reset, and the free plan's limits."
---

# The shop demo

`examples/shop-demo` is the [shop recipe](recipes/shop.md) as `karni new "Shop
Demo" --recipe shop` builds it, plus the little code a public demo needs. It
deploys with one button as one service on Render's free plan. Anyone can sign
in with the demo login and try the API, the admin and the React app.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/cbsshekhawat18-lab/karni)

## Deploy it

1. Press the button (it is also near the top of the repository's README). Render
   reads `render.yaml` at the root of the repository and shows one web service,
   `karni-shop-demo`, on the free plan.
2. Sign in to Render, or create an account, and apply the Blueprint. Render
   generates the secret key, builds the image from `examples/shop-demo/Dockerfile`
   and starts it.
3. When the service is live, open its `onrender.com` address. The sign-in
   prompt shows the demo login.

The image installs the released packages: `karni` and `karni-payments` from
PyPI (`>=0.5,<0.6`, in `pyproject.toml`) and `@karni/ui` from npm (locked in
`frontend/package-lock.json`), not a checkout of this repository.

The Blueprint sets `autoDeployTrigger: off`, as Render advises for a deploy
button, so a push to the repository does not redeploy every copy. Redeploy by
hand from the Render dashboard to pick up a change.

## What runs

One container answers everything, so the demo needs no other service:

| Part | How the demo runs it | Setting |
|---|---|---|
| Web server | gunicorn with two uvicorn workers on `PORT` | `scripts/start.sh`, `WEB_CONCURRENCY` |
| API, admin, health checks | Django, as in every Karni project | |
| React app | built into the image for the site's root, served by Django and WhiteNoise | `KARNI_APP_PATH=/` (Dockerfile), `demo/views.py` |
| Static files | collected when the image is built, served by WhiteNoise | |
| Database | SQLite at `/data/db.sqlite3` on the instance | `DATABASE_URL` |
| Cache | files under `/data/cache`, shared by the workers | `CACHE_URL=filecache:///data/cache` |
| Celery tasks | run inside the request that queues them, no worker and no broker | `CELERY_TASK_ALWAYS_EAGER=True` |
| Readiness | the database and the cache, not the broker | `KARNI_READYZ_CHECKS`, `KARNI_HEALTH_CHECKS` |
| Payments | karni-payments' test provider: checkout opens, no money moves | `KARNI_PAYMENTS_PROVIDER=test` |

The container starts through Karni's deploy gate (`karni check --deploy`),
then `scripts/start.sh` runs `manage.py demo_boot` (migrate, then seed or
reset) and starts gunicorn. The service's health check is `/healthz`.

Measured on a Mac with the released packages: the gunicorn process used about
30 MB and each worker about 100 MB after a few requests. Render's free plan
gives 512 MB.

## The demo login

The sign-in prompt of the React app and the admin's sign-in page both show it:

- email `demo@example.com`
- password `karni-password`

It is the account `karni seed` makes: staff, superuser and every role the API
names. The page Django serves carries the login in meta tags while
`DEMO_MODE` is on (`demo/views.py`), and `frontend/src/demo.tsx` puts it above
Karni's own sign-in prompt through the `AuthGuard` slot.

## Who may write

`DEMO_MODE=True` turns on one rule, in `demo/guard.py`, for every request that
is not GET, HEAD, OPTIONS or TRACE:

| Caller | API | Admin |
|---|---|---|
| Anyone | may sign in, refresh a token, sign out and accept the terms | may sign in and sign out |
| Anonymous, or any account but the demo one | reads only: every write answers 403 `demo_read_only` | reads only: every change answers 403 |
| The demo account | writes everywhere except the account endpoints under `/api/auth/` (password, email, profile, the role matrix): 403 `demo_account_locked` | changes the shop's data, not the user and role tables or a password |

So sign-up is closed (`register/` and the sign-in codes of `otp/` are writes),
the payment webhook is closed, and the demo account cannot change its password,
email or roles or delete itself. The next visitor can always sign in. With
`DEMO_MODE` on, the settings also turn registration off
(`KARNI_ACCOUNTS_REGISTRATION=False`) and send sign-in codes only to existing
accounts.

The demo account has accepted the shop's terms, so the terms gate never stops a
visitor. Another account that signs in accepts them through the API, which is
open to every signed-in account because it is part of signing in.

The rule is a middleware of the demo project. Karni needed no new option for
it: the project's `MIDDLEWARE`, the `AuthGuard` slot and the admin's
`login_template` were enough.

## How the reset works

The data goes back to `karni seed --reset --seed 42` (`DEMO_SEED`) every 24
hours (`DEMO_RESET_HOURS`), without an outside scheduler:

1. **At boot.** `manage.py demo_boot` runs before the web server starts. A
   database without the demo account is seeded. Data older than 24 hours is
   reset. Otherwise the demo account is put back as the seed made it.
2. **While serving.** Each worker asks at most once a minute
   (`DEMO_RESET_CHECK_SECONDS`) whether the last reset, recorded in
   `/data/demo-reset.json`, is more than 24 hours old.
3. **Once.** A worker that finds the data due takes an exclusive, non-blocking
   lock on `/data/demo-reset.json.lock` and checks the time again under it.
   Another worker that asks meanwhile does not get the lock and skips the
   reset. So with any number of workers, one of them resets.
4. **In one transaction.** The reset deletes the rows of every app it does not
   keep, then runs the seed, then restores the demo account (its password, its
   flags and its acceptance of the terms). A worker reading at the same time
   sees the old rows or the new ones, never a mix. SQLite runs in WAL mode with
   `BEGIN IMMEDIATE` and a 20 second busy timeout, so a write that arrives
   during a reset waits for it. The database file is never replaced or deleted
   while the server runs, which is what could corrupt it.

The reset keeps the accounts, the roles, content types, sessions, the token
blacklist and the beat schedule (`DEMO_RESET_KEEP_APPS`). No visitor can change
an account, and keeping them keeps each worker's cached ids right. Everything
else goes: the shop's tables, payments, the change history, the admin log and
import jobs. With the same seed the rows come back with the same ids, so a link
to a product still works after a reset.

On the free plan the instance's disk is not kept either (below), so a restart
or a spin-down also starts from a fresh database, which the boot seeds.

## The free plan's limits

What Render's documentation said on 12 November 2026
([free instances](https://render.com/docs/free),
[instance types](https://render.com/docs/compute-plans),
[Blueprint reference](https://render.com/docs/blueprint-spec)):

- A free web service has 512 MB of memory and 0.1 CPU.
- It spins down after 15 minutes without traffic. The next request waits about
  a minute while it spins up, and the demo then boots from an empty database.
- Its filesystem is ephemeral and it cannot have a persistent disk. Render may
  restart it at any time. Each restart starts from an empty, freshly seeded
  database.
- A workspace gets 750 free instance hours a month.
- Free web services cannot send on ports 25, 465 or 587, so the demo sends no
  email (sign-up, password resets and sign-in codes are closed anyway).
- Cron jobs and background workers have no free instances, so the reset runs
  inside the web service.
- Free web services run one instance, with no shell access and no pre-deploy
  command.

Not confirmed in the documentation: whether the free plan's build has enough
memory for the React build (Karni's [deploy guide](deploy.md#1-a-server)
measured about 1.5 GB), and whether a `WEB_CONCURRENCY` set in the Blueprint
wins over the value Render sets for new services. With one worker instead of
two the demo works the same.

## Production settings

The service runs the production profile (`DJANGO_ENV=prod`): `DEBUG` off, HSTS,
secure cookies and the SSL redirect behind Render's proxy. `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS` and `KARNI_FRONTEND_URL` come from Render's
`RENDER_EXTERNAL_HOSTNAME` and `RENDER_EXTERNAL_URL` through the Blueprint.

Render generates each secret as a base64-encoded 256-bit value, 44 characters
long, and Karni's deploy check `karni.W511` asks for 50 or more. The Blueprint generates two
values, `SECRET_KEY` and `SECRET_KEY_PART_2`, and `config/settings.py` joins
them.

`karni check --deploy` passes with three warnings silenced while `DEMO_MODE` is
on, each on purpose:

| Check | Why the demo silences it |
|---|---|
| `karni.W516`, the admin at `/admin/` | The sign-in page shows the admin to every visitor, and its only account that can change anything is the public demo account. |
| `karni.W520`, email that never arrives | The demo sends no email: sign-up, password resets and sign-in codes are closed, and the free plan blocks the SMTP ports. |
| `karni.W964`, money and search on SQLite | SQLite is a choice for a demo that resets every day. Prices are exact to 15 significant digits, and product search matches the fields instead of a full-text index. |

A test in the demo project (`demo/tests/test_deploy.py`) builds the
environment from `render.yaml` the way Render fills it in and runs the deploy
gate, so a change that breaks it fails CI.

## Run it locally

```sh
cd examples/shop-demo
python3.12 -m venv .venv && .venv/bin/pip install -e . pytest pytest-django
(cd frontend && npm ci && npm run build)
PATH=$PWD/.venv/bin:$PATH PORT=8950 ./scripts/smoke.sh
```

`scripts/smoke.sh` sets production values with a generated key, starts the
exact start command behind the deploy gate on a fresh SQLite database, and
checks with curl: the sign-in pages, a read, a refused write, sign-up closed,
another account read-only, a write by the demo account and its refused
password change. CI runs it on every push, after the demo's tests.

To try the rules by hand, run the start command yourself with the variables of
`render.yaml` and `DEMO_MODE=True`:

```sh
python manage.py collectstatic --noinput
python -m karni.deploy.entrypoint sh scripts/start.sh
```

## After the first deploy

The repository README has a `<!-- live-demo-link -->` comment next to the
button. Replace it with a link to the deployed service once it is live.
