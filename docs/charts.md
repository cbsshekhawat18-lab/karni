---
description: "karni-charts (experimental): saved charts defined and previewed in the Django admin, served through each resource's aggregate action under that resource's access, and drawn in React with SavedChart from @karni/charts-ui."
---

# Saved charts (karni-charts)

!!! warning "Experimental"
    The karni-charts module is [experimental](stability.md#experimental-names):
    the `Chart` model and its admin, `/api/charts/` and its `data` action,
    `karni_charts.services`, the `KARNI_CHARTS_READ` setting and
    `@karni/charts-ui` (`SavedChart`, `useSavedChart`). They may change in a
    minor release, with a CHANGELOG entry. The `CHART` codes keep their
    meaning.

A dashboard's charts change more often than its code: someone wants revenue
by quarter instead of by month, the top five regions, one more filter.
karni-charts keeps each chart as a row people edit in the admin. The app
draws it with one component, and the numbers come from the source resource's
own [aggregate action](aggregations.md), as the person who looks at the
chart, so a chart never shows a row the source's list would hide from them.

```bash
pip install karni-charts
karni add charts
make migrate
npm install @karni/charts-ui
```

In `karni.yaml` the module is `modules: {charts: {}}`, or `{charts: {read:
public}}` for its setting ([app spec](app-spec.md#modules)).

## A chart

A chart reads a **source**: any routed resource whose model declares an
aggregation (`class Karni: aggregate`, see [aggregations](aggregations.md)).
In the admin, **Charts** lists the definitions:

| Field | What it is |
|---|---|
| `name`, `slug`, `description` | the title, the slug the app asks for, a description screen readers hear |
| `source` | the resource it reads (`products`), chosen among the resources that declare an aggregation |
| `kind` | `bar` or `line` |
| `x_field`, `x_bucket`, `x_label` | the x axis: a declared group, a date bucket (`year`, `quarter`, `month`), its label |
| `y_metric`, `y_value`, `y_label` | the y axis: `count`, `sum`, `avg`, `min`, `max` or `distinct_count`, the value it reads, its label |
| `z_field`, `z_bucket`, `z_mode` | an optional second group: `stack` draws stacked bars, `series` one line or bar per value |
| `top` | keep the N largest groups of the x axis and put the rest in "Other" |
| `default_filters` | list filters the chart always applies: `{"channel": "online"}` |
| `allowed_filters` | list filters a viewer may add: `["channel", "launched_on__gte"]` |
| `position` | the order of the list |

Saving checks the axes against the source's declaration
([CHART004](errors.md#chart004), which quotes the source's `E38x`), the
filters ([CHART003](errors.md#chart003)) and the source
([CHART001](errors.md#chart001)). Under the fields, the change form shows a
preview: the chart's data as a table, fetched as the signed-in staff user.

## The API

| Endpoint | Answers |
|---|---|
| `GET /api/charts/` | the definitions, for whoever `KARNI_CHARTS_READ` admits |
| `GET /api/charts/<slug>/` | one definition |
| `GET /api/charts/<slug>/data/?<allowed filters>` | `{"chart": <definition>, "data": <aggregate>}` |

`data` merges the chart's `default_filters` with the viewer's query
parameters, each of which must be in `allowed_filters`
([CHART002](errors.md#chart002) otherwise), then calls `GET
<source>/aggregate/` in the same process, as the viewer. The source's access,
field visibility, filters, throttles and query budget apply as if the viewer
had called it. When the source refuses (a 403, a 404, a 400 with its code),
`data` answers the same, so a viewer who may not list products sees no
product chart. The API only reads: charts are written in the admin.

```json
{
  "chart": {"slug": "launches-per-year", "name": "Launches per year", "kind": "bar", "x_field": "launched_on", "x_bucket": "year", "z_field": "channel", "z_mode": "stack", "...": "..."},
  "data": {
    "group_by": "launched_on:year", "metric": "count", "value": null, "split": "channel",
    "stacked": true, "top": null,
    "categories": [{"key": "2024", "label": "2024", "other": false}, {"key": "2025", "label": "2025", "other": false}],
    "series": [{"key": "online", "label": "Online", "values": [1, 2]}, {"key": "store", "label": "Store", "values": [1, 1]}]
  }
}
```

## In React

```tsx
import { SavedChart } from "@karni/charts-ui";

export function Launches() {
  return <SavedChart chart="launches-per-year" filters={{ channel: "online" }} />;
}
```

`SavedChart` fetches the definition and the data in one request and draws
them with `@karni/ui`'s `DataChart`: the saved name is the title, the
description the chart's description, a stacking z axis gives stacked bars.
It takes `DataChart`'s props for formatting and size, `title` and `kind` to
replace the saved ones, `slots` (DataChart's, plus `Error`) and
`queryOptions`. `useSavedChart(slug, filters)` is the hook underneath.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `KARNI_CHARTS_READ` | `"authenticated"` | Who reads the definitions: `authenticated`, `public` (charts on a public page) or `granted` (the roles' grants on `karni_charts.chart`). The data always follows the source's access. |

## Escape hatches

- `KARNI_CHARTS_READ`, or a subclass of `ChartViewSet` with its own
  `get_access()`, decides who reads the definitions.
- `karni_charts.services`: `sources()` (which resources a chart may read),
  `chart_filters()` (how the viewer's filters merge with the chart's),
  `check_chart()` and `run_chart()` (how the source is called).
- The admin is an explicit registration: unregister `Chart` and register a
  subclass of `karni_charts.admin.ChartAdmin`.
- A chart that a row cannot express is `useAggregate` and `DataChart` in a
  page of your own ([aggregations](aggregations.md#in-react)).

## Error codes

| Code | Problem |
|---|---|
| [CHART001](errors.md#chart001) | the source is not a routed resource with an aggregation |
| [CHART002](errors.md#chart002) | a viewer's filter the chart does not allow |
| [CHART003](errors.md#chart003) | `default_filters` or `allowed_filters` is not valid |
| [CHART004](errors.md#chart004) | the axes do not fit the source's aggregation |

The module's [README](https://github.com/cbsshekhawat18-lab/karni/tree/main/modules/karni-charts)
is its full reference.
