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
        Page content goes here, for example a ResourceTable.
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

/** The Title slot: a page inside a dialog or a tab panel takes an <h2>. */
export const TitleSlot: Story = {
  args: {
    title: "Attendees",
    description: "A section of the event page.",
    slots: {
      Title: ({ children }) => (
        <h2 className="text-xl font-semibold tracking-tight text-foreground">{children}</h2>
      ),
    },
    children: (
      <div className="rounded-lg border border-border p-6 text-sm text-muted-foreground">
        The Header, Title, Description and Actions slots replace their pieces.
      </div>
    ),
  },
};
