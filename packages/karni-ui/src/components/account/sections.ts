/**
 * The sections of the signed-in person's account page.
 *
 * Every installed part adds what it keeps for a person (orders, bookings,
 * courses) as a section, once at startup:
 *
 *   registerAccountSection({ key: "orders", title: "Your orders", order: 20, component: MyOrders });
 *
 * `AccountPage` shows the sections in `order` (lowest first, then by key),
 * after the person's own details. Registering a key again replaces it.
 */
import type { ComponentType } from "react";

export interface AccountSection {
  /** A stable name ("orders"). Registering the same key again replaces the section. */
  key: string;
  /** The section's heading. */
  title: string;
  /** Where it goes: lowest first (the details are 0). Default 50. */
  order?: number;
  /** Show it only to people holding one of these roles (default: everyone signed in). */
  roles?: readonly string[];
  /** What the section shows. It renders inside the page, under its heading. */
  component: ComponentType;
}

const SECTIONS = new Map<string, AccountSection>();

/** Add (or replace) a section of the account page. */
export function registerAccountSection(section: AccountSection): void {
  SECTIONS.set(section.key, section);
}

/** Take a section out (a project that shows something else there). */
export function unregisterAccountSection(key: string): void {
  SECTIONS.delete(key);
}

/** The registered sections, in their order. */
export function accountSections(): AccountSection[] {
  return [...SECTIONS.values()].sort(
    (a, b) => (a.order ?? 50) - (b.order ?? 50) || a.key.localeCompare(b.key),
  );
}
