import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { NavigationMenu } from "../../hooks/useNavigation";
import { createKarniClient, type KarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import {
  Layout,
  defaultLayoutSlots,
  isNavGroup,
  type LayoutNavEntry,
  type LayoutNavGroupProps,
  type LayoutNavItem,
  type LayoutNavLinkProps,
  type LayoutProps,
  type LayoutSlots,
} from "./layout";

const navItems: readonly LayoutNavItem[] = [
  { label: "Events", href: "/events", active: true },
  { label: "Venues", href: "/venues" },
];
/** Same-page targets, so following a link in jsdom does not try to navigate. */
const hashItems: readonly LayoutNavItem[] = [
  { label: "Events", href: "#events", active: true },
  { label: "Venues", href: "#venues" },
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

  it("gives nav links a visible keyboard focus ring", () => {
    render(<Layout navItems={navItems}>content</Layout>);
    expect(screen.getByRole("link", { name: "Venues" })).toHaveClass(
      "focus-visible:ring-2",
      "focus-visible:ring-ring",
    );
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

  it("starts with a skip link to <main>, which takes focus", async () => {
    const user = userEvent.setup();
    render(<Layout navItems={navItems}>content</Layout>);
    await user.tab();
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(skip).toHaveFocus();
    const main = screen.getByRole("main");
    expect(skip).toHaveAttribute("href", `#${main.id}`);
    expect(main).toHaveAttribute("tabindex", "-1");
    await user.keyboard("{Enter}");
    expect(main).toHaveFocus();
    // Focus moved without a hash change, so a hash router keeps its route.
    expect(window.location.hash).toBe("");
  });
});

describe("Layout mobile drawer", () => {
  it("opens as a labelled modal dialog holding the nav", async () => {
    const user = userEvent.setup();
    render(<Layout navItems={navItems}>content</Layout>);

    const toggle = screen.getByRole("button", { name: "Open navigation" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-haspopup", "dialog");
    // aria-controls names the drawer only while it exists.
    expect(toggle).not.toHaveAttribute("aria-controls");

    await user.click(toggle);
    const dialog = screen.getByRole("dialog", { name: "Navigation" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", dialog.id);
    expect(document.getElementById(dialog.id)).toBe(dialog);
    expect(within(dialog).getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    // The page behind is hidden from assistive tech: one nav is exposed, the drawer's.
    expect(screen.getAllByRole("navigation", { name: "Main" })).toHaveLength(1);

    await user.click(within(dialog).getByRole("button", { name: "Close navigation" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(toggle).not.toHaveAttribute("aria-controls");
  });

  it("moves focus in, keeps it there, and returns it to the menu button on Escape", async () => {
    const user = userEvent.setup();
    render(<Layout navItems={navItems}>content</Layout>);
    const toggle = screen.getByRole("button", { name: "Open navigation" });

    toggle.focus();
    await user.keyboard("{Enter}");
    const dialog = screen.getByRole("dialog", { name: "Navigation" });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);

    // Tab cycles inside the drawer: close button, the two links, back around.
    for (let i = 0; i < 5; i += 1) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on backdrop click and when a link is followed", async () => {
    const user = userEvent.setup();
    render(<Layout navItems={hashItems}>content</Layout>);
    const toggle = screen.getByRole("button", { name: "Open navigation" });

    await user.click(toggle);
    await user.click(screen.getByTestId("karni-layout-backdrop"));
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("link", { name: "Venues" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("can be controlled (mobileNavOpen + onMobileNavOpenChange)", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <Layout navItems={navItems} mobileNavOpen onMobileNavOpenChange={onChange}>
        content
      </Layout>,
    );
    expect(screen.getByRole("dialog", { name: "Navigation" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(onChange).toHaveBeenCalledWith(false);
    // Still open until the owner says otherwise.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    rerender(
      <Layout navItems={navItems} mobileNavOpen={false} onMobileNavOpenChange={onChange}>
        content
      </Layout>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes once the window is wide enough to hide the menu button", () => {
    render(
      <Layout navItems={navItems} defaultMobileNavOpen>
        content
      </Layout>,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // What `md:hidden` does to the button once the window passes md.
    const toggle = screen.getByRole("button", { name: "Open navigation", hidden: true });
    toggle.style.display = "none";
    act(() => {
      fireEvent(window, new Event("resize"));
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Layout escape hatches", () => {
  it("renderNavItem wraps items for router integration", () => {
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

  it("sidebar replaces the derived nav wholesale", () => {
    render(
      <Layout navItems={navItems} sidebar={<div>Custom sidebar</div>}>
        content
      </Layout>,
    );
    expect(screen.getByText("Custom sidebar")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });

  it("renders sidebarHeader and sidebarFooter", () => {
    render(
      <Layout navItems={navItems} sidebarHeader={<span>Logo</span>} sidebarFooter={<span>v1</span>}>
        content
      </Layout>,
    );
    expect(screen.getByText("Logo")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
  });

  it("merges className onto the root", () => {
    const { container } = render(<Layout className="min-h-0">content</Layout>);
    expect(container.firstElementChild).toHaveClass("min-h-0", "flex");
  });

  it("the NavLink slot replaces each link and can close the drawer", async () => {
    const user = userEvent.setup();
    function RouterLink({ item, onClick, children, ...props }: LayoutNavLinkProps) {
      return (
        <a {...props} data-router-link={item.href} onClick={onClick}>
          {children}
        </a>
      );
    }
    render(
      <Layout navItems={hashItems} slots={{ NavLink: RouterLink }}>
        content
      </Layout>,
    );
    const link = screen.getByRole("link", { name: "Events" });
    expect(link).toHaveAttribute("data-router-link", "#events");
    expect(link).toHaveAttribute("aria-current", "page");

    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("link", { name: "Venues" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("the Header, Sidebar, MobileDrawer and SkipLink slots replace their pieces", async () => {
    const user = userEvent.setup();
    const slots: Partial<LayoutSlots> = {
      Header: ({ menuButton, children }) => (
        <div data-testid="custom-header">
          {menuButton}
          {children}
        </div>
      ),
      Sidebar: ({ nav }) => <div data-testid="custom-sidebar">{nav}</div>,
      MobileDrawer: ({ open, nav }) => (open ? <div data-testid="custom-drawer">{nav}</div> : null),
      SkipLink: () => null,
    };
    render(
      <Layout navItems={navItems} header="Acme" slots={slots}>
        content
      </Layout>,
    );
    expect(screen.getByTestId("custom-header")).toHaveTextContent("Acme");
    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
    expect(screen.getByTestId("custom-sidebar")).toContainElement(
      screen.getByRole("link", { name: "Events" }),
    );
    expect(screen.queryByRole("link", { name: "Skip to content" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByTestId("custom-drawer")).toBeInTheDocument();
  });

  it("exports its default slots for wrapping", () => {
    function Wrapped(props: React.ComponentProps<LayoutSlots["Header"]>) {
      return (
        <div data-testid="wrapper">
          <defaultLayoutSlots.Header {...props} />
        </div>
      );
    }
    render(
      <Layout header="Acme" slots={{ Header: Wrapped }}>
        content
      </Layout>,
    );
    expect(within(screen.getByTestId("wrapper")).getByRole("banner")).toHaveTextContent("Acme");
  });
});

const groupItems: readonly LayoutNavEntry[] = [
  { label: "Home", href: "#home" },
  {
    label: "Catalog",
    key: "catalog",
    children: [
      { label: "Products", href: "#products" },
      { label: "Categories", href: "#categories" },
    ],
  },
];

describe("Layout nav groups (experimental)", () => {
  it("renders a group as a button that controls its entries, closed by default", () => {
    render(<Layout navItems={groupItems}>content</Layout>);
    const nav = screen.getByRole("navigation", { name: "Main" });
    const button = within(nav).getByRole("button", { name: "Catalog" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    const region = document.getElementById(button.getAttribute("aria-controls") ?? "");
    expect(region).not.toBeNull();
    expect(region).not.toBeVisible();
    expect(within(nav).queryByRole("link", { name: "Products" })).toBeNull();
  });

  it("opens and closes from the keyboard (Enter and Space)", async () => {
    const user = userEvent.setup();
    render(<Layout navItems={groupItems}>content</Layout>);
    const button = screen.getByRole("button", { name: "Catalog" });
    button.focus();
    await user.keyboard("{Enter}");
    expect(button).toHaveAttribute("aria-expanded", "true");
    const group = screen.getByRole("group", { name: "Catalog" });
    expect(within(group).getByRole("link", { name: "Products" })).toBeVisible();
    await user.tab();
    expect(screen.getByRole("link", { name: "Products" })).toHaveFocus();
    button.focus();
    await user.keyboard(" ");
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("opens the group that holds the current page", () => {
    const entries: readonly LayoutNavEntry[] = [
      { label: "Catalog", children: [{ label: "Products", href: "#products", active: true }] },
    ];
    render(<Layout navItems={entries}>content</Layout>);
    expect(screen.getByRole("button", { name: "Catalog" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("link", { name: "Products" })).toHaveAttribute("aria-current", "page");
  });

  it("nests groups, and defaultOpen opens one", () => {
    const entries: readonly LayoutNavEntry[] = [
      {
        label: "Setup",
        defaultOpen: true,
        children: [{ label: "Places", children: [{ label: "Regions", href: "#regions" }] }],
      },
    ];
    render(<Layout navItems={entries}>content</Layout>);
    expect(screen.getByRole("button", { name: "Setup" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Places" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("the NavGroup slot replaces each group", () => {
    function PlainGroup(props: LayoutNavGroupProps): React.ReactElement {
      return (
        <section aria-label={String(props.group.label)} data-open={String(props.open)}>
          {props.children}
        </section>
      );
    }
    render(
      <Layout navItems={groupItems} slots={{ NavGroup: PlainGroup }}>
        content
      </Layout>,
    );
    const section = screen.getByRole("region", { name: "Catalog" });
    expect(section).toHaveAttribute("data-open", "false");
    expect(within(section).getByRole("link", { name: "Products" })).toBeInTheDocument();
    expect(isNavGroup(groupItems[1] as LayoutNavEntry)).toBe(true);
  });
});

function serverMenu(menu: NavigationMenu | Error): KarniClient {
  const base = createKarniClient({ baseUrl: "http://karni.test/api" });
  return {
    ...base,
    request: <T,>(path: string): Promise<T> => {
      if (path !== "/navigation/") return Promise.reject(new Error(path));
      return menu instanceof Error ? Promise.reject(menu) : Promise.resolve(menu as T);
    },
  };
}

function renderServer(menu: NavigationMenu | Error, props: Partial<LayoutProps> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <KarniProvider client={serverMenu(menu)} queryClient={queryClient}>
      <Layout navSource="server" {...props}>
        content
      </Layout>
    </KarniProvider>,
  );
}

const SERVER_MENU: NavigationMenu = {
  items: [
    { label: "Home", icon: "home", route: "/", children: [] },
    {
      label: "Catalog",
      icon: "box",
      route: null,
      children: [
        { label: "Products", icon: null, route: "/products", children: [] },
        { label: "Categories", icon: "own-icon", route: "/categories", children: [] },
      ],
    },
  ],
};

describe("Layout server menu (experimental)", () => {
  it("renders the server's menu with the current page from pathname", async () => {
    renderServer(SERVER_MENU, { pathname: "/products/42" });
    const products = await screen.findByRole("link", { name: "Products" });
    expect(products).toHaveAttribute("href", "/products");
    expect(products).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Catalog" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });

  it("shows icons by name, the app's own over the defaults", async () => {
    renderServer(SERVER_MENU, {
      pathname: "/categories",
      icons: { "own-icon": <svg data-testid="own-icon" /> },
    });
    const home = await screen.findByRole("link", { name: "Home" });
    expect(home.querySelector('svg[data-icon="home"]')).not.toBeNull();
    expect(screen.getByTestId("own-icon")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Products" }).querySelector("svg")).toBeNull();
  });

  it("is busy while loading and falls back to navItems when the request fails", async () => {
    renderServer(new Error("offline"), { navItems: [{ label: "Static", href: "#static" }] });
    expect(screen.getByRole("navigation", { name: "Main" })).toHaveAttribute("aria-busy", "true");
    expect(await screen.findByRole("link", { name: "Static" })).toBeInTheDocument();
  });

  it("follows the window's path without a pathname prop", async () => {
    window.history.pushState({}, "", "/categories");
    try {
      renderServer(SERVER_MENU);
      expect(await screen.findByRole("link", { name: "Categories" })).toHaveAttribute(
        "aria-current",
        "page",
      );
    } finally {
      window.history.pushState({}, "", "/");
    }
  });

  it("passes server links through renderNavItem like static ones", async () => {
    renderServer(SERVER_MENU, {
      pathname: "/",
      renderNavItem: (item, { defaultNode }) => (
        <span data-testid={`wrapped-${item.href}`}>{defaultNode}</span>
      ),
    });
    expect(await screen.findByTestId("wrapped-/")).toBeInTheDocument();
  });
});
