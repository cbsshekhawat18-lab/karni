# karni.api

> **Posture warning — read first.** Every `BaseViewSet` is auto-registered
> on the API router and, under the default
> `IsAuthenticatedOrReadOnly` permission, **anonymously readable**. The two
> knobs: set `permission_classes` on the viewset (or change
> `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`) to lock reads down, and
> set `auto_register = False` to keep a viewset off the router.

A model becomes a full API resource with three lines:

```python
# myapp/viewsets.py  (or myapp/api/viewsets.py)
from karni.api import BaseViewSet
from myapp.models import Event

class EventViewSet(BaseViewSet):
    model = Event
    search_fields = ["title"]
```

That yields CRUD, filtering, pagination, ordering, search, permissions and a
correct OpenAPI schema at `/api/events/`. Mount once:

```python
# config/urls.py
path("api/", include("karni.api.urls")),
```

## BaseViewSet

Declarative attributes (all optional except `model`):

| attribute | default | meaning |
|---|---|---|
| `model` | — | drives queryset, serializer, filters, route |
| `serializer_class` | `None` | explicit class **always** beats generation |
| `queryset` | `model._default_manager.all()` | replace to pre-filter |
| `search_fields` | `()` | enables `?search=` via the search provider |
| `expand_depth` | `0` | server-side default expansion depth |
| `expandable_fields` | auto (forward FK/O2O/M2M) | mapping of expand key → relation; reverse relations only when listed explicitly |
| `auto_register` | `True` | `False` → auto-router skips it |
| `route` | kebab-plural of the model name | router prefix |

Default ordering: model `Meta.ordering`, else `-created_at` when the field
exists, else `-pk`. Every normal DRF hook (`get_queryset`,
`get_serializer_class`, `permission_classes`, `filterset_class`, …) remains
overridable — `BaseViewSet` is a plain `ModelViewSet` underneath, plus
`ObjectPermissionsMixin` (`owner_field`, `object_permission_classes`,
`filter_queryset_for_user`) from `karni.accounts`.

## APIMeta — model-side API metadata

```python
class Event(BaseModel):
    ...
    class APIMeta:
        fields = [...]        # or exclude = [...] (mutually exclusive)
        read_only = ["status"]
        write_only = ["internal_note"]
        schema_name = "Event"  # optional: replaces the AppLabelModel stem
```

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
schema components never collide across apps. Top-level generated classes are
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
- Expanded relations are automatically `select_related` (FK/O2O paths) or
  `prefetch_related` (any M2M/reverse segment), so expansion adds no N+1.
- Expanded nested representations are read-only; writes keep using PKs.

v0.1 bound: each distinct expand-set builds (and caches) one serializer
class; pathological clients can grow that cache breadth-wise. The cap on
depth bounds each entry's size; clear with `build_serializer.cache_clear()`.

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
  route), and `x-karni-auth-mode` at the schema root;
- `SPECTACULAR_SETTINGS["COMPONENT_SPLIT_REQUEST"] = True` so file-upload
  fields keep `format: binary` on the request side.

Generate a TypeScript client straight off `/api/schema/`, e.g.:

```bash
npx openapi-typescript http://localhost:8000/api/schema/ -o src/api/schema.d.ts
```

Ordering and pagination parameters come from the stock DRF classes
(`OrderingFilter`, `KarniPageNumberPagination` — `?page`, `?page_size`
capped at 500).
