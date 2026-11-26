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
`karni`, `karni-cli`, `@karni/ui` and every module's Python package and
React package (when it has one) at the same version
([the list](releasing.md#lockstep-versions)).

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
- AGENTS.md, the agent file `karni rules sync` writes, and the procedures it
  lists. Its wording changes between releases, so run `karni rules sync`
  after upgrading.
- Deprecated in 0.5.0, removed in 1.0: the files that only one tool reads,
  which `karni new` wrote before 0.5.0 (`CLAUDE.md`, `.claude/commands/`,
  `.cursor/rules/karni.mdc`, `.cursor/commands/`, `.windsurf/rules/karni.md`,
  `.windsurf/workflows/`, `.github/copilot-instructions.md`,
  `.github/prompts/`, `.clinerules/karni.md`, `.junie/AGENTS.md` and
  `CONVENTIONS.md`). `karni rules sync` keeps a project's existing ones up to
  date until then and warns with `C860`
  ([migrating](migrations/0.5.md#tool-specific-agent-files-are-deprecated-keep-agentsmd)).

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

Some parts never become experimental. An error code keeps its meaning forever
and is never reused, also for an experimental feature. A change to the
database schema of an experimental model always comes with a migration.

### When a name becomes stable

A name becomes stable once it is used for real: by a real project built on
Karni, or by an example, a recipe, the scaffold or a module in this
repository. Use in a private project counts. It is recorded as "a real
project (private)", never with the project's name. The release that makes a
name stable says so in its CHANGELOG entry, and from then on the promise
above applies in full.

A feature stays experimental while nothing uses it yet, or while a known plan
will still change it. Each line below says which.

### Where the mark is shown

The mark is shown once per feature, in these places and nowhere else:

- the feature's line in the list below,
- one *Experimental* note at the top of the docs section that describes the
  feature (a feature documented on several pages, such as the games, has
  one on each, and a package that is experimental as a whole has one at the
  top of its README). Other sections that mention the feature link to it,
- the docstring (Python) or doc comment (TypeScript) of the feature's public
  entry points: the module or package that is the feature's own, and the main
  class, function or component a project imports from a shared module such
  as `karni.models` or `@karni/ui`. That docstring starts with
  `Experimental.`

The feature's other names (its methods, options, props, types, settings,
commands, error codes and the rows of generated tables) carry no mark. Each
of them is documented in the feature's docs section, which opens with the
note.

In the [reference](REFERENCE.md#capabilities-and-status), the status
`experimental` means this and nothing else. A capability that keeps the
promise but that no project or example uses yet has the status `tested`.

`scripts/experimental.toml` lists the experimental features with their docs
sections and entry points. `python scripts/check_experimental.py` fails when a
mark is anywhere else, or when a feature in the list has no note in its docs
section or no line below. CI runs it.

Experimental now:

- [Games](game.md): the karni-game module (its models, services, hooks, the
  `game.*` family events, `karni_game.merge.Merger`, the signatures, the
  roles), the `KARNI_GAME_*` settings, [the game API](game-api.md) and its
  answers, everything in [`@karni/game`](game-client.md) and its subpaths
  ([sim](game-sim.md), [scenes](game-scenes.md), [ui](game-ui.md),
  [draw](game-draw.md), [collide](game-collide.md),
  [assets](game-assets.md), [sfx](game-sound.md)), the
  [game starters](game-starters.md) (`--genre`, `karni starters`), the
  [game kinds](apps-and-games.md) `game` and `app+game` of `karni new` and
  the `karni-game` command. The next milestones extend the game side, and no
  real project uses it yet.
- [The built-in recipes](recipes/index.md): `shop`, `booking`, `crm`, `lms`,
  `marketplace` and `data-portal` (their specs, files and names), `karni new
  --recipe`, the `recipe` key of `.karni/build.json` (`Record.recipe`), the
  stub rule (`karni_cli.recipes.apply`, `karni_cli.builder.render.is_stub_file`,
  `karni_cli.recipes.karni_owned`) and the `recipes` pytest marker of
  karni-cli's suite. Each recipe is to grow into a full app, so their files
  and names will change.
- [The family](family.md): several recipes in one project (`app.recipes`,
  `app.currency`, `apps.<label>.route`, the `features.people`,
  `features.events`, `features.timeline` and `features.preferences` keys,
  the `requires`, `conflicts` and `version` keys of `recipe.toml`, `karni
  recipes add`, `remove` and `upgrade`, `karni new --recipe a --recipe b`,
  `.karni/recipes/`, `frontend/src/karni/parts.ts`,
  `karni_cli.recipes.compose`), its screens in `@karni/ui` (`FamilyHome`,
  `FamilyLayout`, `AccountPage`, `SignInPage`, `SettingsPage`, the inbox and
  the person's addresses), [named menus](navigation.md#named-menus-experimental)
  and [the family rules](family.md#how-the-rules-are-kept) (`part-imports-part`,
  `part-role-prefix`, `part-route` (K315), `karni.testing.parts` and the `//`
  form of the `karni: allow(...)` marker). Only Karni's own family builds use
  it, and it moves with the recipes.
- [The /new-app flow](agents.md#agents-the-new-app-flow): the `new-app`
  procedure and rule K311, [recipes](app-spec.md#recipes) (`karni recipes
  list` and `show`, `--match` and its ranking, the blank start, the
  `recipe.toml` format and its schema, the `karni.recipes` entry point group,
  `karni recipes --json` and its schema, `karni_cli.recipes`) and
  [the MCP tools](app-spec.md#mcp-tools) `recipes`, `spec_validate`,
  `questions`, `answer`, `plan`, `build` and `modules` with their results'
  schema (`karni_cli.agent_tools`). No project was made through it yet.
- [Clarifying questions](app-spec.md#questions): `karni plan --questions`
  (its `--max`, `--json` and schema, the question ids and the rules that
  choose them), `karni spec answer`, `karni_cli.spec.questions` and
  `karni_cli.spec.edit`. No project was made through them yet.
- [External tables, views and a second database](models.md#external-tables-views-and-a-second-database):
  the `class Karni` options `external`, `writable` and `database`, `karni.db`
  (with `DatabaseRouter`, `karni.db.checks` and `karni.db.introspection`),
  [read-only models](api.md#read-only-models) (`BaseViewSet.is_read_only`
  and `read_only_refused_actions`, `KarniModelAdmin.is_read_only`,
  `assert_crud`'s `read_only`), `karni.testing.create_external_tables`, the
  pytest option `--karni-external-tables`, `manage.py karni_inspect` and
  `karni make model --external`. No project or example uses it yet.
- [Pages behind a capture without a model](public-site.md#pages-behind-a-capture-without-a-model-experimental):
  `karni_site.sitemaps.pages` and `declared_pages`, and the page test's
  `*declared_pages()` that `karni make site` writes. No project or example
  uses it yet.
- [People](people.md): the `karni.people` app and its models, the functions
  of `karni.people`, its events, the `KARNI_PEOPLE*` settings, the people
  endpoints and `fk:people.Person` in `karni.yaml`. It arrived with the family foundation in 0.6.0 and only Karni's own modules
  and recipes use it: the rebuilds of the recipes will prove or reshape it.
- [Family events](family-events.md): `declare`, `publish`, `subscribe`, `once`,
  `Event`, `Declaration`, `Subscriber`, `Registry` and `CONTRACT` in
  `karni.events`, the `karni.outbox` app (its models, admin, tasks, beat
  entries, `karni.outbox.delivery`, `dispatch`, `checks` and `health`), the
  `KARNI_EVENTS_*` settings, the `events:` lines of `karni check`, the outbox
  rows in `karni trace`, karni-payments' `payments.*` events, and
  `capture_events`, `deliver_now` and `assert_events_declared` in
  `karni.testing`.
  It arrived with the family foundation in 0.6.0 and only Karni's own modules
  and recipes use it: the rebuilds of the recipes will prove or reshape it.
- [Timeline](timeline.md): the `karni.timeline` app (its models
  `TimelineEntry` and `TimelineLink`, admin, task and beat entry,
  `karni.timeline.api`, `access`, `checks`, `services` and `subscribers`), the
  functions and `CONTRACT` of `karni.timeline`, the `timeline=` option of
  `declare()`, `GET /api/timeline/`, the `KARNI_TIMELINE_*` settings, the
  timeline titles of the people events and of `payments.payment.succeeded`,
  and the person karni-payments' events carry.
  It arrived with the family foundation in 0.6.0 and only Karni's own modules
  and recipes use it: the rebuilds of the recipes will prove or reshape it.
- [Notifications](notify.md): the `karni.notify` app (its models
  `EmailTemplate`, `Notification`, `Choice` and `Unsubscribe`, admin, task
  and beat entry, `karni.notify.api`, `viewsets`, `editor`, `moves`,
  `source`, `adopt`, `checks` and `services`), the names and `CONTRACT` of
  `karni.notify`, the `channels=` and `replace=` arguments and `CHANNELS`,
  `deliver` and `is_silenced` of `karni.mail`, `/api/inbox/`,
  `/api/email-templates/`, `/api/notify/unsubscribe/`, `features.notify`,
  and the `KARNI_NOTIFY_*` and `KARNI_MAIL_SOURCE` settings.
  It arrived with the family foundation in 0.6.0 and only Karni's own modules
  and recipes use it: the rebuilds of the recipes will prove or reshape it.
- [Preferences](preferences.md): the `karni.preferences` app and its models,
  the names and `CONTRACT` of `karni.preferences`, `/api/preferences/`, the
  admin and the `KARNI_PREFERENCES_*` settings.
  It arrived with the family foundation in 0.6.0 and only Karni's own modules
  and recipes use it: the rebuilds of the recipes will prove or reshape it.
- [Home tiles per role](api.md#home-tiles-per-role-experimental): `karni.tiles` (`Tile`,
  `register`), `GET /api/dashboard/`, karni.yaml's `dashboard:`, and
  `DashboardTiles`, `registerTile` and `registerTileKind` in `@karni/ui`.
  It arrived with the family foundation in 0.6.0 and only Karni's own modules
  and recipes use it: the rebuilds of the recipes will prove or reshape it.
- [Rules](rules.md): the `class Karni` options `bounds`, `unique`,
  `targets`, `frozen`, `delete` and `moves` (`karni.rules`),
  `Access(delete=..., assign=...)`, the written-row check, `Matching`,
  [row actions](api.md#row-actions-experimental) (`karni.api.actions`) and the karni.yaml
  keys that write them.
  It arrived with the family foundation in 0.6.0 and only Karni's own modules
  and recipes use it: the rebuilds of the recipes will prove or reshape it.
- [Catalogues, money and page titles](https://github.com/cbsshekhawat18-lab/karni/blob/main/packages/karni-ui/README.md#catalogues-money-and-page-titles-experimental):
  `ResourceGrid`, the money helpers and `usePageMeta` in `@karni/ui`.
  It arrived with the family foundation in 0.6.0 and only Karni's own modules
  and recipes use them: the rebuilds of the recipes will prove or reshape them.
- [The `karni-commerce` module](commerce.md): the whole of `karni_commerce`
  (the models, the `Sellable` adapter and its registry, `karni_commerce.services`,
  the signals of `karni_commerce.events`, `karni_commerce.fulfilment`, the
  checkout validator, the email kinds), the `KARNI_COMMERCE_*` settings, the
  cart and order endpoints and their answers, and everything in
  `@karni/commerce-ui`.
  It arrived with the family foundation in 0.6.0 and only Karni's own modules
  and recipes use it: the rebuilds of the recipes will prove or reshape it.
- [karni-payments' signals](https://github.com/cbsshekhawat18-lab/karni/blob/main/modules/karni-payments/README.md#signals-experimental):
  the signals of `karni_payments.events` (`payment_status_changed`,
  `refund_created` and `refund_status_changed`). It arrived with the family foundation in 0.6.0 and only Karni's own modules
  and recipes use them: the rebuilds of the recipes will prove or reshape them.
- [Volume seeding](seeding.md#volume-seeding): `karni seed --volume` and
  `--batch-size`, `karni.bulk_seeding`, the `volume`, `bulk` and
  `batch_size` arguments of `karni.seeding.seed`, `karni.seeding.volume_rows`,
  the seed ledger `.karni/local/seeded.json`, the report's `volume`, `bulk`
  and `timings`, and the `KARNI_SEED_BULK_THRESHOLD`, `KARNI_SEED_BATCH_SIZE`
  and `KARNI_SEED_LEDGER` settings, with the seed volume of `karni plan`
  (`karni_cli.spec.plan.seed_time_class`, the `seed_bulk_threshold` fact).
  No project or example uses it yet.
- [The scaling check](testing.md#3-the-scaling-check): `KARNI_SCALING_ROWS`,
  `karni.performance.Scaling`, `scaling_rows`, `query_scaling` on a viewset,
  and `ScalingResult`'s `rows`, `seconds`, `budget`, `endpoint`, `too_slow`
  and `slow_message()`. No project or example uses it yet.
- [Query plans](debugging/queries.md#query-plans-explain): `karni queries
  --explain`'s analysis on PostgreSQL, `karni.api.explain`, the `seq_scans`
  of `--json` and `KARNI_EXPLAIN_SEQ_SCAN_ROWS`. No project or example uses
  it yet.
- [`@karni/ai-ui`](ai-extraction.md#react): `ExtractButton`, `ExtractPreview`
  and `useExtract`. No project or example renders it yet.
- [`@karni/reports-ui`](reports.md#in-react): `ReportButton` and `useReport`.
  No project or example renders it yet.
- [`@karni/storage-ui`](storage.md#the-react-side): everything in it. No
  project or example renders it yet.
- [`ResourceBoard`](https://github.com/cbsshekhawat18-lab/karni/blob/main/packages/karni-ui/README.md#resourceboard-a-board-by-state-experimental):
  the component, its props and its slots. No project or example renders it
  yet.
- [`ResourceCalendar`](https://github.com/cbsshekhawat18-lab/karni/blob/main/packages/karni-ui/README.md#resourcecalendar-day-week-month-and-list-experimental):
  the component, its views, props and slots. No project or example renders it
  yet.
- [`karni remove`](modules.md#taking-a-module-out-karni-remove-x): the
  command and what it writes. No project or example has taken a module out
  with it yet.

Stable since 0.7.1. These were experimental and are now used for real, so the
promise above covers them:

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
- [Demo mode](demo-mode.md): `karni.demo` (its accounts, write rule, reset,
  middlewares, `manage.py karni_demo_boot`, `GET /api/demo/` and `app_urls()`),
  the `KARNI_DEMO_*` settings, and `DemoNotice`, `DemoSignInPrompt`, `useDemo`
  and `karniKeys.demo` in `@karni/ui`.
- [Integer primary keys](models.md#choosing-the-key-type):
  `karni.models.BigIntBaseModel` and `IntegerKeyModel`, the `KARNI_PK`
  setting, `karni make model --pk`, `karni.api.filters.IntegerFilter`, the
  import options `match_ids` and `keep_ids` (with the `ImportJob` fields of
  the same names), the `KEYS:` line of `karni context` and the `API:` line
  (`karni.introspect.api_section`).
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
  `karni spec validate`, `karni spec export`, `karni plan`, `manage.py
  karni_facts`, `karni.facts` and the `karni_cli.spec` package.
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
  `KARNI_CHARTS_READ`) and `@karni/charts-ui` (`SavedChart`,
  `useSavedChart`, `savedChartKey`, `savedChartQuery`).
- [Page blocks](ui.md#page-blocks): `DashboardGrid`, `DashboardCard`,
  `ChartCard`, `DataTable`, `ComparisonTable`, `Accordion`, `MarkdownView`
  (with `preloadMarkdown`), `useResourceCounts`, their slots, props and
  types, ResourceDetail's `related` prop and `Related` slot, the `RelatedDef`
  schema type, the `--karni-dashboard-gap`, `--karni-data-table-max-height`
  and `--karni-data-table-row-height` tokens, the `x-karni-related` OpenAPI
  extension and `KarniAutoSchema.get_karni_related`, the spec's `{detail:
  {related: [...]}}` and dashboard pages other than `home`, `karni make page
  --kind dashboard` (`--count`) and `--related`, and the `components` key of
  `karni ui detect --json`.
- [Field groups and column sets](ui.md#field-groups-and-column-sets):
  `karni.fields.MarkdownField` (and its `markdown` type in `karni make model`
  and the spec), `karni.api.formats` (`FormattedCharField`, a model field's
  `openapi_format`), the `class Karni` options `field_groups`,
  `field_group_layout` and `column_sets`, `karni.layout`, the
  `x-karni-field-groups` and `x-karni-column-sets` OpenAPI extensions with
  `KarniAutoSchema.get_karni_field_groups` and `get_karni_column_sets`,
  `KarniAdminMixin.derive_fieldsets`, the spec's `column_sets`, the
  `fieldGroups` and `groupLayout` props of ResourceForm and ResourceDetail,
  ResourceTable's `columnSets`, `columnSet` and `onColumnSetChange`, and the
  `FieldGroupDef`, `FieldGroupLayout`, `FieldGroupsDef`, `ColumnSetDef` and
  `ColumnSetsDef` types in `@karni/ui`.
- [Names, links and rights on resource pages](ui.md#names-links-and-rights-on-resource-pages):
  `class Karni: label`, how a related row is named and linked, and the
  `onCreate` and `onEdit` rights of the resource pages.
- [AI extraction](ai-extraction.md): the karni-ai module (`karni_ai`, its
  `POST /api/ai/extract/` endpoint and answer, `/api/ai/`, the `AICall`
  model, the `KARNI_AI_*` settings and each provider's key and model
  settings, the `ai.extract` throttle scope, `karni_ai.providers`,
  `karni_ai.extraction`, `karni_ai.schema`, `karni_ai.sources`,
  `karni_ai.services.fetch`, `karni_ai.usage`). `@karni/ai-ui` stays
  experimental.
- [Emails at business moments](events.md#emails-at-business-moments):
  `karni.mail` (`send_templated`, its `kind` and `KARNI_MAIL_DISABLED_KINDS`).
- [The module catalog](modules.md#the-module-catalog): the `karni.module.toml`
  manifest format and the feature manifests, the `karni.modules` entry point
  group, `karni.catalog` (with `python -m karni.catalog`),
  `karni.testing.assert_module_manifest`, `karni modules list` and `show`,
  the `CATALOG:` lines of `karni context`, the `FEATURES:` line of `manage.py
  karni_context`, and `karni_cli.catalog`. `karni remove` stays experimental.
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
  `navSource`, `pathname` and `icons` in `@karni/ui`. Named menus stay
  experimental with the family.
- [Taxonomies](models.md#taxonomies): `class Karni: taxonomies`,
  `karni.taxonomy`, `karni.api.taxonomy` (the `?<key>=` and
  `?<key>_descendants=` filters, the `facets/` and `tagged/` endpoints),
  `BaseViewSet.facet_queryset()`, `taxonomy_actions`, `serves_facets()` and
  `serves_tagged()`, the `x-karni-taxonomy` extension, `origin` of
  `karni.tree.walk_sql`, the `taxonomies` fact, the `taxonomies` key of
  `karni.yaml`, and `FacetPanel`, `useResourceFacets` and `ResourceTable`'s
  `facets` in `@karni/ui`.
- [Suggestions from code](enforcement.md#suggestions) (the `SUG001` to `SUG007`
  codes and their silencing rules `suggest-*`, `karni suggest` and `--json`
  with `karni-suggestions.schema.json`, `karni.suggestions`, `manage.py
  karni_suggest`, `karni_check --no-suggestions` and `--suggestions-file`,
  `.karni/local/suggestions.json`, `KARNI_SUGGESTIONS`, and `C780` and `C781`).
- [Tooling for large projects](large-projects.md):
  [context slices](agents.md#large-projects-one-area-at-a-time)
  (`karni context --summary`, `--app`, `--model` and `--max-tokens`, the
  same flags of `manage.py karni_context`, `karni.introspect`'s
  `summary_context`, `app_context`, `model_context`, `field_text`,
  `resolve_apps` and `resolve_models`) and
  [the check cache](enforcement.md#the-check-cache) (`karni check
  --changed [REF]` and `--no-cache`, `manage.py karni_check --changed` and
  `--no-cache`, `.karni/local/check-cache.json`, `.karni/local/eslintcache`,
  `karni.testing.checkcache` and `KARNI_CHECK_CACHE`). Volume seeding, the
  scaling check and query plans stay experimental.
- [The `karni-reports` module](reports.md): the whole of `karni_reports`
  (`Report`, `register`, `get_report`, the renderers, `GeneratedReport`,
  `karni_reports.services`), the `KARNI_REPORTS_*` settings, the
  `/api/reports/` endpoints and their throttle scopes, the base print
  template `karni_reports/base.html` and its blocks, and `manage.py
  karni_pregenerate`. `@karni/reports-ui` stays experimental.
- [The `karni-storage` module](storage.md): the whole of `karni_storage`
  (`ProtectedFileField`, `ProtectedImageField`, the presets, the storage, the
  tokens, `Thumbnail`, `karni_storage.thumbnails`), the `KARNI_STORAGE_*`
  settings, the `<resource>/<id>/files/<field>/`, `upload/` and `confirm/`
  endpoints and their answers, `x-karni-storage` in the schema, the
  `application/vnd.karni.upload` reference part, `manage.py
  karni_thumbnails` and the `file:protected` and `image:protected` field
  types. `@karni/storage-ui` stays experimental.
- [API versions](api.md#api-versions): the `KARNI_API_VERSION`,
  `KARNI_API_VERSIONS` and `KARNI_API_UNVERSIONED` settings, `karni.api.versions`
  (with `api_urls`, `ApiVersionHeadersMiddleware` and `VersionedSchemaGenerator`),
  the `x-karni-api-versions` extension, `app.api_version` in `karni.yaml`, and
  a client per version from `karni types`.
- [Health checks](deploy.md#12-health-checks): `/healthz` and `/readyz`
  (`karni.health.probe_urls`, `karni.health.views.readyz`,
  `karni.health.checks.check_broker`), the `KARNI_READYZ_CHECKS`,
  `KARNI_HEALTH_TIMEOUT` and `KARNI_LOG_QUIET_PATHS` settings, and
  `karni.conf.logging.QuietPaths`.
- `karni.placeholder` (drawn, deterministic placeholder images) and
  `manage.py karni_publish_web`.
- [karni-payments' test checkout](https://github.com/cbsshekhawat18-lab/karni/blob/main/modules/karni-payments/README.md#trying-a-checkout-in-the-browser):
  the test provider's checkout page and `KARNI_PAYMENTS_TEST_CHECKOUT_PAGE`.

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
  for it (`features: api_cache`, an entity's `cache:`) follow the app spec.

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
