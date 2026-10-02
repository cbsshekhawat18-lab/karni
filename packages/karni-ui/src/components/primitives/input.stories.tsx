import type { Meta, StoryObj } from "@storybook/react";
import { Input } from "./input";
import { Label } from "./label";

const meta = {
  title: "Primitives/Input",
  component: Input,
  tags: ["autodocs"],
  args: {
    placeholder: "Email address",
    type: "email",
  },
} satisfies Meta<typeof Input>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};

export const WithLabel: Story = {
  render: (args) => (
    <div className="grid w-full max-w-sm gap-1.5">
      <Label htmlFor="story-email">Email</Label>
      <Input {...args} id="story-email" />
    </div>
  ),
};

export const Invalid: Story = {
  args: { "aria-invalid": true, defaultValue: "not-an-email" },
};

export const Disabled: Story = {
  args: { disabled: true, defaultValue: "read only value" },
};
