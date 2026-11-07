/**
 * Experimental. The facet counts of a resource tagged to a tree
 * (`class Karni: taxonomies`): `GET /<resource>/facets/?taxonomy=&rollup=`
 * with the list's filters and search, so the counts are those of the rows
 * the list shows.
 *
 * Escape hatch: the hook forwards TanStack Query options except
 * `queryKey`/`queryFn`. The key lives under `karniKeys.resource(resource)`,
 * so a write to the resource refreshes it.
 */
import { useQuery, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";
import type { KarniQueryValue } from "../schema/client";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";
import { listPath } from "./params";

/** Experimental. One node of a facet: its id, label, parent id and how many rows it counts. */
export interface FacetNode {
  id: string | number;
  label: string;
  /** The node's parent, counted or not (null for a root). */
  parent: string | number | null;
  count: number;
}

/** Experimental. The `facets/` answer: the counted nodes in the tree's order, depth first. */
export interface FacetsResponse {
  taxonomy: string;
  rollup: boolean;
  results: FacetNode[];
}

/** Experimental. What `useResourceFacets` asks for. */
export interface ResourceFacetsParams {
  /** The taxonomy key ("region"). May be left out when the resource has one. */
  taxonomy?: string;
  /** True: a node also counts the rows tagged below it, each row once. Default false. */
  rollup?: boolean;
  /** The list's other query parameters (filters, `search`): the counts follow them. */
  query?: Readonly<Record<string, KarniQueryValue>>;
  /** Set false to wait. Default true. */
  enabled?: boolean;
}

/** The query string of a `facets/` request. */
export function facetsQuery(params?: ResourceFacetsParams): Record<string, KarniQueryValue> {
  const query: Record<string, KarniQueryValue> = {};
  for (const [key, value] of Object.entries(params?.query ?? {})) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value) && value.length === 0) continue;
    query[key] = value;
  }
  if (params?.taxonomy !== undefined && params.taxonomy !== "") query.taxonomy = params.taxonomy;
  if (params?.rollup === true) query.rollup = "true";
  return query;
}

/** Experimental. Rows per node of one taxonomy, under the list's filters (`GET /<resource>/facets/`). */
export function useResourceFacets(
  resource: string,
  params?: ResourceFacetsParams,
  options?: Omit<UseQueryOptions<FacetsResponse>, "queryKey" | "queryFn">,
): UseQueryResult<FacetsResponse> {
  const client = useKarniClient();
  const query = facetsQuery(params);
  return useQuery<FacetsResponse>({
    ...options,
    enabled: (options?.enabled ?? true) && params?.enabled !== false,
    queryKey: karniKeys.facets(resource, {
      taxonomy: params?.taxonomy,
      rollup: params?.rollup,
      query: params?.query,
    }),
    queryFn: ({ signal }) =>
      client.request<FacetsResponse>(`${listPath(resource)}facets/`, { query, signal }),
  });
}
