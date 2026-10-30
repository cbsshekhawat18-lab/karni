# @karni/charts-ui

React components for the [karni-charts](../README.md) module: a chart saved
in the admin, drawn with `@karni/ui`'s `DataChart` from its source
resource's aggregate. **Experimental.**

```bash
npm install @karni/charts-ui
```

```tsx
import { SavedChart } from "@karni/charts-ui";

<SavedChart chart="launches-per-year" filters={{ channel: "online" }} />;
```

`SavedChart` fetches `GET /charts/<slug>/data/` (the definition and the data
in one request) through the `KarniClient` of the `KarniProvider` around it,
and draws it: the saved name is the title, the description the chart's
description, a chart whose z axis stacks has stacked bars. The data follows
the source resource's access, so each viewer sees their own numbers.

| Prop                         | What it does                                                                      |
| ---------------------------- | --------------------------------------------------------------------------------- |
| `chart`                      | the chart's slug                                                                  |
| `filters`                    | the filters the chart allows (`allowed_filters`), as `useResourceList` takes them |
| `title`, `kind`              | replace the saved name and kind                                                   |
| `slots`                      | `DataChart`'s slots, plus `Error` for the error state                             |
| `queryOptions`               | TanStack Query options (`refetchInterval`, `placeholderData`, ...)                |
| every other `DataChart` prop | formatting, size, legend, tooltip, `className`                                    |

`useSavedChart(slug, filters, options)` is the hook underneath, for a layout
of your own, and `savedChartKey(slug, filters)` its query key.
