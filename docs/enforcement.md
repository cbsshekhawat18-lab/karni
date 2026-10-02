# Enforcement

Every rule fails a build — nothing warns. Every rule has an explicit, inline
opt-out that requires a reason, because rules without escape hatches cause
forks, and a fork is worse than a duplicate.

Each enforced rule also has a stable agent-facing code (`K101`…`K205`) in
Karni's rule registry: `karni rules` lists them, `karni rules --explain
<code>` gives the rationale and fix, and `karni rules --check <file>` runs a
fast single-file subset of these checks. See [Karni for AI agents](agents.md).

## Backend rules (karni.testing)

Run in CI as `pytest --pyargs karni.testing.architecture`, and on every
`karni check` via the `karni.checks` entry points (`architecture`,
`duplication`). Only project code is scanned — apps whose source lives under
`BASE_DIR`; installed packages (including Karni modules) are never scanned
and must pass these rules in their own CI.

| Rule id | Fails when | Fix |
|---|---|---|
| `model-base` | a concrete model inherits `django.db.models.Model` directly | inherit `karni.models.BaseModel` / `SoftDeleteModel` |
| `viewset-base` | a GenericViewSet subclass bypasses `BaseViewSet` | inherit `karni.api.BaseViewSet` |
| `viewset-access` | a `BaseViewSet` serving a model (`model`/`queryset` set, or routed) has no `access` — inherited declarations and an overridden `get_access()` count | add `access = Access(read=..., write=...)`, or `Unscoped(reason=...)` |
| `access-override` | a class overrides `filter_queryset_for_user` | express the row rule in `access` (`Where(...)`), or opt out with the reason |
| `admin-convention` | a registered admin for a project model isn't a `KarniModelAdmin` | use `AdminMeta` on the model, or subclass `KarniModelAdmin` |
| `raw-sql` | `.raw()`, `cursor.execute()`, `RawSQL` outside `sql_allowed` dirs | move it under `*/sql/*`, or opt out |
| `http-client` | `requests`/`httpx`/`urllib.request` imported outside `http_allowed` | call providers from a `*/services/*` module |
| `redundant-serializer` | a Meta-only ModelSerializer identical to the generated one | delete it — `BaseViewSet(model=X)` generates it |
| `duplicate` | ≥ `min_statements` structurally identical statements in two places | reuse the named Karni API, or extract one implementation |
| `opt-out-reason` | any opt-out marker without a reason | write the reason |

Opt-out (same line, the line above a class or method, or the line above its
first decorator; `opt-out-reason` itself cannot be suppressed):

```python
# karni: allow(raw-sql): aggregation too complex for the ORM, reviewed 2026-10
```

```python
class InvoiceViewSet(BaseViewSet):
    model = Invoice
    access = Access(read=Authenticated(), write=HasRole("billing"))

    # karni: allow(access-override): rows come from the subscription service
    def filter_queryset_for_user(self, queryset):
        return queryset.filter(account__in=subscriptions.visible_accounts(self.request.user))
```

The two access rules guard ADR 0001 Decision 2. `viewset-access` makes a
forgotten declaration a build failure; at runtime such a viewset already
denies every request, and opting out of the rule does not change that.
`access-override` makes widening the row policy visible: the hook receives
the access-scoped queryset, and only replacing it can widen it. An
overridden `get_queryset` needs no marker — it is wrapped, so the read scope
still applies to whatever it returns.

Configuration — `KARNI_ARCHITECTURE` in settings (all keys optional):

```python
KARNI_ARCHITECTURE = {
    "skip_apps": [],                      # extra app labels to exclude
    "sql_allowed": ["*/sql/*", "*/migrations/*"],
    "http_allowed": ["*/services/*", "*/providers/*", "*/tests/*", "conftest.py"],
    "dup": {"min_statements": 8, "exclude": ["*/migrations/*"]},
}
```

## Frontend rules

`karni check` also runs jscpd (pinned in the scaffold's frontend
devDependencies, configured by `frontend/.jscpd.json`) — duplication above
the threshold fails with the full clone report. Opt-out:
`// jscpd:ignore-start -- <reason>` … `// jscpd:ignore-end`; a bare
`ignore-start` without a reason fails.

The `@karni/ui` ESLint plugin (`@karni/ui/eslint-plugin`, flat config only —
ESLint >= 9 — via `configs.recommended`) ships four rules, all `"error"`:

| Rule | Fails when | Fix |
|---|---|---|
| `karni/no-raw-elements` | raw `<table>/<form>/<input>/<select>/<textarea>` JSX outside the UI package | compose `ResourceTable`/`ResourceForm`/`Input`/… |
| `karni/max-page-lines` | a file under `**/pages/**` exceeds 50 physical lines (option `maxLines`) | use the components' props; move logic into hooks |
| `karni/no-deep-imports` | any import from `@karni/ui/dist/*` or `@karni/ui/src/*` | import the public barrel `@karni/ui` |
| `karni/no-direct-http` | `fetch`/`axios`/`XMLHttpRequest`/`new WebSocket` outside `allowPatterns` (default `**/api/**`) | use the generated typed hooks / `KarniClient` |

The preset also turns `karni/no-direct-http` off for `**/*.test.*`,
`**/mocks/**` and vitest setup files, sets
`linterOptions.reportUnusedDisableDirectives: "error"`, and requires a
description on every disable comment
(`@eslint-community/eslint-comments/require-description`). Opt-out is
ESLint's own, with the reason mandatory:
`// eslint-disable-next-line karni/no-direct-http -- <reason>` — a bare
disable, or an unused one, is itself an error.

Component roles: every top-level component claims a semantic role via
`registerComponentRole(role, name)` — the `role` argument must be a string
literal, because `generate-manifest.mjs` statically scans the call sites,
fails the build on duplicate roles (and on non-literal roles), and emits the
`"roles"` map into `dist/manifest.json`. At runtime, re-registering the same
role + name is idempotent; a different name throws at import time (vitest and
prod builds fail), except under the Vite dev server's HMR, where it replaces
and logs a `console.error` instead of killing the app. Replacing on purpose:
`registerComponentRole(role, name, { replace: true, reason: "..." })` — an
empty reason throws. The registry (`getRoleRegistry()`) reflects imported
modules only.
