import { KarniProvider, createKarniClient } from "@karni/ui";
import { QueryClient } from "@tanstack/react-query";
import type { Meta, StoryObj } from "@storybook/react";
import type { SavedChartData } from "./types";
import { SavedChart } from "./SavedChart";

/**
 * Stories run against a stubbed KarniClient (the client's injectable `fetch`),
 * so no backend or MSW worker is needed.
 */
const launches: SavedChartData = {
  chart: {
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
  },
  data: {
    group_by: "launched_on:year",
    metric: "count",
    value: null,
    split: "channel",
    stacked: true,
    top: null,
    categories: [
      { key: "2023", label: "2023", other: false },
      { key: "2024", label: "2024", other: false },
      { key: "2025", label: "2025", other: false },
    ],
    series: [
      { key: "online", label: "Online", values: [12, 18, 25] },
      { key: "store", label: "Store", values: [9, 7, 4] },
    ],
  },
};

function respond(body: unknown, status = 200): typeof fetch {
  return async () =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function withBackend(fetchImpl: typeof fetch) {
  const client = createKarniClient({ baseUrl: "/api", fetch: fetchImpl });
  return function Decorator(Story: () => React.ReactElement): React.ReactElement {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return (
      <KarniProvider client={client} queryClient={queryClient}>
        <Story />
      </KarniProvider>
    );
  };
}

const meta = {
  title: "Charts/SavedChart",
  component: SavedChart,
  tags: ["autodocs"],
  args: { chart: "launches-per-year" },
  decorators: [withBackend(respond(launches))],
} satisfies Meta<typeof SavedChart>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Stacked bars: the chart's z axis stacks the channels. */
export const Stacked: Story = {};

/** The same saved chart drawn as lines. */
export const AsLines: Story = {
  args: { kind: "line" },
};

/** One series, top three categories and an "Other" bar. */
export const TopWithOther: Story = {
  decorators: [
    withBackend(
      respond({
        chart: { ...launches.chart, name: "Units by category", z_field: "", x_label: "Category" },
        data: {
          group_by: "category",
          metric: "sum",
          value: "units",
          split: null,
          stacked: false,
          top: 3,
          categories: [
            { key: "c1", label: "Toys", other: false },
            { key: "c2", label: "Chairs", other: false },
            { key: "c3", label: "Lamps", other: false },
            { key: null, label: "Other", other: true },
          ],
          series: [{ key: null, label: "Sum of units", values: [30, 17, 12, 8] }],
        },
      }),
    ),
  ],
};

/** The source refused: the viewer may not read it. */
export const Refused: Story = {
  decorators: [withBackend(respond({ detail: "You do not have permission." }, 403))],
};
