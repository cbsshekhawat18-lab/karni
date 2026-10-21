import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "../primitives/button";
import { Page } from "../page/page";
import { Layout, type LayoutNavLinkProps } from "./layout";

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

/**
 * The drawer below the md breakpoint, open: a modal dialog that holds focus
 * until Escape, the backdrop, the close button or a link closes it. On a
 * wide window it closes itself (the menu button is hidden there).
 */
export const DrawerOpen: Story = {
  globals: { viewport: { value: "mobile2", isRotated: false } },
  args: {
    defaultMobileNavOpen: true,
    sidebarHeader: <span className="px-3 text-lg font-semibold">Acme</span>,
    sidebarFooter: (
      <Button variant="ghost" className="w-full justify-start">
        Sign out
      </Button>
    ),
    header: <span className="text-sm font-medium">Events admin</span>,
    children: (
      <Page title="Events" description="The drawer covers the page until it closes.">
        <div className="rounded-lg border border-border p-6 text-sm text-muted-foreground">
          Main content area.
        </div>
      </Page>
    ),
  },
};

/** Stand-in for a router's link (e.g. TanStack Router's <Link to>), through the NavLink slot. */
function RouterLink({ item, href, onClick, ...props }: LayoutNavLinkProps) {
  return (
    <a
      {...props}
      href={href}
      onClick={(event) => {
        event.preventDefault();
        console.info(`navigate to ${item.href}`);
        onClick();
      }}
    />
  );
}

export const NavLinkSlot: Story = {
  args: {
    slots: { NavLink: RouterLink },
    children: (
      <Page title="Events">
        <p className="text-sm text-muted-foreground">
          Each nav link renders through the NavLink slot (check the console).
        </p>
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
