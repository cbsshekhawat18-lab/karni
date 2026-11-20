/**
 * Experimental. What each installed part adds to the family pages, once at
 * startup (from its `frontend/src/<prefix>/index.ts`, which the build's
 * `parts.ts` calls):
 *
 *   registerPublicHome({ key: "shop", component: StoreHome });
 *   registerPersonTab({ key: "orders", title: "Orders", component: PersonOrders });
 *   registerTimelineKind("commerce.order.paid", { label: "Order paid", icon: "list" });
 *
 * - A **public home** is what `/` shows to a visitor or a customer: the
 *   shop's storefront, a booking page. With several, the lowest `order`
 *   wins. With none, `/` shows the person's tiles or the sign-in.
 * - A **person tab** is one tab of `/people/<id>` (the staff's page of one
 *   person): the orders of the shop, the bookings, the deals of a CRM.
 * - A **timeline kind** says how `<Timeline>` shows one kind of entry: its
 *   label in the filter, an icon name, and optionally a body of its own.
 *
 * Registering a key again replaces it. `unregister...` takes one out.
 */
import type { ComponentType, ReactNode } from "react";

interface Ordered {
  key: string;
  /** Its place, smallest first (default 50, then by key). */
  order?: number;
}

function sorted<T extends Ordered>(items: Iterable<T>): T[] {
  return [...items].sort((a, b) => (a.order ?? 50) - (b.order ?? 50) || a.key.localeCompare(b.key));
}

/** Experimental. What `/` shows to visitors and customers, registered by a part with a public side. */
export interface PublicHome extends Ordered {
  component: ComponentType;
  /**
   * The storefront's own page, where the back office's "Storefront" button
   * goes (staff see the back office at `/`). Default "/".
   */
  path?: string;
}

const HOMES = new Map<string, PublicHome>();

/** Experimental. Add (or replace) a public home. */
export function registerPublicHome(home: PublicHome): void {
  HOMES.set(home.key, home);
}

/** Experimental. Take a public home out. */
export function unregisterPublicHome(key: string): void {
  HOMES.delete(key);
}

/** Experimental. The public home `/` shows (the lowest `order`), or undefined when no part has one. */
export function publicHome(): PublicHome | undefined {
  return sorted(HOMES.values())[0];
}

/** Experimental. What a person tab receives. */
export interface PersonTabProps {
  /** The person's id. */
  personId: string;
  /** The person as `GET /people/<id>/` answered (names, email, facts). */
  person: Readonly<Record<string, unknown>>;
  /** Opens an app path (a row's page). */
  navigate: (to: string) => void;
}

/** Experimental. One tab of the person page, registered by the part that keeps that data. */
export interface PersonTab extends Ordered {
  title: string;
  component: ComponentType<PersonTabProps>;
  /** Show it only to people holding one of these roles (default: whoever opens the page). */
  roles?: readonly string[];
}

const TABS = new Map<string, PersonTab>();

/** Experimental. Add (or replace) a tab of the person page. */
export function registerPersonTab(tab: PersonTab): void {
  TABS.set(tab.key, tab);
}

/** Experimental. Take a tab of the person page out. */
export function unregisterPersonTab(key: string): void {
  TABS.delete(key);
}

/** Experimental. The registered person tabs, in order. */
export function personTabs(): PersonTab[] {
  return sorted(TABS.values());
}

/** Experimental. One timeline entry, as `GET /timeline/` answers it. */
export interface TimelineEntry {
  id: string;
  occurred_at: string;
  kind: string;
  title: string;
  body: string;
  source: string;
  actor: string | number | null;
  actor_name: string;
  person: string | null;
  event: string | null;
  links: Array<{ model: string; id: string; resource: string | null }>;
  data: Record<string, unknown>;
}

/** Experimental. How `<Timeline>` shows one kind of entry. */
export interface TimelineKind {
  /** The kind in words, for the filter ("Order paid"). Default: the kind's last words. */
  label?: string;
  /** A body of its own for an entry of this kind (default: the entry's body text). */
  render?: (entry: TimelineEntry) => ReactNode;
}

const KINDS = new Map<string, TimelineKind>();

/** Experimental. Say how `<Timeline>` shows entries of `kind` (`commerce.order.paid`). */
export function registerTimelineKind(kind: string, shown: TimelineKind): void {
  KINDS.set(kind, shown);
}

/** Experimental. Forget how a kind is shown. */
export function unregisterTimelineKind(kind: string): void {
  KINDS.delete(kind);
}

/** Experimental. How `kind` is shown (`undefined`: the default). */
export function timelineKind(kind: string): TimelineKind | undefined {
  return KINDS.get(kind);
}

/** Experimental. `commerce.order.paid` in words: "Order paid", unless the kind registered a label. */
export function timelineKindLabel(kind: string): string {
  const own = KINDS.get(kind)?.label;
  if (own !== undefined) return own;
  const words = kind.split(".").slice(1).join(" ").replace(/_/g, " ").trim();
  const text = words === "" ? kind : words;
  return text.charAt(0).toUpperCase() + text.slice(1);
}
