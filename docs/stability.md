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

For everything listed as public below:

1. **Nothing breaks without warning.** A public name is deprecated for at
   least one minor release before it is removed. While deprecated, it keeps
   working and raises a `KarniDeprecationWarning`. The warning names the
   release that removes it and links the migration note. Removal happens in
   the next major release. This applies in 0.x as well: the names 0.2
   deprecates are removed in 1.0, not in 0.3.
2. **Every breaking change is recorded.** Each one is an entry in Karni's
   machine-readable changelog (`karni/changelog/<version>.toml`) and has a
   section in the migration notes ([0.4](migrations/0.4.md), [0.3](migrations/0.3.md), [0.2](migrations/0.2.md), [1.0](migrations/1.0.md)).
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
