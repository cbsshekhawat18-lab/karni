import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Layout, type LayoutNavItem } from "./layout";

const navItems: readonly LayoutNavItem[] = [
  { label: "Events", href: "/events", active: true },
  { label: "Venues", href: "/venues" },
];

describe("Layout", () => {
  it("renders nav items as links inside a labelled nav", () => {
    render(<Layout navItems={navItems}>content</Layout>);
    const nav = screen.getByRole("navigation", { name: "Main" });
    const events = within(nav).getByRole("link", { name: "Events" });
    expect(events).toHaveAttribute("href", "/events");
    expect(within(nav).getByRole("link", { name: "Venues" })).toHaveAttribute("href", "/venues");
  });

  it("marks the active item with aria-current=page", () => {
    render(<Layout navItems={navItems}>content</Layout>);
    expect(screen.getByRole("link", { name: "Events" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Venues" })).not.toHaveAttribute("aria-current");
  });

  it("renders children in <main> and the header slot", () => {
    render(
      <Layout navItems={navItems} header={<span>Acme admin</span>}>
        <p>Dashboard body</p>
      </Layout>,
    );
    expect(within(screen.getByRole("main")).getByText("Dashboard body")).toBeInTheDocument();
    expect(within(screen.getByRole("banner")).getByText("Acme admin")).toBeInTheDocument();
  });

  it("toggles the mobile drawer from the menu button", async () => {
    const user = userEvent.setup();
    render(<Layout navItems={navItems}>content</Layout>);

    const toggle = screen.getByRole("button", { name: "Open navigation" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getAllByRole("navigation", { name: "Main" })).toHaveLength(1);

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    // Static sidebar + open drawer each render the nav.
    expect(screen.getAllByRole("navigation", { name: "Main" })).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(screen.getAllByRole("navigation", { name: "Main" })).toHaveLength(1);
  });

  it("closes the mobile drawer on Escape and on backdrop click", async () => {
    const user = userEvent.setup();
    render(<Layout navItems={navItems}>content</Layout>);
    const toggle = screen.getByRole("button", { name: "Open navigation" });

    await user.click(toggle);
    await user.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    await user.click(screen.getByTestId("karni-layout-backdrop"));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("renderNavItem wraps items for router integration (escape hatch)", () => {
    render(
      <Layout
        navItems={navItems}
        renderNavItem={(item, { defaultClassName }) => (
          <button type="button" className={defaultClassName} data-href={item.href}>
            {item.label}
          </button>
        )}
      >
        content
      </Layout>,
    );
    expect(screen.getByRole("button", { name: "Events" })).toHaveAttribute("data-href", "/events");
    expect(screen.queryByRole("link", { name: "Events" })).not.toBeInTheDocument();
  });

  it("sidebar slot replaces the derived nav wholesale (escape hatch)", () => {
    render(
      <Layout navItems={navItems} sidebar={<div>Custom sidebar</div>}>
        content
      </Layout>,
    );
    expect(screen.getByText("Custom sidebar")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });

  it("renders sidebarHeader and sidebarFooter slots", () => {
    render(
      <Layout navItems={navItems} sidebarHeader={<span>Logo</span>} sidebarFooter={<span>v1</span>}>
        content
      </Layout>,
    );
    expect(screen.getByText("Logo")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
  });
});
