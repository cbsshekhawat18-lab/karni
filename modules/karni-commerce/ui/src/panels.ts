/**
 * Experimental. Panels a selling app adds to the staff's order page.
 *
 * Commerce holds the money. What happens to the goods is the selling app's:
 * the shop's parcel (ship it with a tracking number), a booking's check-in.
 * An app registers a panel once at startup and the order page shows it for
 * every order it applies to:
 *
 *     registerOrderPanel({ key: "parcel", title: "Parcel", component: Parcel,
 *                          when: (order) => order.needs_shipping });
 *
 * The panel gets the order and `refresh()`, which reads the order again after
 * the panel changed something.
 */
import type { ComponentType } from "react";
import type { StaffOrder } from "./types";

export interface OrderPanelProps {
  order: StaffOrder;
  /** Read the order again (after the panel changed it or its goods). */
  refresh: () => void;
}

export interface OrderPanel {
  key: string;
  title: string;
  component: ComponentType<OrderPanelProps>;
  /** Its place among the panels, smallest first. */
  order?: number;
  /** Whether the panel applies to an order (default: every order). */
  when?: (order: StaffOrder) => boolean;
}

const PANELS = new Map<string, OrderPanel>();

/** Experimental. Add a panel to the staff's order page (the same key replaces it). */
export function registerOrderPanel(panel: OrderPanel): void {
  PANELS.set(panel.key, panel);
}

/** Experimental. Take a panel off the staff's order page. */
export function unregisterOrderPanel(key: string): void {
  PANELS.delete(key);
}

/** Experimental. The panels that apply to `order`, in order. */
export function orderPanels(order: StaffOrder): OrderPanel[] {
  return [...PANELS.values()]
    .filter((panel) => panel.when === undefined || panel.when(order))
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
}
