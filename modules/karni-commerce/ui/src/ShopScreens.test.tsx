import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { API_BASE, server } from "../tests/msw/server";
import {
  businessFixture,
  cartState,
  checkoutCalls,
  checkoutOptions,
  orderFixture,
} from "../tests/msw/handlers";
import { renderWithCommerce } from "../tests/test-utils";
import { AbandonedCartsPage } from "./AbandonedCartsPage";
import { CheckoutPage } from "./CheckoutPage";
import { Money } from "./Money";
import { OrderDocumentPage } from "./OrderDocumentPage";
import { OrderPage } from "./OrderPage";
import { ReportsPage } from "./ReportsPage";
import type { ReportResult } from "./types";

const salesReport: ReportResult = {
  key: "sales",
  title: "Sales by day",
  describe: "Paid orders.",
  dated: true,
  start: "2026-10-15",
  end: "2026-11-13",
  by: "day",
  currency: "EUR",
  columns: [
    { key: "date", label: "Day", format: "date" },
    { key: "orders", label: "Orders", format: "number" },
    { key: "total", label: "Sales", format: "money" },
  ],
  rows: [
    { date: "2026-11-10", orders: 2, total: "64.00" },
    { date: "2026-11-11", orders: 1, total: "16.00" },
  ],
  totals: { orders: 3, total: "80.00" },
};

function reportsBackend() {
  const seen: URL[] = [];
  server.use(
    http.get(`${API_BASE}/orders/reports/`, () =>
      HttpResponse.json([
        { key: "sales", title: "Sales by day", describe: "Paid orders.", dated: true },
      ]),
    ),
    http.get(`${API_BASE}/orders/reports/sales/`, ({ request }) => {
      const url = new URL(request.url);
      seen.push(url);
      if (url.searchParams.get("export") === "csv") {
        return new HttpResponse("Day,Orders\n", {
          headers: {
            "content-type": "text/csv",
            "content-disposition": 'attachment; filename="sales.csv"',
          },
        });
      }
      return HttpResponse.json(salesReport);
    }),
  );
  return seen;
}

describe("ReportsPage", () => {
  afterEach(() => window.history.replaceState(null, "", "/"));

  it("lists the reports, runs one with its totals and keeps it in the address", async () => {
    const seen = reportsBackend();
    renderWithCommerce(<ReportsPage />);
    await userEvent.click(await screen.findByRole("button", { name: /Sales by day/ }));
    expect(await screen.findByText("Paid orders.")).toBeInTheDocument();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("€64.00")).toBeInTheDocument();
    const totals = within(table).getByText("Total").closest("tr");
    expect(totals).not.toBeNull();
    expect(within(totals as HTMLElement).getByText("€80.00")).toBeInTheDocument();
    expect(window.location.search).toContain("report=sales");
    expect(seen[0].searchParams.get("by")).toBe("day");
    expect(seen[0].searchParams.get("start")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("asks for the CSV with export=csv", async () => {
    const seen = reportsBackend();
    window.history.replaceState(null, "", "/?report=sales");
    renderWithCommerce(<ReportsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Download CSV" }));
    await waitFor(() =>
      expect(seen.some((u) => u.searchParams.get("export") === "csv")).toBe(true),
    );
  });

  it("says so when there is no report for the person", async () => {
    server.use(http.get(`${API_BASE}/orders/reports/`, () => HttpResponse.json([])));
    renderWithCommerce(<ReportsPage />);
    expect(await screen.findByText("No reports for you")).toBeInTheDocument();
  });
});

describe("AbandonedCartsPage", () => {
  it("shows who left what, and searches", async () => {
    const searches: string[] = [];
    server.use(
      http.get(`${API_BASE}/carts/abandoned/`, ({ request }) => {
        const search = new URL(request.url).searchParams.get("search") ?? "";
        searches.push(search);
        return HttpResponse.json({
          count: 2,
          next: null,
          previous: null,
          results: [
            {
              id: "c1",
              email: "ines@example.com",
              name: "Ines Moreau",
              signed_in: true,
              items: 2,
              lines: ["2 x Desk Lamp"],
              value: "32.00",
              currency: "EUR",
              coupon: "SAVE10",
              touched_at: "2026-11-10T10:00:00Z",
              created_at: "2026-11-10T09:00:00Z",
            },
            {
              id: "c2",
              email: "",
              name: "",
              signed_in: false,
              items: 1,
              lines: ["1 x Seat"],
              value: "45.00",
              currency: "EUR",
              coupon: "",
              touched_at: "2026-11-10T10:00:00Z",
              created_at: "2026-11-10T09:00:00Z",
            },
          ],
        });
      }),
    );
    renderWithCommerce(<AbandonedCartsPage />);
    expect(await screen.findByText("2 x Desk Lamp")).toBeInTheDocument();
    expect(screen.getByText("A visitor (no email yet)")).toBeInTheDocument();
    expect(screen.getByText("€32.00")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search"), "ines");
    await waitFor(() => expect(searches).toContain("ines"));
  });

  it("explains an empty list", async () => {
    server.use(
      http.get(`${API_BASE}/carts/abandoned/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    renderWithCommerce(<AbandonedCartsPage />);
    expect(await screen.findByText(/No abandoned carts: every cart/)).toBeInTheDocument();
  });
});

describe("OrderDocumentPage", () => {
  it("loads the page into a frame and goes back to the order", async () => {
    server.use(
      http.get(`${API_BASE}/orders/document/`, ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get("kind")).toBe("invoice");
        return new HttpResponse("<html><body><h1>Invoice INV-1</h1></body></html>", {
          headers: { "content-type": "text/html" },
        });
      }),
    );
    const { navigated } = renderWithCommerce(<OrderDocumentPage number={1001} orderKey="k1" />);
    const frame = await screen.findByTitle("Invoice for order 1001");
    expect(frame.getAttribute("srcdoc")).toContain("Invoice INV-1");
    expect(frame).toHaveAttribute("sandbox", "allow-same-origin allow-modals");
    await userEvent.click(screen.getByRole("button", { name: "Back to the order" }));
    expect(navigated).toEqual(["/orders/1001?key=k1"]);
  });

  it("says there is no such order", async () => {
    server.use(
      http.get(`${API_BASE}/orders/document/`, () =>
        HttpResponse.json({ detail: "Not found." }, { status: 404 }),
      ),
    );
    renderWithCommerce(<OrderDocumentPage number={9} />);
    expect(await screen.findByText("No such order.")).toBeInTheDocument();
  });
});

describe("OrderPage invoice and downloads", () => {
  it("links the invoice and a download in the delivery list", async () => {
    server.use(
      http.get(`${API_BASE}/orders/lookup/`, () =>
        HttpResponse.json({
          ...orderFixture,
          invoice: "INV-2026-0001",
          fulfilment: [
            {
              title: "Download",
              status: "ready",
              label: "Ready",
              detail: "",
              at: null,
              link: "http://localhost/api/files/abc/",
              link_label: "Get the guide",
            },
          ],
        }),
      ),
    );
    renderWithCommerce(<OrderPage number="1001" orderKey="k1" />);
    expect(
      await screen.findByRole("link", { name: "Print invoice INV-2026-0001" }),
    ).toHaveAttribute("href", "/orders/1001/invoice?key=k1");
    expect(screen.getByRole("link", { name: "Get the guide" })).toHaveAttribute(
      "href",
      "http://localhost/api/files/abc/",
    );
  });
});

describe("CheckoutPage options", () => {
  beforeEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, assign: vi.fn() },
    });
  });

  it("sends accept_terms and shows the server's word when it is missing", async () => {
    Object.assign(checkoutOptions, { accept_terms: true, terms_url: "/terms-of-sale" });
    cartState.lines = [{ kind: "seat", item: "seat", quantity: 1 }];
    renderWithCommerce(<CheckoutPage />);
    await userEvent.type(
      await screen.findByLabelText("Email, for the confirmation"),
      "g@example.com",
    );
    expect(screen.getByRole("link", { name: "terms of sale" })).toHaveAttribute(
      "href",
      "/terms-of-sale",
    );
    const place = screen.getByRole("button", { name: "Place the order and pay" });
    await userEvent.click(place);
    expect(await screen.findByText("Accept the terms of sale.")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/I accept the/));
    await userEvent.click(place);
    await waitFor(() => expect(checkoutCalls).toHaveLength(2));
    expect((checkoutCalls[1] as Record<string, unknown>).accept_terms).toBe(true);
  });

  it("asks a visitor to sign in when guests may not order", async () => {
    checkoutOptions.guest_checkout = false;
    cartState.lines = [{ kind: "seat", item: "seat", quantity: 1 }];
    renderWithCommerce(<CheckoutPage />);
    expect(await screen.findByRole("link", { name: "Sign in to place an order" })).toHaveAttribute(
      "href",
      "/signin?next=%2Fcheckout",
    );
    expect(
      screen.queryByRole("button", { name: "Place the order and pay" }),
    ).not.toBeInTheDocument();
  });
});

describe("Money with the business's display", () => {
  it("shows the currency code when the business asks for it", async () => {
    server.use(
      http.get(`${API_BASE}/preferences/public/`, () =>
        HttpResponse.json({ ...businessFixture, currency_display: "code" }),
      ),
    );
    renderWithCommerce(<Money value="5" currency="EUR" />);
    await waitFor(() => expect(screen.getByText(/EUR/)).toBeInTheDocument());
    expect(screen.queryByText(/€/)).not.toBeInTheDocument();
  });
});
