---
description: "Apps and games in Karni: the kinds karni new makes (site, app, site+app, game, app+game), what each one installs, what an app and a game share (sign-in, people, the admin, the API, events, deploy), the layout of a game-first project, how a game is served at /play/<slug>/, and how a project made with 0.6.0's --kind game reads now."
---

# Apps and games

!!! warning "Experimental"
    The game kinds (`game` and `app+game`), the `game/<slug>/` layout and
    `/play/<slug>/` are [experimental](stability.md#experimental-names):
    their names may change in a minor release, with a CHANGELOG entry.

Karni makes web apps and web games. The two sides are peers: each is a set of
opt-in packages on one shared base, and neither depends on the other. A
project is an app, a game, or both, and `karni new --kind` says which.

## What each kind installs

| Project | `karni new --kind` | Python | npm | Services |
|---|---|---|---|---|
| A public website | `site` | `karni`, `karni-site` | `@karni/ui` in `frontend/`, unless `--no-staff-app` | web, worker, database, Redis |
| An app | `app` | `karni` and the modules you add | `@karni/ui` in `frontend/` | web, worker, database, Redis |
| Both | `site+app` | `karni`, `karni-site` | `@karni/ui` in `frontend/` | the same |
| A game first | `game` | `karni`, `karni-game` | `@karni/game` in `game/<slug>/`, and `@karni/ui` in `frontend/` only with `--staff-app` | web (the API and the admin), worker, database, Redis |
| An app with a game in it | `app+game` | `karni`, `karni-game` | `@karni/ui` and `@karni/game` in `frontend/` | the same, one database |

A project made without a game kind names neither `karni-game` nor
`@karni/game`, and nothing in its Dockerfile, Compose files or Caddyfile
builds or serves a game. A game-first project has no React staff app unless
`--staff-app` asks for one: the Django admin has the game's screens (players,
boards, flagged runs, wallets and the ledger, [the admin](game.md#the-admin-and-the-roles)),
so staff work there.

## What an app and a game share

| The shared base | What the app side uses it for | What the game side uses it for |
|---|---|---|
| Accounts and sign-in (core) | staff and customers | a guest who keeps their progress by signing in |
| [People](people.md) (`karni.people`) | customers, contacts | a player is a person, and merge and erase reach the player |
| The admin, roles, the API conventions and error codes | every resource | games, players, scores, wallets |
| [Family events](family-events.md), the timeline, notifications, preferences | the app's events and messages | `game.*` events, unlock messages, Settings, Games |
| [Content loading](content-loading.md) (`karni load`) | seed and reference data | the game's declared rows (`content/game.yaml`) |
| [Commerce](commerce.md) (an optional module) | carts and orders | real-money items (`game_item`) |
| Deploy, the CLI, the agent rules, these docs | one stack | the same stack, plus the game's build |

A project with both has one sign-in, one person per human, one set of roles,
one database and one web front.

## A game first: `--kind game`

```sh
karni new "Block Hopper" --kind game
```

```text
pyproject.toml          kind = "game", karni and karni-game
config/                 settings and urls: the shared base
games/                  the Django app: the game's server hooks (game.py) and server tests
game/block-hopper/      the game, its own npm package on @karni/game
  index.html            the page
  src/main.ts           the page's code: the canvas, the status line, the ad button
  src/play.ts           the canvas, the loop and the input
  src/session.ts        the portal, the data client, what a finished run reports
  src/rules/            the rules: plain functions of a seed and the inputs
  tests/                the rules' tests, headless (npm test)
  vite.config.ts        karniGame({ devBase: "/play/block-hopper/" })
content/game.yaml       the game declared on the server (karni load content/game.yaml)
```

The game is the project's front door. It is served at `/play/<slug>/`, and `/`
goes there. The admin is at `KARNI_ADMIN_PATH` and the API at `/api/`, as in
every kind. The server side is [karni-game](game.md), wired as `karni add
game` wires it. `--staff-app` adds the React staff app in `frontend/`, served
at `/app/`, which gets no game package: the game has its own.

```sh
cd block_hopper
cp .env.example .env
docker compose up -d            # django, worker, beat, db, redis and the game's dev server
karni migrate && karni load content/game.yaml
# the game: http://localhost:5174/play/block-hopper/, the admin: http://localhost:8000/admin/
```

In `game/block-hopper/`:

```sh
npm install        # Node 20.19+ and npm 10.8+. Commit the package-lock.json it writes.
npm run dev        # http://localhost:5174/play/block-hopper/, the game API proxied to Django
npm test           # the rules, headless
npm run build      # dist/, what production serves at /play/block-hopper/
npm run package    # one package per game portal in dist-portals/, checked and zipped
```

The page calls the game API on its own origin, so it needs no CORS setting. A
portal package calls the API named by `KARNI_GAME_API_URL` when its build has
it ([building for portals](game-client.md#building-for-portals)), and plays on
the device without it.

## An app with a game in it: `--kind app+game`

```sh
karni new "Reading Club" --kind app+game
```

An app whose React app hosts the game on a page at `/game`, with the app's
sign-in and API client: the game's code in `frontend/src/game/`, and
`frontend/portal/` to build the same game alone for the portals. This is what
`--kind game` made in Karni 0.6.0 ([a new game project](game.md#a-new-game-project)
lists every file). `karni add game` in an app adds the server side and
`@karni/game`, and records the kind `app+game`.

## Serving a game

A game-first project serves each folder of `game/` with a `package.json` at
`/play/<slug>/`. Only the build is served, never the game's source.

| Where | How |
|---|---|
| Development | The game's Vite dev server (`npm run dev`, or the `game` service of `docker-compose.yml`) serves it at `http://localhost:5174/play/<slug>/` and proxies `/api` to Django: `KARNI_API_PROXY`, else `KARNI_DEV_PORT` from `.env`. `KARNI_GAME_DEV_PORT` moves the port Compose publishes. |
| Docker Compose ([deploy](deploy.md)) | The Dockerfile's `games` stage builds each game (`npm ci`, or `npm install` until the game has a lock, then `npm run build`), and the prod image holds the builds. The release step publishes each one with `manage.py karni_publish_web --front play/<slug>=game/<slug>/dist`, and Caddy serves `/play/*` from the shared volume with the security headers Django sends. Hashed assets are cached for a year, the page is not. |
| systemd and nginx ([without Docker](deploy.md#without-docker-systemd-and-nginx)) | Each release builds each game with npm (Node.js 20.19 or later on the server), unless its `dist/` came with the project, and publishes it to `<root>/shared/web/play/<slug>/`, where nginx serves `/play/`. A rollback publishes the builds of the release it goes back to. |

`karni make deploy compose` and `karni make deploy systemd-nginx` see the
games in `game/` and write their part. In a game-first project, `/` goes to
the game, unless the staff app is served at `/`. An existing project that
gains a `game/<slug>/` folder adds the `games` stage to its Dockerfile (from a
new `--kind game` project's) and writes the stack again with `--force`: the
command stops with `C105` while the stage is missing.

`karni_publish_web --front PATH=DIR` is not game code: it publishes any built
front end at a path of the web root, and keeps an earlier build's files for a
week, as for the staff app.

## The opt-in, tested

The tests of `karni new` prove it per kind
(`packages/karni-cli/tests/test_kinds.py`):

- a project of kind `app`, `site+app` or `site` names no game package, and
  none of its scaffold or production files builds or serves a game.
- a game-first project names no package of the staff app (`@karni/ui`, React,
  TanStack, Tailwind) and has no `frontend/`, and its game's `package.json`
  depends on `@karni/game` alone.
- a project with both has one settings module, one URL configuration with one
  sign-in and one API, one database service, one web front, and each npm
  package once.
- each kind passes its own tests, `ruff` and `karni check`, and so does a
  project made with 0.6.0's `--kind game`.

`modules/karni-game/ui/tests/opt-in.test.ts` proves the same on the npm side:
the scaffold's staff app and the other Karni packages name no `@karni/game`.

## A project made with 0.6.0's `--kind game`

Karni 0.6.0's `--kind game` made an app with the game on a page, and recorded
`kind = "game"`. That layout is `app+game` now, and nothing in it moves: a
project that records `game` and has its game in `frontend/` (no
`game/<slug>/` folder) is read as `app+game`. `karni context` says so, and
`karni rules sync` writes its agent files for an app with a game. Set
`kind = "app+game"` under `[tool.karni]` to record the name
([migrating to 0.7](migrations/0.7.md#the-game-kind-makes-a-game-first)).

## What it does not do

- The games are not declared in `karni.yaml`, and `karni build` writes no game
  files: a game's files are the project's own once `karni new` wrote them.
- `karni new` writes one game. A second game is a second folder in `game/`
  with its own `package.json`, its row in `content/game.yaml`, and the
  deploy files written again.
- The game-first page has no sign-in screen: a player plays as a guest. The
  server keeps the guest's progress when the player signs in later
  ([players](game.md#players-a-guest-first-an-account-later)).
