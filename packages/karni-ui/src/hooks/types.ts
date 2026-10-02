/**
 * Public parameter/result types of the resource hooks.
 *
 * These names and shapes are PINNED by amendment D11 — karni-cli's generated
 * typed hooks compile against them (they are exported from the package root).
 * Additions must stay source-compatible; never rename or narrow.
 */
import type { QueryKey } from "@tanstack/react-query";

/** DRF PageNumberPagination page shape returned by every list endpoint. */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/**
 * A single filter value as accepted by the backend's FilterSet (api B5/B6).
 * Arrays become repeated query keys; `null`/`undefined` entries are dropped
 * (they mean "no constraint", not "filter by null").
 */
export type FilterValue =
  string | number | boolean | ReadonlyArray<string | number | boolean> | null | undefined;

/** Maps to page / page_size / ordering / search / expand + filter passthrough. */
export interface ResourceListParams {
  /** 1-based page number (`page`). */
  page?: number;
  /** Page size (`page_size`). */
  pageSize?: number;
  /** DRF ordering expression, e.g. `"-created_at"` (`ordering`). */
  ordering?: string;
  /** Full-text search term (`search`); empty string is treated as unset. */
  search?: string;
  /** Extra filter params, spread flat into the query string. Explicit params above win on a name clash. */
  filters?: Record<string, FilterValue>;
  /** Relation paths to expand, comma-joined into `expand` (api B9). */
  expand?: readonly string[];
}

export interface ResourceItemParams {
  /** Relation paths to expand, comma-joined into `expand` (api B9). */
  expand?: readonly string[];
}

export interface ResourceMutationsOptions {
  /**
   * Extra query keys invalidated after any successful mutation, on top of
   * ["karni", resource]. Never pass the bare ["karni"] root (D4) — it would
   * also invalidate the cached schema document.
   */
  invalidateKeys?: readonly QueryKey[];
}
