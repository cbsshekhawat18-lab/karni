/**
 * What the karni-commerce API answers (karni_commerce/api.py). Money is a
 * decimal string with two places, in `currency` (an ISO 4217 code).
 */

/** One option of a line in words: `{label: "Size", value: "M"}`. */
export interface LineDetail {
  label: string;
  value: string;
}

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
  /** The options in words: a size, a colour. */
  details: LineDetail[];
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
  /** The coupon on the cart (its code), or null. */
  coupon: string | null;
  coupon_description: string;
  /** Why the coupon takes nothing off now, or "". */
  coupon_problem: string;
  /** What the coupon takes off the items. */
  discount: string;
  /** How checkout works for this shop. */
  checkout: CheckoutOptions;
}

/** The shop's checkout settings, as the cart reports them. */
export interface CheckoutOptions {
  /** Whether someone may order without signing in. */
  guest_checkout: boolean;
  /** Whether the buyer must accept the terms of sale. */
  accept_terms: boolean;
  /** Where the terms of sale are, or "". */
  terms_url: string;
}

/** A way to send the order, priced for this cart. */
export interface ShippingOption {
  id: string;
  name: string;
  kind: "flat" | "free" | "pickup" | string;
  cost: string;
}

/** One tax of an order: its name, its rate in percent and how much. */
export interface TaxLine {
  name: string;
  rate: string;
  amount: string;
}

/** POST /api/carts/current/quote/: what the cart comes to at an address. */
export interface Quote {
  currency: string;
  subtotal: string;
  discount: string;
  shipping: string;
  tax: string;
  total: string;
  prices_include_tax: boolean;
  needs_shipping: boolean;
  coupon: string | null;
  coupon_problem: string;
  methods: ShippingOption[];
  /** The id of the method the quote priced, or null. */
  method: string | null;
  /** Why the order cannot be sent to the address, or "". */
  shipping_problem: string;
  tax_lines: TaxLine[];
  /**
   * What may be paid now and the rest later, when every line allows a deposit (a
   * booking's), or null. Checkout sends `pay: "deposit"` to choose it.
   */
  deposit: string | null;
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
  details: LineDetail[];
  quantity: number;
  quantity_refunded: number;
  unit_price: string;
  line_total: string;
  /** What a coupon took off the line. */
  discount: string;
  tax: string;
  /** What the buyer pays for the line: its discount off, its tax in. */
  total: string;
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
  /** An absolute URL to a file the buyer may open (a download), or "". */
  link: string;
  /** What the link is called, or "". */
  link_label: string;
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
  discount_total: string;
  shipping_total: string;
  tax_total: string;
  tax_lines: TaxLine[];
  total: string;
  /** Whether the prices included their tax (the tax lines then say "included"). */
  prices_include_tax: boolean;
  coupon_code: string;
  /** The shipping method's name, or "". */
  shipping_method: string;
  amount_paid: string;
  amount_refunded: string;
  /** The deposit asked first ("0.00": the whole total at once). */
  deposit: string;
  /** What is still to pay: the total less what was paid. */
  balance: string;
  /** What the next payment asks: the deposit while it is due, else the balance. */
  due_now: string;
  billing: Address;
  shipping: Address | Record<string, never>;
  needs_shipping: boolean;
  note: string;
  created_at: string;
  paid_at: string | null;
  cancelled_at: string | null;
  hold_until: string | null;
  /**
   * Waiting for its payment (or failed), so "Pay now" may start it again, or part paid
   * by its deposit, with the balance to pay.
   */
  payable: boolean;
  lines: OrderLine[];
  /** The notes the reader may see: the notes to the customer (staff see every note). */
  notes: OrderNote[];
  fulfilment: Fulfilment[];
  /** The invoice's reference once the order is paid, or null. */
  invoice: string | null;
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

/** A note on an order: for the staff (`internal`), or to the customer. */
export interface OrderNote {
  id: string;
  kind: "internal" | "customer";
  body: string;
  author_name: string;
  created_at: string;
}

/** One payment of an order, as staff read it. */
export interface OrderPaymentRow {
  id: string;
  purpose: string;
  amount: string;
  status: string;
  provider: string;
  created_at: string;
}

/** One refund of an order: how much, of which lines, and where it stands. */
export interface OrderRefundRow {
  id: string;
  amount: string;
  lines: Record<string, number>;
  restock: boolean;
  reason: string;
  status: string;
  settled_at: string | null;
  created_at: string;
}

/** GET /api/orders/{id}/staff/: an order as staff read it. */
export interface StaffOrder extends Order {
  payments: OrderPaymentRow[];
  refunds: OrderRefundRow[];
  /** Who bought: their person (karni.people), account, and commerce's facts about them. */
  buyer: {
    person: string | null;
    user: string | null;
    name: string;
    email: string;
    orders: number;
    spent: string;
  };
  refundable: string;
  can_cancel: boolean;
  can_refund: boolean;
  /** Part paid by its deposit, with a balance left: staff may send the link to pay it. */
  can_request_balance: boolean;
}

/** A customer in the staff's customers list (GET /api/orders/customers/): a person
 * (karni.people) with commerce's facts. */
export interface CustomerRow {
  /** The person's id. */
  id: string;
  email: string;
  name: string;
  has_account: boolean;
  order_count: number;
  spent: string;
  currency: string;
  first_order: string;
  last_order: string;
}

/** One customer's page (GET /api/orders/customer/?email= or ?person=). */
export interface CustomerPageData {
  /** The person's id. */
  id: string;
  email: string;
  name: string;
  account: { id: string; name: string; email: string; joined: string | null } | null;
  order_count: number;
  spent: string;
  currency: string;
  first_order: string;
  last_order: string;
  addresses: Address[];
  orders: Array<{
    id: string;
    number: number;
    status: OrderStatus;
    total: string;
    created_at: string;
  }>;
}

/** Something staff may put on an order placed by hand (GET /api/orders/items/). */
export interface SellableItem {
  kind: string;
  /** The kind as staff read it ("Booking"). */
  kind_label?: string;
  item: string;
  /** The options of this choice (a size), sent with the line. */
  options: Record<string, unknown>;
  name: string;
  sku: string;
  price: string;
  available: number | null;
}

/** A kind the project sells (GET /api/orders/kinds/): a product, a booking, a course. */
export interface SellableKind {
  kind: string;
  label: string;
  /** Whether its items can be found by text. */
  searchable: boolean;
}

/** How the buyer pays: the whole total now, or the deposit now and the rest later. */
export type PayWay = "full" | "deposit";

/** One report the signed-in person may run (GET /orders/reports/). */
export interface ReportInfo {
  key: string;
  title: string;
  describe: string;
  dated: boolean;
}

export interface ReportColumn {
  key: string;
  label: string;
  format: "text" | "number" | "money" | "date";
}

/** GET /orders/reports/<key>/: a report's columns, rows and totals. */
export interface ReportResult extends ReportInfo {
  start: string | null;
  end: string | null;
  by: string | null;
  currency: string;
  columns: ReportColumn[];
  rows: Array<Record<string, string | number | null>>;
  totals: Record<string, string | number | null>;
}

/** One cart nobody touched for a while (GET /carts/abandoned/). */
export interface AbandonedCart {
  id: string;
  email: string;
  name: string;
  signed_in: boolean;
  items: number;
  lines: string[];
  value: string;
  currency: string;
  coupon: string;
  touched_at: string;
  created_at: string;
}

/** GET /preferences/public/: what the business says about itself. */
export interface BusinessDetails {
  name: string;
  legal_name: string;
  address: string;
  phone: string;
  email: string;
  time_zone: string;
  language: string;
  currency: string;
  currency_display: "symbol" | "narrowSymbol" | "code" | "name";
}
