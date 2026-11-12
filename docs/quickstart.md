---
description: Install Karni, scaffold a project, add a model, migrate, seed demo data and run it locally with Python 3.12 and Node 24.
---

# Quickstart

Ten minutes from an empty directory to a running app with real data, on
PostgreSQL. Every command on this page is run verbatim by CI
(`.github/ci/quickstart.py`), so it works on a clean machine or the build
fails.

You need Python 3.12+, Node 20.19+ (22.12+ on Node 22, Node 24 LTS
recommended) with the npm it bundles, and Docker, which runs the database.
Without Docker, a PostgreSQL installed on the machine works too: see
[Without Docker](#without-docker) below.

## 1. Install Karni and create a project

<!-- karni:quickstart -->
```sh
python3 -m venv .venv && . .venv/bin/activate
pip install karni karni-cli pytest pytest-django
karni new "Ticket Shop" && cd ticket_shop
cp .env.example .env
docker compose up -d --wait db
printf 'DATABASE_URL=postgres://karni:karni@localhost:5432/karni\nKARNI_CACHE=locmem\n' >> .env
```

`karni new` wrote a Django project configured by one call
(`karni_settings(globals())`), a Vite + React frontend on `@karni/ui`, a
docker-compose stack with a Makefile, and the guidance files AI coding
agents read, and made the folder a git repository with a first commit
(`--no-git` skips it). Run in a terminal, `karni new` first asks what kind of project
it is: Enter takes `app`, this page's kind, and `--kind app` skips the
question (`--kind site` makes a public website, see
[start a site project](public-site.md#start-a-site-project)). `docker compose up -d --wait db` starts the project's
PostgreSQL 16 from that stack, published on localhost only (set
`KARNI_DB_PORT` in `.env` when port 5432 is taken). The two `.env` lines point
the app at it and at an in-process cache instead of Redis. Uploads go to
`data/media` in the project, which git ignores. pytest and pytest-django are the project's dev dependencies
(`karni test` runs them), and they go into the same venv.

PostgreSQL is Karni's default and the database it is built and tested for:
range columns, `EXCLUDE` constraints, trigram search and advisory locks exist
only there. Without Docker, use a PostgreSQL installed on the machine (the
[Without Docker](#without-docker) section below) or, to try Karni with no
server at all, SQLite: leave out the `docker compose` line and use
`DATABASE_URL=sqlite:///data/db.sqlite3` in the `printf` line. Karni's system
checks say which guarantees SQLite cannot give.

### Without Docker

A PostgreSQL and a Redis installed on the machine replace the compose
services. On macOS with Homebrew:

```sh
brew install postgresql@16 redis
brew services start postgresql@16
brew services start redis
```

On Debian or Ubuntu: `sudo apt install postgresql redis-server` (both start
as services). Homebrew's PostgreSQL creates a superuser role named after
your account, so the database URL needs no password. Point the project at the
two services and create its database, then continue with step 2:

```sh
karni new "Ticket Shop" && cd ticket_shop
cp .env.example .env
printf 'DATABASE_URL=postgres://%s@127.0.0.1:5432/ticket_shop\nREDIS_URL=redis://127.0.0.1:6379/0\n' "$USER" >> .env
createdb ticket_shop
```

`karni doctor` looks for a PostgreSQL and a Redis on the machine and prints
these two `.env` lines, with your user and the project's name, whenever
`.env` still names the compose hosts `db` and `redis`. With a local Redis,
`.env` needs no `KARNI_CACHE=locmem` line, and `karni worker` runs the
Celery worker when something needs it. On Debian or Ubuntu, the `postgres`
system user owns the server: `sudo -u postgres createuser -s "$USER"` once,
then `createdb` as above.

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

From two models declared on the command line, Karni produced the models on
`karni.models.BaseModel` and two REST resources with filtering, search,
pagination and `?expand=`. It also produced the `access` declarations that
decide who reads and writes what, admin pages, the list, detail and form
screens, and one test file per resource. `--access public-read` printed
`access: Access(read=Public(), write=HasRole("staff"))`: anyone may read
venues, and only the `staff` role may change them (`public-read:<role>` names
another role). `--access owned:organizer` lets each organizer change only
their own events. The last command adds a sign-in page at `/login`: a new
project has none until you ask for one.

## 3. Seed and test

<!-- karni:quickstart -->
```sh
karni seed
karni test
karni check --no-frontend
```

`karni seed` filled every table with realistic, connected rows and printed a
demo login. `karni test` ran the generated tests: `assert_crud` proves the
whole API surface of each resource (the venue test acts as `staff`, the role
that may write) and `assert_isolated` proves one organizer cannot reach
another's events. `karni check` ran the architecture rules.
`--no-frontend` is needed only until the next step installs the frontend's
dependencies, and plain `karni check` is what CI runs.

## 4. Install the frontend

<!-- karni:quickstart -->
```sh
cd frontend && npm install && cd ..
karni check
```

`npm install` works on npm 10.8 or later: npm 10, which Node 20.19 and Node
22 bundle, and npm 11, which Node 24 bundles. It installs the versions
`frontend/package-lock.json` pins. The lock leaves out `@karni/ui`, which npm
resolves and adds, so commit the lock it writes. `karni doctor` shows your
Node and npm and flags either one when it is too old.

The project's `frontend/package.json` declares the Node and npm it needs in
`engines`, and `frontend/.npmrc` sets `engine-strict`, so an older Node or npm
stops with `EBADENGINE` instead of installing.

Plain `karni check` now runs the frontend checks too: ESLint with
`@karni/ui`'s rules, and jscpd for duplicated code.

## 5. Run it

```sh
karni serve --local                  # Django on http://127.0.0.1:8000
cd frontend && npm run dev           # the app on http://localhost:5173
```

When port 8000 is taken, put `KARNI_DEV_PORT=8020` in `.env`: `karni serve
--local` runs Django on that port and the frontend's dev server proxies
`/api` to it, so nothing else changes.

Open `http://127.0.0.1:8000/` first. It is Karni's welcome page, generated
from the project as it is right now. It shows your models with their admin
and API links, seven status checks (database, migrations, superuser, seed data,
Redis, worker, frontend) each with the command that fixes a cross, the live
`karni context` output and the first prompt to hand an agent. It wears the
same brand as the admin and the React app (`@karni/ui`'s design tokens,
light or dark as your system is set). It is served only while `DEBUG` is on
and disappears the moment you define your own `/` route. The Redis and worker checks stay crosses on this page's `.env`:
nothing here needs them. When you want Celery (e-mails, scheduled tasks,
`/health/ready/` all green), point `REDIS_URL` at a Redis, drop the
`KARNI_CACHE` line and run `karni worker` in a third shell.

Open `http://localhost:5173/login` and sign in with the demo login `karni seed`
printed (`demo@example.com` / `karni-password`), open **Events**, create one, and look at
`http://127.0.0.1:8000/api/docs/` for the OpenAPI document everything was
generated from, and `/admin/` for the admin that needed no `admin.py`.

## What just happened

You wrote no serializer, no permission class, no admin, no form, no table,
no factory and no test scaffolding. The two commands in step 2 declared the
domain, and the framework did the rest. From here:

- The [tutorial](tutorial.md) builds the reference app, EventHub, with
  payments, a Celery email and four roles, in 617 lines of project code.
- [Building with an AI agent](guide/with-ai.md) shows the same workflow
  driven by a coding agent.
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
