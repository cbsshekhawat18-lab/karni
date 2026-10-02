import type { Meta, StoryObj } from "@storybook/react";
import { Skeleton } from "./skeleton";

const meta = {
  title: "Primitives/Skeleton",
  component: Skeleton,
  tags: ["autodocs"],
  args: {
    className: "h-4 w-64",
  },
} satisfies Meta<typeof Skeleton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};

export const CardPlaceholder: Story = {
  render: () => (
    <div className="flex w-80 items-center gap-4 rounded-lg border p-4">
      <Skeleton className="h-12 w-12 rounded-full" />
      <div className="grid flex-1 gap-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    </div>
  ),
};

export const TableRows: Story = {
  render: () => (
    <div className="grid w-96 gap-2">
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-8 w-full" />
    </div>
  ),
};
