/**
 * What the karni-commerce API answers (karni_commerce/api.py). Money is a
 * decimal string with two places, in `currency` (an ISO 4217 code).
 */

/** A cart line, priced by its kind's adapter on the server. */
export interface CartLine {
  id: string;
  kind: string;
  item: string;
  name: string;
  /** The item's own page in the app (a path), or "". */
  url: string;
  image: string | null;
  options: Record<string, unknown>;
  quantity: number;
  unit_price: string;
  /** The regular price a sale is shown against, or null. */
  compare_at_price: string | null;
  line_total: string;
  /** How many a person can still buy, or null for no limit. */
  available: number | null;
  /** What stops the line from being bought ("Sold out."), or "". */
  problem: string;
}

/** GET /api/carts/current/: the shopper's cart. */
export interface Cart {
  /** A visitor's cart token (keep it, send it as X-Cart-Token), null for a signed-in person. */
  token: string | null;
  lines: CartLine[];
  count: number;
  subtotal: string;
  currency: string;
  needs_shipping: boolean;
  /** True when the cart has lines and none has a problem. */
  ready: boolean;
}

/** An address as checkout takes it and the order keeps it. */
export interface Address {
  name: string;
  company?: string;
  line1: string;
  line2?: string;
  city: string;
  region?: string;
  postcode: string;
  country: string;
  phone?: string;
}

/** POST /api/carts/current/checkout/: the order, its guest key and where to pay. */
export interface Placed {
  number: number;
  key: string;
  /** The payment page, or null when nothing is due (a free order is paid at once). */
  url: string | null;
}

export interface OrderLine {
  id: string;
  kind: string;
  item: string;
  name: string;
  sku: string;
  options: Record<string, unknown>;
  quantity: number;
  quantity_refunded: number;
  unit_price: string;
  line_total: string;
  needs_shipping: boolean;
  url: string;
  image: string | null;
}

/** What a selling app reports about the goods: a parcel shipped, a seat confirmed. */
export interface Fulfilment {
  title: string;
  status: string;
  label: string;
  detail: string;
  at: string | null;
}

/** The money states of an order. */
export type OrderStatus =
  "pending" | "paid" | "part_paid" | "failed" | "cancelled" | "refunded" | "part_refunded";

/** GET /api/orders/lookup/: an order as its buyer, or the guest with its key, reads it. */
export interface Order {
  id: string;
  number: number;
  status: OrderStatus;
  email: string;
  buyer_name: string;
  currency: string;
  subtotal: string;
  total: string;
  amount_paid: string;
  amount_refunded: string;
  billing: Address;
  shipping: Address | Record<string, never>;
  needs_shipping: boolean;
  note: string;
  created_at: string;
  paid_at: string | null;
  cancelled_at: string | null;
  hold_until: string | null;
  /** Waiting for its payment (or failed), so "Pay now" may start it again. */
  payable: boolean;
  lines: OrderLine[];
  fulfilment: Fulfilment[];
}

/** An order as GET /api/orders/ lists it. */
export interface OrderRow {
  id: string;
  number: number;
  status: OrderStatus;
  total: string;
  currency: string;
  created_at: string;
}
