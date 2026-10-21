/**
 * Internal helpers for ResourceTable (contract "ResourceTable" + D5).
 * Pure functions, unit-tested directly; not part of the public barrel.
 */
import type { SortingState } from "@tanstack/react-table";

/**
 * Maps TanStack sorting state to the DRF `ordering` query parameter.
 * Column ids equal schema field names verbatim — that IS the ordering
 * contract (D5) — so `[{id: "title", desc: true}]` becomes `-title`.
 */
export function sortingToOrdering(sorting: SortingState): string | undefined {
  if (sorting.length === 0) return undefined;
  return sorting.map((entry) => (entry.desc ? `-${entry.id}` : entry.id)).join(",");
}

/** `"-title,starts_at"` → TanStack sorting state (the inverse of sortingToOrdering). */
export function orderingToSorting(ordering: string): SortingState {
  return ordering
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0 && part !== "-")
    .map((part) =>
      part.startsWith("-") ? { id: part.slice(1), desc: true } : { id: part, desc: false },
    );
}

/** The HTTP status of a KarniApiError-shaped error, if it has one. */
export function statusOf(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null || !("status" in error)) return undefined;
  const status = (error as { status: unknown }).status;
  return typeof status === "number" ? status : undefined;
}

/**
 * Duck-typed 404 check (works with KarniApiError or any error exposing a
 * numeric `status`), used for the D5 page-clamp: a list 404 with page > 1
 * decrements the page and refetches as loading, never as an error.
 */
export function isNotFoundError(error: unknown): boolean {
  return statusOf(error) === 404;
}

/**
 * The list query's retry rule: a request the server refused (4xx) fails the
 * same way again, so it is not retried, except a timeout (408) or a rate
 * limit (429). Network failures and 5xx get three tries.
 */
export function shouldRetryList(failureCount: number, error: unknown): boolean {
  const status = statusOf(error);
  if (status !== undefined && status >= 400 && status < 500 && status !== 408 && status !== 429) {
    return false;
  }
  return failureCount < 3;
}

/** "loose-slots" → "loose slots": the resource as a sentence names it. */
export function resourceWords(resource: string): string {
  return resource.replace(/[_-]+/g, " ").trim().toLowerCase();
}

/**
 * A conservative English singular ("events" → "event", "categories" →
 * "category", "addresses" → "address"); ResourceTable's `itemLabel` prop
 * replaces it where it guesses wrong.
 */
export function singular(plural: string): string {
  if (/[^aeiou]ies$/.test(plural)) return `${plural.slice(0, -3)}y`;
  if (/(?:ss|x|z|ch|sh)es$/.test(plural)) return plural.slice(0, -2);
  if (/[^s]s$/.test(plural)) return plural.slice(0, -1);
  return plural;
}

export function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function pageCountFor(count: number | undefined, pageSize: number): number {
  if (count === undefined || count <= 0 || pageSize <= 0) return 1;
  return Math.max(1, Math.ceil(count / pageSize));
}

/** Safe record view of an unknown row (rows are plain JSON objects). */
export function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** Best-effort human message from a KarniApiError-shaped or plain Error. */
export function errorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null) {
    const data = (error as { data?: unknown }).data;
    if (typeof data === "object" && data !== null) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === "string" && detail.length > 0) return detail;
    }
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.length > 0) return message;
  }
  return "Something went wrong while loading this table.";
}

/**
 * Display label for an enum member: ALL_CAPS and lower_snake constants are
 * prettified ("DRAFT" → "Draft", "in_progress" → "In progress"); mixed-case
 * values ("iOS") pass through untouched.
 */
export function enumLabel(
  value: string | number,
  labels?: Readonly<Record<string, string>>,
): string {
  const known = labels?.[String(value)];
  if (known !== undefined) return known;
  if (typeof value === "number") return String(value);
  const simple = /^[A-Za-z0-9_ ]+$/.test(value);
  if (simple && (value === value.toUpperCase() || value === value.toLowerCase())) {
    const spaced = value.toLowerCase().replace(/_+/g, " ").trim();
    if (spaced.length === 0) return value;
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
  }
  return value;
}
