---
description: "The data portal recipe: datasets and indicators published by region and sector, with region and sector trees, analysts limited to the regions granted to them, an aggregate, a saved chart, search and import. What it builds and changes."
---

# Recipe: data portal

!!! warning "Experimental"
    Recipes are [experimental](../stability.md#experimental-names). See
    [recipes](index.md).

Datasets that publish indicators: a value for a region, a sector and a year.
Regions and sectors are trees (continents and their countries, sectors and
their topics). Staff and editors see everything. An analyst sees the
datasets and indicators of the regions an admin granted to them, user by
user, and the regions below each one.

```sh
karni new "Open Data" --recipe data-portal
```

This is the recipe for an app whose rows hang on a hierarchy and whose
readers are cut by it. It uses what the large-apps features give a
data-heavy app, in one spec.

## Entities and roles

The app `portal`:

| Entity | Fields | Notes |
|---|---|---|
| Region | name, slug (the import key) | a tree: `parent` is added by `tree: true`. Searched by name, cached for an hour |
| Sector | name, slug (the import key) | a tree, as Region |
| Dataset | title, slug (the import key), summary and method (`markdown`), publisher, frequency, license, source_url, published_on | tagged to Region and Sector (`taxonomies`), with field groups Overview, Method and Source, and the column sets `default` and `source`. Keeps its change history |
| Indicator | dataset, region, sector, year, value (`decimal:18:3`), unit, label (the import key), note | declares an aggregate. Keeps the history of `value`. The column sets `default` and `detail` |

An indicator's `label` is the text a person reads and a file names the row
by, such as `Life expectancy, France, 2020`. The seed writes it from the
dataset, the region and the year.

| Role | Grants |
|---|---|
| `admin` | a system role: everything, users, roles and grants too |
| `staff` | `portal.*:view` at scope `all`: reads every dataset, indicator, region and sector |
| `editor` | `all` on datasets and indicators, and `view` on regions and sectors: imports and edits |
| `analyst` | `tree:region` on `view` of datasets and indicators, and `view` of regions and sectors |

No role is given at sign-up (`default: false` on each): an admin gives each
account its role.

An analyst's role grant names no region. The regions come from per-user
grants (`features: user_grants`), one row each, which an admin writes in the
Django admin, on the user's page, or through `POST /api/auth/permissions/grants/`.
A grant of `portal.indicator:view` with scope `tree:region` and the targets
Europe and Asia opens every indicator whose region is Europe, Asia or below
either. An analyst with no grant sees nothing, never everything, and a grant
with `expires_at` ends by itself. Grant both `portal.indicator:view` and
`portal.dataset:view`: a dataset is read through the regions it is tagged
with, an indicator through its own `region`.

Regions and sectors are open to read for every role of the portal, so a
filter or a form can list them. Only the datasets and indicators follow the
tree scope.

## Modules and features

- `charts` ([saved charts](../charts.md)): `Indicators per year`, one saved
  chart, is in the seed. It counts indicators per year, stacked by
  continent, and reads the same aggregate as the page.
- `user_grants` ([per-user grants](../accounts.md#per-user-grants)): the
  analyst's regions.
- `api_cache` ([response caching](../api.md#response-caching)): Region and
  Sector are cached for an hour (`cache: 3600`), the other entities for the
  default lifetime. An entry is the caller's own for an analyst, and a grant
  written changes what the next request reads.

## The large-apps features it uses

| Feature | In this recipe |
|---|---|
| [Tree models](../models.md#tree-models) | `tree: true` on Region and Sector: the tree endpoints, the tree table and the walks |
| [The tree scope](../accounts.md#the-tree-scope) | `tree:region` in the analyst's grants, checked against the spec when you build |
| [Per-user grants](../accounts.md#per-user-grants) | the regions of each analyst, with a reason and an end date |
| [Taxonomies](../models.md#taxonomies) | `taxonomies: {region: Region, sector: Sector}` on Dataset: the filters `?region=`, the `facets/` counts and `tree:region` on datasets |
| [Aggregations](../aggregations.md) | `GET /api/indicators/aggregate/?group_by=year&metric=avg&value=value`, grouped by year, region, continent (`region__parent`), sector and dataset, under the caller's scope |
| [Saved charts](../charts.md) | the seeded chart over that aggregate, drawn by `SavedChart` |
| [Search across models](../global-search.md) | `global_search` on Dataset and Indicator: `GET /api/search/?q=life` finds both, inside the caller's scope |
| [Markdown fields and field groups](../ui.md#field-groups-and-column-sets-experimental) | `summary` and `method`, and the groups of the dataset form and detail page |
| [Column sets](../ui.md#field-groups-and-column-sets-experimental) | the presets of the Dataset and Indicator tables |
| [Related tabs and dashboard pages](../app-spec.md#related-tabs-and-dashboard-pages) | the dataset and region pages show an Indicators tab, and `overview` is a dashboard page |
| [Navigation](../navigation.md) | the menu of `karni.yaml`: Home, Overview, Data (Datasets, Indicators) and Browse (Regions, Sectors) |
| [Import and export](../import-export.md) | each list exports and imports with a preview, and the keys (`slug`, `label`) make a row an update |
| [Response caching](../api.md#response-caching) | `cache: 3600` on the trees |

Pages: the home page and `overview` (dashboards), datasets (list, detail with
an Indicators tab, form), indicators (list, detail, form), regions (list,
detail with an Indicators tab, form) and sectors (list, form). Demo data: 40
regions (6 continents and 34 countries), 15 sectors (5 and their topics), 24
datasets and about 3,000 indicators, all synthetic.

The `overview` page counts the rows of each resource the user may read, so
an analyst sees the counts of their regions. To draw the saved chart on it,
add a card to a page of your own (`- charts: code` in `pages`):

```tsx
import { SavedChart } from "@karni/charts-ui";

export default function Charts() {
  return <SavedChart chart="indicators-per-year" />;
}
```

## Domain code

- `portal/seeds.py`: the region and sector trees, thirty named measures
  (`Unemployment rate`, `Access to safe drinking water`) filed under their
  topic and tagged with the countries they cover, a value per dataset,
  country and year that stays in the range of its measure and unit, and the
  saved chart. The names come from `SECTORS` and `REGIONS`. The indicators
  are written in bulk, so a larger demo is a larger `seed` count. The
  seeded slugs are the slugs of the names (`europe`, `france`,
  `unemployment-rate`), so an import file names a row as it reads.
- `portal/tests/test_portal.py`: the tree scope limits an analyst to the
  granted regions and a grant ends, the aggregate and the saved chart under
  that scope, the dashboard's counts, search, and an import by `label` and
  `slug`.
- `portal/tests/conftest.py`: the tests read `X-Cache`, so they switch the
  deprecated `X-Karni-Cache` header off. Set `KARNI_API_CACHE_LEGACY_HEADER=False`
  in `.env` as well.

## What people usually change

| Change | In karni.yaml or the project |
|---|---|
| the trees' nodes | the seeds in `portal/seeds.py`, or load real nodes with an import |
| the dataset fields and their groups | `fields` and `groups` of `Dataset` |
| what an indicator measures | `value`, `unit` and `year` of `Indicator`, and its `aggregate.values` |
| which regions each analyst reads | per-user grants in the admin, not `karni.yaml` |
| what an analyst may open | `roles.analyst.grants`, for example `portal.indicator:view` to `portal.indicator` to let analysts write too |
| the groups an indicator may be aggregated by | `aggregate.group_by` of `Indicator`, then change the saved chart in the admin |
| the cache lifetime | `cache` of an entity, or `features.api_cache: {ttl: 600}` |

Then run `karni build`.
