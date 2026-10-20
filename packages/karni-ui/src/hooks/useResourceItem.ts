/**
 * Single-item hook for one resource (contract "Hooks" + D11).
 *
 * `useResourceItem<Event>("events", id, { expand: ["venue"] })` fetches
 * `GET /<resource>/<id>/?expand=venue` and caches it under
 * `karniKeys.detail(resource, id, params)` — params participate in the key,
 * so an expanded detail view and an unexpanded edit form never clobber each
 * other's cache entry, while `karniKeys.resource(resource)` invalidation
 * still reaches both.
 *
 * Escape hatch: `options` forwards every TanStack Query option except
 * `queryKey`/`queryFn` (e.g. `enabled` for "fetch only when an id exists").
 */
import { useQuery, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";
import { buildItemQuery, detailPath } from "./params";
import type { ResourceItemParams } from "./types";

/** Fetches one row of a resource (`GET /<resource>/<id>/`), optionally expanded. */
export function useResourceItem<T = Record<string, unknown>>(
  resource: string,
  id: string | number,
  params?: ResourceItemParams,
  options?: Omit<UseQueryOptions<T>, "queryKey" | "queryFn">,
): UseQueryResult<T> {
  const client = useKarniClient();
  return useQuery<T>({
    ...options,
    queryKey: karniKeys.detail(resource, id, params),
    queryFn: ({ signal }) =>
      client.request<T>(detailPath(resource, id), { query: buildItemQuery(params), signal }),
  });
}
