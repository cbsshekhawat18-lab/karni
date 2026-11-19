/**
 * A simulated karni_commerce backend for the test suite (the conventions of
 * packages/karni-ui/tests/msw/).
 *
 * One visitor cart holds `cartState.lines`. `POST /carts/current/lines/`
 * sets or adds a line of the known items (`lamp`, sold out when `available`
 * is 0, `seat`, and `visit`, a booking with a deposit of 20.00: a cart of
 * bookings only is offered the deposit), checkout answers `placedFixture` (and
 * records its body in `checkoutCalls`), and `/orders/lookup/` answers
 * `orderFixture` for number 1001 with the key `k1`. `GET /auth/me/` answers
 * 401: the reader is a visitor unless a test signs someone in.
 */
import { HttpResponse, http } from "msw";
import type { BusinessDetails, Cart, CartLine, Order, Placed, Quote } from "../../src/types";

export const API_BASE = "http://localhost/api";

interface Known {
  name: string;
  price: string;
  compare: string | null;
  available: number | null;
  url: string;
  deposit?: string;
}

export const ITEMS: Record<string, Known> = {
  lamp: { name: "Brass Lamp", price: "16.00", compare: "20.00", available: 3, url: "/shop/lamp" },
  seat: { name: "Seat at Pottery", price: "45.00", compare: null, available: null, url: "" },
  visit: {
    name: "Booking: Tuning",
    price: "80.00",
    compare: null,
    available: 1,
    url: "",
    deposit: "20.00",
  },
};

export const cartState: {
  lines: { kind: string; item: string; quantity: number }[];
  coupon: string | null;
} = {
  lines: [],
  coupon: null,
};

/** The one coupon the simulated backend knows: 10% off. */
export const COUPON = "SAVE10";

export const checkoutCalls: unknown[] = [];

/** What the cart reports about checkout (a test changes it, the reset puts it back). */
export const checkoutOptions = { guest_checkout: true, accept_terms: false, terms_url: "" };

export const businessFixture: BusinessDetails = {
  name: "Lindqvist Goods",
  legal_name: "",
  address: "",
  phone: "",
  email: "",
  time_zone: "UTC",
  language: "en",
  currency: "EUR",
  currency_display: "symbol",
};

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
  buyer_name: "Ines Moreau",
  currency: "EUR",
  subtotal: "32.00",
  discount_total: "3.20",
  shipping_total: "5.00",
  tax_total: "6.76",
  tax_lines: [{ name: "TVA", rate: "20.0000", amount: "6.76" }],
  total: "40.56",
  prices_include_tax: false,
  coupon_code: "SAVE10",
  shipping_method: "Standard",
  amount_paid: "32.00",
  amount_refunded: "0.00",
  deposit: "0.00",
  balance: "0.00",
  due_now: "0.00",
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
      options: { colour: "brass" },
      details: [{ label: "Finish", value: "Brass" }],
      quantity: 2,
      quantity_refunded: 0,
      unit_price: "16.00",
      line_total: "32.00",
      discount: "3.20",
      tax: "5.76",
      total: "34.56",
      needs_shipping: true,
      url: "/shop/lamp",
      image: null,
    },
  ],
  notes: [
    {
      id: "n1",
      kind: "customer",
      body: "Wrapped as a gift.",
      author_name: "Theo Lindqvist",
      created_at: "2026-11-10T11:00:00Z",
    },
  ],
  fulfilment: [
    {
      title: "Parcel",
      status: "shipped",
      label: "Shipped",
      detail: "Tracking TR123",
      at: null,
      link: "",
      link_label: "",
    },
  ],
  invoice: null,
};

export function resetMswData(): void {
  cartState.lines = [];
  cartState.coupon = null;
  checkoutCalls.length = 0;
  Object.assign(checkoutOptions, { guest_checkout: true, accept_terms: false, terms_url: "" });
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
    details: [],
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
  const subtotal = lines.reduce((sum, row) => sum + Number(row.line_total), 0);
  return {
    coupon: cartState.coupon,
    coupon_description: cartState.coupon ? "10% off" : "",
    coupon_problem: "",
    discount: (cartState.coupon ? subtotal * 0.1 : 0).toFixed(2),
    token: lines.length ? "t1" : null,
    lines,
    count: lines.reduce((sum, row) => sum + row.quantity, 0),
    subtotal: lines.reduce((sum, row) => sum + Number(row.line_total), 0).toFixed(2),
    currency: "EUR",
    needs_shipping: lines.some((row) => row.kind === "product"),
    ready: lines.length > 0 && lines.every((row) => !row.problem),
    checkout: { ...checkoutOptions },
  };
}

export const handlers = [
  http.get(`${API_BASE}/auth/me/`, () =>
    HttpResponse.json({ detail: "Not signed in." }, { status: 401 }),
  ),
  http.get(`${API_BASE}/auth/csrf/`, () => new HttpResponse(null, { status: 204 })),
  http.get(`${API_BASE}/preferences/public/`, () => HttpResponse.json(businessFixture)),
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
  http.post(`${API_BASE}/carts/current/coupon/`, async ({ request }) => {
    const body = (await request.json()) as { code: string };
    const code = body.code.trim().toUpperCase();
    if (code && code !== COUPON) {
      return HttpResponse.json({ code: ["No coupon has that code."] }, { status: 400 });
    }
    cartState.coupon = code || null;
    return HttpResponse.json(currentCart());
  }),
  http.post(`${API_BASE}/carts/current/quote/`, async ({ request }) => {
    const body = (await request.json()) as {
      address: { country: string };
      shipping_method: string;
    };
    const cart = currentCart();
    const country = body.address.country;
    const methods =
      country === "FR"
        ? [
            { id: "m1", name: "Standard", kind: "flat", cost: "5.00" },
            { id: "m2", name: "Pickup in Lyon", kind: "pickup", cost: "0.00" },
          ]
        : [];
    const method = methods.find((m) => m.id === body.shipping_method) ?? methods[0] ?? null;
    const goods = Number(cart.subtotal) - Number(cart.discount);
    const shipping = method ? Number(method.cost) : 0;
    const tax = country === "FR" ? (goods + shipping) * 0.2 : 0;
    const deposits = cartState.lines.map((row) =>
      ITEMS[row.item].deposit ? Number(ITEMS[row.item].deposit) * row.quantity : null,
    );
    const deposit =
      deposits.length > 0 && deposits.every((value) => value !== null)
        ? deposits.reduce<number>((sum, value) => sum + (value ?? 0), 0).toFixed(2)
        : null;
    const quote: Quote = {
      currency: "EUR",
      subtotal: cart.subtotal,
      discount: cart.discount,
      shipping: shipping.toFixed(2),
      tax: tax.toFixed(2),
      total: (goods + shipping + tax).toFixed(2),
      prices_include_tax: false,
      needs_shipping: cart.needs_shipping,
      coupon: cart.coupon,
      coupon_problem: "",
      methods,
      method: method?.id ?? null,
      shipping_problem:
        country && country !== "FR" ? `We do not send orders to ${country} yet.` : "",
      tax_lines: tax ? [{ name: "TVA", rate: "20.0000", amount: tax.toFixed(2) }] : [],
      deposit,
    };
    return HttpResponse.json(quote);
  }),
  http.post(`${API_BASE}/carts/current/checkout/`, async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    checkoutCalls.push(body);
    if (checkoutOptions.accept_terms && body.accept_terms !== true) {
      return HttpResponse.json({ accept_terms: ["Accept the terms of sale."] }, { status: 400 });
    }
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
  http.get(`${API_BASE}/orders/kinds/`, () =>
    HttpResponse.json([{ kind: "product", label: "Product", searchable: true }]),
  ),
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
