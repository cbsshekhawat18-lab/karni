import type { Meta, StoryObj } from "@storybook/react";
import { Input } from "./input";
import { Label } from "./label";

const meta = {
  title: "Primitives/Label",
  component: Label,
  tags: ["autodocs"],
  args: {
    children: "Field label",
  },
} satisfies Meta<typeof Label>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};

export const WithControl: Story = {
  render: () => (
    <div className="grid w-full max-w-sm gap-1.5">
      <Label htmlFor="story-name">Name</Label>
      <Input id="story-name" placeholder="Ada Lovelace" />
    </div>
  ),
};

export const WithDisabledPeer: Story = {
  render: () => (
    <div className="grid w-full max-w-sm gap-1.5">
      {/* peer-disabled styling comes from the Input's `peer` class */}
      <Input id="story-disabled" className="peer" disabled placeholder="Disabled" />
      <Label htmlFor="story-disabled">Dimmed via peer-disabled</Label>
    </div>
  ),
};
