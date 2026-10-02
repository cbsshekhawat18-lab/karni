import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "../primitives/button";
import { Page } from "./page";

const meta = {
  title: "Support/Page",
  component: Page,
  tags: ["autodocs"],
  args: {
    title: "Events",
    description: "Everything scheduled across your venues.",
  },
} satisfies Meta<typeof Page>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {
  args: {
    children: (
      <div className="rounded-lg border border-border p-6 text-sm text-muted-foreground">
        Page content goes here — e.g. a ResourceTable.
      </div>
    ),
  },
};

export const WithActions: Story = {
  args: {
    actions: (
      <>
        <Button variant="outline">Export</Button>
        <Button>New event</Button>
      </>
    ),
    children: (
      <div className="rounded-lg border border-border p-6 text-sm text-muted-foreground">
        The actions slot sits to the right of the title.
      </div>
    ),
  },
};

export const CustomHeader: Story = {
  args: {
    header: (
      <div className="rounded-lg bg-muted p-4 text-sm text-muted-foreground">
        The <code>header</code> escape hatch replaces the derived title row entirely.
      </div>
    ),
    children: <p className="text-sm text-muted-foreground">Content below the custom header.</p>,
  },
};
