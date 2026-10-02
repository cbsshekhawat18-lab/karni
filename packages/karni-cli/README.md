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

## Execution environment
Commands that run the project resolve, in order: `--docker/--no-docker` flag →
`<project>/.venv` → a running compose service (default `django`; change with
`--service` or `KARNI_COMPOSE_SERVICE`) → an error naming both remedies.
