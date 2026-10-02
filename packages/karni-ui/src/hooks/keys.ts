/**
 * Query-key factory for every cache entry @karni/ui creates (contract D4).
 *
 * Key shapes:
 * - `["karni", "$schema"]` — the parsed OpenAPI schema (staleTime Infinity).
 * - `["karni", resource]` — the invalidation root for one resource.
 * - `["karni", resource, "list", normalizedParams]` — one list page.
 * - `["karni", resource, "detail", String(id)]` — one item; when the item was
 *   fetched with params (e.g. `expand`), the normalized params are appended as
 *   a fifth element so differently-shaped payloads never share a cache entry.
 *   Prefix invalidation via `karniKeys.resource(...)` still reaches them.
 *
 * Use this factory for any manual cache work (`setQueryData`,
 * `invalidateQueries`, prefetching) so your keys and the library's keys never
 * drift.
 *
 * NEVER invalidate the bare `["karni"]` root: it would also blow away the
 * schema entry (`["karni", "$schema"]`), refetching and re-parsing the whole
 * OpenAPI document. Invalidate `karniKeys.resource(resource)` instead — the
 * `"$"` prefix guarantees the schema key can never collide with a real
 * resource name (DRF router prefixes cannot contain `$`).
 */
import { buildItemQuery, buildListQuery, normalizeParams } from "./params";
import type { ResourceItemParams, ResourceListParams } from "./types";

export const karniKeys = {
  /** Cache key of the parsed OpenAPI schema document. */
  schema(): readonly unknown[] {
    return ["karni", "$schema"] as const;
  },

  /**
   * The invalidation root for one resource — every list and detail key of
   * `resource` lives under this prefix.
   */
  resource(resource: string): readonly unknown[] {
    return ["karni", resource] as const;
  },

  /**
   * Key for one list page. Params are normalized (D4): undefined/null
   * dropped, keys sorted recursively, values stringified as they hit the
   * query string — `{search: "x", page: 2}` and `{page: 2, search: "x"}`
   * share one entry.
   */
  list(resource: string, params?: ResourceListParams): readonly unknown[] {
    return ["karni", resource, "list", normalizeParams(buildListQuery(params))] as const;
  },

  /**
   * Key for one item. The id is always stringified, so `detail("events", 5)`
   * and `detail("events", "5")` share one entry. Params (expand) append a
   * normalized fifth element — see the module docs.
   */
  detail(resource: string, id: string | number, params?: ResourceItemParams): readonly unknown[] {
    const query = buildItemQuery(params);
    if (Object.keys(query).length > 0) {
      return ["karni", resource, "detail", String(id), normalizeParams(query)] as const;
    }
    return ["karni", resource, "detail", String(id)] as const;
  },
};
