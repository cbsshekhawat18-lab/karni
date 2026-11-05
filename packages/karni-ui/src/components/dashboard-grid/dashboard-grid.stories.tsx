import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "../primitives/button";
import { Stat } from "../stat/stat";
import { ChartCard } from "./chart-card";
import { DashboardCard, DashboardGrid } from "./dashboard-grid";

const monthly = [
  { label: "Jan", value: 120 },
  { label: "Feb", value: 210 },
  { label: "Mar", value: 180 },
  { label: "Apr", value: 260 },
];

const regions = [
  { label: "North", value: 42 },
  { label: "South", value: 31 },
  { label: "East", value: 18 },
  { label: "West", value: 27 },
];

const meta = {
  title: "Blocks/DashboardGrid",
  component: DashboardGrid,
  tags: ["autodocs"],
  args: { columns: 3 },
  argTypes: { columns: { control: "select", options: [2, 3, 4] } },
} satisfies Meta<typeof DashboardGrid>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Cards of different spans: a wide chart, a narrow one, and a card of plain content. */
export const Overview: Story = {
  render: (args) => (
    <DashboardGrid {...args}>
      <ChartCard
        title="Orders per month"
        description="Every order placed, by month."
        kind="line"
        data={monthly}
        span={2}
        actions={
          <Button variant="outline" size="sm">
            Open orders
          </Button>
        }
      />
      <ChartCard title="Products by region" kind="bar" data={regions} />
      <DashboardCard title="This week" span="full">
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat label="New customers" value="48" delta={6} />
          <Stat label="Returns" value="3" delta={-2} />
          <Stat label="Open tickets" value="12" />
        </div>
      </DashboardCard>
    </DashboardGrid>
  ),
};

/** The three states every data card has: loading, nothing to show, and a failure. */
export const States: Story = {
  render: (args) => (
    <DashboardGrid {...args}>
      <ChartCard title="Loading chart" kind="bar" data={[]} loading />
      <ChartCard title="Empty chart" kind="bar" data={[]} />
      <ChartCard
        title="Failed chart"
        kind="bar"
        data={[]}
        error={new TypeError("Failed to fetch")}
        onRetry={() => undefined}
      />
    </DashboardGrid>
  ),
};
