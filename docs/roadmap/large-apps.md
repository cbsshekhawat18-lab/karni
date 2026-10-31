---
description: "Karni's plan for large, data-heavy apps: 100+ models, deep hierarchies, analytics dashboards and mobile clients. Every item, its phase, goal, dependencies and status, and the definition of done each one meets."
---

# Roadmap: large, data-heavy apps

Karni today fits apps with tens of models, a React staff app and a public site.
Large apps go further: a hundred or more models, deep hierarchies (disease
areas, product taxonomies), access granted node by node and user by user,
analytics dashboards, and mobile clients that sign in with Google or Apple.
Each of those is written by hand in every such project today. This plan moves
them into Karni, item by item, so an agent writes only the domain.

The plan follows Karni's rules. Anything with a meaningful RAM cost or a
separate service is a module in `modules/`, not core. Every abstraction has an
escape hatch. A public API change goes through the deprecation cycle in the
[stability promise](../stability.md). The decisions in
[ADR 0001](../decisions/0001-core-architecture.md) and
[ADR 0002](../decisions/0002-permissions-audit.md) still hold: one tenant per
deployment, `access` declared on every viewset with its closed vocabulary,
404 for a row out of scope and 403 for a row readable but not writable, soft
delete in `BaseModel`, and the query budgets.

## Items

Status is one of planned, in progress or done. A dependency means the item
cannot start before the item it names is done.

### Phase 1: blockers

| Item | Goal | Depends on | Status |
|---|---|---|---|
| 1a | Social sign-in by ID token in JWT mode: a mobile or single-page client sends a Google, Microsoft or Apple ID token and gets Karni's token pair. | none | done |
| 1b | Email one-time-code login: sign in with a six-digit code sent by email, no password. | none | done |
| 1c | A versioned terms acceptance gate: the API refuses a signed-in user until they accept the current terms version. | none | done |
| 2 | Integer primary keys as an option, next to UUIDs, working everywhere a key appears. | none | done |
| 3 | External and read-only tables, SQL views and a second database, as models Karni accepts. | none | done |

### Phase 2: data and access

| Item | Goal | Depends on | Status |
|---|---|---|---|
| 4 | Tree models: a mixin with cycle-safe recursive queries, tree endpoints, a tree view and a tree select. | none | planned |
| 5 | A `tree:<field>` access scope: a grant on a node covers every row tagged with it or with a node under it. | 4 | planned |
| 6 | Per-user grants: access granted to one user, with targets and an expiry, alongside role grants. | none | planned |
| 7 | Taxonomy tagging: one declaration tags a model to a tree, with filters, facet counts, import columns and the access scope. | 4, 5 | planned |
| 8 | Aggregation endpoints and saved charts: grouped counts and sums under the list's filters and access, and charts defined in the admin. | none | planned |
| 9 | Response caching to stable: keys that never mix access scopes, invalidation derived from relations, and an admin screen. | none | planned |
| 10 | Cross-model search: one ranked search endpoint over every model that opts in, with access applied per model. | none | done |

### Phase 3: pages for large apps

| Item | Goal | Depends on | Status |
|---|---|---|---|
| 11 | Page blocks beyond CRUD in `@karni/ui`: dashboard grid, chart card, accordion, markdown view, data table, comparison table and related tabs. | none | planned |
| 12 | Markdown fields, field groups and column sets, so a model with 100+ columns still has usable forms, detail pages and tables. | none | planned |
| 13 | Navigation from data: a menu each user gets from their roles and grants, edited in the admin. | 6 | planned |

### Phase 4: scale and production

| Item | Goal | Depends on | Status |
|---|---|---|---|
| 14 | Tooling for 100+ models: scoped context, incremental checks, volume seeding, query plans and a CI benchmark. | none | planned |
| 15 | Optional modules: reports (PDF), ai (structured extraction) and storage (S3). | none | planned |
| 16 | Production proof: a CI job that boots the Docker stack end to end, health and readiness endpoints, API versioning and a deploy guide. | none | planned |

### Then: the reference app

| Item | Goal | Depends on | Status |
|---|---|---|---|
| 17 | A medical-intelligence reference app (`examples/medintel`) that uses every item above, with synthetic data and a friction log. | 1a to 5 to start, then each later item | planned |

Notes on the order:

- Item 5 designs the interface for per-user grants that item 6 then fills,
  so the two agree without item 5 waiting for item 6.
- Item 13 may store the menu as a tree model when item 4 is done. Settings
  alone work without it.
- Item 6 uses the `Can("area:action")` slot that ADR 0001 reserved for a
  grants tier. Declarations written with `HasRole` keep working.
- Item 8's saved charts and item 15's three modules are modules
  (`karni add charts`, `karni add reports`, ...). Core never imports them.
- Item 16 overlaps the production stack 0.4.1 adds (`karni make deploy
  compose` and its CI job). It extends that work and does not repeat it.

## Definition of done

Every item meets all of these before it counts as done.

- **It follows [CLAUDE.md](https://github.com/cbsshekhawat18-lab/karni/blob/main/CLAUDE.md)
  and the patterns already in the code.** Type hints, ruff, mypy and pytest
  in Python, strict TypeScript with no `any` and Vitest in the UI. An escape
  hatch for every abstraction, and no abstraction without three real uses.
- **New public names start as experimental.** They follow the
  [experimental tier](../stability.md#experimental-names) of the stability
  promise: marked `Experimental.` in the docstring, by an *Experimental*
  note in the docs and by *Experimental tier* in the reference, free to
  change in a minor release with a CHANGELOG entry, and stable once a
  reference application uses them.
- **It is tested.** Unit and integration tests, plus an `assert_*` helper or a
  `karni check` rule wherever there is a misuse to catch.
- **It is documented.** A docs page or section, `docs/REFERENCE.md`
  regenerated with `scripts/gen_reference.py`, a CHANGELOG entry (and a
  changelog TOML entry when a project must change), and the agent rules
  updated with `karni rules sync` when agents need to know.
- **Everything passes.** The full test suite on SQLite and PostgreSQL and
  `karni check` pass, and the examples are updated when they use the
  feature.
- **One branch per item.** Nothing is pushed and no pull request is opened
  until the owner asks.
- **The private app stays private.** The app whose needs motivated this plan
  is never named, linked or copied anywhere: code, data, docs, tests or
  commits. Its code may be read as a reference, never quoted.
