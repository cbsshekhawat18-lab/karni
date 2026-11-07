---
description: "Every Karni feature, grouped by what you need, each with a link to its page, and the status of each capability, generated from the source."
---

# Features

Every feature Karni ships, grouped by what you need, with a link to the page
that explains it. The [status lists](#status-of-every-capability), the
[modules](#every-module), the [commands](#commands) and the
[make targets](#make-targets) at the end are generated from the source by
`scripts/gen_reference.py`, and CI fails when this page misses a page of the
Reference or Debugging sections.

## Start fast

- **[Quickstart](quickstart.md)**: from an empty folder to a running app with demo data, run verbatim by CI.
- **[Recipes](recipes/index.md)**: six ready apps built by `karni new --recipe`: an [online shop](recipes/shop.md), [booking](recipes/booking.md), a [CRM](recipes/crm.md), [online courses](recipes/lms.md), a [marketplace](recipes/marketplace.md) and a [data portal](recipes/data-portal.md).
- **[The app spec, `karni.yaml`](app-spec.md)**: the app in one small file, with `karni spec validate`, `karni plan`, its questions and `karni build`.
- **[The `karni` command](cli.md)**: every command and option, from `karni new` to `karni upgrade`.
- **[Settings](settings.md)**: one `karni_settings(globals())` call, driven by the environment and validated at startup.
- **[Demo data](seeding.md)**: `karni seed` fills every table with realistic, connected rows and prints a demo login.
- **[Real content](content-loading.md)**: `karni load` reads a JSON or YAML file by natural key, in one transaction.
- **[A public website](public-site.md)**: server-rendered pages at `/`, every text and image editable in the admin.
- **[From a design to content](design-content.md)**: a designer's static pages become models and real rows.
- **[Tutorial: EventHub](tutorial.md)** and **[adding an entity end to end](adding-an-entity.md)**: a whole app, step by step.

## Data and access

- **[Models](models.md)**: `BaseModel` with a UUID key, timestamps, soft delete and audit fields, integer keys, external tables and SQL views, [tree models](models.md#tree-models) and [taxonomies](models.md#taxonomies).
- **[Typed fields](fields.md)**: money, percent, quantity, phone, country, currency, markdown and more, with rules the database enforces.
- **[Lifecycle and capacity](lifecycle-and-capacity.md)**: declared states and transitions, capacity that never oversells, no-overlap constraints.
- **[The API](api.md)**: `BaseViewSet` with a required `access` rule, generated serializers, filters, search, `?expand=`, query budgets and the OpenAPI schema.
- **[Permissions at the queryset](concepts/queryset-permissions.md)**: one row filter for list, detail, relations and expansion, so a row outside your scope is a 404.
- **[Accounts](accounts.md)**: email sign-in, the auth endpoints, roles as data, per-user grants, two-factor and social login.
- **[Change history](change-history.md)**: who changed which field from what to what, in the admin, the API and the UI.
- **[Events and listeners](events.md)**: react to model changes from `listeners.py`, inline or queued to Celery.
- **[Scheduling](scheduling.md)**: periodic and background work in `schedules.py`, run by Celery beat and workers.

## Large apps

- **[Aggregations](aggregations.md)**: counts, sums and averages at `<resource>/aggregate/` by category, relation or date.
- **[Search across models](global-search.md)**: `GET /api/search/` with access applied per model, and a command palette.
- **[Navigation from data](navigation.md)**: each user's menu, opened by the same roles and grants as the API.
- **[Import and export](import-export.md)**: CSV and XLSX from any list, and uploads with a mandatory dry run.
- **[Large projects](large-projects.md)**: `karni context` one area at a time, a cached `karni check`, volume seeding and query plans for 100 models or more.

## Admin

- **[The admin](admin.md)**: every model registered with derived columns, filters, search, pagination and bulk edit, with no `admin.py`.
- **[Row scope and field visibility](admin.md#row-scope)**: the admin opens rows and fields by the same rules as the API.
- **[Saved charts](charts.md)**: charts defined and previewed in the admin, served under each resource's access (a module).

## UI

- **[@karni/ui](ui.md)**: `ResourceTable`, `ResourceForm` and `ResourceDetail` from the OpenAPI schema, the app shell, sign-in pages, page blocks and hooks.
- **[Theming](theming.md)**: `karni ui detect` maps your design system's theme onto Karni's tokens and primitives.

## Modules

- **[The module contract](modules.md)**: one command to add a module, one to remove it, and the catalog every module describes itself in.
- **[PDF reports](reports.md)**, **[AI extraction](ai-extraction.md)**, **[protected files](storage.md)** and the [other modules](#every-module): each a separate package for anything with its own service or a real memory cost.

## Coding agents

- **[Karni for coding agents](agents.md)**: AGENTS.md from one rule set, `karni context`, `karni rules`, the procedures and the MCP server.
- **[The /new-app flow](agents.md#agents-the-new-app-flow)**: from a one-line request to a running app, through `karni.yaml` and `karni build`.
- **[Building with an agent](guide/with-ai.md)** and **[without one](guide/without-ai.md)**: the same project, both ways.
- **[Enforcement](enforcement.md)**: `karni check` and the ESLint preset fail the build when code rebuilds what Karni ships, with an inline opt-out and a reason ([why](concepts/enforcement-layer.md)).
- **[Error codes](errors.md)**: every code with its cause and fix, offline through `karni explain <code>`.
- **[Token benchmark](benchmarks/tokens.md)**: three apps built by a coding agent with and without Karni.

## Debugging

- **[Request ids and capture](debugging/capture.md)**: one id across requests, tasks, email and webhooks.
- **[Trace, replay and failure briefs](debugging/trace-and-replay.md)**: `karni trace`, `karni replay` and `karni explain --failure`.
- **[Explain a traceback](debugging/explain.md)**: `karni explain` names the failure in a pasted traceback, with the fix.
- **[Find an N+1](debugging/queries.md)**: `karni queries` reports every SQL query of one endpoint and the fix.
- **[Why is it missing?](debugging/why.md)**: `karni why` says why a row, field or action is refused for a user.
- **[Measured: three seeded bugs](debugging/measured.md)**: the debugging commands tried on real bugs.

## Production

- **[Deploying to a server](deploy.md)**: the production Docker Compose stack with Caddy and automatic TLS, `karni check --deploy`, backups, restore and health checks.
- **[Security](security.md)**: safe defaults, the security headers and the deploy checks.
- **[Testing](testing.md)**: `assert_crud`, `assert_isolated` and `assert_pages`, query budgets and the architecture rules.
- **[Stability promise](stability.md)**: what is public API, the deprecation cycle, and `karni upgrade` with its codemods.
- **[The reference](REFERENCE.md)**: every command, base class, setting, component, hook, module and error code, generated from the source.

## Status of every capability

`stable`: public under the [stability promise](stability.md) and used by a
reference application. `experimental`: public and covered by Karni's own
tests, not yet used by a reference application. `planned`: documented as
coming, not in the code. Each capability's evidence is in the
[reference](REFERENCE.md#capabilities-and-status).

### Models

<!-- generated:models -->
- `stable` `BaseModel`: UUID key, created and updated timestamps, soft delete, `created_by` and `updated_by`
- `experimental` `BigIntBaseModel`: the same base on a 64-bit integer key, chosen per model (`karni make model --pk bigint`, `KARNI_PK`), with legacy ids in imports and `karni load`, and `karni.W530` for a public resource. Experimental tier
- `stable` Realistic, connected seed data (`karni seed`, `<app>/seeds.py`)
- `experimental` Real content from a JSON or YAML file, created or updated by natural key (`karni load`)
- `experimental` Models and real rows from a designer's pages: the repeated content, its fields and relations (`karni design analyze`, `karni design extract`)
- `stable` Model events and listeners, optionally queued to Celery (`@on_updated`)
- `stable` Field-level change history (`class Karni: audit = True`)
- `experimental` Scheduled tasks (`<app>/schedules.py`, `karni schedule`)
- `experimental` External tables, SQL views and a second database as models Karni reads (`class Karni: external`, `writable`, `database`, `karni make model --external`). Experimental tier
- `experimental` Tree models: `TreeModel` and `OrderedTreeModel` with cycle-safe walks (`roots`, `children`, `ancestors`, `descendants`, `subtree_ids`), `move_to()` and `delete_branch()`, and the tree changelist in the admin. Experimental tier
- `experimental` Taxonomy tagging: one declaration tags a model to tree models (`class Karni: taxonomies`), a generated or adopted many-to-many per key, import and export columns by natural key, and the `tree:<key>` scope. Experimental tier
- `planned` A tenant scope on every model (the `karni-tenancy` module)

Base classes: `AuditedModel`, `BaseModel`, `BigIntBaseModel`, `GuardedModel`, `IntegerKeyModel`, `OrderedTreeModel`, `SoftDeleteModel`, `TimestampedModel`, `TreeModel`, `UUIDModel`.
<!-- /generated:models -->

### API

<!-- generated:api -->
- `stable` `BaseViewSet`: CRUD, filters, search, ordering, pagination, `?expand=` and the OpenAPI document, with no serializer
- `stable` `access` declarations (`Public`, `Owned`, `HasRole`, `Where`, `Granted`) compiled into both the request gate and the row filter
- `stable` Query budgets: a list endpoint that runs more queries than declared fails its test
- `stable` CSV and XLSX export of any list (`/export/?format=`)
- `stable` Import from CSV or XLSX with a mandatory preview (`/import/`)
- `stable` Response caching per viewset (`Cache`, `Uncached`, `KARNI_API_CACHE`): entries shared only by callers with the same access, invalidated on every write, `X-Cache`
- `experimental` Rows of any resource read from text, a web page or a PDF by a language model, always through the import preview (`karni add ai`, `POST /api/ai/extract/`, usage, costs and budgets). Experimental tier
- `experimental` Sign-in with a Google, Microsoft or Apple ID token in JWT and session mode (`social/<provider>/`, `KARNI_SOCIAL_TOKEN_PROVIDERS`). Experimental tier
- `experimental` Sign-in with a one-time code sent by email, in JWT and session mode (`otp/send/`, `otp/verify/`, `KARNI_EMAIL_OTP`). Experimental tier
- `experimental` A versioned terms acceptance gate: 403 `E245` under `/api/` until a signed-in user accepts the current version (`terms/`, `terms/accept/`, `KARNI_TERMS`). Experimental tier
- `experimental` Tree endpoints on a tree model's viewset (`tree/`, `children/`, `ancestors/`, `move/`, `?parent=`, `?descendants_of=`, `DELETE ?branch=true`) and `x-karni-tree` in the OpenAPI document. Experimental tier
- `experimental` Taxonomy filters and counts: `?<key>=` and `?<key>_descendants=` on the list, `facets/` (rows per node under the list's filters and access, rolled up on request) and a tree node's `tagged/` per tagging model. Experimental tier
- `experimental` Search across models: one ranked `GET /api/search/` over every model that declares `class Karni: search`, each under its own list access, one query per model, with the trigram indexes in its migrations (`karni.W590`). Experimental tier
- `experimental` PDF reports of a row (the `reports` module): a template rendered in the background with WeasyPrint, cached by template and data, served only to users who may retrieve the row (`/api/reports/<report>/<id>/`, `ReportButton`). Experimental tier
- `experimental` Protected files (the `storage` module): kept in a private S3-compatible bucket or on disk, downloaded only through the row's own viewset by a signed URL, with direct uploads and thumbnails (`ProtectedFileField`, `<resource>/<id>/files/<field>/`). Experimental tier
- `stable` TypeScript types and typed hooks from the OpenAPI document (`karni types`)
- `experimental` Grouped counts and sums under the list's filters and access: `GET <resource>/aggregate/` from `class Karni: aggregate`, with date buckets, top N and Other, a second dimension and numbers stored as text (`TextNumber`). Experimental tier

Declarations: `Access`, `Authenticated`, `Budget`, `Cache`, `Can`, `Granted`, `HasRole`, `Owned`, `Public`, `Scaling`, `Throttle`, `Uncached`, `Unpaginated`, `Unscoped`, `Where`.
<!-- /generated:api -->

### Admin

<!-- generated:admin -->
- `stable` Every model registered with derived columns, filters and search, with no `admin.py`
- `experimental` Row scope from the roles' grants: a staff user sees and edits only the rows a grant allows
- `experimental` Field visibility, change history and the import and export screens
- `experimental` A permission matrix of every role against every model and action
<!-- /generated:admin -->

### UI components and hooks

<!-- generated:ui -->
- `stable` `ResourceTable`, `ResourceForm` and `ResourceDetail` driven by the OpenAPI schema
- `stable` Sign-in, session restore and role checks (`AuthProvider`, `LoginForm`, `usePermission`)
- `stable` Data hooks with shared caching (`useResourceList`, `useResourceItem`)
- `stable` Import screen with column mapping and preview (`ResourceImport`)
- `stable` Page building blocks: `Page`, `Layout`, `Stat`, `Modal`, `Toaster`, `EmptyState`
- `experimental` `ChangeHistory`, `DataChart` and `FileUpload`
- `experimental` `useAggregate` and `DataChart`'s `aggregate` and `stacked`: a resource's aggregate, read directly. Experimental tier
- `experimental` `SocialButton` and `useSocialLogin`: sign-in with an ID token from the provider's own SDK. Experimental tier
- `experimental` `OtpLoginForm` and `useOtpLogin`: sign-in with a code sent by email, also as `LoginForm`'s `codeSignIn` switch. Experimental tier
- `experimental` `GlobalSearch` and `useGlobalSearch`: a Cmd or Ctrl+K command palette over search across models, grouped per resource, each hit linking to its ResourceDetail page (`<Layout search>`). Experimental tier
- `experimental` `TermsGate` and `useAuth()`'s `termsRequired` and `acceptTerms`: the app renders once the user accepts the current terms. Experimental tier
- `experimental` `TreeView`, `TreeSelect` (used by `ResourceForm` for a relation to a tree) and `TreeBreadcrumb` (on `ResourceDetail` of a tree), with `useResourceTree`. Experimental tier
- `experimental` `Layout`'s server menu (`navSource="server"`, `useNavigation`): collapsible groups, icons by name and the current page marked. Experimental tier
- `experimental` `FacetPanel` and `ResourceTable`'s `facets`: rows per node of a taxonomy, and choosing nodes filters the table, with `useResourceFacets`. Experimental tier
- `experimental` `karni ui detect`: the project's shadcn/ui, Tailwind, Material UI, Chakra UI or Mantine theme, or any stylesheet (`--css`), as Karni's tokens, and shadcn/ui components as Karni's primitives
- `experimental` `Dashboard` (the staff app's home page from `Karni.dashboard`) and `ResourceDetail`'s buttons for a `StateField`'s transitions
- `experimental` Page blocks beyond CRUD: `DashboardGrid`, `ChartCard`, `DataTable` (computed rows: sorting, a sticky header and first column, CSV and XLSX export, only the rows in view rendered), `ComparisonTable`, `Accordion`, `MarkdownView` (sanitized, loaded on first use) and `useResourceCounts`. Experimental tier
- `experimental` `ResourceDetail`'s related tabs (`related`): a table per reverse relation, from the `x-karni-related` extension of the OpenAPI schema. Experimental tier
- `experimental` Wide models: `MarkdownField` (edited with a preview, shown sanitized), `class Karni: field_groups` (form and detail sections or tabs, admin fieldsets) and `column_sets` (table presets kept per user), with `karni.E550` to `E553`. Experimental tier

74 components and 29 hooks, among them `ResourceTable`, `ResourceForm`, `ResourceDetail`, `ResourceSelect`, `ResourceImport`, `AuthProvider`, `AuthGuard`, `LoginForm`, `Page`, `Layout`. The hooks are `useDelayedFlag`, `useOnlineStatus`, `useTheme`, `useKarniPrimitives`, `useUnsavedChangesGuard`, `useResourceTree`, `useResourceChildren`, `useResourceAncestors`, `useResourceAccessForest`, `useTreeMutations`, `useResourceFacets`, `useChangeHistory`, `useImportDescribe`, `useImportJob`, `useImportActions`, `useResourceList`, `useResourceItem`, `useResourceMutations`, `useResourceCounts`, `useAggregate`, `useGlobalSearch`, `useKarniClient`, `useSchema`, `useAuth`, `usePermission`, `useSocialLogin`, `useOtpLogin`, `useNavigation`, `useToast`.
<!-- /generated:ui -->

### Permissions

<!-- generated:permissions -->
- `stable` One `access` declaration per viewset: 404 outside the read scope, 403 for read-but-not-write
- `stable` Roles as data (`KARNI_ROLES`) with the `all` and `own` scopes
- `experimental` The `related:<key>` scope (`class Karni: scope_paths`) and `custom:` scopes
- `stable` Membership through a path: `owner_field = "workspace__members"`
- `stable` Scope paths that do not resolve fail `karni check` (`E214`) instead of answering 500
- `experimental` Per-user grants next to the role grants: a pattern and a scope for one user, with targets and an expiry, in the admin and an API (`UserGrant`, `KARNI_USER_GRANTS`). Experimental tier
- `experimental` The tree scope: a grant on a node of a tree reaches every row under it (`tree:<path>` in `KARNI_ROLES` and user grants, one subtree subquery, the `access/` forest, `TreeView`'s `access`). Experimental tier
- `experimental` Navigation from data: each user's menu from `KARNI_NAVIGATION` or a `NavItem` tree edited in the admin, opened by the same role and per-user grants as the API (`GET /api/navigation/`). Experimental tier
- `experimental` Field visibility per role (`class Karni: field_roles`)
- `experimental` Row scope in the admin, from the same grants as the API
- `stable` Change history: who changed which field, when, from what to what
- `experimental` Sensitive fields recorded in the history without their values
- `experimental` Maker-checker approvals and safe impersonation (the `approvals` and `impersonation` modules)
- `planned` Tenancy: a tenant scope applied to every model
<!-- /generated:permissions -->

### Agent integration

<!-- generated:agents -->
- `stable` `karni context`, `karni rules` and `karni check` in the project workflow
- `stable` AGENTS.md, the one agent file, generated from the rule set (`karni rules sync`)
- `stable` Procedures for the routine tasks (`new-model`, `new-page`, …), listed in AGENTS.md: `karni rules --procedure <name>`, or `/<name>` in a request
- `experimental` `karni explain <code>`: why an error happens and the fix, offline
- `experimental` The app spec, `karni.yaml`, with a published JSON Schema: `karni spec validate` (every problem with its code and line), `karni spec export` (the spec of an existing project) and `karni plan` (what `karni build` would change, risky changes with their row counts). Experimental tier
- `experimental` Clarifying questions: `karni plan --questions` lists the few gaps of `karni.yaml` worth asking the user (owners, access, the sign-up role, the kind, each module's and feature's asks), chosen by fixed rules, and `karni spec answer` writes an answer keeping the file's comments. Experimental tier
- `experimental` `karni build`: the spec applied in one command, idempotently. Karni's code in files of its own (`<app>/karni/`), the project's created once and never rewritten, a hand edit found by its sha256 (`.karni/build.json`), then migrations, seed, types, tests and `karni check`. Experimental tier
- `experimental` Spec pages beyond CRUD: a detail page's related tabs and dashboard pages of charts, in `karni plan`, `karni build`, `karni spec export` and `karni make page`. Experimental tier
- `experimental` The module catalog: a manifest per module and built-in feature, `karni modules list` and `show`, a `CATALOG:` line per entry in `karni context`, `karni add` wiring from the manifest and `karni remove`, which never drops data. Experimental tier
- `experimental` The `/new-app` flow, from a one-line request to a running app: recipes (`karni recipes list --match`, `show`, the `karni.recipes` entry points, the blank start), the `new-app` procedure and rule K311 in AGENTS.md, and the MCP tools `recipes`, `spec_validate`, `questions`, `answer`, `plan`, `build` and `modules`, each returning JSON with a published schema. Experimental tier
- `experimental` Six recipes, `shop`, `booking`, `crm`, `lms`, `marketplace` and `data-portal`, and `karni new "<Name>" --recipe <name>`: the recipe's karni.yaml, then `karni build`, which writes the recipe's domain code, seeds and tests over its own stubs, never over the project's code, and runs the tests and `karni check`. Each is built from scratch in CI. Experimental tier
- `experimental` `karni why` / `karni why-empty`: why a row, field or action is refused or missing for a user, from the code that decides it
- `experimental` MCP server exposing `context`, `rules`, `check`, `why` and `why_empty` as tools
- `experimental` Large projects, one area at a time: `karni context --summary`, `--app`, `--model` and `--max-tokens`, and a `karni check` that skips unchanged files (a cache per check and file, `--changed [REF]` for the files git reports). Experimental tier

Procedures: `/new-model`, `/new-page`, `/add-module`, `/new-module`, `/site-from-design`, `/new-app`.
<!-- /generated:agents -->

### Testing

<!-- generated:testing -->
- `stable` `assert_crud` and `assert_isolated`: the whole API surface and owner isolation in two calls
- `stable` Generated tests from `karni make model … --with test`
- `stable` OpenAPI snapshot test (`assert_schema_snapshot`)
- `stable` Clients per role (`client_as`)
- `experimental` `query_budget` and `user_with_roles` helpers
- `experimental` Performance at volume: `karni seed --volume` (bulk rows that keep their relations), scaling row counts and a time budget per viewset (`Scaling`), `karni queries --explain` with the index a sequential scan wants (PostgreSQL), and a CI benchmark on 100 models. Experimental tier
- `experimental` `assert_pages`: a public site's pages, their title, description, alt text and links, in one call
- `stable` Architecture rules that fail the build (`karni check`, the ESLint preset)

Helpers: `APITestCase`, `assert_admin_row_hidden`, `assert_crud`, `assert_isolated`, `assert_module_manifest`, `assert_pages`, `assert_row_hidden`, `assert_schema_snapshot`, `client_as`, `create_external_tables`, `load_content`, `query_budget`, `user_with_roles`.
<!-- /generated:testing -->

## Every module

Install a module, then `karni add <name>` wires it into settings, the URLs and
the agent files ([the module contract](modules.md)).

<!-- generated:modules -->
- `experimental` `karni add ai`: Rows for any resource read from text, a web page or a PDF by a language model, always through the import preview
- `experimental` `karni add approvals`: A second person approves high-value changes before they are written, with a queue, an API and an audit trail
- `experimental` `karni add charts`: Charts defined and previewed in the admin, served through each resource's aggregate action under its access
- `experimental` `karni add impersonation`: Safe 'log in as user' for Karni support staff: an explicit permission, no privilege escalation, a banner, a time limit, both identities in the audit trail
- `stable` `karni add payments`: Hosted checkout, refunds and signature-verified webhooks for Stripe and Razorpay, with a test provider for CI
- `experimental` `karni add reports`: A row printed to PDF from an HTML template in the background, cached by template and data, served only to users who may see the row
- `experimental` `karni add site`: Every text, image and menu editable in the admin, public forms, redirects, and error pages that cannot fail
- `experimental` `karni add storage`: Files a row owns, in S3 or an S3-compatible service, served only to whoever may read that row, with direct uploads and thumbnails
- `planned` `karni-tenancy`
<!-- /generated:modules -->

## Commands

Each command links to its entry in the [reference](REFERENCE.md#commands).

<!-- generated:commands -->
| Command | What it does |
|---|---|
| [`karni new`](REFERENCE.md#karni-new) | Create a project: a public website, an app, or both |
| [`karni add`](REFERENCE.md#karni-add) | Install an optional module and wire it into settings |
| [`karni remove`](REFERENCE.md#karni-remove) | Take a module out again: what karni add wired, never its data |
| [`karni modules`](REFERENCE.md#karni-modules) | The module catalog (experimental): every module and built-in feature, added or not, with what it provides and the questions to ask (list, show): [list](REFERENCE.md#karni-modules-list), [show](REFERENCE.md#karni-modules-show) |
| [`karni upgrade`](REFERENCE.md#karni-upgrade) | Upgrade across Karni versions: codemods, diff, manual-change report |
| [`karni doctor`](REFERENCE.md#karni-doctor) | Report the environment: project, interpreter, Node, adapters, history |
| [`karni config`](REFERENCE.md#karni-config) | Read and write Karni settings in the project's .karni/config.toml (committed) or, with --global, in ~/.config/karni/config.toml: [get](REFERENCE.md#karni-config-get), [set](REFERENCE.md#karni-config-set), [list](REFERENCE.md#karni-config-list) |
| [`karni ui`](REFERENCE.md#karni-ui) | Fit Karni's components to the project's design system: [detect](REFERENCE.md#karni-ui-detect) |
| [`karni context`](REFERENCE.md#karni-context) | Print a compact machine-readable project inventory |
| [`karni rules`](REFERENCE.md#karni-rules) | Karni's conventions for humans and AI agents (no Django needed): [sync](REFERENCE.md#karni-rules-sync) |
| [`karni check`](REFERENCE.md#karni-check) | Run architecture and system checks |
| [`karni suggest`](REFERENCE.md#karni-suggest) | What Karni could do that the project does by hand, with the fix of each |
| [`karni explain`](REFERENCE.md#karni-explain) | Explain an error code (E104, C101, PAY004, K106), or a pasted traceback or log line (karni explain -): class, cause, where, fix |
| [`karni types`](REFERENCE.md#karni-types) | Generate TS types and typed hooks from the backend OpenAPI |
| [`karni mcp`](REFERENCE.md#karni-mcp) | Serve context, rules, check, the debugging tools and the app-builder flow (recipes, questions, answer, plan, build) as MCP tools (needs karni-cli\[mcp]) |
| [`karni queries`](REFERENCE.md#karni-queries) | Run one endpoint in-process as a user and report its queries |
| [`karni serve`](REFERENCE.md#karni-serve) | Start the dev stack |
| [`karni migrate`](REFERENCE.md#karni-migrate) | Apply migrations |
| [`karni test`](REFERENCE.md#karni-test) | Run the test suite |
| [`karni shell`](REFERENCE.md#karni-shell) | Open a Django shell |
| [`karni routes`](REFERENCE.md#karni-routes) | List every URL with its methods, name, view, model and access |
| [`karni schema`](REFERENCE.md#karni-schema) | Show every column, constraint and index, and the declaration behind each |
| [`karni worker`](REFERENCE.md#karni-worker) | Run a Celery worker |
| [`karni beat`](REFERENCE.md#karni-beat) | Run Celery beat |
| [`karni schedule`](REFERENCE.md#karni-schedule) | List and run the Celery beat schedules: [list](REFERENCE.md#karni-schedule-list), [run](REFERENCE.md#karni-schedule-run) |
| [`karni seed`](REFERENCE.md#karni-seed) | Fill every model with realistic demo data |
| [`karni load`](REFERENCE.md#karni-load) | Load real content from a JSON or YAML file |
| [`karni sync-roles`](REFERENCE.md#karni-sync-roles) | Create or update the roles KARNI_ROLES declares |
| [`karni createsuperuser`](REFERENCE.md#karni-createsuperuser) | Create an admin user |
| [`karni manage`](REFERENCE.md#karni-manage) | Run any management command |
| [`karni why`](REFERENCE.md#karni-why) | Explain an access decision: why a row, field or action is refused or missing |
| [`karni why-empty`](REFERENCE.md#karni-why-empty) | Explain an empty list: which step removes the rows, and the fix |
| [`karni make`](REFERENCE.md#karni-make) | Generate project code: apps, models, viewsets, tasks, schedules, listeners, pages: [app](REFERENCE.md#karni-make-app), [model](REFERENCE.md#karni-make-model), [viewset](REFERENCE.md#karni-make-viewset), [serializer](REFERENCE.md#karni-make-serializer), [migration](REFERENCE.md#karni-make-migration), [test](REFERENCE.md#karni-make-test), [factory](REFERENCE.md#karni-make-factory), [seeder](REFERENCE.md#karni-make-seeder), [task](REFERENCE.md#karni-make-task), [schedule](REFERENCE.md#karni-make-schedule), [event](REFERENCE.md#karni-make-event), [listener](REFERENCE.md#karni-make-listener), [command](REFERENCE.md#karni-make-command), [service](REFERENCE.md#karni-make-service), [middleware](REFERENCE.md#karni-make-middleware), [page](REFERENCE.md#karni-make-page), [component](REFERENCE.md#karni-make-component), [site](REFERENCE.md#karni-make-site), [view](REFERENCE.md#karni-make-view), [deploy](REFERENCE.md#karni-make-deploy), [form](REFERENCE.md#karni-make-form), [module](REFERENCE.md#karni-make-module) |
| [`karni import`](REFERENCE.md#karni-import) | Import a designer's files into the project: [design](REFERENCE.md#karni-import-design) |
| [`karni design`](REFERENCE.md#karni-design) | Read a designer's pages: the models their content needs, and the content itself: [analyze](REFERENCE.md#karni-design-analyze), [extract](REFERENCE.md#karni-design-extract) |
| [`karni spec`](REFERENCE.md#karni-spec) | The app spec, karni.yaml (experimental): check it (validate), write it from an existing project (export), or answer a question of karni plan --questions (answer): [validate](REFERENCE.md#karni-spec-validate), [export](REFERENCE.md#karni-spec-export), [answer](REFERENCE.md#karni-spec-answer) |
| [`karni plan`](REFERENCE.md#karni-plan) | Compare karni.yaml with the project: what karni build would change |
| [`karni build`](REFERENCE.md#karni-build) | Make the project match karni.yaml, without touching hand-written code |
| [`karni trace`](REFERENCE.md#karni-trace) | Follow a captured request: its tasks, retries, email, webhooks, audit |
| [`karni replay`](REFERENCE.md#karni-replay) | Re-run a captured request against the current code, as any user |
| [`karni recipes`](REFERENCE.md#karni-recipes) | Recipes (experimental): ready-made karni.yaml files a new app starts from, matched to a one-line request (list, show): [list](REFERENCE.md#karni-recipes-list), [show](REFERENCE.md#karni-recipes-show) |
<!-- /generated:commands -->

## Make targets

The Makefile of every new project:

<!-- generated:make-targets -->
```sh
make up         # karni serve -d
make down       # docker compose down
make serve      # karni serve
make migrate    # karni make migration; karni migrate
make types      # karni types
make check      # karni check; karni rules sync --check
make rules      # karni rules
make agents     # karni rules sync
make context    # karni context
make test       # karni test
make shell      # karni shell
make routes     # karni routes
make schedules  # karni schedule list
make superuser  # karni createsuperuser
make logs       # docker compose logs -f django worker beat
```
<!-- /generated:make-targets -->
