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

/**
 * Duck-typed 404 check (works with KarniApiError or any error exposing a
 * numeric `status`), used for the D5 page-clamp: a list 404 with page > 1
 * decrements the page and refetches as loading, never as an error.
 */
export function isNotFoundError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    (error as { status: unknown }).status === 404
  );
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
export function enumLabel(value: string | number): string {
  if (typeof value === "number") return String(value);
  const simple = /^[A-Za-z0-9_ ]+$/.test(value);
  if (simple && (value === value.toUpperCase() || value === value.toLowerCase())) {
    const spaced = value.toLowerCase().replace(/_+/g, " ").trim();
    if (spaced.length === 0) return value;
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
  }
  return value;
}
