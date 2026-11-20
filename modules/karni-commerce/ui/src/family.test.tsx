/**
 * Commerce's part of the family pages: a kind's line renderer on the cart and
 * the order page, /orders and /orders/<number> per audience, and what
 * `register()` adds (the account section, the person tab, the order link).
 */
import {
  accountSections,
  personTabs,
  recordHref,
  unregisterAccountSection,
  unregisterPersonTab,
  unregisterRecordLink,
} from "@karni/ui";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { API_BASE } from "../tests/msw/handlers";
import { server } from "../tests/msw/server";
import { renderWithCommerce } from "../tests/test-utils";
import { CartPage } from "./CartPage";
import { FamilyOrderPage, FamilyOrdersPage, register } from "./family";
import { registerLineRenderer, unregisterLineRenderer } from "./lines";
import { OrderPage } from "./OrderPage";
import { registerCommercePaths, registeredCommercePaths } from "./routes";

function signedIn(roles: string[]): void {
  server.use(
    http.get(`${API_BASE}/auth/me/`, () =>
      HttpResponse.json({ id: 3, email: "ines@example.com", roles }),
    ),
  );
}

afterEach(() => {
  unregisterLineRenderer("product");
  unregisterAccountSection("orders");
  unregisterPersonTab("orders");
  unregisterRecordLink("orders");
});

describe("line renderers", () => {
  it("draw a kind's lines on the order page and in the cart", async () => {
    registerLineRenderer("product", ({ line, place }) => (
      <span>
        {line.name} drawn for the {place}
      </span>
    ));
    const order = renderWithCommerce(<OrderPage number="1001" orderKey="k1" />);
    expect(await screen.findByText("Brass Lamp drawn for the order")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Brass Lamp" })).not.toBeInTheDocument();
    order.unmount();
    unregisterLineRenderer("product");
    renderWithCommerce(<OrderPage number="1001" orderKey="k1" />);
    expect(await screen.findByRole("link", { name: "Brass Lamp" })).toBeInTheDocument();
  });

  it("leave a kind without one on the default", async () => {
    renderWithCommerce(<CartPage />);
    expect(await screen.findByRole("heading", { name: "Your cart" })).toBeInTheDocument();
  });
});

describe("the family's order pages", () => {
  it("give a customer their own orders and their order", async () => {
    signedIn(["customer"]);
    renderWithCommerce(<FamilyOrdersPage />);
    expect(await screen.findByRole("heading", { name: "Your orders" })).toBeInTheDocument();
  });

  it("give staff the order to run", async () => {
    signedIn(["shop-staff"]);
    const asked: string[] = [];
    server.use(
      http.get(`${API_BASE}/orders/lookup/`, ({ request }) => {
        asked.push(new URL(request.url).pathname);
        return HttpResponse.json({ id: "o1", number: 1001 });
      }),
      http.get(`${API_BASE}/orders/o1/staff/`, ({ request }) => {
        asked.push(new URL(request.url).pathname);
        return HttpResponse.json({ detail: "stop here" }, { status: 404 });
      }),
    );
    renderWithCommerce(<FamilyOrderPage number="1001" />);
    await waitFor(() => expect(asked).toContain("/api/orders/o1/staff/"));
  });

  it("give the buyer the order page, with the guest's key", async () => {
    renderWithCommerce(<FamilyOrderPage number="1001" orderKey="k1" />);
    expect(await screen.findByRole("heading", { name: "Order 1001" })).toBeInTheDocument();
  });
});

describe("register", () => {
  it("adds the account section, the person tab and the link to an order", () => {
    register();
    expect(accountSections().map((section) => section.key)).toContain("orders");
    expect(personTabs().map((tab) => tab.key)).toEqual(["orders"]);
    expect(recordHref("orders", { number: 1001 })).toBe("/orders/1001");
    expect(recordHref("orders", { id: "o1", title: "1002" })).toBe("/orders/1002");
  });

  it("lets a selling part set where an empty cart sends the buyer", () => {
    registerCommercePaths({ browse: "/shop/catalogue" });
    expect(registeredCommercePaths().browse).toBe("/shop/catalogue");
    registerCommercePaths({ browse: "/" });
  });
});
