/**
 * A simulated karni_commerce backend for the test suite (the conventions of
 * packages/karni-ui/tests/msw/).
 *
 * One visitor cart holds `cartState.lines`. `POST /carts/current/lines/`
 * sets or adds a line of the two known items (`lamp`, sold out when
 * `available` is 0, and `seat`), checkout answers `placedFixture` (and
 * records its body in `checkoutCalls`), and `/orders/lookup/` answers
 * `orderFixture` for number 1001 with the key `k1`. `GET /auth/me/` answers
 * 401: the reader is a visitor unless a test signs someone in.
 */
import { HttpResponse, http } from "msw";
import type { Cart, CartLine, Order, Placed } from "../../src/types";

export const API_BASE = "http://localhost/api";

interface Known {
  name: string;
  price: string;
  compare: string | null;
  available: number | null;
  url: string;
}

export const ITEMS: Record<string, Known> = {
  lamp: { name: "Brass Lamp", price: "16.00", compare: "20.00", available: 3, url: "/shop/lamp" },
  seat: { name: "Seat at Pottery", price: "45.00", compare: null, available: null, url: "" },
};

export const cartState: { lines: { kind: string; item: string; quantity: number }[] } = {
  lines: [],
};

export const checkoutCalls: unknown[] = [];

export const placedFixture: Placed = {
  number: 1001,
  key: "k1",
  url: "https://pay.example.test/session/1",
};

export const orderFixture: Order = {
  id: "o1",
  number: 1001,
  status: "paid",
  email: "ines@example.com",
  name: "Ines Moreau",
  currency: "EUR",
  subtotal: "32.00",
  total: "32.00",
  amount_paid: "32.00",
  amount_refunded: "0.00",
  billing: {
    name: "Ines Moreau",
    line1: "4 Rue des Lilas",
    city: "Lyon",
    postcode: "69001",
    country: "FR",
  },
  shipping: {
    name: "Ines Moreau",
    line1: "4 Rue des Lilas",
    city: "Lyon",
    postcode: "69001",
    country: "FR",
  },
  needs_shipping: true,
  note: "",
  created_at: "2026-11-10T10:00:00Z",
  paid_at: "2026-11-10T10:05:00Z",
  cancelled_at: null,
  hold_until: null,
  payable: false,
  lines: [
    {
      id: "l1",
      kind: "product",
      item: "lamp",
      name: "Brass Lamp",
      sku: "BL-1",
      options: {},
      quantity: 2,
      quantity_refunded: 0,
      unit_price: "16.00",
      line_total: "32.00",
      needs_shipping: true,
      url: "/shop/lamp",
      image: null,
    },
  ],
  fulfilment: [
    { title: "Parcel", status: "shipped", label: "Shipped", detail: "Tracking TR123", at: null },
  ],
};

export function resetMswData(): void {
  cartState.lines = [];
  checkoutCalls.length = 0;
  ITEMS.lamp.available = 3;
}

function line(entry: { kind: string; item: string; quantity: number }): CartLine {
  const known = ITEMS[entry.item];
  const problem =
    known.available !== null && entry.quantity > known.available
      ? known.available > 0
        ? `Only ${known.available} left.`
        : "Sold out."
      : "";
  return {
    id: `${entry.kind}-${entry.item}`,
    kind: entry.kind,
    item: entry.item,
    name: known.name,
    url: known.url,
    image: null,
    options: {},
    quantity: entry.quantity,
    unit_price: known.price,
    compare_at_price: known.compare,
    line_total: (Number(known.price) * entry.quantity).toFixed(2),
    available: known.available,
    problem,
  };
}

export function currentCart(): Cart {
  const lines = cartState.lines.map(line);
  return {
    token: lines.length ? "t1" : null,
    lines,
    count: lines.reduce((sum, row) => sum + row.quantity, 0),
    subtotal: lines.reduce((sum, row) => sum + Number(row.line_total), 0).toFixed(2),
    currency: "EUR",
    needs_shipping: lines.some((row) => row.kind === "product"),
    ready: lines.length > 0 && lines.every((row) => !row.problem),
  };
}

export const handlers = [
  http.get(`${API_BASE}/auth/me/`, () =>
    HttpResponse.json({ detail: "Not signed in." }, { status: 401 }),
  ),
  http.get(`${API_BASE}/auth/csrf/`, () => new HttpResponse(null, { status: 204 })),
  http.get(`${API_BASE}/carts/current/`, () => HttpResponse.json(currentCart())),
  http.post(`${API_BASE}/carts/current/lines/`, async ({ request }) => {
    const body = (await request.json()) as {
      kind: string;
      item: string;
      quantity: number;
      add?: boolean;
    };
    const known = ITEMS[body.item];
    const found = cartState.lines.find((row) => row.item === body.item);
    const wanted = body.quantity + (body.add && found ? found.quantity : 0);
    if (known.available !== null && wanted > known.available) {
      return HttpResponse.json(
        { item: [known.available > 0 ? `Only ${known.available} left.` : "Sold out."] },
        { status: 400 },
      );
    }
    cartState.lines = cartState.lines.filter((row) => row.item !== body.item);
    if (wanted > 0) cartState.lines.push({ kind: body.kind, item: body.item, quantity: wanted });
    return HttpResponse.json(currentCart());
  }),
  http.post(`${API_BASE}/carts/current/checkout/`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    checkoutCalls.push(body);
    if (!body.email) {
      return HttpResponse.json(
        { email: ["An email address, for the confirmation."] },
        { status: 400 },
      );
    }
    return HttpResponse.json(placedFixture, { status: 201 });
  }),
  http.get(`${API_BASE}/orders/lookup/`, ({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get("number") === "1001" && url.searchParams.get("key") === "k1") {
      return HttpResponse.json(orderFixture);
    }
    return HttpResponse.json({ detail: "No such order." }, { status: 404 });
  }),
  http.post(`${API_BASE}/orders/pay/`, () => HttpResponse.json({ url: null })),
  http.get(`${API_BASE}/orders/`, () =>
    HttpResponse.json({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: "o1",
          number: 1001,
          status: "paid",
          total: "32.00",
          currency: "EUR",
          created_at: "2026-11-10T10:00:00Z",
        },
      ],
    }),
  ),
];
