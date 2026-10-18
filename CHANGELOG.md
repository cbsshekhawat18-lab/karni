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
