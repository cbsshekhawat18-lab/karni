import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "../primitives/button";
import { EmptyState } from "./empty-state";

function InboxIcon(): JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
    >
      <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
    </svg>
  );
}

const meta = {
  title: "Support/EmptyState",
  component: EmptyState,
  tags: ["autodocs"],
  args: {
    title: "No events yet",
    description: "Create your first event to get started.",
  },
} satisfies Meta<typeof EmptyState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};

export const WithIconAndAction: Story = {
  args: {
    icon: <InboxIcon />,
    action: <Button>Create event</Button>,
  },
};

export const TitleOnly: Story = {
  args: {
    title: "Nothing here",
    description: undefined,
  },
};
