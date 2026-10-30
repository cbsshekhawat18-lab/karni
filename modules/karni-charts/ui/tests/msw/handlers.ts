/**
 * A simulated karni_charts backend for the test suite (the conventions of
 * packages/karni-ui/tests/msw/).
 *
 * `GET /charts/<slug>/data/` answers `savedChartFixture` for
 * `launches-per-year`: its aggregate narrows to the online rows for
 * `?channel=online`, and any filter the chart does not allow is a 400
 * `CHART002`. Every other slug is a 404. `dataCalls` records each request's
 * query string.
 */
import type { AggregateResult } from "@karni/ui";
import { HttpResponse, http } from "msw";
import type { SavedChartData, SavedChartDefinition } from "../../src/types";

export const API_BASE = "http://localhost/api";

export const chartFixture: SavedChartDefinition = {
  id: "c0ffee00-0000-4000-8000-000000000001",
  name: "Launches per year",
  slug: "launches-per-year",
  description: "Products launched each year, by channel.",
  source: "products",
  kind: "bar",
  x_field: "launched_on",
  x_bucket: "year",
  x_label: "Year",
  y_metric: "count",
  y_value: "",
  y_label: "Products",
  z_field: "channel",
  z_bucket: "",
  z_mode: "stack",
  top: null,
  default_filters: {},
  allowed_filters: ["channel"],
  position: 0,
};

export const aggregateFixture: AggregateResult = {
  group_by: "launched_on:year",
  metric: "count",
  value: null,
  split: "channel",
  stacked: true,
  top: null,
  categories: [
    { key: "2024", label: "2024", other: false },
    { key: "2025", label: "2025", other: false },
  ],
  series: [
    { key: "online", label: "Online", values: [1, 2] },
    { key: "store", label: "Store", values: [1, 1] },
  ],
};

export const savedChartFixture: SavedChartData = { chart: chartFixture, data: aggregateFixture };

/** The query string of every data request since the last reset. */
export const dataCalls: URLSearchParams[] = [];

export function resetMswData(): void {
  dataCalls.length = 0;
}

export const handlers = [
  http.get(`${API_BASE}/charts/:slug/data/`, ({ params, request }) => {
    const query = new URL(request.url).searchParams;
    dataCalls.push(query);
    if (params.slug !== chartFixture.slug) {
      return HttpResponse.json({ detail: "No Chart matches the given query." }, { status: 404 });
    }
    const refused = [...query.keys()].filter(
      (name) => !chartFixture.allowed_filters.includes(name),
    );
    if (refused.length > 0) {
      return HttpResponse.json(
        {
          code: "CHART002",
          detail: `The chart does not allow the filter(s) ${refused.join(", ")}.`,
        },
        { status: 400 },
      );
    }
    if (query.get("channel") === "online") {
      const online = aggregateFixture.series.filter((entry) => entry.key === "online");
      return HttpResponse.json({
        ...savedChartFixture,
        data: { ...aggregateFixture, series: online },
      });
    }
    return HttpResponse.json(savedChartFixture);
  }),
];
