# Changelog

Every package in this repository (`karni`, `karni-cli`, `karni-payments`,
`@karni/ui`, `@karni/payments-ui`) is released at one version, in lockstep;
see [docs/releasing.md](docs/releasing.md).

Breaking changes and deprecations are recorded in machine-readable form in
`packages/karni/karni/changelog/<version>.toml` — that is what `karni upgrade`
reads to apply codemods and list the manual steps — and explained in
`docs/migrations/<version>.md`. This file is the human summary.

## 0.3.0 — 2026-10-20

See [docs/migrations/0.3.md](docs/migrations/0.3.md) for the two breaking
changes and how to upgrade.

- Membership scoping and generated tests, from the Social Stats case study:
  `own` takes an owner path through a many-to-many
  (`owner_field = "workspace__members"`), now documented as the way to scope
  rows to a workspace's members; the test factories accept one row for a
  many-to-many, so `assert_crud` and `assert_isolated` drive it; a new
  check, `E214`, resolves every path a role's grants filter on (owner paths,
  scope paths, custom scopes) at boot, so a scope that names a missing path
  fails `karni check` instead of answering 500; `karni make test` says, in
  its output and the test file, why it leaves `assert_isolated` out.
- Django 5.2 LTS: karni requires `Django>=5.2.8,<5.3` (5.1 is out of
  support; pip-audit reported ten unpatched advisories against 5.1.15) and
  django-unfold 0.110. Python 3.14 is supported and tested — on Django 5.1
  every admin page failed under 3.14. Projects pinned to Django 5.1 upgrade
  Django with karni; no project code changes were needed in EventHub,
  Social Leads or the modules. Dropping Django 5.1 is a minor-release
  change under the [stability promise](docs/stability.md), released as 0.3.0.
- `karni seed` can run again on a seeded database. Each run is a new process
  that draws the same UUID keys from the same seed, so a second run failed
  with `E612` on the primary key (found by running the README quickstart, then
  adding a model and seeding again). A key an earlier run used is now replaced
  by one derived from it; an empty database still gets the same rows.
- A generated reference: `scripts/gen_reference.py` writes `docs/REFERENCE.md`
  (every command, base class, `class Karni` key, setting, component, hook,
  module, error code, make target and slash command, with each capability's
  status) and the README's generated blocks from the source, and CI fails when
  either is stale. `karni.meta.OPTIONS` (and a module's `KARNI_OPTIONS`) now
  documents each `class Karni` key; the generator fails on a key that code
  reads but no list declares. Every `@karni/ui` export has a one-line JSDoc.
- The README is rewritten: a demo recorded from a real quickstart run
  (`scripts/demo/`), a cheat sheet, the generated command table and per-area
  reference, an honest comparison and status. The quickstart (README and
  docs) adds `karni make page login --kind login`: a new project had no
  sign-in page for the React app. Package READMEs link absolutely, so their
  links work on PyPI.

## 0.2.0 — 2026-10-20

See [docs/migrations/0.2.md](docs/migrations/0.2.md) for every breaking
change and its migration note.

- Roles as data: `KARNI_ROLES`, `karni sync-roles`, `user.can()`,
  `@requires()`, `Can("app.model:action")` in `access` declarations
  (ADR 0002).
- Row-level scoping (ADR 0002, P2): `access = Granted()` is the default
  `karni make viewset` writes and scopes rows by the roles' grants; the
  admin shows only the rows the user's grants reach; `scope_exempt` with a
  reason that `karni check` lists; `assert_isolated` gains the `grant`
  dimension and probes expansion, filters, search, ordering and the admin.
- Welcome page: `/` on first boot (`karni.welcome.welcome_urls()`, mounted
  last by the scaffold) shows the project live — models with admin and API
  links, modules, seven status checks each with the command that fixes a
  cross, the `karni context` output and the first agent prompt. `DEBUG`
  only, gone once the project owns `/`; `karni.E505` guards production.
- Field-level visibility (ADR 0002, P3): `class Karni: field_roles` hides
  fields per role on the API (absent, never `null`), in `?expand=`, in the
  per-role OpenAPI schema and in the admin; write-protected fields are
  refused naming the roles that may; `?ordering=`, filters and `?search=`
  ignore hidden fields; `@karni/ui` refetches the schema on identity
  change; `assert_crud` checks visibility. `?ordering=` now accepts only
  serializer-visible fields; `search_fields` may not name a write-only
  field (`E131`); `E212` validates `field_roles`.
- Change history (ADR 0002, P4): the `karni.audit` app records, for models
  that opt in with `class Karni: audit = True`, who changed what from what
  to what, captured at the model layer so the API, admin, commands and the
  shell all leave the same entry; sensitive fields are redacted; surfaced on
  the admin History tab, `GET /<resource>/<id>/history/` and
  `<ChangeHistory/>`; retention pruning off by default; `karni check` flags
  `update()`/`bulk_update()` on audited models (`audited-bulk-write`, `K113`).
- Permission matrix (ADR 0002, P5): Roles → *Permission matrix* in the
  admin changes who may do what with no deploy — roles across, models down,
  a scope selector per action, bulk selectors, a confirmation diff — with
  the guard rails (system roles keep their declared grants, nobody grants
  what they do not hold, nobody removes their own last permission to change
  permissions) and the matrix's own change history; *Effective permissions*
  answers "why can this person see this?" per user; the same as an API
  under `api/auth/permissions/` for custom UIs, fixtures and tests
  (`E213`). `RolePermission.origin` tells the sync which grants the matrix
  owns; `KARNI_MATRIX_EXCLUDE`.
- Import and export (ADR 0002, P6): `GET /<resource>/export/?format=csv|xlsx`
  on every resource — the list as the request sees it, filters and scope and
  field visibility included, relations as natural keys — and a four-step
  import (`/<resource>/import/…`): upload, map columns (remembered per model
  per user), the mandatory dry run with exact counts and per-row errors,
  then one transaction recorded as one audit batch; large files run in
  Celery with progress; per-model hooks in `class Karni` (`natural_key`,
  `import_key`, `import_lookup`, `import_transform`, `after_import`); a
  downloadable template per model. Export actions and an Import page on
  every Karni admin; `<ResourceImport/>` and export buttons on
  `<ResourceTable>` in `@karni/ui`. `KARNI_IMPORT_INLINE_ROWS`,
  `KARNI_IMPORT_MAX_ROWS`, `KARNI_EXPORT_MAX_ROWS`; `E801`–`E803`.
- Write interception: every `BaseModel` save and delete sends
  `karni.signals.pre_write`; a receiver that raises `KarniWriteDeferred`
  stops the write before any SQL — the API answers 202 with its payload,
  the admin shows its message. The hook behind the new `karni-approvals`
  module (M1): `class Karni: requires_approval = [...]` turns a maker's
  guarded change into a pending change a second person approves or
  rejects (never the maker, in code), with per-model approvals count,
  approver roles and timeouts, an admin queue, `/api/pending-changes/`,
  Celery notifications, every decision in `karni.audit`, and
  `@karni/approvals-ui` (`<ApprovalsQueue/>`, `<ApprovalsBadge/>`).
- Vetoes: `karni.vetoes.register_veto` refuses an action at the API and
  admin gates after the access declaration admitted it (a maintenance
  freeze, a read-only tenant); `KarniAdminMixin.vetoed()`. The hook behind
  the new `karni-impersonation` module (M2): "log in as user" for support
  with an explicit `impersonate` permission never implied by staff status,
  no privilege escalation (a target holding anything the actor lacks is
  refused), a banner naming both identities with a one-click exit, a
  session record, every write attributed to both identities in
  `karni.audit` (the row's actor is the target, the batch's actor the
  impersonator), a configurable time limit, a hard block on deleting,
  exporting and payment changes while impersonating, the target notified
  and a reason required by default, a threat model in the README;
  `karni.audit.capture.within_batch`; `@karni/impersonation-ui`
  (`<ImpersonationBanner/>`); `useAuth().adoptTokens` in `@karni/ui`.
- `karni check` and the architecture suite now scan a project's apps
  without `BASE_DIR` (the audit's "enforcement scans zero files" finding).
- The launch audit's remaining findings: `karni migrate` creates `pg_trgm`
  (`?search=` no longer 500s on a fresh PostgreSQL); `KARNI_CACHE=locmem`
  runs a project without Redis and the quickstart uses it, with pytest in
  its install line; `karni.welcome.media_urls()` serves uploads in
  development; `karni --version`; `karni doctor` with the venv outside the
  project; `karni context` (and the MCP `context` tool) from the interpreter
  running karni-cli; `karni serve`/`karni worker` pass SIGTERM on to the
  server; `karni test` says when pytest is missing (`C011`); `karni check`
  runs the frontend's ESLint next to jscpd; the scaling check also measures
  every list with `?expand=`; a `KARNI_*` dotted path that cannot be imported
  is `E506` naming the setting (`E507` for `KARNI_CACHE`); generated detail
  pages expand their relations; a required relation left empty says
  "Required" and an optional one clears; `[tool.karni] baseline` in a new
  project's pyproject, so `karni upgrade` never reports changes a fresh
  scaffold already satisfies; `LOGIN_REDIRECT_URL` defaults to the admin;
  the seed login says "superuser"; the two schema warnings are gone. The
  cosmetics too: choice labels from the schema's choice list instead of raw
  markdown help text (`FieldDef.enumLabels`), one casing for every table
  header, `karni rules` trimmed (402 cl100k tokens, measured), and the
  admin's *All* rows counted once. The EventHub Playwright journeys ran
  (three passed) and every package built, installed into a clean venv and
  dry-run published.
- Every `BaseViewSet` declares `access`; relation fields and `?expand=`
  follow the target's read scope; query budgets fail tests.
- Errors that teach: every error carries a code, `karni explain <code>`,
  the generated error reference.
- `karni make …` generators and the project runners (`karni serve`,
  `migrate`, `test`, `seed`, …); `karni upgrade` with codemods.
- The documentation site, the EventHub reference application, release
  automation, the brand assets.

## 0.1.0

The first cut: `BaseModel` and scopes, the `access` declaration, generated
serializers and viewsets, the derived admin, accounts, events and schedules,
`@karni/ui`, the scaffold and the agent adapters.
