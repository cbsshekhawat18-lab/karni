/**
 * Experimental. Links to a record from wherever another record points at it.
 *
 * An app says where a resource's records live once at startup:
 *
 *     registerRecordLink("orders", (row) => `/orders/${String(row.number)}`);
 *     setRecordNavigate((to) => router.history.push(to));
 *
 * A table cell or a detail value of a relation to that resource is then a
 * link to the record (the expanded row is what `href` receives). Without a
 * registration the cell stays plain text. `setRecordNavigate` lets a click
 * use the app's router instead of loading the page again.
 *
 * Escape hatch: `unregisterRecordLink`, and ResourceTable's `columns` or
 * ResourceDetail's `fields` render a value any other way.
 */
import * as React from "react";
import { cn } from "../../lib/cn";

type Row = Readonly<Record<string, unknown>>;

/** Where a record of a resource lives in the app, or null for none. */
export type RecordHref = (row: Row) => string | null | undefined;

const LINKS = new Map<string, RecordHref>();
let navigateTo: ((to: string) => void) | null = null;

/** Experimental. Records of `resource` link to `href(row)` wherever a relation shows them. */
export function registerRecordLink(resource: string, href: RecordHref): void {
  LINKS.set(resource, href);
}

/** Experimental. Forget the link of `resource` (tests, an app that replaces it). */
export function unregisterRecordLink(resource: string): void {
  LINKS.delete(resource);
}

/** Experimental. How a record link opens: the app's router (`null`: the browser's own). */
export function setRecordNavigate(navigate: ((to: string) => void) | null): void {
  navigateTo = navigate;
}

/** Experimental. The address of `row` of `resource`, when the app registered one. */
export function recordHref(resource: string | undefined, row: unknown): string | null {
  if (resource === undefined || row === null || typeof row !== "object") return null;
  const href = LINKS.get(resource);
  if (href === undefined) return null;
  const found = href(row as Row);
  return typeof found === "string" && found !== "" ? found : null;
}

export interface RecordLinkProps {
  resource: string | undefined;
  row: unknown;
  children: React.ReactNode;
  className?: string;
}

/**
 * Experimental. `children` as a link to the record, when its resource has a
 * registered link. A click does not reach the row around it (a table row's
 * own click opens that row).
 */
export function RecordLink({ resource, row, children, className }: RecordLinkProps) {
  const href = recordHref(resource, row);
  if (href === null) return <>{children}</>;
  return (
    <a
      href={href}
      className={cn(
        "rounded-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
      onClick={(event) => {
        event.stopPropagation();
        if (navigateTo === null || event.metaKey || event.ctrlKey || event.shiftKey) return;
        event.preventDefault();
        navigateTo(href);
      }}
    >
      {children}
    </a>
  );
}
