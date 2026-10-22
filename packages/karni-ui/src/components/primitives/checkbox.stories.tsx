import type { Meta, StoryObj } from "@storybook/react";
import { Checkbox } from "./checkbox";
import { Label } from "./label";

const meta = {
  title: "Primitives/Checkbox",
  component: Checkbox,
  tags: ["autodocs"],
} satisfies Meta<typeof Checkbox>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {
  args: { "aria-label": "Accept terms" },
};

export const WithLabel: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <Checkbox id="story-terms" />
      <Label htmlFor="story-terms">Accept terms and conditions</Label>
    </div>
  ),
};

export const Checked: Story = {
  args: { defaultChecked: true, "aria-label": "Accept terms" },
};

export const Disabled: Story = {
  args: { disabled: true, defaultChecked: true, "aria-label": "Accept terms" },
};

/** aria-invalid gives the destructive border (the form sets it with its error message). */
export const Invalid: Story = {
  render: () => (
    <div className="grid gap-1.5">
      <div className="flex items-center gap-2">
        <Checkbox id="story-terms-invalid" aria-invalid aria-describedby="story-terms-error" />
        <Label htmlFor="story-terms-invalid">Accept terms and conditions</Label>
      </div>
      <p id="story-terms-error" className="text-sm text-destructive">
        Accept the terms to continue.
      </p>
    </div>
  ),
};
