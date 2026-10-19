# Changelog

Every package in this repository (`karni`, `karni-cli`, `karni-payments`,
`@karni/ui`, `@karni/payments-ui`) is released at one version, in lockstep;
see [docs/releasing.md](docs/releasing.md).

Breaking changes and deprecations are recorded in machine-readable form in
`packages/karni/karni/changelog/<version>.toml` — that is what `karni upgrade`
reads to apply codemods and list the manual steps — and explained in
`docs/migrations/<version>.md`. This file is the human summary.

## Unreleased — 0.2.0

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
- `karni check` and the architecture suite now scan a project's apps
  without `BASE_DIR` (the audit's "enforcement scans zero files" finding).
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
