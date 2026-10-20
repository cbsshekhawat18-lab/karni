---
description: Install Karni, scaffold a project, add a model, migrate, seed demo data and run it locally with Python 3.12 and Node 24.
---

# Quickstart

Ten minutes from an empty directory to a running app with real data, no
Docker required. Every command on this page is run verbatim by CI
(`.github/ci/quickstart.py`), so it works on a clean machine or the build
fails.

You need Python 3.12+ and Node 20.19+ (Node 24 LTS recommended).

## 1. Install Karni and create a project

<!-- karni:quickstart -->
```sh
python3 -m venv .venv && . .venv/bin/activate
pip install karni karni-cli pytest pytest-django
karni new "Ticket Shop" && cd ticket_shop
cp .env.example .env
printf 'DATABASE_URL=sqlite:///data/db.sqlite3\nKARNI_CACHE=locmem\nMEDIA_ROOT=data/media\nSTATIC_ROOT=data/static\n' >> .env
```

`karni new` wrote a Django project configured by one call
(`karni_settings(globals())`), a Vite + React frontend on `@karni/ui`, a
docker-compose stack with a Makefile, and the guidance files AI coding
agents read. The four `.env` lines point it at SQLite, an in-process cache
and a local media folder for this walk-through, so nothing on this page
needs PostgreSQL or Redis; the defaults expect the compose stack's. pytest
and pytest-django are the project's dev dependencies (`karni test` runs
them); they go into the same venv.

## 2. Add a domain

<!-- karni:quickstart -->
```sh
karni make app events
karni make model Venue name:str:200 city:str:100 capacity:int --with viewset,test --access public-read
karni make model Event title:str:200 description:text starts_at:datetime ends_at:datetime \
    "status:choice:draft|published" organizer:fk:User venue:fk:Venue -a --access owned:organizer
karni make migration --app events
karni migrate
karni make page login --kind login
```

Two models, declared on the command line, became: the models on
`karni.models.BaseModel`; two REST resources with filtering, search,
pagination and `?expand=`; the `access` declarations that decide who reads
and writes what; admin pages; list, detail and form screens; and one test file
per resource. The last command adds a sign-in page at `/login`: a new
project has none until you ask for one.

## 3. Seed, test, run

<!-- karni:quickstart -->
```sh
karni seed
karni test
karni check --no-frontend
```

`karni seed` filled every table with realistic, connected rows and printed a
demo login. `karni test` ran the generated tests — `assert_crud` proves the
whole API surface of each resource and `assert_isolated` proves one organizer
cannot reach another's events. `karni check` ran the architecture rules
(`--no-frontend` only until the next step installs the frontend's
dependencies; plain `karni check` is what CI runs).

Now serve it:

```sh
karni serve --local                  # Django on http://127.0.0.1:8000
cd frontend && npm install && npm run dev   # the app on http://localhost:5173
```

Open `http://127.0.0.1:8000/` first: Karni's welcome page, generated from
the project as it is right now — your models with their admin and API
links, seven status checks (database, migrations, superuser, seed data,
Redis, worker, frontend) each with the command that fixes a cross, the live
`karni context` output and the first prompt to hand an agent. It is served
only while `DEBUG` is on and disappears the moment you define your own
`/` route. The Redis and worker checks stay crosses on this page's `.env`:
nothing here needs them. When you want Celery (e-mails, scheduled tasks,
`/health/ready/` all green), point `REDIS_URL` at a Redis, drop the
`KARNI_CACHE` line and run `karni worker` in a third shell.

Open `http://localhost:5173/login` and sign in with the demo login `karni seed`
printed (`demo@example.com` / `karni-password`), open **Events**, create one, and look at
`http://127.0.0.1:8000/api/docs/` for the OpenAPI document everything was
generated from, and `/admin/` for the admin that needed no `admin.py`.

## What just happened

You wrote no serializer, no permission class, no admin, no form, no table,
no factory and no test scaffolding; the two commands in step 2 declared the
domain and the framework did the rest. From here:

- the [tutorial](tutorial.md) builds the reference app, EventHub, with
  payments, a Celery email and four roles, in 593 lines of project code;
- [Building with an AI agent](guide/with-ai.md) shows the same workflow
  driven by Claude Code or Cursor;
- [Building without one](guide/without-ai.md) lists every `karni make`
  command.

## Using a Karni checkout instead of PyPI

To try changes that are not released yet, replace the `pip install` line
with editable installs from a checkout and let `karni new` find `@karni/ui`
in it:

```sh
pip install -e /path/to/Karni/packages/karni -e /path/to/Karni/packages/karni-cli
export KARNI_UI_SRC=/path/to/Karni/packages/karni-ui   # built once with npm run build
```

That is exactly what CI does for this page.
