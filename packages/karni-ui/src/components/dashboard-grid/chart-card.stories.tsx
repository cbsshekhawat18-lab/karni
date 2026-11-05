import type { Meta, StoryObj } from "@storybook/react";
import { ChartCard } from "./chart-card";

const meta = {
  title: "Blocks/ChartCard",
  component: ChartCard,
  tags: ["autodocs"],
  args: {
    title: "Products by category",
    description: "How many products each category holds.",
    kind: "bar",
    data: [
      { label: "Tools", value: 64 },
      { label: "Garden", value: 38 },
      { label: "Kitchen", value: 51 },
      { label: "Toys", value: 22 },
    ],
  },
  argTypes: { kind: { control: "select", options: ["line", "bar"] } },
} satisfies Meta<typeof ChartCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Bar: Story = {};

export const Line: Story = { args: { kind: "line", title: "Orders over time" } };

export const Loading: Story = { args: { loading: true } };

export const Empty: Story = { args: { data: [] } };

export const Failed: Story = {
  args: { data: [], error: new TypeError("Failed to fetch"), onRetry: () => undefined },
};
