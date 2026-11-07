import type { Meta, StoryObj } from "@storybook/react";
import { ComparisonTable, type ComparisonMetric } from "./comparison-table";

interface Plan {
  id: string;
  name: string;
  price: number;
  seats: number;
  storage: number;
  support: boolean;
}

const plans: Plan[] = [
  { id: "basic", name: "Basic", price: 9, seats: 3, storage: 10, support: false },
  { id: "team", name: "Team", price: 29, seats: 10, storage: 100, support: true },
  { id: "business", name: "Business", price: 79, seats: 50, storage: 1000, support: true },
];

const metrics: ComparisonMetric<Plan>[] = [
  {
    key: "price",
    label: "Price",
    description: "Per month",
    better: "lower",
    format: (value) => (typeof value === "number" ? `€${value}` : ""),
  },
  { key: "seats", label: "Seats", better: "higher" },
  {
    key: "storage",
    label: "Storage",
    better: "higher",
    format: (value) => (typeof value === "number" ? `${value} GB` : ""),
  },
  { key: "support", label: "Phone support" },
];

const meta = {
  title: "Blocks/ComparisonTable",
  component: ComparisonTable<Plan>,
  tags: ["autodocs"],
  args: { caption: "Plans compared", entities: plans, metrics, metricHeader: "Plan" },
} satisfies Meta<typeof ComparisonTable<Plan>>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Three plans side by side, with the best price, seats and storage marked. */
export const Plans: Story = {};

export const Loading: Story = { args: { loading: true } };

export const Empty: Story = { args: { entities: [] } };
