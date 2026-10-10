# karni.api

> **Posture — read first.** Every `BaseViewSet` must declare `access`; it is
> the only gate. A viewset without it answers **403 to every request** (the
> message names the fix) and fails the build (`viewset-access`). Nothing is
> anonymously readable unless the declaration says `Public()`. Set
> `auto_register = False` to keep a viewset off the router.

A model becomes a full API resource with four lines:

```python
# myapp/viewsets.py  (or myapp/api/viewsets.py)
from karni.api import Access, Authenticated, BaseViewSet, Public
from myapp.models import Event

class EventViewSet(BaseViewSet):
    model = Event
    access = Access(read=Public(), write=Authenticated())
    search_fields = ["title"]
```

That yields CRUD, filtering, pagination, ordering, search, access control,
N+1-free queries and a correct OpenAPI schema at `/api/events/`. Mount once:

```python
# config/urls.py
path("api/", include("karni.api.urls")),
```

## BaseViewSet

Declarative attributes (all optional except `model` and `access`):

| attribute | default | meaning |
|---|---|---|
| `model` | — | drives queryset, serializer, filters, route |
| `access` | — (**required**) | `Access(read=, write=, create=)` or `Unscoped(reason=)` — see [Access control](#access-control) |
| `serializer_class` | `None` | explicit class **always** beats generation |
| `queryset` | `model._default_manager.all()` | replace to pre-filter |
| `search_fields` | `()` | enables `?search=` via the search provider |
| `expand_depth` | `0` | server-side default expansion depth |
| `expandable_fields` | auto (forward FK/O2O/M2M) | mapping of expand key → relation; reverse relations only when listed explicitly |
| `auto_register` | `True` | `False` → auto-router skips it |
| `route` | kebab-plural of the model name | router prefix |
| `select_related` / `prefetch_related` | `()` | query hints merged into the derived lookups — see [Performance](#performance) |
| `optimize` | `True` | `False` → only the hints apply |
| `query_budget` | `None` (`KARNI_QUERY_BUDGET`) | `Budget(list=25, reason=...)` |
| `pagination` | `None` (`pagination_class`) | `Unpaginated(max_rows=N, reason=...)` — the only way to return plain lists |
| `cache` | `None` (`KARNI_API_CACHE`) | `Uncached(reason=...)` or `Cache(ttl=..., depends_on=[...])` |

Default ordering: model `Meta.ordering`, else `-created_at` when the field
exists, else `-pk`. Every normal DRF hook (`get_queryset`,
`get_serializer_class`, `permission_classes`, `filterset_class`, …) remains
overridable — `BaseViewSet` is a plain `ModelViewSet` underneath, plus
`ObjectPermissionsMixin` (`filter_queryset_for_user`) from `karni.accounts`.
Overriding `get_queryset` (with or without `super()`) never loses the access
scope: `BaseViewSet.__init_subclass__` wraps it.

## Access control

One declaration per viewset (ADR 0001, Decision 2), compiled into **both**
enforcement layers:

1. a **request gate** — a DRF permission (`karni.api.access.AccessPermission`)
   that `get_permissions()` always puts first: 401/403 before any query;
2. a **row filter** — the `read` predicate as a `Q`, applied in
   `get_queryset()`. It is authoritative: lists, details, custom actions,
   relation-field PK validation and `?expand=` all go through it.

```python
from karni.api import Access, Authenticated, BaseViewSet, HasRole, Owned

class EventViewSet(BaseViewSet):
    model = Event
    access = Access(
        read=Owned("organizer") | HasRole("staff"),
        write=Owned("organizer"),
        create=Authenticated(),        # organizer is stamped server-side
    )
```

The vocabulary is closed — every predicate has a request-level and a
row-level answer:

| predicate | gate | rows |
|---|---|---|
| `Public()` | everyone | all |
| `Authenticated()` | authenticated users | all (none for anonymous) |
| `HasRole("a", "b")` | holds any of the roles (Django groups, one query per request) | all for holders, none otherwise |
| `Owned("organizer")` | authenticated users | `organizer = request.user`; traversals (`"event__organizer"`) and to-many paths (`"members"`, automatic `distinct()`) work; `Owned("pk")` on the user model |
| `Owned("user", bypass=HasRole("x"))` | same as `Owned("user") \| HasRole("x")` | |
| `Where(lambda request: Q(...))` | passes (or the function returns a `bool` for both) | the returned `Q` |
| `a \| b`, `a & b` | any / all | OR / AND of the row filters |
| `Can("area:action")` | reserved for DB-backed grants — raises today | |

`Owned()` without a field is a class-definition error that names the fix
(`created_by` only when written explicitly). An `Owned` path that does not
lead to the user model fails at class definition too. Python's `or`/`and`
on predicates raise `TypeError` — use `|`/`&`.

Which predicate governs which action:

| action | predicate | out of scope |
|---|---|---|
| `list` | `read` | row not listed |
| `retrieve`, safe custom `@action` | `read` | **404** (the message names the read scope; no existence oracle) |
| `create` | `create` (default: `write`) | 401/403 at the gate |
| `update` / `partial_update` / `destroy`, unsafe custom `@action` | `write`, row looked up through `read` | unreadable → **404**; readable but not writable → **403** |
| `@action(detail=True, methods=["post"], access=HasRole("x"))` | that predicate; the lookup still goes through `read` | as above |

Owner fields: a direct FK to the user model named by `Owned` in `write` or
`create` is stamped from `request.user` on create (`perform_create`) and is
read-only in the generated serializer — the body never chooses the owner.

**Posture and DRF permissions.** `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`
(Karni default: `IsAuthenticated`) is **not** consulted for a viewset with an
`Access` declaration — the declaration is the gate, so a permissive project
default cannot open one. `permission_classes` set on a viewset (or an
`@action`) are ANDed **after** the access gate: they can only narrow. The
DRF default still covers plain DRF views and `Unscoped` viewsets.

**Model scopes cannot be lifted.** The row filter is only ever `filter()`-ed
onto the model's default manager, so no predicate (`HasRole` bypasses
included) can reach soft-deleted rows or, later, another tenant's rows.
Lifting a model scope takes `Model.objects.without(name, reason=...)`.

**Relations and expansion follow the target's scope.** A writable relation
field of a generated serializer (`KarniPrimaryKeyRelatedField`) accepts only
primary keys of rows the requester can read through the **target** model's
viewset; an out-of-scope PK fails exactly like a missing one. `?expand=`
embeds only readable rows: to-many levels are scoped `Prefetch`es, and a
to-one level into a narrowed target becomes a scoped `Prefetch` too (one
extra query; an unreadable target renders as `null`). The target viewset is
the **first viewset registered for the target model on the `KARNI_API_ROUTER`
router** (`karni.api.routers.viewset_for_model`, the same map
`x-karni-relation` uses); its `access.read` and `filter_queryset_for_user`
apply, its own `get_queryset` does not. A target with **no routed viewset**
(`auto_register = False` and not registered explicitly, or simply no
viewset) is not an API resource and has no row policy: PKs and expansion use
its default manager, so model scopes still hold. A target whose viewset has
no `access` accepts no PK and expands to nothing. Serializers used without a
request in their context (server-side code) are not narrowed.

Escape hatches, least to most drastic:

1. change the declaration;
2. `Where(...)` for arbitrary row logic, `@action(access=...)` for one action,
   `get_access()` to compute the declaration per request;
3. override `filter_queryset_for_user(queryset)` — it receives the
   access-scoped queryset; the `access-override` rule requires
   `# karni: allow(access-override): <reason>`;
4. `access = Unscoped(reason="...")` — no compiled gate, no row policy: the
   viewset's `permission_classes` (else the DRF default) decide, rows are
   limited only by model scopes and `filter_queryset_for_user`; the reason is
   published as `x-karni-access`;
5. `auto_register = False` plus your own view (the `viewset-base` rule still
   applies).

Deprecated: `object_permission_classes` on a `BaseViewSet` warns
(`KarniDeprecationWarning`) and is removed in 1.0 — it still runs, after the
access object check. Express the rule in `access` instead
([migration note](migrations/0.2.md#object_permission_classes); `karni upgrade`
lists every viewset that sets it). `IsOwner`,
`RolePermission` and `ObjectPermissionsMixin` remain for plain DRF views
(see [accounts](accounts.md#roles-and-object-permissions)).

## APIMeta — model-side API metadata

```python
class Event(BaseModel):
    ...
    class APIMeta:
        fields = [...]        # or exclude = [...] (mutually exclusive)
        read_only = ["status"]
        write_only = ["internal_note"]
        schema_name = "Event"  # optional: replaces the AppLabelModel stem
        select = ["venue"]     # optional query hints for properties listed in fields
        prefetch = ["tags"]    #   (see Performance → Query optimisation)
        validate = True        # run Model.clean() on create/update (default)
```

**Model validation.** A domain invariant lives in the model's `clean()`:

```python
class Booking(BaseModel):
    def clean(self):
        if self.quantity > self.tier.remaining:
            raise ValidationError({"quantity": f"Only {self.tier.remaining} seats left."})
```

The generated serializer runs `clean()` on the would-be row before every
create and update — including the values the viewset stamps on save, such as
owner fields — and a `django.core.exceptions.ValidationError` becomes the 400
response, keyed by field. No serializer is needed for a cross-field rule.
Opt out per model with `APIMeta.validate = False`; an explicit
`serializer_class` built on `KarniModelSerializer` keeps the behaviour and can
override `run_model_clean()`.

Rules enforced at build time (violations raise `ImproperlyConfigured` naming
the model):

- `fields` and `exclude` are mutually exclusive; `read_only`/`write_only`
  must be subsets of the effective fields.
- `id`, `created_at`, `updated_at` (from `BaseModel`) are always read-only.
- Password-named `CharField`s are never auto-exposed. User-like models
  (`AbstractBaseUser`/`PermissionsMixin` subclasses) additionally force
  `last_login`, `is_staff`, `is_superuser`, `is_active`, `groups`,
  `user_permissions` read-only.
- M2M fields are writable by default — mark them in `read_only` to freeze.

Generated serializers get deterministic app-qualified component names
(`MyappEventSerializer`, expanded variants suffixed per expand path), so
schema components never collide across apps. An explicit `serializer_class`
(`karni make serializer`) is named by drf-spectacular from its class name
(`EventSerializer` → `Event`), so switching to one changes the schema
snapshot and the generated frontend types once; `x-karni-access.owned` is
published only when the read predicate is a single `Owned(...)`. Top-level generated classes are
cached per `(model, expand-set, max-depth)`; `build_serializer.cache_clear()`
resets the cache (it also resets when `KARNI_API_MAX_EXPAND_DEPTH` changes
under `override_settings`).

## Filtering

`KarniFilterBackend` auto-derives a FilterSet when a `BaseViewSet` (or a view
setting `karni_auto_filterset = True`) declares no `filterset_class`/
`filterset_fields` — for any other view it behaves exactly like stock
`DjangoFilterBackend`. Derived lookups:

| field type | lookups |
|---|---|
| Char/Slug/Email | `exact`, `icontains` |
| Int/Float/Decimal/Date/DateTime | `exact`, `gte`, `lte` |
| Boolean | `exact` |
| FK/O2O | `exact` (typed by the target pk — UUID pks get a UUID filter) |
| fields with `choices` | `exact` via `ChoiceFilter` (stays an enum) |

Excluded from derivation: `TextField` (unindexed seq scans — opt back in
with explicit `filterset_fields`), File/Image/JSON/binary fields,
`APIMeta.write_only`/excluded fields, and password-named fields. The
type→lookups map is the overridable `lookup_map` class attribute on
`KarniFilterBackend`. Explicit `filterset_*` on the viewset always wins,
untouched.

## Expansion

`?expand=organizer,venue` inlines related objects; dotted paths
(`?expand=venue.city_ref`) nest. Multiple `expand` params merge.

- Allowed keys per level: `expandable_fields` or all forward FK/O2O/M2M
  names; each dotted segment is validated against the model at that level
  and an unknown key answers 400 listing the allowed keys there.
- Depth is capped by `KARNI_API_MAX_EXPAND_DEPTH` (env, default 2) — deeper
  paths answer 400. Cycles stop at the PK.
- Expanded relations are just nested serializers to the
  [query optimiser](#query-optimisation): `select_related` for FK/O2O paths
  into targets whose read scope keeps every row, a scoped `Prefetch` for any
  M2M/reverse segment or narrowed target — so expansion adds no N+1.
- Expanded nested representations are read-only; writes keep using PKs.
- Only rows the requester can read are embedded — every level goes through
  its target's read scope (see [Access control](#access-control)); a to-one
  target outside it renders as `null`.

`karni.api.expansion.related_lookups()` and `scoped_related_lookups()` are
deprecated (they warn; removed in 1.0): the optimiser derives the same
lookups from the expanded serializer — call `karni.api.optimizer.optimize()`.

v0.1 bound: each distinct expand-set builds (and caches) one serializer
class; pathological clients can grow that cache breadth-wise. The cap on
depth bounds each entry's size; clear with `build_serializer.cache_clear()`.

## Performance

ADR 0001 Decision 3. Four defaults, all on without project code, each with
an escape hatch that is a declaration on the viewset — never silence. `karni
context` lists every declared exception (`PERF:` line) so you see the
existing ones before adding another.

### Query optimisation

Every `list` and `retrieve` runs the queryset through
`karni.api.optimizer.optimize()` after the access scope: it walks the
serializer that will render the response — generated, expanded or
hand-written, nested to any depth — and derives the lookups:

| Serializer field | Derived |
|---|---|
| PK relation over a forward FK/O2O | nothing (DRF reads the `*_id` column) |
| PK list over an M2M / reverse FK | `Prefetch(name, queryset=<target>.only("pk"))` |
| nested serializer on a FK/O2O | `select_related(name)`, recursing with the prefix |
| nested serializer `many=True` | `Prefetch(name, queryset=<optimised target queryset>)` |
| dotted `source="venue.city.name"` | `select_related("venue__city")` |
| `SlugRelatedField`, `StringRelatedField`, … | `select_related` / a full-row `Prefetch` |
| `SerializerMethodField`, a model property | opaque — needs a hint |

Every `Prefetch` queryset starts at the target's default manager (soft delete
and other model scopes) narrowed by the **target viewset's read scope**, and
a to-one level into a narrowed target is a scoped `Prefetch` instead of a
join, so an unreadable row renders as `null` (ADR 0001 R3). Measured: a
publisher list nesting writers → novels → chapters (+ an M2M PK list and an
M2M slug list) costs **6 queries at 2 or 12 publishers**; with
`optimize = False` it costs 32 and 182 (`tests/api/test_optimizer.py`).

Hints for what the walker cannot see — merged with the derived lookups, never
replacing them:

```python
class NovelViewSet(BaseViewSet):
    model = Novel
    access = Access(read=Public(), write=Authenticated())
    serializer_class = NovelSerializer   # has chapter_count = SerializerMethodField()
    prefetch_related = ["chapters"]      # what get_chapter_count reads
    select_related = []                  # same, for to-one reads

class Novel(BaseModel):
    ...
    class APIMeta:
        select = ["writer"]              # for the writer_name property in APIMeta.fields;
        prefetch = []                    # applied wherever Novel is rendered, at any depth
```

A hint string is applied as written (model scopes apply, the target viewset's
read scope does not); a hinted `Prefetch(...)` owns its whole subtree; and a
lookup already on the incoming queryset (`queryset = ...prefetch_related(...)`)
wins over a derived one at the same level. `optimize = False` keeps only the
hints; override `optimize_queryset(queryset, serializer_class=None)` for a
hand-built strategy. Custom actions are not optimised automatically — return
`self.paginated_response(qs)` (which is) or call `self.optimize_queryset(qs)`.

### Query budgets

Every `BaseViewSet` request is counted (auth, role lookups and the
pagination `COUNT` included — ADR 0001 R5) against its action's budget:

| Action | Budget (`KARNI_QUERY_BUDGET`) |
|---|---|
| `list`, `retrieve` | 8 |
| `create`, `update`, `partial_update` | 12 |
| `destroy` | 10 |
| anything else (`"*"`) | 15 |

`KARNI_QUERY_BUDGET_MODE` decides what an overrun does: `raise` in tests (the
`karni` pytest plugin sets it — see [testing](testing.md)), `warn` in the dev
profile (a log line with the grouped duplicate report), `off` in production
(no wrapper at all). Both counting modes set `X-Karni-Queries` (and
`X-Karni-Query-Budget`). The failure names the repeated statement and what
rendered it:

```
EventViewSet.list ran 14 queries; budget is 8.
14 queries, 12 duplicated, 3.1 ms in SQL
  12× SELECT … FROM "app_tag" INNER JOIN "app_event_tags" ON … WHERE … = %s
      ← EventSerializer.tag_names (app/serializers.py:41 in get_tag_names)
```

**Raising a budget** is a declaration with a reason:

```python
class ReportViewSet(BaseViewSet):
    model = Report
    access = Access(read=HasRole("staff"), write=HasRole("staff"))
    query_budget = Budget(list=25, reason="per-row signed URLs, measured 2026-10")
    # Budget(export=None, reason=...) stops checking one action;
    # Budget(default=20, reason=...) covers every action not named.
```

`Budget` keys are action names (typos fail at class definition); unnamed
actions keep the project budget. Project-wide: `KARNI_QUERY_BUDGET = {"list":
10}` (a partial dict merged over the defaults). Non-viewset code: `with
karni.testing.query_budget(n): ...`.

**Dev query log.** `karni.middleware.QueryLogMiddleware` (first in Karni's
`MIDDLEWARE`; on when `KARNI_QUERY_LOG` is — the dev profile) logs every
request that ran SQL on the `karni.queries` logger: query count, duplicated
count, SQL time and total time, plus one line per repeated statement with
what rendered it — `WARNING` when anything repeated, `INFO` otherwise. Off, it
removes itself from the chain at startup.

### Pagination

Every list is paginated by a `karni.pagination.KarniPagination` subclass —
`KarniPageNumberPagination` (default: `?page=`, `?page_size=`) or
`KarniCursorPagination` (`?cursor=`; no `COUNT(*)` for very large tables).

- **Hard cap.** `?page_size=` and the default `PAGE_SIZE` (env
  `KARNI_PAGE_SIZE`, 50) are capped at `KARNI_MAX_PAGE_SIZE` (env, default
  **100**). A paginator subclass may set a lower `max_page_size`, never a
  higher one.
- **Floor.** `KARNI_MAX_PAGE_SIZE` may not be configured below
  `KARNI_MAX_PAGE_SIZE_FLOOR` (env, default **25** — the page size
  `@karni/ui`'s `ResourceTable` requests; the floor itself is at least 1).
  A cap of `0`/`None` would switch DRF's cap off, and a cap below what the UI
  requests silently hides rows from its page count — boot validation refuses
  both. Lowering the floor is the explicit, project-wide way to allow a
  smaller cap.
- **Cannot be switched off by accident.** `pagination_class = None` on a
  viewset is a class-definition error, a non-Karni paginator class too, and
  boot refuses `REST_FRAMEWORK["PAGE_SIZE"] = None` (or missing) and a
  `DEFAULT_PAGINATION_CLASS` that is missing or not a `KarniPagination`.
- **The opt-out states a reason** and stays bounded:

  ```python
  class ExportViewSet(BaseViewSet):
      model = Event
      access = Access(read=HasRole("staff"), write=HasRole("staff"))
      pagination = Unpaginated(max_rows=2000, reason="CSV export")
  ```

  The list is a plain JSON array of at most `max_rows` rows;
  `X-Karni-Truncated: true` says rows were cut.
- **Custom actions** that return lists use the helper (the
  `unpaginated-action` rule fails the build on `Serializer(qs,
  many=True).data` in an action — see [enforcement](enforcement.md)):

  ```python
  @action(detail=False)
  def upcoming(self, request):
      return self.paginated_response(self.get_queryset().filter(starts_at__gte=now()))
  ```

  `paginated_response(queryset, serializer_class=None)` paginates (same
  envelope and cap as `list`), optimises for the serializer, and orders an
  unordered queryset by the viewset's default `ordering`. Pass
  `self.filter_queryset(qs)` to honour the request's filters too.

### Response caching

Off by default; **one setting turns it on**: `KARNI_API_CACHE = True` (env).
Then the data of every successful `GET` `list` and `retrieve` of every
`BaseViewSet` is cached (`X-Karni-Cache: hit|miss`) for `KARNI_API_CACHE_TTL`
seconds (300) in the `KARNI_API_CACHE_ALIAS` cache (`"default"`).

- **Invalidation is automatic**: a save, delete or M2M change of any model
  the response reads — the models of the optimiser's plan, the models
  crossed by `Owned` paths, plus `Cache(depends_on=[...])` — replaces that
  model's version token (and the row's, for details), so every affected entry
  becomes unreachable at once. Details are invalidated per row.
- **Per requester**: keys include the full URL (host, `?page=`, `?expand=`,
  filters), the user, the user's roles and the language; the access gate
  runs before the cache is read. Details are cached only for viewsets whose
  gate is the `Access` declaration alone (extra `permission_classes` would be
  skipped on a hit).
- **Not seen**: `QuerySet.update()`, `bulk_create()`/`bulk_update()` and raw
  SQL send no signals — call `karni.api.caching.invalidate(Model, pk=None)`
  after them. A `SerializerMethodField` reading a model the serializer does
  not render needs `cache = Cache(depends_on=[ThatModel])`.

```python
class StockViewSet(BaseViewSet):
    model = Stock
    access = Access(read=Authenticated(), write=HasRole("ops"))
    cache = Uncached(reason="levels change every second")   # opt out

class CatalogueViewSet(BaseViewSet):
    model = Product
    access = Access(read=Public(), write=HasRole("ops"))
    cache = Cache(ttl=3600, depends_on=[Price])             # tune
```

## Search

`?search=` delegates to the provider named by `KARNI_SEARCH_PROVIDER`:

- `karni.api.search.postgres.PostgresSearchProvider` (default) — Postgres
  full-text (`SearchVector`/`SearchRank`) OR trigram similarity in a single
  lazy queryset. Class attrs to tune (subclass + point the setting at yours):
  `similarity_threshold` (0.3), `rank_threshold`, `use_trigram` (False drops
  the trigram leg).
- `karni.api.search.simple.SimpleSearchProvider` — OR of `icontains` across
  `search_fields`; works on any database (karni's own test suite uses it on
  sqlite).

Rank ordering vs `?ordering=`: search runs **after** ordering in the filter
pipeline; when the client did not pass an explicit `?ordering=`, results are
rank-ordered by the provider, otherwise the requested ordering wins.

Note: unlike DRF's stock `SearchFilter`, provider search does not interpret
the `^`, `=`, `@`, `$` field prefixes — `search_fields` are plain field
names.

### Postgres setup (pg_trgm)

The trigram leg needs the `pg_trgm` extension and, for speed, a GIN index.
One migration does both — `karni.api.search.postgres` re-exports the pieces:

```python
from django.db import migrations
from karni.api.search.postgres import GinTrgmIndex, TrigramExtension

class Migration(migrations.Migration):
    dependencies = [("myapp", "0001_initial")]
    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name="event",
            index=GinTrgmIndex(fields=["title"], name="event_title_trgm"),
        ),
    ]
```

Postgres-only behaviour is exercised in CI by a job with a Postgres service;
locally the suite runs the simple provider on sqlite.

### Custom providers

Subclass `karni.api.search.SearchProvider`, implement
`search(*, queryset, query, fields, view=None, …)` returning a queryset of
the same model, and set `KARNI_SEARCH_PROVIDER`. Swapping to Elasticsearch /
Meilisearch later happens behind this interface with no project code change.

## Auto-router

At the first import of `karni.api.urls`, the factory named by
`KARNI_API_ROUTER` (default `karni.api.routers.get_default_router`, a
zero-argument callable) builds the router and runs `autodiscover()`:

- Every installed app's `viewsets` / `api.viewsets` module is imported;
  `BaseViewSet` subclasses with `model` set and `auto_register = True` are
  registered at `route` or the kebab-plural of the model name
  (`Company` → `companies`, `Box` → `boxes`, `Day` → `days`; the helper
  `karni.api.routers.pluralize` is public).
- Basenames are `"<app_label>-<kebab-model>"`, unique across apps.
- **Explicit wins**: viewsets already registered and prefixes already taken
  are skipped (debug log); an auto-vs-auto prefix collision logs a warning
  naming both viewsets. `autodiscover()` is idempotent.

The setting is consumed once, at first URLconf import — overriding
`KARNI_API_ROUTER` afterwards (e.g. in a test) is a no-op; router tests
should build fresh `KarniRouter` instances instead. To pre-register explicit
routes:

```python
# myproject/api.py
from karni.api.routers import KarniRouter

def get_router():
    router = KarniRouter()
    router.register("events", MySpecialEventViewSet, basename="myapp-event")
    router.autodiscover()  # everything else, explicit registration wins
    return router
```

```python
KARNI_API_ROUTER = "myproject.api.get_router"
```

## Schema

`KarniAutoSchema` (the conf default `DEFAULT_SCHEMA_CLASS`) keeps
drf-spectacular's native introspection (choices → enums, `null=True` →
nullable, required from blank/default) and adds:

- an `expand` query parameter on list/retrieve (an enum of allowed keys when
  derivable) — the schema documents the **unexpanded** response shape only
  in v0.1;
- `search` (contributed by `KarniSearchFilter`, list ops only, and only when
  the view actually has `search_fields`);
- vendor extensions for typed frontends: `x-karni-resource` (router prefix,
  on list operations of auto-registered viewsets), `x-karni-relation`
  (`{"resource", "many"}` on relation fields whose target has a registered
  route), `x-karni-access` on every `BaseViewSet` operation (the predicate
  governing it: `{"public": true}`, `{"authenticated": true}`,
  `{"role": [...]}`, `{"owned": "<path>"}`, `{"where": "<fn>"}`,
  `{"any": [...]}`/`{"all": [...]}`, `{"unscoped": "<reason>"}`,
  `{"deny": ...}` — display hints only, the server enforces), and
  `x-karni-auth-mode` at the schema root;
- operations whose access can admit anonymous callers (`Public`, `Where`)
  list the empty security requirement `{}`;
- `SPECTACULAR_SETTINGS["COMPONENT_SPLIT_REQUEST"] = True` so file-upload
  fields keep `format: binary` on the request side.

Generate a TypeScript client straight off `/api/schema/`, e.g.:

```bash
npx openapi-typescript http://localhost:8000/api/schema/ -o src/api/schema.d.ts
```

Ordering and pagination parameters come from the stock DRF classes
(`OrderingFilter`, `KarniPageNumberPagination` — `?page`, `?page_size`
capped at `KARNI_MAX_PAGE_SIZE`, default 100). An `Unpaginated` viewset's list
is documented as a plain array with no paging parameters.
