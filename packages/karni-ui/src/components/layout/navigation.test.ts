import { describe, expect, it } from "vitest";
import type { NavigationItem } from "../../hooks/useNavigation";
import { isNavGroup } from "./layout";
import { activeRoute, navigationEntries } from "./navigation";
import { defaultNavIcons, navIcon } from "./nav-icons";

const item = (label: string, route: string, icon: string | null = null): NavigationItem => ({
  label,
  icon,
  route,
  children: [],
});

const MENU: NavigationItem[] = [
  item("Home", "/", "home"),
  {
    label: "Catalog",
    icon: "box",
    route: null,
    children: [item("Products", "/products"), item("Archived products", "/products/archived")],
  },
  item("Regions", "/regions", "unknown-name"),
];

describe("activeRoute", () => {
  it("prefers the exact route, then the longest route the path is under", () => {
    expect(activeRoute(MENU, "/products")).toBe("/products");
    expect(activeRoute(MENU, "/products/42")).toBe("/products");
    expect(activeRoute(MENU, "/products/archived/7")).toBe("/products/archived");
    expect(activeRoute(MENU, "/regions/?page=2")).toBe("/regions");
  });

  it("marks / only on /, and nothing for an unknown path", () => {
    expect(activeRoute(MENU, "/")).toBe("/");
    expect(activeRoute(MENU, "/reports")).toBeNull();
    expect(activeRoute(MENU, "/productsx")).toBeNull();
  });
});

describe("navigationEntries", () => {
  it("turns items into links and groups, in order, with one current page", () => {
    const entries = navigationEntries(MENU, { pathname: "/products/42" });
    expect(entries.map((entry) => entry.label)).toEqual(["Home", "Catalog", "Regions"]);
    const [home, catalog] = entries;
    expect(home && !isNavGroup(home) && home.href).toBe("/");
    expect(home && !isNavGroup(home) && home.active).toBe(false);
    if (catalog === undefined || !isNavGroup(catalog)) throw new Error("Catalog is a group");
    expect(
      catalog.children.map((child) => (isNavGroup(child) ? null : [child.href, child.active])),
    ).toEqual([
      ["/products", true],
      ["/products/archived", false],
    ]);
  });

  it("finds icons by name, with the app's icons first", () => {
    const own = { box: "BOX" };
    const entries = navigationEntries(MENU, { pathname: "/", icons: own });
    expect(entries[0]?.icon).toBe(defaultNavIcons["home"]);
    expect(entries[1]?.icon).toBe("BOX");
    expect(entries[2]?.icon).toBeUndefined();
  });
});

describe("navIcon", () => {
  it("knows the built-in names and shows nothing for others", () => {
    for (const name of ["home", "list", "chart", "bar-chart", "users", "settings", "map"]) {
      expect(navIcon(name)).toBeDefined();
    }
    expect(navIcon("nope")).toBeUndefined();
    expect(navIcon(null)).toBeUndefined();
  });
});
