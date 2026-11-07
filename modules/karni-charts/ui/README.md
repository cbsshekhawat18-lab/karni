# @karni/charts-ui

React components for the Karni charts module: SavedChart and its hook.

[![npm](https://img.shields.io/npm/v/@karni/charts-ui)](https://www.npmjs.com/package/@karni/charts-ui) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/charts/)

A chart saved in the admin with the [karni-charts](https://pypi.org/project/karni-charts/) module, drawn with `@karni/ui`'s `DataChart` from its source resource's aggregate. **Experimental.**

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

## Links

- Saved charts: <https://cbsshekhawat18-lab.github.io/karni/charts/>
- The Python module: <https://pypi.org/project/karni-charts/>
- Karni, the framework this package is part of: <https://github.com/cbsshekhawat18-lab/karni>
- Changelog: <https://github.com/cbsshekhawat18-lab/karni/blob/main/CHANGELOG.md>
- Issues: <https://github.com/cbsshekhawat18-lab/karni/issues>
- License: Apache-2.0. @karni/charts-ui is released with every other Karni package, at one version.
