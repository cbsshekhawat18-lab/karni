---
description: "Search across models in Karni: class Karni: search, GET /api/search/ with access applied per model, the trigram indexes and their check, the GlobalSearch command palette and the global_search key of karni.yaml."
---

# Search across models

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    the `class Karni` option `search`, `karni.global_search`,
    `karni.api.global_search` (with `GlobalSearchView` and `search_queryset`),
    `BaseViewSet.global_search_queryset`, `karni.fields.TrigramIndex`, the
    `KARNI_GLOBAL_SEARCH_*` settings, the `x-karni-search` schema extension,
    the `global_search` key of `karni.yaml`, `SearchResource` in
    `karni types`, and `GlobalSearch`, `useGlobalSearch` and `Layout`'s
    `search` in `@karni/ui`.

One search box finds rows of every kind at once: products, suppliers, people,
documents. Each model opts in, each one is searched under its own access
rules, and each hit links to the row's page.

This is not the list search. `?search=` on a list endpoint searches one
resource ([API: search](api.md#search)). `GET /api/search/` searches every
model that opts in.

## The declaration

```python
class Product(BaseModel):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=40)
    supplier = models.ForeignKey(Supplier, null=True, on_delete=models.SET_NULL)

    class Karni:
        search = {
            "fields": ["name", "sku"],      # text fields the query is matched with
            "title": "name",                # what a hit shows (default: the first field)
            "subtitle": "supplier__name",   # a second line (default: none)
            "weight": 2,                    # this model's scores count double (default: 1)
        }
```

- `fields` are text fields of the model: `CharField`, `TextField` and their
  subclasses (Karni's `EmailField`, `SlugField`, `PhoneField`, ...). A
  related model is searched through its own declaration.
- `title` and `subtitle` name a field of the model or a path through foreign
  keys.
- `weight` is a number above 0. It multiplies the model's scores, so its hits
  rank above (or below) other models' hits.

Only declared models are searched. A model also needs a routed
`BaseViewSet`: search reads it through its list endpoint and links each hit
to it. `karni check` warns with [`W591`](errors.md#w591) when one is missing,
and refuses a malformed declaration with [`E430`](errors.md#e430).

## The endpoint

`karni.api.urls` mounts it, so every project has it:

```
GET /api/search/?q=lamp&models=products,suppliers&limit=5
```

```json
{
  "query": "lamp",
  "groups": [
    {
      "resource": "products",
      "label": "Products",
      "hits": [
        {"resource": "products", "id": 7, "title": "Desk lamp",
         "subtitle": "Lamp Works", "score": 1.0}
      ]
    },
    {
      "resource": "suppliers",
      "label": "Suppliers",
      "hits": [
        {"resource": "suppliers", "id": 3, "title": "Lamp Works",
         "subtitle": "Porto", "score": 0.45}
      ]
    }
  ]
}
```

- **Access per model.** Each model is searched through the queryset its own
  list endpoint uses for the request: the viewset's request gate, then its
  `get_queryset()` with the model's scopes and the `access.read` row filter.
  A model the caller cannot list never appears, and neither does a row its
  list leaves out.
- **One query per model.** Each model's hits are one `SELECT`, plus what the
  access rules need to know about the user, once per request.
- **Ranking on PostgreSQL.** A row matches when a searched field contains the
  query (`ILIKE`) or is similar to it (pg_trgm's `%`, then a similarity above
  `KARNI_GLOBAL_SEARCH_THRESHOLD`, 0.3). It scores the greatest trigram
  similarity of its fields, so `Lamp` comes before `Desk lamp` and a typo
  such as `lampp` still finds it. The `%` operator uses pg_trgm's own
  `pg_trgm.similarity_threshold` (0.3) first, so a lower setting needs that
  lowered too.
- **Ranking on SQLite.** A row matches when a field contains the query
  (`icontains`). It scores 1 when a field equals the query, 0.75 when a field
  starts with it, else 0.5.
- **Order.** The weight multiplies each score. Hits are best first within a
  group, and groups are ordered by their best hit.
- **Limits.** `?limit=` hits per model (`KARNI_GLOBAL_SEARCH_LIMIT`, 5, at
  most `KARNI_GLOBAL_SEARCH_MAX_LIMIT`, 20). `?models=` names the resources to
  search, comma-separated. A resource search does not cover answers 400
  [`E431`](errors.md#e431) with the list it covers.
- **Short queries.** A query shorter than `KARNI_GLOBAL_SEARCH_MIN_LENGTH`
  (2) answers `{"groups": []}`, never an error, and runs no query.

Each hit carries its `resource` (the router prefix) and its `id`, so a client
links it to `/<resource>/<id>`, the route `karni make page --kind detail`
gives a `ResourceDetail` page. The OpenAPI document describes the endpoint
(operation `global_search`) and marks it with `x-karni-search: {"resources":
[...]}`. `karni types` turns that into `SearchResource`, the union of the
resource names, and a `useGlobalSearch` typed with it in `hooks.ts`.

### Changing how one model is searched

`BaseViewSet.global_search_queryset(queryset, query, declaration)` builds a
model's search queryset. `queryset` is the list queryset for the request,
access applied. The result carries the annotations `karni_search_title`,
`karni_search_subtitle` and `karni_search_score` (the constants `TITLE`,
`SUBTITLE` and `SCORE` of `karni.api.global_search`), best first:

```python
from django.db.models import Value
from django.db.models.functions import Concat
from karni.api.global_search import TITLE, search_queryset

class PersonViewSet(BaseViewSet):
    model = Person
    access = Granted()

    def global_search_queryset(self, queryset, query, declaration):
        found = search_queryset(queryset, query, declaration)
        return found.annotate(**{TITLE: Concat("first_name", Value(" "), "last_name")})
```

Keep the result narrowed from `queryset`, so the access rules still hold. To
replace the whole endpoint, subclass `GlobalSearchView` (`get_targets`,
`bound_view`, `search_target`, `get_limit`) and declare
`path("api/search/", MyView.as_view())` before Karni's API include.

## The indexes

Each searched field gets a GIN trigram index, `karni.fields.TrigramIndex`, in
the model's `Meta.indexes`. So `makemigrations` (and `karni build`) writes it
with the model:

```python
migrations.AddIndex(
    model_name="product",
    index=karni.fields.TrigramIndex(fields=["name"], name="catalog_product_1c2d3e4f_trgm"),
)
```

On PostgreSQL the index serves both `ILIKE '%lamp%'` and `%`, and creating it
creates the `pg_trgm` extension first when the database lacks it
([`E966`](errors.md#e966) names the fix when the role may not). On SQLite and
other databases it is a no-op, like Karni's other
[PostgreSQL-only indexes](fields.md). Removing a field from `fields` writes
the `RemoveIndex`.

`karni check` compares the declarations with the database on PostgreSQL. A
searched field whose table exists without a trigram index on that column is
[`W590`](errors.md#w590), with the command that adds it:

```
search indexes: catalog.Product: karni.W590: Product.Karni.search searches Product.sku, but
catalog_product.sku has no trigram index on database 'default': every search reads the whole table.
	HINT: Run `python manage.py makemigrations catalog` and `python manage.py migrate` ...
```

For a table another system owns (`class Karni: external = True`) the hint is
the `CREATE INDEX` to run in its database.

## The palette

`GlobalSearch` in `@karni/ui` is a command palette over the endpoint. Cmd+K
on macOS, Ctrl+K elsewhere, or its button opens it. It searches after a short
pause in typing, shows the hits grouped per resource, and each hit links to
its `ResourceDetail` page. It follows the WAI-ARIA combobox pattern: Arrow Down
and Arrow Up move through the hits while focus stays in the input, Enter opens
one, Escape closes the palette.

```tsx
import { Layout } from "@karni/ui";

<Layout navItems={nav} search>
  <Outlet />
</Layout>;
```

`search` mounts it in the layout's top bar, and an object passes its props,
such as `search={{ onSelect }}` to navigate with your router.
`hrefFor` changes where a hit links, `models` narrows the resources,
`slots.ResultLink` renders your router's link, and `useGlobalSearch` is the
data underneath for a search page of your own. The
[package README](https://github.com/cbsshekhawat18-lab/karni/blob/main/packages/karni-ui/README.md)
has the props.

## In karni.yaml

An entity opts in with `global_search`:

```yaml
apps:
  catalog:
    entities:
      Product:
        fields: {name: str, sku: "str:40", supplier: fk:Supplier?}
        search: [name, sku]
        global_search: {subtitle: supplier__name, weight: 2}
      Supplier:
        fields: {name: str, city: str?}
        search: name
        global_search: true
```

`true` searches the entity's `search` fields with the first one as the title.
The mapping takes `fields` (default: `search`), `title`, `subtitle` and
`weight`. `karni plan` shows it, `karni build` writes `class Karni: search`
into the entity's Karni-owned model base and the index migration, and
`karni spec export` reads it back. See [the app spec](app-spec.md).
