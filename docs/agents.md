---
description: "How Karni's agent guidance works: rules as structured data in one module, the context, rules, check and explain commands, the generated adapters and the MCP server."
---

# Karni for AI agents

The CLI is the mechanism, not the file. Karni's agent guidance lives in one
place, `karni.agent.rules` (`packages/karni/karni/agent/rules.py`), as
structured data: every rule has a code, a category, a severity, a rationale,
a fix and the enforcement rule it maps to. Agents read it through the `karni`
command (or the MCP server). The file coding agents look for, `AGENTS.md`, is
generated and short: run `karni context` and `karni rules` first, then follow
what they return.

## CLI surface

| Command | What it returns |
|---|---|
| `karni context` | Live inventory: APPS, MODELS, VIEWSETS, COMPONENTS, HOOKS, PAGES, SITE (the public site's routes), MODULES, CATALOG (a line per module and built-in feature, with whether the project has it: [the module catalog](modules.md#the-module-catalog)), BASES |
| `karni context --summary` / `--app LABEL` / `--model NAME` | One area of a large project at a time: a line per app, one app in full, one model in depth. `--max-tokens N` cuts at whole sections (experimental, [below](#large-projects-one-area-at-a-time)) |
| `karni modules list` / `show NAME` | The module catalog: every module and feature with its options and the questions to ask (experimental) |
| `karni recipes list --match "<request>"` / `show NAME` | The recipes a new app starts from, ranked for a one-line request, and the blank start ([the /new-app flow](#agents-the-new-app-flow), experimental) |
| `karni rules` | Every convention as `CODE summary` (about 620 tokens for Karni's own rules, measured) |
| `karni rules --explain K101` | One rule in full: statement, why, fix, enforcing rule id |
| `karni rules --procedure new-model` | The steps of a standard procedure |
| `karni rules --check FILE [--check FILE…]` | Static violations with code, line, message and fix. Exit 1 if any |
| `karni rules --json` | The raw data (rules, procedures, adapter overrides) |
| `karni rules sync` | Regenerate AGENTS.md (and any deprecated tool-specific file the project still has) |
| `karni rules sync --check` | Exit 1 when any generated file is stale (CI gate) |
| `karni explain E104` | Any code (error `E`/`W`, command `C`, module `PAY`, rule `K`): why Karni objects and the exact fix |
| `karni why events/<id> --as <user>` | Why a row, field or action is refused or missing for a user, computed by the code that enforces it ([debugging](debugging/why.md)). `karni why-empty <resource> --as <user>` covers an empty list |
| `karni explain - < traceback.txt` | The Karni failure in a pasted traceback, test failure or log line: class, cause, `file:line`, fix, docs ([debugging](debugging/explain.md)) |
| `karni queries /api/events/ --as USER` | Every query one endpoint runs. Repeated ones are grouped by the field and relation behind them, with the fix ([debugging](debugging/queries.md)) |
| `karni explain --failure last` | A captured crash as a brief: request, user, failing frame with locals, SQL, next steps ([debugging](debugging/trace-and-replay.md)) |
| `karni trace <request-id>` | One request's story in order: its tasks and retries, email, webhooks, change-log entries |
| `karni replay <request-id> --as USER` | Re-run a captured request against the current code ("was 403, now 200") |
| `karni mcp` | The same surface as MCP tools: `context`, `rules`, `check`, for debugging `why`, `why_empty`, `explain_text`, `queries`, `trace`, `replay`, `explain_failure`, and for the [/new-app flow](#agents-the-new-app-flow) `recipes`, `spec_validate`, `questions`, `answer`, `plan`, `build`, `modules` |

`karni context` and `karni rules` together are enough to start work without
reading files. `karni rules --check` is a fast single-file subset of the real
enforcement. For Python it reads the AST: model-base, viewset-base,
viewset-access (direct `BaseViewSet` subclasses only), access-override,
unpaginated-action, admin-convention, raw-sql, http-client,
redundant-serializer, opt-out reasons. For TS/JS it runs a comment- and
string-aware scan: raw elements, the page cap, deep imports, direct HTTP,
eslint-disable reasons. `karni check` and the `@karni/ui` ESLint preset
stay authoritative, and cross-file rules (duplicates) are not checked per file.
Path allowances use the documented defaults (`*/sql/*`, `*/services/*`,
`src/api/`), matched relative to the project root.

### Large projects: one area at a time

!!! warning "Experimental"
    `karni context --summary`, `--app`, `--model` and `--max-tokens`, and
    `manage.py karni_context`'s flags of the same names, are
    [experimental](stability.md#experimental-names).

On a project with a hundred models or more the inventory caps the models it
lists. Read one area at a time instead:

```sh
karni context --summary                  # one line per app: models, viewsets, pages
karni context --app catalog              # one app in full
karni context --model catalog.Product    # one model in depth (repeatable)
karni context --app catalog --max-tokens 1500
```

`--summary` prints a `SUMMARY` line with the totals, then one `APP` line per
app with its models (the first 20 named), its viewsets and its pages (those
named after one of its models), with their counts:

```text
SUMMARY: 3 apps, 31 models, 29 viewsets. One app: karni context --app <label>. One model: karni context --model <name>.
APP catalog: 12 models (Category Product Supplier ...), 11 viewsets, 6 pages
```

`--app LABEL` (repeatable) prints that app in full: every model with up to
twelve fields, the key types, `RELATIONS` out of the app and `in:` the
relations from other apps into it, the scopes, each viewset with its route
and access, the roles and actions that reach the models, the field
visibility, the declared performance exceptions and the pages. `--model
NAME` (a name or `app_label.Name`, repeatable) prints one model in depth:
where the class is, its key and table, every field in the spec's words
(`str:200`, `fk:Category?`, `decimal:10,2`, `choices(draft,live)`), the
relations that point at it, its viewsets with their search fields, and its
pages. An unknown name is [E470](errors.md#e470) with the names that come
close, and a bare name two apps share is [E471](errors.md#e471).

`--max-tokens N` cuts the output at whole sections (a line with the indented
lines under it) to about N tokens, four characters each. The last line says
what was left out and the command that prints it:

```text
LEFT OUT: VIEWSETS ROLES PERF PAGES BASES (~640 tokens). karni context --app catalog prints them.
```

Without these flags `karni context` prints what it always printed. A project
whose karni predates them says so ([C580](errors.md#c580)).

None of this imports Django or project code. `karni.agent` is stdlib-only.
The CLI finds it, in order: in its own environment (`local`), through the
project's interpreter like `karni context` does (`project`, using `.venv`, else
the running compose service, so the answer comes from the project's karni
version), or
from the copy bundled into karni-cli (`bundled`, what `karni new` uses when
only karni-cli is installed). Force one with
`KARNI_AGENT_SOURCE=local|project|bundled`.

## Error codes

Every error Karni prints starts with a stable code and ends with a link:
`E104: EventViewSet: Owned('organiser') does not lead from Event to the user
model ... See …/errors/#e104`. The message names the class, field or setting
to change. `karni explain E104` (offline, no project needed) adds why Karni
objects and the general fix. System checks (`karni.E101`, …) run on every
`manage.py` command, so a missing `access` or a broken schedule fails on boot,
not on the first request. All codes: [errors.md](errors.md), generated from
the registries.

## Rule codes

Codes are stable. A code is never reused for a different rule.

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
convention that is not machine-checked. `should` is a strong default.
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
# ADAPTERS = {"disable": ["agents-md"]}  # only when the project writes AGENTS.md itself
```

`ADD` entries take `code` (any 1–3 capitals but a bare `K`, plus three
digits) and `rule`, optionally `summary`, `category` (default `project`),
`severity` (`error`/`must`/`should`, default `must`), `rationale`, `fix`.
`OVERRIDE` may change `summary`, `rule`, `rationale`, `fix`, `severity`,
`category` of a Karni rule. Codes and enforcement mappings are fixed.
`DISABLE` hides rules from `karni rules` and from `--check`, but it does not turn
off `karni check` or ESLint (configure those where they live). `ADD += [...]`
works too. Unknown names, codes or fields are errors that name the line.

## AGENTS.md

`karni new` generates it, and `karni rules sync` refreshes it. It is the one
agent file: coding agents read `AGENTS.md` at the repository root. It says to
run `karni context` and `karni rules` first, states the project's kind and
stack, lists the procedures for routine tasks (`new-model`, `new-page`,
`add-module`, `new-module`, `site-from-design` and `new-app`), and tells the
agent that a request starting with `/<name>`, such as `/new-app a booking app
for a yoga studio`, asks for that procedure. `karni rules --procedure <name>`
prints the steps. The registry is
`packages/karni-cli/karni_cli/agent_adapters.toml`.

AGENTS.md is at most 100 lines and carries a
``Generated by `karni rules sync` `` marker. Sync only overwrites a file with
that marker: a hand-written `AGENTS.md` is reported and left alone unless you
pass `--force`, which backs it up under `.karni/backup/` first.
`ADAPTERS = {"disable": ["agents-md"]}` in `karni.rules.py` stops Karni writing
it, for a project that keeps its own.

### Deprecated: the files only one tool reads

Before 0.5.0, `karni new` also wrote one instruction file and one command
folder per tool. They are deprecated and removed in 1.0
([stability](stability.md#agent-guidance)). In a project that has them,
`karni rules sync` keeps them up to date through 0.5, `--check` reports them
when they are stale, and sync prints one warning, `C860`, naming them.
`karni doctor` mentions them once. A deleted one is not written again, and a
hand-written file in one of those places is the project's own.
[Migrating to 0.5](migrations/0.5.md#tool-specific-agent-files-are-deprecated-keep-agentsmd)
lists them and the steps.

### Module guidance

A module ships `AGENTS.fragment.md` ([module contract](modules.md)).
`karni add <x>` reads it through the project's interpreter, records it as
`.karni/modules/<x>.md` (commit it) and re-runs sync. From there it appears
in `karni rules` output (`[module:<x>]`) and in `AGENTS.md` between
`<!-- karni:module:<x> -->` markers. If inline module guidance would push the
file past 100 lines, it lists the modules and points at `karni rules`
instead.

### CI staleness check

```sh
karni rules sync --check
```

Exits 1 and lists every stale file when AGENTS.md (or a deprecated file the
project still has) differs from what the registry, `karni.rules.py` and
`.karni/modules/` produce. The scaffold's `make check` runs it after
`karni check`.

## MCP

```sh
pip install 'karni-cli[mcp]'
karni mcp                 # stdio; --project PATH when not started inside the project
```

Tools: `context()`, `rules(code="", procedure="")`, `check(path)`,
`why(target, user="", action="", method="", params="", as_json=False)` and
`why_empty(resource, user, params="", as_json=False)` ([`karni
why`](debugging/why.md)). Each returns the same text as the CLI.

For debugging (the [development capture](debugging/capture.md)):
`trace(request_id="last", as_json=False)`, `replay(request_id="last",
as_user="", sets=[], drop_redacted=False, commit=False)` and
`explain_failure(failure_id="last")`, which return the text of `karni trace`,
`karni replay` and `karni explain --failure`.

Debugging tools: `explain_text(text)` (`karni explain -` on a pasted
traceback or log line) and `queries(endpoint, as_user="", method="GET",
data="", explain=False)` (`karni queries`). Rules K013 and K014 tell an agent
to call them before reading a traceback or hunting an N+1 by hand.

For the [/new-app flow](#agents-the-new-app-flow) (experimental):
`recipes(match="", name="")`, `spec_validate(path="")`, `questions(spec="",
max=5)`, `answer(id, value, spec="")`, `plan(spec="")`, `build(spec="",
dry_run=False, allow_destructive=False)` and `modules(name="")`. Each returns
JSON that follows a published schema: [the MCP tools](app-spec.md#mcp-tools).

Register it with your tool as a stdio server whose command is `karni` and
whose arguments are `mcp`. Most tools read this shape, in a project-scoped
`.mcp.json` or in the tool's own MCP settings:

```json
{ "mcpServers": { "karni": { "command": "karni", "args": ["mcp"] } } }
```

The server is built on the official MCP Python SDK (`MCPServer` in mcp 2.x,
`FastMCP` in mcp 1.x).

## Agents: the /new-app flow

!!! warning "Experimental"
    The `new-app` procedure, rule K311, `karni recipes`, the recipe format
    and the MCP tools of the flow are
    [experimental](stability.md#experimental-names).

Most apps start as one line: "a booking app for a yoga studio, with online
payments". The agent turns that line into a small spec, `karni.yaml`, and
Karni turns the spec into code with `karni build`, without a language model.
The agent writes by hand only the domain logic that is left.

Describe the app in one line and give it to the agent after `/new-app`.
AGENTS.md tells the agent that this asks for the `new-app` procedure:

```text
/new-app a booking app for a yoga studio, with online payments
```

If your tool does not pass that line on to the agent, the same flow is one
prompt:

```text
Run `karni rules --procedure new-app` and follow every step for: <the app in one line>
```

The steps, as the [procedure](#new-app-build-an-app-from-a-one-line-request-karniyaml-then-karni-build)
gives them:

1. **A recipe, or the blank start.** `karni recipes list --match "<the
   request>"` ranks the [recipes](app-spec.md#recipes) by the words they
   share with the request. The agent starts `karni.yaml` from the closest
   one, or from the blank start (the version and the app's name, nothing
   else) when none fits, and writes in it what the request asks for.
2. **The questions.** `karni plan --questions` lists the few questions for
   the user ([questions](app-spec.md#questions)). The agent asks those and
   only those.
3. **The answers.** `karni spec answer <id> <value>` writes each one into
   `karni.yaml`, keeping its comments and layout.
4. **The plan.** `karni plan` shows what will change, risky changes first.
5. **The build.** `karni build` writes Karni's code, runs the migrations,
   seeds, types, tests and `karni check`. A Karni-owned file edited by hand
   stops it, and the agent asks the user which of the three ways on to take.
6. **The domain logic.** The agent writes only what `karni.yaml` cannot
   express, in the project's own files: methods in `<app>/models.py`,
   actions in `<app>/viewsets.py`, `<app>/seeds.py`, its own pages and
   tests.
7. **Done** when `karni check` and `karni test` pass.

A new project can also start from a recipe with its domain code in place:
`karni new "<Name>" --recipe <name>` writes the recipe's `karni.yaml` and
runs `karni build`, which writes the recipe's own methods, actions, seeders
and tests too ([recipes](recipes/index.md)). The flow then goes on from the
questions, for what the request changes.

Rule K311 says it in AGENTS.md: never hand-write what `karni.yaml` can
express. Change `karni.yaml` and run `karni build` again. `karni new` ends
with the same two lines, and so does the welcome page of a new project.

With the MCP server, the tools `recipes`, `spec_validate`, `questions`,
`answer`, `plan` and `build` do the same as the commands and return JSON
([the MCP tools](app-spec.md#mcp-tools)). The MCP `build` never forces or
adopts a file edited by hand: those stay the user's call.

## Migrating an existing project

Projects scaffolded before 0.2 have hand-written agent files. `karni
upgrade` runs a codemod for them:

1. Module blocks move to `.karni/modules/<x>.md`.
2. Every line you added to Karni's text becomes a `karni.rules.py` `ADD`
   entry, verbatim (one per bullet or paragraph, codes `P001`…).
3. Every line you removed from Karni's text is listed as a `# REVIEW:`
   comment in `karni.rules.py` and printed, because only you know whether
   it meant "disable this rule".
4. Originals are backed up under `.karni/backup/`, then the files are
   generated again (the tool-specific ones are deprecated since 0.5.0).

Files that do not look like Karni's are left untouched and reported.
`karni upgrade --dry-run` shows the diff. This is one entry in Karni's
changelog. See [migrating to 0.2](migrations/0.2.md#agent-guidance-files).

## Plain-language prompts

These prompts do the same as `/new-model`, `/new-page`, `/add-module`,
`/new-module`, `/site-from-design` and `/new-app`, for a tool that does not
pass a line starting with `/` on to the agent. The block below is generated
from the procedure data (a test fails when it is stale).

<!-- karni:procedures:start (generated: `karni rules --prompts-doc`) -->

### `new-model`: Add a domain model the Karni way (model + viewset, nothing else)

Prompt for tools without slash commands (replace the placeholder):

> Run `karni rules --procedure new-model` and follow every step for: `<ModelName> [in <app>] [fields...]`

What `karni rules --procedure` returns:

```text
Add a new domain model: <ModelName> [in <app>] [fields...]

1. Run `karni context` to see existing apps, models and viewsets.
2. `karni make model <Name> <field:type ...> --with viewset --access <who> [--search f1,f2] [--app <app>]` writes the model on `karni.models.BaseModel` and its viewset (`-a` also adds list/detail/form pages). Field types: `karni make model --help`. `--access`: granted (default), public-read (anyone reads, staff write), public-create (a public form that anyone may send and staff read, rate-limited by Karni; `karni make form` writes a whole public form with its tests, email and page tag), owned:<fk to user>, staff, role:<name>, authenticated. Edit the generated `access` for anything richer (`Owned(...) | HasRole(...)`, `Where(...)`). Do NOT write an admin, serializer or router. The auto-router registers it, and the admin, filters and schema are derived.
3. Add `class APIMeta:` / `class AdminMeta:` only for fields that must be hidden, read-only or write-only.
4. `karni make migration && karni migrate && karni types`
5. Verify: `karni context` lists the model and viewset, and GET /api/<plural>/ works for a caller `access` admits and is refused (401/403) or empty for one it does not.

Total new code should be well under 20 lines. If it isn't, stop: you are reimplementing something Karni provides.

Rules that apply: K009, K101, K102, K109, K114, K108, K115, K116, K302, K305, K003
```

### `new-page`: Add a frontend page composing @karni/ui (50 lines or fewer)

Prompt for tools without slash commands (replace the placeholder):

> Run `karni rules --procedure new-page` and follow every step for: `<page purpose> [resource]`

What `karni rules --procedure` returns:

```text
Add a page: <page purpose> [resource]

1. Run `karni context` for available components, hooks, resources and pages.
2. `karni make page <name> --resource <resource> --kind list|detail|form` writes `frontend/src/pages/<name>.tsx` composing @karni/ui and does the rest a person would do by hand: register the route alongside the existing pages (frontend/src/routes.tsx). Without `--resource` it is a bare `<Page>`. Never hand-roll tables, forms or fetching. A page of the public server-rendered site is not an app screen: `karni make view <name> --app <site app>` (K309).
3. Custom behaviour goes through props (`columns`, `fields`, `rowActions`, slots, custom cell/field renderers). Extend, never fork a variant.
4. Keep the file at 50 lines or fewer. Data access only via @karni/ui hooks (`useResourceList`, `useResourceItem`, `useResourceMutations`) and the typed hooks generated by `karni types`.
5. `karni rules --check <the page file>` must report no violations.

Rules that apply: K009, K201, K202, K204, K303, K306, K309
```

### `add-module`: Install an optional Karni module and wire it into settings

Prompt for tools without slash commands (replace the placeholder):

> Run `karni rules --procedure add-module` and follow every step for: `<module> (e.g. payments)`

What `karni rules --procedure` returns:

```text
Install Karni module: <module> (e.g. payments)

1. Run `karni modules show <module>`: what it provides, what it needs and the questions to settle first, each with the setting its answer goes to.
2. A PDF of one row (an invoice, a product sheet) is the `reports` module: declare a Report in `<app>/reports.py` (model, template, get_context), never a hand-written PDF view.
3. A file only the row's readers may download (a contract scan, an ID photo) is the `storage` module: `ProtectedFileField` or `ProtectedImageField` (karni.yaml: `file:protected`), never a hand-written download view, presigned URL or boto3 call.
4. Run `karni add <module>`. It adds the `karni-<module>` dependency to pyproject.toml, wires `karni_<module>` into the INSTALLED_APPS block marked `# karni:apps` in config/settings.py (with any middleware its manifest wires), and (once installed) records the module's agent guidance. It prints the URL include to add, if any.
5. Rebuild/install: `docker compose build` (or `uv pip install -r pyproject.toml` in a host venv), then `make migrate`. Run `karni add <module>` again if it asked you to.
6. Run `karni context`. The module must appear under MODULES, and `karni rules` now includes its guidance.
7. Configure only the settings the module documents. Do not patch its internals.
8. For `ai` (rows read from text, a web page or a PDF by a language model): the provider goes in karni.yaml (`modules: ai: {provider: ...}`), the API key and the model name in .env only (`karni modules show ai` names them), and `karni check` fails until they are set. Use the `test` provider in tests and CI.
9. To take it out again: `karni remove <module>` (it never drops the tables).
10. To create a new reusable module instead: `karni make module <name>` (modules/karni-<name>/, docs/modules.md).

Rules that apply: K009, K307, K308
```

### `new-module`: Create a new local Django app following Karni conventions

Prompt for tools without slash commands (replace the placeholder):

> Run `karni rules --procedure new-module` and follow every step for: `<app_name>`

What `karni rules --procedure` returns:

```text
Create a local app: <app_name>

1. Run `karni context` first to confirm the domain isn't already covered.
2. `karni make app <app_name>` writes `__init__.py`, `apps.py`, `models.py`, `viewsets.py`, `migrations/`, `tests/` and adds the app to the `# karni:apps` block in config/settings.py. No admin.py, serializers.py, urls.py, forms.py: Karni derives all of that.
3. Add models with `karni make model <Name> <field:type ...> --app <app_name> --with viewset --access <who>` (procedure new-model).
4. `karni make migration && karni migrate && karni types`, then `karni context` to verify.
5. Anything reusable across projects belongs in a Karni module: `karni make module <name>`, not in this project. Say so instead of building it.

Rules that apply: K009, K305, K307
```

### `site-from-design`: Build the public site from a designer's pages, with models and real content

Prompt for tools without slash commands (replace the placeholder):

> Run `karni rules --procedure site-from-design` and follow every step for: `<design folder> [site app]`

What `karni rules --procedure` returns:

```text
Build the public site from the design: <design folder> [site app]

1. Run `karni context` to see the kind, the apps, the models and whether a site app exists.
2. `karni design analyze <design folder> --app <site app> --map content/design-map.json` lists the content that repeats (cards, detail pages, galleries, lists of links), the models and relations it proposes as `karni make model` commands, and the decisions the markup cannot settle, and writes a draft content map. Read it first: rename a model or field in its command and in the map together, and delete from both what should stay in a template.
3. `karni import design <design folder> --app <site app> --editable --map content/design-map.json` turns the pages into the site app: `base.html` with the shared header and footer, a template, view and route per page, the files under `static/<site app>/`, `{% ifactive %}` on the menu. Every text, image, menu and contact detail the client sees becomes editable in the admin, except what the map reads into rows: the loops render that from the rows, never from blocks. The report names each `<form>`. Then `karni migrate` and `karni test`: the page test covers every page. Change which structures the map holds later? Import again before you edit the templates.
4. Answer every decision in the map. A hand-picked list or flag: keep the value, remove its `decide` and add the field the decision names to that model's command. One a query derives (every project of this service, the newest three): delete the value from the map and query it in the view.
5. Run the `karni make model` commands in the order printed (models others point at come first), then `karni make migration && karni migrate`. Staff edit the rows in the admin as it is: write no viewset, serializer or admin class for them.
6. `karni design extract <design folder> --map content/design-map.json -o content/site.json` writes the pages' real content and copies the images it names to `content/files/`. Fix what it reports (a missing image, two pages that disagree on a value, a required field without one) in the map or the models, then extract again.
7. `karni load content/site.json --dry-run` shows what changes per model, row by row. Then `karni load content/site.json`, and once more: the second run must say Nothing changed. Commit `content/`. Never fill these tables with `karni seed` (it refuses tables that hold real rows) or with content you type in.
8. Turn the repeated markup into loops. The view reads `Model.objects` (filter what is not published, `select_related`/`prefetch_related` what the template loops over). The template keeps one copy of the item's markup inside `{% for %}` with `{{ row.field }}` where the map reads a value, `{% image row.image width=<its width in the card> alt=row.title %}` for an image (with `eager=forloop.first` in a list at the top of the page, such as a hero slider: the first picture loads first, not lazily) and `{{ row.heading|highlight }}` for highlighted words (`==words==`, the site's one convention: set `KARNI_SITE_HIGHLIGHT` to the markup the analysis names, unless `karni import design --editable` already did. `karni explain <SETTING>` prints any setting's format and default). A model's detail pages become one view and template with a `<slug:slug>` capture, keeping each page's URL (the slug is the page's file name).
9. For those detail pages: `karni make view <model> --app <site app> --path "/<folder>/<slug:slug>/"` writes the view, its template and its route, and turns every `{% ifactive %}` naming the old pages' views into the folder's path (`"/<folder>/*"`). Build the template from one detail page's template (its blocks stay, their keys start with the model's name), read the row with `get_object_or_404(Model.objects, slug=slug)`, delete the old pages' views, routes and templates, and point every link at `{% url '<site app>:<model>' row.slug %}`. Give the model `get_absolute_url()` returning that URL. `{% karni_seo %}` finds the page's row by itself: `object` (or `seo`) in the context when it is a row, else the row in the context whose `get_absolute_url()` is the page's path. The row gives the page its title, description and share image, and wins over the template's own, so the detail template writes no `{% block title %}` or `{% block description %}`. `class Karni: seo = {"title": "name", "description": "intro"}` names the fields when they are not `title`, `description` and `image` (`karni explain karni_seo`). `karni check` (SITE002) and `karni check --seo` (SITE007, a menu item still pointing at an old page) name what is left.
10. For each `<form>` the import named: `karni make form <name> <field:type> ...` with the design's fields (`--notify <SETTING>` for the email that tells staff) writes the model, its viewset, the tests and the email, and prints the `{% karni_form %}` tag that keeps the form's classes, labels and button, with `editable=` so the client edits its texts, and says which design field fills which model field. Put the tag where the `<form>` was, then `karni make migration && karni migrate`. Never write a form view, a form template or a throttle.
11. `{% karni_seo %}` in `base.html` writes each page's title, description, canonical link, share tags and JSON-LD (a detail page's from its row, as above), `{% image %}` serves a card's picture at the card's size, and karni-site answers `/sitemap.xml` and `/robots.txt`: write none of them by hand. Give a model whose rows are not all public `class Karni: sitemap = {"filter": {...}}`, then run `karni check --seo` and fix each SITE010 to SITE018 it reports.
12. `karni test`: give each detail page a real URL in the page test's `PAGES`. The test loads the content first (`load_content("content/site.json")` from `karni.testing`, which reads the path from the project root, in an autouse fixture: the page test the import wrote has it), so every page renders real rows. Then `karni check`. Nobody can sign in to the admin yet: `karni createsuperuser` makes the first account, and the client's own is a user the admin gives the staff role (or the editor role, to change only the content).

Nothing is retyped and nothing is invented: every value comes from the design through extract and load, and a new version of the design is extract and load again.

Rules that apply: K009, K309, K003, K301
```

### `new-app`: Build an app from a one-line request: karni.yaml, then karni build

Prompt for tools without slash commands (replace the placeholder):

> Run `karni rules --procedure new-app` and follow every step for: `<the app in one line>`

What `karni rules --procedure` returns:

```text
Build this app: <the app in one line>

1. `karni recipes list --match "<the request>"` ranks the recipes by the words they share with the request. Start karni.yaml from the closest one that fits (`karni recipes show <name>` prints its spec and what people usually change) or, when none does, from the blank start it prints. Write in it what the request asks for: apps, entities and fields, roles, modules (`karni modules list`), features, pages. `karni spec validate` checks it.
2. `karni plan --questions` lists the questions for the user, most impact first. Ask the user those and only those, with their options and defaults, in one message. Names, labels and the rest are yours to choose.
3. Write each answer with `karni spec answer <id> <value>` (a question the user leaves to you takes its default). Edit karni.yaml by hand only for what no question covers. Run `karni plan --questions` again until none is open.
4. `karni plan` shows what `karni build` will change. Check that it is what the request asks for, and ask the user before any risky (!) change.
5. `karni build` makes the project match karni.yaml: modules, models, viewsets, migrations, seeds, types, tests and `karni check`. It stops at the first failure with its code and what to do next. A Karni-owned file edited by hand stops it (C273): ask the user which of the three ways on to take.
6. Write only the domain logic that is left, where the project owns the code: methods on the subclasses in `<app>/models.py`, custom actions in `<app>/viewsets.py`, demo values in `<app>/seeds.py`, your own pages and tests. Never edit `<app>/karni/` or the `karni:spec` blocks: `karni build` rewrites them.
7. Done when `karni check` and `karni test` pass.

Never hand-write what karni.yaml can express: change karni.yaml and run `karni build` again. The MCP tools recipes, questions, answer, plan and build do the same as these commands.

Rules that apply: K311, K310, K305, K301
```

<!-- karni:procedures:end -->
