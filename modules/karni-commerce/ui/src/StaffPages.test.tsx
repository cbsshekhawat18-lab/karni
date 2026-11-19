import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { API_BASE, server } from "../tests/msw/server";
import { orderFixture } from "../tests/msw/handlers";
import { renderWithCommerce } from "../tests/test-utils";
import { CustomerPage, CustomersPage } from "./Customers";
import { NewOrderPage } from "./NewOrderPage";
import {
  registerBuyerOrderPanel,
  registerOrderPanel,
  unregisterBuyerOrderPanel,
  unregisterOrderPanel,
} from "./panels";
import { OrderPage } from "./OrderPage";
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
  buyer: {
    person: "p-1",
    user: null,
    name: "Ines Moreau",
    email: "ines@example.com",
    orders: 2,
    spent: "50.00",
  },
  refundable: "32.00",
  can_cancel: true,
  can_refund: true,
  can_request_balance: false,
};

function staffBackend(order: StaffOrder = staffOrder) {
  const posted: Array<{ path: string; body: unknown }> = [];
  server.use(
    http.get(`${API_BASE}/schema/`, () => HttpResponse.json({}, { status: 404 })),
    http.get(`${API_BASE}/orders/lookup/`, () => HttpResponse.json({ ...orderFixture, id: "o1" })),
    http.get(`${API_BASE}/orders/o1/staff/`, () => HttpResponse.json(order)),
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

const bookingLine = {
  ...orderFixture.lines[0],
  id: "l2",
  kind: "booking",
  item: "v1",
  name: "Booking: Tuning",
  sku: "",
  details: [],
  needs_shipping: false,
};

/** An order of a booking whose deposit is paid: 20.00 of 80.00. */
const partPaid: StaffOrder = {
  ...staffOrder,
  status: "part_paid",
  total: "80.00",
  deposit: "20.00",
  amount_paid: "20.00",
  balance: "60.00",
  due_now: "60.00",
  payable: true,
  lines: [bookingLine],
  payments: [{ ...staffOrder.payments[0], purpose: "deposit", amount: "20.00" }],
  can_request_balance: true,
};

describe("StaffOrderPage", () => {
  afterEach(() => {
    unregisterOrderPanel("parcel");
    unregisterOrderPanel("visit");
  });

  it("shows a part's panel only on an order with its kind, with its lines", async () => {
    staffBackend({ ...staffOrder, lines: [...staffOrder.lines, bookingLine] });
    registerOrderPanel({
      key: "visit",
      title: "Booking",
      kinds: ["booking"],
      component: ({ lines }) => <p>Lines: {lines.map((line) => line.name).join(", ")}</p>,
    });
    registerOrderPanel({
      key: "parcel",
      title: "Parcel",
      kinds: ["parcel-kind"],
      component: () => <p>No parcel here</p>,
    });
    renderWithCommerce(<StaffOrderPage number="1001" />);
    const panel = await screen.findByRole("region", { name: "Booking" });
    expect(within(panel).getByText("Lines: Booking: Tuning")).toBeInTheDocument();
    expect(screen.queryByText("No parcel here")).not.toBeInTheDocument();
  });

  it("shows the deposit and the balance, and sends the balance link", async () => {
    const posted = staffBackend(partPaid);
    renderWithCommerce(<StaffOrderPage number="1001" />);
    expect(await screen.findByText("Still to pay")).toBeInTheDocument();
    expect(screen.getByText("€60.00")).toBeInTheDocument();
    expect(screen.getByText(/Deposit, .*test, succeeded/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send the balance link" }));
    await waitFor(() => expect(posted).toEqual([{ path: "balance-link", body: {} }]));
  });

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
      "/people/p-1",
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
              id: "p-1",
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
          id: "p-1",
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

describe("OrderPage panels and the balance", () => {
  afterEach(() => unregisterBuyerOrderPanel("visit"));

  it("asks the buyer for the balance of a part-paid order, with a part's panel", async () => {
    server.use(http.get(`${API_BASE}/orders/lookup/`, () => HttpResponse.json(partPaid)));
    registerBuyerOrderPanel({
      key: "visit",
      title: "Your booking",
      kinds: ["booking"],
      component: ({ lines }) => <p>{lines.length} booking to come</p>,
    });
    renderWithCommerce(<OrderPage number="1001" orderKey="k1" />);
    expect(await screen.findByText(/Your deposit is paid/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Pay the balance \(\s*€60\.00\s*\)$/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 booking to come")).toBeInTheDocument();
    expect(screen.getByText("Still to pay")).toBeInTheDocument();
  });

  it("asks for the deposit while nothing is paid", async () => {
    server.use(
      http.get(`${API_BASE}/orders/lookup/`, () =>
        HttpResponse.json({
          ...partPaid,
          status: "pending",
          amount_paid: "0.00",
          balance: "80.00",
          due_now: "20.00",
        }),
      ),
    );
    renderWithCommerce(<OrderPage number="1001" orderKey="k1" />);
    expect(
      await screen.findByRole("button", { name: /^Pay the deposit \(\s*€20\.00\s*\)$/ }),
    ).toBeInTheDocument();
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
      http.post(`${API_BASE}/orders/manual/quote/`, async ({ request }) => {
        const body = (await request.json()) as { coupon: string; shipping_method: string };
        const pickup = body.shipping_method === "m2";
        const known = body.coupon === "TENOFF";
        return HttpResponse.json({
          currency: "EUR",
          subtotal: "32.00",
          discount: known ? "3.20" : "0.00",
          shipping: pickup ? "0.00" : "5.00",
          tax: "0.00",
          total: known ? (pickup ? "28.80" : "33.80") : pickup ? "32.00" : "37.00",
          prices_include_tax: false,
          needs_shipping: true,
          coupon: known ? "TENOFF" : null,
          coupon_problem: body.coupon && !known ? "No coupon has that code." : "",
          methods: [
            { id: "m1", name: "Standard", kind: "flat", cost: "5.00" },
            { id: "m2", name: "Pickup", kind: "pickup", cost: "0.00" },
          ],
          method: pickup ? "m2" : "m1",
          shipping_problem: "",
          tax_lines: [],
        });
      }),
      http.post(`${API_BASE}/orders/manual/`, async ({ request }) => {
        placed = await request.json();
        return HttpResponse.json(
          { id: "o9", number: 1009, link: "/orders/1009?key=k" },
          { status: 201 },
        );
      }),
    );
    const { navigated } = renderWithCommerce(<NewOrderPage />);
    expect(screen.queryByLabelText("Kind")).not.toBeInTheDocument(); // one kind sold
    await userEvent.click(await screen.findByRole("button", { name: "Add Brass Lamp" }));
    await userEvent.click(screen.getByRole("button", { name: "Add Brass Lamp" }));
    await userEvent.type(screen.getByLabelText("Email"), "noor@example.com");
    await userEvent.type(screen.getByLabelText(/Full name/), "Noor Haddad");
    await userEvent.type(screen.getByLabelText(/^Address\s*\*?$/), "1 Quay");
    await userEvent.type(screen.getByLabelText(/City/), "Porto");
    await userEvent.type(screen.getByLabelText(/Postcode/), "4000");
    // The quote shows the shipping and the total before the order is placed.
    expect(await screen.findByText("Shipping (Standard)")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Coupon/), "NOPE");
    expect(await screen.findByText("No coupon has that code.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/Coupon/));
    await userEvent.type(screen.getByLabelText(/Coupon/), "TENOFF");
    expect(await screen.findByText("Discount (TENOFF)")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/Pickup/));
    expect(await screen.findByText("Shipping (Pickup)")).toBeInTheDocument();
    expect(screen.getAllByText(/28\.80/).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Place the order" }));
    await waitFor(() => expect(navigated).toContain("/orders/1009"));
    expect(placed).toMatchObject({
      email: "noor@example.com",
      name: "Noor Haddad",
      send_link: true,
      coupon: "TENOFF",
      shipping_method: "m2",
      lines: [{ kind: "product", item: "p1", quantity: 2 }],
      pay: "full",
    });
  }, 20000);

  it("finds items of every kind, filters by kind and asks for a deposit", async () => {
    const asked: URL[] = [];
    let placed: unknown = null;
    server.use(
      http.get(`${API_BASE}/orders/kinds/`, () =>
        HttpResponse.json([
          { kind: "booking", label: "Booking", searchable: true },
          { kind: "product", label: "Product", searchable: true },
        ]),
      ),
      http.get(`${API_BASE}/orders/items/`, ({ request }) => {
        asked.push(new URL(request.url));
        return HttpResponse.json([
          {
            kind: "booking",
            kind_label: "Booking",
            item: "v1",
            options: {},
            name: "Booking: Tuning",
            sku: "",
            price: "80.00",
            available: 1,
          },
        ]);
      }),
      http.post(`${API_BASE}/orders/manual/quote/`, () =>
        HttpResponse.json({
          currency: "EUR",
          subtotal: "80.00",
          discount: "0.00",
          shipping: "0.00",
          tax: "0.00",
          total: "80.00",
          prices_include_tax: false,
          needs_shipping: false,
          coupon: null,
          coupon_problem: "",
          methods: [],
          method: null,
          shipping_problem: "",
          tax_lines: [],
          deposit: "20.00",
        }),
      ),
      http.post(`${API_BASE}/orders/manual/`, async ({ request }) => {
        placed = await request.json();
        return HttpResponse.json({ id: "o9", number: 1009, link: "/orders/1009" }, { status: 201 });
      }),
    );
    renderWithCommerce(<NewOrderPage />);
    await userEvent.selectOptions(await screen.findByLabelText("Kind"), "booking");
    await waitFor(() => expect(asked.at(-1)?.searchParams.get("kind")).toBe("booking"));
    expect(screen.getByText(/^Booking, 1 available$/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add Booking: Tuning" }));
    await userEvent.click(await screen.findByLabelText(/Pay a deposit/));
    expect(screen.getByText(/later by the link we email the customer/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Email"), "noor@example.com");
    await userEvent.type(screen.getByLabelText(/Full name/), "Noor Haddad");
    await userEvent.type(screen.getByLabelText(/^Address\s*\*?$/), "1 Quay");
    await userEvent.type(screen.getByLabelText(/City/), "Porto");
    await userEvent.type(screen.getByLabelText(/Postcode/), "4000");
    await userEvent.click(screen.getByRole("button", { name: "Place the order" }));
    await waitFor(() => expect(placed).toMatchObject({ pay: "deposit" }));
  }, 20000);
});
