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

- **Project**: [new](#karni-new), [add](#karni-add), [upgrade](#karni-upgrade), [doctor](#karni-doctor), [config](#karni-config)
- **Frontend**: [ui](#karni-ui)
- **Agents and checks**: [context](#karni-context), [rules](#karni-rules), [check](#karni-check), [explain](#karni-explain), [types](#karni-types), [mcp](#karni-mcp)
- **Debugging**: [queries](#karni-queries)
- **Runners**: [serve](#karni-serve), [migrate](#karni-migrate), [test](#karni-test), [shell](#karni-shell), [routes](#karni-routes), [schema](#karni-schema), [worker](#karni-worker), [beat](#karni-beat), [schedule](#karni-schedule), [seed](#karni-seed), [sync-roles](#karni-sync-roles), [createsuperuser](#karni-createsuperuser), [manage](#karni-manage)
- **Debugging**: [why](#karni-why), [why-empty](#karni-why-empty)
- **Generators**: [make](#karni-make)
- **Debugging**: [trace](#karni-trace), [replay](#karni-replay)

## Project

### `karni new`

Scaffold a project from templates/project

```
karni new [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Project name (slug is derived from it) |
| `--output-dir`, `-o` PATH | `.` |  |
| `--domain` TEXT | `example.com` | Production domain for Caddy |

### `karni add`

Install an optional module and wire it into settings

```
karni add MODULE
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODULE` (required) |  | Module short name, e.g. "payments" |

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

Writes one file the project owns, `karni-theme.css`, imported after `@karni/ui/styles.css` (wired into `src/main.tsx` when it has the scaffold's import). The report lists every token mapped (from, to, value) and every value not mapped, with the reason. A generated file edited since is never overwritten without `--force`.

Example:

```sh
karni ui detect --dry-run
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

## Agents and checks

### `karni context`

Print a compact machine-readable project inventory

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

### `karni rules`

Karni's conventions for humans and AI agents (no Django needed).

```
karni rules [OPTIONS] COMMAND [ARGS]...
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--check` PATH (repeatable) |  | Statically check FILE (repeatable) and exit 1 on violations. |
| `--explain` TEXT |  | Show one rule in full. |
| `--procedure` TEXT |  | Show a procedure's steps. |
| `--json` |  | Machine-readable output. |

#### `karni rules sync`

Regenerate the agent adapter files from Karni's rule registry.

```
karni rules sync [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--check` |  | Only compare, and exit 1 if any adapter is stale (for CI). |
| `--force` |  | Overwrite hand-written files (backed up under .karni/backup/). |

### `karni check`

Run architecture and system checks

```
karni check [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |
| `--frontend/--no-frontend` | on |  |
| `--quiet`, `-q` |  | Do not print the optional tip. |

### `karni explain`

Explain an error code (E104, C101, PAY004, K106), or a pasted traceback or log line (karni explain -): class, cause, where, fix

```
karni explain [OPTIONS] [CODE]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `CODE` |  | An error code such as E104, W101, C101, PAY004 or K106. Pass - to read a traceback or log line from stdin. |
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

Serve context, rules, check, explain_text and queries as MCP tools (needs karni-cli[mcp])

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
| `--explain` |  | Add EXPLAIN plans for the slowest queries. |
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
| `--port` INTEGER |  | --local only. Default 8000. |
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

A host worker on macOS gets `--pool=solo` (the prefork pool cannot run tasks there).

```
karni worker [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to celery worker: -Q QUEUES, --concurrency N … |
| `--app`, `-A` TEXT | `config` | Celery app module. Env: `KARNI_CELERY_APP`. |
| `--loglevel`, `-l` TEXT | `info` |  |
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

Example:

```sh
karni seed --count 20 --seed 42 --reset
```

```
karni seed [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to manage.py karni_seed: --count N, --seed S, --reset, --model app.Model, --json, --force. |
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
| `country:country / currency:currency` | CountryField() / CurrencyField() with a CHECK against the ISO list |
| `meta:json[:queried]` | JSONField(default=dict), and queried adds a GIN index |
| `tags:array:str[:len]` | ArrayField(models.CharField(...)) with a GIN index, PostgreSQL only |
| `doc:file / photo:image` | FileField / ImageField with `upload_to="<app>/<model>/"`. Image needs Pillow |
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

Add `class NAME(BaseModel)` with FIELDS to APP/models.py.

Example:

```sh
karni make model Event title:str:200 starts_at:datetime "status:choice:draft|live" organizer:fk:User 'venue:fk:Venue?' -a --access owned:organizer
```

```
karni make model [OPTIONS] NAME [FIELDS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Model class name, PascalCase (e.g. Event). |
| `FIELDS...` |  | Fields as name:type[:arg][?]. Types: str[:len] text int float decimal[:max:places] bool date datetime url file image uuid choice:a\|b fk:Model m2m:Model o2o:Model. Typed fields (karni.fields): money[:EUR] percent[:min:max] quantity email[:unique] slug[:source] phone country currency json[:queried] array:str. A trailing ? makes the field optional. |
| `--with` TEXT (repeatable) |  | Also generate: viewset, page, test, factory, seeder (comma-separated or repeated). |
| `--all`, `-a` |  | Also generate the viewset, the pages and the API test. |
| `--access` TEXT |  | With viewset: granted\|authenticated\|public-read\|owned:&lt;field&gt;\|staff\|role:&lt;name&gt;. |
| `--search` TEXT (repeatable) |  | With viewset: search_fields (comma-separated). |
| `--migrate` |  | Run `karni make migration` for the app afterwards. |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

#### `karni make viewset`

Add `<Model>ViewSet(BaseViewSet)` to APP/viewsets.py, with CRUD at `/api/<models>/`.

It declares `model = <Model>` and the mandatory `access` (ADR 0001): granted (default: whatever KARNI_ROLES grants for the model, row-scoped), authenticated, public-read (anonymous reads), `owned:<field>` (rows whose `<field>` is the user), staff (role "staff") or `role:<name>`.

```
karni make viewset [OPTIONS] MODEL
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODEL` (required) |  | Model class name (e.g. Event). |
| `--access` TEXT |  | Who reads/writes: granted\|authenticated\|public-read\|owned:&lt;field&gt;\|staff\|role:&lt;name&gt;. Default: granted (the roles' grants). |
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
| `--role` TEXT |  | The role the test acts as. By default it is the first HasRole the viewset declares. For Granted() it is the first KARNI_ROLES role whose grant reaches the model (own/related first). Otherwise the test uses any signed-in user. |
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

With --resource R --kind list|detail|form the page composes ResourceTable / ResourceDetail / ResourceForm for the API resource R. Without --resource the page is a bare `<Page>`. Routes: list at `<base>`, detail at `<base>/$id`, form at `<base>/new` and `<base>/$id/edit`, where the base is --path or `/<resource>`.

```
karni make page [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Page file name, kebab-case (e.g. events). |
| `--resource` TEXT |  | API resource (router prefix, e.g. events). |
| `--kind` TEXT |  | With --resource: list (default), detail or form. A login page needs no resource. |
| `--path` TEXT |  | Route path. For resource pages it is the base (default `/<resource>`). |
| `--title` TEXT |  | Page title (default: from the name). |
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

Writes NAME/views.py (a home view), NAME/urls.py (app_name NAME, a `# karni:urls` marker), NAME/templates/NAME/base.html and home.html, NAME/templates/404.html, NAME/static/NAME/site.css and a page test, then inserts `path("", include("NAME.urls"))` at the `# karni:urls` marker of config/urls.py, so the home page replaces the welcome page. A new app also gets the `karni make app` skeleton and the `# karni:apps` entry. An existing app keeps every file it has. Add pages with `karni make view`.

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

Writes `def NAME(request)` in APP/views.py, APP/templates/APP/NAME.html extending the site's base.html, and `path(..., views.NAME, name="NAME")` at the `# karni:urls` marker of APP/urls.py. The app must come from `karni make site`.

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

#### `karni make module`

Create modules/karni-NAME/, a reusable module per docs/modules.md.

The karni-NAME distribution with the karni_NAME app, a range-pinned karni dependency, the karni.settings fragment, AGENTS.fragment.md and a standalone test suite. Works outside a project too.

```
karni make module [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Module short name (e.g. payments, live-chat). |
| `--dir` PATH |  | Parent directory (default: modules/ in the project, else the cwd). |
| `--force` |  | Create only the missing files of an existing module (keeps the rest). |
| `--dry-run` |  | Print the files and diff it would write, but write nothing. |

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
