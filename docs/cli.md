---
description: Every karni command with its arguments and options, generated from the CLI's own help text.
---

# The `karni` command

> Generated from the CLI itself — `python -m karni_cli.clidoc > docs/cli.md`;
> `packages/karni-cli/tests/test_clidoc.py` fails when this file is stale.
> Change a command's help, then regenerate; never edit this file by hand.

`karni <command> --help` prints the same information. Runners execute in the
project environment: the project's `.venv`, else the running docker compose
service (`--docker/--no-docker` forces one; `--service` / `KARNI_COMPOSE_SERVICE`
names it). Put `--` before passthrough arguments that clash with karni's own
options.

On the host, a command that starts Django first checks that the database
driver loads, and one that opens the database (`migrate`, `seed`,
`serve --local`, `test`, ...) that the server answers. A missing driver or an
unreachable database is a coded error with the fix
([C012](errors.md#c012), [C013](errors.md#c013)) instead of Django's
traceback; `KARNI_DB_CHECK=false` skips the check.

## Contents

- **Project**: [new](#karni-new), [add](#karni-add), [upgrade](#karni-upgrade), [doctor](#karni-doctor), [config](#karni-config)
- **Agents and checks**: [context](#karni-context), [rules](#karni-rules), [check](#karni-check), [explain](#karni-explain), [types](#karni-types), [mcp](#karni-mcp)
- **Runners**: [serve](#karni-serve), [migrate](#karni-migrate), [test](#karni-test), [shell](#karni-shell), [routes](#karni-routes), [worker](#karni-worker), [beat](#karni-beat), [schedule](#karni-schedule), [seed](#karni-seed), [sync-roles](#karni-sync-roles), [createsuperuser](#karni-createsuperuser), [manage](#karni-manage)
- **Debugging**: [why](#karni-why), [why-empty](#karni-why-empty)
- **Generators**: [make](#karni-make)

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

Read and write Karni settings: project .karni/config.toml (committed) or --global ~/.config/karni/config.toml; the project wins.

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

## Agents and checks

### `karni context`

Print a compact machine-readable project inventory

```
karni context [OPTIONS] [PATH]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `PATH` |  | File to brief, relative to the cwd (needs --with-history). |
| `--with-history` |  | Append what a history provider (e.g. Gigai Chronicle) recorded about PATH under a HISTORY: heading — without PATH, the project's recorded decisions, from providers that offer them. Capped at ~300 tokens (~1200 characters), cut at line boundaries with a last line naming the command for the full brief. With no history store detected, prints the plain inventory and nothing else. |
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
| `--check` PATH (repeatable) |  | Statically check FILE (repeatable); exit 1 on violations. |
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
| `--check` |  | Only compare; exit 1 if any adapter is stale (for CI). |
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

Explain an error code (E104, C101, PAY004, K106): why and the fix

```
karni explain [OPTIONS] CODE
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `CODE` (required) |  | An error code such as E104, W101, C101, PAY004 or K106. |
| `--json` |  | Machine-readable output. |

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

Serve context, rules and check as MCP tools (needs karni-cli[mcp])

```
karni mcp [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--project` PATH |  | Project root (default: found from the working directory). |

## Runners

### `karni serve`

Start the dev stack — wraps `docker compose up` (or `manage.py runserver` with --local).

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

Apply migrations — wraps `manage.py migrate [ARGS]`.

```
karni migrate [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to manage.py migrate: [app_label] [migration_name] --plan --fake … |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni test`

Run the test suite — wraps `python -m pytest [ARGS]`.

```
karni test [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to pytest: paths, -k EXPR, -x, --lf … (use -- before --help). |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni shell`

Open a Django shell — wraps `manage.py shell [ARGS]`.

```
karni shell [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to manage.py shell: -c CODE, -i ipython … |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni routes`

List every URL: methods, name, view, model, access — wraps `manage.py karni_routes`.

```
karni routes [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--json` |  | Print the routes as a JSON list. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni worker`

Run a Celery worker — wraps `python -m celery -A config worker -l info [ARGS]`.

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

Run Celery beat — wraps `python -m celery -A config beat -l info [ARGS]`.

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

Celery beat schedules — wraps `manage.py karni_schedules`.

```
karni schedule COMMAND [ARGS]...
```

#### `karni schedule list`

List every schedule: name, task, timing, source — wraps `manage.py karni_schedules`.

```
karni schedule list [OPTIONS]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--json` |  | Print the schedules as a JSON list. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

#### `karni schedule run`

Run one schedule's task now, synchronously — wraps `manage.py karni_schedules --run NAME`.

```
karni schedule run [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | The schedule name (see `karni schedule list`). |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni seed`

Fill every model with realistic demo data — wraps `manage.py karni_seed [ARGS]`.

Values come from field names and types (an `email` gets an email, `price` money, `starts_at` a near-future date); relations point at seeded rows; the same --seed gives the same rows. Prints a demo login (demo@example.com / karni-password). Per-model overrides live in &lt;app&gt;/seeds.py (`karni make seeder <Model>`).

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

Create or update the roles KARNI_ROLES declares — wraps `manage.py karni_sync_roles [ARGS]`.

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

Create an admin user — wraps `manage.py createsuperuser [ARGS]`.

```
karni createsuperuser [OPTIONS] [ARGS...]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `ARGS...` |  | Passed to manage.py createsuperuser: --email E, --noinput … |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

### `karni manage`

Run any management command — wraps `manage.py ARGS` (raw passthrough).

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
| `TARGET` (required) |  | What to explain: &lt;resource&gt;/&lt;id&gt; (a row), &lt;resource&gt;.&lt;field&gt; (a field), &lt;resource&gt; (its list), or a status followed by a request id (403 &lt;request-id&gt;). Resources are named as the API names them: events, events-event or events.Event. |
| `REQUEST_ID` |  | The request id, after a status. |
| `--as` TEXT |  | The user: email, username, primary key, or anonymous. |
| `--action` TEXT |  | For a row: view (default), update, delete, or an @action name; create or list for a resource. |
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

Generate project code: apps, models, viewsets, tasks, schedules, listeners, pages ... (`karni make --list`). Never overwrites without --force; --dry-run previews.

```
karni make [OPTIONS] COMMAND [ARGS]...
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `--list` |  | Print every generator with a one-line summary. |

Every generator follows the same rules:

- It writes project code only — never framework logic.
- It never overwrites: an existing target is an error naming the file and
  `--force` (which replaces it).
- `--dry-run` prints the files and the diff it would write, and writes nothing.
- It prints every created and modified file, then any notes (the chosen
  `access`, the route, the next command).
- The target app is `--app <label>`, else the project's only local app (local
  apps are the `# karni:apps` entries of config/settings.py).
- Existing files change only through marker comments (`# karni:apps`,
  `# karni:middleware`, `// karni:page-imports`, `// karni:routes`) or
  AST-located appends; an unfamiliar layout is an error that names the manual
  step. Generated Python is ruff-clean (isort sections, ruff format layout).
- It never imports Django: `karni make migration` (and `make model --migrate`)
  run `manage.py makemigrations` through the project interpreter.
- Every generator is also available as a hidden Laravel-style alias:
  `karni make:<type>` (e.g. `karni make:model Event title:str`).

`karni make --list`:

```
app         Create a local Django app (models.py, viewsets.py) wired into # karni:apps.
model       Add a model on BaseModel from a field DSL; --with viewset,page,test or -a chains them.
viewset     Add a BaseViewSet for a model, with its access declaration (--access).
serializer  Add an explicit serializer (--reason required) and set serializer_class.
migration   Create migrations: wraps manage.py makemigrations [app] [--name] [--empty].
test        Add <app>/tests/test_<model>.py: assert_crud + the isolation check for a resource.
factory     Add an explicit test factory to <app>/factories.py (overrides the generated one).
seeder      Add a Seeder to <app>/seeds.py: per-model rows and values for karni seed.
task        Add a Celery task (@shared_task) to <app>/tasks.py; --retry N.
schedule    Add a beat schedule (every/cron) to <app>/schedules.py, creating the task if needed.
event       Add a custom event (a Django Signal) to <app>/events.py.
listener    Add a listener to <app>/listeners.py: --on Model.created|updated|deleted or an event.
command     Add a management command (<app>/management/commands/<name>.py).
service     Add a service module (<app>/services/<name>.py) — the home of HTTP clients.
middleware  Add a middleware class to <app>/middleware.py, wired via # karni:middleware.
page        Add a frontend page (<= 50 lines) composing @karni/ui, with its route.
component   Add a React component that claims a role (registerComponentRole).
module      Create a reusable module skeleton: modules/karni-<name>/ (docs/modules.md).
```

Field DSL for `karni make model NAME [FIELD...]`:

| Field | Generates |
| --- | --- |
| `title:str[:len]` | CharField(max_length=len) — 255 when omitted |
| `body:text` | TextField() |
| `count:int` | IntegerField() |
| `ratio:float` | FloatField() |
| `price:decimal[:max:places]` | DecimalField(max_digits=max, decimal_places=places) — 10, 2 |
| `done:bool` | BooleanField(default=False) |
| `day:date / at:datetime` | DateField() / DateTimeField() |
| `email:email / site:url / slug:slug` | EmailField() / URLField() / SlugField() (:len optional) |
| `meta:json` | JSONField(default=dict) |
| `doc:file / photo:image` | FileField / ImageField(upload_to="&lt;app&gt;/&lt;model&gt;/") — image needs Pillow |
| `ref:uuid` | UUIDField(default=uuid.uuid4) |
| `status:choice:draft\|live` | a TextChoices class + CharField(choices=..., default=first) |
| `owner:fk:User` | ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE) |
| `venue:fk:Venue / fk:shop.Venue` | ForeignKey("Venue") in the same app, or "app.Model" |
| `tags:m2m:Tag / profile:o2o:User` | ManyToManyField / OneToOneField |
| `name:type?` | optional: null=True, blank=True (strings and files: blank=True) |

#### `karni make app`

Create a local app — replaces `manage.py startapp`.

Writes NAME/{__init__,apps,models,viewsets}.py, NAME/migrations/ and NAME/tests/, and adds NAME to the `# karni:apps` block of config/settings.py. No admin.py, serializers.py or urls.py: Karni derives them. An existing app is never truncated: --force only fills in missing files.

```
karni make app [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | App label, snake_case (e.g. events). |
| `--force` |  | Create only the missing files of an existing app (keeps the rest). |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

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
| `FIELDS...` |  | Fields as name:type[:arg][?] — str[:len] text int float decimal[:max:places] bool date datetime email url slug json file image uuid choice:a\|b fk:Model m2m:Model o2o:Model; trailing ? = optional. |
| `--with` TEXT (repeatable) |  | Also generate: viewset, page, test, factory, seeder (comma-separated or repeated). |
| `--all`, `-a` |  | Also generate the viewset, the pages and the API test. |
| `--access` TEXT |  | With viewset: granted\|authenticated\|public-read\|owned:&lt;field&gt;\|staff\|role:&lt;name&gt;. |
| `--search` TEXT (repeatable) |  | With viewset: search_fields (comma-separated). |
| `--migrate` |  | Run `karni make migration` for the app afterwards. |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make viewset`

Add `<Model>ViewSet(BaseViewSet)` to APP/viewsets.py — CRUD at /api/&lt;models&gt;/.

Declares `model = <Model>` and the mandatory `access` (ADR 0001): granted (default: whatever KARNI_ROLES grants for the model, row-scoped), authenticated, public-read (anonymous reads), owned:&lt;field&gt; (rows whose &lt;field&gt; is the user), staff (role "staff"), role:&lt;name&gt;.

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
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make serializer`

Add `<Model>Serializer` to APP/serializers.py and set the viewset's serializer_class.

BaseViewSet generates the serializer and APIMeta steers it, so an explicit one needs --reason; it is recorded as the `# karni: allow(redundant-serializer): <reason>` marker.

```
karni make serializer [OPTIONS] MODEL
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODEL` (required) |  | Model class name (e.g. Event). |
| `--reason` TEXT |  | Why the generated serializer is not enough (required). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make migration`

Create migrations — wraps `manage.py makemigrations [APP] [--name NAME] [--empty]`.

Without --app every app with model changes gets a migration; --empty (a data migration) targets one app: --app, else the only local app. --dry-run is makemigrations' own (prints, writes nothing).

```
karni make migration [OPTIONS] [NAME]
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` |  | Migration name (makemigrations --name), e.g. add_event_capacity. |
| `--empty` |  | An empty migration to fill in (data migrations); needs one app. |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |
| `--docker/--no-docker` |  |  |
| `--service` TEXT | `django` | Env: `KARNI_COMPOSE_SERVICE`. |

#### `karni make test`

Add APP/tests/test_&lt;model&gt;.py — the resource's whole API surface in a few lines.

One APITestCase: `assert_crud` checks list, retrieve, create, update, delete, the denials the access declaration promises, pagination, filtering and the OpenAPI contract; `assert_isolated` (when reads are Owned, or Granted() with an own/related grant) checks another scope's rows are out of reach on every surface. Run it with `karni test`.

```
karni make test [OPTIONS] MODEL
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODEL` (required) |  | Model class name (e.g. Event); it needs a viewset. |
| `--role` TEXT |  | The role the test acts as. Default: the first HasRole the viewset declares; for Granted() the first KARNI_ROLES role whose grant reaches the model (own/related first); else any signed-in user. |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

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
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make seeder`

Add `<Model>Seeder(Seeder)` to APP/seeds.py, read by `karni seed`.

Only needed to steer a model's demo data: Meta.count pins its rows per run, and a class attribute overrides a field (a value or a factory-boy declaration); every other field stays inferred from its name and type.

```
karni make seeder [OPTIONS] MODEL
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `MODEL` (required) |  | Model class name (e.g. Event). |
| `--count` INTEGER |  | Rows per `karni seed` run for this model (0 skips it). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

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
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make schedule`

Add every(...)/cron(...) to APP/schedules.py — merged into Celery beat at startup.

Without --task the schedule runs APP.tasks.&lt;name&gt; (dashes become underscores), which is created when missing.

```
karni make schedule [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Schedule name, unique in the project (e.g. nightly-report). |
| `--every` TEXT |  | Interval: 30s, 15m, 1h, 1h30m, 1d. |
| `--cron` TEXT |  | Five-field crontab, e.g. "0 3 * * *" (03:00 daily). |
| `--task` TEXT |  | Dotted task to run (default: APP.tasks.&lt;name&gt;, created if missing). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

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
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make listener`

Add a listener to APP/listeners.py (autodiscovered — no AppConfig.ready wiring).

--on Event.created|updated|deleted uses karni.events (soft deletes count as deleted); --on order_shipped receives a custom event from events.py.

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
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

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
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make service`

Add APP/services/NAME.py — the one place HTTP clients are allowed (K105).

```
karni make service [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Service module name, snake_case (e.g. stripe_client). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make middleware`

Add a middleware class to APP/middleware.py and wire it into MIDDLEWARE.

Wiring goes through the `# karni:middleware` block of config/settings.py (appended after Karni's middleware); without that block the command prints the line to add.

```
karni make middleware [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Class name, PascalCase (Middleware suffix added). |
| `--app` TEXT |  | Target app label (default: the project's only local app). |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make page`

Add frontend/src/pages/NAME.tsx (&lt;= 50 lines) and register its route.

--resource R --kind list|detail|form composes ResourceTable / ResourceDetail / ResourceForm for the API resource R; without --resource the page is a bare &lt;Page&gt;. Routes: list &lt;base&gt;, detail &lt;base&gt;/$id, form &lt;base&gt;/new and &lt;base&gt;/$id/edit, base = --path or /&lt;resource&gt;.

```
karni make page [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Page file name, kebab-case (e.g. events). |
| `--resource` TEXT |  | API resource (router prefix, e.g. events). |
| `--kind` TEXT |  | With --resource: list (default), detail or form; login needs no resource. |
| `--path` TEXT |  | Route path (resource pages: the base, default /&lt;resource&gt;). |
| `--title` TEXT |  | Page title (default: from the name). |
| `--no-route` |  | Do not register the route in frontend/src/routes.tsx. |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make component`

Add frontend/src/components/NAME.tsx, registered with registerComponentRole.

A role already claimed by @karni/ui (its manifest) or by another project component is refused — compose that component instead, or pass --replace-reason to replace it on purpose.

```
karni make component [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Component name, PascalCase (e.g. StatusBadge). |
| `--role` TEXT |  | Semantic role it claims (default: kebab-case of NAME). |
| `--replace-reason` TEXT |  | Take over a role another component claims, saying why. |
| `--force` |  | Overwrite / replace existing targets. |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |

#### `karni make module`

Create modules/karni-NAME/ — a reusable module per docs/modules.md.

The karni-NAME distribution with the karni_NAME app, a range-pinned karni dependency, the karni.settings fragment, AGENTS.fragment.md and a standalone test suite. Works outside a project too.

```
karni make module [OPTIONS] NAME
```

| Argument / option | Default | Description |
| --- | --- | --- |
| `NAME` (required) |  | Module short name (e.g. payments, live-chat). |
| `--dir` PATH |  | Parent directory (default: modules/ in the project, else the cwd). |
| `--force` |  | Create only the missing files of an existing module (keeps the rest). |
| `--dry-run` |  | Print the files and diff it would write; write nothing. |
