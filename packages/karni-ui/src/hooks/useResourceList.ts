/**
 * Paginated list hook for one resource (contract "Hooks" + D11).
 *
 * `useResourceList<Event>("events", { page: 2, search: "conf" })` fetches
 * `GET /<resource>/?page=2&search=conf` through the KarniClient (auth-aware
 * inside an <AuthProvider>) and caches it under
 * `karniKeys.list(resource, params)`. The response is the raw DRF page:
 * `{ count, next, previous, results }`.
 *
 * Escape hatch: `options` forwards every TanStack Query option except
 * `queryKey`/`queryFn` (e.g. `enabled`, `placeholderData`, `staleTime`,
 * `select`).
 */
import { useQuery, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";
import { buildListQuery, listPath } from "./params";
import type { Paginated, ResourceListParams } from "./types";

export function useResourceList<T = Record<string, unknown>>(
  resource: string,
  params?: ResourceListParams,
  options?: Omit<UseQueryOptions<Paginated<T>>, "queryKey" | "queryFn">,
): UseQueryResult<Paginated<T>> {
  const client = useKarniClient();
  return useQuery<Paginated<T>>({
    ...options,
    queryKey: karniKeys.list(resource, params),
    queryFn: ({ signal }) =>
      client.request<Paginated<T>>(listPath(resource), { query: buildListQuery(params), signal }),
  });
}
