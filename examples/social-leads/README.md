# Social Leads

A leads/CRM module built on Karni as a practice project: a real product's data
model, endpoints, screens and workspace permission rule, written against
Karni's documented public surface only. It is used to learn from and to test
the framework. What Karni should have provided and did not is listed in
[FRICTION.md](FRICTION.md).

```sh
python3.12 -m venv .venv && .venv/bin/pip install -e ../../packages/karni -e ../../packages/karni-cli pytest pytest-django
cp .env.example .env && printf 'DATABASE_URL=sqlite:///data/db.sqlite3\nKARNI_CACHE=locmem\n' >> .env
.venv/bin/karni migrate && .venv/bin/karni seed && .venv/bin/karni test
```

What the project wrote: `crm/models.py` (workspace membership is each
model's `owner_field` path), `crm/viewsets.py`, `crm/services.py`,
`crm/tests/test_leads.py` (the four other test files are generated), the
`KARNI_ROLES` block in `config/settings.py`, and `frontend/src/pages/lead*.tsx`
with `frontend/src/components/`. Everything else below is the `karni new`
scaffold.

---

A [Karni](https://github.com/cbsshekhawat18-lab/karni) project: batteries-included Django + DRF +
Celery, configured almost entirely by `karni_settings(globals())` in
`config/settings.py`. Every Karni default can be overridden from that file.
Anything you assign after the call wins.

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
| `frontend` | Vite dev server (React + TS), proxies `/api` and `/health` to django | http://localhost:5173 |

Verify the stack (Postgres, Redis and Celery all checked):

```sh
curl http://localhost:8000/health/ready/
# {"status": "ok", "checks": {"database": ..., "cache": ..., "celery": ...}}
```

Other endpoints: liveness at `/health/`, admin at `/admin/`, OpenAPI schema at
`/api/schema/`, Swagger UI at `/api/docs/`.

## Frontend

`frontend/` is Vite + React + TypeScript on [@karni/ui](https://github.com/cbsshekhawat18-lab/karni/tree/main/packages/karni-ui).
`src/App.tsx` mounts `KarniProvider` (one `createKarniClient({ baseUrl: "/api" })`),
`AuthProvider`, the router and a `Toaster`. `src/main.tsx` imports
`@karni/ui/styles.css` (the `--karni-*` design tokens) and `src/index.css`
(Tailwind v3 with the `@karni/ui/tailwind-preset`, see `tailwind.config.ts`).
Every route renders inside `src/layout.tsx`, which is @karni/ui's `Layout` with one
nav entry per static route in `src/routes.tsx`, so pages from
`karni make page` (or `karni make model ... -a`) appear in the sidebar.

```sh
cd frontend
npm install
npm run dev     # http://localhost:5173, proxies /api and /health to Django
npm run build   # tsc + vite build into frontend/dist
npm run lint    # ESLint with the karni/* enforcement rules
```

The dev server proxies to `http://127.0.0.1:8000` (`karni serve --local`).
Docker compose sets `KARNI_API_PROXY=http://django:8000` for its container.

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
copy is a snapshot: a plain `npm install` does not notice a rebuilt checkout.
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
or `KARNI_CACHE=locmem` to run without Redis at all), and settings.py loads
it automatically. Variables you already exported win, and
`KARNI_DOTENV=false` skips the file. Then run `karni serve --local` for Django
and `npm run dev` in `frontend/`. Run `karni worker` only when something needs
Celery:

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

Generate code with `karni make`. `karni make --list` shows every generator,
and each one runs through the project's `.venv` or the running compose service
where it needs Django:

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

`karni new` generated thin agent adapters: `AGENTS.md`, `CLAUDE.md`,
`.cursor/rules/karni.mdc`, `.windsurf/rules/karni.md`,
`.github/copilot-instructions.md`, `.clinerules/karni.md`, `CONVENTIONS.md`,
`.junie/AGENTS.md` and slash commands. They all say the same thing: run
`karni context` and `karni rules` first. Do not edit them. Put project rules
in `karni.rules.py` and run `karni rules sync` (`make check` fails when they
are stale). `karni mcp` serves the same surface over MCP.

## Production

The `prod` Dockerfile target builds a slim, non-root image that runs
`gunicorn config.asgi:application` with uvicorn workers and collects static
files to `/data/static` at build time:

```sh
docker build --target prod -t social_leads:latest .
```

Run it with `DJANGO_ENV=prod`, a real `SECRET_KEY` and `ALLOWED_HOSTS`.
Karni validates the configuration at startup and fails loudly on anything
insecure or missing. Put Caddy in front using the provided `Caddyfile`: it
provisions TLS for `$DOMAIN` automatically, serves `/static/*` and `/media/*`
from `/data` (share the `/data` volume between the django container and
Caddy), and reverse-proxies everything else to `django:8000`. For the
frontend, `npm run build` in `frontend/` produces static assets you can serve
from Caddy or any CDN.
