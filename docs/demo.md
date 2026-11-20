---
description: "The shop demo: the shop recipe built by karni new, deployed with one button as a single free Render service. What runs, the public demo logins, the write rule that keeps it usable, the daily reset, and the free plan's limits."
---

# The shop demo

`examples/shop-demo` is the [shop recipe](recipes/shop.md) as `karni new "Shop
Demo" --recipe shop` builds it, plus its demo settings and two demo accounts.
The rules that make a project safe to publish (who may write, the reset, the
boot command, the sign-in notice) are Karni's own [demo mode](demo-mode.md), so
the demo has no code of its own for them. It deploys with one button as one
service on Render's free plan. Anyone can sign in with a demo login and try the
API, the admin and the React app.

**Live demo:** [karni-shop-demo.onrender.com](https://karni-shop-demo.onrender.com/). Sign in as
`demo@example.com` with the password `karni-password`. The free plan stops the
service after 15 idle minutes, so the first page can take a minute to wake.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/cbsshekhawat18-lab/karni)

## Deploy it

1. Press the button (it is also near the top of the repository's README). Render
   reads `render.yaml` at the root of the repository and shows one web service,
   `karni-shop-demo`, on the free plan.
2. Sign in to Render, or create an account, and apply the Blueprint. Render
   generates the secret key, builds the image from `examples/shop-demo/Dockerfile`
   and starts it.
3. When the service is live, open its `onrender.com` address. The sign-in
   prompt shows the demo logins.

The image installs the released packages: `karni` and `karni-payments` from
PyPI (`karni>=0.6.0,<0.7`, in `pyproject.toml`) and `@karni/ui` from npm (locked in
`frontend/package-lock.json`), not a checkout of this repository.

The demo uses Karni's [demo mode](demo-mode.md), which first ships in 0.6.0,
so the image needs `karni>=0.6.0` and `@karni/ui` 0.6.0 or later. Until 0.6.0 is
released, a build from the repository fails at `pip install`. After the release,
run `npm install @karni/ui@^0.6.0` in `examples/shop-demo/frontend` to move its
lock file to the release, commit the lock, then redeploy by hand. The
`render.yaml` variables did not change.

The Blueprint sets `autoDeployTrigger: off`, as Render advises for a deploy
button, so a push to the repository does not redeploy every copy. Redeploy by
hand from the Render dashboard to pick up a change.

## What runs

One container answers everything, so the demo needs no other service:

| Part | How the demo runs it | Setting |
|---|---|---|
| Web server | gunicorn with two uvicorn workers on `PORT` | `scripts/start.sh`, `WEB_CONCURRENCY` |
| API, admin, health checks | Django, as in every Karni project | |
| React app | built into the image for the site's root, served by Django and WhiteNoise | `KARNI_APP_PATH=/` (Dockerfile), `karni.demo.urls.app_urls()` |
| Static files | collected when the image is built, served by WhiteNoise | |
| Database | SQLite at `/data/db.sqlite3` on the instance | `DATABASE_URL` |
| Cache | files under `/data/cache`, shared by the workers | `CACHE_URL=filecache:///data/cache` |
| Celery tasks | run inside the request that queues them, no worker and no broker | `CELERY_TASK_ALWAYS_EAGER=True` |
| Readiness | the database and the cache, not the broker | `KARNI_READYZ_CHECKS`, `KARNI_HEALTH_CHECKS` |
| Payments | karni-payments' test provider: checkout opens, no money moves | `KARNI_PAYMENTS_PROVIDER=test` |

The container starts through Karni's deploy gate (`karni check --deploy`),
then `scripts/start.sh` runs `manage.py karni_demo_boot` (migrate, then seed or
reset) and starts gunicorn. The service's health check is `/healthz`.

Measured on a Mac with the released packages: the gunicorn process used about
30 MB and each worker about 100 MB after a few requests. Render's free plan
gives 512 MB.

## The demo logins

The sign-in prompt of the React app and the admin's sign-in page both list them,
with what each can do. Both use the password `karni-password`:

| Login | Role | What it can do |
|---|---|---|
| `demo@example.com` | Staff, a superuser | Manage categories, products, carts and orders, and open the admin. |
| `customer@example.com` | Customer | Fill a cart, check out with the test provider and read their own orders. |

`config/settings.py` lists them in `KARNI_DEMO_ACCOUNTS`. The staff account is
the one `karni seed` makes. `GET /api/demo/` gives the list to
`DemoSignInPrompt` from `@karni/ui`, which `frontend/src/layout.tsx` puts above
Karni's own sign-in prompt through the `AuthGuard` slot. Each account is locked
against changing its password, email or roles, and against deleting itself.

## Who may write

`DEMO_MODE=True` turns on the write rule of [demo mode](demo-mode.md#who-may-write)
for every request that is not GET, HEAD, OPTIONS or TRACE:

| Caller | API | Admin |
|---|---|---|
| Anyone | may sign in, refresh a token, sign out and accept the terms | may sign in and sign out |
| Anonymous, or any account that is not a demo account | reads only: every write answers 403 `demo_read_only` | reads only: every change answers 403 |
| A demo account | writes what the shop's own access rules allow, except the account endpoints under `/api/auth/` (password, email, profile, the role matrix): 403 `demo_account_locked` | changes the shop's data (staff only), not the user and role tables or a password |

So sign-up is closed (`register/` and the sign-in codes of `otp/` are writes),
the payment webhook is closed, and a demo account cannot change its password,
email or roles or delete itself. The next visitor can always sign in. With
`DEMO_MODE` on, `config/settings.py` also turns registration off
(`KARNI_ACCOUNTS_REGISTRATION=False`) and sends sign-in codes only to existing
accounts.

Both demo accounts have accepted the shop's terms, so the terms gate never stops
a visitor. Another account that signs in accepts them through the API, which is
open to every signed-in account because it is part of signing in.

## How the reset works

The data goes back to `karni seed --reset --seed 42` (`DEMO_SEED`) every 24
hours (`DEMO_RESET_HOURS`), without an outside scheduler. The mechanism is the
one in [demo mode](demo-mode.md#the-reset): a boot step, a check by each worker
at most once a minute, one worker under a lock, one transaction, and SQLite in
WAL mode with `BEGIN IMMEDIATE` and a 20 second busy timeout (set in
`config/settings.py`).

For the shop, the reset keeps the accounts, the roles, content types, sessions,
the token blacklist and the beat schedule. Everything else goes: the shop's
tables, payments, the change history, the admin log and import jobs. With the
same seed the rows come back with the same ids, so a link to a product still
works after a reset. Both demo accounts are put back with their password,
flags, roles and accepted terms.

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

Shown by the first deploy of this Blueprint, on 12 November 2026:

- A Docker service runs on the free plan.
- The free plan's build finished the React build.
- A service can copy its own `RENDER_EXTERNAL_HOSTNAME` and
  `RENDER_EXTERNAL_URL` into other variables: the site answers on its address,
  and signing in to the admin passes the CSRF origin check.

Still not confirmed:

- Whether a `WEB_CONCURRENCY` set in the Blueprint wins over the value Render
  sets for new services. With one worker instead of two the demo works the same.

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

A test in the demo project (`tests/demo/test_deploy.py`) builds the
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
checks with curl: the sign-in pages and `/api/demo/`, a read, a refused write,
sign-up closed, an account that is not a demo account read-only, a write by each
demo account and its refused password change. CI runs it on every push, after the demo's tests.

To try the rules by hand, run the start command yourself with the variables of
`render.yaml` and `DEMO_MODE=True`:

```sh
python manage.py collectstatic --noinput
python -m karni.deploy.entrypoint sh scripts/start.sh
```

## After the first deploy

The repository README links the deployed service as "Live demo", next to the
button. A deployment of your own has its own address: change that link in your
copy.
