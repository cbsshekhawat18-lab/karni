---
description: "Karni aggregations (experimental): declare what a resource may be grouped and summed by, then GET <resource>/aggregate/ returns counts, sums, averages, minimums and maximums by category, relation or date bucket, with top N and Other, a second dimension, every list filter and the list's access. useAggregate and DataChart read the result."
---

# Aggregations

!!! warning "Experimental"
    Everything on this page is [experimental](stability.md#experimental-names):
    `class Karni: aggregate`, the viewset's `aggregation`, `get_aggregation()`
    and `aggregate_queryset()`, the `aggregate` action and its response,
    `karni.aggregation` (with `Aggregation` and `TextNumber`),
    `karni.api.aggregate`, `x-karni-aggregate`, the
    `KARNI_AGGREGATE_MAX_GROUPS` setting, and `useAggregate`,
    `aggregateSeries` and DataChart's `aggregate` and `stacked` in `@karni/ui`.
    They may change in a minor release, with a CHANGELOG entry. The error
    codes keep their meaning.

A data app's charts are counts and sums grouped by something: products per
category, revenue per quarter, the five largest regions and the rest as
"Other", each bar split by channel. Each one is usually a hand-written view
with its own GROUP BY, its own filters and its own access check, and each
one can show rows the list would hide. In Karni a model declares what may be
aggregated, and every resource gets one action that does it under the same
filters and access as the list.

## Declare what may be aggregated

Nothing is aggregatable until the model says so, next to its other
[`class Karni`](REFERENCE.md#model-metadata-class-karni) options:

```python
from karni.aggregation import TextNumber
from karni.models import BaseModel


class Product(BaseModel):
    category = models.ForeignKey(Category, null=True, on_delete=models.SET_NULL)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    launched_on = models.DateField()
    price = models.DecimalField(max_digits=12, decimal_places=2)
    units = models.PositiveIntegerField()
    revenue_text = models.CharField(max_length=40, blank=True)  # "$1.2B", "450K"

    class Karni:
        aggregate = {
            "group_by": ["category", "category__parent", "channel", "launched_on"],
            "values": ["price", "units", "revenue"],
            "metrics": ["count", "sum", "avg"],
            "expressions": {"revenue": TextNumber("revenue_text")},
        }
```

| Key | Takes | Default |
|---|---|---|
| `group_by` | the fields, relation paths (`category__parent`) and expression names a request may group by. A date or datetime field allows every bucket. `launched_on:year` allows only that one | required |
| `values` | the fields, paths and expression names a metric reads | `[]` (only a plain count) |
| `metrics` | the metrics a request may name: `count`, `sum`, `avg`, `min`, `max`, `distinct_count` | all six |
| `expressions` | name to a Django expression, usable in `group_by` and `values` | `{}` |

A viewset can declare its own, which wins over the model's:

```python
from karni.aggregation import Aggregation


class ProductViewSet(BaseViewSet):
    model = Product
    access = Granted()
    aggregation = Aggregation(group_by=["channel"], metrics=["count"])
```

`karni check` refuses a declaration that names a field the model does not
have, a bucket on a field that is not a date, a write-only field or an
unknown metric ([E380](errors.md#e380)), and warns about an expression that
neither list uses ([W570](errors.md#w570)).

## The request

```text
GET /api/products/aggregate/?group_by=launched_on:year&metric=sum&value=price&stack=channel&featured=true
```

| Parameter | Takes |
|---|---|
| `group_by` | required. A declared field, relation path or expression. A date or datetime field takes `:year`, `:quarter` or `:month`, and without a bucket it groups by the date itself |
| `metric` | `count` (the default), `sum`, `avg`, `min`, `max` or `distinct_count`, among the declared metrics |
| `value` | the declared value the metric reads. `sum`, `avg`, `min` and `max` need a number. `count` without a value counts rows, with one it counts the rows where it is set |
| `top` | keep the N largest groups and put every other row in one "Other" group |
| `stack` | a second dimension, drawn as stacked bars |
| `series` | a second dimension, drawn as separate series |
| any list filter, `search` | exactly as on the list: `?featured=true`, `?price__gte=25`, `?search=lamp` |

`stack` and `series` take the same values as `group_by` and give the same
numbers. The response says which one the request used, so a chart knows to
stack. The aggregate's own parameters are never list filters on this
endpoint, so a model field named `value` or `top` is not filterable here.

## The response

```json
{
  "group_by": "launched_on:year",
  "metric": "sum",
  "value": "price",
  "split": "channel",
  "stacked": true,
  "top": null,
  "categories": [
    {"key": "2024", "label": "2024", "other": false},
    {"key": "2025", "label": "2025", "other": false}
  ],
  "series": [
    {"key": "online", "label": "Online", "values": [10.0, 35.0]},
    {"key": "store", "label": "Store", "values": [150.0, 0]}
  ]
}
```

`categories` are the groups of `group_by`, in display order. `series` has
one entry per value of the second dimension (one entry, named after the
metric, without one), each with a value per category in the same order.

- **Keys** are JSON: a value, a related row's key, or a date bucket written
  `2024`, `2024-Q1` or `2024-01`.
- **Labels**: a relation shows what people read for the related row: its
  `Karni.label_field`, else its first text field named `name`, `title` or
  `label`, else its [natural key](REFERENCE.md#model-metadata-class-karni)
  (`Karni.natural_key`). So a region keyed by the slug `europe` reads
  `Europe`, in a chart's legend and axis and in a comparison's headers, while
  its `key` stays the row's id for filters and links. A label field the
  requester may not read ([field visibility](api.md#field-visibility)) gives
  way to the natural key. A choice shows its label, a boolean `Yes` or `No`,
  a bucket `2024`, `Q1 2024` or `Jan 2024`. Rows with no value form the
  group `(none)`.
- **Order**: dates by date, everything else by value, largest first. In a
  split, a category's value is the sum of its series' values. "Other" comes
  last.
- **Missing cells** of a split read `0` for `count`, `distinct_count` and
  `sum` (no rows), and `null` for `avg`, `min` and `max`.
- **`top`** ranks the groups that have a key. Rows with no key go to "Other"
  with the rest. With a second dimension, "Other" holds a value per series.

## Filters and access

The action runs over `aggregate_queryset()`: the same `get_queryset()` the
list uses (model scopes, the `access` read scope, `filter_queryset_for_user`),
then the list's filter backends and `?search=`. A user sees counts of exactly
the rows the list shows them, and an anonymous request is refused the way the
list refuses it. The action is a read, so it follows `access.read`, and
`Granted()` asks for the `view` permission.

A field hidden from the requester by
[`Karni.field_roles`](api.md#field-visibility), or written only
(`APIMeta.write_only`), is refused like an undeclared one, as a group, a
value, or a field an expression reads.

## Queries

Each request is one query, two with `top` (the "Other" group), whatever the
number of rows: the grouping runs in the database. A request that would
return more than `KARNI_AGGREGATE_MAX_GROUPS` groups (default 1000) is
refused with [E387](errors.md#e387): send `top`, narrow it with filters, or
group by a coarser bucket. The action counts against the viewset's
[query budget](api.md#query-budgets) like any other (`Budget(aggregate=N)`),
and the [query-scaling check](enforcement.md) measures it with 2 and with 12
rows.

## Numbers stored as text

Data loaded from spreadsheets and other systems often keeps amounts as
text: `"$1,045,000"`, `"450K"`, `"9.5 million"`, `"2.1bn"`. `TextNumber`
reads them in SQL, on PostgreSQL and SQLite, so they can be summed and
averaged without a second column:

```python
"expressions": {"revenue": TextNumber("revenue_text")}
```

It trims the text, upper-cases it, removes currency signs (`$ € £ ¥ ₹`),
thousands separators and spaces, then reads a plain number, or a number
followed by a suffix: `K` and `THOUSAND` (thousands), `M`, `MM`, `MN` and
`MILLION`, `B`, `BN` and `BILLION`, `T`, `TN` and `TRILLION`. Anything else,
such as `"Undisclosed"`, an empty text or a range, is `NULL`: a sum leaves it
out, and it never counts as 0. The result is a float.

Pass your own suffixes or characters to remove:

```python
TextNumber("amount_text", suffixes={"CR": 1e7, "L": 1e5})
TextNumber("amount_text", strip=["$", ","])
```

Any Django expression works the same way in `expressions`, for a group or
a value of your own:

```python
"expressions": {
    "margin": F("price") - F("cost"),
    "launch_year": ExtractYear("launched_on"),
}
```

## In React

`useAggregate` builds the request and `DataChart` reads the response
directly:

```tsx
import { DataChart, useAggregate } from "@karni/ui";

export function LaunchesByYear() {
  const { data, isLoading } = useAggregate("products", {
    groupBy: "launched_on:year",
    stack: "channel",
    filters: { featured: true },
  });
  return <DataChart kind="bar" title="Launches per year" aggregate={data} loading={isLoading} />;
}
```

The query is cached under the resource, so a create, update or delete of a
product refreshes it. `DataChart` stacks the bars of a `stack` request
(`stacked={false}` groups them side by side instead) and `aggregateSeries`
turns a response into `DataChart` series by hand. `karni types` writes a
typed hook per resource that declares an aggregation,
`useProductsAggregate`, whose `groupBy` accepts only the declared groups.

A chart that people edit in the admin instead of in code is a
[saved chart](charts.md).

## OpenAPI

The `aggregate` operation of a resource that declares an aggregation
documents its parameters, with the declared groups, values and metrics as
enums, the list's filters, and the `AggregateResult` response. It carries
`x-karni-aggregate: {"group_by": [...], "values": [...], "metrics": [...]}`,
with every bucket of a date spelled out. A resource without a declaration has
no `aggregate` operation, and the action answers 404 ([E381](errors.md#e381)).

## Escape hatches

- `aggregation` on the viewset replaces the model's declaration.
- `get_aggregation()` returns a declaration computed per request, or `None`
  to turn the action off.
- `aggregate_queryset()` changes the rows an aggregate counts.
- `expressions` takes any Django expression, and `TextNumber` takes
  `suffixes` and `strip`.
- Override the `aggregate` action, or write an `@action` of your own, for an
  answer the declaration cannot express.

## Error codes

| Code | Problem |
|---|---|
| [E380](errors.md#e380) | a declaration that does not fit its model (`karni check`) |
| [E381](errors.md#e381) | the resource declares no aggregation (404) |
| [E382](errors.md#e382) | `group_by`, `stack` or `series` names something not declared, or hidden from the requester |
| [E383](errors.md#e383) | a metric that is not allowed |
| [E384](errors.md#e384) | a value that is missing, not declared, hidden or not a number |
| [E385](errors.md#e385) | a date bucket that does not fit |
| [E386](errors.md#e386) | `top`, or `stack` and `series` together, not valid |
| [E387](errors.md#e387) | more groups than `KARNI_AGGREGATE_MAX_GROUPS` |
| [W570](errors.md#w570) | an expression no list uses |
