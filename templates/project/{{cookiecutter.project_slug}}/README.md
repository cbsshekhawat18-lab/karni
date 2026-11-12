# {{ cookiecutter.project_name }}

A [Karni](https://github.com/cbsshekhawat18-lab/karni) project: batteries-included Django + DRF +
Celery, configured almost entirely by `karni_settings(globals())` in
`config/settings.py`. Every Karni default can be overridden from that file.
Anything you assign after the call wins.

## What this project is

{% if cookiecutter.kind == "site" -%}
A public website (`kind = "site"` in pyproject.toml): a site app of Django views
and templates on the [karni-site](https://github.com/cbsshekhawat18-lab/karni/tree/main/modules/karni-site)
module, at `/`. The client changes every text, image, menu, contact detail and
page title in the admin, as staff or with the `editor` role. Nobody signs up:
staff create the accounts.
{%- if cookiecutter.staff_app == "yes" %} The staff app in `frontend/` is for staff, such as the
requests a public form collects.
{%- else %} There is no React staff app: staff work in the admin.
{%- endif %}
{%- elif cookiecutter.kind == "site+app" -%}
A public website and an app (`kind = "site+app"` in pyproject.toml): a site app
of Django views and templates on the [karni-site](https://github.com/cbsshekhawat18-lab/karni/tree/main/modules/karni-site)
module at `/`, edited in the admin, and a REST API with the React app in
`frontend/` for signed-in users.
{%- else -%}
An app (`kind = "app"` in pyproject.toml): a REST API and the React app in
`frontend/` for signed-in users. `karni add site` adds a public website.
{%- endif %}

## Quickstart

```sh
cp .env.example .env
docker compose up --build
```

This boots:

| Service    | What                                            | Where                  |
| ---------- | ----------------------------------------------- | ---------------------- |
| `django`   | migrations, then Django dev server              | http://localhost:8000  |
| `db`       | postgres:16                                     | internal (`db:5432`)   |
| `redis`    | redis:7 (Celery broker + cache)                 | internal (`redis:6379`)|
| `worker`   | Celery worker                                   | none                   |
| `beat`     | Celery beat (django-celery-beat DB scheduler)   | none                   |
{%- if cookiecutter.staff_app == "yes" %}
| `frontend` | Vite dev server (React + TS), proxies `/api` and `/health` to django | http://localhost:5173 |
{%- endif %}

Verify the stack (Postgres, Redis and Celery all checked):

```sh
curl http://localhost:8000/health/ready/
# {"status": "ok", "checks": {"database": ..., "cache": ..., "celery": ...}}
```

Probes: `/healthz` (the process answers) and `/readyz` (database, cache and broker).
Other endpoints: liveness at `/health/`, admin at `/admin/`, OpenAPI schema at
`/api/schema/`, Swagger UI at `/api/docs/`.
{%- if cookiecutter.staff_app == "yes" %}

## Frontend

`frontend/` is Vite + React + TypeScript on [@karni/ui](https://github.com/cbsshekhawat18-lab/karni/tree/main/packages/karni-ui).
`src/App.tsx` mounts `KarniProvider` (one `createKarniClient({ baseUrl: "/api" })`),
`AuthProvider`, the router and a `Toaster`. `src/main.tsx` imports
`@karni/ui/styles.css` (the `--karni-*` design tokens) and `src/index.css`
(Tailwind 4 with the `@karni/ui/tailwind-preset`, loaded through `@config` from `tailwind.config.ts`).
Every route renders inside `src/layout.tsx`, which is @karni/ui's `Layout` with one
nav entry per static route in `src/routes.tsx` (`routeNavItems`). That is how pages from
`karni make page` (or `karni make model ... -a`) appear in the sidebar. Every page but
a sign-in page sits behind `AuthGuard`, so a visitor who is not signed in sees the
sign-in prompt, and `src/pages/home.tsx` is the dashboard: counts and the newest rows
of every model that declares `class Karni: dashboard = {...}`. The admin wears the
same brand as the app: `karni ui detect` (or `karni ui detect --css <stylesheet>`)
writes `src/karni-theme.css`, and `KARNI_THEME_CSS` serves it to the admin too.

```sh
cd frontend
npm install     # Node 20.19+ and npm 10.8+, from package-lock.json
npm run dev     # http://localhost:5173, proxies /api and /health to Django
npm run build   # tsc + vite build into frontend/dist
npm run lint    # ESLint with the karni/* enforcement rules
```

The dev server proxies to `http://127.0.0.1:8000`, where `karni serve
--local` runs Django. When port 8000 is taken, set `KARNI_DEV_PORT=8020` in
`.env`: `karni serve --local` and the dev server both read it, and docker
compose publishes Django on it. For its container, docker compose sets
`KARNI_API_PROXY=http://django:8000`, which wins over `KARNI_DEV_PORT`.
`karni serve --local --port 8030` prints how to point the dev server at that
port: `cd frontend && KARNI_API_PROXY=http://127.0.0.1:8030 npm run dev`.

`package-lock.json` pins every package but @karni/ui, which the first `npm
install` resolves and adds. Commit the lock it writes. Without a lock, npm
before 11.6 can crash while it resolves Vite's optional peers (`Cannot read
properties of null (reading 'edgesOut')`), so keep it: after removing it, run
the next install with npm 11.6 or later (`npx --yes npm@11 install`).
{%- endif %}

## Using a local Karni checkout

Until karni and @karni/ui are published, a project can run against a Karni
checkout.

**@karni/ui.** `karni new` resolves it like the project template:
`KARNI_UI_SRC=/path/to/Karni/packages/karni-ui` > the Karni checkout `karni`
itself runs from > the npm release (`^0.1.0`). A local source is written into
`frontend/package.json` as `"@karni/ui": "file:/abs/path/to/packages/karni-ui"`,
and `frontend/.npmrc` (`install-links=true`) installs it as a packed copy,
exactly like the npm release, so React and TanStack Query exist once. The copy
ships the checkout's built `dist/` (`karni new` builds it when missing). The
copy is a snapshot. A plain `npm install` does not notice a rebuilt checkout.
After changing @karni/ui, rebuild it and refresh the copy:

```sh
(cd /path/to/Karni/packages/karni-ui && npm run build)
(cd frontend && rm -rf node_modules/@karni/ui && npm install)
# docker compose: docker compose exec frontend rm -rf node_modules/@karni/ui
#                 docker compose restart frontend
```

Under docker compose the `frontend` container runs `npm install` on start and
gets the checkout mounted read-only at the same absolute path, so the `file:`
spec resolves inside the container too (the mount is in `docker-compose.yml`
when `karni new` found a local @karni/ui). The container ignores
`package-lock.json`, which records the checkout relative to the host's
`frontend/`. Moving the checkout means updating both `frontend/package.json`
and that mount, or running `karni new` again.

Without Docker, run everything on the host. Install the project's own
dependencies into the venv first (`pip install -e . pytest pytest-django`:
that is what brings `psycopg` for a host PostgreSQL, and pytest for
`karni test`). Point `.env` at local services
(`DATABASE_URL=sqlite:///db.sqlite3`, `REDIS_URL=redis://127.0.0.1:6379/0`,
or `KARNI_CACHE=locmem` to run without Redis at all), and settings.py loads it
automatically (variables you already exported win, and `KARNI_DOTENV=false`
skips it). Then run `karni serve --local` for Django and `npm run dev` in
`frontend/`, plus `karni worker` only when something needs Celery:

```sh
karni migrate && karni serve --local    # http://127.0.0.1:8000
(cd frontend && npm run dev)            # http://localhost:5173, in a second shell
```

**karni (Python).** For the host `.venv` (`karni serve --local`,
`karni migrate`, ...), install the checkout next to the project's other
dependencies:

```sh
uv venv && uv pip install -e /path/to/Karni/packages/karni -r pyproject.toml
```

For Docker, vendor a checkout into the project and point the `KARNI_SRC`
build arg at it (docker-compose reads it from `.env`):

```sh
cp -r /path/to/Karni/packages/karni ./.karni-src
echo "KARNI_SRC=.karni-src" >> .env   # or edit the existing line
docker compose build
```

`KARNI_SRC` must be a path inside this project (the Docker build context).
The vendored copy is installed before the PyPI dependencies, so it takes
precedence.

## Day-to-day

Generate code with `karni make` (`karni make --list` shows every generator,
and each runs through the project's `.venv` or the running compose service where
it needs Django):

```sh
karni make app events                       # replaces manage.py startapp; wires INSTALLED_APPS
karni make model Event title:str:200 starts_at:datetime organizer:fk:User -a \
    --access owned:organizer                # model + viewset + list/detail/form pages
karni make migration && karni migrate
karni createsuperuser
```

Override any Django, DRF, Celery or Karni setting in `config/settings.py`,
below the `karni_settings()` call. Generators add apps to the `# karni:apps`
block and middleware to the `# karni:middleware` block, so keep those markers.

## AI coding agents

`karni new` generated `AGENTS.md`, the instructions coding agents read. It
says to run `karni context` and `karni rules` first, lists the procedures for
routine tasks, and reads a request that starts with `/new-app` (or another
procedure's name) as that procedure. Do not edit it. Put project rules in
`karni.rules.py` and run `karni rules sync` (`make check` fails when it is
stale). `karni mcp` serves the same surface over MCP.

Optional: to keep the prompts behind your code, install
[Gigai Chronicle](https://github.com/cbsshekhawat18-lab/gigai-chronicle)
(`npm install -g gigai-chronicle`, then `chronicle init` in this folder). It
records every prompt you give an agent inside this repository, and
`karni context --with-history <file>` reads it back to brief the next agent.
It is MIT licensed, local-only, and made by Karni's author.

## Production

`docker-compose.prod.yml` is the production stack: a one-shot `release`
service (the deploy checks, migrations, `collectstatic`, the web server's
files), `django` (gunicorn with uvicorn workers), Celery `worker` and `beat`,
`caddy` (automatic TLS for `DOMAIN`, static and media files, the staff app at
`/app/`, everything else proxied to Django), `db`, `redis` and `backup`
(database and media, on a schedule, with retention). On a server with Docker:

```sh
cp .env.prod.example .env.prod      # fill in every empty value, never commit it
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Every container from the `prod` image runs `karni check --deploy` before its
command, and refuses to start while a value is unsafe (E520).
`KARNI_SKIP_DEPLOY_CHECK=1` starts it anyway in an emergency, logged on every
start. The staff app in `frontend/` is built into the image and served by
Caddy, with the same security headers Django sends.

[Deploying to a server](https://cbsshekhawat18-lab.github.io/karni/deploy/)
covers DNS, TLS, the first superuser, updates without failed requests,
rollback, logs, backups and restore. `karni make deploy compose --force`
rewrites the three files with other choices: the staff app on another path or
host (`--app-path`, `--app-domain`), no Celery, a managed database or Redis,
no backups.
