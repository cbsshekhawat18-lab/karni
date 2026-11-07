# karni-charts

Saved charts for Karni: charts defined and previewed in the admin, served through each resource's aggregate action under its access.

[![PyPI](https://img.shields.io/pypi/v/karni-charts)](https://pypi.org/project/karni-charts/) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/charts/)

A chart's data is never stored or computed by the module: it is the source resource's own [aggregate action](https://cbsshekhawat18-lab.github.io/karni/aggregations/), fetched as the person who views the chart, so a chart never shows a row the source's list would hide from them.

**Experimental**, like the aggregations it builds on: the model, the API, the
settings and `@karni/charts-ui` may change in a minor release, with a
CHANGELOG entry. The error codes keep their meaning.

## Install

```bash
pip install karni-charts
karni add charts
make migrate
```

`karni add charts` puts `karni_charts` in `INSTALLED_APPS`. The API rides
Karni's auto-router (no URL include), and the settings arrive through the
module's settings fragment. The React component is in `@karni/charts-ui`:

```bash
npm install @karni/charts-ui
```

## A chart

A source is any routed resource whose model declares an aggregation:

```python
class Product(BaseModel):
    class Karni:
        aggregate = {
            "group_by": ["category", "channel", "launched_on"],
            "values": ["price"],
        }
```

In the admin, **Charts** holds the definitions:

| Field | What it is |
|---|---|
| `name`, `slug`, `description` | what the chart is called, the slug the app asks for, a description screen readers hear |
| `source` | the resource it reads (`products`), chosen from the resources that declare an aggregation |
| `kind` | `bar` or `line` |
| `x_field`, `x_bucket`, `x_label` | the x axis: a declared group, a date bucket (`year`, `quarter`, `month`) for a date, its label |
| `y_metric`, `y_value`, `y_label` | the y axis: `count`, `sum`, `avg`, `min`, `max` or `distinct_count`, the value it reads, its label |
| `z_field`, `z_bucket`, `z_mode` | an optional second group: `stack` (stacked bars) or `series` (one line or bar per value) |
| `top` | keep the largest N groups of the x axis and put the rest in "Other" |
| `default_filters` | list filters the chart always applies, `{"channel": "online"}` |
| `allowed_filters` | list filters a viewer may add, `["channel", "launched_on__gte"]` |
| `position` | the order charts are listed in |

Saving checks the axes against the source's declaration (`CHART004`), the
filters (`CHART003`) and the source (`CHART001`). The change form shows a
preview under the fields: the chart's data as a table, as the signed-in staff
user may see it.

## Main features

- Charts defined and previewed in the admin: a source resource, its axes and its filters
- Served at `/api/charts/<slug>/data/` through the source's aggregate action, as the viewer
- Filters a viewer may add, next to the ones the chart applies
- Drawn in React with one component, `SavedChart` from [`@karni/charts-ui`](https://www.npmjs.com/package/@karni/charts-ui)
- Error codes `CHART001` to `CHART004`, explained offline by `karni explain`

## The API

| Endpoint | Answers |
|---|---|
| `GET /api/charts/` | the definitions, for whoever `KARNI_CHARTS_READ` admits |
| `GET /api/charts/<slug>/` | one definition |
| `GET /api/charts/<slug>/data/?<allowed filters>` | `{"chart": <definition>, "data": <aggregate>}` |

The `data` action merges the chart's `default_filters` with the viewer's
query parameters, which must be in `allowed_filters` (anything else is a 400,
`CHART002`), then calls the source's `GET <source>/aggregate/` in-process,
as the viewer. The source's access, field visibility, filters, throttles and
query budget apply as if the viewer had called it. When the source refuses
(a 403, a 404, a 400 with its `E38x` code), the `data` action answers the
same. Charts are written in the admin only: the API reads.

## In React

```tsx
import { SavedChart } from "@karni/charts-ui";

<SavedChart chart="launches-per-year" filters={{ channel: "online" }} />
```

`SavedChart` fetches the definition and the data in one request and draws
them with `@karni/ui`'s `DataChart` (stacked bars for a `stack` chart). It
takes `DataChart`'s own props for formatting (`valueFormatter`,
`xTickFormatter`, `slots`, `className`, `width`, `height`), and `slots` of
its own for the loading and error states. `useSavedChart(slug, filters)` is
the hook underneath.

## Settings

| Setting | Env var | Default | Meaning |
|---|---|---|---|
| `KARNI_CHARTS_READ` | `KARNI_CHARTS_READ` | `"authenticated"` | Who reads the chart definitions: `authenticated`, `public` (charts on a public page) or `granted` (the roles' grants on `karni_charts.chart`). The data always follows the source's own access. |

## Escape hatches

- `KARNI_CHARTS_READ`, or `ChartViewSet.get_access()` in a subclass you
  register yourself, decides who reads the definitions.
- `karni_charts.services`: `sources()` (the resources a chart may read),
  `chart_filters()` (how the viewer's filters merge with the chart's),
  `check_chart()` and `run_chart()` (how the source is called).
- `Chart.query()` is the source's query string for a chart.
- The admin is an explicit registration: `admin.site.unregister(Chart)`, then
  register a subclass of `karni_charts.admin.ChartAdmin`.
- A chart the model cannot express is `useAggregate` and `DataChart` from
  `@karni/ui` in a page of your own.

## Error codes

| Code | Problem |
|---|---|
| `CHART001` | the source is not a routed resource with an aggregation |
| `CHART002` | a viewer's filter the chart does not allow |
| `CHART003` | `default_filters` or `allowed_filters` is not valid |
| `CHART004` | the axes do not fit the source's aggregation |

`karni explain CHART001` prints each one.

## Links

- Saved charts: <https://cbsshekhawat18-lab.github.io/karni/charts/>
- Aggregations: <https://cbsshekhawat18-lab.github.io/karni/aggregations/>
- React components: <https://www.npmjs.com/package/@karni/charts-ui>
- Karni, the framework this package is part of: <https://github.com/cbsshekhawat18-lab/karni>
- Changelog: <https://github.com/cbsshekhawat18-lab/karni/blob/main/CHANGELOG.md>
- Issues: <https://github.com/cbsshekhawat18-lab/karni/issues>
- License: Apache-2.0. karni-charts is released with every other Karni package, at one version.
