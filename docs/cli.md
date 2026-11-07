---
description: Every karni command with its arguments and options, generated from the CLI's own help text.
---

# The `karni` command

> Generated from the CLI itself by `python -m karni_cli.clidoc > docs/cli.md`.
> `packages/karni-cli/tests/test_clidoc.py` fails when this file is stale.
> Change a command's help, then regenerate. Never edit this file by hand.

`karni <command> --help` prints the same information. Runners execute in the
project environment: the project's `.venv`, else the running docker compose
service. `--docker/--no-docker` forces one, and `--service` / `KARNI_COMPOSE_SERVICE`
names the service. Put `--` before passthrough arguments that clash with karni's
own options.

On the host, a command that starts Django first checks that the database
driver loads. A command that opens the database (`migrate`, `seed`,
`serve --local`, `test`, ...) also checks that the server answers. A missing
driver or an unreachable database is a coded error with the fix
([C012](errors.md#c012), [C013](errors.md#c013)) instead of Django's
traceback. `KARNI_DB_CHECK=false` skips the check.

## Contents

- **Project**: [new](#karni-new), [add](#karni-add), [remove](#karni-remove), [modules](#karni-modules), [upgrade](#karni-upgrade), [doctor](#karni-doctor), [config](#karni-config)
- **Frontend**: [ui](#karni-ui)
- **Agents and checks**: [context](#karni-context), [rules](#karni-rules), [check](#karni-check), [suggest](#karni-suggest), [explain](#karni-explain), [types](#karni-types), [mcp](#karni-mcp)
- **Debugging**: [queries](#karni-queries)
- **Runners**: [serve](#karni-serve), [migrate](#karni-migrate), [test](#karni-test), [shell](#karni-shell), [routes](#karni-routes), [schema](#karni-schema), [worker](#karni-worker), [beat](#karni-beat), [schedule](#karni-schedule), [seed](#karni-seed), [load](#karni-load), [sync-roles](#karni-sync-roles), [createsuperuser](#karni-createsuperuser), [manage](#karni-manage)
- **Debugging**: [why](#karni-why), [why-empty](#karni-why-empty)
- **Generators**: [make](#karni-make), [import](#karni-import), [design](#karni-design), [spec](#karni-spec), [plan](#karni-plan), [build](#karni-build)
- **Debugging**: [trace](#karni-trace), [replay](#karni-replay)
- **Other**: [recipes](#karni-recipes)

## Project

### `karni new`

Create a project: a public website, an app, or both.

Every kind has the API, the admin, PostgreSQL, Redis, Celery, the security defaults and the production stack. A site (--kind site) also has a site app at / on the karni-site module, where the client edits every text, image, menu and page title in the admin, registration off and the roles staff and editor. An app (--kind app) has the React app in frontend/. A site+app has both.

With --design, the site is built from a designer's pages, and the next steps say what is left: the models, the real content and the loops (karni rules --procedure site-from-design).

With --recipe (experimental), the app starts from a recipe's karni.yaml, and karni build makes it: the models and the API, the recipe's own domain code, seeds and tests, the migrations, demo data, the tests and karni check.

Example:

```sh
karni new "Crumb Bakery" --kind site --design ../design
```

Example:

```sh
karni new "Corner Shop" --recipe shop
```

```
karni new [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Project name (slug is derived from it) |
| `--output-dir`, `-o` PATH | `.` |  |
| `--domain` TEXT | `example.com` | Production domain for Caddy |
| `--kind` TEXT |  | What the project is: site (a public website the client edits in the admin), app (an API and a React app for signed-in users) or site+app. Asked when run in a terminal, else app (site with --design). |
| `--design` PATH |  | A designer's folder of static pages (index.html, css/, img/): the site is built from it (karni design analyze, karni import design --editable), and the next steps are the rest of the site-from-design procedure. Implies a kind with a site. |
| `--staff-app/--no-staff-app` |  | The React staff app in frontend/. An app always has it. A site has it unless --no-staff-app, and then staff work in the admin. |
| `--site-app` TEXT | `website` | The label of the site app a kind with a site gets. |
| `--git/--no-git` | on | Make the project a git repository with a first commit of what karni new wrote. Skipped inside an existing repository and when git is not installed. |
| `--recipe` TEXT |  | Experimental. Start the app from a recipe (karni recipes list, or blank): its karni.yaml with this name, then karni build, which also writes the recipe's own domain code, seeds and tests and runs the tests and karni check. Without the project's interpreter or database it stops after karni.yaml: run karni build next. |

### `karni add`

Install an optional module and wire it into settings

```
karni add MODULE
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODULE` (required) |  | Module short name, e.g. "payments" (karni modules list). An unknown name is C840. |

### `karni remove`

Take a module out again: what karni add wired, never its data

```
karni remove [OPTIONS] MODULE
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODULE` (required) |  | Module short name, e.g. "payments" |
| `--dry-run` |  | Print every change and each table's rows. Write nothing. |
| `--keep-tables` |  | Take the module out although its tables exist: they stay in the database. |

### `karni modules`

The module catalog (experimental): every module and built-in feature, added or not, with what it provides and the questions to ask (list, show).

```
karni modules COMMAND [ARGS]...
```

#### `karni modules list`

Experimental. Every module and built-in feature: kind, status, state, purpose, questions.

Modules first, then features. A module is added (in the # karni:apps block), installed (the project's interpreter has it) or available. Each question names the setting its answer goes to.

```
karni modules list [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--json` |  | Print the entries as JSON (every manifest key, plus state). |

#### `karni modules show`

Experimental. One module or feature: what it provides, the questions, the wiring.

For a module: what karni add writes (apps, middleware, context processors, the kind) and prints (the URL include, extras), which karni remove takes out again. For a feature: the setting that turns it on and the extra it needs.

```
karni modules show [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | A module or feature, e.g. payments or two_factor. |
| `--json` |  | Print the entries as JSON (every manifest key, plus state). |

### `karni upgrade`

Upgrade across Karni versions: codemods, diff, manual-change report

```
karni upgrade [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--to` TEXT |  | Target Karni version (default: the newest release in the changelog) |
| `--from` TEXT |  | The project's current Karni version, instead of asking its interpreter (use it when the new karni is already installed) |
| `--dry-run` |  | Print a unified diff of every change and write nothing |
| `--allow-dirty` |  | Write even with uncommitted changes, or outside a git work tree |
| `--list` |  | List every recorded breaking change and exit |
| `--docker/--no-docker` |  | Where to ask for the installed karni version |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni doctor`

Report the environment: project, interpreter, Node, adapters, history

```
karni doctor [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |
| `--quiet`, `-q` |  | Do not print the optional tip. |

### `karni config`

Read and write Karni settings in the project's .karni/config.toml (committed) or, with --global, in ~/.config/karni/config.toml. The project's value wins.

```
karni config COMMAND [ARGS]...
```

#### `karni config get`

Print the effective value of KEY.

```
karni config get [OPTIONS] KEY
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `KEY` (required) |  | Setting name (see `karni config list`). |
| `--global` |  | Use the global file ($XDG_CONFIG_HOME/karni/config.toml) only. |

#### `karni config set`

Set KEY to VALUE in the project file (or --global).

```
karni config set [OPTIONS] KEY VALUE
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `KEY` (required) |  | Setting name (see `karni config list`). |
| `VALUE` (required) |  | New value (true/false). |
| `--global` |  | Use the global file ($XDG_CONFIG_HOME/karni/config.toml) only. |

#### `karni config list`

Every setting with its effective value and source.

```
karni config list
```

## Frontend

### `karni ui`

Fit Karni's components to the project's design system.

```
karni ui COMMAND [ARGS]...
```

#### `karni ui detect`

Adopt the frontend's design system: map its theme onto Karni's `--karni-*` tokens.

It looks for a theme in this order. First shadcn/ui (`components.json`): Karni's tokens reference the project's CSS variables with `var()`, and `karni-primitives.tsx` registers its components as Karni's primitives. Next a Tailwind theme (`@theme` blocks, or the `tailwind.config` that Node evaluates in the project). Then a Material UI, Chakra UI or Mantine theme (literal values read from the source). Without any of these it uses Karni's defaults, listed for editing.

`--css <path>` reads any stylesheet instead (plain CSS, Bootstrap, a design with no variables at all): its custom properties, then its body, link, button and input rules, mapped onto the colour, radius and font tokens as literal values. The report grades each token as found, inferred or defaulted. The same file then themes the admin.

Writes one file the project owns, `karni-theme.css`, imported after `@karni/ui/styles.css` (wired into `src/main.tsx` when it has the scaffold's import). The report lists every token mapped (from, to, value) and every value not mapped, with the reason. A generated file edited since is never overwritten without `--force`.

Examples:

```sh
karni ui detect --dry-run, karni ui detect --css design/ --dry-run
```

```
karni ui detect [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--output`, `-o` PATH |  | Where to write karni-theme.css (default: next to the main stylesheet). |
| `--frontend` PATH |  | The frontend directory (default: the current directory if it has package.json, else ./frontend, else the Karni project's frontend/). |
| `--source` CHOICE |  | Read this source instead of detecting the first one present: shadcn, tailwind, mui, chakra, mantine or defaults. |
| `--primitives/--no-primitives` | on | For shadcn/ui, also write karni-primitives.tsx (the project's components as Karni's primitives). |
| `--force` |  | Overwrite generated files even if they were edited. |
| `--dry-run` |  | Print the report and the files, but write nothing. |
| `--json` |  | Print the report as JSON (for agents). |
| `--css` PATH (repeatable) |  | Read these stylesheets (or directories of pages and the stylesheets they link) instead of the frontend's design system: any CSS, with variables or without. Repeatable. Later files win, as in a browser. |

## Agents and checks

### `karni context`

Print a compact machine-readable project inventory.

On a large project read one area at a time: --summary first, then --app or --model.

Example:

```sh
karni context --app catalog --max-tokens 1500
```

```
karni context [OPTIONS] [PATH]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `PATH` |  | File to brief, relative to the cwd (needs --with-history). |
| `--with-history` |  | Append what a history provider (e.g. Gigai Chronicle) recorded about PATH under a HISTORY: heading. Without PATH, append the project's recorded decisions, from the providers that offer them. The block is capped at ~300 tokens (~1200 characters) and cut at line boundaries, with a last line naming the command for the full brief. With no history store detected, it prints the plain inventory and nothing else. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |
| `--manifest` PATH |  | Explicit manifest.json path |
| `--app` TEXT (repeatable) |  | Only this app, in full: every model with its fields, the relations in and out, its viewsets with route and access, its roles and pages (repeatable). Experimental. |
| `--model` TEXT (repeatable) |  | One model in depth: Name or app_label.Name. Every field, the relations that point at it, its viewsets and pages (repeatable). Experimental. |
| `--summary` |  | One line per app: its models, viewsets and pages, with their counts. Experimental. |
| `--max-tokens` INT RANGE |  | Cut the output at whole sections to about N tokens (4 characters each). The last line names what was left out and the command that prints it. Experimental. |

### `karni rules`

Karni's conventions for humans and AI agents (no Django needed).

```
karni rules [OPTIONS] COMMAND [ARGS]...
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--check` PATH (repeatable) |  | Statically check FILE and exit 1 on violations. Several files: --check a.py b.py (or --check repeated). |
| `--explain` TEXT |  | Show one rule in full. |
| `--procedure` TEXT |  | Show a procedure's steps. |
| `--json` |  | Machine-readable output. |

#### `karni rules sync`

Regenerate AGENTS.md (and any deprecated tool-specific agent file) from the rules.

```
karni rules sync [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--check` |  | Only compare, and exit 1 if any adapter is stale (for CI). |
| `--force` |  | Overwrite hand-written files (backed up under .karni/backup/). |

### `karni check`

Run architecture and system checks.

An unchanged file is not checked again: the results of the file checks are cached in .karni/local/ (--no-cache turns that off).

Example:

```sh
karni check --changed main
```

```
karni check [OPTIONS] [REF]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `REF` |  | With --changed: the git ref to compare with (a branch, a tag, a commit) instead of HEAD. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |
| `--frontend/--no-frontend` |  | Run the frontend checks (eslint and jscpd in frontend/). By default they run when frontend/node_modules is installed, and are skipped with a note when it is not, except in CI. --frontend fails without it, --no-frontend skips them. |
| `--quiet`, `-q` |  | Do not print the optional tip. |
| `--verbose`, `-v` |  | Print the frontend tools' own output (ESLint, jscpd's report) when they pass too. By default a pass is one line and only a failure prints their output. |
| `--deploy` |  | Also run the deploy checks (DEBUG, SECRET_KEY, hosts, HSTS, cookies, admin path, CORS, CSP) and fail on warnings. Run it with the production environment. |
| `--seo` |  | Also run the SEO checks: every page of the public site rendered, and missing or shared titles and descriptions, images without alt, size or smaller copies, broken links and pages missing from the sitemap reported (karni-site, SITE010 to SITE018). |
| `--changed` |  | Only the files git reports as changed: the working tree and the index against HEAD (or REF), and untracked files. The checks that read the whole project still run. Experimental. |
| `--no-cache` |  | Check every file again: do not read or write the check cache (.karni/local/check-cache.json) or ESLint's. Experimental. |

### `karni suggest`

What Karni could do that the project does by hand, with the fix of each

```
karni suggest [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--json` |  | Print {version, enabled, suggestions: [{code, rule, file, line, message, fix, command}], problems: [...]} (docs/assets/karni-suggestions.schema.json). |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni explain`

Explain an error code (E104, C101, PAY004, K106), or a pasted traceback or log line (karni explain -): class, cause, where, fix

```
karni explain [OPTIONS] [CODE]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `CODE` |  | An error code such as E104, W101, C101, PAY004 or K106, a setting such as KARNI_SITE_HIGHLIGHT, a template tag such as image, a content map key such as map.items, or a reference such as access. Pass - to read a traceback or log line from stdin. |
| `--json` |  | Machine-readable output. |
| `--failure` TEXT |  | A captured failure id (.karni/failures/), a failed request's id, or `last`: print it as a brief (development, DEBUG on). |

### `karni types`

Generate TS types and typed hooks from the backend OpenAPI

```
karni types [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--schema-out` PATH | `frontend/src/api/schema.yml` |  |
| `--out` PATH | `frontend/src/api` |  |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni mcp`

Serve context, rules, check, the debugging tools and the app-builder flow (recipes, questions, answer, plan, build) as MCP tools (needs karni-cli[mcp])

```
karni mcp [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--project` PATH |  | Project root (default: found from the working directory). |

## Debugging

### `karni queries`

Run one endpoint in-process as a user and report its queries.

The report has the query count and time, the repeated queries grouped by cause (field, relation, why the optimiser did not fetch it) and the fix. It wraps `manage.py karni_queries`.

```
karni queries [OPTIONS] ENDPOINT
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ENDPOINT` (required) |  | A path (`/api/events/?page=2`), a resource (`events`, `events/<id>`) or a viewset (`EventViewSet`, `EventViewSet.retrieve`). |
| `--as` TEXT |  | The user: email, username or primary key (default: anonymous). |
| `--method` TEXT | `GET` | HTTP method. |
| `--data` TEXT |  | JSON request body (the request's writes are rolled back). |
| `--json` |  | Machine-readable output. |
| `--explain` |  | Add the plans. On PostgreSQL: EXPLAIN ANALYZE of every query, rolled back with the request, and each sequential scan on a table of KARNI_EXPLAIN_SEQ_SCAN_ROWS rows or more (default 1000) with the index that would serve it. Elsewhere: plain EXPLAIN of the slowest queries. |
| `--all` |  | List every statement, not only repeats. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

## Runners

### `karni serve`

Start the dev stack. It wraps `docker compose up` (or `manage.py runserver` with --local).

```
karni serve [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--local` |  | Run manage.py runserver through the project .venv instead. |
| `--host` TEXT |  | --local only. Default 127.0.0.1. |
| `--port` INTEGER |  | --local only. Default: KARNI_DEV_PORT from the environment or .env, else 8000 (the frontend's dev server proxies to the same port). Another port prints how to point the frontend at it. |
| `--build` |  | compose only: rebuild images first. |
| `--detach`, `-d` |  | compose only: run in background. |

### `karni migrate`

Apply migrations. It wraps `manage.py migrate [ARGS]`.

```
karni migrate [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to manage.py migrate: [app_label] [migration_name] --plan --fake … |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni test`

Run the test suite. It wraps `python -m pytest [ARGS]`.

```
karni test [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to pytest: paths, -k EXPR, -x, --lf … (use -- before --help). |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni shell`

Open a Django shell. It wraps `manage.py shell [ARGS]`.

```
karni shell [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to manage.py shell: -c CODE, -i ipython … |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni routes`

List every URL with its methods, name, view, model and access.

It wraps `manage.py karni_routes`.

```
karni routes [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--json` |  | Print the routes as a JSON list. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni schema`

Show every column, constraint and index, and the declaration behind each.

It wraps `manage.py karni_schema`. Per model it lists column types and CHECKs, unique constraints (partial on soft-deletable models) and indexes (Django's FK indexes, Karni's GIN/BRIN), each with why it exists and whether the database has it. It also lists the columns viewsets search, filter or order by, with the index serving each.

Example:

```sh
karni schema events --json
```

```
karni schema [OPTIONS] [LABELS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `LABELS...` |  | App labels or app.Model (default: every model of your own apps). |
| `--json` |  | Print the report as JSON (for agents). |
| `--no-db` |  | Report the declarations only, without reading the database. |
| `--database` TEXT | `default` | Database alias to describe. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni worker`

Run a Celery worker. It wraps `python -m celery -A config worker -l info [ARGS]`.

A worker on a Mac runs the threads pool (Celery's prefork pool fails every task there).

```
karni worker [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to celery worker: -Q QUEUES, --concurrency N … |
| `--app`, `-A` TEXT | `config` | Celery app module. Env: `KARNI_CELERY_APP`. |
| `--loglevel`, `-l` TEXT | `info` |  |
| `--pool`, `-P` TEXT |  | Celery's pool: threads, solo or prefork (or eventlet, gevent). Default: threads for a worker on a Mac, else Celery's prefork. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni beat`

Run Celery beat. It wraps `python -m celery -A config beat -l info [ARGS]`.

```
karni beat [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to celery beat. |
| `--app`, `-A` TEXT | `config` | Celery app module. Env: `KARNI_CELERY_APP`. |
| `--loglevel`, `-l` TEXT | `info` |  |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni schedule`

List and run the Celery beat schedules. It wraps `manage.py karni_schedules`.

```
karni schedule COMMAND [ARGS]...
```

#### `karni schedule list`

List every schedule with its name, task, timing and source.

It wraps `manage.py karni_schedules`.

```
karni schedule list [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--json` |  | Print the schedules as a JSON list. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

#### `karni schedule run`

Run one schedule's task now, synchronously.

It wraps `manage.py karni_schedules --run NAME`.

```
karni schedule run [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | The schedule name (see `karni schedule list`). |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni seed`

Fill every model with realistic demo data. It wraps `manage.py karni_seed [ARGS]`.

Values come from field names and types (an `email` gets an email, `price` money, `starts_at` a near-future date). Relations point at seeded rows, and the same --seed gives the same rows. It prints a demo login (demo@example.com / karni-password). Per-model overrides live in `<app>/seeds.py` (`karni make seeder <Model>`).

It first prints the models it will write to, and refuses when one of their tables already holds rows (users aside), because demo rows would mix with real content. Pass --reset to wipe the tables first or --force to add rows on top. Real content belongs in `karni load`.

--volume N (experimental) writes N rows per model in bulk, for performance work: relation targets first, foreign keys drawn from existing rows, in batches (--batch-size), with the rows and the time per model. It refuses when a table holds rows no seed run left there, unless --reset or --force. A model whose seed count reaches KARNI_SEED_BULK_THRESHOLD takes the bulk path in a plain run too.

Example:

```sh
karni seed --count 20 --seed 42 --reset
```

```
karni seed [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to manage.py karni_seed: --count N, --seed S, --reset, --model app.Model, --json, --force, --volume N, --batch-size N. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni load`

Load real content from a JSON or YAML file. It wraps `manage.py karni_load FILE [ARGS]`.

The file maps model labels to lists of rows. Each row is matched by its natural key (`slug`, `email`, or `Karni.natural_key`) and created or updated, so the same file loads again without duplicates and says when nothing changed. Relations name their targets by natural key, file and image fields hold paths relative to the content file (uploaded once, or again with --refresh-files), and a nested list holds a row's children (--prune deletes the ones it does not name). One transaction with the API's validation: an invalid row rolls everything back. --dry-run lists, per model, each row it would create or change with the fields that change. `karni seed` is for demo data, `karni load` for real content (`karni design extract` writes it from a designer's pages).

Example:

```sh
karni load content/site.json --dry-run
```

```
karni load [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | The content file, then options passed to manage.py karni_load: --dry-run, --refresh-files, --prune, --as USER, --json. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni sync-roles`

Create or update the roles KARNI_ROLES declares.

It wraps `manage.py karni_sync_roles [ARGS]`.

Expands each role's grant patterns against every model and action into Role, Permission and RolePermission rows: creates what is missing, updates what changed, reports roles the database holds that the declaration no longer names, and never deletes. The same sync runs after every `karni migrate` (KARNI_ROLES_AUTOSYNC).

Example:

```sh
karni sync-roles --dry-run
```

```
karni sync-roles [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to manage.py karni_sync_roles: --dry-run, --json. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni createsuperuser`

Create an admin user. It wraps `manage.py createsuperuser [ARGS]`.

```
karni createsuperuser [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to manage.py createsuperuser: --email E, --noinput … |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni manage`

Run any management command. It wraps `manage.py ARGS` (raw passthrough).

```
karni manage [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | The manage.py command and its arguments, e.g. `showmigrations events`. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

## Debugging

### `karni why`

Explain an access decision: why a row, field or action is refused or missing

```
karni why [OPTIONS] TARGET [REQUEST_ID]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `TARGET` (required) |  | What to explain: `<resource>/<id>` (a row), `<resource>.<field>` (a field), `<resource>` (its list), or a status followed by a request id (`403 <request-id>`). Resources are named as the API names them: `events`, `events-event` or `events.Event`. |
| `REQUEST_ID` |  | The request id, after a status. |
| `--as` TEXT |  | The user: email, username, primary key, or anonymous. |
| `--action` TEXT |  | For a row: view (default), update, delete, or an @action name. For a resource: create or list. |
| `--method` TEXT |  | The HTTP method, for an @action that answers several. |
| `--param` TEXT (repeatable) |  | A query parameter the request carries, key=value (repeatable). |
| `--json` |  | Print the verdict as JSON (for agents). |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni why-empty`

Explain an empty list: which step removes the rows, and the fix

```
karni why-empty [OPTIONS] RESOURCE
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `RESOURCE` (required) |  | The resource, named as the API names it. |
| `--as` TEXT |  | The user: email, username, primary key, or anonymous. |
| `--param` TEXT (repeatable) |  | A query parameter the request carries, key=value (repeatable). |
| `--json` |  | Print the verdict as JSON (for agents). |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

## Generators

### `karni make`

Generate project code: apps, models, viewsets, tasks, schedules, listeners, pages ... (`karni make --list`). It never overwrites without --force, and --dry-run previews.

```
karni make [OPTIONS] COMMAND [ARGS]...
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--list` |  | Print every generator with a one-line summary. |

Every generator follows the same rules:

- It writes project code only, never framework logic.
- It never overwrites: an existing target is an error naming the file and
  `--force` (which replaces it).
- `--dry-run` prints the files and the diff it would write, and writes nothing.
- It prints every created and modified file, then any notes (the chosen
  `access`, the route, the next command).
- The target app is `--app <label>`, else the project's only local app (local
  apps are the `# karni:apps` entries of config/settings.py).
- Existing files change only through marker comments (`# karni:apps`,
  `# karni:middleware`, `# karni:urls`, `// karni:page-imports`, `// karni:routes`) or
  AST-located appends. An unfamiliar layout is an error that names the manual
  step. Generated Python is ruff-clean (isort sections, ruff format layout).
- It never imports Django: `karni make migration` (and `make model --migrate`)
  run `manage.py makemigrations` through the project interpreter.
- Every generator is also available as a hidden Laravel-style alias:
  `karni make:<type>` (e.g. `karni make:model Event title:str`).

`karni make --list`:

```
app         Create a local Django app (models.py, viewsets.py) wired into # karni:apps.
model       Add a model on BaseModel from a field DSL (--with viewset,page,test or -a chains them).
viewset     Add a BaseViewSet for a model, with its access declaration (--access).
serializer  Add an explicit serializer (--reason required) and set serializer_class.
migration   Create migrations: wraps manage.py makemigrations [app] [--name] [--empty].
test        Add <app>/tests/test_<model>.py: assert_crud + the isolation check for a resource.
factory     Add an explicit test factory to <app>/factories.py (overrides the generated one).
seeder      Add a Seeder to <app>/seeds.py: per-model rows and values for karni seed.
task        Add a Celery task (@shared_task) to <app>/tasks.py, optionally with --retry N.
schedule    Add a beat schedule (every/cron) to <app>/schedules.py, creating the task if needed.
event       Add a custom event (a Django Signal) to <app>/events.py.
listener    Add a listener to <app>/listeners.py: --on Model.created|updated|deleted or an event.
command     Add a management command (<app>/management/commands/<name>.py).
service     Add a service module (<app>/services/<name>.py), the home of HTTP clients.
middleware  Add a middleware class to <app>/middleware.py, wired via # karni:middleware.
page        Add a frontend page (<= 50 lines) composing @karni/ui, with its route.
component   Add a React component that claims a role (registerComponentRole).
site        Create a public site app (Django views, urls, templates, static) mounted at "/".
view        Add a page to a site app: a function view, its template and its URL.
deploy      Write the production stack: docker-compose.prod.yml, the Caddyfile, .env.prod.example.
form        Add a public form: model, viewset, notification, tests, staff pages ({% karni_form %}).
module      Create a reusable module skeleton: modules/karni-<name>/ (docs/modules.md).
```

Field DSL for `karni make model NAME [FIELD...]`:

| Field | Generates |
| --- | --- |
| `title:str[:len]` | CharField(max_length=len), 255 when omitted |
| `body:text` | TextField() |
| `count:int` | IntegerField() |
| `ratio:float` | FloatField() |
| `price:decimal[:max:places]` | DecimalField(max_digits=max, decimal_places=places), 10 and 2 when omitted |
| `done:bool` | BooleanField(default=False) |
| `day:date / at:datetime` | DateField() / DateTimeField() |
| `site:url[:len]` | URLField() |
| `price:money:EUR` | MoneyField(currency="EUR"): NUMERIC(19,4), Decimal only |
| `price:money` | MoneyField(currency_field="price_currency") + price_currency = CurrencyField() |
| `rate:percent[:min:max]` | PercentField() with a CHECK between the bounds (0..100) |
| `stock:quantity` | QuantityField(default=0) with a CHECK that it is never negative |
| `email:email[:unique]` | EmailField(), where unique=True is case-insensitive (LOWER index) |
| `slug:slug[:source]` | SlugField(populate_from="source"), unique among live rows (:len too) |
| `phone:phone` | PhoneField(): E.164, CHECK format |
| `notes:markdown` | MarkdownField(): text, edited with a preview and shown formatted in @karni/ui |
| `country:country / currency:currency` | CountryField() / CurrencyField() with a CHECK against the ISO list |
| `meta:json[:queried]` | JSONField(default=dict), and queried adds a GIN index |
| `tags:array:str[:len]` | ArrayField(models.CharField(...)) with a GIN index, PostgreSQL only |
| `doc:file / photo:image` | FileField / ImageField with `upload_to="<app>/<model>/"`. An image field makes pyproject.toml depend on `karni[images]` (Pillow) |
| `doc:file:protected / photo:image:protected` | ProtectedFileField / ProtectedImageField (karni-storage, experimental): stored privately, downloaded only through the row's viewset. Needs `karni add storage` |
| `ref:uuid` | UUIDField(default=uuid.uuid4) |
| `status:choice:draft\|live` | a TextChoices class + CharField(choices=..., default=first) |
| `status:state:draft,confirmed,cancelled` | StateField(states=[...], transitions={...}): each state moves to the next (edit the dict), or declare the moves with &gt;: 'status:state:draft&gt;confirmed\|draft&gt;cancelled' |
| `during:datetimerange / nights:daterange` | DateTimeRangeField() / DateRangeField() (PostgreSQL range columns, karni.fields) |
| `remaining:capacity:quantity` | CapacityField(total="quantity"), consumed with karni.capacity.reserve(). Without :total, CapacityField(default=0) |
| `owner:fk:User` | ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE) |
| `venue:fk:Venue / fk:shop.Venue` | ForeignKey("Venue") in the same app, or "app.Model" |
| `tags:m2m:Tag / profile:o2o:User` | ManyToManyField / OneToOneField |
| `name:type?` | optional: null=True, blank=True (strings and files: blank=True) |

#### `karni make app`

Create a local app. It replaces `manage.py startapp`.

Writes NAME/{__init__,apps,models,viewsets}.py, NAME/migrations/ and NAME/tests/, and adds NAME to the `# karni:apps` block of config/settings.py. No admin.py, serializers.py or urls.py: Karni derives them. An existing app is never truncated: --force only fills in missing files.

```
karni make app [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | App label, snake_case (e.g. events). |
| `--force` |  | Create only the missing files of an existing app (keeps the rest). |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make model`

Add `class NAME(BaseModel)` with FIELDS to APP/models.py (BigIntBaseModel with --pk bigint).

Example:

```sh
karni make model Event title:str:200 starts_at:datetime "status:choice:draft|live" organizer:fk:User 'venue:fk:Venue?' -a --access owned:organizer
```

Experimental: karni make model Sale --external --table reporting.sales [--database warehouse] [--writable] writes a plain models.Model over that existing table or view from its columns (Meta.managed = False, class Karni: external = True), and its viewset. The database must be reachable.

```
karni make model [OPTIONS] NAME [FIELDS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Model class name, PascalCase (e.g. Event). |
| `FIELDS...` |  | Fields as name:type[:arg][?]. Types: str[:len] text int float decimal[:max:places] bool date datetime url file image uuid choice:a\|b fk:Model m2m:Model o2o:Model. Typed fields (karni.fields): money[:EUR] percent[:min:max] quantity email[:unique] slug[:source] phone country currency json[:queried] array:str. A trailing ? makes the field optional. |
| `--with` TEXT (repeatable) |  | Also generate: viewset, page, test, factory, seeder (comma-separated or repeated). |
| `--all`, `-a` |  | Also generate the viewset, the pages and the API test. |
| `--access` TEXT |  | With viewset: granted\|authenticated\|public-read[:&lt;role&gt;]\|public-create[:&lt;role&gt;]\|owned:&lt;field&gt;\|staff\|role:&lt;name&gt;. public-read: anyone reads, only role 'staff' (or :&lt;role&gt;) writes. public-create: anyone creates (a public form), only that role reads and writes. |
| `--search` TEXT (repeatable) |  | With viewset: search_fields (comma-separated). |
| `--external` |  | Experimental. A model over a table or view another system owns, written from the columns of --table (Meta.managed = False, class Karni: external = True), with its viewset. It reads the database, which must be reachable. |
| `--table` TEXT |  | With --external: the table or view, e.g. sales or reporting.sales. |
| `--database` TEXT |  | With --external: the DATABASES alias the table lives in (class Karni: database). |
| `--writable` |  | With --external: let the API and the admin write it (class Karni: writable). |
| `--migrate` |  | Run `karni make migration` for the app afterwards. |
| `--order` TEXT |  | Order rows by this field (Meta.ordering), e.g. position or -created_at. |
| `--key` TEXT |  | The field karni load and imports match rows on (Karni.import_key). Rows nested under a parent are matched on the parent plus this field, e.g. position. |
| `--pk` TEXT |  | The primary key: uuid (BaseModel) or bigint (BigIntBaseModel, experimental). Default: KARNI_PK in config/settings.py, else uuid. |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make viewset`

Add `<Model>ViewSet(BaseViewSet)` to APP/viewsets.py, with CRUD at `/api/<models>/`.

It declares `model = <Model>` and the mandatory `access` (ADR 0001): granted (default: whatever KARNI_ROLES grants for the model, row-scoped), authenticated, public-read (anyone reads, only role "staff" writes, or the role `public-read:<role>` names), public-create (a public form: anyone creates, only role "staff" or `public-create:<role>` reads and writes), `owned:<field>` (rows whose `<field>` is the user), staff (role "staff") or `role:<name>`.

```
karni make viewset [OPTIONS] MODEL
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODEL` (required) |  | Model class name (e.g. Event). |
| `--access` TEXT |  | Who reads/writes: granted\|authenticated\|public-read[:&lt;role&gt;]\|public-create[:&lt;role&gt;]\|owned:&lt;field&gt;\|staff\|role:&lt;name&gt;. Default: granted (the roles' grants). public-read: anyone reads, only role 'staff' (or :&lt;role&gt;) writes. public-create: anyone creates (a public form), only that role reads and writes. |
| `--search` TEXT (repeatable) |  | search_fields, comma-separated or repeated (e.g. title,venue). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make serializer`

Add `<Model>Serializer` to APP/serializers.py and set the viewset's serializer_class.

BaseViewSet generates the serializer and APIMeta steers it, so an explicit one needs --reason. The reason is recorded as the `# karni: allow(redundant-serializer): <reason>` marker.

```
karni make serializer [OPTIONS] MODEL
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODEL` (required) |  | Model class name (e.g. Event). |
| `--reason` TEXT |  | Why the generated serializer is not enough (required). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make migration`

Create migrations. It wraps `manage.py makemigrations [APP] [--name NAME] [--empty]`.

Without --app every app with model changes gets a migration. With --empty (a data migration) it targets one app: --app, else the only local app. --dry-run is makemigrations' own (it prints and writes nothing).

```
karni make migration [OPTIONS] [NAME]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` |  | Migration name (makemigrations --name), e.g. add_event_capacity. |
| `--empty` |  | An empty migration to fill in (data migrations). It needs one app. |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

#### `karni make test`

Add `APP/tests/test_<model>.py`: the resource's whole API surface in a few lines.

It writes one APITestCase. `assert_crud` checks list, retrieve, create, update, delete, the denials the access declaration promises, pagination, filtering and the OpenAPI contract. `assert_isolated` (when reads are Owned, or Granted() with an own/related grant) checks that another scope's rows are out of reach on every surface. Run it with `karni test`.

```
karni make test [OPTIONS] MODEL
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODEL` (required) |  | Model class name (e.g. Event). The model needs a viewset. |
| `--role` TEXT |  | The role the test acts as, one the project declares (KARNI_ROLES or an added module, C830 otherwise). By default it is the first HasRole the viewset's write predicate names (then create, then read), so the test really writes. For Granted() it is the first KARNI_ROLES role whose grant reaches the model (own/related first; own needs an owner field). Otherwise the test uses any signed-in user. |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make factory`

Add `<Model>Factory(ModelFactory)` to APP/factories.py.

Only needed to change generated values: an explicit factory replaces the generated one everywhere (tests, related rows, karni seed), and fields it does not declare keep their generated, realistic values.

```
karni make factory [OPTIONS] MODEL
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODEL` (required) |  | Model class name (e.g. Event). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make seeder`

Add `<Model>Seeder(Seeder)` to APP/seeds.py, read by `karni seed`.

Only needed to steer a model's demo data: Meta.count pins its rows per run, and a class attribute overrides a field (a value or a factory-boy declaration). Every other field stays inferred from its name and type.

```
karni make seeder [OPTIONS] MODEL
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODEL` (required) |  | Model class name (e.g. Event). |
| `--count` INTEGER |  | Rows per `karni seed` run for this model (0 skips it). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make task`

Add a Celery task `NAME` to APP/tasks.py (registered as APP.tasks.NAME).

```
karni make task [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Task function name, snake_case (e.g. send_digest). |
| `--retry` INTEGER |  | Retry up to N times on any exception (exponential backoff). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make schedule`

Add every(...)/cron(...) to APP/schedules.py, merged into Celery beat at startup.

Without --task the schedule runs `APP.tasks.<name>` (dashes become underscores), which is created when missing.

```
karni make schedule [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Schedule name, unique in the project (e.g. nightly-report). |
| `--every` TEXT |  | Interval: 30s, 15m, 1h, 1h30m, 1d. |
| `--cron` TEXT |  | Five-field crontab, e.g. "0 3 * * *" (03:00 daily). |
| `--task` TEXT |  | Dotted task to run (default: `APP.tasks.<name>`, created if missing). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make event`

Add `NAME = Signal()` to APP/events.py (autodiscovered with the listeners).

```
karni make event [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Event name, snake_case (e.g. order_shipped). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make listener`

Add a listener to APP/listeners.py (autodiscovered, so no AppConfig.ready wiring).

With --on Event.created|updated|deleted it uses karni.events (soft deletes count as deleted). With --on order_shipped it receives a custom event from events.py.

```
karni make listener [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Listener function name, snake_case. |
| `--on` TEXT (required) |  | Model.created\|Model.updated\|Model.deleted (app_label.Model.event for an installed app's model, e.g. karni_payments.Payment.updated), or a custom event (order_shipped). |
| `--queued` |  | Run the work in a Celery worker after the transaction commits. |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make command`

Add a management command NAME to APP (run it with `karni manage NAME`).

```
karni make command [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Command name, snake_case (e.g. send_reminders). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make service`

Add APP/services/NAME.py, the one place HTTP clients are allowed (K105).

```
karni make service [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Service module name, snake_case (e.g. stripe_client). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make middleware`

Add a middleware class to APP/middleware.py and wire it into MIDDLEWARE.

Wiring goes through the `# karni:middleware` block of config/settings.py (appended after Karni's middleware). Without that block the command prints the line to add.

```
karni make middleware [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Class name, PascalCase (Middleware suffix added). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make page`

Add frontend/src/pages/NAME.tsx (at most 50 lines) and register its route.

With --resource R --kind list|detail|form the page composes ResourceTable / ResourceDetail / ResourceForm for the API resource R (a detail page takes --related tabs). --kind dashboard composes DashboardGrid and ChartCard with the rows of each --count resource. Without --resource the page is a bare `<Page>`. Routes: list at `<base>`, detail at `<base>/$id`, form at `<base>/new` and `<base>/$id/edit`, where the base is --path or `/<resource>`, and a dashboard at `/<name>`.

```
karni make page [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Page file name, kebab-case (e.g. events). |
| `--resource` TEXT |  | API resource (router prefix, e.g. events). |
| `--kind` TEXT |  | With --resource: list (default), detail or form. A login page needs no resource, a dashboard (experimental) counts resources (--count), and blank is the bare page. |
| `--path` TEXT |  | Route path. For resource pages it is the base (default `/<resource>`). |
| `--title` TEXT |  | Page title (default: from the name). |
| `--related` TEXT (repeatable) |  | Experimental. With --kind detail: a related tab (deals, or deals.partner), a resource whose model has a fk to this one (C561 otherwise). Repeat it. |
| `--count` TEXT (repeatable) |  | Experimental. With --kind dashboard: a resource to count. Repeat it (default: every resource the project routes). |
| `--no-route` |  | Do not register the route in frontend/src/routes.tsx. |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make component`

Add frontend/src/components/NAME.tsx, registered with registerComponentRole.

A role already claimed by @karni/ui (its manifest) or by another project component is refused. Compose that component instead, or pass --replace-reason to replace it on purpose.

```
karni make component [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Component name, PascalCase (e.g. StatusBadge). |
| `--role` TEXT |  | Semantic role it claims (default: kebab-case of NAME). |
| `--replace-reason` TEXT |  | Take over a role another component claims, saying why. |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make site`

Create a public, server-rendered site app NAME and mount it at "/".

Writes NAME/views.py (a home view), NAME/urls.py (app_name NAME, a `# karni:urls` marker), NAME/templates/NAME/base.html and home.html, NAME/templates/404.html and 500.html, NAME/static/NAME/site.css and NAME/tests/test_pages.py (assert_pages on every page in its PAGES list), then inserts `path("", include("NAME.urls"))` at the `# karni:urls` marker of config/urls.py, so the home page replaces the welcome page, and sets handler404 and handler500 there to karni_site's views. The site's runtime is the karni-site module: when the project lacks it, the dependency, the `# karni:apps` entry, its redirect middleware and its `site` context processor are added as `karni add site` would (then `karni migrate`). A new app also gets the `karni make app` skeleton and the `# karni:apps` entry. An existing app keeps every file it has (with --force, only the missing files are created). Add pages with `karni import design` or `karni make view`.

```
karni make site [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | App label, snake_case (e.g. website). |
| `--no-route` |  | Do not include the site at "" in config/urls.py. |
| `--force` |  | Replace the home view and create only the missing files (existing ones are kept). |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make view`

Add a page NAME to the site app APP: a view, its template and its URL.

Writes `def NAME(request)` in APP/views.py, APP/templates/APP/NAME.html extending the site's base.html, and `path(..., views.NAME, name="NAME")` at the `# karni:urls` marker of APP/urls.py. The URL also goes into PAGES at the `# karni:pages` marker of APP/tests/test_pages.py, so assert_pages checks the page (a path with a capture needs a real URL there, which the command asks for). The app must come from `karni make site`.

```
karni make view [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | View name, snake_case (e.g. about). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--path` TEXT |  | URL path (default /&lt;name&gt;/). Captures such as /services/&lt;slug:slug&gt;/ become view parameters. |
| `--no-route` |  | Do not register the URL in &lt;app&gt;/urls.py. |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make deploy`

Write the production stack: docker-compose.prod.yml, the Caddyfile and .env.prod.example.

One command then starts it on a server: `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`. Every file is the project's to edit. docs/deploy.md is the walk-through.

```
karni make deploy [OPTIONS] TARGET
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `TARGET` (required) |  | What to write. `compose`: the Docker Compose stack. |
| `--domain` TEXT |  | The site's host for .env.prod.example (default: DOMAIN in .env.example). |
| `--app-path` TEXT | `/app/` | Path the staff app (frontend/) is served under, e.g. /app/ or /, on the site's host. |
| `--app-domain` TEXT |  | Serve the staff app on its own host instead, e.g. app.example.com. |
| `--app/--no-app` | on | Serve the staff app at all. |
| `--celery/--no-celery` | on | Celery worker and beat services. |
| `--backups/--no-backups` | on | The backup service. |
| `--db/--no-db` | on | A PostgreSQL service (--no-db: a managed one). |
| `--redis/--no-redis` | on | A Redis service (--no-redis: a managed one). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make form`

Add a public form NAME with FIELDS: it works with and without JavaScript, safely.

Writes the model (the visitor's fields, a status lifecycle and staff-only notes, hidden from visitors through field_roles, an admin inbox), a BaseViewSet with create=Public() (Karni's rate limit and honeypot apply by themselves), the tests, the staff app's pages when there is a frontend, and with --notify a queued email to the addresses in that setting. It wires karni-site and its form view. Put {% karni_form "NAME" %} in a site template: the output names the imported design's &lt;form&gt; it replaces, with the arguments that keep its markup.

Example:

```sh
karni make form contact name:str email:email subject:str message:text --notify ENQUIRY_RECIPIENTS
```

```
karni make form [OPTIONS] NAME [FIELDS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | The form's name, snake_case: contact, booking_request, newsletter. |
| `FIELDS...` |  | The fields a visitor fills, as name:type[:arg][?] (karni make model's DSL): str text email url phone int float decimal bool date datetime choice:a\|b country file image fk:Model m2m:Model. A trailing ? makes a field optional. |
| `--notify` TEXT |  | A Django setting (e.g. ENQUIRY_RECIPIENTS) holding the addresses each new submission is emailed to, by a queued listener. Without it nothing is sent. |
| `--states` TEXT |  | The inbox lifecycle of the status field (default new&gt;replied\|new&gt;archived\|replied&gt;archived): a,b,c moves in order, and a&gt;b\|a&gt;c declares each move. The first state is where a submission starts. |
| `--role` TEXT | `staff` | The role that reads, answers and deletes submissions (default staff). |
| `--migrate` |  | Run `karni make migration` for the app afterwards. |
| `--tag` |  | Write nothing: print the {% karni_form %} tag of a form made already, with the arguments that keep the imported design's &lt;form&gt;. Its fields are read from the model unless FIELDS are given. |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make module`

Create modules/karni-NAME/, a reusable module per docs/modules.md.

The karni-NAME distribution with the karni_NAME app, a range-pinned karni dependency, the karni.settings fragment, AGENTS.fragment.md, the catalog entry karni.module.toml and a standalone test suite. Works outside a project too.

```
karni make module [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Module short name (e.g. payments, live-chat). |
| `--dir` PATH |  | Parent directory (default: modules/ in the project, else the cwd). |
| `--force` |  | Create only the missing files of an existing module (keeps the rest). |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

### `karni import`

Import a designer's files into the project.

```
karni import COMMAND [ARGS]...
```

#### `karni import design`

Build the public site from a folder of static pages, keeping the design as written.

Copies the CSS, JavaScript and images into APP/static/APP/ unchanged, puts the header, navigation and footer every page shares into APP/templates/APP/base.html (a block shared by some pages becomes a partial), turns each page into a template extending it with a view and a route (index.html answers "/", about.html "/about/", a folder a nested route), rewrites links to `{% url %}` and asset paths to `{% static %}` (anchors and query strings kept), turns a meta-refresh stub into a permanent redirect, marks the current menu item with `{% ifactive %}` wherever the design marked it, wraps inline scripts in `{% csp_hash %}` so they run under the Content-Security-Policy, and adds every page to the page test. base.html's title, description and share tags go inside `{% karni_seo %}`. Every image of the design gets its width and height, and, with Pillow installed, smaller WebP copies and a srcset. It reports the files it did not see used and anything it could not map. The app is created with `karni make site` when needed.

With --editable, every text becomes a block (`{% editable %}`), every image `{% editable_image %}`, each navigation a menu (`{% get_menu %}`) seeded from the design's links, and the site's name, logo, favicon, phone, email, map and social links come from the site's settings: the client changes all of it in the admin, and the templates hold the design's text as the defaults.

Writes .karni/design.json. A second run with a new version of the design reports the changes and keeps every file the project edited since, and every block keeps its key.

With --map content/design-map.json (karni design analyze --map writes it), the content the map reads into rows gets no blocks: the cards, detail pages and galleries that become models are rendered from the rows, and the client edits the rows in the admin.

```
karni import design [OPTIONS] DIRECTORY
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `DIRECTORY` (required) |  | The folder with the design's HTML pages, CSS, JavaScript and images. |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--diff` |  | Report what changed since the last import and write nothing. |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |
| `--editable/--no-editable` |  | Make every text, image, menu and contact detail editable in the admin (karni-site blocks, menus and site settings). Remembered for later imports. |
| `--map` PATH |  | The content map from karni design analyze --map: with --editable, the content it reads into rows (cards, detail pages, galleries) gets no blocks, because the templates render it from the rows. Remembered for later imports. |

### `karni design`

Read a designer's pages: the models their content needs, and the content itself.

```
karni design COMMAND [ARGS]...
```

#### `karni design analyze`

Find the content that repeats in a design and propose models for it.

Reads every page, sets aside what every page shares (the header, the footer), and finds the structures that repeat within and across pages: cards, list items, a gallery inside each project, a page per doctor. For each it infers the fields from the markup (a heading with its highlighted words kept as ==words==, text, an image with its alt text, a link to another page, a list of tags, a date, a price, a number) and the relations between them (a card that links to a detail page is that page's model, a list of links to other items is a relation). Names come from the design's classes, headings and pages. It prints ready-to-run `karni make model` commands, models others point at first, the decisions the markup cannot settle (a hand-picked list, or one a query derives), and the KARNI_SITE_HIGHLIGHT that renders the highlighted words with `{{ value|highlight }}`.

--map writes a draft content map: which structure is which model and which element is which field. Edit it, answer its decisions, then run `karni design extract`.

Example:

```sh
karni design analyze ../design --map content/design-map.json
```

```
karni design analyze [OPTIONS] DIRECTORY
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `DIRECTORY` (required) |  | The folder with the design's HTML pages. |
| `--app` TEXT |  | The app the models go in (default: the app karni import design used, else website). |
| `--json` |  | Print the analysis as JSON. |
| `--map` PATH |  | Write a draft content map to this file, for karni design extract. |
| `--force` |  | Replace a map file that is there. |

#### `karni design extract`

Write the design's content as a `karni load` file, read with a content map.

Each model's rows come from the pages the map names: a row per item (or per detail page), keyed so the same item read on several pages is one row, its fields read from the elements the map gives and parsed by the field's type. Relations name their rows by key, child rows (a gallery) nest under their parent, and the images are copied next to the output file (files/ beside it, at their path in the design), so `karni load` uploads the designer's own images and the project needs nothing outside it. --keep-paths points into the design folder instead. The map's open decisions must be answered first.

Example:

```sh
karni design extract ../design --map content/design-map.json -o content/site.json
```

```
karni design extract [OPTIONS] DIRECTORY
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `DIRECTORY` (required) |  | The folder with the design's HTML pages. |
| `--map` PATH (required) |  | The content map (karni design analyze --map writes a draft). |
| `--output`, `-o` PATH | `content/site.json` | The content file to write, in the karni load format. |
| `--dry-run` |  | Print what would be written and write nothing. |
| `--keep-paths` |  | Point image paths into the design folder instead of copying the images next to the output file (files/). |

### `karni spec`

The app spec, karni.yaml (experimental): check it (validate), write it from an existing project (export), or answer a question of karni plan --questions (answer).

```
karni spec COMMAND [ARGS]...
```

#### `karni spec validate`

Experimental. Check a karni.yaml: every problem with its code, line and fix.

It checks the YAML, every key and value (unknown keys are errors, keys that start with x- are kept and ignored), each field through karni make model's own parser, and every reference: relations, roles named in access, grants, pages, modules, field groups, keys and owners. Codes are C211 to C242 (karni explain &lt;code&gt;). Exit status 1 when there is a problem.

```
karni spec validate [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--spec` PATH |  | The spec file. Default: karni.yaml in the project root, else in this directory. |
| `--json` |  | Print {file, valid, issues: [{code, line, path, message, fix}]}. |

#### `karni spec export`

Experimental. Write the spec of this project from its code (manage.py karni_facts).

The models become entities (each field in the field syntax when its type makes the same column), the viewsets their access and search, KARNI_ROLES the roles, the settings the features, the installed modules and their changed settings the modules, frontend/src/routes.tsx the pages, and the seeders the seed counts. What the spec cannot express is listed, and kept as comments at the top of the file. The file starts with a yaml-language-server line naming the JSON Schema, for editors.

```
karni spec export [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `-o`, `--output` PATH |  | Write the spec to this file. Default: print it. |
| `--force` |  | Replace the output file if it exists. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

#### `karni spec answer`

Experimental. Write the answer to a question of karni plan --questions into karni.yaml.

The answer goes to the key the question names, and every other line of the file stays as it was: comments, order and layout. The question is then settled and karni plan --questions no longer asks it. Editing the file by hand settles it the same way. An id that is not an open question (C400) and a value the question does not take (C401) are refused, and so is an answer that cannot be written without changing anything else (C402): nothing is written then.

```
karni spec answer [OPTIONS] QUESTION_ID VALUE
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `QUESTION_ID` (required) |  | The question's id, as karni plan --questions prints it. |
| `VALUE` (required) |  | One of its options (several comma-separated when it takes several), or a value of its type when it has none. |
| `--spec` PATH |  | The spec file. Default: karni.yaml in the project root, else in this directory. |

### `karni plan`

Compare karni.yaml with the project: what karni build would change

```
karni plan [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--spec` PATH |  | The spec file. Default: karni.yaml in the project root, else in this directory. |
| `--json` |  | Print {version, file, valid, issues, changes: [{area, action, target, detail, risky, reason, rows}], summary, row_counts} (docs/assets/karni-plan.schema.json). |
| `--offline` |  | Do not open the database: risky changes show no row counts. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |
| `--questions` |  | Print the questions to ask the user before karni build instead of the plan: the gaps of karni.yaml, most impact first. Reads only the spec. With --json, docs/assets/karni-questions.schema.json. |
| `--max` INT RANGE |  | With --questions: show at most N (default 5, 0 shows them all). |

### `karni build`

Make the project match karni.yaml, without touching hand-written code

```
karni build [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--spec` PATH |  | The spec file. Default: karni.yaml in the project root, else in this directory. |
| `--dry-run` |  | Print the plan and the files it would write. Write nothing. |
| `--allow-destructive` |  | Apply the risky (!) changes too: a field or entity removed, a type narrowed, access widened. Without it they stop the build (C270), each named with its rows. |
| `--force` |  | Replace Karni-owned files edited by hand, keeping each as &lt;file&gt;.orig. |
| `--adopt` TEXT (repeatable) |  | Hand a Karni-owned file (or config/settings.py, frontend/src/routes.tsx for their blocks) to the project: karni build stops managing it. Repeatable. |
| `--verbose`, `-v` |  | Print every change of the plan before the steps, as karni plan does. By default the plan is one line, with each risky change under it. |
| `--json` |  | Print {version, file, valid, issues, status, code, message, plan, files, hand_edits, adopted, steps, next} (docs/assets/karni-build.schema.json). |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

## Debugging

### `karni trace`

Follow a captured request: its tasks, retries, email, webhooks, audit

```
karni trace [OPTIONS] REQUEST_ID
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `REQUEST_ID` (required) |  | A request id (the X-Request-ID response header), or `last`. |
| `--json` |  | Print the story as JSON. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni replay`

Re-run a captured request against the current code, as any user

```
karni replay [OPTIONS] REQUEST_ID
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `REQUEST_ID` (required) |  | A captured request id, or `last`. |
| `--as` TEXT |  | Replay as this user: an email, a username or a primary key. |
| `--anonymous` |  | Replay without a user. |
| `--set` TEXT (repeatable) |  | Supply a redacted value: FIELD=VALUE (dotted body path, or query:NAME). Repeatable. |
| `--drop-redacted` |  | Leave redacted values out instead of supplying them. |
| `--commit` |  | Keep the writes. By default the replay is rolled back. |
| `--json` |  | Print the result as JSON. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

## Other

### `karni recipes`

Recipes (experimental): ready-made karni.yaml files a new app starts from, matched to a one-line request (list, show).

```
karni recipes COMMAND [ARGS]...
```

#### `karni recipes list`

Experimental. Every recipe, or with --match the best few for a request, and the blank start.

--match compares the words of the request with each recipe's use_when and purpose, after lowercasing, making plurals singular and leaving out words that name no app (a, the, app, with ...). A recipe scores 2 for each word one of its use_when phrases has and 1 for each word only its purpose has. A word that is the recipe's own noun (its name, or a use_when phrase of that one word) scores 4. The recipes that score 2 or more come back, best first, at most 3. When none does, start from the blank start: karni.yaml with the version and the app's name, nothing else.

```
karni recipes list [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--match` TEXT |  | A one-line request: the best few recipes for it, with their scores (2 for each word of the request a use_when phrase has, 1 for each one only the purpose has). |
| `--json` |  | Print {version, request, threshold, recipes, blank, next, problems} (docs/assets/karni-recipes.schema.json). |

#### `karni recipes show`

Experimental. One recipe: what it is for, what people usually change, its files and spec.

blank shows the blank start: karni.yaml with the version and the app's name, nothing else, where an app starts when no recipe fits. --files prints the recipe's own model methods, actions, seeders and tests, which only karni new --recipe writes into a project.

```
karni recipes show [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | A recipe, or blank for the blank start. |
| `--files` |  | Print the recipe's own domain code instead: each file of its files/ folder, with the path it takes in a project (with --json: {recipe, files: {path: text}}). |
| `--json` |  | Print {version, request, threshold, recipes, blank, next, problems} (docs/assets/karni-recipes.schema.json). |
