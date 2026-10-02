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
- `karni types` — dump the OpenAPI schema (`manage.py spectacular`), generate
  `types.ts` (openapi-typescript, project-pinned binary preferred, else
  `npx openapi-typescript@^7`) and typed hooks (`hooks.ts`) over @karni/ui.
- `karni context` — compact machine-readable inventory (< 200 tokens for a
  typical project): MODELS/VIEWSETS from `manage.py karni_context`,
  COMPONENTS/HOOKS from @karni/ui's build-generated `dist/manifest.json`
  (omitted when absent — run `npm i @karni/ui` in `frontend/` on the host to
  enable them; `--manifest PATH` overrides). Nothing is hand-maintained.
- `karni check` — Django system checks plus `karni.checks` entry-point hooks
  (the architecture-test extension surface).
- `karni upgrade [--list] [--dry-run]` — mechanical migrations between Karni
  versions; the registry is empty in v0.1.

## Execution environment
Commands that run the project resolve, in order: `--docker/--no-docker` flag →
`<project>/.venv` → a running compose service (default `django`; change with
`--service` or `KARNI_COMPOSE_SERVICE`) → an error naming both remedies.
