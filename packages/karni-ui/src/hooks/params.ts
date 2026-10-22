/**
 * Query-param construction and key normalization for the resource hooks
 * (contract "Hooks" + D4).
 *
 * `buildListQuery` / `buildItemQuery` turn the typed param objects into the
 * flat record that is sent to the backend (page → `page`, pageSize →
 * `page_size`, expand → comma-joined per api contract B9, filters spread
 * flat). `normalizeParams` produces the canonical representation used inside
 * query keys (D4): undefined/null dropped, keys sorted recursively, values
 * stringified exactly as they hit the query string, so two call sites that
 * describe the same request always share one cache entry.
 *
 * Internal module: not re-exported from the barrel.
 */
import type { FilterValue, ResourceItemParams, ResourceListParams } from "./types";

/** Canonical param value shape stored inside query keys (D4). */
export type NormalizedParamValue = string | readonly string[] | NormalizedParams;
export type NormalizedParams = { readonly [key: string]: NormalizedParamValue };

function stringifyScalar(value: string | number | boolean): string {
  return typeof value === "string" ? value : String(value);
}

function isScalarArray(value: FilterValue): value is ReadonlyArray<string | number | boolean> {
  return Array.isArray(value);
}

/**
 * Flattens ResourceListParams into the query record sent to the server.
 * Explicit params win over a `filters` entry of the same name. Empty
 * `search`/`ordering` strings and empty `expand` arrays are omitted (they
 * describe "no constraint", and sending them would fragment the cache).
 */
export function buildListQuery(
  params?: ResourceListParams,
): Record<string, string | readonly string[]> {
  const query: Record<string, string | readonly string[]> = {};
  if (params === undefined) return query;

  if (params.filters !== undefined) {
    for (const [key, value] of Object.entries(params.filters)) {
      if (value === null || value === undefined) continue;
      if (isScalarArray(value)) {
        if (value.length > 0) query[key] = value.map(stringifyScalar);
      } else {
        query[key] = stringifyScalar(value);
      }
    }
  }

  if (params.page !== undefined) query.page = String(params.page);
  if (params.pageSize !== undefined) query.page_size = String(params.pageSize);
  if (params.ordering !== undefined && params.ordering !== "") query.ordering = params.ordering;
  if (params.search !== undefined && params.search !== "") query.search = params.search;
  if (params.expand !== undefined && params.expand.length > 0) {
    query.expand = params.expand.join(",");
  }
  return query;
}

/** Detail requests only carry `expand` (api contract B9). */
export function buildItemQuery(params?: ResourceItemParams): Record<string, string> {
  const query: Record<string, string> = {};
  if (params?.expand !== undefined && params.expand.length > 0) {
    query.expand = params.expand.join(",");
  }
  return query;
}

/**
 * D4 normalization: drop undefined/null, sort keys recursively, stringify
 * values as they hit the query string. The result is what `karniKeys` embeds
 * in list keys.
 */
export function normalizeParams(value: Record<string, unknown>): NormalizedParams {
  const out: Record<string, NormalizedParamValue> = {};
  for (const key of Object.keys(value).sort()) {
    const normalized = normalizeValue(value[key]);
    if (normalized !== undefined) out[key] = normalized;
  }
  return out;
}

function normalizeValue(value: unknown): NormalizedParamValue | undefined {
  if (value === null || value === undefined) return undefined;
  if (Array.isArray(value)) {
    return (value as readonly unknown[])
      .filter((item) => item !== null && item !== undefined)
      .map((item) =>
        typeof item === "object" && item !== null ? JSON.stringify(item) : String(item),
      );
  }
  if (typeof value === "object") {
    return normalizeParams(value as Record<string, unknown>);
  }
  return String(value);
}

/** `/events/` for resource "events" (the DRF router prefix, api B13). */
export function listPath(resource: string): string {
  const trimmed = resource.replace(/^\/+|\/+$/g, "");
  return `/${trimmed}/`;
}

/** `/events/5/`. Ids are encoded so UUIDs and slugs are safe. */
export function detailPath(resource: string, id: string | number): string {
  return `${listPath(resource)}${encodeURIComponent(String(id))}/`;
}
