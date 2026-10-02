import type { Meta, StoryObj } from "@storybook/react";
import { Label } from "./label";
import { Textarea } from "./textarea";

const meta = {
  title: "Primitives/Textarea",
  component: Textarea,
  tags: ["autodocs"],
  args: {
    placeholder: "Tell us a little about the event…",
  },
} satisfies Meta<typeof Textarea>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};

export const WithLabel: Story = {
  render: (args) => (
    <div className="grid w-full max-w-sm gap-1.5">
      <Label htmlFor="story-description">Description</Label>
      <Textarea {...args} id="story-description" rows={5} />
    </div>
  ),
};

export const Disabled: Story = {
  args: { disabled: true, defaultValue: "Locked content" },
};
