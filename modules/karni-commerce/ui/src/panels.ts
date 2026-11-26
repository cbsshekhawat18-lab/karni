/**
 * Panels a selling part adds to the order pages.
 *
 * Commerce holds the money. What happens to what was bought is the selling
 * part's: the shop's parcel (ship it with a tracking number), a booking's
 * check-in, a course's start link. A part registers a panel once at startup,
 * and an order page shows it for every order it applies to:
 *
 *     registerOrderPanel({ key: "parcel", title: "Parcel", component: Parcel,
 *                          kinds: ["product"], when: (order) => order.needs_shipping });
 *     registerBuyerOrderPanel({ key: "visit", title: "Your booking", component: Visit,
 *                               kinds: ["booking"] });
 *
 * `registerOrderPanel` is the staff's order page, `registerBuyerOrderPanel` the
 * buyer's. `kinds` names the kinds of line the panel is about: it shows only on
 * an order with such a line, and gets those lines (`lines`). Without `kinds` it
 * shows on every order and gets every line. `when` narrows it further. The panel
 * gets the order, its lines and `refresh()`, which reads the order again after
 * the panel changed something.
 *
 * Override / escape hatch: the same key replaces a panel, `unregister...` takes
 * one out, and `panelRegistry()` makes a registry for a page of your own.
 */
import type { ComponentType } from "react";
import type { Order, OrderLine, StaffOrder } from "./types";

export interface OrderPanelProps<O extends Order = StaffOrder> {
  order: O;
  /** The order's lines of the panel's kinds (every line when it names none). */
  lines: OrderLine[];
  /** Read the order again (after the panel changed it or what it sold). */
  refresh: () => void;
}

export interface OrderPanel<O extends Order = StaffOrder> {
  key: string;
  title: string;
  component: ComponentType<OrderPanelProps<O>>;
  /** Its place among the panels, smallest first. */
  order?: number;
  /** The kinds of line it is about (`["booking"]`): it shows only on an order with one. */
  kinds?: string[];
  /** Whether the panel applies to an order (default: every order with a line of its kinds). */
  when?: (order: O) => boolean;
}

/** A panel that applies to an order, with the lines it is about. */
export interface AppliedPanel<O extends Order = StaffOrder> {
  panel: OrderPanel<O>;
  lines: OrderLine[];
}

export interface PanelRegistry<O extends Order> {
  register: (panel: OrderPanel<O>) => void;
  unregister: (key: string) => void;
  /** The panels that apply to `order`, in order, each with its lines. */
  applied: (order: O) => AppliedPanel<O>[];
}

/** A registry of panels for one order page. */
export function panelRegistry<O extends Order>(): PanelRegistry<O> {
  const panels = new Map<string, OrderPanel<O>>();
  return {
    register: (panel) => {
      panels.set(panel.key, panel);
    },
    unregister: (key) => {
      panels.delete(key);
    },
    applied: (order) =>
      [...panels.values()]
        .map((panel) => ({
          panel,
          lines:
            panel.kinds === undefined
              ? order.lines
              : order.lines.filter((line) => panel.kinds?.includes(line.kind)),
        }))
        .filter(
          ({ panel, lines }) =>
            (panel.kinds === undefined || lines.length > 0) &&
            (panel.when === undefined || panel.when(order)),
        )
        .sort((a, b) => (a.panel.order ?? 0) - (b.panel.order ?? 0)),
  };
}

const STAFF = panelRegistry<StaffOrder>();
const BUYER = panelRegistry<Order>();

/** Add a panel to the staff's order page (the same key replaces it). */
export function registerOrderPanel(panel: OrderPanel): void {
  STAFF.register(panel);
}

/** Take a panel off the staff's order page. */
export function unregisterOrderPanel(key: string): void {
  STAFF.unregister(key);
}

/** The staff page's panels that apply to `order`, in order. */
export function orderPanels(order: StaffOrder): OrderPanel[] {
  return STAFF.applied(order).map(({ panel }) => panel);
}

/** The staff page's panels that apply to `order`, each with its lines. */
export function appliedOrderPanels(order: StaffOrder): AppliedPanel[] {
  return STAFF.applied(order);
}

/** Add a panel to the buyer's order page (the same key replaces it). */
export function registerBuyerOrderPanel(panel: OrderPanel<Order>): void {
  BUYER.register(panel);
}

/** Take a panel off the buyer's order page. */
export function unregisterBuyerOrderPanel(key: string): void {
  BUYER.unregister(key);
}

/** The buyer page's panels that apply to `order`, each with its lines. */
export function buyerOrderPanels(order: Order): AppliedPanel<Order>[] {
  return BUYER.applied(order);
}
