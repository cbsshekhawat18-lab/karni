import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "../primitives/button";
import { Page } from "../page/page";
import { Layout } from "./layout";

const meta = {
  title: "Support/Layout",
  component: Layout,
  tags: ["autodocs"],
  parameters: {
    layout: "fullscreen",
  },
  args: {
    navItems: [
      { label: "Dashboard", href: "#dashboard" },
      { label: "Events", href: "#events", active: true },
      { label: "Venues", href: "#venues" },
      { label: "Settings", href: "#settings" },
    ],
  },
} satisfies Meta<typeof Layout>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {
  args: {
    sidebarHeader: <span className="px-3 text-lg font-semibold">Acme</span>,
    children: (
      <Page title="Events" description="Resize below the md breakpoint to see the drawer.">
        <div className="rounded-lg border border-border p-6 text-sm text-muted-foreground">
          Main content area.
        </div>
      </Page>
    ),
  },
};

export const WithHeaderAndFooterSlots: Story = {
  args: {
    sidebarHeader: <span className="px-3 text-lg font-semibold">Acme</span>,
    sidebarFooter: (
      <Button variant="ghost" className="w-full justify-start">
        Sign out
      </Button>
    ),
    header: (
      <>
        <span className="text-sm font-medium">Events admin</span>
        <span className="ml-auto text-sm text-muted-foreground">jane@example.com</span>
      </>
    ),
    children: (
      <Page title="Dashboard">
        <div className="rounded-lg border border-border p-6 text-sm text-muted-foreground">
          Header, sidebarHeader and sidebarFooter are free slots.
        </div>
      </Page>
    ),
  },
};

export const RouterIntegration: Story = {
  args: {
    renderNavItem: (item, { defaultClassName }) => (
      // Stand-in for a router link (e.g. TanStack Router's <Link>): reuse the
      // styled class and take over navigation yourself.
      <button
        type="button"
        className={defaultClassName}
        onClick={() => {
          console.info(`navigate to ${item.href}`);
        }}
      >
        {item.label}
      </button>
    ),
    children: (
      <Page title="Events">
        <p className="text-sm text-muted-foreground">
          Nav items render through the renderNavItem escape hatch (check the console).
        </p>
      </Page>
    ),
  },
};
