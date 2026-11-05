---
description: What counts as Karni's public API, how semantic versioning applies from 0.1.0, and the deprecation cycle every breaking change goes through.
---

# Stability promise

Karni is a dependency you upgrade, not a template you copy, so what may
change, and when, is part of its design. This page defines what counts as
public API and what Karni promises about it.

## Versioning

Karni uses [semantic versioning](https://semver.org), starting at 0.1.0.
Every published package moves in **lockstep**: one release tag publishes
`karni`, `karni-cli`, `karni-payments`, `@karni/ui` and `@karni/payments-ui`
at the same version ([releasing](releasing.md)).

| Release | May contain |
|---|---|
| Patch (`0.2.1`) | Bug and security fixes only. No public API change, no new deprecation. |
| Minor (`0.3.0`) | New features and deprecations. Before 1.0, also breaking changes, always under the rules below. |
| Major (`1.0.0`, `2.0.0`) | Removal of anything deprecated in an earlier minor. |

## The promise

For everything listed as public below, except the names marked
[experimental](#experimental-names):

1. **Nothing breaks without warning.** A public name is deprecated for at
   least one minor release before it is removed. While deprecated, it keeps
   working and raises a `KarniDeprecationWarning`. The warning names the
   release that removes it and links the migration note. Removal happens in
   the next major release. This applies in 0.x as well: the names 0.2
   deprecates are removed in 1.0, not in 0.3.
2. **Every breaking change is recorded.** Each one is an entry in Karni's
   machine-readable changelog (`karni/changelog/<version>.toml`) and has a
   section in the migration notes ([0.5](migrations/0.5.md), [0.4](migrations/0.4.md), [0.3](migrations/0.3.md), [0.2](migrations/0.2.md), [1.0](migrations/1.0.md)).
3. **Mechanical changes are applied for you.** When a change can be made
   safely by rewriting code (a renamed import, setting, base class or method),
   it ships with a codemod. `karni upgrade --to <version>` runs every codemod
   between your version and the target, shows the diff (`--dry-run`), and
   lists what it could not change, with file and line.
4. **Security fixes reach the latest minor release.** The supported versions
   are listed in [Security](security.md).

A rare exception: if a security fix cannot be made without breaking a public
API, the fix ships anyway. The release notes and the migration note say so,
and a codemod or detector is included where possible.

## What is public API

### Python (`karni`, `karni-payments`)

- **Every name in a module's `__all__`**, imported from the module that
  declares it: for example `karni.models.BaseModel`,
  `karni.api.access.Owned`, `karni.testing.assert_crud` and
  `karni.seeding.Seeder`. Names not in `__all__` are internal, even when
  importable.
- **Documented overridable methods and attributes** of public classes,
  meaning the escape hatches named in their docstrings and in the docs
  (`get_queryset` hooks, `access`, `optimize`, `Meta` options, seeder
  `seed()`, and so on). Their signatures are public.
- **Settings:** every documented `KARNI_*` setting, its meaning and its
  default. Changing a default is a breaking change.
- **Project file conventions** Karni discovers by name: `<app>/listeners.py`,
  `<app>/events.py`, `<app>/schedules.py`, `<app>/seeds.py`,
  `<app>/factories.py`, `<app>/tasks.py`.
- **Entry-point groups:** `karni.settings` (module settings fragments),
  `karni.checks` (architecture checks) and `karni.history_providers`
  (agent history providers), plus the `pytest11` plugin.
- **The REST API contract Karni generates:** URL shapes, the query
  parameters (`?expand=`, `?search=`, filters, ordering, `page`,
  `page_size`), response envelopes and status codes, including the 404
  out-of-scope and 403 read-but-not-write rule of `access`.
- **Error codes.** A code (for example `E012`) keeps its meaning forever.
  Codes are never renumbered or reused. Message wording may improve in any
  release, so match on the code, not the text.
- **Database schema of Karni's own models** (accounts, module models).
  Changes always come with a migration.

### TypeScript (`@karni/ui`, `@karni/payments-ui`)

- Everything exported from the package root (`@karni/ui`): components, their
  documented props, hooks and types.
- The subpath exports in `package.json`: `@karni/ui/styles.css`,
  `@karni/ui/tailwind-preset`, `@karni/ui/tailwind-v4.css`, `@karni/ui/eslint-plugin` and
  `@karni/ui/manifest.json`.
- ESLint rule ids (`karni/no-raw-elements`, …) and what each forbids.
- Deep imports (`@karni/ui/dist/...`, `src/...`) are internal, and the
  ESLint plugin flags them.

### The `karni` command (`karni-cli`)

- Command names, arguments and flags, as listed in [the CLI
  reference](cli.md). `karni make:<type>` aliases are public too.
- **Machine-readable output** (`--json`, `karni context`, `karni rules`,
  `karni routes --json`). Fields are only added, never renamed or removed,
  within a major release.
- Exit codes: 0 for success, and non-zero for failure with the reason on
  stderr.
- The **files `karni make` generates** and their layout, because projects
  and agents rely on where code goes. The generated *content* may improve.
- `karni_cli` as a Python import is internal. Only the command line is
  public.

### Agent guidance

- Rule codes (`K001`, …) and what each enforces.
- The adapter files `karni rules sync` writes (AGENTS.md, CLAUDE.md,
  `.cursor/rules/karni.mdc`, …). Their wording changes between releases, so run
  `karni rules sync` after upgrading.

## What is internal

- Anything whose name starts with `_`: modules, functions, attributes.
- Anything not in `__all__`, not documented, or documented as internal.
- `karni.agent` internals other than the history-provider interface
  (`karni.agent.history`).
- Test-suite helpers inside Karni's own repository (`tests/` packages).
- The exact SQL Karni emits, query counts (query *budgets* are public), log
  message wording, and admin template markup.
- The scaffold's templates (`templates/project/`). They generate *your*
  files, and changing them never changes an existing project. Project-level
  migrations, where needed, ship as `karni upgrade` codemods.

## Experimental names

A new public name can ship as **experimental** first. An experimental name is
public and documented, but it may change or be removed in a minor release
without the deprecation cycle above. Every such change is noted in the
[CHANGELOG](https://github.com/cbsshekhawat18-lab/karni/blob/main/CHANGELOG.md)
and in the migration notes of that release, so an upgrade never changes one
silently.

A name is experimental only when it is marked, and the mark is visible
wherever you meet the name:

- its docstring (Python) or doc comment (TypeScript) starts with
  `Experimental.`,
- the docs section that describes it opens with an *Experimental* note,
- its capability in the [reference](REFERENCE.md#capabilities-and-status)
  has the status `experimental` and says *Experimental tier*. The status
  `experimental` alone only means that no reference application uses the
  capability yet: those names keep the promise.

Some parts never become experimental. An error code keeps its meaning forever
and is never reused, also for an experimental feature. A change to the
database schema of an experimental model always comes with a migration.

An experimental name becomes stable in a minor release, once a reference
application uses it. The CHANGELOG entry of that release says so, and from
then on the promise above applies in full.

Experimental now:

- [Sign-in with an ID token (Google, Microsoft, Apple)](accounts.md#sign-in-with-an-id-token-google-microsoft-apple):
  the `social/<provider>/` endpoint, the `KARNI_SOCIAL_TOKEN_*` settings,
  `karni.accounts.social_token`, the `SocialIdentity` model, and
  `useSocialLogin` and `SocialButton` in `@karni/ui`.
- [Sign-in with a code sent by email](accounts.md#sign-in-with-a-code-sent-by-email):
  the `otp/send/` and `otp/verify/` endpoints, the `KARNI_EMAIL_OTP*`
  settings, the `auth.otp_*` throttle scopes, `karni.accounts.otp`, the
  `LoginCode` model, `karni.accounts.services.prove_address`, and
  `useOtpLogin`, `OtpLoginForm` and `LoginForm`'s `codeSignIn` in `@karni/ui`.
- [Terms acceptance](accounts.md#terms-acceptance): the `terms/` and
  `terms/accept/` endpoints, the `KARNI_TERMS` setting, `karni.accounts.terms`
  (with `TermsGateMiddleware`), the `TermsAcceptance` model, the `terms` field
  of `me/`, the client's `onError` hook, and `TermsGate` and `useAuth()`'s
  `terms`, `termsRequired` and `acceptTerms` in `@karni/ui`.
- [Integer primary keys](models.md#choosing-the-key-type):
  `karni.models.BigIntBaseModel` and `IntegerKeyModel`, the `KARNI_PK`
  setting, `karni make model --pk`, `karni.api.filters.IntegerFilter`, the
  import options `match_ids` and `keep_ids` (with the `ImportJob` fields of
  the same names), and the `KEYS:` line of `karni context`.
- [External tables, views and a second database](models.md#external-tables-views-and-a-second-database):
  the `class Karni` options `external`, `writable` and `database`, `karni.db`
  (with `DatabaseRouter`, `karni.db.checks` and `karni.db.introspection`),
  `BaseViewSet.is_read_only` and `read_only_refused_actions`,
  `KarniModelAdmin.is_read_only`, `assert_crud`'s `read_only`,
  `karni.testing.create_external_tables`, the pytest option
  `--karni-external-tables`, `manage.py karni_inspect` and `karni make model
  --external`.
- [Per-user grants](accounts.md#per-user-grants): the `KARNI_USER_GRANTS`
  setting, the `UserGrant` model, `karni.accounts.grants`, the `targets` and
  `grant_id` of `karni.accounts.roles.Grant` and the user-grant fields of
  `GrantSource` and of the effective permissions, the `permissions/grants/`
  endpoints, the grants inline and admin (`karni.accounts.admin.grant_form`),
  and `features: user_grants` in `karni.yaml`.
- [Search across models](global-search.md): the `class Karni` option
  `search`, `karni.global_search`, `karni.api.global_search` (with
  `GlobalSearchView`, `search_queryset`, `search_targets` and the `TITLE`,
  `SUBTITLE` and `SCORE` annotations), the `GET /api/search/` endpoint and
  its response, `BaseViewSet.global_search_queryset`,
  `karni.fields.TrigramIndex`, the `KARNI_GLOBAL_SEARCH_*` settings, the
  `x-karni-search` schema extension, the entity key `global_search` of
  `karni.yaml`, `SearchResource` and the typed `useGlobalSearch` of `karni
  types`, and `GlobalSearch`, `useGlobalSearch`, `karniKeys.search` and
  `Layout`'s `search` in `@karni/ui`.
- [The app spec](app-spec.md): the `karni.yaml` format and its JSON Schema,
  `karni spec validate`, `karni spec export`, `manage.py karni_facts`,
  `karni.facts` and the `karni_cli.spec` package.
- [Clarifying questions](app-spec.md#questions): `karni plan --questions`
  (its `--max`, its `--json` output and schema, the question ids and the
  rules that choose them), `karni spec answer`, `karni_cli.spec.questions`
  and `karni_cli.spec.edit`.
- [`karni build`](app-spec.md#karni-build): the command, its `--json` output
  and schema, the layout of the files it writes (`<app>/karni/`,
  `<app>/tests/karni/`, `frontend/src/pages/karni/`, the `karni:spec`
  blocks), `.karni/build.json`, `manage.py karni_makemigrations` and the
  `karni_cli.builder` package.
- [Aggregations](aggregations.md): `class Karni: aggregate`, the viewset's
  `aggregation`, `get_aggregation()` and `aggregate_queryset()`, the
  `aggregate` action, its parameters and response, `karni.aggregation` (with
  `Aggregation`, `TextNumber` and `run_aggregate`), `karni.api.aggregate`,
  `x-karni-aggregate`, the `KARNI_AGGREGATE_MAX_GROUPS` setting,
  `karni.testing.performance.aggregate_query`, the `use<Resource>Aggregate`
  hooks `karni types` writes, and `useAggregate`, `aggregateKey`,
  `buildAggregateQuery`, `aggregateSeries` and DataChart's `aggregate` and
  `stacked` in `@karni/ui`.
- [Saved charts](charts.md): the karni-charts module (the `Chart` model and
  its admin, `/api/charts/` and its `data` action, `karni_charts.services`,
  `KARNI_CHARTS_READ`, the `CHART` codes' wording) and `@karni/charts-ui`
  (`SavedChart`, `useSavedChart`, `savedChartKey`, `savedChartQuery`).
- [Page blocks](ui.md#page-blocks-experimental): `DashboardGrid`,
  `DashboardCard`, `ChartCard`, `DataTable`, `ComparisonTable`, `Accordion`,
  `MarkdownView` (with `preloadMarkdown`), `useResourceCounts`, their slots,
  props and types, ResourceDetail's `related` prop and `Related` slot, the
  `RelatedDef` schema type, the `--karni-dashboard-gap`,
  `--karni-data-table-max-height` and `--karni-data-table-row-height` tokens,
  the `x-karni-related` OpenAPI extension and
  `KarniAutoSchema.get_karni_related`, the spec's `{detail: {related: [...]}}`
  and dashboard pages other than `home`, `karni make page --kind dashboard`
  (`--count`) and `--related`, and the `components` key of `karni ui detect
  --json`.
- [Field groups and column sets](ui.md#field-groups-and-column-sets-experimental):
  `karni.fields.MarkdownField` (and its `markdown` type in `karni make
  model` and the spec), `karni.api.formats` (`FormattedCharField`, a model
  field's `openapi_format`), the `class Karni` options `field_groups`,
  `field_group_layout` and `column_sets`, `karni.layout`, the
  `x-karni-field-groups` and `x-karni-column-sets` OpenAPI extensions with
  `KarniAutoSchema.get_karni_field_groups` and `get_karni_column_sets`,
  `KarniAdminMixin.derive_fieldsets`, the spec's entity `groups` (now
  `Karni.field_groups`) and `column_sets`, the `fieldGroups` and
  `groupLayout` props of ResourceForm and ResourceDetail, ResourceTable's
  `columnSets`, `columnSet` and `onColumnSetChange`, and the `FieldGroupDef`,
  `FieldGroupLayout`, `FieldGroupsDef`, `ColumnSetDef` and `ColumnSetsDef`
  types in `@karni/ui`.
- [AI extraction](ai-extraction.md): the karni-ai module (`karni_ai`, its
  `POST /api/ai/extract/` endpoint and answer, `/api/ai/`, the `AICall`
  model, the `KARNI_AI_*` settings and the providers' `ANTHROPIC_*` and
  `OPENAI_*` settings, the `ai.extract` throttle scope, `karni_ai.providers`,
  `karni_ai.extraction`, `karni_ai.schema`, `karni_ai.sources`,
  `karni_ai.services.fetch`, `karni_ai.usage`) and `@karni/ai-ui`
  (`ExtractButton`, `ExtractPreview`, `useExtract`).
- [The module catalog](modules.md#the-module-catalog): the `karni.module.toml`
  manifest format and the feature manifests, the `karni.modules` entry point
  group, `karni.catalog` (with `python -m karni.catalog`),
  `karni.testing.assert_module_manifest`, `karni modules list` and `show`,
  `karni remove`, the `CATALOG:` lines of `karni context`, the `FEATURES:`
  line of `manage.py karni_context`, and `karni_cli.catalog`.
- [The /new-app flow](agents.md#agents-the-new-app-flow): the `new-app`
  procedure and rule K311, [recipes](app-spec.md#recipes) (`karni recipes
  list` and `show`, `--match` and its ranking, the blank start, the
  `recipe.toml` format and its schema, the `karni.recipes` entry point group,
  `karni recipes --json` and its schema, `karni_cli.recipes`), and [the MCP
  tools](app-spec.md#mcp-tools) `recipes`, `spec_validate`, `questions`,
  `answer`, `plan`, `build` and `modules` with their results' schema
  (`karni_cli.agent_tools`).
- [The built-in recipes](recipes/index.md): `shop`, `booking`, `crm`, `lms`
  and `marketplace` (their specs, files and names), `karni new --recipe`,
  the `recipe` key of `.karni/build.json` (`Record.recipe`), the stub rule
  (`karni_cli.recipes.apply`, `karni_cli.builder.render.is_stub_file`,
  `karni_cli.recipes.karni_owned`) and the `recipes` pytest marker of
  karni-cli's suite.
- [Tree models](models.md#tree-models): `karni.models.TreeModel` and
  `OrderedTreeModel`, `karni.managers.TreeQuerySet` and `TreeManager`,
  `karni.tree`, `karni.api.tree` (the `tree/`, `children/`, `ancestors/` and
  `move/` endpoints, `?parent=`, `?descendants_of=` and `DELETE ?branch=`),
  `BaseViewSet.serves_tree`, `tree_actions`, `tree_max_nodes`,
  `tree_default_depth`, `tree_max_depth`, `tree_top_level()` and
  `get_tree_node_serializer_class()`, the `x-karni-tree` extension,
  `karni.admin.tree` and `tree_changelist_max_rows`, the `hand-written-tree`
  rule, the `tree` key of `karni.yaml` and the `tree` fact, the
  `use<Name>Tree` hooks of `karni types`, and `TreeView`, `TreeSelect`,
  `TreeBreadcrumb`, `useResourceTree`, `useResourceChildren`,
  `useResourceAncestors` and `useTreeMutations` in `@karni/ui`.
- [The tree scope](accounts.md#the-tree-scope): the `tree:<path>` scope (with
  the `tree` value of `RolePermission.scope`), `karni.accounts.tree_scope`,
  `karni.accounts.grants.user_key`, the `access/` endpoint of a tree
  resource (`BaseViewSet.access_forest`, `karni.api.tree.tree_access_serializer`),
  the `tree:<field>` options of the permission matrix, the `tree` entry of a
  `karni why` grant in `--json`, `tree:<path>` in a `karni.yaml` role grant,
  and `useResourceAccessForest` and `TreeView`'s `access` in `@karni/ui`.
- [Navigation from data](navigation.md): the `KARNI_NAVIGATION` and
  `KARNI_NAVIGATION_PAGES` settings, `karni.navigation` (with
  `karni.navigation.api`, `karni.navigation.checks` and
  `karni.navigation.admin`), the `karni.navigation` app and its `NavItem`
  model, the `navigation/` endpoint, the `navigation` key of `karni.yaml` and
  `karni_cli.spec.navigation`, and `useNavigation`, `karniKeys.navigation`,
  `navigationEntries`, `activeRoute`, `defaultNavIcons`, `navIcon`,
  `isNavGroup`, `LayoutNavGroup`, the `NavGroup` slot and `Layout`'s
  `navSource`, `pathname` and `icons` in `@karni/ui`.
- [Taxonomies](models.md#taxonomies): `class Karni: taxonomies`,
  `karni.taxonomy`, `karni.api.taxonomy` (the `?<key>=` and
  `?<key>_descendants=` filters, the `facets/` and `tagged/` endpoints),
  `BaseViewSet.facet_queryset()`, `taxonomy_actions`, `serves_facets()` and
  `serves_tagged()`, the `x-karni-taxonomy` extension, `origin` of
  `karni.tree.walk_sql`, the `taxonomies` fact, the `taxonomies` key of
  `karni.yaml`, and `FacetPanel`, `useResourceFacets` and `ResourceTable`'s
  `facets` in `@karni/ui`.

Stable since 0.4.1:

- [Response caching](api.md#response-caching): `Cache`, `Uncached`,
  `karni.api.caching` (`invalidate`, `invalidation_batch`, `clear`,
  `access_scope`, `dependencies`, `normalized_query`, `cache_enabled`,
  `flush_time`, `FlushTime`, `CACHE_HEADER` and `BYPASS_HEADER`),
  `BaseViewSet.cache`, `get_cache_scope` and `get_response_cache`, the
  `KARNI_API_CACHE`, `KARNI_API_CACHE_TTL`, `KARNI_API_CACHE_ALIAS` and
  `KARNI_API_CACHE_FLUSH` settings, the `X-Cache` response header and the
  `X-Bypass-Cache` request header, the `karni.E410`, `E411` and `W580`
  checks, the `karni-flush-api-cache` schedule and its task
  `karni.tasks.flush_api_cache`, and `karni.admin.cache` (the *API cache*
  screen). The `X-Karni-Cache` header is deprecated and goes in 1.0, with
  the transitional setting `KARNI_API_CACHE_LEGACY_HEADER`. The spec's keys
  for it (`features: api_cache`, an entity's `cache:`) follow the app spec,
  which is experimental.
- [Suggestions from code](enforcement.md#suggestions) (the `SUG001` to `SUG007`
  codes and their silencing rules `suggest-*`, `karni suggest` and `--json`
  with `karni-suggestions.schema.json`, `karni.suggestions`, `manage.py
  karni_suggest`, `karni_check --no-suggestions` and `--suggestions-file`,
  `.karni/local/suggestions.json`, `KARNI_SUGGESTIONS`, and `C780` and `C781`),
- Tooling for large projects:
  [context slices](agents.md#large-projects-one-area-at-a-time)
  (`karni context --summary`, `--app`, `--model` and `--max-tokens`, the
  same flags of `manage.py karni_context`, `karni.introspect`'s
  `summary_context`, `app_context`, `model_context`, `field_text`,
  `resolve_apps` and `resolve_models`),
  [the check cache](enforcement.md#the-check-cache) (`karni check
  --changed [REF]` and `--no-cache`, `manage.py karni_check --changed` and
  `--no-cache`, `.karni/local/check-cache.json`, `.karni/local/eslintcache`,
  `karni.testing.checkcache` and `KARNI_CHECK_CACHE`),
  [volume seeding](seeding.md#volume-seeding) (`karni seed --volume` and
  `--batch-size`, `karni.bulk_seeding`, the `volume`, `bulk` and
  `batch_size` arguments of `karni.seeding.seed`, `karni.seeding.volume_rows`,
  the seed ledger `.karni/local/seeded.json`, the report's `volume`, `bulk`
  and `timings`, `KARNI_SEED_BULK_THRESHOLD`, `KARNI_SEED_BATCH_SIZE` and
  `KARNI_SEED_LEDGER`), [the scaling settings](testing.md#3-the-scaling-check)
  (`KARNI_SCALING_ROWS`, `karni.performance.Scaling`, `scaling_rows`,
  `query_scaling` on a viewset, and `ScalingResult`'s `rows`, `seconds`,
  `budget`, `endpoint`, `too_slow` and `slow_message()`),
  [query plans](debugging/queries.md#query-plans-explain) (`karni queries
  --explain`'s analysis on PostgreSQL, `karni.api.explain`, the `seq_scans`
  of `--json` and `KARNI_EXPLAIN_SEQ_SCAN_ROWS`), the seed volume of
  `karni plan` (`karni_cli.spec.plan.seed_time_class`, the `seed_bulk_threshold`
  fact) and `scripts/benchmark/large_project.py` with its baseline.
- [The `karni-reports` module](modules.md#modules-in-this-repository): the
  whole of `karni_reports` (`Report`, `register`, `get_report`, the
  renderers, `GeneratedReport`, `karni_reports.services`), the
  `KARNI_REPORTS_*` settings, the `/api/reports/` endpoints and their
  throttle scopes, the base print template `karni_reports/base.html` and its
  blocks, `manage.py karni_pregenerate`, and `useReport` and `ReportButton`
  in `@karni/reports-ui`. The six-letter code prefix (`REPORT001`) is not
  experimental: codes keep their meaning.

## Supported platforms

| Component | Supported |
|---|---|
| Python | 3.12, 3.13, 3.14 (3.14 from 0.3.0) |
| Django | 5.2 LTS |
| Node.js (frontend tooling) | 20.19+ for projects (Vite 8), 22.12+ to develop Karni itself (Vitest 5) |
| React | 18, 19 |
| PostgreSQL | 16+ (production). SQLite works for development and tests. |

Dropping a supported Python, Django or Node version is a minor-release change
that is announced one minor release ahead. Adding one can happen in any minor
release.
