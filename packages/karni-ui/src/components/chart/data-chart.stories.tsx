import type { Meta, StoryObj } from "@storybook/react";
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
