# karni-cli

The `karni` command. Orchestrates a Karni project's own `manage.py` via
subprocess — the CLI itself never imports Django.

## Commands
- `karni new <name>` — scaffold a project from the bundled cookiecutter
  template (monorepo checkouts use the live `templates/project`; override with
  `KARNI_TEMPLATES`).
- `karni add <module>` — add `karni-<module>` to `[project].dependencies` and
  wire `karni_<module>` into the `# karni:apps` block in config/settings.py.
  Only that marker block is managed; any other layout gets a clear error and
  you edit settings manually.
  Once the module is installed it also records the module's
  `AGENTS.fragment.md` as `.karni/modules/<module>.md` and refreshes the agent
  adapters.
- `karni types` — dump the OpenAPI schema (`manage.py spectacular`), generate
  `types.ts` (openapi-typescript, project-pinned binary preferred, else
  `npx openapi-typescript@^7`) and typed hooks (`hooks.ts`) over @karni/ui.
- `karni context` — compact machine-readable inventory (< 200 tokens for a
  typical project): APPS (from the `# karni:apps` block) and PAGES (from
  `frontend/src/pages/`) read statically, MODELS/VIEWSETS from `manage.py karni_context`,
  COMPONENTS/HOOKS from @karni/ui's build-generated `dist/manifest.json`
  (omitted when absent — run `npm i @karni/ui` in `frontend/` on the host to
  enable them; `--manifest PATH` overrides). Nothing is hand-maintained.
- `karni context --with-history [PATH]` — the same inventory plus a
  `HISTORY:` brief of what was already asked and decided about PATH (without
  PATH: the project's recorded decisions) from any history provider that
  detects a store, e.g. Gigai Chronicle's `.chronicle/`. Capped at ~300
  tokens (characters ÷ 4), cut at line boundaries with a last line naming the
  full-brief command. With no store the output is exactly `karni context`'s.
  See `docs/concepts/history-providers.md`.
- `karni check [-q]` — Django system checks plus `karni.checks` entry-point hooks
  (the architecture-test extension surface). A clean run outside CI may end
  with one tip on stderr, at most once per project; `-q` suppresses it.
- `karni doctor [-q]` — human-readable environment report: project,
  interpreter (`.venv` / compose service), Node/npm, the @karni/ui manifest,
  adapter freshness, history providers. May end with the same one-time tip.
- `karni config get|set|list [--global] KEY [VALUE]` — settings
  (`suggest_tools`): `.karni/config.toml` in the project (committed) or
  `$XDG_CONFIG_HOME/karni/config.toml` with `--global`; the project wins.
  Machine-local state (e.g. "tip shown") lives in the self-ignoring
  `.karni/local/`.
- `karni rules [--explain CODE | --procedure NAME | --check FILE... | --json]`
  — Karni's conventions from `karni.agent.rules` (no Django needed), and
  static single-file checks (exit 1 on violations).
- `karni rules sync [--check] [--force]` — regenerate the thin agent adapters
  (AGENTS.md, CLAUDE.md, Cursor, Windsurf, Copilot, Cline, Aider, Junie) and
  slash commands from `karni_cli/agent_adapters.toml`; `--check` is the CI
  staleness gate.
- `karni mcp` — context, rules and check as MCP tools
  (`pip install 'karni-cli[mcp]'`).
- `karni upgrade [--list] [--dry-run]` — mechanical migrations between Karni
  versions (codemod: old hand-written agent files -> `karni.rules.py` +
  generated adapters).

See `docs/agents.md` for the agent surface in full.

## Runners
Artisan-style shortcuts. Each runner runs one project command through the
project interpreter (see *Execution environment* below), streams its output
and exits with its exit code. `--help` on each names the command it wraps.
Extra arguments pass straight through; put `--` before any that clash with
karni's own options (`--docker`, `--service`, `--help`).

| Command | Runs |
|---|---|
| `karni serve` | `docker compose up` (`--build`, `-d`) |
| `karni serve --local [--host H] [--port P]` | `manage.py runserver 127.0.0.1:8000` via `.venv` |
| `karni migrate [ARGS]` | `manage.py migrate [ARGS]` |
| `karni test [ARGS]` | `python -m pytest [ARGS]` |
| `karni shell [ARGS]` | `manage.py shell [ARGS]` |
| `karni routes [--json]` | `manage.py karni_routes`: every URL with methods, name, view, model, access |
| `karni worker [-A APP] [-l LEVEL] [ARGS]` | `python -m celery -A config worker -l info [ARGS]` |
| `karni beat [-A APP] [-l LEVEL] [ARGS]` | `python -m celery -A config beat -l info [ARGS]` |
| `karni schedule list [--json]` | `manage.py karni_schedules`: every merged beat schedule |
| `karni schedule run NAME` | `manage.py karni_schedules --run NAME`: runs the task once, synchronously |
| `karni createsuperuser [ARGS]` | `manage.py createsuperuser [ARGS]` |
| `karni manage ARGS` | `manage.py ARGS`: the raw passthrough for everything else |

In docker mode, `shell`, `test`, `worker`, `beat`, `createsuperuser` and
`manage` get a TTY (`docker compose exec` without `-T`) when karni runs in a
terminal, so prompts and Ctrl-C work. Scripted and agent runs keep `-T`.
With the compose stack up, `worker` and `beat` already run as services, so
`karni worker` and `karni beat` are for `.venv` development. See
`docs/events.md` and `docs/scheduling.md`.

## Generators
`karni make <type>` writes the project code a task needs, so neither a person
nor an AI agent hand-creates a file a generator makes. `karni make --list`
prints them all; every one is also a hidden Laravel-style alias
`karni make:<type>`. The full reference (every option, the field DSL) is
[docs/cli.md](../../docs/cli.md), generated from this CLI.

| Command | Writes |
|---|---|
| `karni make app NAME` | `NAME/{__init__,apps,models,viewsets}.py`, `migrations/`, `tests/`; wires `# karni:apps` |
| `karni make model NAME [FIELD...]` | `class NAME(BaseModel)` in `<app>/models.py`; `--with viewset,page` / `-a` chains; `--migrate` |
| `karni make viewset MODEL` | `<Model>ViewSet` with its `access` (`--access authenticated\|public-read\|owned:<field>\|staff\|role:<name>`), `--search` |
| `karni make serializer MODEL --reason ...` | `<app>/serializers.py` + `serializer_class` on the viewset |
| `karni make migration [NAME]` | runs `manage.py makemigrations [--app] [--name] [--empty]` through the project interpreter |
| `karni make task NAME` | `@shared_task` in `<app>/tasks.py` (`--retry N`) |
| `karni make schedule NAME` | `every(...)`/`cron(...)` in `<app>/schedules.py` (`--every 15m` / `--cron "0 3 * * *"`, `--task`) |
| `karni make event NAME` | a `Signal` in `<app>/events.py` |
| `karni make listener NAME --on ...` | `<app>/listeners.py`: `Model.created\|updated\|deleted` or a custom event; `--queued` |
| `karni make command NAME` | `<app>/management/commands/NAME.py` |
| `karni make service NAME` | `<app>/services/NAME.py` (where HTTP clients are allowed) |
| `karni make middleware NAME` | `<app>/middleware.py`, wired through `# karni:middleware` |
| `karni make page NAME` | `frontend/src/pages/NAME.tsx` (≤ 50 lines; `--resource R --kind list\|detail\|form`), route in `frontend/src/routes.tsx` |
| `karni make component NAME` | `frontend/src/components/NAME.tsx` claiming a role (`--role`) |
| `karni make module NAME` | `modules/karni-NAME/` per docs/modules.md |

```sh
karni make app events
karni make model Event title:str:200 starts_at:datetime "status:choice:draft|live" \
    organizer:fk:User 'venue:fk:Venue?' -a --access owned:organizer --search title
karni make migration && karni migrate
karni make listener notify_organizer --on Event.created --queued
karni make schedule nightly-report --cron "0 3 * * *"
```

Every generator: never overwrites without `--force`; `--dry-run` prints the
files and diff and writes nothing; prints each created/modified file plus
notes (the chosen `access`, the route, the next command); resolves the app
from `--app` or the project's only local app; edits existing files only
through marker comments or AST-located appends (an unfamiliar layout is an
error naming the manual step); never imports Django. Generated Python is
clean under ruff (lint and format) and `karni rules --check`, and generated
pages parse and stay within 50 lines — `tests/test_make_gate.py` generates
every type into a fresh scaffold and asserts it (plus `tsc` and the
frontend's ESLint config when `KARNI_TEST_NODE_MODULES` points at an
installed `frontend/node_modules`), then runs the generated backend for real
(makemigrations, migrate, check, requests through the Django test client).

Quote fields that end in `?` in zsh (`'venue:fk:Venue?'`) and choice values
joined by `|`.

## Execution environment
Commands that run the project resolve, in order: `--docker/--no-docker` flag →
`<project>/.venv` → a running compose service (default `django`; change with
`--service` or `KARNI_COMPOSE_SERVICE`) → an error naming both remedies.
