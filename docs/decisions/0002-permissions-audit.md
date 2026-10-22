---
description: "ADR 0002: the audit of Karni's permission and admin surface that precedes the roles, row scoping, field visibility, history, matrix and import/export work."
---

# ADR 0002 — Permissions and admin: audit before the retrofits

*Status: accepted 2026-10-18 (P0 of the Permissions & Admin sequence). No code
changed in this session. Since then: P1 (roles as data), P2 (row-level
scoping — `Granted()`, the admin's row scope, `scope_exempt`, the `grant`
isolation dimension), P3 (field-level visibility — `Karni.field_roles`,
per-role serializer, schema and admin, the ordering/filter/search oracles
closed), P4 (change history — `karni.audit`, `Karni.audit`, the History
tab, `/history/`, `<ChangeHistory/>`, `audited-bulk-write`), P5 (the
permission matrix — the admin page, its guard rails, effective permissions,
`api/auth/permissions/`, `RolePermission.origin`), P6 (import and export
— `karni.transfer`, `/export/`, the four-step import with its mandatory dry
run, audit batches, `<ResourceImport/>`), M1 (the `karni-approvals`
module on the new `karni.signals.pre_write` hook) and M2 (the
`karni-impersonation` module on the new `karni.vetoes` registry) have
shipped — the sequence is complete; §2 below describes the state before
them.*

This audits Karni's permission surface before the six retrofits (P1 roles as
data, P2 row-level scoping, P3 field-level visibility, P4 change history, P5
the permission matrix, P6 import/export) and the two modules (approvals,
impersonation). Each gap is ranked by blast radius — what leaks or forks when
it is missing — and priced in the lines of project code a typical app writes
today because Karni does not provide it.

## 1. Where role names live

Every occurrence of `staff`, `user`, `customer` (and the examples' `organizer`,
`editor`, `admin`) as a string literal in `packages/karni` was checked:

| Where | What it is | Project can replace without editing karni? |
|---|---|---|
| `karni/api/access.py` (docstrings, error text) | examples: `HasRole("staff")`, `Owned("organizer")` | yes — prose only |
| `karni/errorcodes/__init__.py` E103/E105/E109 fix text | examples | yes — prose only |
| `karni/testing/api.py`, `isolation.py`, `pytest_plugin.py` | examples in docstrings | yes |
| `karni/accounts/permissions.py:95` | `RolePermission.for_roles("editor", "admin")` in a docstring | yes |
| `karni/accounts/permissions.py:135,169` | `owner_field = "user"` — a **field name** default on the legacy `IsOwner` / `ObjectPermissionsMixin`, not a role | yes (class attribute) |
| `karni/introspect.py:21`, `karni/admin/__init__.py:64` | `"admin"` as an **app label** to skip | n/a |

**Finding:** no code path in `karni` compares a role to a literal. Roles are
Django groups; `HasRole("x")` and `assign_role(user, "x")` create and read
groups by name, so a project with a role called `warehouse_manager` needs no
karni edit today. What breaks instead is everything *around* the name:

- there is no declared role set — a role exists only because some `access`
  declaration or `assign_role` call mentions it, so `karni context` cannot
  list roles, a typo creates a silent new role, and nothing says which roles
  are system roles;
- `karni seed` derives the roles to grant the demo login by scanning `access`
  declarations for `HasRole` names (`seeding._Run.roles()`), which is the
  only "role registry" that exists, and it is indirect;
- a role's *reach* (which rows, which fields) is written in code per viewset
  (`Owned("organizer") | HasRole("staff")`), so granting a role more or fewer
  rows is a code change and a deploy.

So the fork risk P1 names is real, but it is not in `karni.accounts`; it is in
every project's `viewsets.py`, where role policy lives as code.

## 2. What enforcement exists today

| Capability | Status | Code |
|---|---|---|
| Role check on an endpoint | **present** | `karni.api.access.HasRole` in the `access` declaration: the request gate (`AccessPermission.has_permission`) and the row filter (`rows()` → all rows for holders). Legacy `karni.accounts.permissions.RolePermission` for plain DRF views. |
| Row-level scoping | **present, static** | `Owned(path)` (direct or traversal, to-many with `distinct()`), `Where(fn)`, `|`/`&`, compiled into `BaseViewSet.get_queryset()`; out-of-scope detail → 404 (ADR 2.4); relation-field PKs and `?expand=` go through the target viewset's read scope (2.5); owner stamping on create. **Absent:** a per-role scope (`all` / `own` / `related` / custom) chosen as data; the same scope applied in the admin; any export (there is none to scope). The admin (`karni.admin.soft_delete.SoftDeleteAdminMixin.get_queryset`) lifts only `soft_delete`; a staff user with admin access sees every row of every model. |
| Field-level masking | **absent** | `APIMeta.read_only` / `write_only` / `exclude` apply to everyone. A role that must not see `salary` needs a second serializer (`karni make serializer --reason`) and a `get_serializer_class()` branch per role, in every viewset, and the admin, filters and ordering still expose the field. |
| Field-level change history | **absent** | `AuditedModel` records *who* (`created_by`, `updated_by`) and *when*; nothing records *what changed*. No history endpoint, admin tab or component. |
| A UI for changing who can do what, no deploy | **absent** | Django's admin still shows Group permissions, but `access` ignores Django model permissions, so editing them changes nothing — a misleading screen. |
| Generic import/export for master data | **absent** | EventHub wrote its attendee CSV export by hand (`examples/eventhub/FRICTION.md` F3); `.learning` records doc_ACA's hand-rolled export that splats client-supplied column names into `.values()`. No importer exists anywhere. |

## 3. What ADR 0001 chose, and whether the code matches

ADR 0001 Decision 2 (rulings 2.1–2.8) chose **layered, queryset-authoritative
enforcement compiled from one mandatory `access` declaration** — gate and row
filter from the same predicate, 404 out of scope, scoped relation fields and
expansion, auto-wrapped `get_queryset`, a closed vocabulary of `Owned`,
`HasRole`, `Authenticated`, `Public`, `Where`, `Unscoped`.

**The code matches it.** `karni/api/access.py` compiles both layers;
`viewset-access` fails the build on a missing declaration; `assert_crud` and
`assert_isolated` prove the 404/403 split and the isolation for every
resource; EventHub's four viewsets are declared this way.

Ruling 2.2 is the hinge for this sequence: *"`HasRole(...)` over Django
Groups now. The `Can("area:action")` slot is reserved for a later DB-grants
tier; declarations written against `HasRole` keep working."* P1 and P2 **are**
that tier. They do not replace the `access` declaration — they give it a
predicate whose answer is data.

## 4. What my own past projects did

`.learning/PATTERNS.md` (the extraction across ~20 projects):

- **Pattern 6, weighted 14, ten projects:** role enforcement diverged from
  hard-coded `IsX` permission classes on a `role` CharField (five projects)
  to bhukailasa's **DB-backed `area:action` grants with wildcards and a single
  `require()` factory every route must take** — recommended there as the
  core default. Karni today sits between: declarations in code, roles as
  groups, no grants table. P1's `user.can(action)` and `@requires(action)` is
  bhukailasa's factory; P2's scopes are what that project lacked.
- **Pattern 37, three projects:** tenant/branch scoping done once well
  (xperso's `TenantScopedMixin`: a single enforcement point, stamps the owner,
  never trusts the body, isolation tests). Karni's `Owned` + `assert_isolated`
  matches the shape; the admin was not covered there either.
- **Pattern 19, weighted 8, five projects:** audit logging diverged (a
  library, thread-local + signals, explicit before/after JSON with IP,
  append-only). Weakness 13: three money-touching apps had no audit trail at
  all. P4 is this pattern as a default-off opt-in with redaction.
- **Pattern 34, eleven projects:** three independent "config-driven admin
  kits" and copy-paste admin screens — the permission matrix (P5) and
  import/export (P6) are the two screens those kits rebuilt most.
- **Weakness 9:** client-side permission walls that fail open (doc_ACA).
  Karni's doctrine already puts the wall on the queryset; P3 extends it to
  fields so the client never has to hide anything.
- **Weakness 19:** hand-parsed export endpoints. P6 replaces them.

Where the corpus and Karni's current design diverge: the corpus's best
project put policy in the database; Karni put it in a declaration. The
retrofits keep the declaration (it is what an agent reads and the build
checks) and let its predicate read the database.

## 5. What the gaps cost, in project lines

Estimates per typical app (10 models, 3 roles), from EventHub and the corpus:

| Gap | Lines a project writes today | Why |
|---|---|---|
| P2 row scoping as data, in the admin and exports | ~150 | a `get_queryset` or `Where` per viewset the role policy touches (~8 lines × N), the same filter copied into every admin class and export; **and the one copy an agent forgets is a leak, not a bug** |
| P3 field-level visibility | ~450 | one serializer per role per model (3 × 10 × ~15 lines) plus `get_serializer_class()` branches, plus the admin/filter/ordering holes nobody closes |
| P4 change history | ~250–350 | a history model, `pre_save` snapshot + signals, a diff helper, redaction, an admin tab and an API endpoint |
| P1 roles as data | ~120 | role constants, a seed of groups, helpers, and `karni context` blindness; the real cost is the fork when a role needs a scope the code did not anticipate |
| P6 import/export | ~200 per import, ~30 per export | parse, validate, preview, commit, template — rebuilt per model per project (FRICTION F3 is the export half) |
| P5 permission matrix | 0 lines, 1 deploy per change | every "give Priya access to invoices" is a code change today |

## 6. Ranked by blast radius, with the files each gap changes

1. **P2 — scoping as data, applied everywhere (data leak when missing).**
   `karni/api/access.py` (`Can` becomes real: gate + rows from grants),
   `karni/api/viewsets.py` (`Granted()` default path), `karni/admin/base.py`
   and `soft_delete.py` (scope in `get_queryset`), `karni/testing/isolation.py`
   and `api.py` (the matrix tests), `karni/agent/check.py` + `rules.py`
   (`scope_exempt` reasons listed), `karni-cli` generators (`--access
   granted`).
2. **P3 — field visibility (schema leak when missing).**
   `karni/api/serializers.py` (per-request field set), `karni/api/filters.py`
   and ordering (hidden fields are not filterable or orderable),
   `karni/api/schema.py` (per-role schema), `karni/admin/derive.py`,
   `@karni/ui` resource components (defensive filtering), P6's exporters.
3. **P1 — roles as data (fork risk; prerequisite of 2, 3, 5).**
   `karni/accounts/models.py` (+ migration), `permissions.py`,
   `karni/conf/base.py` (`KARNI_ROLES`), a `karni_sync_roles` command and
   `karni sync-roles` runner, `karni/introspect.py` (`ROLES:` line),
   `karni/seeding.py` (demo roles from the declared set), `docs/accounts.md`.
4. **P4 — change history (compliance gap).** New `karni/audit/`, hooks in
   `karni/models.py` (opt-in metadata), `BaseViewSet` history action, admin
   tab, `@karni/ui` `ChangeHistory`, a beat task, `karni check` rule for
   `update()` on audited models.
5. **P6 — import/export (leak if built before 2 and 3).** New
   `karni/api/exports.py` and `imports.py`, `BaseViewSet` actions, admin
   actions, `@karni/ui` `ResourceImport` and the table's export button,
   Celery task for large files.
6. **P5 — permission matrix (operational cost, needs 1 and 2).** New admin
   views on django-unfold, an API, guard rails, audit of the matrix itself.

## 7. Design settled here, so the retrofits agree with each other

These are the decisions P1–P6 implement; they keep ADR 0001's rulings intact.

- **The `access` declaration stays the single enforcement path.** The grants
  tier is a predicate, not a bypass: `Can("events:view")` answers the gate
  (does any of the user's roles hold a grant for that action?) and the rows
  (the union of the grants' scopes). `Granted()` is `Can` for the viewset's
  own model and the current action, so `access = Granted()` means "whatever
  the roles say", with scoping included — the default path P2 asks for,
  still an explicit declaration (ruling 2.1), still compiled into both layers
  (2.3), still 404 out of scope (2.4).
- **Roles stay Django groups.** `Role` is one-to-one with `Group` (slug,
  name, description, `is_system`); `user.roles` reads through `user.groups`.
  `HasRole`, `assign_role`, the admin, third-party apps and every existing
  declaration keep working; nothing is migrated away from groups.
- **Permissions are Karni's, not `auth.Permission`.** `Permission` is
  `(content_type, action)` where actions are `view/add/change/delete` plus
  the custom actions a model declares; `RolePermission` is the join and
  carries the scope (`all`, `own`, `related:<path>`, `custom:<name>`). Django's
  model permissions are left to the admin's own machinery and documented as
  unrelated to `access`.
- **A project declares roles in one place:** the `KARNI_ROLES` setting (the
  shipped default is `staff` / `user` / `customer`), reconciled by
  `karni sync-roles`, which creates and updates and *reports* but never
  deletes. Nothing in karni compares a role to a literal; the defaults are
  data in `karni.conf.base`.
- **Model metadata lives in `class Karni`:** `owner_field` (for the `own`
  scope; `created_by` when the model is audited and nothing is declared —
  a role-level scope declared in data, unlike `Owned()` in code, which keeps
  ruling 2.6), `scope_paths`, `actions`, and later `field_roles`, `audit`,
  `requires_approval`.
- **Per-request caching is mandatory:** the user's roles and grants are
  resolved once per request (the request-scoped store the current-user
  middleware already keeps) and never per object.
- **Boring defaults:** a new model with no `Karni` metadata and
  `access = Granted()` is fully visible to `staff`, scoped to its owner for
  `user`, and audited not at all. Every deviation is declared.
- **Tests are the deliverable:** `assert_isolated` grows the scope dimensions
  (`own`, `related`); `assert_crud` gains field-visibility checks;
  `karni.testing` ships the "cannot reach another scope through list,
  retrieve, update, delete, expand, filter, search, ordering, admin, export"
  matrix as one call.

## 8. Order

P1 → P2 (stop and try to break it) → P3 → P4 (independent; may interleave) →
P5 → P6 → modules M1, M2. Each is its own session, its own migration, and a
full run of the existing suites before the next.
