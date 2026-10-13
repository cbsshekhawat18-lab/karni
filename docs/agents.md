# Karni for AI agents

The CLI is the mechanism, not the file. Karni's agent guidance lives in one
place, `karni.agent.rules` (`packages/karni/karni/agent/rules.py`), as
structured data: every rule has a code, a category, a severity, a rationale,
a fix and the enforcement rule it maps to. Agents read it through the `karni`
command (or the MCP server). The files tools look for (`AGENTS.md`,
`CLAUDE.md`, `.cursor/rules/karni.mdc`, …) are thin generated adapters that
all say the same thing: run `karni context` and `karni rules` first, then
follow what they return.

## CLI surface

| Command | What it returns |
|---|---|
| `karni context` | Live inventory: APPS, MODELS, VIEWSETS, COMPONENTS, HOOKS, PAGES, MODULES, BASES |
| `karni rules` | Every convention as `CODE summary` (under 400 tokens for Karni's own rules) |
| `karni rules --explain K101` | One rule in full: statement, why, fix, enforcing rule id |
| `karni rules --procedure new-model` | The steps of a standard procedure |
| `karni rules --check FILE [--check FILE…]` | Static violations with code, line, message and fix; exit 1 if any |
| `karni rules --json` | The raw data (rules, procedures, adapter overrides) |
| `karni rules sync` | Regenerate every adapter and slash-command file |
| `karni rules sync --check` | Exit 1 when any generated file is stale (CI gate) |
| `karni explain E104` | Any code (error `E`/`W`, command `C`, module `PAY`, rule `K`): why Karni objects and the exact fix |
| `karni mcp` | The same surface as MCP tools: `context`, `rules`, `check` |

`karni context` and `karni rules` together are enough to start work without
reading files. `karni rules --check` is a fast single-file subset of the real
enforcement (AST for Python: model-base, viewset-base, viewset-access (direct
`BaseViewSet` subclasses only), access-override, unpaginated-action,
admin-convention, raw-sql, http-client, redundant-serializer, opt-out reasons;
a comment- and string-aware scan for TS/JS: raw elements, the page cap, deep
imports, direct HTTP, eslint-disable reasons). `karni check` and the `@karni/ui` ESLint preset
stay authoritative; cross-file rules (duplicates) are not checked per file.
Path allowances use the documented defaults (`*/sql/*`, `*/services/*`,
`src/api/`), matched relative to the project root.

None of this imports Django or project code. `karni.agent` is stdlib-only;
the CLI finds it, in order: in its own environment (`local`), through the
project's interpreter like `karni context` does (`project`: `.venv`, else the
running compose service; this answers with the project's karni version), or
from the copy bundled into karni-cli (`bundled`, what `karni new` uses when
only karni-cli is installed). Force one with
`KARNI_AGENT_SOURCE=local|project|bundled`.

## Error codes

Every error Karni prints starts with a stable code and ends with a link:
`E104: EventViewSet: Owned('organiser') does not lead from Event to the user
model ... See …/errors/#e104`. The message names the class, field or setting
to change; `karni explain E104` (offline, no project needed) adds why Karni
objects and the general fix. System checks (`karni.E101`, …) run on every
`manage.py` command, so a missing `access` or a broken schedule fails on boot,
not on the first request. All codes: [errors.md](errors.md), generated from
the registries.

## Rule codes

Stable; a code is never reused for a different rule.

| Range | Category |
|---|---|
| `K0xx` | workflow: how to work in a Karni project |
| `K1xx` | backend: Python/Django |
| `K2xx` | frontend: React/TypeScript |
| `K3xx` | architecture: what to build at all, and where |
| `P001`… | your project's rules (`karni.rules.py`) |

Severity `error` (shown as `K101!`) means enforced: the rule maps onto an
enforcement id (`model-base`, `viewset-base`, `viewset-access`,
`access-override`, `unpaginated-action`, `query-scaling`,
`admin-convention`, `raw-sql`, `http-client`,
`redundant-serializer`, `duplicate`, `opt-out-reason`,
`karni/no-raw-elements`, `karni/max-page-lines`, `karni/no-deep-imports`,
`karni/no-direct-http`, `jscpd`) and fails the build. `must` is a mandatory
convention that is not machine-checked; `should` is a strong default.
`karni rules --json` lists the mapping.

## Project rules: `karni.rules.py`

An optional file at the project root. It is parsed, never executed: only
literal assignments to these names are allowed.

```python
# karni.rules.py
ADD = [
    {"code": "P001", "rule": "Money is always a Decimal, never a float.",
     "summary": "Money is Decimal, never float.", "severity": "must"},
]
OVERRIDE = {"K007": {"summary": "Commands: just up, just migrate, karni types/check/context."}}
DISABLE = ["K304"]
ADAPTERS = {"disable": ["copilot-prompts"], "paths": {"windsurf": ".devin/rules/karni.md"}}
```

`ADD` entries take `code` (any 1–3 capitals but a bare `K`, plus three
digits) and `rule`, optionally `summary`, `category` (default `project`),
`severity` (`error`/`must`/`should`, default `must`), `rationale`, `fix`.
`OVERRIDE` may change `summary`, `rule`, `rationale`, `fix`, `severity`,
`category` of a Karni rule; codes and enforcement mappings are fixed.
`DISABLE` hides rules from `karni rules` and from `--check`; it does not turn
off `karni check` or ESLint (configure those where they live). `ADD += [...]`
works too. Unknown names, codes or fields are errors that name the line.

## Adapters

`karni new` generates them; `karni rules sync` refreshes them. The registry
is `packages/karni-cli/karni_cli/agent_adapters.toml`: a renamed file is a
config change, not a code change, and each entry records the documentation
it was verified against (2026-10-02).

| Tool | File | Format |
|---|---|---|
| AGENTS.md readers (Codex, Jules, Gemini CLI, Zed, Warp, Devin; also Cursor, Copilot, Windsurf, Cline, Junie) | `AGENTS.md` | Markdown, no frontmatter. Canonical; carries module guidance |
| Claude Code | `CLAUDE.md` | `@AGENTS.md` import (a CLAUDE.md is read instead of AGENTS.md, so it imports it) |
| Cursor | `.cursor/rules/karni.mdc` | frontmatter `description`, `globs`, `alwaysApply: true` |
| Windsurf / Devin Desktop | `.windsurf/rules/karni.md` | frontmatter `trigger: always_on` |
| GitHub Copilot | `.github/copilot-instructions.md` | Markdown, no frontmatter |
| Cline | `.clinerules/karni.md` | Markdown in the `.clinerules/` directory |
| Aider | `CONVENTIONS.md` | Markdown; load with `aider --read CONVENTIONS.md` or `read:` in `.aider.conf.yml` |
| JetBrains Junie | `.junie/AGENTS.md` | Markdown; carries module guidance |

Slash commands for `new-model`, `new-page`, `add-module` and `new-module`
come from the same procedure data:

| Tool | Files |
|---|---|
| Claude Code | `.claude/commands/<name>.md` (`description`, `argument-hint`, `$ARGUMENTS`) |
| Cursor | `.cursor/commands/<name>.md` (plain Markdown) |
| Windsurf | `.windsurf/workflows/<name>.md` (`description`) |
| GitHub Copilot (VS Code) | `.github/prompts/<name>.prompt.md` (`description`, `argument-hint`, `agent: agent`) |

Every generated file is at most 100 lines and carries a
``Generated by `karni rules sync` `` marker. Sync only overwrites files with
that marker: a hand-written file in an adapter's place is reported and left
alone unless you pass `--force`, which backs it up under `.karni/backup/`
first. Generated files that are no longer produced (a disabled adapter, a
moved path) are removed.

Conventions that changed from the names originally planned, each following
the tool's current documentation: Cline reads a `.clinerules/` **directory**
(not a single file), Windsurf's `.windsurfrules` is legacy (rules live in
`.windsurf/rules/`, or `.devin/rules/`), Cursor's `.cursorrules` is no longer
documented (`.cursor/rules/*.mdc`), and Junie's `.junie/guidelines.md` is
legacy and never read while an `AGENTS.md` exists, so `.junie/AGENTS.md` is
generated. Cline workflows are not generated: their documentation page could
not be verified.

### Module guidance

A module ships `AGENTS.fragment.md` ([module contract](modules.md)).
`karni add <x>` reads it through the project's interpreter, records it as
`.karni/modules/<x>.md` (commit it) and re-runs sync. From there it appears
in `karni rules` output (`[module:<x>]`) and in `AGENTS.md` and
`.junie/AGENTS.md` between `<!-- karni:module:<x> -->` markers. If inline
module guidance would push those files past 100 lines, they list the
modules and point at `karni rules` instead.

### CI staleness check

```sh
karni rules sync --check
```

Exits 1 and lists every stale file when an adapter differs from what the
registry, `karni.rules.py` and `.karni/modules/` produce. The scaffold's
`make check` runs it after `karni check`.

## MCP

```sh
pip install 'karni-cli[mcp]'
karni mcp                 # stdio; --project PATH when not started inside the project
```

Tools: `context()`, `rules(code="", procedure="")`, `check(path)`. Each
returns the same text as the CLI.

Claude Code:

```sh
claude mcp add karni -- karni mcp
```

or commit a project-scoped `.mcp.json`:

```json
{ "mcpServers": { "karni": { "command": "karni", "args": ["mcp"] } } }
```

Cursor, `.cursor/mcp.json`:

```json
{ "mcpServers": { "karni": { "command": "karni", "args": ["mcp"] } } }
```

The server is built on the official MCP Python SDK (`MCPServer` in mcp 2.x,
`FastMCP` in mcp 1.x).

## Migrating an existing project

Projects scaffolded before this change have hand-written `AGENTS.md`,
`CLAUDE.md`, `.cursorrules` and `.claude/commands/*.md`. `karni upgrade`
runs a codemod for them:

1. module blocks move to `.karni/modules/<x>.md`;
2. every line you added to Karni's text becomes a `karni.rules.py` `ADD`
   entry, verbatim (one per bullet or paragraph, codes `P001`…);
3. every line you removed from Karni's text is listed as a `# REVIEW:`
   comment in `karni.rules.py` and printed, because only you know whether
   it meant "disable this rule";
4. originals are backed up under `.karni/backup/`, then the adapters are
   generated.

Files that do not look like Karni's are left untouched and reported.
`karni upgrade --dry-run` shows the diff. This is one entry in Karni's
changelog; see [migrating to 0.2](migrations/0.2.md#agent-guidance-files).

## Plain-language prompts

For tools without slash commands, these prompts do the same as `/new-model`,
`/new-page`, `/add-module` and `/new-module`. The block below is generated
from the procedure data (a test fails when it is stale).

<!-- karni:procedures:start (generated: `karni rules --prompts-doc`) -->

### `new-model` — Add a domain model the Karni way (model + viewset, nothing else)

Prompt for tools without slash commands (replace the placeholder):

> Run `karni rules --procedure new-model` and follow every step for: `<ModelName> [in <app>] [fields...]`

What `karni rules --procedure` returns:

```text
Add a new domain model: <ModelName> [in <app>] [fields...]

1. Run `karni context` to see existing apps, models and viewsets.
2. `karni make model <Name> <field:type ...> --with viewset --access <who> [--search f1,f2] [--app <app>]` writes the model on `karni.models.BaseModel` and its viewset (`-a` also adds list/detail/form pages). Field types: `karni make model --help`. `--access`: authenticated (default), public-read, owned:<fk to user>, staff, role:<name>; edit the generated `access` for anything richer (`Owned(...) | HasRole(...)`, `Where(...)`). Do NOT write an admin, serializer or router: the auto-router registers it; admin, filters, schema are derived.
3. Add `class APIMeta:` / `class AdminMeta:` only for fields that must be hidden, read-only or write-only.
4. `karni make migration && karni migrate && karni types`
5. Verify: `karni context` lists the model and viewset; GET /api/<plural>/ works for a caller `access` admits and is refused (401/403) or empty for one it does not.

Total new code should be well under 20 lines. If it isn't, stop — you are reimplementing something Karni provides.

Rules that apply: K009, K101, K102, K109, K108, K302, K305, K003
```

### `new-page` — Add a frontend page composing @karni/ui (50 lines or fewer)

Prompt for tools without slash commands (replace the placeholder):

> Run `karni rules --procedure new-page` and follow every step for: `<page purpose> [resource]`

What `karni rules --procedure` returns:

```text
Add a page: <page purpose> [resource]

1. Run `karni context` for available components, hooks, resources and pages.
2. `karni make page <name> --resource <resource> --kind list|detail|form` writes `frontend/src/pages/<name>.tsx` composing @karni/ui and does the rest a person would do by hand: register the route alongside the existing pages (frontend/src/routes.tsx). Without `--resource` it is a bare `<Page>`. Never hand-roll tables, forms or fetching.
3. Custom behaviour goes through props (`columns`, `fields`, `rowActions`, slots, custom cell/field renderers) — extend, never fork a variant.
4. Keep the file at 50 lines or fewer. Data access only via @karni/ui hooks (`useResourceList`, `useResourceItem`, `useResourceMutations`) and the typed hooks generated by `karni types`.
5. `karni rules --check <the page file>` must report no violations.

Rules that apply: K009, K201, K202, K204, K303, K306
```

### `add-module` — Install an optional Karni module and wire it into settings

Prompt for tools without slash commands (replace the placeholder):

> Run `karni rules --procedure add-module` and follow every step for: `<module> (e.g. payments)`

What `karni rules --procedure` returns:

```text
Install Karni module: <module> (e.g. payments)

1. Run `karni add <module>` — it adds the `karni-<module>` dependency to pyproject.toml, wires `karni_<module>` into the INSTALLED_APPS block marked `# karni:apps` in config/settings.py, and (once installed) records the module's agent guidance.
2. Rebuild/install: `docker compose build` (or `uv pip install -r pyproject.toml` in a host venv), then `make migrate`; run `karni add <module>` again if it asked you to.
3. Run `karni context` — the module must appear under MODULES; `karni rules` now includes its guidance.
4. Configure only settings the module documents; do not patch its internals.
5. To create a new reusable module instead: `karni make module <name>` (modules/karni-<name>/, docs/modules.md).

Rules that apply: K009, K308
```

### `new-module` — Create a new local Django app following Karni conventions

Prompt for tools without slash commands (replace the placeholder):

> Run `karni rules --procedure new-module` and follow every step for: `<app_name>`

What `karni rules --procedure` returns:

```text
Create a local app: <app_name>

1. Run `karni context` first — confirm the domain isn't already covered.
2. `karni make app <app_name>` writes `__init__.py`, `apps.py`, `models.py`, `viewsets.py`, `migrations/`, `tests/` and adds the app to the `# karni:apps` block in config/settings.py. No admin.py, serializers.py, urls.py, forms.py — Karni derives all of that.
3. Add models with `karni make model <Name> <field:type ...> --app <app_name> --with viewset --access <who>` (procedure new-model).
4. `karni make migration && karni migrate && karni types`, then `karni context` to verify.
5. Anything reusable across projects belongs in a Karni module: `karni make module <name>`, not in this project — say so instead of building it.

Rules that apply: K009, K305, K307
```

<!-- karni:procedures:end -->
