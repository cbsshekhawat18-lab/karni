# Changelog

Every package in this repository (`karni`, `karni-cli`, `karni-payments`,
`@karni/ui`, `@karni/payments-ui`) is released at one version, in lockstep.
See [docs/releasing.md](docs/releasing.md).

Breaking changes and deprecations are recorded in machine-readable form in
`packages/karni/karni/changelog/<version>.toml` and explained in
`docs/migrations/<version>.md`. The TOML file is what `karni upgrade` reads to
apply codemods and list the manual steps. This file is the human summary.

## 0.5.0 (unreleased)

- **Suggestions from code (experimental).** `karni check`, `karni doctor` and
  the new `karni suggest` end with a compact block of what Karni could do that
  the project does by hand, each with its file, line and the exact command or
  change, and never fail a run. Seven codes in a new `SUG` series
  (`karni explain SUG001`): a self-referencing foreign key named like a parent
  (use `TreeModel`), a text field that holds markdown (use `MarkdownField`),
  raw SQL opt-outs with `GROUP BY` (use the aggregate declaration), three
  models tagged to one tree (declare a taxonomy), an added module nothing uses
  (`karni remove <name>`), a module the spec or README describes that is not
  added (`karni add <name>`) and a project that drifted from `karni.yaml`
  (`karni build` or `karni spec export`). Silence one per line with
  `# karni: allow(<rule>): <reason>`, the form of the architecture rules, or
  all of them with `KARNI_SUGGESTIONS = False`. `karni suggest --json` has a
  versioned schema, [karni-suggestions.schema.json](docs/assets/karni-suggestions.schema.json),
  and the agent rule K004 tells agents to read them. `manage.py karni_check`
  gains `--no-suggestions` and `--suggestions-file`, and `manage.py
  karni_suggest` is new. See [suggestions](docs/enforcement.md#suggestions).

- **Medintel, the large-app reference.** `examples/medintel` is a
  medical-intelligence portal on synthetic data, built from `karni.yaml` with
  `karni build`: two trees, taxonomies, per-user grants on tree nodes,
  aggregates and saved charts, cross-model search, markdown fields, a menu
  from data, both sign-in methods with the terms gate, and import and export,
  in 486 lines of project code. Its tests and a CI job (`medintel`) run it,
  and the [friction log](docs/friction/medintel.md) lists what it had to work
  around. Two fixes came out of it: `karni seed --reset` now wipes a tree
  leaves first, and `assert_crud`'s list check follows the pages, so a seeded
  table no longer hides the new row.
- **Production email is set up, or the deploy check says so.** `karni_settings()`
  reads the mail server from `EMAIL_URL` (`smtp+tls://user:password@host:587`)
  and `DEFAULT_FROM_EMAIL` and `SERVER_EMAIL` from the environment, and
  `karni check --deploy` reports `karni.W520` while production mail goes to the
  console, locmem, dummy or file backend or comes from a localhost sender. A new
  project's `.env.prod.example` lists the email settings, and both env examples
  show `KARNI_PHONE_COUNTRY_CODE` with its format. See the
  [migration note](docs/migrations/0.5.md#production-email-email_url-and-karniw520).
- **`karni explain` explains settings.** `karni explain KARNI_SITE_HIGHLIGHT`
  prints a setting's description, default, environment variable and docs link,
  Karni's own and every module's, from the source
  [docs/settings.md](docs/settings.md) is generated from, which now lists each
  module's settings too, with an anchor per row.
- **Fixes from the second end-to-end test.** `karni import design --editable`
  makes the design's repeated address `site.address` and gives each page's
  first large picture `fetchpriority="high"`, and `{% image ... eager=True %}`
  (`eager=forloop.first` in a loop) loads a picture first. `karni design
  analyze` leaves an empty list's placeholder text to the page. `karni make
  form` keeps a control's `rows`, `min`, `max`, `step` and `pattern`
  (`{% karni_form attrs=... %}`), prints its tag again with `--tag`, puts the
  recipients in `.env.prod.example`, and writes an email that leaves out empty
  optional fields and links the admin with a full address (`admin_url`, from
  `KARNI_SITE_URL` or the request's origin, which queued tasks carry as
  `karni.tracing.get_origin()`). A `karni make` command that changes the API
  says how to accept the new snapshot. The scaffold's settings define
  `BASE_DIR`, the site's page test loads `content/site.json` with
  `karni.testing.load_content` (read from the project root), and `karni new`
  and the site-from-design procedure name `karni createsuperuser`. `karni
  check --seo` holds back the crawl's request logs, and `/sitemap.xml` reads
  each section once.
- **Fixes from the third end-to-end test.** `karni worker` on a Mac runs
  Celery's threads pool (`--pool` picks another), and the dev profile gives
  broker reads a 5 second timeout, so a stopping worker no longer hangs in
  "Warm shutdown" when Redis does not answer its last poll. `karni explain`
  explains karni-site's template tags (`karni explain image`) and the content
  map's keys (`karni explain map.items`), from the sources the tables in
  docs/public-site.md and docs/design-content.md are rendered from. `karni
  design analyze` makes a detail page's `<dl>` with the same terms on every
  page one typed field per term (`"term"` in the map). `karni import design
  --editable --map` seeds a menu of every detail page of a model as that
  model's rows, so a new row appears in it. The site-from-design procedure
  says how `{% karni_seo %}` finds a detail page's row. See the
  [migration notes](docs/migrations/0.5.md#the-development-worker-threads-on-a-mac-and-a-broker-timeout).
- **Karni sites say they run on Karni.** `{% karni_seo %}` writes
  `<meta name="generator" content="Karni">` on every public page, and the
  scaffold's `frontend/index.html` carries the same line, so tools that list
  a site's technologies can detect Karni. It names no version. A design's own
  generator tag is replaced. `KARNI_GENERATOR` changes the text, and `""`
  turns it off. See [docs/public-site.md](docs/public-site.md#seo-by-default).
- **A public site is ready for search engines by default.** karni-site's
  `{% karni_seo %}` in base.html writes each page's title, description,
  canonical link, `noindex`, Open Graph and Twitter tags and the site's
  JSON-LD (`Organization`, or `LocalBusiness` with address, phone, opening
  hours, logo and social profiles, `KARNI_SITE_SCHEMA_TYPE`), from the
  admin's entry for the page, then `seo` in the view's context, then the row
  the page is about (`class Karni: seo`), then the template's own tags, then
  the site's settings. `/sitemap.xml` lists the site's pages and the public
  rows of every model with a page (`class Karni: sitemap`, published flags,
  scopes and soft deletes honoured), and `/robots.txt` closes the site
  outside production (`DJANGO_ENV`, `KARNI_SITE_ALLOW_INDEXING`). `{% image
  obj.photo width=400 alt=... %}` writes `srcset`, `sizes`, `width`,
  `height` and lazy loading from WebP copies a Celery task makes next to
  each upload through the project's storage (`KARNI_SITE_IMAGE_WIDTHS`,
  `KARNI_SITE_IMAGE_QUALITY`, the upload cap `KARNI_SITE_IMAGE_MAX_SIZE`),
  and shows the original until they exist. Pillow is the `karni-site[images]`
  extra. `karni check --seo` (the new `karni.checks.seo` entry-point group)
  renders every page through the test client and reports SITE010 to SITE018:
  missing or shared titles and descriptions, images without alt, size or
  smaller copies, broken internal links and pages missing from the sitemap.
  `karni make site` and `karni add site` include `karni_site.urls`, `karni
  make site` writes `{% karni_seo %}` and the images extra, and `karni import
  design` puts the tag where the design's head tags were and gives the
  design's images their width and height and smaller WebP copies in a
  `srcset`. [docs/public-site.md](docs/public-site.md#seo-by-default).

- **A token benchmark harness (experimental).** `scripts/benchmarks/tokens/` measures the
  same three apps (booking with payments, a CRM with three roles and CSV import, a shop with
  orders and refunds) built by Claude Code with and without Karni: a contract and black-box
  acceptance tests per task, a reference solution built with Karni for each, two starting
  projects made by script, `run.py` for the runs (interleaved, a fresh folder and PostgreSQL
  database each, a time limit, the harness's own checks after the agent stops) and
  `report.py` for the median and spread per task and condition. The method, the commands, the
  limits and the raw data are in `docs/benchmarks/tokens.md`. No runs are published yet.
- **Five recipes, and `karni new --recipe` (experimental).** `shop`,
  `booking`, `crm`, `lms` and `marketplace` ship in karni-cli. Each is a
  `karni.yaml` that leaves no question open, with the modules and features
  that suit it and demo volumes, plus the little domain code a spec cannot
  express, with tests of its own: an order's total and checkout, a slot
  that never takes more bookings than its capacity, a deal pipeline, a
  course's completion for a student, a payout after a fee from a setting.
  `karni new "<Name>" --recipe <name>` renders the project, writes the
  recipe's spec with the project's name and runs `karni build`, which
  writes the recipe's files over its own stubs before it migrates, seeds
  with the recipe's seeders, runs the tests and `karni check`. Without an
  interpreter or a database for the project it stops after the spec and
  says to run `karni build`. A recipe's file replaces a stub only while it
  is exactly what build wrote, else the build stops with `C441` and writes
  nothing. `C420` now names the closest recipes, a recipe with a file where
  karni build writes its own code is `C421`, and `C440` refuses `--recipe`
  with `--design`, `--kind site` or `--no-staff-app`. `karni build` now
  writes the settings block before the apps, so the test of a `Granted()`
  entity acts as a role the spec declares. A new `recipes` CI job builds
  each recipe from scratch. [docs/recipes/index.md](docs/recipes/index.md).
- **A sixth recipe, `data-portal` (experimental).** Datasets and the
  indicators they publish by region and sector, in one recipe: Region and
  Sector as trees, Dataset tagged to both (taxonomies) with markdown fields,
  field groups and column sets, Indicator rows with an aggregate by year,
  region, continent, sector and dataset, search across datasets and
  indicators, related tabs, a dashboard page, the menu from the spec, import
  and export by natural key, response caching on the trees, and the
  karni-charts module with one saved chart in the seed. An analyst reads the
  datasets and indicators of the regions granted to them by per-user grants
  and the `tree:region` scope, staff read everything and an editor imports
  and edits. About 3,000 synthetic indicators come from the recipe's seeders.
  [docs/recipes/data-portal.md](docs/recipes/data-portal.md).
- **Fixes found building it.** With `KARNI_USER_GRANTS` on, a user grant
  written after a cached list was not seen until the entry expired, because
  the cache key holds the caller and not the caller's grants: every cached
  response now reads the grant table's version token while the feature is
  on. And `karni spec validate` refuses `region__parent` in an aggregate
  with `C500` on a tree entity, though the aggregation docs name it: a tree
  entity's `parent` (and `position` on an ordered tree) is known now.
- **The /new-app flow (experimental): from a one-line request to a running
  app.** A new procedure, `new-app`, takes an agent through the flow: a
  recipe or the blank start (`karni recipes list --match`), the questions
  of `karni plan --questions` and only those, `karni spec answer`, `karni
  plan`, `karni build`, then only the domain logic that is left, in the
  project's own files. `karni rules sync` renders it into every adapter: a
  `/new-app` slash command for Claude Code, Cursor, Windsurf and Copilot,
  and a line in AGENTS.md and the other instruction files for tools without
  slash commands. A new rule, `K311`, says never to hand-write what
  karni.yaml can express (`karni rules` grows by 19 tokens, to 603). The
  welcome page's first prompt and the last lines of `karni new` are now
  this flow: describe the app in one line, then `/new-app`. Run `karni
  rules sync` in an existing project for the new command and rule.
  [docs/agents.md](docs/agents.md#agents-the-new-app-flow).
- **Recipes (experimental): `karni recipes list [--match "<request>"]` and
  `karni recipes show <name>`.** A recipe is a folder with a `karni.yaml`, a
  `recipe.toml` (name, title, purpose, `use_when`, `usually_changed`) and
  optional files of its own. Karni's live in karni-cli, and others join
  through the `karni.recipes` entry point group. `--match` ranks them by
  plain word overlap with the request (2 for a `use_when` word, 1 for a
  purpose word), with no language model, and when none scores 2 it names
  the blank start: a karni.yaml with the version and the app's name. Five
  recipes ship with it (above). `--json` follows the published
  `docs/assets/karni-recipes.schema.json`, `recipe.toml` follows
  `docs/assets/karni-recipe.schema.json`, and `C420` and `C421` are new.
  [docs/app-spec.md](docs/app-spec.md#recipes).
- **MCP tools for the flow (experimental).** `karni mcp` adds `recipes`,
  `spec_validate`, `questions`, `answer`, `plan`, `build` and `modules`,
  each returning the JSON its command prints, as published in
  `docs/assets/karni-mcp.schema.json`. `build` never forces or adopts a
  Karni-owned file edited by hand: it returns `C273` with the three ways
  on, for the user to choose. [docs/app-spec.md](docs/app-spec.md#mcp-tools).

- **Search across models (experimental): `class Karni: search` and
  `GET /api/search/`.** A model opts in with `search = {"fields": [...],
  "title": ..., "subtitle": ..., "weight": ...}`. `GET
  /api/search/?q=&models=&limit=` searches every declared model through the
  queryset its routed viewset's list uses for the request, so a model or a
  row the caller cannot list never appears, in one query per model. The
  answer is grouped per resource, each hit with its `resource`, `id`,
  `title`, `subtitle` and `score`, so a client links it to its
  `ResourceDetail` page. PostgreSQL ranks by trigram similarity (`ILIKE` or
  pg_trgm's `%`, then `KARNI_GLOBAL_SEARCH_THRESHOLD`), SQLite matches by
  `icontains`, and the weight orders models against each other. A query
  under `KARNI_GLOBAL_SEARCH_MIN_LENGTH` answers no groups, and an unknown
  `?models=` name is 400 `E431`. Each searched field gets a
  `karni.fields.TrigramIndex` in `Meta.indexes`, so `makemigrations` and
  `karni build` write it, and `karni check` names a searched field without
  its index on PostgreSQL with the command that adds it (`W590`).
  `BaseViewSet.global_search_queryset` is the escape hatch. `E430` refuses a
  malformed declaration and `W591` warns about a declared model no viewset
  serves. The OpenAPI document carries the operation and `x-karni-search`,
  `karni types` exports `SearchResource` and a typed `useGlobalSearch`, and
  `@karni/ui` adds `GlobalSearch` (a Cmd or Ctrl+K command palette, the
  WAI-ARIA combobox pattern, role `global-search`, tokens
  `--karni-search-width` and `--karni-search-max-height`), `useGlobalSearch`
  and `<Layout search>`. In `karni.yaml` an entity takes `global_search:
  true` or `{fields, title, subtitle, weight}`, whose fields default to its
  `search` list (`C540` to `C542`), and `karni plan`, `karni build` and
  `karni spec export` follow it. Large-apps roadmap item 10.
  [docs/global-search.md](docs/global-search.md).

- **Wide models (experimental), large-apps item 12: `MarkdownField`, field
  groups and column sets.** `karni.fields.MarkdownField` is a `TextField`
  whose OpenAPI property says `format: markdown` (`karni.api.formats`: any
  model field with an `openapi_format` publishes one). `ResourceForm` edits
  it with Write and Preview tabs, `ResourceDetail` shows it formatted and
  sanitized through `MarkdownView`, `ResourceTable` leaves it out of its
  default columns, and it is searched like any text field. `class Karni:
  field_groups = {"Overview": [...], "Financials": [...]}` lays out
  `ResourceForm` and `ResourceDetail` as sections, or tabs with
  `field_group_layout = "tabs"` (a tab with a failing field is marked and
  opens when focus moves to it), and the admin's change form as fieldsets.
  The fields in no group come last, under Other. `column_sets = {"default":
  [...], "financial": [...]}` gives `ResourceTable` a column set menu whose
  choice is kept per user and table. The schema publishes both as
  `x-karni-field-groups` and `x-karni-column-sets` on the list operation,
  limited to the fields the requester may read. `karni check` refuses a
  malformed declaration, a group or set naming a field the model does not
  have and a field in two groups (`karni.E550` to `karni.E553`). A 120-field
  test model keeps a list page of 25 rows under 200,000 bytes and a detail
  under 8,000, and renders ResourceForm under 1,000 ms and ResourceDetail
  under 600 ms in the UI suite. New props: `fieldGroups` and `groupLayout`
  (ResourceForm, ResourceDetail), `columnSets`, `columnSet` and
  `onColumnSetChange` (ResourceTable). [docs/fields.md](docs/fields.md#markdownfield),
  [docs/ui.md](docs/ui.md#field-groups-and-column-sets-experimental).
- **The spec takes `markdown`, `groups` and `column_sets` (experimental).**
  `karni make model` and the spec take the field type `markdown` (no longer
  reserved, `C224`). `karni build` writes an entity's `groups` as
  `Karni.field_groups` in the Karni-owned model base instead of the admin's
  fieldsets, and the new entity key `column_sets` as `Karni.column_sets`
  (`C680` and `C681` refuse an unknown or repeated column and a set without
  columns or a snake_case name). `karni plan` shows both and treats a change
  between `text` and `markdown` as the same column. `karni spec export`
  reads them back. The published JSON Schema is regenerated.
- **`@karni/ui` reads a formatted string that may be blank.** drf-spectacular
  publishes a blank email, URL or markdown field as `oneOf [{format},
  {maxLength: 0}]`. The schema parser read it as kind `unknown` and the
  form had no input for it. It is now that string.

- **Page blocks beyond CRUD in `@karni/ui` (experimental), large-apps item
  11.** `DashboardGrid` and `DashboardCard` (a responsive grid of titled
  cards with spans, and loading, empty and error states), `ChartCard` (a
  card around `DataChart`), `DataTable` (rows a page computed: sorting, a
  sticky header and first column, CSV and XLSX export, and only the rows in
  view rendered past 100 rows, so 10,000 rows scroll smoothly),
  `ComparisonTable` (entities as columns, metrics as rows, the best value
  marked), `Accordion` (the WAI-ARIA accordion pattern) and `MarkdownView`
  (sanitized markdown). Each has a component role, stories in the axe suite
  and tests. MarkdownView loads its parser and sanitizer (`marked` and
  `DOMPurify`, new dependencies of `@karni/ui`) on first use, and DataTable
  loads its XLSX writer (written in Karni, no dependency) on the first
  export, so pages that do not use them pay nothing. `useResourceCounts`
  counts the rows of each resource for a chart. New tokens:
  `--karni-dashboard-gap`, `--karni-data-table-max-height` and
  `--karni-data-table-row-height`, which `karni ui detect` lists.
  [docs/ui.md](docs/ui.md#page-blocks-experimental).
- **Related tabs on ResourceDetail (experimental).** `related={["deals",
  "people"]}` shows a tab per reverse relation, each a ResourceTable
  filtered to the record. The OpenAPI schema publishes each model's reverse
  relations as `x-karni-related` on its list operation, with the list
  parameter that filters each one (`null` when its list has none), so the
  UI guesses nothing. [docs/api.md](docs/api.md).
- **The spec takes related tabs and dashboard pages (experimental).** A
  detail page written `{detail: {related: [Booking]}}` gets the tabs (`C560`
  to `C563` refuse a tab that names no entity, an entity with no fk to the
  page's, an ambiguous fk, or a tab listed twice), and a page of kind
  `dashboard` named anything but `home` is a DashboardGrid with a ChartCard
  of each entity's rows. `karni plan` shows both, `karni build` writes them,
  `karni spec export` reads them back, and `karni make page` takes `--kind
  dashboard` (with `--count`) and `--related`. The published JSON Schema is
  regenerated. [docs/app-spec.md](docs/app-spec.md#pages).
- **`karni/no-raw-elements` flags a raw `<details>` too**, and its messages
  name the page blocks: a `<table>` is a ResourceTable, a DataTable or a
  ComparisonTable, and a `<details>` an Accordion. `karni rules --check` and
  rule `K201` say the same. A page that writes a raw `<details>` fails the
  lint until it uses `Accordion` or carries a disable comment with a reason.

- **Tooling for large projects (experimental), large-apps item 14.**
  `karni context --summary` prints one line per app (its models, viewsets
  and pages, with their counts), `--app LABEL` one app in full (every model,
  the relations in and out, each viewset with its route and access, the
  roles, the pages) and `--model NAME` one model in depth (every field in
  the spec's words, the relations that point at it). `--max-tokens N` cuts
  the output at whole sections and names what was left out and the command
  that prints it. Without them the output is unchanged. `karni check` keeps
  the results of the file checks (the source rules and the duplication
  fingerprints, Karni's own included) in `.karni/local/check-cache.json`
  under each file's hash, and ESLint keeps its cache in
  `.karni/local/eslintcache`, so an unchanged file is not checked again. A
  cache from another Karni, Django or Python version or from other settings
  is ignored. `karni check --changed [REF]` checks only the files git
  reports as changed, while the whole-project checks still run, and
  `--no-cache` (or `KARNI_CHECK_CACHE = False`) turns the cache off. On the
  100-model benchmark project a cached `karni check` takes about half the
  time of a cold one. `karni seed --volume N` writes N rows per model with
  `bulk_create` in batches (`--batch-size`): relation targets first, foreign
  keys drawn from existing rows, one-to-one targets used once, a self
  relation pointing at earlier batches, many-to-many links in bulk, and the
  rows, time and rate per model in the report. It refuses a table holding
  rows no seed run left there (a ledger in `.karni/local/seeded.json`,
  `E473`) unless `--reset` or `--force`. A seed count at
  `KARNI_SEED_BULK_THRESHOLD` (default 1000) takes the bulk path in a plain
  run too, so `karni plan` shows a large `seed` count of karni.yaml with its
  expected time class and `karni build` seeds it in bulk. The scaling check
  takes its row counts from `KARNI_SCALING_ROWS` and, per viewset, from
  `query_scaling = Scaling(rows=(5, 500), seconds=0.3)`, whose `seconds` is a
  time budget at the large count: a failed budget (`E476`) names the
  endpoint, the rows, the time and the queries. On PostgreSQL `karni queries
  --explain` now runs `EXPLAIN ANALYZE` of every query inside the request's
  rolled-back transaction and flags each sequential scan on a table of
  `KARNI_EXPLAIN_SEQ_SCAN_ROWS` rows or more (`W611`) with the index that
  would serve it. On another database it keeps its plain `EXPLAIN` of the
  slowest statements and says so (`W610`). A new CI job times `karni check`,
  `karni context` and the tests on a 100-model project
  (`scripts/benchmark/large_project.py`) and fails above 1.5 times the
  baseline. New codes: E470, E471, E473, E475 to E477, W610, W611, C580 to
  C582. [docs/enforcement.md](docs/enforcement.md#the-check-cache),
  [docs/seeding.md](docs/seeding.md#volume-seeding),
  [docs/debugging/queries.md](docs/debugging/queries.md#query-plans-explain).

- **karni-reports (experimental): PDF reports of a row.** A new module,
  `karni add reports`, with `@karni/reports-ui`. A report is declared in
  `<app>/reports.py`: `@register` on a `Report` naming the model, the
  template (which extends the shipped base print template,
  `karni_reports/base.html`, with the page size, margins and header and
  footer blocks) and `get_context(obj)`. A Celery task renders the template
  to HTML, then to PDF with WeasyPrint, and stores the file through Django's
  storage. The file is cached by the report, the row, a template version
  (the template's sources, what it extends or includes, the page size and
  the renderer) and a data version (a hash of the context), so a changed row
  or template gives a new file and an unchanged one is served again without
  rendering. `POST /api/reports/<report>/<id>/` answers 200 with the
  download path when cached and 202 otherwise, `status/` follows it and
  `download/` streams the PDF. Each one retrieves the row through its
  model's own viewset first, so another user's row is a 404, and each is
  throttled per caller. While rendering, only `data:` URLs and static and
  media files are read, never the network. `manage.py karni_pregenerate`
  renders every row, given ids or only stale ones, in batches with counts
  and times. The admin lists the generated files with their status, size,
  data version and errors, with a Regenerate action. `karni check` fails for
  a report without a viewset (`REPORT004`) or a template (`REPORT010`).
  `KARNI_REPORTS_RENDERER = "fake"` renders in tests without system
  libraries. Codes `REPORT001` to `REPORT011`. In karni.yaml,
  `modules: {reports: {page_size: letter}}`: `karni plan --questions` asks
  the page size and `karni build` wires the module. WeasyPrint needs Pango,
  a system library (`libpango-1.0-0 libpangoft2-1.0-0`), which CI installs.
  [docs/modules.md](docs/modules.md#modules-in-this-repository).
- **Error codes may have a six-letter prefix.** The registry, `karni
  explain`, the failure briefs and the debug middleware accept `REPORT001`
  like `PAY001`.

- **karni-ai (experimental): structured extraction with a language model,
  always through the import preview.** A new optional module, `pip install
  "karni-ai[anthropic]"` (or `[openai]`) and `karni add ai`, with
  `@karni/ai-ui`. `POST /api/ai/extract/` takes a resource (its router
  prefix) and one source: text, a URL or a PDF. A language model reads it
  into rows that follow the JSON Schema of the resource's own writable fields
  (its OpenAPI request component, for the caller's role), the answer is
  validated against that schema, and the rows go through Karni's import
  preview. The endpoint answers the proposed rows, a problem per field, the
  preview's counts and the import job's id. Nothing is written until the user
  confirms through the import's own commit. Only a user the resource's access
  lets create may call it, 30 times an hour each (throttle scope
  `ai.extract`). A URL is fetched only over http or https, to a public
  address (redirects checked the same way), within a size limit and a
  timeout. PDF text comes from pypdf. Providers: `anthropic`, `openai` (SDK
  extras) and a deterministic `test` provider. The provider, the model name
  and the key come from settings and the environment only, with no default
  model: `karni check` fails (`AI001` to `AI005`) until they are set. Every
  call is logged (`AICall`, read-only in the admin) with its tokens and a
  cost from `KARNI_AI_PRICES`, and optional monthly token budgets per user
  and per project refuse a call when spent (`AI013`, `AI014`). In karni.yaml,
  `modules: ai: {provider: ...}` is planned, asked by `karni plan
  --questions` and wired by `karni build`. `ExtractButton` and `useExtract`
  in `@karni/ai-ui` read a source into the preview and commit it.
  Karni core never imports the module. Codes `AI001` to `AI016`.
  [docs/ai-extraction.md](docs/ai-extraction.md).

- **karni-storage (experimental): protected files in S3 or an
  S3-compatible service.** A new module, `karni add storage`, with
  `@karni/storage-ui`. `ProtectedFileField` and `ProtectedImageField`
  (`file:protected` and `image:protected` in karni.yaml and `karni make
  model`) keep their files in a private bucket or, in development, in a
  directory no URL serves. The API gives each one as the row's download
  path, `<resource>/<id>/files/<field>/`, which retrieves the row through
  the model's own viewset first (another user's row, a soft-deleted row and
  a hidden field are a 404), then redirects to a signed URL that lives
  `KARNI_STORAGE_URL_EXPIRY` seconds, or streams the file on local storage.
  With `Accept: application/json` it answers a link that opens without
  credentials, for token auth. One setting, `KARNI_STORAGE_PROVIDER`
  (`aws`, `r2`, `minio`, `spaces`, `b2`, `gcs-interop`), gives core's S3
  backend the endpoint, region and addressing style, with the credentials
  in the environment. Direct uploads: `POST <resource>/files/<field>/upload/`
  answers a presigned POST with the field's size limit and content type (a
  presigned PUT where the service takes no POST policy), the browser sends
  the file to the bucket, and `POST .../confirm/` checks the object's
  existence, size and type before a row may point at it, through a token
  only that user may use for that field. The three endpoints are limited
  per caller under their own throttle scopes (`storage.download`,
  `storage.upload`, `storage.confirm`, rates in
  `KARNI_STORAGE_THROTTLE_RATES`) and answer 429 past the limit.
  Thumbnails of protected images are made by a Celery task with core's
  thumbnailer and served through the same path (`?size=small`). `karni check` fails for an unknown preset
  (`STORE001`), missing credentials (`STORE002`), a missing region, account
  id, endpoint or bucket (`STORE003`) and a missing URL include
  (`STORE004`). Codes `STORE001` to `STORE020`, and `C720` for a protected
  field without the module. `@karni/storage-ui` has `ProtectedFileInput` for
  `ResourceForm` (the upload with progress and the confirm),
  `ProtectedFileLink`, `ProtectedImage` and their hooks. In karni.yaml,
  `modules: {storage: {provider: r2}}`: `karni plan --questions` asks the
  provider, and `karni build` wires the module and places its URL include.
  [docs/storage.md](docs/storage.md).
- **`karni build` places a module's URL include.** When a build adds a
  module whose manifest names one (`wiring.urls`), the line goes at the
  `# karni:urls` marker of `config/urls.py`, so the code the build generates
  works at once. `karni add` still prints it, and `karni remove` takes it
  out.

- **Production proof (experimental): `/healthz` and `/readyz`, API versions
  and a deploy guide.** `/healthz` is liveness and `/readyz` is readiness over
  `KARNI_READYZ_CHECKS` (the database, the cache and the Celery broker,
  `check_broker`), each check bounded by `KARNI_HEALTH_TIMEOUT` seconds. A
  failure is 503 and `failing` names the check. The health views (these and
  `/health/`, `/health/ready/`) are never cached, open before the terms are
  accepted and left out of the request log while they answer below 400
  (`KARNI_LOG_QUIET_PATHS`). The scaffold mounts them with `*probe_urls`, its
  dev and production compose files ask `/readyz`, and Caddy forwards both. A
  project without them keeps asking `/health/` until you add the two lines
  (`karni make deploy compose` picks the URL from `config/urls.py`).
  `KARNI_API_VERSION=v1` mounts the API at `/api/v1/` through
  `karni.api.versions.api_urls()` (the scaffold uses it), `KARNI_API_UNVERSIONED`
  keeps, redirects (308) or removes `/api/`, and `KARNI_API_VERSIONS` marks a
  version deprecated, with a sunset date and migration notes: its responses
  carry `Deprecation`, `Sunset` and `Link` headers. Each version has its own
  OpenAPI document and Swagger UI, and `karni types` writes `types.ts` and
  `hooks.ts` for each into `frontend/src/api/<version>/`. `app.api_version` in
  `karni.yaml` is shown by `karni plan` and written by `karni build` as
  `KARNI_API_VERSION`. New codes: `E590`, `E591`, `W660`, `W661` and `C740`.
  The "Production stack (compose, smoke)" CI job now migrates, seeds, runs a
  smoke script that signs in, reads a list at `/api/` and `/api/v1/` and
  checks a deprecated version's headers, and a Playwright test that signs in
  to the built staff app and sees a ResourceTable page. The deploy guide gains
  the variables that matter, migrations on deploy, health checks, Celery and
  beat, static and media files, API versions and scaling. See
  [docs/deploy.md](docs/deploy.md) and [docs/api.md](docs/api.md#api-versions).
- **Clarifying questions (experimental): `karni plan --questions` and
  `karni spec answer`.** Before `karni build`, `karni plan --questions
  [--json] [--max N]` lists the few questions to ask the user, at most 5
  by default, decided by fixed rules over `karni.yaml` and the module
  manifests, never by a language model: an entity related to the user
  without `owner`, an entity without `access` (the `--access` presets that
  fit it), roles without a `default` for sign-ups, no `app.kind`, and each
  unanswered ask of a listed module or of a feature the spec turns on.
  The data model and access come first, then the kind and the modules,
  then the features, and the same spec always gives the same questions.
  Each has a stable id, one sentence, its options, a default and the key it
  sets. `karni spec answer <id> <value>` writes the answer into karni.yaml
  and keeps every other line, comments included. An unknown id (`C400`), a
  value the question does not take (`C401`) and an answer that cannot be
  written cleanly (`C402`) are refused. It reads only the spec, so it works
  before the project exists. `--json` follows the published
  `docs/assets/karni-questions.schema.json`. A new agent rule, `K310`,
  tells agents to ask only these questions before `karni build`.
  [docs/app-spec.md](docs/app-spec.md#questions).

- **Navigation from data (experimental): each user's menu, opened by the
  same grants as the API.** `KARNI_NAVIGATION` is a list of items and groups
  (`{"label", "route", "icon", "order", "requires"}`, a group with
  `children` and no route), or `"db"` for the `NavItem` tree (an
  `OrderedTreeModel`) of the new `karni.navigation` app, which a project adds
  to `INSTALLED_APPS` only for that source. An entry requires `public`,
  `authenticated` (the default) or a permission pattern as in `KARNI_ROLES`,
  read through `grants_for`: role grants and live per-user grants. `GET
  /api/navigation/` answers the requesting user's menu in order, a group
  whose entries are all hidden left out, in at most three queries (role
  grants, user grants, the rows), with the `Navigation` and `NavigationItem`
  schema components. The admin lists `NavItem` as a tree and has a *Menu
  preview* per user. `karni check` reports an item whose route no frontend
  page serves (`E533`, naming the closest route, from the `path:` entries of
  `KARNI_NAVIGATION_PAGES`) and a requirement that names no permission
  (`E534`), reading the database menu where the database answers (`W630`,
  `W631`). New codes `E530` to `E536`, `W630` and `W631`.
  [docs/navigation.md](docs/navigation.md).
- **@karni/ui: the menu from the server (experimental).** `<Layout
  navSource="server" pathname={pathname}>` renders `useNavigation()` (`GET
  /navigation/`, cached per signed-in user): groups collapse behind a button
  (Enter or Space) and open while they hold the current page, the current
  page is the exact route or the longest route the path is under, and icons
  come by name from `defaultNavIcons` or the `icons` prop. `navItems` takes
  groups (`LayoutNavGroup`) too, with a `NavGroup` slot, and
  `navigationEntries` converts the server's items on its own.
- **`karni.yaml`: `navigation` (experimental).** `navigation: true` is every
  page with a route of its own, in `pages` order, and a list gives the order
  and the groups (`- Catalog: [Product, Category]`), each page with optional
  `label`, `icon` and `requires`. Each page's requirement comes from its
  access. `karni build` writes `KARNI_NAVIGATION` in the settings block,
  `karni plan` shows it (`+ KARNI_NAVIGATION: Home /, Catalog (...)`), and
  `karni spec export` writes it back from the setting. New codes `C640` to
  `C642`. `manage.py karni_facts` reports `KARNI_NAVIGATION`.
  [docs/app-spec.md](docs/app-spec.md#navigation).
- **Tree models (experimental): a hierarchy is one declaration.**
  `class Region(TreeModel, BaseModel)` adds `parent` (a nullable foreign
  key to the model itself, `PROTECT`, `related_name="children"`), and
  `OrderedTreeModel` adds `position` for the order of siblings. Both work
  with `BaseModel` and `BigIntBaseModel`. `objects` is a `TreeManager`:
  `roots()`, `children(node)`, `ancestors(node)`, `descendants(nodes,
  include_self, max_depth)`, `subtree_ids(ids)` and `walk(...)`, each one
  recursive query that never loops on cyclic data (the `CYCLE` clause on
  PostgreSQL, a path of keys on SQLite). `save()`, `clean()` and
  `move_to(parent, position=None)` refuse a parent at or below the node
  (`E340`), and `move_to()` renumbers the old and new siblings of an
  ordered tree in the same transaction. A soft-deleted node hides its
  branch: `delete()` refuses a node with live children (`E341`, HTTP 409),
  and `delete_branch()` soft-deletes a whole branch in one statement.
  New codes `E340` to `E345`, system checks `E344` (the base listed before
  `TreeModel`) and `E345` (a redeclared `parent`).
  [docs/models.md](docs/models.md#tree-models).
- **Tree endpoints (experimental).** A `BaseViewSet` whose model is a tree
  model serves `tree/?root=&depth=` (nested and lazy: each node has
  `has_children`, and `children` is `null` where not loaded, bounded by
  `tree_max_depth` and `tree_max_nodes`), `<id>/children/` (paginated),
  `<id>/ancestors/` and `<id>/move/`, and its list takes `?parent=<id>`,
  `?parent=null` and `?descendants_of=<id>`. `DELETE ?branch=true` deletes a
  branch with write access to every node in it. Every walk follows the
  rows the requester may read, and the query counts do not grow with the
  tree. `Granted()` maps `move` to `change`. On an ordered tree `position`
  is read-only in the API. The OpenAPI document marks a tree model's schema
  and every relation to one with `x-karni-tree`.
- **The admin lists a tree model in tree order (experimental)**, each name
  indented by depth, with no declaration (`tree_changelist_max_rows`).
- **`karni check`'s new `hand-written-tree` rule (experimental) and agent
  rule `K312`.** A project model with a `parent` (or `parent_*`) foreign key
  to itself that is not a `TreeModel` fails the check. Inherit `TreeModel`
  first and drop the field, or opt out with `# karni: allow(hand-written-tree):
  <reason>`. `karni rules` lists 45 rules in 575 tokens.
- **`karni.yaml`: an entity takes `tree: true` (TreeModel) or `tree:
  ordered` (OrderedTreeModel) (experimental).** `karni spec validate`
  refuses a tree on an external entity, or a tree entity that declares
  `parent` or `position` (`C460`). `karni spec export` writes the key,
  `karni plan` shows it, and making an entity a tree or flat again, or
  dropping `ordered`, is a risky change. `karni build` lists `TreeModel` or
  `OrderedTreeModel` first in the model base. `manage.py karni_facts` gives
  each model's `tree` (`null`, `"tree"` or `"ordered"`) and leaves the tree's
  own fields out of `fields`. [docs/app-spec.md](docs/app-spec.md#trees).
- **`karni types` writes a `use<Name>Tree` hook** for each resource whose
  schema carries `x-karni-tree` (experimental).
- **@karni/ui: trees (experimental).** `TreeView` shows a tree resource
  with lazy branches, search and the WAI-ARIA tree keyboard pattern.
  `TreeSelect` picks one node or several, and `ResourceForm` uses it for
  every foreign key or many-to-many whose schema carries `x-karni-tree`.
  `TreeBreadcrumb` shows the path from the root, and `ResourceDetail` shows
  it above a tree resource's record (new `breadcrumb` prop and `Breadcrumb`
  slot). `useResourceTree`, `useResourceChildren`, `useResourceAncestors`
  and `useTreeMutations` wrap the endpoints, and the schema parser reads
  `x-karni-tree` into `ResourceSchema.tree` and `FieldDef.tree`. New
  component roles `tree-view`, `tree-select` and `tree-breadcrumb`, and the
  theme tokens `--karni-tree-indent` and `--karni-tree-max-height`.
- **Per-user grants (experimental): access given to one user, next to the
  role grants.** `UserGrant` in `karni.accounts` (migration `0009`) holds a
  permission pattern and a scope written as in `KARNI_ROLES`, `targets` (row
  ids for a `related:<key>` scope, in place of `user.<key>`), `expires_at`,
  `granted_by` and `reason`, with every change in the history. While
  `KARNI_USER_GRANTS` is on (default off), `grants_for` adds a user's live
  grants to their role grants, so `Granted()`, `Can`, `user.can`,
  `@requires`, the admin's row scope and imports answer with the union, for
  one more query per request however many checks it makes. Off, no grant row
  is read. `karni.accounts.grants` writes them (`grant`, `bulk_grant`,
  `change`, `expire`, `revoke`), refusing a bad pattern, scope or targets
  (`E360`, `E361`, `E362`), a grant the operator does not hold (`E363`) and
  a field `change()` does not set (`E365`),
  and `scope_targets(user, scope, permission=...)` gives the target ids a
  user's roles and user grants hold, with the grant behind each, for the
  tree scope and the menus to come. The admin edits a user's grants on their
  page and lists them all under *User grants* (with *Expire selected*), the
  effective permissions mark each source as a role or a user grant, and
  `api/auth/permissions/grants/` lists, adds, changes, revokes and
  bulk-grants them (`E364` once switched off). `karni why` and `karni
  why-empty` name the user grant that decided, with its id, reason and
  expiry. `features: user_grants: true` in `karni.yaml` turns it on through
  `karni plan` and `karni build`. `Grant` gains `targets` and `grant_id`,
  and `GrantSource` the user grant's fields, all defaulting to empty.
  [docs/accounts.md](docs/accounts.md#per-user-grants).
- **The tree scope (experimental): a grant on a node reaches every row under
  it.** `tree:<path>` is a new scope for `KARNI_ROLES`, user grants,
  `Granted()`, `Can`, `user.can` and the admin's row scope. `<path>` is the
  row's foreign key or many-to-many to a tree model, through relations when
  needed (`tree:region`, `tree:product__categories`). A user grant's targets
  are its nodes, and a role grant (or a user grant without targets) reaches
  the node in the user attribute named after the path's last step
  (`user.region`). No node gives no row, never every row. The rows compile
  to one subquery, the cycle-safe walk of the tree models started from every
  granted node at once, and the nodes are read once per request, so list,
  detail, custom actions, export, import relation lookups and the admin keep
  flat query counts. `karni.accounts.tree_scope` holds `resolve_path`,
  `subtree_rows`, `tree_rows`, `granted_targets`, `SubtreeKeys`, `tree_scope()`
  for a `Where`, `access_forest` and `explain_row`. `RolePermission.scope`
  takes `tree` (migration `0010`, choices and help texts only), `tree` joins
  `TARGETED_SCOPES`, a user who holds a node may grant a node below it, and
  the permission matrix offers `tree:<field>` for each relation to a tree
  model. A path that does not end at a tree model is `E490` at startup, and
  a role grant whose members have no such attribute is the warning `W620`.
  A tree resource serves `GET access/?permission=`: the requester's granted
  nodes, their ancestors and every other root, each flagged `granted`
  (`E491` for a bad pattern). `karni why` and `karni why-empty` name the
  grant and the node: "user grant 12 targets Europe, and this row's region
  Lyon is under it". In `karni.yaml` a role grant takes `tree:<path>`,
  checked against the spec's tree entities (`C620`), and `karni plan` and
  `karni build` carry it into `KARNI_ROLES`. `@karni/ui` adds
  `useResourceAccessForest`, and `TreeView` takes `access` to show the
  forest, granted nodes selectable and their ancestors greyed.
  [docs/accounts.md](docs/accounts.md#the-tree-scope).
- **Taxonomy tagging (experimental): one declaration tags a model to tree
  models.** `class Karni: taxonomies = {"region": "geo.Region"}` gives the
  model a many-to-many named after each key, added when the class is
  prepared so `makemigrations` writes it (a plain `ManyToManyField`, blank,
  `related_name="+"`, whose auto-created through table already holds the
  unique row and node pair and the node index the queries use), or adopts
  the many-to-many the model declares under that name. The list takes
  `?region=<id>,<id>` and `?region_descendants=true`, one subquery over the
  cycle-safe walk through the nodes the requester may read. `GET
  <resource>/facets/?taxonomy=region&rollup=true` counts the rows per node
  under the list's filters, search and access, rolled up to the ancestors
  with each row once, in two queries whatever the number of nodes
  (`facet_queryset()` is the escape hatch). A tree resource that a taxonomy
  points at serves `GET <id>/tagged/?descendants=true`: the rows tagged with
  the node per tagging model, each under its own access. The key is a
  `tree:<key>` scope path, imports and exports name tags by natural key with
  `|` between several, and the relation carries `x-karni-taxonomy` in the
  OpenAPI document. `karni.taxonomy` holds `taxonomies`, `tagging`,
  `tagged_rows`, `facet_counts` and `facets`, and `karni.tree.walk_sql`
  takes `origin=True`. New codes `E570` (a malformed declaration), `E571`
  and `E572` (`karni check`: a target that is not a tree, an adopted field
  that does not point at it) and `E573` (a bad parameter, 400).
  `manage.py karni_facts` gives each model's `taxonomies` and leaves a
  generated field out of `fields`. [docs/models.md](docs/models.md#taxonomies).
- **`karni.yaml`: an entity takes `taxonomies: {region: Region}`
  (experimental),** checked against the spec's tree entities (`C700` to
  `C703`). `karni plan` shows it and writes a migration when it changes (a
  taxonomy removed or pointed at another tree is risky), `karni build` writes
  `class Karni: taxonomies` into the model base, `karni spec export` reads it
  back, and a role grant's `tree:<path>` may follow a taxonomy key. The key is
  no longer reserved (`C224`). [docs/app-spec.md](docs/app-spec.md#taxonomies).
- **@karni/ui: `FacetPanel` and `ResourceTable`'s `facets` (experimental).**
  `FacetPanel` shows each node of a taxonomy with its count from `facets/`,
  nested by parent, with a checkbox per node. `<ResourceTable facets />`
  shows one per taxonomy, counted under the table's other filters and
  search, and choosing nodes filters the table to the rows tagged with them
  or below them, kept in the URL. `useResourceFacets` is the hook, and the
  parsed schema marks a taxonomy's field (`taxonomy`) and the `facets`
  operation. `ResourceForm` keeps editing the tags with `TreeSelect`.

- **Aggregations (experimental): grouped counts and sums under the list's
  filters and access.** A model declares what may be aggregated in `class
  Karni: aggregate` (`group_by`, `values`, `metrics`, `expressions`), or a
  viewset in `aggregation`, and `GET <resource>/aggregate/` takes
  `group_by` (a field, a relation path, an expression, or a date bucket
  `:year`, `:quarter`, `:month`), `metric` (count, sum, avg, min, max,
  distinct_count), `value`, `top` (the rest in "Other"), `stack` or
  `series`, and every list filter and `search`. Access applies first,
  through the list's queryset. It is one query, two with "Other". A field,
  metric or path that is not declared, or hidden from the requester, is a
  400 with its code (`E382` to `E387`), a resource without a declaration a
  404 (`E381`), and `karni check` checks the declarations (`E380`,
  `W570`). `karni.aggregation.TextNumber` reads numbers stored as text
  (`"$1.2B"`, `"450K"`) in SQL on PostgreSQL and SQLite. The OpenAPI
  document has the `AggregateResult` response, the parameters with the
  declared values as enums, and `x-karni-aggregate`. The query-scaling
  check measures the action, `KARNI_AGGREGATE_MAX_GROUPS` (default 1000)
  caps the groups, and `get_aggregation()` and `aggregate_queryset()` are
  the escape hatches. In `@karni/ui`, `useAggregate` fetches it and
  `DataChart` reads it through `aggregate`, with stacked bars (`stacked`),
  and `karni types` writes `use<Resource>Aggregate` with the declared
  groups as a union type. [docs/aggregations.md](docs/aggregations.md).
- **Saved charts: the karni-charts module (experimental).** `karni add
  charts` adds a `Chart` model edited in the admin: a source resource (any
  routed resource whose model declares an aggregation), the x axis (a group
  with a date bucket), the y axis (a metric and a value), an optional z axis
  (stacked or as series), `top`, `default_filters` and `allowed_filters`.
  Saving checks the axes against the source's declaration (`CHART001`,
  `CHART003`, `CHART004`), and the change form previews the data as the
  signed-in user. `GET /api/charts/<slug>/data/` returns the definition and
  the data, read through the source's own aggregate action as the viewer,
  so the access is the source's, and a viewer's filter the chart does not
  allow is a 400 (`CHART002`). `KARNI_CHARTS_READ` chooses who reads the
  definitions. `@karni/charts-ui` draws one with `<SavedChart chart="..."
  />` on `@karni/ui`'s `DataChart`. [docs/charts.md](docs/charts.md).
- **`aggregate:` in karni.yaml (experimental).** An entity's `aggregate:
  {group_by, values, metrics}` is validated against its fields and
  relations (`C500` a field or path it does not have, `C501` a metric,
  `C502` a date bucket), shown by `karni plan` (an option, no migration),
  written by `karni build` into `class Karni: aggregate` of the Karni-owned
  model base, and read back by `karni spec export` (an aggregate with
  expressions stays in code). `charts` is a module of the catalog, so
  `modules: {charts: {read: public}}` adds it. The published JSON Schema
  is regenerated, and `aggregate:` is no longer a reserved key (`C224`).
- **Rule K314 (agents): grouped counts and sums are `class Karni:
  aggregate` and the aggregate action, never a hand-written GROUP BY view.**
  `karni rules` lists 45 conventions in 576 tokens.

- **Response caching is stable** (large-apps item 9). Keys are
  `karni:api:r:<app_label.model>:<sha256>` over the viewset, the path, the
  query string normalised (sorted parameters, empty values dropped, the comma
  lists of `?expand=` and `__in` filters sorted), the API version, the
  language, the caller's access scope and the version tokens of every model
  read. Callers with the same roles share an entry when the read access
  depends on roles alone (`Public`, `Authenticated`, `HasRole`, grants scoped
  `all`), otherwise the entry is the user's own. `BaseViewSet.get_cache_scope`
  and `karni.api.caching.access_scope` decide it. Every write invalidates:
  signals for every model in every process, Karni's `update()`, `delete()`,
  `bulk_create()` and `bulk_update()` once per call, imports and content
  loads once per run (never for a dry run), the admin's bulk actions once per
  action (`invalidation_batch()`), and again when a transaction commits.
  `invalidate(Model)` now covers the model's details too. `X-Cache: HIT`,
  `MISS` or `BYPASS` on every cacheable response, and `X-Bypass-Cache: 1`
  for staff. `karni.E410` refuses a cached viewset that reads an external,
  unmanaged or other-database model without `Cache(ttl=...)` or
  `Uncached(...)`, and `karni.W580` warns about a per-process cache in
  production. `KARNI_API_CACHE_FLUSH = "03:30 Europe/Paris"` schedules a
  daily full flush through Celery beat (`karni-flush-api-cache`, `E411` for a
  bad value). `clear()` uses the backend's `delete_pattern` when it has one
  and replaces the version tokens otherwise, and the admin's *API cache*
  screen shows the setup and clears everything or one resource. The pytest
  plugin starts every test with an empty response cache. EventHub caches its
  venues. `X-Karni-Cache` is deprecated (removed in 1.0, with a warning once
  per process until `KARNI_API_CACHE_LEGACY_HEADER = False`).
  [docs/api.md](docs/api.md#response-caching),
  [migration note](docs/migrations/0.5.md#response-caching-is-stable).
- **karni.yaml takes `features: api_cache` and an entity's `cache:`.**
  `api_cache` takes `true`, `false` or `{ttl: <seconds>}` and sets
  `KARNI_API_CACHE` and `KARNI_API_CACHE_TTL` in the settings block (left
  out, the block sets nothing and the environment decides). An entity's
  `cache:` (seconds, or `false`) becomes `cache = Cache(ttl=...)` or
  `cache = Uncached(reason="spec")` in its Karni-owned viewset. `karni spec
  export` and `karni plan` read both back, and `manage.py karni_facts`
  reports each viewset's `cache` and the two settings. New codes: `C520` (an
  entity's `cache` is not valid) and `C521` (with `api_cache` on, an entity
  reads an external table or one on another database and has no `cache`).
  The `api_cache` feature manifest is `in_spec = true`.
- **`karni build` (experimental): the spec applied in one command,
  idempotently, without touching hand-written code.** `karni build
  [--spec karni.yaml] [--dry-run] [--allow-destructive] [--json] [--force]
  [--adopt <file>...]` computes `karni plan`, refuses risky changes without
  `--allow-destructive` (`C270`), a key type switch (`C272`) and a module
  removal (`C271`), checks that no Karni-owned file was edited by hand
  (`C273`), then runs `karni add` for new modules, writes the files,
  `manage.py karni_makemigrations`, migrate, seed (only the tables it
  created, only while empty), `karni types`, `karni test` and `karni check`.
  It stops at the first failure with its code (`C270` to `C285`), and the
  next run continues from there. A second run with no change writes
  nothing. Karni's code lives in files of its own (`<app>/karni/models.py`
  as abstract classes, `api.py` as viewset bases, `seeds.py`,
  `<app>/tests/karni/`, `frontend/src/pages/karni/`, and the `karni:spec`
  blocks of `config/settings.py` and `routes.tsx`), fingerprinted in
  `.karni/build.json`. The project's `models.py`, `viewsets.py` and
  `seeds.py` hold a subclass per entity, created once. `--force` keeps a
  `.orig` copy, and `--adopt` hands a file to the project. `--json` follows
  the published `docs/assets/karni-build.schema.json`.
  [docs/app-spec.md](docs/app-spec.md#karni-build).
- **`manage.py karni_makemigrations` (experimental).** Django's
  `makemigrations` without questions, with the renames written first as
  `RenameModel` and `RenameField` (so the data stays when the type changes
  too), and a required field added to an empty table without a one-off
  value.
- **`karni plan` marks what karni build manages.** Each change gains
  `managed` (and the summary `not_managed`): a change on a model, viewset
  or page the project wrote by hand is printed `(not managed)`. `access:
  code` now matches any access the project declares, the planned API tests
  are `<app>/tests/karni/test_<entity>.py` (none for an external entity or
  one on another database), and a module option at its default no longer
  shows as a change. A page of kind `code` (`- reports: code`) is a page of
  the project's own, and `karni spec export` writes one so.
- **`karni make test` checks isolation only where reads are owned.** An
  `Owned(...)` in `write=` alone no longer gives `assert_isolated`, and a
  role the read rule admits outright (`HasRole("staff")` next to
  `Owned(...)`) no longer runs it: the check acts as a signed-in user. Both
  generated tests failed with `E605` before.
- **The query-scaling rule measures a model on another database there**
  (`Karni.database`), instead of failing on the test database's guard.
- **The module catalog and `karni remove` (experimental).** Every module
  describes itself in `karni.module.toml` inside its package, found through
  the new `karni.modules` entry point group, and every built-in feature
  (`two_factor`, `email_code_login`, `social_login`, `terms`, `api_cache`)
  has a manifest in `karni/catalog/features/`: purpose, what it provides
  (models, endpoints, pages, settings with their types), the questions to
  ask (each mapped to a setting, with options and a default), requires,
  conflicts, services, status and, for a module, the wiring `karni add`
  performs. `karni.catalog` parses and checks them. `karni modules list
  [--json]` and `karni modules show <name> [--json]` print the catalog,
  installed or not (karni-cli bundles a copy of each of Karni's manifests),
  and `karni context` prints a `CATALOG:` line per module and feature with
  whether the project has it (the backend adds a `FEATURES:` line). `karni
  add` reads the manifest for what it wires, with the same result for
  Karni's four modules: the URL include it prints comes from the manifest
  (none for approvals), and it adds the extras and the services the module
  needs, and refuses a module that conflicts with one the project has
  (`C315`). The new `karni remove <name> [--dry-run] [--keep-tables]` takes
  out what `karni add` wired, byte for byte, refuses while another module
  requires it (`C316`), and never drops data: it counts each table's rows
  through `manage.py karni_rows` and, while a table exists, stops with the
  `karni migrate <app> zero` command to run deliberately first (`C319`).
  The app spec reads its modules, their options, its features and the
  social sign-in providers from the catalog, replacing A1's hand-made
  table, and `karni spec validate` checks requires and conflicts (`C324`).
  `karni.testing.assert_module_manifest` checks a module's manifest against
  its entry point, settings fragment and models, and `karni make module`
  writes a manifest with that test. Rule K307 and the add-module procedure
  point agents at the catalog. New codes `C313` to `C319`, `C324` and `E310`.
  [docs/modules.md](docs/modules.md#the-module-catalog).

- **`karni plan` (experimental): what `karni build` would change, writing
  nothing.** `karni plan [--spec karni.yaml] [--json] [--offline]` validates
  the spec, reads the project the way `karni spec export` does, compares
  both in the spec's normal form and prints one line per change, grouped by
  area (app, modules, features, roles, apps, entities, fields, access, pages,
  migrations, seed, tests), with `+`, `~`, `-` and `!` for a risky change and
  a summary line. Risky changes (a field or entity removed, a type changed,
  a shorter length, a field that becomes required, a relation pointed
  elsewhere, a module removed, a key type switched, an entity moved to
  another database, access or a grant widened) name the rows they affect,
  counted by the new `manage.py karni_rows` (`karni.facts.count_rows`, only
  `SELECT COUNT`), and `karni build` will refuse them without
  `--allow-destructive`. `--json` follows the published
  `docs/assets/karni-plan.schema.json`. `C250` when the project cannot be
  read. [docs/app-spec.md](docs/app-spec.md#karni-plan).
- **The app spec's `pk`, `external`, `table`, `writable`, `database` and
  `was` (experimental).** The entity keys reserved by `C224` are keys now:
  `pk: uuid|bigint` (default: the project's `KARNI_PK`), `external: true`
  with `table` and `writable`, and `database: <alias>`. `was: <old name>` on
  an entity, or on a field written as `{type, was}`, makes a rename explicit
  and keeps the data. New codes `C251` to `C254` check them, `karni spec
  export` writes them back (a model on `BigIntBaseModel`, an external model,
  a model Karni manages on another database), and `manage.py karni_facts`
  adds each model's key type, table and `managed`, the database aliases and
  `KARNI_PK`. Its `base_model` is now true for `BigIntBaseModel` too, and
  the fields of Karni's model mixins are left out of every model's
  `fields`, not only of `BaseModel`'s.
- **The app spec, `karni.yaml` (experimental).** One small file describes an
  app in the terms `karni make`, `karni add` and the settings already use:
  `app` (name, kind), `modules` (each with its settings as options),
  `features` (`two_factor`, `email_code_login`, `social_login`, `terms`),
  `roles` (`KARNI_ROLES` with Karni's scopes, and `default` for
  `KARNI_ACCOUNTS_DEFAULT_ROLES`), `apps` with their entities (fields in
  `karni make model`'s syntax, `key`, `search`, `owner`, `audit`, `groups`,
  `order`, `scope_paths`, and `access` in Karni's `Access` vocabulary, or
  `access: code`), `pages` and `seed`. Unknown keys are errors, keys that
  start with `x-` are kept and ignored, and the keys of later features are
  reserved. `karni spec validate [--spec karni.yaml] [--json]` reports every
  problem with its code (`C210` to `C246`), line, path and fix, checking each
  field with the generator's own parser and every reference between the
  parts. `karni spec export [-o karni.yaml]` writes the spec of an existing
  project from its models, viewsets, settings, modules, seeders and frontend
  routes, lists what the spec cannot express, and starts the file with the
  `yaml-language-server` line naming the JSON Schema, published as
  `docs/assets/karni-spec.schema.json`. The backend side is the new
  `manage.py karni_facts` (`karni.facts`). karni-cli now depends on Pydantic
  2, which Karni already requires. `karni make model`'s field rendering is one
  function per field (`render_field`), with no change to what it writes.
  [docs/app-spec.md](docs/app-spec.md).
- **Experimental names: a tier of the stability promise.** A new public name
  may ship as experimental first: marked `Experimental.` in its docstring, by
  an *Experimental* note in its docs and by *Experimental tier* in the
  reference. It may change or be removed in a minor release without the
  deprecation cycle, each change noted here and in the migration notes, and
  it becomes stable once a reference application uses it. Error codes stay
  permanent. [docs/stability.md](docs/stability.md#experimental-names).
- **Sign in with a Google, Microsoft or Apple ID token (experimental).** A
  mobile app or a single-page app posts the ID token its provider's SDK
  returned to `POST api/auth/social/<provider>/` and gets what `login/`
  gives: a token pair in JWT mode, a session in session mode, or the 2FA
  gate. Karni verifies the token offline against the provider's key set
  (cached, fetched again on a rotated key at most once a minute), with the
  audience among the configured client ids, the issuer (Microsoft's per
  tenant, with a `tenants` allowlist), the expiry and the nonce (raw or
  SHA-256). Providers are small classes a project can add to or replace
  (`IdTokenProvider`). `KARNI_SOCIAL_TOKEN_SIGNUP` (`open`, `approval` for
  accounts an administrator activates, or `existing`) and
  `KARNI_SOCIAL_TOKEN_LINK_VERIFIED` decide who gets in. Linked identities
  live in the new `SocialIdentity` model (run `karni migrate`), shown
  read-only in the admin, and a link survives an email change. A Microsoft
  address counts as verified only with the `xms_edov` claim or a tenant in
  `trusted_tenants`. Each refusal has a code, `E215` to `E227`, and the
  endpoint its own throttle scope, `auth.social`. Needs `pip install
  'karni[social-token]'` (`E509` without it). It works in both modes and does
  not need `KARNI_SOCIAL_AUTH`, which stays session-only. `@karni/ui` adds
  `useSocialLogin(provider)` and `SocialButton` (the app's own provider SDK
  supplies the token: Karni bundles none).
  [docs/accounts.md](docs/accounts.md#sign-in-with-an-id-token-google-microsoft-apple).
- **Sign in with a code sent by email (experimental).** With
  `KARNI_EMAIL_OTP = True`, `POST api/auth/otp/send/ {"email"}` emails a
  numeric code and `POST api/auth/otp/verify/ {"email", "code"}` answers what
  `login/` gives: a token pair in JWT mode, a session in session mode, or the
  2FA gate. No password is involved. The send answer is the same 200 for
  every address, and every failure of a code is the same `E235`, so neither
  reveals whether an address has an account. Codes come from `secrets`, are
  stored only as an HMAC-SHA256 keyed by `SECRET_KEY` in the new `LoginCode`
  model (run `karni migrate`), and die after one use, `KARNI_EMAIL_OTP_TTL`
  (600 seconds) or `KARNI_EMAIL_OTP_MAX_ATTEMPTS` wrong guesses (5). A new
  code replaces the old one. `KARNI_EMAIL_OTP_SIGNUP` takes the same three
  policies as sign-in with an ID token (`open`, `approval` with `E224`,
  `existing`), an inactive account answers `E226`, and the routes answer
  `E236` once the setting is off. New throttle scopes: `auth.otp_send` (per
  IP), `auth.otp_send_email` (per address) and `auth.otp_verify`. The email
  is the `login_code` template through `KARNI_ACCOUNTS_EMAIL_BACKEND`, and an
  hourly schedule, `karni-flush-login-codes`, deletes expired codes. A code,
  like an ID token, now also verifies an account's address, and an account
  never verified loses its password (`karni.accounts.services.prove_address`).
  `@karni/ui` adds `useOtpLogin()`, `OtpLoginForm` and `LoginForm`'s
  `codeSignIn` switch.
  [docs/accounts.md](docs/accounts.md#sign-in-with-a-code-sent-by-email).
- **A versioned terms acceptance gate (experimental).** With `KARNI_TERMS =
  {"version": "2026-11", "url": "/terms/", "required": True}`, every
  signed-in user must accept that version before using the API: until they
  do, every request under `KARNI_TERMS["paths"]` (default `["/api/"]`)
  answers 403 `E245` with the version and the url. Staff and superusers are
  gated too. The auth mount (`login/`, `refresh/`, `me/` and the rest), the
  OpenAPI schema and `KARNI_TERMS["exempt"]` stay open, anonymous requests
  pass to the view, and the admin and a public site are not under `/api/`.
  `GET api/auth/terms/` answers the terms and whether the user accepted them,
  `POST api/auth/terms/accept/ {"version", "client"?}` records the acceptance
  with the IP (read like the throttles, honouring `NUM_PROXIES`), the user
  agent and the app's own `client` object, and another version is refused
  with `E246`. `me/` (and so `login/`) carries `terms` while the setting is
  set, and is unchanged otherwise. The record is the new append-only
  `TermsAcceptance` model (run `karni migrate`): rewriting a row raises
  `E247`, and the admin lists it read-only with a filter by version and an
  export. The gate is `karni.accounts.terms.TermsGateMiddleware`, which
  `karni_settings()` lists after authentication and which leaves the chain at
  startup unless the setting requires acceptance. Its answer is cached per
  (user, version), so a gated request costs no query after the first, and a
  new version makes everyone accept again. `karni.E248` reports a gate
  missing from `MIDDLEWARE`, `E249` the routes once the setting is unset.
  `@karni/ui` adds `TermsGate` and `useAuth()`'s `terms`, `termsRequired`
  (from `/me/` and from the gate's 403 on any request, through the client's
  new `onError` hook) and `acceptTerms(client)`.
  [docs/accounts.md](docs/accounts.md#terms-acceptance).
- **Integer primary keys, next to UUIDs (experimental).** `BigIntBaseModel`
  is `BaseModel` on a 64-bit integer key (`BigAutoField`), with the same
  timestamps, soft delete, audit users, guards, managers and `pre_write`.
  Both bases share one private core, so they never drift. The key type is in
  each model's class line, so one project mixes both, and Karni's own models
  and the modules keep their UUIDs and their migrations. `IntegerKeyModel`
  is the mixin on its own. `karni make model --pk bigint|uuid` picks it per
  model, and `KARNI_PK = "bigint"` in `config/settings.py` makes it the
  default. A project's own user model can redeclare `id` as a `BigAutoField`
  on `AbstractKarniUser`: login, JWT and session mode, `me/`, roles, 2FA,
  sign-in with an ID token or a code and the terms gate work with it.
  Integer keys can be guessed: `karni.W530` warns for a resource on integer
  keys that anyone may read (fix: a UUID key or a slug lookup; silence one
  viewset with `# karni: allow(public-integer-key): <reason>`). Ids stay JSON
  numbers. `karni context` prints each model's key type on a `KEYS:` line.
  `karni seed --reset` restarts the sequences it wipes, so the same seed gives
  the same integer ids. [docs/models.md](docs/models.md#choosing-the-key-type).
- **The primary key is no longer a derived filter.** `?id=`, `?id__gte=` and
  `?id__lte=` are not derived any more, for either key type. Declare them in
  `filterset_fields` where clients need them. A relation to an integer-keyed
  model filters with the new `IntegerFilter`, which refuses `1.5`.
  [Migration note](docs/migrations/0.5.md#the-primary-key-is-no-longer-a-derived-filter).
- **Imports match ids only when asked.** An upload's `id` column matches
  existing rows only with the new `match_ids` option, so an export from one
  environment cannot update unrelated rows in another, and `keep_ids` creates
  rows with the file's ids (legacy data, for a role that may create rows
  anywhere), then moves the PostgreSQL sequence past them. `karni load` moves
  the sequence after writing integer ids too. A relation cell names a target
  with a natural key by that key alone, so a numeric natural key is never
  read as an id. A row outside the scope reads "not found or not in your
  scope", whether it exists or not. The admin's map step has both options.
  Migration `karni_transfer.0002_importjob_id_options`.
  [docs/import-export.md](docs/import-export.md#ids).
- **Smaller fixes for integer keys.** `assert_row_hidden`'s export checks
  match an id exactly, never as a substring. `check_schema` probes a detail
  URL a numeric `lookup_value_regex` accepts. `karni replay` refuses (`E924`)
  when the captured id now belongs to another email. Ids show without
  thousands separators in `ResourceDetail` and `ResourceTable`. A capacity,
  overlap or state error on an unsaved row no longer names `None` as its id.
- **External tables, SQL views and a second database (experimental).** A
  model over a table or view another system owns declares `class Karni:
  external = True` with `Meta.managed = False`, on plain `models.Model`: the
  `model-base` rule accepts it, Karni runs no DDL for it, its viewset answers
  every write and the import endpoints with 405 (and the OpenAPI document
  leaves them out), its admin is read-only, it keeps no change history, and
  seeding and the query-scaling check skip it. `writable = True` lets the API
  and the admin write it, with a primary key the database does not generate
  sent on create. Access, role grants, row scope and field roles work as on
  any model, and a PostgreSQL table in another schema is `db_table =
  'reporting"."sales'`. `class Karni: database = "<alias>"` routes a model's
  reads, writes and migrations to that alias through `karni.db.DatabaseRouter`,
  which `karni_settings()` appends to `DATABASE_ROUTERS` after the project's
  own routers. On such an alias only the models routed there migrate, and
  relations across aliases are refused. Startup checks: `E270`, `E271`,
  `E275`, `E276`, `W541`, `W542`. `karni check` compares each external model
  with its table or view where the database answers: `E272` to `E274`, and
  `W540` when it does not answer. Karni's pytest plugin creates the tables of
  external models (and their PostgreSQL schema) in each test database
  (`--karni-external-tables=off` turns it off), and `assert_crud` checks a
  read-only model's refusals by itself (`read_only=`). `karni make model
  <Name> --external --table <[schema.]table> [--database <alias>]
  [--writable]` writes the model from the table's columns with Django's
  `inspectdb` machinery (`manage.py karni_inspect`), and its viewset (`C140`
  to `C142`). Generated factories now give a primary key the model does not
  generate a distinct value per row, and the role sync after `migrate` skips
  a database the role tables are not routed to.
  [docs/models.md](docs/models.md#external-tables-views-and-a-second-database).
- **The admin is light only.** Unfold's `THEME` is `"light"`: no light / dark
  / system switch on any page, and a browser in dark mode still gets the
  light admin. There is no setting for it. See
  [docs/admin.md](docs/admin.md#theming) and the
  [migration note](docs/migrations/0.5.md#the-admin-is-light-only).
- **The admin is simple to use.** Every list has a labelled **Add** button and
  **Edit**, **Delete** (or **Restore**) buttons on each row, shown only when
  the user's permissions allow them. Bulk actions on every list: delete
  selected (soft where the model has it, with a count and a sample on the
  confirmation), restore selected, **edit selected** (set chosen fields to one
  value on every selected row, saved row by row in one transaction, field
  permissions respected, `KARNI_ADMIN_BULK_EDIT_MAX` rows at most, default
  500) and export selected. Every form has a fixed bar (Save first, Save and
  add another, Save and continue editing, Cancel, Delete). Technical fields
  move to a collapsed read-only **Details** section, lists show at most six
  columns (name first, updated time last), and an empty list says "No
  \<models\> yet." with an Add button. The home page has a **Getting started**
  panel a user can dismiss and bring back from the user menu
  (`KARNI_ADMIN_GUIDE`), and each list and form shows one line of help from
  `class Karni: help`, else the model's docstring. `karni.yaml` takes `help:`
  per entity. Run `migrate` (one new table, `karni_admin_guidedismissal`).
  See [docs/admin.md](docs/admin.md#the-screens) and the
  [migration note](docs/migrations/0.5.md#the-admin-is-simple-to-use).
- **Everything a client sees on a public site is edited in the admin.**
  The karni-site module now holds the site's own details (`SiteSettings`:
  name, tagline, logo, favicon, the default share image, address, phone,
  email, map link, opening hours and social links, as `site` in every
  template, swappable through `KARNI_SITE_SETTINGS_MODEL`), editable blocks
  (`{% editable "home.intro" %}...{% endeditable %}` and `{% editable_image
  %}`, where the template's content is the default, stored on the first
  render and followed until someone changes it, edited as plain text with
  history, cleaned to a safe inline subset by a standard-library sanitiser
  behind `KARNI_SITE_SANITIZER`, with a highlight convention set by
  `KARNI_SITE_HIGHLIGHT`, and one cache read per page), menus (`{% get_menu
  "header" as items %}` looped in the design's own markup, nested items that
  go to a page by URL name, a row's page or an address, children from a
  model's rows, the current page on each item, seeded from the design's
  navigation), redirects (301 or 302, answered by
  `karni_site.middleware.RedirectMiddleware` where the site has no page,
  query strings passed on, loops refused with SITE006), per-page titles and
  descriptions (`PageSeo`, looked up with `karni_site.seo.page_seo(request)`)
  and an `editor` role that changes the content and nothing else. `karni
  import design --editable` marks every text, image, menu and contact detail
  of a designer's pages with these tags, with readable keys that
  `.karni/design.json` keeps stable across imports. `karni make site` and
  `karni add site` wire the middleware and the `site` context processor,
  and `karni check` reports either missing (SITE004, SITE005).
  [docs/public-site.md](docs/public-site.md#everything-the-client-edits).
- **A module can declare roles: the `karni.roles` entry point.** Its roles
  join `KARNI_ROLES` (the project's own win for the same slug), so `karni
  sync-roles`, the permission matrix and `karni context` treat them like the
  project's. [docs/modules.md](docs/modules.md#7c-optional-karniroles-roles-a-module-declares).

- **A designer's static pages become the site: `karni import design <dir>
  --app <app>`.** The folder's HTML, CSS, JavaScript and images become a site
  app with the design kept as written. The files are copied unchanged under
  `static/<app>/`, the header, navigation and footer every page shares go
  into `base.html` (a block some pages share becomes a partial, a page whose
  header differs keeps its own in a block override), each page becomes a
  template extending it with a view and a route (`index.html` answers `/`,
  `about.html` `/about/`, a folder a nested route), links become `{% url %}`
  and asset paths `{% static %}` (anchors and query strings kept, `srcset`
  and `url(...)` in style attributes included), a meta-refresh stub becomes a
  permanent redirect, and the current menu item is marked with
  `{% ifactive %}` wherever the designer marked it, whatever class or
  attribute the design uses. Inline scripts are wrapped in `{% csp_hash %}`
  so they run under the Content-Security-Policy, and the origins a page
  loads from are declared with `{% csp_allow %}`. Every page joins the page
  test. The report names the files no page or stylesheet uses and anything
  that could not be mapped. `.karni/design.json` records the import: a
  second run with a new version of the design reports what changed
  (`--diff` reports only) and keeps every file the project edited since
  (`--force` replaces them). The parsing, comparison and rewriting live in
  `karni_cli.design` for the later `karni design` commands.
  [docs/public-site.md](docs/public-site.md#import-a-design).
- **The content that repeats in a design becomes models and rows: `karni
  design analyze` and `karni design extract`.** `analyze <dir>` reads a
  designer's pages and finds the structures repeated within and across them
  (cards, list items, a gallery inside each project, a page per doctor). It
  infers the fields from the markup (a heading with its highlighted words,
  text, an image and its alt, a link, a list of tags, a date, a price, a
  number), merges the places that show the same items (a card that links to
  a detail page, an anchor that is an item's `id`, a shared key or title),
  finds the relations (a list of links to another model's items, an
  attribute holding its keys, items nested in another model's items) and
  prints ready-to-run `karni make model` commands, models others point at
  first. Names come from the design's classes, headings, labels, pages and
  folders. What the markup cannot settle (a list on a detail page that may
  be hand-picked or derived, a few items shown on the home page, a card
  styled on its own that holds a list item's values) is a decision for the
  agent, with the evidence. The report also gives the `KARNI_SITE_HIGHLIGHT`
  that renders the design's highlighted words, or says that `karni import
  design --editable` already wrote it. `--json` prints it all as stable
  JSON, and `--map <file>` writes a draft content map. `extract <dir> --map
  <file>` reads the pages with the map and writes their content in the
  `karni load` format: values parsed by type, highlighted words between the
  site's marker (`==words==`, the map's `"marker"`), relations by key,
  children nested, image paths relative to the output file. It refuses
  while a decision is open (C122) or the map cannot be followed (C121).
  [docs/design-content.md](docs/design-content.md).
- **`karni load --dry-run` shows a diff per model.** Each row it would create,
  each row it would change with the fields that change (old and new value),
  each file it would upload and each child `--prune` would delete, the first
  20 rows of a model listed and the rest counted. `--json` carries the same
  rows under `"changes"`. [docs/content-loading.md](docs/content-loading.md#validation-and-errors).
- **`karni make model --order <field> --key <field>`** writes `Meta.ordering`
  and `Karni.import_key`, the field `karni load` matches rows on (a child
  row: its parent plus that field, such as `position`).
- **One convention for highlighted words: `{{ value|highlight }}` in
  karni-site.** A model field keeps highlighted words the way an editable
  block does, between `KARNI_SITE_HIGHLIGHT`'s marker (`==words==`), and the
  filter renders them in the setting's tag and class, everything else
  escaped. `|highlight:"span.dot"` names another markup for one value,
  `|highlight:""` drops the marks. A backslash before the marker (`\==`)
  keeps it as typed, in a field and in an editable block alike.
- **New agent procedure `site-from-design`**: import, analyze, models,
  extract, load, then templates that loop over the rows. Run `karni rules
  sync` for its slash command files.
- **Projects have a kind: `karni new --kind site|app|site+app`.** `karni new`
  asks what the project is (an app when nobody can answer) and sets it up
  for that kind. A site gets the site app at `/` on karni-site, the admin as
  the place the client edits it, registration off and the roles staff and
  editor, with the staff app optional (`--no-staff-app`). An app is what
  `karni new` always made, and a site+app has both. The kind is recorded as
  `kind` under `[tool.karni]` in pyproject.toml, `karni context` prints it
  first, and the agent files open with it and its stack, so an agent never
  asks which technology to use. `karni add site` turns an app into a
  site+app and says how to go back. The root `karni --help` says how to
  start.
- **`karni new --design <dir>` builds the site from a designer's pages.** It
  runs `karni design analyze` (the draft content map `content/design-map.json`)
  and `karni import design --editable --map` (the site app, everything the
  client sees editable, the staff app and the admin themed from the design),
  then prints the rest of the site-from-design procedure with the project's
  paths. A kind with a site is implied.
- **`karni import design --editable --map <file>`: no blocks over rows.** The
  content a content map reads into rows (a list's items, a model's detail
  page values, galleries) is imported without blocks, because the loops
  render it from the rows and the client edits the rows. The copy a model's
  detail pages share has one key on all of them. The record remembers the
  map. Without a staff app, the import themes the admin from the file
  `KARNI_THEME_CSS` names.
- **The site-from-design procedure is the whole flow**: analyze, import with
  `--editable --map`, decisions, models, extract, load, loops, the one view
  for a model's detail pages (`karni make view <model> --path
  "/<folder>/<slug:slug>/"`), `karni make form` for each `<form>`, the page
  test and `karni check`. Its models step no longer runs `karni types`, which
  a site whose models have no API refused. `karni context` prints a `DESIGN:`
  line: the designer's pages the project imported, and the content map.
- **`karni make model` takes the model's own name for a relation to itself**,
  app-qualified too (`related:m2m:website.Course?`, as `karni design analyze`
  proposes it), as `"self"`. A many-to-many to itself is
  `symmetrical=False`: a hand-picked list goes one way, so `karni load` sets
  each row's own list and a second load changes nothing.
- **A site built from a design needs fewer hand edits.** `karni make form`
  prints a tag that always compiles, matches the design's fields to the
  model's by label and type, and adds `editable="<key>"`, which makes the
  form's labels, placeholders, button and message editable blocks. `karni
  design analyze` keeps a row of figures as page copy and writes `"by":
  "key"` or `"by": "title"` for a text that names another row (an unknown
  value is `C124`). `karni design extract` reads thousands separators and
  the page's decimal mark, and copies the images it names to
  `content/files/` (`--keep-paths` for the old paths). A menu item stays
  active on the pages under its path (`KARNI_SITE_MENU_SECTIONS`), `karni
  make view` with a capture rewrites `{% ifactive %}` names of the pages it
  replaces, and `karni check --seo` names a menu item whose page is gone
  (`SITE007`) and makes the image copies no worker made. `{% site_defaults %}`
  takes `share_image`, `logo`, `favicon` and `hours`, and an editable import
  fills them from the design: its `og:image` and its opening hours, which
  become `site.hours`. A design's plain `<em>` in headings is its highlight,
  and a block's default renders the marker.
- **New module `karni-site`: the runtime of a public site.** `{% ifactive
  "<app>:<name>" %}` marks the current page in a menu around whatever markup
  the design uses, `{% csp_hash %}` and `{% csp_allow %}` let a design's
  inline scripts and other origins pass the Content-Security-Policy for that
  response only, and `karni_site.views.page_not_found` and `server_error`
  render the site's own 404 and 500 pages with the request and fall back to
  a plain page when one fails. `karni check` runs SITE001 (templates get the
  request) and SITE002 (every URL name an `{% ifactive %}` names exists).
  `karni make site` wires the module the way `karni add site` does, sets
  `handler404` and `handler500`, and writes `templates/500.html`. In
  core, `karni.security.extend_request_csp(request, {...})` adds sources for
  one response from code that runs while it is built, and a hash added next
  to `'unsafe-inline'` is left out, because a browser would otherwise ignore
  the `'unsafe-inline'`. [docs/modules.md](docs/modules.md).
- **Public forms in one command: `karni make form`.** `karni make form
  contact name:str email:email subject:str message:text --notify
  ENQUIRY_RECIPIENTS` writes a contact form, a booking request, a newsletter
  sign-up or a job application alike: the model (the visitor's fields from
  the field DSL, a `status` StateField for the inbox from `--states`,
  staff-only `notes`, both hidden from visitors through `field_roles`,
  `audit`, `dashboard`, an admin inbox and an indexed search), a
  `BaseViewSet` with `create=Public()` read by `--role` (Karni's rate limit
  and honeypot apply, no throttle is written), the project's tests
  (anonymous submit, without JavaScript, the email, the protected fields,
  the rate limit, staff-only reading, `assert_crud`), the staff app's pages,
  and with `--notify` a queued listener, its email templates and the
  recipients setting. Without `--notify` nothing is sent. When the site came
  from `karni import design`, the command names the template and line of
  the design's `<form>` it replaces and prints the tag with the arguments
  that keep that form's class names, rows, labels and button. The import
  now records each page's forms in `.karni/design.json` and lists them in
  its report. [docs/public-site.md](docs/public-site.md#public-forms).
- **karni-site: `{% karni_form "<name>" %}` and its view.** The tag renders
  the fields a visitor fills from the form viewset's create serializer, with
  labels, required marks, limits, choices, the CSRF token and the honeypot.
  It works without JavaScript: the browser posts to `karni_site:form`, which
  saves through the viewset's own `create` (access, rate limit, honeypot,
  validation and history are the API's), then redirects back with
  `?sent=<name>` or renders the page again, by its own view, with the
  errors next to each field (400, 429, 403). `karni_site/forms.js` submits
  in place with inline errors and the rate-limit message, and runs under
  the enforced Content-Security-Policy because it is a static file with no
  inline code. Class names and markup come from the tag's arguments
  (`classes="bootstrap"`, `field_class`, `rows`, `labels`, ...), the
  `KARNI_SITE_FORM_*` settings and overridable templates.
  `karni_site.notify.notify_recipients` emails a row to the addresses a
  setting names, from the project's templates, with `Reply-To`. New codes:
  SITE020 (a check: a tag names a form that does not exist), SITE021 to
  SITE023. Rule K309 and the `new-model` procedure name `karni make form`.
- **A new project's staff app is ready to hand over.** The scaffold's
  `layout.tsx` wraps every page but a sign-in page in `<AuthGuard explain>`,
  so a visitor who is not signed in gets the sign-in prompt in place of a
  page of errors, and offers "Sign out". Its menu comes from the new
  `routeNavItems` in `@karni/ui` (one entry per static route, detail and
  "new" routes left out, the sign-in page listed only while nobody is signed
  in), which the example apps use too. Its home page is the new
  `<Dashboard>`: a `Stat` tile per count and the newest rows of every model
  that declares `class Karni: dashboard = {...}` (counts of every row, the
  new ones, one per state, and named counts by list filters), published as
  `x-karni-dashboard` on the list operation and checked at boot (`E133`).
  Nothing in the page names a model. See
  [docs/api.md](docs/api.md#the-staff-dashboard).
- **`ResourceDetail` renders a `StateField`'s transitions as buttons.** One
  per state the record may move to from its current state
  (`x-karni-transitions`), shown when the API lets this user write the field.
  A click PATCHes the field, a move into a terminal state asks first, and a
  refusal shows the server's own sentence. `transitions` tunes labels,
  confirmations and who may, or hides them, and the `Transitions` slot
  replaces them. `ResourceTable` puts a lifecycle field first in its derived filters.
  The parser exposes `transitions` and `initial` on a `FieldDef`.
- **`karni ui detect --css <path>` maps any stylesheet.** Plain CSS, a
  Bootstrap-style sheet, a design with no variables at all (then the body,
  link, button, heading and input rules are read), one file or a directory
  of pages. Custom properties whose name means a role are "found", values
  taken from rules or derived (ring, input, a contrasting primary
  foreground) are "inferred", the rest are "defaulted", and the report says
  which. A dark-only design is written for both modes. It is also a function,
  `karni_cli.uitheme.detect_css(paths)`, which `karni import design` calls.
  See [docs/theming.md](docs/theming.md#any-stylesheet-css).
- **One theme for the staff app and the admin.** `KARNI_THEME_CSS` (default
  `frontend/src/karni-theme.css`, the file `karni ui detect` writes) is
  served to the admin as the static file `karni/project-theme.css` by the
  new `karni.admin.theme.ProjectThemeFinder` (live under `runserver`,
  copied by `collectstatic`, same origin so the Content-Security-Policy
  allows it) and loaded third in `UNFOLD["STYLES"]`. Without the file the
  URL serves an empty stylesheet. See
  [docs/theming.md](docs/theming.md#one-theme-for-the-staff-app-and-the-admin).
- **`karni-theme.css` keeps dark mode.** Light-only colours are now written
  under `:root:not(.dark)`, so they no longer override Karni's dark palette
  under `<html class="dark">`. A file written by an earlier release is
  regenerated with `karni ui detect --force`.
- **Public server-rendered pages have a home.** `karni make site <app>`
  creates a site app (function views, `urls.py` with `app_name`, templates,
  static files, a 404 page) and includes it at `""` in `config/urls.py`, so
  its home page replaces the welcome page. `karni make view <name> --app
  <app>` adds a page. New rule K309 says where a public site goes, and K302
  and K306 now say they are about app screens. `karni context` lists the
  site's routes on a `SITE:` line. [docs/public-site.md](docs/public-site.md)
  covers reading content, SEO basics and public forms.
- **`assert_pages` tests a public site's pages.** `assert_pages(client,
  urls)` in `karni.testing` (and `self.assert_pages(urls)` on
  `APITestCase`) requests each page and checks a 200, a non-empty `<title>`
  and `<meta name="description">`, an `alt` attribute on every `<img>`
  (`alt=""` passes), that every same-site link, stylesheet and image answers,
  and that a URL the site does not have answers 404. Every problem is
  reported in one `E618` error, one line per page and problem, and each URL
  is requested once per call. Other hosts are not requested. The test client
  serves no static files, so a `{% static %}` URL is looked up with the
  staticfiles finders. `karni make site` writes `<app>/tests/test_pages.py`,
  which calls it on a `PAGES` list, and `karni make view` adds each new URL
  at its `# karni:pages` marker. The generated `base.html` passes it.
  Escape hatches: `follow=`, `check_links=`, `require_title=`,
  `require_description=`, `require_alt=`, `not_found_url=`, `ignore=`,
  `hosts=`, and a `PageParser` subclass as `parser=`. See
  [docs/testing.md](docs/testing.md#public-pages-assert_pages).
- **`config/urls.py` has a `# karni:urls` marker** where `karni make site`
  inserts its include. `karni upgrade` adds it to existing projects
  ([docs/migrations/0.5.md](docs/migrations/0.5.md)).
- **Security: `--access public-read` no longer lets every signed-in user
  write.** In 0.4.0 the preset wrote `Access(read=Public(),
  write=Authenticated())`. A new project also has open self-registration, so
  anyone who signed up could create, change and delete every row of the
  resource, and the generated test, acting as any signed-in user, passed. It
  was found in a real project built on 0.4.0. The preset now writes
  `write=HasRole("staff")`, and `--access public-read:<role>` names another
  role. This changes a security-relevant default: review every viewset that
  declares `read=Public(), write=Authenticated()`. `karni upgrade` lists the
  step, and [the 0.5 migration note](docs/migrations/0.5.md) has the
  details.
- **Public forms are protected by default.** A viewset whose `create` anyone
  may call (`create=Public()`) is limited to `KARNI_PUBLIC_CREATE_RATE` (10
  an hour per caller, by client IP for anonymous callers) with no
  `throttle` declaration. `Throttle(create=...)` replaces the rate and
  `Throttle(create=None)` or `KARNI_PUBLIC_CREATE_RATE = None` turns it off.
  A request that fills the honeypot field `KARNI_PUBLIC_CREATE_HONEYPOT_FIELD`
  (default `homepage`) is answered 202 and saves nothing. The field is named
  in the schema as `x-karni-honeypot`, never as a body field, and
  `@karni/ui`'s `ResourceForm` renders it hidden. The import endpoints of such
  a viewset now need a signed-in user, and an anonymous caller can no longer
  read an import job. `karni make model ... --access public-create` writes a
  public form's declaration, and the `new-model` agent procedure names it.
  The pytest plugin starts each test with empty
  rate-limit counters. This changes a default: see
  [the 0.5 migration note](docs/migrations/0.5.md#public-creates-are-rate-limited).
- **Security headers on every response.** `karni.security.SecurityHeadersMiddleware`
  sends a Content-Security-Policy (report-only while `DEBUG` is on) and a
  Permissions-Policy. The default policy allows what Karni serves: the admin
  (with `'unsafe-eval'` for its Alpine.js, on admin pages only), the API docs
  pages from their CDN, the welcome page's two scripts by hash and the
  `@karni/ui` app's theme script by hash. `KARNI_CSP` adds sources (Google
  Fonts, analytics) or removes a directive, `None` turns the header off,
  `KARNI_CSP_REPORT_ONLY` overrides the `DEBUG` choice, and `@csp_extend` and
  `@csp_exempt` adjust one view. `KARNI_PERMISSIONS_POLICY` allows a browser
  feature back. A new project's Swagger page uses drf-spectacular's split
  view, which needs no inline script. See
  [security headers](docs/security.md#security-headers).
- **`karni check --deploy`.** It runs Django's `check --deploy` plus ten
  Karni deploy checks, `karni.W510` to `karni.W519`: `DEBUG`, a strong
  `SECRET_KEY`, `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` without wildcards,
  HSTS, secure cookies, the admin off `/admin/`, CORS not open to every
  origin, and an enforced Content-Security-Policy whose `script-src` allows
  no injected script. Each finding prints with its code and fix, a warning
  fails the run, and a Django warning that a Karni check covers is printed
  once. `manage.py check --deploy` runs the same checks. `karni_check` now
  prints the findings of a failing Django check, which it used to swallow.
  `CSRF_TRUSTED_ORIGINS` is read from the environment, and the scaffold's
  `.env.example` lists the production values to set. See
  [deploy checks](docs/security.md#deploy-checks).
- **A production stack in every new project, booted in CI.** `karni new`
  (and `karni make deploy compose` in an existing project) writes
  `docker-compose.prod.yml`, the `Caddyfile` and `.env.prod.example`. The
  stack has a one-shot `release` service (the deploy checks, `migrate`,
  `collectstatic`, then `manage.py karni_publish_web`), `django` (gunicorn with
  uvicorn workers), Celery `worker` and `beat`, `caddy` (automatic TLS for
  `DOMAIN`, static and media files from the shared volume, the staff app at
  `/app/`, everything else proxied to Django), `db`, `redis` and `backup`, with
  health checks, restart policies, memory limits, log rotation, named volumes
  and no bind mount of source. Flags cover what differs between projects:
  `--app-path`, `--app-domain`, `--no-app`, `--no-celery`, `--no-db`,
  `--no-redis`, `--no-backups`, `--domain`. The scaffold's `Dockerfile` gains
  a `staff-app` stage (the frontend built with Vite's base set to the app's
  path) and a `backup` target, and `frontend/src/routes.tsx` passes that base
  to the router. `karni_publish_web` copies the Caddyfile, the built staff app
  and a snippet with the security headers Django sends, computed from the
  project's settings, into the volume Caddy reads, so a release or a rollback
  changes them together. A new CI job, "Production stack (compose, smoke)",
  creates a project, builds both images, starts the stack with generated
  production values and checks health, a public page, the admin login,
  static files, the staff app, the http redirect, the security headers, the
  deploy gate and a restored backup. See [docs/deploy.md](docs/deploy.md).
- **`karni check --deploy` at container start.** The production image's
  entrypoint, `python -m karni.deploy.entrypoint`, runs the deploy checks
  before its command and exits with `E520` when they fail.
  `KARNI_SKIP_DEPLOY_CHECK=1` starts it anyway, logged on every start, and
  `KARNI_DEPLOY_CHECK_COMMAND` replaces the check. `python -m
  karni.deploy.healthcheck` is the container health probe: it asks `/health/`
  with an allowed host and `X-Forwarded-Proto: https`, which a plain request
  in production does not pass.
- **Backups with retention, and a tested restore.** `karni.deploy.backup`
  (`karni-backup` in the backup image) dumps the database with `pg_dump` and
  archives the media every `KARNI_BACKUP_INTERVAL_HOURS`, keeps the newest
  `KARNI_BACKUP_KEEP`, uploads to `KARNI_BACKUP_S3_BUCKET` when it is set, and
  restores in one transaction (`restore`, with `--create` for a second
  database or `--clean` over the live one). `counts --against` compares the
  row counts of two databases. A failure is `E521` and turns the service
  unhealthy. It uses the standard library only.
- **`KARNI_HEALTH_CHECKS` is read from the environment** (comma-separated),
  so a deployment without a Celery worker leaves the Celery check out of
  `/health/ready/`.
- **`karni make test` acts as the role that may write.** For a viewset whose
  writes need a role, the generated test uses the role the `write` predicate
  names (then `create`, then `read`), so it exercises real creates, updates
  and deletes instead of confirming the refusals.
- **New warning `karni.W102`.** While registration is open, `karni check`
  warns for every routed viewset whose `write` is `Authenticated()` or
  `Public()` without a narrowing `HasRole`, `Granted`, `Owned` or `Can`.
  `create=Authenticated()` with an owned `write` is not reported.
- **`KARNI_ACCOUNTS_REGISTRATION` turns self-registration off.** It defaults
  to `True`, so existing projects do not change. `False` leaves `register/`
  out of the URLs (404) and out of the OpenAPI schema.
- **`assert_crud` sends a real image for a required `ImageField`.** The
  create and update bodies carried `<field>.txt` for every file field, and
  DRF's `ImageField` answered 400 ("Upload a valid image"), so every model
  with a required image failed the create and update checks. A required
  image now gets a 1x1 PNG made with Pillow (`E501` names `pip install
  'karni[images]'` when it is missing), a plain `FileField` keeps the text
  upload, every request gets a fresh upload (one passed in `payload=` is
  rewound), and the stored file must not be empty after the create and the
  update. `assert_isolated` posts such a body as multipart too, where it
  raised `UnicodeDecodeError` on the PNG. Two related messages changed. When the declaration refuses every
  write to the role, the report lists `no write exercised` in `skipped` and
  `assert_crud` warns, since such a run proves refusals only (pin them with
  `expect=` when they are the point). When the rows the run created are
  missing from the list, the message names the read rule and `karni
  why-empty`, instead of blaming the paginator.
- **`karni load` loads a project's real content from a file.** A JSON or
  YAML file maps model labels to rows. Each row is matched by its natural
  key (`Karni.import_key`, `Karni.natural_key`, a unique slug, or a unique
  constraint) and created or updated, so a second run with the same file
  changes nothing and says so. Relations name their targets by natural key.
  File and image fields hold paths relative to the content file and upload
  once (`--refresh-files` uploads again). A nested list holds a row's
  children, matched by parent and key or position, and `--prune` deletes the
  ones it no longer lists. The whole file loads in one transaction through
  the API's serializer and `clean()`, and one bad row rolls everything back
  with an error naming the file, model, key and field (`E804`, `E805`).
  `--dry-run` prints created, updated and unchanged per model. `--as USER`
  attributes the writes, and the change history records the load as one
  batch. It reuses the importer's row logic (`karni.transfer.imports`), which
  gains the escape hatches the loader needs. See
  [Loading content](docs/content-loading.md).
- **`karni seed` refuses tables that already hold rows.** It prints the
  models it will write to, then refuses (`E617`) when one of their tables
  already holds rows, because seed cannot tell its own rows from real
  content. The user table is left out and `--model` narrows the check, so a
  fresh project still seeds without flags. `--reset` starts over and
  `--force` adds demo rows on top. See
  [the migration note](docs/migrations/0.5.md#karni-seed-refuses-tables-that-already-hold-rows).
- **The case study page is removed**, with the before/after line counts the
  README quoted from it. The `examples/social-leads` app stays as a practice
  project and keeps running in CI.
- **A new project's frontend requires npm 11, and Karni says so.** npm 10,
  which Node 20 and 22 bundle, crashed in `npm install` of a fresh scaffold
  with `Cannot read properties of null (reading 'edgesOut')` while it
  resolved Vite 8's optional peers. The newest npm 10 (10.9.9) has the same
  bug, and npm 11 fixed it. The scaffold's `frontend/package.json` now
  declares `"engines": {"node": ">=20.19", "npm": ">=11"}` and its
  `frontend/.npmrc` sets `engine-strict=true`. npm runs that check only after
  the step that crashes, so it stops npm 10 with `EBADENGINE` once a
  `package-lock.json` exists, not on the first install. For the first
  install, the quickstart now has a step that works on any supported Node:
  `npx --yes npm@11 install`. `karni doctor` flags an npm below 11 and a Node
  outside Vite 8's range, with the fix. When ESLint or jscpd is missing,
  `karni check` names the npm requirement and what to run on npm 10. CI runs
  the quickstart on Node 20 with its bundled npm as well as on Node 24.
- **A rate limit for one action.** `throttle = Throttle(create="10/hour")` on
  a `BaseViewSet` limits each caller of that action, on top of the
  project-wide `anon` and `user` throttles. A public contact form no longer
  needs a hand-written `get_throttles()`. It is DRF's throttle under the
  scope `"<route>.<action>"`, so `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`
  replaces the rate or switches it off with `None`. The OpenAPI schema
  publishes the rate as `x-karni-throttle`, and a bad declaration is `E132`.
  See [rate limits](docs/api.md#rate-limits).
- **`env` and `SILENCED_SYSTEM_CHECKS` after `karni_settings()`.** The call
  leaves `env`, the django-environ reader Karni uses, in the settings module,
  so a setting added below it reads `.env` without `import os`. It is also
  importable as `from karni.conf import env`. `SILENCED_SYSTEM_CHECKS` now
  starts as an empty list, so `SILENCED_SYSTEM_CHECKS += ["karni.W967"]` no
  longer raises NameError. The `karni.W967` hint shows that exact line.
- **`karni make model` asks the project about Pillow.** The ImageField note
  appears only when the project's interpreter cannot import Pillow, or when
  there is no host interpreter to ask (a Docker-only project). The scaffold
  keeps depending on plain `karni`: `karni[images]` only adds Pillow, a
  native dependency a project without image fields does not need, and the
  note says to list `karni[images]` when one is added.
- **One dev port: `KARNI_DEV_PORT`.** Set it in `.env` and `karni serve
  --local` runs Django on it, the scaffold's `frontend/vite.config.ts`
  proxies `/api` and `/health` to it (read from `../.env` with Vite's
  `loadEnv`), and `docker-compose.yml` publishes Django on it. The default
  stays 8000, and `KARNI_API_PROXY` still wins when set. `karni serve --local`
  prints how to point the frontend at the server whenever the two disagree
  (`--port`, `--host`, a `KARNI_API_PROXY` that names another address, or a
  `vite.config.ts` from before this setting), and a bad `KARNI_DEV_PORT` is
  `C007`. The example apps' configs and compose files follow the scaffold.
- **Settings read during the call fail loudly below it.** `karni_settings()`
  reads `KARNI_AUTH_MODE`, `KARNI_2FA`, `KARNI_SOCIAL_AUTH`,
  `KARNI_SOCIAL_PROVIDERS`, `KARNI_FRONTEND_URL`, `KARNI_AUTH_THROTTLE_RATES`,
  `KARNI_JSON_LOGS`, `KARNI_CACHE` and `KARNI_STORAGE` during the call to
  compute other settings. Assigned below the call, one of them changed
  nothing and said nothing. Now the system check `karni.E508` fails startup
  and names the setting, what was computed from it, and the fix (move it
  above the call or pass it as a keyword). `KARNI_CACHE` and `KARNI_STORAGE`
  defined above the call build `CACHES` and `STORAGES`, as the environment
  does. The list is generated into [docs/settings.md](docs/settings.md) from
  `karni.conf.CALL_TIME_SETTINGS`, and the scaffold's `settings.py` names it.
- **`KARNI_ADMIN_LOGO` works wherever it is assigned, and on the login
  screen.** It was read during the call, so a value assigned below it was
  silently ignored. The admin now reads it on every request through
  `karni.conf.admin_logo.site_logo` and `site_icon` in `UNFOLD`, a bad value
  fails startup validation (`E303`), and the login screen shows the logo
  above its title (`karni_admin/login.html`, set as the admin site's
  `login_template` unless the site has one). Replacing `UNFOLD` below the
  call while a logo is set is `karni.E508`.
- **`karni make model` adds the images extra to pyproject.toml.** With an
  image field, the `karni` requirement in `[project].dependencies` becomes
  `karni[images]`, keeping its version spec, markers and other extras. Only
  that one string changes, `--dry-run` shows the diff, the note names the
  change and the reinstall (`pip install -e .`), and a project that lists the
  extra already is left alone.
- **`karni doctor` finds a local PostgreSQL and Redis.** Two new lines,
  `database` and `redis`, show what `DATABASE_URL` and `REDIS_URL` name
  (from the environment, `.env` or Karni's default, password masked) and
  whether the server answers: a socket connect with a short timeout and one
  protocol exchange, nothing read or written. When `.env` still names the
  compose hosts `db` and `redis` and they do not resolve, doctor looks on
  `127.0.0.1` at the default port and the configured one, and prints the
  exact `.env` lines for the local services (`DATABASE_URL=postgres://<your
  user>@127.0.0.1:5432/<project>`, `createdb <project>`,
  `REDIS_URL=redis://127.0.0.1:6379/0`) or how to start them. The quickstart
  has a "Without Docker" section with the Homebrew and apt steps.
- **An edit form keeps a stored file without asking for it (@karni/ui).**
  `ResourceForm` no longer marks a file or image field "required" on edit
  when the row already has a file. The current file stays listed by name,
  and saving without a new one keeps it.
- **The sign-in page leaves the sidebar after sign-in.** The scaffold's
  `layout.tsx` (and the example apps') lists a `.../login` route only while
  nobody is signed in.
- **Fixes in the scaffold and docs.** The scaffold's README linked to
  `github.com/karni`, which is not Karni. It now links to the repository, and
  `python -m karni.links check` catches the ownerless form too.
  `docs/testing.md` opens with the four fixtures most tests use.

### Fixed (backend self-test)

- **`?expand=parent` nests the parent of a tree.** A tree resource accepted
  `?expand=parent` (E126 listed it) and `?expand=region.parent` through a
  relation, but answered the key: the serializer stopped at any model already
  on the path. Every level a client names now nests, the path and
  `KARNI_API_MAX_EXPAND_DEPTH` bound it, and a parent the requester cannot
  read (above a tree grant, or outside the tree resource's read scope)
  expands to `null`, with nothing of it in the answer.
- **The unversioned redirect answers a POST with 308.** With
  `KARNI_API_UNVERSIONED = "redirect"`, a POST, PUT, PATCH or DELETE to
  `/api/x/` got Django's "CSRF verification failed" page (403), with or
  without a bearer token. The redirect is exempt from CSRF now: it changes
  nothing, and the versioned view it leads to still checks CSRF for a session.
- **`karni why` names the tree grant to widen.** For a row outside every tree
  grant, the fix named a user attribute the user model lacks (the one
  `karni.W620` reports) and the role to widen to `all`. It now names the
  user grant to widen first, with the `grants.change(...)` call. Without a
  user grant of the scope it gives the `grants.grant(...)` call that adds one,
  and it names the attribute only when the user model has it.

## 0.4.0 (2026-10-22)

- **PostgreSQL is the default, everywhere.** `pip install karni` now brings
  the PostgreSQL driver (`psycopg[binary]`), and the quickstart runs on
  PostgreSQL: `docker compose up -d --wait db` starts the project's own
  PostgreSQL 16, which a new project's `docker-compose.yml` now publishes on
  localhost only (`KARNI_DB_PORT` changes the port). SQLite is the no-Docker
  alternative, one `DATABASE_URL` away, without the guarantees only
  PostgreSQL gives.
- **Focus follows navigation, and a table is one Tab stop (@karni/ui).**
  `Layout` moves focus to the new page's heading after a client-side route
  change and announces the page title. It stays put on the first load, when
  only search params change, and when the page took focus itself.
  `routeFocus={false}` turns it off. `ResourceTable` is a WAI-ARIA grid with
  a roving tabindex: Tab enters and leaves the table, arrow keys move between
  rows and cells, Enter opens a row and Space toggles its selection. A 50-row
  page went from 205 Tab stops to 1. The table's role is now `grid`, and
  `keyboardNavigation="native"` restores the plain table.
- **OpenAPI enums are named after their model and field.** Two choice fields
  with the same name but different choices no longer get hash names such as
  `Status469Enum`. `karni.api.schema.postprocess_schema_enums` names them
  `<Model><Field>Enum` (`RefundStatusEnum`), with the app label in front when
  two apps have a model of the same name. `ENUM_NAME_OVERRIDES` still wins,
  and drf-spectacular's own hook restores its names.
- **The modules are tested on PostgreSQL.** CI runs karni-payments,
  karni-approvals and karni-impersonation on PostgreSQL 16 on every Python
  version, through the same overlay as the core. A pending change in
  karni-approvals now lists its fields in the model's order on PostgreSQL
  too (`jsonb` stores keys shortest first).
- **Scaffold comments in plain sentences.** The comments and the description
  in a new project's files no longer use em dashes.
- **Messages in plain sentences.** What the framework, the `karni` command,
  the modules and @karni/ui print or show (errors, system checks, `karni why`,
  `karni queries`, the query log, test helper failures, admin pages, emails,
  UI status text) no longer uses semicolons or em dashes. A few formats
  changed: the query log reads `GET /path 200: 3 queries, 2 duplicated`, a
  budget overrun reads `ran 28 queries against a budget of 8`, and
  `karni explain -` still recognises both the old and the new forms. A CLI
  error that ends in a command prints its docs link on the next line.
  Empty values show Django's `-` in the admin and `EmptyValue` in @karni/ui
  (`Select`'s default clear label and `DataChart`'s missing values). Tests in
  a project that match the old wording, or the old dash option label, need
  the new text.
- **Saving your prompts, suggested once.** The one-time tip in
  `karni doctor` and `karni check` now says what Gigai Chronicle is for (it
  keeps every prompt you give an agent, and `karni context --with-history`
  reads it back) and how to install it. It still says it is by Karni's
  author, still appears once per project, never in CI, and
  `karni config set suggest_tools false` silences it. The README, the AI
  guide and a new project's README mention it as optional.
- **AI visibility baseline.** `scripts/ai-visibility-check.md` records the
  first run (2026-10-22): Karni appeared in 0 of 10 questions with web
  search and 0 of 10 without, and a search for its own name found no Karni
  page yet.

- **Plainer wording across the docs, error codes, CLI help and agent files.**
  The documentation, the error code explanations and fixes, `karni --help`,
  the settings reference, the agent rules and procedures, and the header of
  the generated AGENTS.md and its siblings no longer use semicolons or em
  dashes, and read as plain sentences. No code, setting or command changed.
  Error code entries are headed `E104: title`. Run `karni rules sync` to
  pick up the new adapter wording. EventHub measures 619 lines of project
  code (the restore listener added 4).
- **Fixed: exporting a nested relation crashed.** A serializer that nests
  related rows (`many=True`, or `?expand=`) made CSV and XLSX exports fail
  with `TypeError: unhashable type: 'dict'`. Nested rows now export by the
  related model's natural key, the same as a plain relation.
- **Fixed: restoring a deleted row skipped its listeners.** New
  `karni.events.on_restored`, the counterpart of `on_deleted`. It runs inside
  the restore's transaction, so a listener that raises undoes the restore.
  `SoftDeleteModel.delete()` and `restore()` now run in a transaction with
  their listeners. The admin's delete and restore actions now go row by row,
  so `on_deleted` and `on_restored` run there too (they used one bulk
  `UPDATE` and fired nothing). A row a listener refuses is reported and the
  rest are restored. EventHub uses this to take a restored booking's seats
  again. A sold-out tier refuses the restore with E985.
- **Fixed: duplicate OpenAPI operation IDs.** `GET <resource>/import/` and
  `GET <resource>/import/{job}/` shared one ID, and so did the two
  effective-permissions routes, so generated clients got `_retrieve_2`
  names. A route that ends in a path parameter now gets `_by_<param>`, for
  example `events_import_by_job_retrieve`. Clients generated from the schema
  rename those two functions. The standard detail IDs do not change.
- **Fixed: booking one slot at the same moment could fail with a 500.**
  PostgreSQL sometimes settled several concurrent writes against a
  `no_overlap` constraint with a deadlock instead of the overlap error.
  Writes to one resource (one room, say) now take turns through a
  transaction-scoped advisory lock, so the second writer sees the first
  one's row and gets the 409 (E984).
- Query budgets no longer count `SAVEPOINT` statements or those advisory
  locks. They come from `transaction.atomic()` nesting and locking, not from
  reading data.
- **Typed fields: the database enforces what a value is (`karni.fields`).**
  `MoneyField` (NUMERIC(19,4), a declared currency, floats refused with
  `E962`, a declared rounding rule, and `quantize`/`split`/`allocate` that never
  lose a cent), `PercentField` and `QuantityField` (CHECK bounds),
  `EmailField` (unique on `LOWER(email)`), `SlugField` (generated,
  collision-free), `PhoneField` (E.164 CHECK), `CountryField`/`CurrencyField`
  (CHECK against shipped ISO 3166-1 / ISO 4217 lists), `JSONField(queried=True)`
  and `ArrayField` (GIN), and `SearchField` (a generated tsvector with a GIN
  index the default search provider matches through). Unique Karni fields and
  the new `LiveUniqueConstraint` are partial on soft-deletable models, so a
  deleted row frees its value. Every guarantee is proven with raw SQL on
  PostgreSQL and, where portable, SQLite. New checks: `E960` (a FloatField
  named like money fails boot), `W965` (CASCADE on a financial or audited
  model), `E964`/`W964` (a field or guarantee the configured database lacks),
  `W967` (a searched, filtered or ordered column without an index), plus
  `E961`, `E963`, `E968`, `E970`. `class Karni:` gains `append_only` (BRIN),
  `cascade`, `financial` and `not_money`. `karni schema` (`manage.py
  karni_schema`, `--json`) lists every column, constraint and index, why it
  exists and whether the database has it. `karni.accounts` 0005 creates
  `btree_gist`, and `CreateExtension` names the exact SQL (`E966`) when the role
  may not. `karni make model` gains `money[:EUR]`, `percent`, `quantity`,
  `email[:unique]`, `slug[:source]`, `phone`, `country`, `currency`,
  `json[:queried]` and `array:<type>` (`email`, `slug` and `json` now write
  the Karni fields). Rule K114. See [docs/fields.md](docs/fields.md).
- **Lifecycle columns and limited resources, enforced by the database**
  ([docs/lifecycle-and-capacity.md](docs/lifecycle-and-capacity.md)).
  `karni.fields.StateField(states=..., transitions=...)` declares a status
  column's states (a `CHECK` on the column) and its legal moves:
  `row.transition("status", "confirmed")` or assignment + `save()` is checked
  against the state the row was loaded with (`E980`, `E982`, a 400 in the
  API), written with a conditional `UPDATE ... WHERE status = <loaded>` so two
  concurrent transitions never both succeed (`E981`, a 409), recorded in the
  change log (action `transition`) and announced by
  `karni.lifecycle.state_changed` / `@on_transition`. The OpenAPI schema
  carries `x-karni-transitions` and `x-karni-initial`.
  `karni.fields.CapacityField(total=...)` is a counter the database keeps
  between zero and its total, consumed only with `karni.capacity.reserve()` /
  `release()` (a locked, conditional `UPDATE`, with `E985`, a 409, naming what
  is left). `class Karni: no_overlap = NoOverlap("room", "during", ignore=...)`
  adds a PostgreSQL `EXCLUDE USING gist` constraint (creating `btree_gist`
  when first applied) that ignores soft-deleted and released rows (`E984`, a
  409 naming the existing row). Off PostgreSQL it is not enforced and
  `karni.W980` says so. New: `karni.fields.DateRangeField` /
  `DateTimeRangeField`, `karni.models.GuardedModel` (part of `BaseModel`),
  `karni make model` types `state`, `daterange`, `datetimerange` and
  `capacity`, agent rules `K115` and `K116`, codes `E980`–`E988`, `W980` and
  `C370`–`C372`. EventHub's ticket tiers and bookings use them (619 lines of
  project code, measured).
- **`karni why`: an access decision explained by the code that makes it.**
  `karni why events/<id> --as alice@example.com [--action update]`,
  `karni why events.<field> --as ...`, `karni why-empty events --as ...` and
  `karni why 403 <request-id>` (a request the dev server recorded) print the
  user and roles, the grants that applied and where each comes from, the gate
  and every part of `read`/`write` against the row, the row's values
  (redacted like the change history), the result, `file:line` and one
  concrete fix. It adds `--json` for agents, `why`/`why_empty` on `karni mcp`,
  and rule `K015`. The verdict comes from running DRF's own gate and lookup in a
  rolled-back transaction while the access layer records its decisions
  (`karni.api.access.trace`). `Predicate.explain()` takes a predicate apart
  with the same folds `|` and `&` use. A test matrix checks the verdict
  against the API for every user, viewset, action and row of the test app.
  New: `karni.why`, `manage.py karni_why`, `BaseViewSet.base_queryset()`,
  `karni.vetoes.first_veto`, `karni.accounts.roles.grant_rows` /
  `grant_sources`, and codes `E901`–`E908`, `C310`–`C312`. See
  [debugging](docs/debugging/why.md).
- **Debugging: one request id everywhere, a development capture, and
  `karni trace` / `karni replay` / `karni explain --failure`.** Every
  request gets an id (`X-Request-ID` on the response, where a client's value is
  accepted only in development or from a trusted proxy,
  `KARNI_REQUEST_ID_TRUST_HEADER`) that follows its Celery tasks and their
  retries (a message header), its email (`X-Karni-Request-ID`), outgoing
  calls (`karni.tracing.outgoing_headers()`) and the change log
  (`ChangeLog.request_id`, `ChangeBatch.request_id`, migration
  `karni_audit.0003`). With `DEBUG` on, Karni writes `.karni/requests/`,
  `.karni/failures/` and `.karni/trace/` under the project, bounded
  (`KARNI_DEBUG_CAPTURE_KEEP`, `KARNI_DEBUG_TRACE_DAYS`) and redacted by
  the change log's rules plus known secret values. With `DEBUG` off nothing
  runs. `karni trace` follows a request through its async work in order,
  `karni replay [--as USER]` re-runs it against the current code (rolled
  back unless `--commit`), and `karni explain --failure` turns a crash into a
  brief. The same three are MCP tools and agent rules K030–K032. New codes
  E920–E924, W920, C320–C323. karni-payments links a webhook delivery to
  the checkout it settles. See [debugging](docs/debugging/capture.md).
- **Debugging: `karni explain -` and `karni queries`.** `karni explain -`
  reads a pasted traceback, test failure or log line (stdin) and names the
  Karni failure in it: a registered code, an agent rule, a query-count
  failure, a CSRF/CORS refusal, an access outcome or a documented
  framework-adjacent failure (driver, database, migrations, settings, Redis,
  OpenAPI), with the cause, the first project frame, the fix and the docs
  link, or says plainly that it does not recognise it. `karni queries
  <endpoint> --as <user>` runs one endpoint in-process (writes rolled back),
  records every SQL statement with its stack and groups the repeated ones by
  the serializer field and relation behind them, with the optimiser's reason
  and the exact hint (`--json`, `--explain`, `--all`). The optimiser now
  records its blind spots (`karni.api.optimizer.blind_spots`). MCP tools
  `explain_text` and `queries`, agent rules K013 and K014, and codes E940–E943,
  C340, C341. See [debugging](docs/debugging/explain.md).
- One brand across the welcome page, the admin and `@karni/ui`: the same
  colours in light and dark, radius, font stack and dark-mode switch (the
  `dark` class on `<html>`, following the system preference by default). The
  `karni` package ships `@karni/ui`'s token stylesheet as the static file
  `karni/tokens.css`, a byte-for-byte copy that a test keeps identical. The
  admin loads it through `UNFOLD["STYLES"]` with `karni/unfold-theme.css`.
  In the admin, unfold's primary scale and text colours now read the tokens (`@karni/ui`'s
  near-black primary in light mode, near-white in dark, replacing the indigo
  scale), its neutral scale holds the tokens' gray values, `BORDER_RADIUS` is
  `var(--karni-radius-md)` and the font is `@karni/ui`'s system stack instead
  of Inter. Retheme the admin like the frontend, with `--karni-*` overrides in
  a stylesheet appended to `UNFOLD["STYLES"]` ([admin](docs/admin.md#theming)).
  The welcome page inlines the tokens instead of its own palette. Karni's
  admin pages (import, permission matrix, effective permissions) share
  `karni/admin-pages.css`, with no colour literals and no dark-mode duplicates.
  On a tablet the matrix shows several roles beside a narrower model column,
  the template downloads and the effective-permissions link are 44px buttons,
  and on touch screens unfold's sidebar rows, inputs, selects and save buttons
  are 44px. The hard-delete confirmation uses unfold's layout and buttons (its
  buttons rendered as plain text). Account emails use the brand's colour values.
- `@karni/ui` forms: `ResourceForm` validates when a field loses focus (not
  per keystroke, and `validationMode` / `reValidateMode` change it), puts every
  DRF error shape on its field, shows a focusable summary when more than one
  thing fails, words 401/403/409/429/5xx and offline failures in a banner with
  "Try again", never loses typed input, shows a skeleton shaped like the form,
  "You can't edit this event" on a 403, disables the fields while saving
  (`PendingButton`), submits with Enter and Ctrl/Cmd+Enter, autofocuses on
  create, and wires labels, `aria-invalid`, `aria-describedby` and
  `aria-required` for every field kind. Unsaved changes: `beforeunload` while
  dirty (`guardUnsavedChanges`), `onDirtyChange`, and
  `useUnsavedChangesGuard` for a router's blocker. New `slots`
  (`defaultResourceFormSlots`), `submitLabel`, `autoFocus`, `resourceLabel`.
  Fixed: an empty optional email or URL field no longer blocks the submit, and
  a created form now starts over after saving (it kept the typed values).
  `ResourceSelect` pages through the API instead of showing one page (scroll,
  "Load more", keyboard), renders only the rows in view, keeps results while
  a search loads, says when search is unavailable, tells "no venues yet" from
  "no match", has loading, error, 403 and offline states, labels preselected
  ids in one `?id__in=` request where the API has it, never shows a bare id,
  forwards its ref and takes `onBlur`, `aria-*`, `slots`
  (`defaultResourceSelectSlots`), `searchable`, `idsFilter`. Input, Textarea,
  Select, Checkbox, Switch and FileUpload draw `aria-invalid` with the
  destructive tokens. `Select` and `FileUpload` take `aria-describedby`,
  `aria-invalid` and `onBlur`. A slow `PendingButton` keeps its accessible
  name. `useSchema` returns `refetch` and `isFetching`.
- `@karni/ui` unhappy-state kit: `describeError` words any failure in plain
  words (never a status code), `ErrorState`, `PermissionDenied`,
  `PendingButton` (progress after 500ms, keeps its width), `useDelayedFlag`,
  `useOnlineStatus`. Dark mode for apps: `ThemeProvider`, `ThemeToggle` and
  `KARNI_THEME_SCRIPT` (follows the system until the user chooses), and
  `karniTheme()` from the new `@karni/ui/vite` entry, which puts the script
  first in `index.html`'s `<head>`. A project from `karni new` has all of it
  wired, with the toggle in the sidebar footer.
- `karni ui detect`: adopts the frontend's design system as `@karni/ui`'s
  tokens, in one file the project owns (`karni-theme.css`, imported after
  `@karni/ui/styles.css`). shadcn/ui: every token references the project's
  own variable (`var(--primary)`, or `hsl(var(--primary))` for Tailwind 3
  HSL channels) on `:root, .dark`, and `karni-primitives.tsx` registers the
  project's shadcn components as Karni's primitives. Otherwise a Tailwind
  theme (`@theme`, or the `tailwind.config` Node evaluates), a Material UI,
  Chakra UI or Mantine theme (literal values read statically), or Karni's
  defaults listed for editing. The report lists every token mapped and every
  value not mapped with the reason (`--json` for agents, `--dry-run` to
  preview). An edited file is never overwritten without `--force`. New error
  codes C301-C304. `karni new` does not write the file (nothing to detect in
  a fresh project). See [docs/theming.md](docs/theming.md).
- `@karni/ui` ResourceDetail, ResourceImport, ChangeHistory, LoginForm and
  AuthGuard handle every unhappy state through the kit, each with `slots`
  (and `defaultXSlots` to wrap). ResourceDetail shows a loading placeholder in
  the record's own layout, header included (no layout shift). A 404 shows
  "Couldn't find this event" (worded so an out-of-scope record is not
  confirmed to exist) with a `back` action, and a 403 shows "You can't view
  this event". Retry refetches the schema when that failed, and offline
  reloads by itself. `title`/`actions` may be functions of the record. Edit
  and Delete come with `onEdit`/`canEdit`, `enableDelete`/`canDelete`/`onDeleted`
  (delete asks first and reports a refusal in the dialog). A field the role
  may not read has no row at all. An empty value is the new shared `EmptyValue` (an en
  dash read as "empty"), also used by ResourceTable (which now treats `""`
  as empty) and ChangeHistory. ResourceImport shows no form when the role may
  not import, keeps the file after a failed upload, confirms a commit with
  its counts, announces progress by the quarter, and its tables have
  captions and header scopes. LoginForm tells wrong credentials from
  throttling, server errors and a dropped connection, wires the message to
  the fields and focuses the email (`autoFocus`). AuthGuard can explain a
  refusal (`explain` gives a sign-in prompt for anonymous visitors and
  PermissionDenied for a role without access, and `anonymous`/`denied` replace
  one case). Deprecated: a guard with no `fallback` and no `explain` still
  renders nothing, as in 0.3, and warns once in development. Version 1.0 makes
  `explain` the default (`fallback={null}` keeps rendering nothing).
  Behaviour changes: a non-HTTP sign-in failure no longer reads as wrong
  credentials. ResourceDetail's empty dash is "–" (was "—"), and its error
  panel no longer shows a raw error message.
- `@karni/ui` primitive registry: `<KarniProvider primitives={{ button: Button,
  input: Input, select: {...} }}>` renders every Karni component with the
  project's own primitives (roles `button`, `input`, `textarea`, `checkbox`,
  `switch`, `label`, `skeleton` and the `select` family), keeping Karni's
  schema-driven behaviour. shadcn/ui's components fit the contract as they
  are. `KarniPrimitivesProvider` and `useKarniPrimitives` are exported.
- `@karni/ui` design tokens: every visual value in every component now
  resolves from a CSS custom property in `--karni-color-*`, `--karni-space-*`,
  `--karni-radius-*`, `--karni-font-*` or `--karni-shadow-*` (plus stacking,
  opacity, motion and line widths). The preset maps Tailwind's scales onto
  them, so one stylesheet rethemes every component. Colours take any CSS
  colour. Motion drops to 0ms under `prefers-reduced-motion`. New ESLint rule
  `karni/no-style-literals` and a test that compiles every component class
  keep literals out, and `npm run build` runs the lint. Every Storybook story
  renders pixel-identical before and after, light and dark. The 0.3 HSL
  triplet names (`--karni-primary`, ...) still work and are deprecated
  ([docs/migrations/0.4.md](docs/migrations/0.4.md)). ResourceDetail's section
  background now uses the shared `muted-subtle` shade (50% muted, was 40%).
- `@karni/ui` app shell, keyboard and screen readers: `Layout`, `Page`,
  `Modal`, `Toaster`, `EmptyState`, `Stat`, `DataChart` and `FileUpload` take
  `className` and `slots` (`slots={{ NavLink: RouterLink }}`), with exported
  slot contracts and `default*Slots`. `ModalTitle` and `ModalDescription` are
  exported. Layout's mobile drawer is a modal dialog (focus trapped and
  returned to the menu button, Escape closes, labelled) and the shell starts
  with a skip link. Nav links, SelectTrigger and the toast close buttons show
  a keyboard focus ring. Toasts are announced by urgency (errors assertive)
  and pause while hovered or focused. FileUpload announces refused files,
  takes `error`, `uploading`, `aria-invalid`, `aria-describedby` and
  `aria-labelledby`. DataChart is focusable (the arrow keys read point by
  point), gets a generated summary and `loading`, and keeps its axis labels
  legible on phones. Stat takes `loading`, and a zero delta reads "Unchanged"
  (it read "Increased by +0"). `Input`, `Textarea`, `SelectTrigger` and
  `Checkbox` show a destructive border under `aria-invalid`. Contrast: token
  values change so every pair the components use reaches WCAG AA in both
  themes (in light `muted-foreground`, `destructive`, `input`, `chart-2` and
  `chart-3`, in dark `destructive`, `destructive-foreground` and `input`), checked by
  a new test, and the dark theme's modal and drawer scrim dims the page (it
  lightened it). axe-core runs over every Storybook story in both themes in
  CI (WCAG 2.x A and AA) and fails the build on any violation. A story turns
  one rule off only with a written reason. Dialogs are never taller than the
  viewport (they scroll inside), and a busy pagination button keeps its name.
- `@karni/ui` ResourceTable in every state and at real size. Each state is its
  own screen and a replaceable slot (`slots`, `defaultResourceTableSlots`):
  a loading outline of the real layout (nothing moves when data arrives),
  "No events yet" with the create action (`onCreate`, `createLabel`) apart
  from "No events match" with "Clear filters", errors in plain words with a
  retry, a failed refresh that keeps the rows, "You can't view events" for a
  403 (4xx are no longer retried, except 408 and 429. Anything else retries as
  the app's QueryClient `retry` default says, so `retry: false` shows the
  error at once), offline, and progress
  after 500ms with controls that do not double-fire. Row actions follow the
  schema's `x-karni-access` rules for the signed-in user (`canCreate`,
  `canEdit`, `canDelete` override). Delete failures are reported (row delete
  now confirms in a dialog instead of `window.confirm`). Bulk actions confirm
  destructive work with the count, may return `{ failed: [{ id, reason }] }`
  to mark failed rows, and show progress. Page, page size, sort, search and
  filters live in the URL (namespaced, and Back works), with `syncUrl`,
  `urlNamespace` and `stateStore` for a router. There is a page size
  choice, first/last and jump to page. Wide tables scroll in their own box with
  a sticky header and a frozen first column. Compact rows and hidden columns
  are remembered per user. Below `cardBreakpoint` (the table's own width), rows
  render as cards. Rows open
  from the keyboard, checkboxes are named after their row, and page, sort,
  selection and loading changes are announced. The parsed schema now carries
  each operation's `access` rule. Changed wording: the empty screen says "No
  events yet" (was "Nothing here yet"), the select-all checkbox "Select all
  events on this page", row checkboxes "Select <row>", filter "All" items
  "Status: All", and list errors read like every other error ("Something went
  wrong on our side", "Try again").
- The README opens with why Karni exists, then says what problem it solves,
  how, what you get and what you still write. The canonical description now
  leads with the same framing (your agent writes only your domain, and the rest
  is a package you upgrade) on the GitHub About, PyPI, npm, the docs homepage,
  the FAQ and llms.txt. `scripts/check_description.py` also checks the FAQ's
  first answer and the README's first two sections (order, the story's
  180-word limit, the four answers in order, no marketing words), and writes
  the homepage's description quoted.
- All five Python packages (`karni`, `karni-cli`, `karni-payments`,
  `karni-approvals`, `karni-impersonation`) are on PyPI (0.3.1). The README's quickstart installs them with a plain `pip install`.
- **Security: a row outside the requester's row scope stays hidden on every
  response.** An audit probed row-scope denials (a user who may list a
  resource but not one row in it). The row itself was already treated as
  missing everywhere (404 on detail and the write verbs, absent from lists,
  filters, search, ordering, exports and the admin). Four paths leaked
  *related* rows and are fixed:
  - A write's response (`PATCH`/`PUT`/`POST …?expand=`), and any response of
    a viewset with `optimize = False` or a `select_related` /
    `prefetch_related` hint, embedded related rows (and listed to-many ids)
    outside the target's read scope. The generated serializers now check
    related rows at render time (`karni.api.related`): no extra query on the
    optimised path, one per related model and page otherwise.
  - An export named an unreadable related row by its natural key (a venue's
    name where the API shows only its id). It now keeps the id, and the
    admin's export names related rows as far as the admin's row scope shows
    them.
  - `?ordering=` on a to-many relation repeated each row once per related
    row, readable or not (and pushed others off the page), and on a forward
    relation sorted by the related model's `Meta.ordering`. Behaviour change
    for API clients: to-many and reverse relations are no longer orderable
    by default, and `?ordering=<relation>` sorts by its key column. An
    explicit `ordering_fields` is unchanged.
  - A relation in explicit `filterset_fields` filtered by the key of a row the
    requester cannot read (200) but refused a missing one (400). Its choices
    are now the readable rows (`KarniFilterSet`), so both answer 400.
- `karni.testing.assert_row_hidden(client, "/api/events/", row, visible=…)`
  proves in one line that a row outside the client's row scope behaves as
  "does not exist" on every API surface: detail and write verbs (compared
  with a missing key), detail actions, the list and its count, filters,
  search, ordering, `?expand=` and id lists from every related resource
  (writes included), and every export format.
  `assert_admin_row_hidden(staff, row, visible=…)` does the same for the
  admin's changelist, change, history and delete views. Each check runs on
  its own (`checks=["export"]`), `probe=` takes a `HiddenRowProbe` subclass,
  and a run that proves nothing (the client cannot list, or sees no row)
  fails with the new code `E616`. `assert_isolated` now runs the same probe on
  the other principal's row (and probes PUT, where a 403 on a write passes only when
  a missing row gets 403 too), so tests `karni make test` writes get it
  without a change.
- `karni check` exits 1 when only eslint fails (a raw `<table>` in a page, any
  `karni/*` rule). It printed `FAILED` but exited 0, so CI let it through.
- `karni` commands no longer end in Django's traceback when the project's
  database is not ready. On the host, a command that starts Django first
  checks that the database driver loads, and one that opens the database
  (`migrate`, `seed`, `sync-roles`, `createsuperuser`, `serve --local`,
  `test`, `beat`, `manage`) that the server answers. A missing driver is
  `C012` (install `psycopg[binary]` into the project interpreter, or use
  Docker) and an unreachable database is `C013` (with the address, the
  driver's error, and a note when `.env` is missing or `db` is the compose
  host). Captured commands (`karni context`, `karni types`) are checked only
  after they fail, so they cost nothing when the project works.
  `KARNI_DB_CHECK=false` skips the check. `karni check` still runs the
  frontend checks when the backend cannot start.
- Releases can publish npm with an `NPM_TOKEN` repository secret instead of
  trusted publishing, like `PYPI_API_TOKEN` for PyPI ([releasing](docs/releasing.md)).
- The `karni` command as a container image, `ghcr.io/cbsshekhawat18-lab/karni`
  (linux/amd64 and arm64), built from the PyPI release after every release
  and listed under the repository's Packages. It runs the CLI on machines
  without Python 3.12: `docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/work"
  ghcr.io/cbsshekhawat18-lab/karni new "Ticket Shop"`.
- `karni`, `karni-cli`, `karni-payments` and `karni-approvals` are on PyPI
  (0.3.1). The README's quickstart installs them with a plain `pip install`.
  Installing from a checkout is for unreleased changes only.
- `@karni/ui` and the three module UIs are on npm (0.3.1). The README's
  quickstart installs the frontend with a plain `npm install`, and `karni new`
  no longer says `@karni/ui` is unpublished.
- Tailwind 4 for new projects: `karni new` sets up Tailwind 4 through
  `@tailwindcss/vite`, loading the same `@karni/ui` preset with `@config`, and
  Vite 8. New `@karni/ui/tailwind-v4.css`, imported after Tailwind in a
  Tailwind 4 project, keeps a bare `border` on the `--karni-border` token.
  `@karni/ui` keeps working with Tailwind 3: every Storybook story (light and
  dark) and every page a new project generates render pixel-identical under
  Tailwind 3 and 4. The form and sign-in field gaps no longer use `space-y`
  (Tailwind 4 moved its margin onto the inline label, which ignores it).
- Development tooling: Vite 8, Vitest 5, Storybook 10 (with
  msw-storybook-addon 3) and Tailwind 4 in `@karni/ui` and the module UIs.
  CI and releases run on Node 24 (Node 20 is out of support, Vitest 5 needs
  22.12 or later, and npm trusted publishing needs npm 11.5). The Pages and
  artifact actions are on their current majors. `npm audit` reports nothing, dev
  dependencies included.

## 0.3.1 (2026-10-20)

A patch release: security updates to the development tooling, Vite 6.4 for
new projects, and publishing to PyPI. No public API changes.

- The release workflow publishes to each registry separately:
  `KARNI_PUBLISHING` names the registries that are set up (`pypi`, `npm`,
  `pypi,npm` or `true`), and PyPI uploads one project at a time, core first,
  with `skip-existing`, so a missing trusted publisher cannot half-publish a
  release. The GitHub release carries the npm tarballs too.
- Development tooling upgraded, closing every Dependabot alert (52, all in
  build and test tools, none in what the packages ship): Vite 6.4, Vitest 4.1
  (which drops tinypool), vite-plugin-dts 5 (API Extractor, and with it
  sprintf-js, is no longer installed), typescript-eslint 8 in the module UIs,
  and overrides for `uuid` (Storybook 8) and `postcss-selector-parser`
  (Tailwind 3). New projects get Vite 6.4 and the same override. The
  generated type declarations and Tailwind's output are unchanged. Vitest 4
  hands a jsdom `FormData` to Node's fetch without file names, so the UI test
  setup restores them the way a browser sends them.

## 0.3.0 (2026-10-20)

See [docs/migrations/0.3.md](docs/migrations/0.3.md) for the two breaking
changes and how to upgrade.

- Membership scoping and generated tests, from the social-leads practice project:
  `own` takes an owner path through a many-to-many
  (`owner_field = "workspace__members"`), now documented as the way to scope
  rows to a workspace's members. The test factories accept one row for a
  many-to-many, so `assert_crud` and `assert_isolated` drive it. A new
  check, `E214`, resolves every path a role's grants filter on (owner paths,
  scope paths, custom scopes) at boot, so a scope that names a missing path
  fails `karni check` instead of answering 500. `karni make test` says, in
  its output and the test file, why it leaves `assert_isolated` out.
- Django 5.2 LTS: karni requires `Django>=5.2.8,<5.3` (5.1 is out of
  support, and pip-audit reported ten unpatched advisories against 5.1.15) and
  django-unfold 0.110. Python 3.14 is supported and tested. On Django 5.1,
  every admin page failed under 3.14. Projects pinned to Django 5.1 upgrade
  Django with karni. No project code changes were needed in EventHub,
  Social Leads or the modules. Dropping Django 5.1 is a minor-release
  change under the [stability promise](docs/stability.md), released as 0.3.0.
- `karni seed` can run again on a seeded database. Each run is a new process
  that draws the same UUID keys from the same seed, so a second run failed
  with `E612` on the primary key (found by running the README quickstart, then
  adding a model and seeding again). A key an earlier run used is now replaced
  by one derived from it. An empty database still gets the same rows.
- A generated reference: `scripts/gen_reference.py` writes `docs/REFERENCE.md`
  (every command, base class, `class Karni` key, setting, component, hook,
  module, error code, make target and slash command, with each capability's
  status) and the README's generated blocks from the source, and CI fails when
  either is stale. `karni.meta.OPTIONS` (and a module's `KARNI_OPTIONS`) now
  documents each `class Karni` key, and the generator fails on a key that code
  reads but no list declares. Every `@karni/ui` export has a one-line JSDoc.
- The README is rewritten: a demo recorded from a real quickstart run
  (`scripts/demo/`), a cheat sheet, the generated command table and per-area
  reference, an honest comparison and status. The quickstart (README and
  docs) adds `karni make page login --kind login`: a new project had no
  sign-in page for the React app. Package READMEs link absolutely, so their
  links work on PyPI.

## 0.2.0 (2026-10-20)

See [docs/migrations/0.2.md](docs/migrations/0.2.md) for every breaking
change and its migration note.

- Roles as data: `KARNI_ROLES`, `karni sync-roles`, `user.can()`,
  `@requires()`, `Can("app.model:action")` in `access` declarations
  (ADR 0002).
- Row-level scoping (ADR 0002, P2): `access = Granted()` is the default
  `karni make viewset` writes and scopes rows by the roles' grants. The
  admin shows only the rows the user's grants reach. `scope_exempt` takes a
  reason that `karni check` lists. `assert_isolated` gains the `grant`
  dimension and probes expansion, filters, search, ordering and the admin.
- Welcome page: `/` on first boot (`karni.welcome.welcome_urls()`, mounted
  last by the scaffold) shows the project live: models with admin and API
  links, modules, seven status checks each with the command that fixes a
  cross, the `karni context` output and the first agent prompt. It is `DEBUG`
  only and gone once the project owns `/`, and `karni.E505` guards production.
- Field-level visibility (ADR 0002, P3): `class Karni: field_roles` hides
  fields per role on the API (absent, never `null`), in `?expand=`, in the
  per-role OpenAPI schema and in the admin. Write-protected fields are
  refused naming the roles that may. `?ordering=`, filters and `?search=`
  ignore hidden fields. `@karni/ui` refetches the schema on identity
  change. `assert_crud` checks visibility. `?ordering=` now accepts only
  serializer-visible fields, `search_fields` may not name a write-only
  field (`E131`), and `E212` validates `field_roles`.
- Change history (ADR 0002, P4): the `karni.audit` app records, for models
  that opt in with `class Karni: audit = True`, who changed what from what
  to what, captured at the model layer so the API, admin, commands and the
  shell all leave the same entry. Sensitive fields are redacted. The history
  shows on the admin History tab, `GET /<resource>/<id>/history/` and
  `<ChangeHistory/>`. Retention pruning is off by default. `karni check` flags
  `update()`/`bulk_update()` on audited models (`audited-bulk-write`, `K113`).
- Permission matrix (ADR 0002, P5): Roles → *Permission matrix* in the
  admin changes who may do what with no deploy (roles across, models down,
  a scope selector per action, bulk selectors, a confirmation diff), with
  the guard rails (system roles keep their declared grants, nobody grants
  what they do not hold, nobody removes their own last permission to change
  permissions) and the matrix's own change history. *Effective permissions*
  answers "why can this person see this?" per user. The same is available as
  an API under `api/auth/permissions/` for custom UIs, fixtures and tests
  (`E213`). `RolePermission.origin` tells the sync which grants the matrix
  owns. Also new: `KARNI_MATRIX_EXCLUDE`.
- Import and export (ADR 0002, P6): `GET /<resource>/export/?format=csv|xlsx`
  on every resource (the list as the request sees it, filters and scope and
  field visibility included, relations as natural keys) and a four-step
  import (`/<resource>/import/…`): upload, map columns (remembered per model
  per user), the mandatory dry run with exact counts and per-row errors,
  then one transaction recorded as one audit batch. Large files run in
  Celery with progress. Per-model hooks live in `class Karni` (`natural_key`,
  `import_key`, `import_lookup`, `import_transform`, `after_import`), and
  there is a downloadable template per model. Every Karni admin gets export
  actions and an Import page, and `@karni/ui` gets `<ResourceImport/>` and
  export buttons on `<ResourceTable>`. Settings `KARNI_IMPORT_INLINE_ROWS`,
  `KARNI_IMPORT_MAX_ROWS` and `KARNI_EXPORT_MAX_ROWS`, codes `E801`–`E803`.
- Write interception: every `BaseModel` save and delete sends
  `karni.signals.pre_write`. A receiver that raises `KarniWriteDeferred`
  stops the write before any SQL: the API answers 202 with its payload, and
  the admin shows its message. The hook behind the new `karni-approvals`
  module (M1): `class Karni: requires_approval = [...]` turns a maker's
  guarded change into a pending change a second person approves or
  rejects (never the maker, in code), with per-model approvals count,
  approver roles and timeouts, an admin queue, `/api/pending-changes/`,
  Celery notifications, every decision in `karni.audit`, and
  `@karni/approvals-ui` (`<ApprovalsQueue/>`, `<ApprovalsBadge/>`).
- Vetoes: `karni.vetoes.register_veto` refuses an action at the API and
  admin gates after the access declaration admitted it (a maintenance
  freeze, a read-only tenant), plus `KarniAdminMixin.vetoed()`. The hook behind
  the new `karni-impersonation` module (M2): "log in as user" for support
  with an explicit `impersonate` permission never implied by staff status,
  no privilege escalation (a target holding anything the actor lacks is
  refused), a banner naming both identities with a one-click exit, a
  session record, every write attributed to both identities in
  `karni.audit` (the row's actor is the target, the batch's actor the
  impersonator), a configurable time limit, a hard block on deleting,
  exporting and payment changes while impersonating, the target notified
  and a reason required by default, a threat model in the README. Also new:
  `karni.audit.capture.within_batch`, `@karni/impersonation-ui`
  (`<ImpersonationBanner/>`) and `useAuth().adoptTokens` in `@karni/ui`.
- `karni check` and the architecture suite now scan a project's apps
  without `BASE_DIR` (the audit's "enforcement scans zero files" finding).
- The launch audit's remaining findings: `karni migrate` creates `pg_trgm`
  (`?search=` no longer 500s on a fresh PostgreSQL). `KARNI_CACHE=locmem`
  runs a project without Redis and the quickstart uses it, with pytest in
  its install line. `karni.welcome.media_urls()` serves uploads in
  development. Also fixed: `karni --version`, `karni doctor` with the venv
  outside the project, and `karni context` (and the MCP `context` tool) from
  the interpreter running karni-cli. `karni serve`/`karni worker` pass SIGTERM
  on to the server. `karni test` says when pytest is missing (`C011`).
  `karni check` runs the frontend's ESLint next to jscpd. The scaling check
  also measures every list with `?expand=`. A `KARNI_*` dotted path that
  cannot be imported is `E506` naming the setting (`E507` for `KARNI_CACHE`).
  Generated detail pages expand their relations. A required relation left
  empty says "Required" and an optional one clears. A new project's pyproject
  has `[tool.karni] baseline`, so `karni upgrade` never reports changes a fresh
  scaffold already satisfies. `LOGIN_REDIRECT_URL` defaults to the admin.
  The seed login says "superuser". The two schema warnings are gone. The
  cosmetics too: choice labels from the schema's choice list instead of raw
  markdown help text (`FieldDef.enumLabels`), one casing for every table
  header, `karni rules` trimmed (402 cl100k tokens, measured), and the
  admin's *All* rows counted once. The EventHub Playwright journeys ran
  (three passed) and every package built, installed into a clean venv and
  dry-run published.
- Every `BaseViewSet` declares `access`. Relation fields and `?expand=`
  follow the target's read scope. Query budgets fail tests.
- Errors that teach: every error carries a code, `karni explain <code>`,
  the generated error reference.
- `karni make …` generators and the project runners (`karni serve`,
  `migrate`, `test`, `seed`, …), and `karni upgrade` with codemods.
- The documentation site, the EventHub reference application, release
  automation, the brand assets.

## 0.1.0

The first cut: `BaseModel` and scopes, the `access` declaration, generated
serializers and viewsets, the derived admin, accounts, events and schedules,
`@karni/ui`, the scaffold and the agent adapters.
