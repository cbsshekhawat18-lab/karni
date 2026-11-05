import type { Meta, StoryObj } from "@storybook/react";
import type { AggregateResult } from "../../hooks/useAggregate";
import { DataChart } from "./data-chart";

const monthly = [
  { label: "Jan", value: 120 },
  { label: "Feb", value: 210 },
  { label: "Mar", value: 180 },
  { label: "Apr", value: 260 },
  { label: "May", value: 300 },
  { label: "Jun", value: 245 },
] as const;

const multiSeries = [
  { name: "Signups", data: [...monthly] },
  {
    name: "Churn",
    data: [
      { label: "Jan", value: 30 },
      { label: "Feb", value: 42 },
      { label: "Mar", value: 35 },
      { label: "Apr", value: 48 },
      { label: "May", value: 40 },
      { label: "Jun", value: 38 },
    ],
  },
] as const;

const meta = {
  title: "Support/DataChart",
  component: DataChart,
  tags: ["autodocs"],
  args: {
    kind: "line",
    title: "Signups over time",
    description: "Monthly signups, January through June.",
    data: monthly,
  },
  argTypes: {
    kind: {
      control: "select",
      options: ["line", "bar"],
    },
  },
} satisfies Meta<typeof DataChart>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Line: Story = {};

export const Bar: Story = {
  args: { kind: "bar" },
};

export const MultiSeries: Story = {
  args: {
    title: "Signups vs churn",
    data: undefined,
    series: multiSeries,
  },
};

export const GroupedBars: Story = {
  args: {
    kind: "bar",
    title: "Signups vs churn",
    data: undefined,
    series: multiSeries,
  },
};

export const CustomFormatting: Story = {
  args: {
    title: "Monthly revenue",
    valueFormatter: (value) => `$${value.toLocaleString()}`,
    xTickFormatter: (label) => label.toUpperCase(),
  },
};

export const CustomTooltip: Story = {
  args: {
    renderTooltip: ({ label, points }) => (
      <p className="font-medium">
        {label}: {points.map((point) => String(point.value)).join(" / ")}
      </p>
    ),
  },
};

export const Empty: Story = {
  args: {
    data: [],
    emptyLabel: "No signups recorded yet",
  },
};

export const Loading: Story = {
  args: { loading: true },
};

/**
 * Keyboard: Tab focuses the chart, the arrow keys move the tooltip from
 * month to month and announce each value (also Home and End). Escape hides it.
 */
export const KeyboardFocus: Story = {
  args: {
    title: "Signups vs churn",
    data: undefined,
    series: multiSeries,
  },
  play: ({ canvasElement }) => {
    const svg = canvasElement.querySelector("svg");
    svg?.focus();
    for (const key of ["ArrowRight", "ArrowRight", "ArrowRight"]) {
      svg?.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
    }
  },
};

/** A phone-width container: tick labels stay legible, lines stay visible. */
export const Narrow: Story = {
  args: {
    title: "Signups vs churn",
    data: undefined,
    series: multiSeries,
    className: "max-w-80",
  },
};

/** What `useAggregate("products", { groupBy: "launched_on:year", stack: "channel" })` returns. */
const byYearAndChannel: AggregateResult = {
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
};

/** An aggregate read directly, stacked because the request said `stack`. */
export const FromAnAggregate: Story = {
  args: {
    kind: "bar",
    title: "Products launched per year, by channel",
    data: undefined,
    aggregate: byYearAndChannel,
  },
};

/** The largest categories and an "Other" bar (`top=3`), one series. */
export const TopWithOther: Story = {
  args: {
    kind: "bar",
    title: "Units sold by category",
    data: undefined,
    aggregate: {
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
  },
};
