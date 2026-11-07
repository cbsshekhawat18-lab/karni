import { describe, expect, it } from "vitest";
import { isSignInRoute, routeLabel, routeNavItems } from "./route-nav";

const PATHS = ["/", "/orders", "/orders/$id", "/orders/$id/edit", "/orders/new", "/login"];

describe("routeNavItems", () => {
  it("lists the static routes in registration order and marks the active one", () => {
    expect(routeNavItems(PATHS, { pathname: "/orders/42" })).toEqual([
      { href: "/", label: "Home", active: false },
      { href: "/orders", label: "Orders", active: true },
      { href: "/login", label: "Login", active: false },
    ]);
  });

  it("drops the sign-in page once someone is signed in", () => {
    const hrefs = routeNavItems(PATHS, { pathname: "/", signedIn: true }).map((item) => item.href);
    expect(hrefs).toEqual(["/", "/orders"]);
  });

  it("keeps the sign-in page while the session is still loading (signedIn false)", () => {
    const hrefs = routeNavItems(PATHS, { pathname: "/login" }).map((item) => item.href);
    expect(hrefs).toContain("/login");
  });

  it("marks only the exact route or a page under it, never a prefix", () => {
    const items = routeNavItems(["/", "/orders", "/orders-archive"], {
      pathname: "/orders-archive",
    });
    expect(items.map((item) => [item.href, item.active])).toEqual([
      ["/", false],
      ["/orders", false],
      ["/orders-archive", true],
    ]);
  });

  it("takes custom label, hidden and signIn rules (a custom rule replaces the default)", () => {
    const items = routeNavItems(["/", "/staff/sign-in", "/reports", "/$slug"], {
      pathname: "/",
      signedIn: true,
      label: (path) => path.toUpperCase(),
      hidden: (path) => path === "/reports",
      signIn: (path) => path.endsWith("/sign-in"),
    });
    expect(items.map((item) => item.label)).toEqual(["/", "/$SLUG"]);
  });

  it("lists a path once", () => {
    expect(routeNavItems(["/a", "/a"], { pathname: "/" })).toHaveLength(1);
  });
});

describe("routeLabel and isSignInRoute", () => {
  it("humanises the last segment", () => {
    expect(routeLabel("/")).toBe("Home");
    expect(routeLabel("/line-items")).toBe("Line items");
    expect(routeLabel("/admin/audit_log")).toBe("Audit log");
  });

  it("knows the sign-in pages", () => {
    expect(isSignInRoute("/login")).toBe(true);
    expect(isSignInRoute("/staff/sign-in/")).toBe(true);
    expect(isSignInRoute("/signin")).toBe(true);
    expect(isSignInRoute("/logins")).toBe(false);
    expect(isSignInRoute("/")).toBe(false);
  });
});
