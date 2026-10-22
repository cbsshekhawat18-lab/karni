---
description: "ADR 0001: the tenancy shape, permission depth and performance defaults Karni's core is built on, with the code that implements each decision."
---

# ADR 0001: Core architecture (tenancy shape, permission depth, performance defaults)

| | |
|---|---|
| Status | **Accepted 2026-10-02.** The author accepted all recommendations. The binding rulings are in §7. |
| Date | 2026-10-02 |
| Scope | The query layer (`karni.managers`, `karni.models`), `BaseViewSet`, the generated serializers, pagination, and the testing/enforcement surface |
| Evidence | `.learning/PATTERNS.md` (P6, P19, P24, P25, P36, P37, weak practices 2, 8, 9), `.learning/GAPS.md` (§3 karni-tenancy, §4.2, §4.3, §4.7, §5.1), and the current source (cited as `path:line`) |
| Not decided here | Soft vs hard delete default (GAPS §4.7), token storage (§4.1), Celery profile (§4.4). Where they touch this ADR, it says so. |

**How to read the citations.** Paths are relative to `packages/karni/karni/` unless written in full.
`models.py`, `managers.py` and `middleware.py` are **in-flight**. They were rebuilt today to the
author's spec (TimestampedModel, UUIDModel, SoftDeleteModel, AuditedModel, BaseModel, a composable
`KarniQuerySet`, contextvars `CurrentUserMiddleware`). Their line numbers are as read at about 10:20
on 2026-10-02 and may drift. The tenancy analysis targets that rebuilt `BaseModel`.

---

## 0. Ground truth: the read path today

```
BaseViewSet.get_queryset()                     api/viewsets.py:157-177
  ├─ queryset.all() | model._default_manager.all()        :165-168
  │    └─ BaseManager.get_queryset → .filter(deleted_at__isnull=True)  managers.py:131-132
  ├─ self.filter_queryset_for_user(qs)  ← identity by default        :169 / accounts/permissions.py:190-201
  └─ select_related/prefetch_related for ?expand= paths ONLY          :170-176 / api/expansion.py:172-204
filter_queryset(): KarniFilterBackend → OrderingFilter → KarniSearchFilter   api/viewsets.py:100
paginate_queryset(): KarniPageNumberPagination (page_size 50, max 500)     pagination.py:21-22, conf/base.py:246-247
permission gate: DEFAULT_PERMISSION_CLASSES = IsAuthenticatedOrReadOnly   conf/base.py:244
```

These current facts drive the decisions below. All were found by reading the code. Items marked
"(by reading)" have not been exercised by a test.

| # | Fact | Where |
|---|---|---|
| F1 | Every auto-registered viewset can be read anonymously by default. | `conf/base.py:244`, `docs/api.md:3-8` |
| F2 | Row scoping is an opt-in override hook that does nothing by default. | `accounts/permissions.py:190-201` |
| F3 | If a subclass overrides `get_queryset()` without calling `super()`, row scoping and expand optimisation are both silently lost. | `api/viewsets.py:157-177` |
| F4 | `IsOwner` is object-level only, so DRF never runs it on `list`. Owner-only lists need `filter_queryset_for_user` as well. karni-payments does both by hand. | `accounts/permissions.py:115-143`, `modules/karni-payments/karni_payments/viewsets.py:78,81-93,150-158` |
| F5 | Generated relation fields validate PKs against `related_model._default_manager` (DRF's default). The target's viewset scoping does not apply, so a client can attach another user's object by PK (by reading). | `api/serializers.py:67-109` |
| F6 | `BaseModel` now carries `created_by`/`updated_by` FKs to the user. `?expand=` allows every non-auto-created FK, and the user serializer exposes `email`. Under F1, `GET /api/<any>/?expand=created_by` therefore returns creators' emails to anonymous callers (by reading). | `models.py:164-179`, `api/expansion.py:55-59`, `accounts/models.py:65-74` |
| F7 | Unexpanded M2M fields are in the default serializer field set. `ManyRelatedField` runs `.all()` once per row, so every list endpoint of a model with an M2M is N+1 out of the box (by reading). Nested serializers' own M2Ms are not prefetched either. | `api/serializers.py:230-234`, `api/expansion.py:172-204` |
| F8 | One test asserts a query count, and only on the expanded path. The framework has no per-endpoint budget. | `tests/api/test_expand.py:222-237` |
| F9 | Pagination can be switched off three ways with no error: `pagination_class = None` on a view, `REST_FRAMEWORK["PAGE_SIZE"] = None` (validation skips `None`), or a list-returning `@action`. | `conf/validation.py:185-191`, `pagination.py` |
| F10 | The derived admin already prevents changelist N+1 for FKs in `list_display`. | `admin/derive.py:186-197` |
| F11 | Two "see everything" managers exist that bypass any default-manager filter: `all_objects` on `SoftDeleteModel`/`BaseModel` and `SoftDeleteAdminMixin`'s queryset. | `models.py:106,211`, `admin/soft_delete.py:133` |
| F12 | `all_with_deleted()` is `super().get_queryset()`. What it drops depends on MRO position, not on a name. | `managers.py:124-140` |
| F13 | Module settings fragments may only add new top-level names. They cannot touch `MIDDLEWARE`, `INSTALLED_APPS` or `REST_FRAMEWORK`. | `docs/modules.md:93-102` |

---

## Decision 1: Multi-tenancy

### Evidence

PATTERNS P37 has weight 4 across three projects. The recommendation there was **MODULE**, adopting
xperso's single enforcement point plus dedicated isolation tests ("its audit found exactly the views
that bypassed it"). GAPS §3 sketches `karni-tenancy` as a viewset-level `TenantScopedMixin` built
on `filter_queryset_for_user`. The newest project (bhukailasa) is single-tenant. Nothing in the
corpus used schema-per-tenant or DB-per-tenant.

### Options

| | (a) Shared schema, `tenant_id` on every row | (b) Schema per tenant (Postgres schemas, django-tenants style) | (c) Database per tenant |
|---|---|---|---|
| **Isolation strength** | Logical only. One missing predicate leaks data. Postgres RLS can backstop it (policy on `current_setting('karni.tenant')`). | Namespace-level. Same DB role and connection. A wrong `search_path` leaks. | Physical. Separate credentials, backups and residency are possible. |
| **Migration complexity** | One `migrate`, as now. Adopting later means a column, backfill, NOT NULL and composite indexes on every scoped table, and **every global unique constraint becomes `(tenant, …)`**. | `migrate_schemas` runs O(tenants). It can fail partway and leave mixed versions. Apps must be split into SHARED/TENANT. | Migrations run O(DBs), with per-DB failure handling. |
| **Query overhead** | One indexed predicate per scoped table per query. Needs `(tenant_id, …)` composite indexes. Small. | No predicate, but `SET search_path` per transaction. pgbouncer transaction pooling needs per-transaction SET. Catalog bloat at thousands of schemas × tables. | No predicate. Connection pools multiply per tenant. |
| **Admin implications** | One admin. Tenant staff get a scoped changelist. Superusers can do cross-tenant views with an explicit unscoped mode and a tenant column. | One admin per schema. Cross-tenant reporting means unions across schemas outside the ORM. | One admin per DB. Cross-tenant work is impossible in the ORM. |
| **Interaction with BaseModel** | Needs a tenant FK on every scoped model and a tenant scope in the default manager pipeline. The rebuilt `BaseManager` is where it composes, next to soft delete (`managers.py:147`). | No model change. "Shared vs tenant" is per **app**, not per model. `karni.accounts`, `django_celery_beat`/`_results` and `token_blacklist` must be shared, and project apps are tenant. | No model change. A DB router picks `using=` from context, and Django's `DATABASES` must become dynamic. |
| **Interaction with auto-router** | No change. Same routes. The tenant comes from a context provider (subdomain, header or JWT claim), never from the URL prefix. | No change to routes. Hostname middleware must run before URL resolution. OpenAPI is identical across tenants. | No change to routes. Same as (b). |
| **Fit with Karni's settings/module contract** | Fits. A module adds a model, a scope and a context provider through entry points (F13 is respected). | Poor fit. It needs a custom DB `ENGINE`, `DATABASE_ROUTERS`, middleware placed first, and an app split. All of these are Django builtins that fragments cannot touch (F13), so core `conf/base.py:122-160` would change. The scaffold's `migrate` would also change. | "Deployment per tenant" (N compose stacks) fits with **zero** framework code. In-process DB switching fits poorly, for the same reasons as (b). |
| **Celery / beat / cache** | Tasks need the tenant bound from message headers. One beat. Cache keys get prefixed. | Tasks need the schema bound. Beat and results tables must be shared. | One worker pool per DB, or per-task DB binding. Beat per tenant. |
| **Cost to add later, BaseModel not shaped** | **High.** Every manager, every `get_queryset` override, every service query, every task, every unique constraint and all raw SQL. | Medium code, high ops (app split, data moved into schemas). | Deployment-per-tenant: none. In-process: medium. |
| **Cost to add later, BaseModel shaped as below** | **Low–medium.** Install the module, generate migrations, backfill a default tenant, fix global unique constraints. No hand-written query changes. | Unchanged (the shape does not help much). | Unchanged. |

### Recommendation

1. **Karni v1 ships single-tenant.**
2. When tenancy is built, **(a) shared schema** is the one Karni supports in-process, delivered as
   the `karni-tenancy` **module**. This follows PATTERNS P37: tenancy has a RAM/ops cost and is not
   universal, so by the CLAUDE.md rule it belongs in `modules/`.
3. **(c) is supported only as deployment-per-tenant** and documented. It needs no framework code
   and gives the strongest isolation for the few clients who need it.
4. **(b) is declined.** It is the only option that forces core changes to settings Karni and its
   modules are not allowed to retune (F13). Its per-app shared/tenant split also conflicts with
   `karni.accounts` and the Celery apps being unconditionally installed (`conf/base.py:122-150`).

**Where the tenant filter lives: this ADR diverges from GAPS §3. Both sides:**

| | Viewset-level (GAPS §3 / xperso: `TenantScopedMixin` via `filter_queryset_for_user`) | **Model-level (this ADR): a tenant scope in the default-manager pipeline** |
|---|---|---|
| Covers API list/detail | yes | yes |
| Covers Celery tasks, services, management commands | no | yes, or fails closed when no tenant is bound |
| Covers the derived admin (`admin/base.py`, stock `get_queryset`) | no | yes |
| Covers FK write validation (F5) and related descriptors and prefetches | no | yes. DRF uses `_default_manager`, and Django builds related managers from the default manager's class. |
| Visibility to an agent | explicit in the viewset | implicit. Mitigated by `karni context` printing the active scopes per model, and by errors that name the scope. |
| Historical evidence | xperso's audit found the views that bypassed it | soft delete already lives at this layer in the rebuilt `BaseModel` (`managers.py:131-132`) |

The xperso lesson is that a single enforcement point at the viewset layer still gets bypassed by
code that is not a viewset. A cross-tenant leak is the most expensive bug a multi-tenant product can
ship. **This ADR recommends the model level, failing closed, with GAPS §3's isolation-test helper
kept.** This is a recommendation only: see Q1.2.

### The deliverable: how BaseModel and the query layer must be shaped now

These shape decisions cost nearly nothing in v1, which has no tenant scope registered. They exist
so that installing `karni-tenancy` later changes **no hand-written project code**.

**S1. One named scope pipeline in the default manager.** `KarniQuerySet`'s manager applies an
ordered list of **named scopes**. It does not hard-code filters. Soft delete becomes the first
scope, `soft_delete`, replacing the literal filter at `managers.py:131-132`. Tenancy registers as
`tenant`. Order is fixed by each scope's `order` attribute. The order does not affect AND
semantics, but it does matter for removal and error messages.

**S2. Escape hatches remove one scope by name, never all of them.** `objects.all_with_deleted()`
and `deleted_only()` become `objects.without("soft_delete")` (and that plus `.dead()`). They must
**keep** a future tenant scope. F12's `super().get_queryset()` does not guarantee that, and F11's
`all_objects` drops everything. So `all_objects` (`models.py:106,211`) and its use in
`admin/soft_delete.py:133` go through a deprecation cycle (warn in the next minor, remove at the
next major, per CLAUDE.md). The in-flight rebuild is the cheapest moment to do this. General form:
`Model.objects.without("tenant", reason="cross-tenant billing report")`, where `reason` is required
and logged.

**S3. Writes are stamped by scopes too.** `AuditedModel.save()` already stamps from a contextvar
(`models.py:186-193`). Generalise this into a `stamp(instance, ctx)` step that every registered
scope gets on `save()` **and** on `KarniQuerySet.bulk_create()`. `bulk_create` skips `save()`, so it
is the hole to close now. The tenant scope stamps `tenant_id` and **raises** if no tenant is bound,
whereas audit stamping silently skips. The request body is never trusted (xperso rule).

**S4. One request context, not one contextvar per concern.** Generalise `middleware.py` from
"current request + user override" into `karni.context`. It holds the request plus values from
registered **context providers** (user today, tenant later), resolved lazily as the user already is
(`middleware.py:39-55`). `bind(**values)` is the explicit form for tasks, commands and tests.
`current_user()` stays as a thin alias, so the public API is unchanged. `karni/celery.py` copies
the bound context into task headers on publish and rebinds it on `task_prerun`.

**S5. Scope-owned fields are declared by the scope, not hard-coded.** The read-only sets in
`api/serializers.py:272-279` and `admin/derive.py:26` (`created_by`, `deleted_at`, …) become "core
fields ∪ fields owned by registered scopes". The tenant FK is then read-only in generated
serializers and hidden or read-only in the derived admin automatically.

**S6. Registration via entry points, override via a setting.** Scopes register through a
`karni.scopes` entry-point group, which mirrors the existing `karni.checks` group
(`packages/karni/pyproject.toml:39-41`). Context providers register through
`karni.context_providers`. A project-level `KARNI_SCOPES` list can reorder or disable them (the
escape hatch). Entry points rather than a settings fragment is forced by F13.

**S7. Field contribution without editing model source.** `karni-tenancy` adds `tenant =
ForeignKey(KARNI_TENANT_MODEL)` to scoped models from a `class_prepared` hook. That precedent comes
from django-modeltranslation, and `makemigrations` picks it up. All project `BaseModel` subclasses
are scoped by default. A model opts out with an inner `class ScopeMeta: tenant = "shared"`, which
follows the `APIMeta`/`AdminMeta` convention. **Alternative considered and rejected:** a nullable
`tenant_id` on `BaseModel` now. It would add a dead column to every table of every single-tenant
project, and `models.py:204-207` already warns that changing base fields ripples migrations into
every model, including the user.

**S8. Make bypassing the pipeline a build failure.** Add an architecture rule `manager-base`
(`testing/architecture.py`): a project model whose `objects` does not derive from Karni's manager
fails, with the usual `# karni: allow(manager-base): <reason>` opt-out. A plain
`objects = models.Manager()` today silently drops soft delete, and tomorrow it would drop tenancy.
The existing `raw-sql` rule (`testing/architecture.py:177-202`) becomes the tenant-leak guard. The
module makes `sql_allowed` paths subject to RLS.

**Residual cost, stated honestly.** Even with S1–S8, adopting tenancy needs three changes.
(1) Every `unique=True` / `UniqueConstraint` on a scoped model must become per-tenant, which is a
project edit plus a migration. (2) Raw SQL under `sql_allowed` must be reviewed. (3) Models meant
to be global need a one-line `ScopeMeta`. Nothing else changes in hand-written code.

### Implementation sketch

```python
# karni/scopes.py (core, new)
class Scope(Protocol):
    name: str                      # "soft_delete" | "tenant" | …
    order: int                     # soft_delete=10, tenant=20
    def applies_to(self, model: type[Model]) -> bool: ...
    def filter(self, qs: QuerySet, ctx: Context) -> QuerySet: ...   # raise ScopeContextMissing to fail closed
    def stamp(self, obj: Model, ctx: Context) -> None: ...
    def owned_fields(self, model: type[Model]) -> frozenset[str]: ...

# karni/managers.py
class KarniManager(Manager.from_queryset(BaseQuerySet)):
    def get_queryset(self):            return apply_scopes(super().get_queryset(), skip=())
    def without(self, *names, reason): log_unscope(self.model, names, reason)
                                       return apply_scopes(super().get_queryset(), skip=names)
    def all_with_deleted(self):        return self.without("soft_delete", reason="all_with_deleted")

# karni_tenancy (module, later)
class TenantScope:
    name, order = "tenant", 20
    def filter(self, qs, ctx):
        if ctx.tenant is None: raise ScopeContextMissing(qs.model, "tenant")
        return qs.filter(tenant_id=ctx.tenant.pk)
```

Migrations are unaffected: Karni managers do not set `use_in_migrations`, so historical models are
unscoped.

### Cost to reverse

- **Shape (S1–S8):** low. It is internal to `karni.managers`/`karni.context`. Dropping it means
  returning to the hard-coded soft-delete filter. Only the `all_objects` deprecation is user-visible,
  and it is the right change regardless.
- **Choosing (a):** moving to (b) or (c) later means a per-tenant data export into schemas or
  databases, which is ops-heavy but mechanical. Deployment-per-tenant stays available as a parallel
  offering at any time.

> **Questions for the author on Decision 1**
> 1. **Q1.1** Confirm: v1 is single-tenant. In-process tenancy will be (a) shared schema via a `karni-tenancy` module. (c) is offered only as deployment-per-tenant. (b) is declined.
> 2. **Q1.2** Where does the tenant filter live: **model-level scope pipeline (this ADR)** or **viewset-level `filter_queryset_for_user` mixin (GAPS §3 / xperso)**?
> 3. **Q1.3** When a scoped model is queried with no tenant bound (shell, command, task): **raise (recommended)**, return empty, or run unscoped?
> 4. **Q1.4** While the model rebuild is still open: approve replacing `all_objects` and `SoftDeleteManagerMixin`'s `super()`-based methods with named-scope removal (`objects.without("soft_delete")`), with `all_objects` going through a deprecation cycle?
> 5. **Q1.5** Users under tenancy: **shared users + `Membership(user, tenant, role)` (statox form)** or one tenant per user? This decides whether roles become per-tenant (ties to GAPS §4.3).
> 6. **Q1.6** When the module is installed: every project `BaseModel` is scoped unless marked `ScopeMeta.tenant = "shared"` (recommended), or each model opts in?
> 7. **Q1.7** Accept that global unique constraints on scoped models are a one-time project change when tenancy is adopted?
> 8. **Q1.8** Should Postgres RLS ship in the module as optional hardening (`KARNI_TENANCY_RLS`), or stay out of scope?

---

## Decision 2: Permission enforcement depth

### Evidence

PATTERNS P6 has weight 14, the second-sharpest change-over-time trail in the corpus.

- workland's external review found nearly every endpoint open and patched it afterwards.
- xperso ran three stacked authz systems, and its audit found the views that bypassed the scoping
  mixin.
- bhukailasa settled on "a resource cannot forget its gate".
- Weak practice 2 is default-allow. Weak practice 8 is "security helpers written but never wired".
- karni-payments is the in-repo proof that both layers are needed: `IsAuthenticated` plus
  `filter_queryset_for_user` with a role bypass (`viewsets.py:78,81-93`). Its "defence in depth:
  even with permissions swapped, non-admins see nothing" (`viewsets.py:153-158`) is the layered
  design written by hand.

### Options

| | (a) DRF permission classes | (b) Queryset-level scoping in BaseViewSet | (c) Both, layered |
|---|---|---|---|
| **What an omission does** | The endpoint falls back to the global default. Today that is anonymous read (F1). | All rows are visible to everyone who passes the gate. | The other layer still holds. |
| **How the failure shows up** | **Silently.** The agent's own happy-path tests pass, and an attacker finds it. | **Loudly.** The agent's own tests see 404s and empty lists. | Loud where (b) is the authoritative layer. |
| **List endpoints** | `has_permission` is all-or-nothing. `has_object_permission` never runs on list (F4). | Covered. | Covered. |
| **Detail/update/delete** | Via `get_object` → `has_object_permission` (403). | Via `get_object` over the scoped queryset (404, which does not reveal the row exists). | Both. |
| **Custom `@action`s** | Each must restate its classes (payments `refund`, `viewsets.py:126`). | Any action using `get_object()` or `get_queryset()` inherits the scope. | Inherits. |
| **FK writes (F5) and `?expand=` (F6)** | Not covered. | Covered only if relation and expansion querysets go through the **target's** scope. | Same. |
| **What opting out looks like** | **Absence**: nothing to grep. | **Presence**: an override, which can be detected by a rule. | Presence. |
| **Agent familiarity** | High. It is the DRF idiom agents know best. | Low. "Why is my row missing?" | Medium if both layers come from **one declaration**. |
| **Runtime cost** | ~0 queries (role checks: 1). | One predicate. Role lookups: 1, cacheable per request. | Sum of both, about the same. |

### Which agent failure is more dangerous?

**An agent forgetting a permission class is more dangerous.**

- Forgetting fails **open and silent**. The code that is missing leaves nothing to grep. The tests
  that would catch it are tests the agent did not think to write, for the same reason it forgot the
  class. The first person to see the bug is an outsider. F1 makes this concrete in Karni today: a
  forgotten `permission_classes` means anonymous read, and F6 shows it leaking user emails through
  `?expand=created_by`.
- Fighting a queryset filter fails **closed and loud**. The agent's test gets a 404 or an empty
  list immediately. The risk is not the filter. The risk is how the agent "fixes" it: overriding
  `get_queryset()` without `super()` (F3), or stubbing `filter_queryset_for_user` to return the
  queryset unchanged. Both fixes are **visible code artifacts** that an architecture rule can
  catch. The soft-delete default manager in the rebuilt `BaseModel` is a live example of the
  fighting cost. A `unique` slug collides with an invisible soft-deleted row. That failure is
  confusing, but it is a 500/IntegrityError, not a leak.

So the design goal is: **make omission impossible or loud, and make the fight short and visible.**
Concretely:

- The scope is authoritative and runs even through overrides.
- Errors name the scope that hid the row.
- `karni context` prints each viewset's policy so the agent can see the filter before fighting it.
- Opting out is a named declaration with a mandatory reason.

### Recommendation

**(c) layered, with the queryset as the authoritative layer, and both layers generated from one
declaration on the viewset.** The agent writes one `access = …` line. Karni compiles it into:

1. a request-level gate (permission class) per action, and
2. a row-level `Q` applied in `get_queryset()`.

Neither layer can be forgotten, because neither is written by hand. The point of (a) is kept: an
early 401/403 before any query. The point of (b) is kept: lists, actions, relations and expansion
are all scoped.

**Open conflict GAPS §4.2 (default posture): both sides.** This ADR's design works under any
answer. What changes is what a viewset **with no `access` declaration** does:

| §4.2 option | Missing `access` means | For | Against |
|---|---|---|---|
| (a) `IsAuthenticated` default, with public reads made explicit (`access = Public(read=True)`) | Authenticated users see every row. | Smallest change. DRF-conventional. The agent's first request works. | Still fails open **inside** the authenticated population, which is the multi-user leak. |
| (b) Every `BaseViewSet` must declare `access`. Missing it is a build failure (architecture rule `viewset-access`) and deny-all at runtime. | Nothing. It does not build. | Closest to bhukailasa ("a route cannot exist without a gate"). Turns the silent failure into a loud one. | One more line per viewset. `docs/adding-an-entity.md`'s six-line viewset becomes seven. |
| (c) Keep `IsAuthenticatedOrReadOnly` + warning | Anonymous read. | No change. | F1 + F6. This is PATTERNS weak practice 2. |

The failure-mode analysis above points to (b). The author's history (P6) points to (b). That is
the author's ruling to make (Q2.1).

**Open conflict GAPS §4.3 (grant granularity): both sides.** The predicate vocabulary below has a
request-level `HasRole(...)` predicate. Today it is backed by Django Groups (`has_role`,
`accounts/permissions.py:72-81`). If the author adopts bhukailasa's DB-backed `area:action` grants,
the same slot gains `Can("events:update")`, backed by `Role`/`Grant` rows, and Groups stays as the
light tier. Declarations written against `HasRole` keep working either way. This ADR does not
choose (Q2.2).

### Object-level permissions without per-project reimplementation

"This organizer sees only their own events":

```python
class EventViewSet(BaseViewSet):
    model = Event
    access = Access(
        read=Owned("organizer") | HasRole("staff"),
        write=Owned("organizer"),
        create=Authenticated(),          # organizer is stamped server-side
    )
```

| Action | Behaviour |
|---|---|
| `list` | Queryset filtered by the `read` `Q`. |
| `retrieve` | `get_object()` over the read-scoped queryset. An out-of-scope row returns **404**. |
| `create` | Gate on `create`. The `Owned` field is stamped from `request.user` (scope stamping, S3) and is read-only in the generated serializer. |
| `update` / `partial_update` / `destroy` | Look up in the read scope. A row that is readable but not writable returns **403** (its existence is already known). An unreadable row returns 404. |
| Custom `@action` | Inherits `read` (safe methods) or `write` (unsafe). Override with `@action(access=…)`. |
| FK writes to this model from other resources | `KarniPrimaryKeyRelatedField` validates against the **target viewset's** `read` scope. It finds the target through the router's model→route map, which already exists for the schema (`api/schema.py:224`). This closes F5. |
| `?expand=` into this model | To-many prefetches use the target's `read` scope. To-one expansion into a row-scoped target is allowed only when listed in `expandable_fields`. This closes F6. |

Predicate vocabulary, kept small on purpose. Every predicate compiles to a `Q` (row-level) and/or a
bool (request-level):

- `Owned(path)` supports traversal (`"event__organizer"`) and to-many paths with automatic
  `distinct()`. `Owned()` with no argument can mean `created_by` (Q2.6).
- `HasRole(*names)` (or `Can(...)` under §4.3), `Authenticated()`, `Public()`.
- `Where(lambda request: Q(...))` for anything else.
- `|`, `&`.
- `Owned(..., bypass=HasRole("payments-admin"))` covers the payments pattern
  (`viewsets.py:81-93`) in one line.

This is the third real occurrence of owner scoping: payments ×2, workland/xperso in the corpus, and
`IsOwner`. That satisfies the three-occurrences rule.

**Making the scope hard to lose (F3).** `BaseViewSet.__init_subclass__` wraps any `get_queryset`
a subclass defines, so the compiled `read` scope is applied to whatever queryset it returns.
`def get_queryset(self): return Event.objects.filter(published=True)` is still owner-scoped.

### Escape hatches, from least to most drastic

1. **Change the declaration.** This covers almost every case.
2. **`Where(...)` predicate** for arbitrary row logic.
3. **Override `filter_queryset_for_user`.** The hook stays (`accounts/permissions.py:190`). A new
   architecture rule `access-override` requires `# karni: allow(access-override): <reason>`.
4. **`access = Unscoped(reason="public catalogue")`.** Explicit, greppable, listed by
   `karni context`, and shown in the OpenAPI `x-karni-access` extension.
5. **`auto_register = False` plus your own view.** The `viewset-base` rule still applies
   (`testing/architecture.py:80-121`).

**Precedence across layers (see §4):** role bypasses act on the row policy only. **No access
predicate can lift a model-level scope** (tenant, soft delete). Lifting one needs
`objects.without(name, reason=…)`.

### Cost to reverse

- **Layered → permission classes only:** low code cost (stop applying the compiled `Q`), but it is a
  security regression.
- **Default posture:** tightening later (to §4.2 (a) or (b)) is a breaking change for every project
  that relied on anonymous reads. Under the deprecation rule that is warn for one minor, then remove
  at the next major, which makes it **cheapest to decide before 1.0**.
- **The `access` declaration:** additive. `filter_queryset_for_user` and `IsOwner` remain valid for
  one deprecation cycle.

> **Questions for the author on Decision 2**
> 1. **Q2.1 (GAPS §4.2)** Default posture: (a) `IsAuthenticated` + explicit `Public(...)`, (b) mandatory `access` per viewset (build failure + runtime deny-all), or (c) status quo? Note F6 under (c).
> 2. **Q2.2 (GAPS §4.3)** Does the request-level predicate stay `HasRole` over Groups, or gain `Can("area:action")` over DB grants, with Groups as the light tier?
> 3. **Q2.3** Approve "layered, queryset authoritative, one `access` declaration compiled into both layers" as the enforcement model?
> 4. **Q2.4** Out-of-scope object: **404 (recommended)** or 403? Readable-but-not-writable: 403?
> 5. **Q2.5** Approve changing current behaviour so relation-field PK validation (F5) and `?expand=` (F6) respect the target viewset's read scope?
> 6. **Q2.6** May `Owned()` with no argument default to `created_by`, or must the owner field always be named? (`created_by` means "who created it", which differs from "who owns it" when staff create on someone's behalf.)
> 7. **Q2.7** Should `__init_subclass__` auto-wrap overridden `get_queryset` so the scope is always applied, or should an architecture rule just flag overrides that skip `super()`?
> 8. **Q2.8** Confirm the predicate vocabulary is closed at: `Owned`, `HasRole`/`Can`, `Authenticated`, `Public`, `Where`, `Unscoped`, `|`/`&`.

---

## Decision 3: Performance defaults

### Evidence

PATTERNS P25 (one pagination class, with the envelope baked into the CRUD factory) and the
weak-practice doctrine "a control ships wired in with opt-out, or it doesn't ship" (weak practice
8). There is no corpus evidence for query budgets: none of the 23 projects had one. This part is
driven by the agent-authoring premise, not by history. Today Karni covers only expanded paths
(F7, F8) and the admin changelist (F10).

### 3.1 Deriving `select_related` / `prefetch_related` automatically

| Option | Coverage | Risk |
|---|---|---|
| Expansion-only (today, `api/expansion.py:172-204`) | `?expand=` paths only. Misses F7's unexpanded M2M, nested serializers' own relations, and agent-written serializers. | N+1 on every M2M model's list. |
| **Serializer walker (recommended)** | Walks the serializer actually in use, whether generated or explicit. | Opaque fields (`SerializerMethodField`, properties) are invisible to it. Covered by hints + 3.2. |
| Auto-prefetch on FK access (django-auto-prefetch style) | Any attribute access. | Magic at the model layer. Hides cost from agents. Another dependency. |

**Recommendation: the serializer walker.** `karni/api/optimizer.py: optimize(qs, serializer_class,
hints)` runs inside `get_queryset()` after scoping (see §4):

| Serializer field | Derived optimisation |
|---|---|
| PK relation to a forward FK | none (DRF reads the `_id` attname) |
| `ManyRelatedField(source=s)` | `Prefetch(s, queryset=<target default manager>.only("pk"))` (fixes F7) |
| Nested serializer on a FK/O2O | `select_related(s)`, recursing with prefix |
| Nested serializer `many=True` | `Prefetch(s, queryset=optimize(<target scoped qs>, child))` |
| Dotted `source="venue.name"` | `select_related("venue")` |
| `SerializerMethodField`, model property | Opaque. Uses `APIMeta.prefetch` / `select` hints or viewset `select_related = […]` / `prefetch_related = […]`, which are merged. |

`related_lookups` becomes a special case of the walker. If GAPS §5.1 removes `?expand=`, the walker
is still needed for F7 (Q3.1).

### 3.2 A query counter that fails tests

An absolute threshold alone **does not detect N+1**: a test with one row passes either way. Two
mechanisms, both on by default:

| Mechanism | What it catches | How |
|---|---|---|
| **Per-endpoint budget** | Fat endpoints, and N+1 in any test that happens to use enough rows. | `BaseViewSet.dispatch` wraps the request in `connection.execute_wrapper`. It counts queries and compares them with `query_budget` for `(viewset, action)`. Modes come from `KARNI_QUERY_BUDGET_MODE`: `raise` in tests (via a `pytest11` plugin), `warn` in the dev profile (log + `X-Karni-Queries` header), `off` in prod. |
| **Scaling check (N-independence)** | N+1 itself. | `pytest --pyargs karni.testing.performance` (same pattern as `karni.testing.architecture`). For every routed viewset it seeds rows at N=2 and N=12 and asserts `queries(12) == queries(2)` for `list` and `retrieve`, using the project's `<app>/factories.py` (factory-boy, already in the stack). |

Default budget (`KARNI_QUERY_BUDGET` in `conf/base.py`), to be calibrated against the measured
baseline:

- `list`/`retrieve`: 8. This covers auth (1–2), role or grant lookup (1), `COUNT` (1), data (1),
  and about 3 prefetches.
- `create`/`update`/`partial_update`: 12.
- `destroy`: 10.
- `*`: 15.

Non-viewset views use `with karni.testing.query_budget(n): …`.

### 3.3 Pagination that cannot be disabled by accident

| Hole (F9) | Fix |
|---|---|
| `pagination_class = None` on a viewset | `BaseViewSet.__init_subclass__` raises `ImproperlyConfigured` unless the class declares `pagination = Unpaginated(max_rows=N, reason="…")`. That still slices at `max_rows` and sets `X-Karni-Truncated`. Any `KarniPagination` subclass, such as a new `KarniCursorPagination` for very large tables where `COUNT(*)` hurts, is accepted. |
| `REST_FRAMEWORK["PAGE_SIZE"] = None` / `DEFAULT_PAGINATION_CLASS` replaced | `conf/validation.py:_check_rest_framework` refuses to boot on `None`, or on a class that is not a `KarniPagination` subclass. |
| `@action(detail=False)` returning `Serializer(qs, many=True).data` | A new architecture rule, `unpaginated-action` (AST: `many=True` in a viewset action with no `paginate_queryset`), plus a `self.paginated_response(qs)` helper so the right path is shorter than the wrong one. |
| `max_page_size = 500` with depth-2 expansion (`pagination.py:22`) | Lower to 100 via `KARNI_MAX_PAGE_SIZE` (Q3.4). `ResourceTable` defaults to 25, so it is unaffected. |

### 3.4 Where the escape hatch lives

All of them are **on the viewset class body**, all are declarative, and every one that relaxes a
guarantee requires a `reason`:

```python
class ReportViewSet(BaseViewSet):
    model = Report
    query_budget = Budget(list=25, reason="per-row signed URLs, measured 2026-10")
    prefetch_related = ["sections__charts"]          # hint merged into the optimizer
    optimize = True                                  # False → only hints apply
    pagination = Unpaginated(max_rows=2000, reason="CSV export")
```

Global defaults live in settings. Static rules use the existing
`# karni: allow(<rule>): <reason>` marker (`docs/enforcement.md`). `karni context` lists every
relaxed budget and unpaginated viewset, so an agent sees the existing exceptions before adding a
new one.

### Cost to reverse

- **Optimizer:** low. It is additive. `optimize = False` or removing it returns to
  expansion-only. Risk: over-prefetching. Mitigated because to-many PK lists use `.only("pk")`.
- **Budget:** low. Set the mode to `off`. The scaling check is a separate suite.
- **Pagination guard:** loosening later is non-breaking. Tightening later breaks every project that
  disabled it, so **decide strict now**.

> **Questions for the author on Decision 3**
> 1. **Q3.1** Approve the serializer-walking optimizer replacing expansion-only lookups? Does the answer change if GAPS §5.1 drops `?expand=`?
> 2. **Q3.2** Scaling check data: require a factory-boy factory per routed model (a missing one fails `karni check`, with opt-out), or ship a minimal auto-fill in `karni.testing` (more magic, no project code)?
> 3. **Q3.3** Budget numbers (8/12/10/15) and modes (raise in tests / warn in dev / **off** in prod): or **log** in prod?
> 4. **Q3.4** Lower `max_page_size` from 500 to 100 (`KARNI_MAX_PAGE_SIZE`)?
> 5. **Q3.5** Make `pagination_class = None` a class-definition error (hatch: `Unpaginated(max_rows, reason)`), and refuse to boot on `PAGE_SIZE = None`?
> 6. **Q3.6** Unpaginated list `@action`s: a build-failing `unpaginated-action` rule, or only the `paginated_response()` helper plus docs?

---

## 4. Interactions between the decisions: one pipeline, one order

All three decisions meet in `BaseViewSet.get_queryset()`. The composition order is fixed:

```
READ
 1  Model._default_manager                         ← model-level scopes (Decision 1), always on
      1a soft_delete   (order 10)
      1b tenant        (order 20, module)
 2  explicit `queryset` / subclass get_queryset()  ← project code (auto-wrapped, Q2.7)
 3  access.read  Q                                 ← row policy (Decision 2)
 4  optimize(serializer) + hints                   ← Decision 3; prefetch querysets re-enter at step 1 for the target model
 5  filter backends: filters → ordering → search   ← api/viewsets.py:100
 6  pagination                                     ← Decision 3 guard
WRITE (save / bulk_create)
 1  tenant stamp (fails closed)  2  owner stamp from access (Owned)  3  audit stamp (created_by/updated_by)
```

| Rule | Why |
|---|---|
| **R1. Model scopes run before viewset scopes.** | Invariants (tenant, deleted) must hold for code that never touches a viewset: tasks, admin, relation validation. |
| **R2. A bypass never crosses a layer.** `HasRole("admin")` lifts the row policy, never the tenant. `objects.without("soft_delete")` keeps the tenant. | Removes the "admin sees other tenants' data" and "show deleted also shows other tenants" bugs (F11, F12). |
| **R3. Optimisation runs after scoping, and every `Prefetch` queryset is built from the target's default manager plus the target viewset's read scope.** | Prefetched and expanded rows obey the same rules as the target's own list (closes F6 for to-many). `select_related` cannot filter, which is why to-one expansion into row-scoped targets is opt-in (Decision 2 table). |
| **R4. Filtering and search run after scoping.** | A filter or search parameter can only narrow what the caller may already see. The search provider receives a scoped queryset. |
| **R5. Query budgets include scope and auth queries.** | Role and membership lookups are real cost. Cache them per request in `karni.context` so the budget stays flat. |
| **R6. Stamping order is tenant → owner → audit, and the stamped fields are read-only in the serializer (S5).** | The body never chooses tenant or owner. Audit records the actor even when an admin acts for an owner. |
| **R7. Out of scope at steps 1–3 returns 404. Visible but not writable returns 403.** | No existence oracle across tenants or owners. |

Tie to GAPS §4.7: if the author reverses the rebuilt `BaseModel`'s soft-delete default back to hard
delete plus audit snapshot, step 1a is not registered for those models. Nothing else in the
pipeline changes, which is the point of S1.

---

## 5. Existing Karni files each decision would change

Paths are repository-relative. Only files that exist today are listed. New files (`karni/scopes.py`,
`karni/context.py` or an expanded `karni/middleware.py`, `karni/api/optimizer.py`,
`karni/testing/performance.py`, `karni/testing/pytest_plugin.py`, `modules/karni-tenancy/`) are
**not** listed.

### Decision 1: Tenancy shape (now) and karni-tenancy (later)

| File | Change | When |
|---|---|---|
| `packages/karni/karni/managers.py` | Named scope pipeline replaces the hard-coded filter (`:124-147`). `without()`, `bulk_create` stamping. | now |
| `packages/karni/karni/models.py` | Deprecate `all_objects` (`:106,211`). Generalise `AuditedModel.save` stamping into scope stamping (`:186-193`). | now |
| `packages/karni/karni/middleware.py` | Becomes or delegates to `karni.context` with providers and `bind()`. `current_user()` is kept as an alias. | now |
| `packages/karni/karni/celery.py` | Propagate and rebind context through task headers. | now |
| `packages/karni/karni/conf/base.py` | `KARNI_SCOPES` default. Middleware entry (`:151-160`). | now |
| `packages/karni/karni/conf/validation.py` | Validate scope registry and order. | now |
| `packages/karni/karni/api/serializers.py` | Read-only set from scope-owned fields (`:272-279`). | now |
| `packages/karni/karni/api/viewsets.py` | Stamping in the create path. Pipeline stages (`:157-177`). | now |
| `packages/karni/karni/admin/derive.py` | `AUDIT_FIELDS` (`:26`) from scope-owned fields. | now |
| `packages/karni/karni/admin/soft_delete.py` | `all_objects` → `objects.without("soft_delete")` (`:105,127-133`). | now |
| `packages/karni/karni/admin/base.py` | Bind admin context. Superuser cross-tenant mode. | later |
| `packages/karni/karni/testing/architecture.py` | New `manager-base` rule. `raw-sql` messaging. | now |
| `packages/karni/karni/introspect.py` | Print active scopes per model. | now |
| `packages/karni/pyproject.toml` | `karni.scopes` / `karni.context_providers` entry-point groups. | now |
| `packages/karni/karni/accounts/models.py` | User is shared. Membership hook (Q1.5). | later |
| `packages/karni/karni/accounts/permissions.py` | `has_role` per tenant membership (`:72-81`). | later |
| `packages/karni/karni/accounts/api/views.py` | Register/login bind or create membership. | later |
| `modules/karni-payments/karni_payments/tasks.py`, `webhooks.py` | Bind the tenant from the `Payment` row before processing. | later |
| `packages/karni-ui/src/schema/client.ts` | Tenant header, only if the tenant is header-resolved. | later |
| `packages/karni/tests/test_models.py` (+ admin/api tests touching `all_objects`) | Scope pipeline and deprecation tests. | now |
| `docs/modules.md`, `docs/api.md`, `docs/admin.md`, `docs/enforcement.md` | Scope entry-point contract, `without()`, `manager-base` rule. | now |
| `templates/project/{{cookiecutter.project_slug}}/AGENTS.md` | "Model scopes and how to lift one" guidance. | now |

### Decision 2: Permission enforcement

| File | Change |
|---|---|
| `packages/karni/karni/conf/base.py` | `DEFAULT_PERMISSION_CLASSES` (`:244`) per Q2.1. |
| `packages/karni/karni/conf/validation.py` | Posture validation (e.g. refuse `AllowAny` as the global default outside dev). |
| `packages/karni/karni/accounts/permissions.py` | `Access` and predicates. `IsOwner`/`RolePermission` become compiled forms. `ObjectPermissionsMixin` (`:146-201`) applies the compiled scope. |
| `packages/karni/karni/api/viewsets.py` | `access` attribute. `__init_subclass__` wrapping `get_queryset`. 404/403 split in `get_object`. Per-action gates. |
| `packages/karni/karni/api/serializers.py` | Relation-field querysets go through the target's read scope (F5). Owner field read-only. |
| `packages/karni/karni/api/expansion.py` | Expansion respects the target scope. To-one opt-in (F6). |
| `packages/karni/karni/api/schema.py` | `x-karni-access` extension. Reuse `_route_for_model` (`:224`). |
| `packages/karni/karni/api/routers.py` | Under Q2.1(b): register deny-all for viewsets missing `access` (`:193-204`). |
| `packages/karni/karni/testing/architecture.py` | `viewset-access` and `access-override` rules. |
| `packages/karni/karni/introspect.py` | Print each viewset's policy. |
| `packages/karni/karni/accounts/models.py` | Only if Q2.2 adopts DB grants (`Role`/`Grant`). |
| `modules/karni-payments/karni_payments/viewsets.py` | Replace hand-written scoping (`:78-93,150-158`) with `access = …`. |
| `packages/karni-ui/src/auth/usePermission.ts`, `packages/karni-ui/src/schema/parse.ts`, `packages/karni-ui/src/schema/types.ts` | Read `x-karni-access` as display hints only. |
| `packages/karni/tests/api/*`, `packages/karni/tests/accounts/*` | Scoping, 404/403, relation and expansion tests. |
| `docs/api.md` (posture warning `:3-8`), `docs/accounts.md`, `docs/adding-an-entity.md`, `docs/enforcement.md` | Document `access` and the new rules. |
| `templates/project/{{cookiecutter.project_slug}}/AGENTS.md` | "Declare `access`. Never override `get_queryset` to widen". |

### Decision 3: Performance defaults

| File | Change |
|---|---|
| `packages/karni/karni/api/viewsets.py` | Optimizer call. Budget wrapper in `dispatch`. Pagination guard in `__init_subclass__`. `paginated_response()`. |
| `packages/karni/karni/api/expansion.py` | `related_lookups` (`:172-204`) is subsumed by the optimizer. |
| `packages/karni/karni/api/serializers.py` | `APIMeta.select` / `prefetch` hints. |
| `packages/karni/karni/pagination.py` | `KarniPagination` base. `max_page_size` from `KARNI_MAX_PAGE_SIZE` (`:22`). `Unpaginated`. Cursor variant. |
| `packages/karni/karni/conf/base.py` | `KARNI_QUERY_BUDGET`, `KARNI_QUERY_BUDGET_MODE`, `KARNI_MAX_PAGE_SIZE`. |
| `packages/karni/karni/conf/dev.py` | `warn` budget mode. |
| `packages/karni/karni/conf/validation.py` | Refuse `PAGE_SIZE=None` and non-Karni pagination classes (`:172-193`). |
| `packages/karni/karni/testing/__init__.py`, `packages/karni/karni/testing/architecture.py` | `query_budget()` helper. `unpaginated-action` rule. |
| `packages/karni/pyproject.toml` | `pytest11` plugin entry point. |
| `packages/karni/karni/admin/derive.py` | Optional: prefetch for M2M in `list_display` (FKs already handled, `:186-197`). |
| `packages/karni/karni/introspect.py` | List relaxed budgets and unpaginated viewsets. |
| `packages/karni/tests/api/test_expand.py` | Extend `:222-237` to the unexpanded M2M case (F7). |
| `packages/karni-ui/src/hooks/types.ts`, `packages/karni-ui/src/components/resource/select/ResourceSelect.tsx` | Only if Q3.4 lowers the cap below what callers request. |
| `docs/api.md`, `docs/enforcement.md`, `templates/project/{{cookiecutter.project_slug}}/AGENTS.md` | Budgets, hints, pagination rules. |

---

## 6. All questions for the author (to settle before implementation)

**Decision 1 (tenancy):** Q1.1 scope of support (a / deployment-per-tenant / not b) · Q1.2 model-level vs viewset-level filter (GAPS §3) · Q1.3 behaviour with no tenant bound · Q1.4 replace `all_objects` with named-scope removal during the in-flight rebuild · Q1.5 shared users + membership vs one tenant per user · Q1.6 scoped by default vs opt-in · Q1.7 accept the unique-constraint adoption cost · Q1.8 RLS in the module.

**Decision 2 (permissions):** Q2.1 default posture (GAPS §4.2) · Q2.2 Groups vs `area:action` grants (GAPS §4.3) · Q2.3 layered and queryset-authoritative via one `access` declaration · Q2.4 404 vs 403 · Q2.5 relation-field and expansion scoping · Q2.6 `Owned()` defaulting to `created_by` · Q2.7 auto-wrap `get_queryset` vs rule-only · Q2.8 closed predicate vocabulary.

**Decision 3 (performance):** Q3.1 serializer-walking optimizer (and if `?expand=` goes) · Q3.2 factories vs auto-fill for the scaling check · Q3.3 budget numbers and prod mode · Q3.4 `max_page_size` 500 → 100 · Q3.5 `pagination_class = None` as an error and refusing `PAGE_SIZE=None` · Q3.6 `unpaginated-action` rule vs helper only.

---

## 7. Rulings (accepted 2026-10-02)

The author accepted all recommendations. Where a question carried no bolded pick, the ruling
follows this document's own analysis. Those rulings are marked *(from analysis)*.

| Q | Ruling |
|---|---|
| 1.1 | v1 is single-tenant. Later in-process tenancy is (a), a shared schema via a `karni-tenancy` module. (c) is offered only as deployment-per-tenant, and documented. (b) is declined. |
| 1.2 | Tenant filter lives at the **model level**: a named scope in the default-manager pipeline, failing closed. GAPS §3's isolation-test helper is kept. |
| 1.3 | A scoped model queried with no tenant bound **raises**. |
| 1.4 | **Yes, now.** Named-scope removal `objects.without("soft_delete", reason=...)` replaces `all_objects` and the `super()`-based `all_with_deleted()` / `deleted_only()`. The old names go through a deprecation cycle (warn in 0.2, remove in 1.0). |
| 1.5 | *(from analysis)* Shared users + `Membership(user, tenant, role)`. Roles become per-tenant. Module-time decision, no v1 code. |
| 1.6 | With the module installed, every project `BaseModel` is scoped unless `ScopeMeta.tenant = "shared"`. |
| 1.7 | Accepted: global unique constraints on scoped models are a one-time change when tenancy is adopted. |
| 1.8 | *(from analysis)* Postgres RLS ships in the module as optional hardening (`KARNI_TENANCY_RLS`, off by default). Module-time. |
| 2.1 | **(b)** Every `BaseViewSet` must declare `access`. Missing it fails the build (`viewset-access` architecture rule) and denies everything at runtime. |
| 2.2 | *(from analysis)* `HasRole(...)` over Django Groups now. The `Can("area:action")` slot is reserved for a later DB-grants tier. Declarations written against `HasRole` keep working. |
| 2.3 | Layered, queryset authoritative, compiled from one `access` declaration. |
| 2.4 | Out of scope → **404**. Readable but not writable → 403. |
| 2.5 | Yes: relation-field PK validation and `?expand=` respect the target viewset's read scope. |
| 2.6 | *(from analysis)* The owner field must be named. `Owned()` without an argument is a class-definition error whose message names the fix. `created_by` is allowed only when written explicitly (`Owned("created_by")`). |
| 2.7 | *(from analysis)* `BaseViewSet.__init_subclass__` auto-wraps an overridden `get_queryset` so the scope always applies. Overriding `filter_queryset_for_user` needs `# karni: allow(access-override): <reason>`. |
| 2.8 | Closed vocabulary: `Owned`, `HasRole` (+ reserved `Can`), `Authenticated`, `Public`, `Where`, `Unscoped`, `|`, `&`. |
| 3.1 | Serializer-walking optimizer replaces expansion-only lookups. `?expand=` stays for now (GAPS §5.1 removal is a separate question). |
| 3.2 | *(from analysis, aligned with Phase 13)* Automatic factories from `karni.testing`. An explicit `<app>/factories.py` factory overrides them. No project code required. |
| 3.3 | Budgets list/retrieve 8, create/update 12, destroy 10, other 15. Modes: raise in tests, warn in dev, off in prod. |
| 3.4 | `max_page_size` 500 → 100 (`KARNI_MAX_PAGE_SIZE`). |
| 3.5 | `pagination_class = None` is a class-definition error (hatch: `Unpaginated(max_rows, reason)`). Boot refuses `PAGE_SIZE = None`. |
| 3.6 | *(from analysis)* Both: the build-failing `unpaginated-action` rule and the `paginated_response()` helper. |
| n/a | Soft delete stays in `BaseModel` (the author's prompt sequence). GAPS §4.7 is closed in its favour. |

