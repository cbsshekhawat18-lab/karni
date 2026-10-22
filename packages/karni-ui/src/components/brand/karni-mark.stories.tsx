import type { Meta, StoryObj } from "@storybook/react";
import { KarniMark } from "./karni-mark";

const meta = {
  title: "Support/KarniMark",
  component: KarniMark,
  tags: ["autodocs"],
} satisfies Meta<typeof KarniMark>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The default size (28px) draws the small-size variant; it is an image named "Karni". */
export const Playground: Story = {};

/** `auto` switches to the full drawing above 32px. */
export const Sizes: Story = {
  render: () => (
    <div className="flex items-end gap-6">
      <KarniMark size={20} />
      <KarniMark size={28} />
      <KarniMark size={48} />
      <KarniMark size={96} />
    </div>
  ),
};

/** Next to a visible name the mark is decorative: `title=""` hides it from screen readers. */
export const Decorative: Story = {
  render: () => (
    <span className="flex items-center gap-2 text-lg font-semibold">
      <KarniMark title="" />
      Karni
    </span>
  ),
};
