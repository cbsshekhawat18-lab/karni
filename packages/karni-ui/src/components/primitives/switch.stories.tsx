import type { Meta, StoryObj } from "@storybook/react";
import { Label } from "./label";
import { Switch } from "./switch";

const meta = {
  title: "Primitives/Switch",
  component: Switch,
  tags: ["autodocs"],
} satisfies Meta<typeof Switch>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};

export const WithLabel: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <Switch id="story-notifications" />
      <Label htmlFor="story-notifications">Email notifications</Label>
    </div>
  ),
};

export const On: Story = {
  args: { defaultChecked: true },
};

export const Disabled: Story = {
  args: { disabled: true },
};
