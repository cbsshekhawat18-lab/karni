import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { API_BASE, server } from "../tests/msw/server";
import { orderFixture } from "../tests/msw/handlers";
import { renderWithCommerce } from "../tests/test-utils";
import { CustomerPage, CustomersPage } from "./Customers";
import { NewOrderPage } from "./NewOrderPage";
import { registerOrderPanel, unregisterOrderPanel } from "./panels";
import { StaffOrderPage } from "./StaffOrderPage";
import type { StaffOrder } from "./types";

const staffOrder: StaffOrder = {
  ...orderFixture,
  notes: [
    {
      id: "n1",
      kind: "internal",
      body: "Fragile.",
      author_name: "Theo Lindqvist",
      created_at: "2026-11-10T11:00:00Z",
    },
  ],
  payments: [
    {
      id: "p1",
      purpose: "full",
      amount: "32.00",
      status: "succeeded",
      provider: "test",
      created_at: "2026-11-10T10:05:00Z",
    },
  ],
  refunds: [],
  buyer: { user: null, name: "Ines Moreau", email: "ines@example.com", orders: 2, spent: "50.00" },
  refundable: "32.00",
  can_cancel: true,
  can_refund: true,
};

function staffBackend() {
  const posted: Array<{ path: string; body: unknown }> = [];
  server.use(
    http.get(`${API_BASE}/schema/`, () => HttpResponse.json({}, { status: 404 })),
    http.get(`${API_BASE}/orders/lookup/`, () => HttpResponse.json({ ...orderFixture, id: "o1" })),
    http.get(`${API_BASE}/orders/o1/staff/`, () => HttpResponse.json(staffOrder)),
    http.get(`${API_BASE}/orders/o1/history/`, () =>
      HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
    ),
    http.post(`${API_BASE}/orders/o1/:action/`, async ({ request, params }) => {
      posted.push({ path: String(params["action"]), body: await request.json() });
      return HttpResponse.json(staffOrder);
    }),
  );
  return posted;
}

describe("StaffOrderPage", () => {
  afterEach(() => unregisterOrderPanel("parcel"));

  it("shows the order with its buyer, payments, notes and the panels apps add", async () => {
    staffBackend();
    registerOrderPanel({
      key: "parcel",
      title: "Parcel",
      component: ({ order }) => <p>Parcel of order {order.number}</p>,
    });
    renderWithCommerce(<StaffOrderPage number="1001" />);
    expect(await screen.findByRole("heading", { name: "Order 1001" })).toBeInTheDocument();
    expect(screen.getByText("Fragile.")).toBeInTheDocument();
    expect(screen.getByText("Parcel of order 1001")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ines Moreau" })).toHaveAttribute(
      "href",
      "/customers/ines%40example.com",
    );
    expect(screen.getByText(/test, succeeded/)).toBeInTheDocument();
  });

  it("refunds one item back into stock", async () => {
    const posted = staffBackend();
    renderWithCommerce(<StaffOrderPage number="1001" />);
    await userEvent.click(await screen.findByRole("button", { name: "Refund" }));
    const form = screen.getByRole("form", { name: "Refund" });
    const quantity = within(form).getByLabelText(/Brass Lamp/);
    await userEvent.clear(quantity);
    await userEvent.type(quantity, "1");
    await userEvent.type(within(form).getByLabelText(/Reason/), "Chipped");
    await userEvent.click(within(form).getByRole("button", { name: "Refund" }));
    await waitFor(() =>
      expect(posted).toEqual([
        { path: "refund", body: { lines: { l1: 1 }, restock: true, reason: "Chipped" } },
      ]),
    );
  });

  it("asks before it cancels, and writes a note to the customer", async () => {
    const posted = staffBackend();
    renderWithCommerce(<StaffOrderPage number="1001" />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel order" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel the order" }));
    await userEvent.type(screen.getByLabelText("Add a note"), "Leaves today.");
    await userEvent.click(screen.getByLabelText(/Send it to the customer/));
    await userEvent.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() =>
      expect(posted).toEqual([
        { path: "cancel", body: {} },
        { path: "notes", body: { body: "Leaves today.", kind: "customer" } },
      ]),
    );
  });
});

describe("CustomersPage and CustomerPage", () => {
  it("lists the buyers with what they spent, each a link to their page", async () => {
    const asked: URL[] = [];
    server.use(
      http.get(`${API_BASE}/orders/customers/`, ({ request }) => {
        asked.push(new URL(request.url));
        return HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              email: "ines@example.com",
              name: "Ines Moreau",
              has_account: true,
              order_count: 2,
              spent: "50.00",
              currency: "EUR",
              first_order: "2026-10-01T10:00:00Z",
              last_order: "2026-11-10T10:00:00Z",
            },
          ],
        });
      }),
    );
    renderWithCommerce(<CustomersPage />);
    expect(await screen.findByRole("link", { name: "Ines Moreau" })).toHaveAttribute(
      "href",
      "/customers/ines%40example.com",
    );
    expect(screen.getByText("€50.00")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "-spent");
    await waitFor(() => expect(asked.at(-1)?.searchParams.get("ordering")).toBe("-spent"));
  });

  it("shows one customer's orders and addresses", async () => {
    server.use(
      http.get(`${API_BASE}/orders/customer/`, () =>
        HttpResponse.json({
          email: "ines@example.com",
          name: "Ines Moreau",
          account: null,
          order_count: 1,
          spent: "32.00",
          currency: "EUR",
          first_order: "2026-11-10T10:00:00Z",
          last_order: "2026-11-10T10:00:00Z",
          addresses: [orderFixture.billing],
          orders: [
            {
              id: "o1",
              number: 1001,
              status: "paid",
              total: "32.00",
              created_at: "2026-11-10T10:00:00Z",
            },
          ],
        }),
      ),
    );
    renderWithCommerce(<CustomerPage email="ines@example.com" />);
    expect(await screen.findByRole("heading", { name: "Ines Moreau" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Order 1001/ })).toHaveAttribute(
      "href",
      "/orders/1001",
    );
    expect(screen.getByText(/ordered as a guest/)).toBeInTheDocument();
    expect(screen.getByText(/4 Rue des Lilas/)).toBeInTheDocument();
  });
});

describe("NewOrderPage", () => {
  it("places an order of the items found for the customer, then opens it", async () => {
    let placed: unknown = null;
    server.use(
      http.get(`${API_BASE}/orders/items/`, () =>
        HttpResponse.json([
          {
            kind: "product",
            item: "p1",
            name: "Brass Lamp",
            sku: "BL-1",
            price: "16.00",
            available: 3,
          },
        ]),
      ),
      http.post(`${API_BASE}/orders/manual/`, async ({ request }) => {
        placed = await request.json();
        return HttpResponse.json(
          { id: "o9", number: 1009, link: "/orders/1009?key=k" },
          { status: 201 },
        );
      }),
    );
    const { navigated } = renderWithCommerce(<NewOrderPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add Brass Lamp" }));
    await userEvent.click(screen.getByRole("button", { name: "Add Brass Lamp" }));
    await userEvent.type(screen.getByLabelText("Email"), "noor@example.com");
    await userEvent.type(screen.getByLabelText(/Full name/), "Noor Haddad");
    await userEvent.type(screen.getByLabelText(/^Address\s*\*?$/), "1 Quay");
    await userEvent.type(screen.getByLabelText(/City/), "Porto");
    await userEvent.type(screen.getByLabelText(/Postcode/), "4000");
    await userEvent.click(screen.getByRole("button", { name: "Place the order" }));
    await waitFor(() => expect(navigated).toContain("/orders/1009"));
    expect(placed).toMatchObject({
      email: "noor@example.com",
      name: "Noor Haddad",
      send_link: true,
      lines: [{ kind: "product", item: "p1", quantity: 2 }],
    });
  });
});
