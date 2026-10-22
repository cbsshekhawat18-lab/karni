# karni-cli

The `karni` command. It runs a Karni project's own `manage.py` as a
subprocess, so the CLI itself never imports Django.

## Commands
- `karni new <name>`: scaffold a project from the bundled cookiecutter
  template. Monorepo checkouts use the live `templates/project`, and
  `KARNI_TEMPLATES` overrides it.
- `karni add <module>`: add `karni-<module>` to `[project].dependencies` and
  wire `karni_<module>` into the `# karni:apps` block in config/settings.py.
  Only that marker block is managed. Any other layout gets a clear error, and
  you edit settings manually.
  Once the module is installed it also records the module's
  `AGENTS.fragment.md` as `.karni/modules/<module>.md` and refreshes the agent
  adapters.
- `karni types`: dump the OpenAPI schema (`manage.py spectacular`), generate
  `types.ts` (openapi-typescript, project-pinned binary preferred, else
  `npx openapi-typescript@^7`) and typed hooks (`hooks.ts`) over @karni/ui.
- `karni ui detect`: map the frontend's design system (shadcn/ui, a Tailwind
  theme, Material UI, Chakra UI or Mantine) onto @karni/ui's `--karni-*`
  tokens in `karni-theme.css`, plus `karni-primitives.tsx` for shadcn/ui.
  `--dry-run` previews, `--json` reports for agents, and edited files are kept
  unless `--force`.
- `karni context`: a compact machine-readable inventory (< 200 tokens for a
  typical project). APPS (from the `# karni:apps` block) and PAGES (from
  `frontend/src/pages/`) are read statically, MODELS/VIEWSETS come from `manage.py karni_context`,
  and COMPONENTS/HOOKS from @karni/ui's build-generated `dist/manifest.json`.
  Those two are omitted when the manifest is absent. Run `npm i @karni/ui` in
  `frontend/` on the host to enable them, or override with `--manifest PATH`.
  Nothing is hand-maintained.
- `karni context --with-history [PATH]`: the same inventory plus a
  `HISTORY:` brief of what was already asked and decided about PATH (without
  PATH: the project's recorded decisions) from any history provider that
  detects a store, e.g. Gigai Chronicle's `.chronicle/`. Capped at ~300
  tokens (characters ÷ 4), cut at line boundaries with a last line naming the
  full-brief command. With no store the output is exactly `karni context`'s.
  See `docs/concepts/history-providers.md`.
- `karni check [-q]`: Django system checks plus `karni.checks` entry-point hooks
  (the architecture-test extension surface). A clean run outside CI may end
  with one tip on stderr, at most once per project. `-q` suppresses it.
- `karni doctor [-q]`: a human-readable environment report covering the
  project, interpreter (`.venv` / compose service), Node/npm, the @karni/ui
  manifest, adapter freshness and history providers. It may end with the same
  one-time tip.
- `karni config get|set|list [--global] KEY [VALUE]`: settings
  (`suggest_tools`), kept in `.karni/config.toml` in the project (committed) or
  in `$XDG_CONFIG_HOME/karni/config.toml` with `--global`. The project wins.
  Machine-local state (e.g. "tip shown") lives in the self-ignoring
  `.karni/local/`.
- `karni rules [--explain CODE | --procedure NAME | --check FILE... | --json]`:
  Karni's conventions from `karni.agent.rules` (no Django needed), and
  static single-file checks (exit 1 on violations).
- `karni rules sync [--check] [--force]`: regenerate the thin agent adapters
  (AGENTS.md, CLAUDE.md, Cursor, Windsurf, Copilot, Cline, Aider, Junie) and
  slash commands from `karni_cli/agent_adapters.toml`. `--check` is the CI
  staleness gate.
- `karni mcp`: context, rules and check as MCP tools
  (`pip install 'karni-cli[mcp]'`).
- `karni upgrade [--to VERSION] [--from VERSION] [--dry-run] [--allow-dirty] [--list]`
  moves the project across Karni versions. It reads the karni installed in
  the project (`--from` overrides), takes every breaking change between that
  and `--to` from Karni's machine-readable changelog
  (`packages/karni/karni/changelog/*.toml`, bundled into karni-cli), and runs
  their codemods in release order. Python codemods use libcst. TypeScript
  codemods use a pinned jscodeshift through `npx`, and without Node.js they
  are skipped with the reason. The codemods run on a scratch copy, and the result
  is written back all at once, or not at all if one fails. `--dry-run` prints
  a unified diff and writes nothing. Writing needs a clean git tree.
  `--allow-dirty` overrides that, and is also required outside git. The
  report lists what was applied (each file and its rewrite count), what could
  not be fixed automatically (the sites found, with each migration-note link)
  and what was skipped. Run it before you raise the karni pin. See
  `docs/migrations/`.

See `docs/agents.md` for the agent surface in full.

## Runners
Artisan-style shortcuts. Each runner runs one project command through the
project interpreter (see *Execution environment* below), streams its output
and exits with its exit code. `--help` on each names the command it wraps.
Extra arguments pass straight through. Put `--` before any that clash with
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
prints them all. Each one is also available as a hidden Laravel-style alias,
`karni make:<type>`. The full reference (every option, the field DSL) is
[docs/cli.md](https://cbsshekhawat18-lab.github.io/karni/cli/), generated from this CLI.

| Command | Writes |
|---|---|
| `karni make app NAME` | `NAME/{__init__,apps,models,viewsets}.py`, `migrations/`, `tests/`, and wires `# karni:apps` |
| `karni make model NAME [FIELD...]` | `class NAME(BaseModel)` in `<app>/models.py`, with `--with viewset,page` / `-a` chains and `--migrate` |
| `karni make viewset MODEL` | `<Model>ViewSet` with its `access` (`--access authenticated\|public-read\|owned:<field>\|staff\|role:<name>`), `--search` |
| `karni make serializer MODEL --reason ...` | `<app>/serializers.py` + `serializer_class` on the viewset |
| `karni make migration [NAME]` | runs `manage.py makemigrations [--app] [--name] [--empty]` through the project interpreter |
| `karni make task NAME` | `@shared_task` in `<app>/tasks.py` (`--retry N`) |
| `karni make schedule NAME` | `every(...)`/`cron(...)` in `<app>/schedules.py` (`--every 15m` / `--cron "0 3 * * *"`, `--task`) |
| `karni make event NAME` | a `Signal` in `<app>/events.py` |
| `karni make listener NAME --on ...` | `<app>/listeners.py`: `Model.created\|updated\|deleted` or a custom event, with `--queued` |
| `karni make command NAME` | `<app>/management/commands/NAME.py` |
| `karni make service NAME` | `<app>/services/NAME.py` (where HTTP clients are allowed) |
| `karni make middleware NAME` | `<app>/middleware.py`, wired through `# karni:middleware` |
| `karni make page NAME` | `frontend/src/pages/NAME.tsx` (≤ 50 lines, `--resource R --kind list\|detail\|form`), route in `frontend/src/routes.tsx` |
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

Every generator follows the same rules. It never overwrites without
`--force`, and `--dry-run` prints the files and diff and writes nothing. It
prints each created/modified file plus notes (the chosen `access`, the route,
the next command). It resolves the app from `--app` or the project's only
local app. It edits existing files only through marker comments or
AST-located appends, and an unfamiliar layout is an error naming the manual
step. It never imports Django. Generated Python is clean under ruff (lint and
format) and `karni rules --check`, and generated pages parse and stay within
50 lines. `tests/test_make_gate.py` generates every type into a fresh scaffold
and asserts this (plus `tsc` and the frontend's ESLint config when
`KARNI_TEST_NODE_MODULES` points at an installed `frontend/node_modules`).
Then it runs the generated backend for real (makemigrations, migrate, check,
requests through the Django test client).

Quote fields that end in `?` in zsh (`'venue:fk:Venue?'`) and choice values
joined by `|`.

## Execution environment
Commands that run the project resolve, in order: `--docker/--no-docker` flag →
`<project>/.venv` → a running compose service (default `django`, changed with
`--service` or `KARNI_COMPOSE_SERVICE`) → an error naming both remedies.
