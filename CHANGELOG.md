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
