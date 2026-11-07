/**
 * Experimental. Cross-model search (`GET /search/`) as a TanStack query.
 *
 * `useGlobalSearch({ q: "lamp" })` asks the endpoint every model with
 * `class Karni: search` answers through, and returns its groups: one per
 * resource, best hit first, each hit with the `resource` and `id` that link
 * it to its detail page. The server applies each model's own list access, so
 * the hook never filters anything itself.
 *
 * A query shorter than `minLength` (2 by default, the server's
 * `KARNI_GLOBAL_SEARCH_MIN_LENGTH`) sends no request and reads as an empty
 * result. `R` narrows the resource names: `karni types` generates
 * `SearchResource` and a `useGlobalSearch` typed with it.
 *
 * Escape hatch: `options` forwards every TanStack Query option except
 * `queryKey`/`queryFn` (`enabled`, `staleTime`, `placeholderData`, ...).
 */
import {
  keepPreviousData,
  useQuery,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";

/** Experimental. What `GET /search/` is asked. */
export interface GlobalSearchParams<R extends string = string> {
  /** The query (`q`). Leading and trailing spaces are dropped. */
  q: string;
  /** The resources to search (`models`, comma-joined). Default: every one search covers. */
  models?: readonly R[];
  /** Hits per resource (`limit`). Default: the server's `KARNI_GLOBAL_SEARCH_LIMIT`. */
  limit?: number;
}

/** Experimental. One hit: a row of one resource, with what links it to its page. */
export interface GlobalSearchHit<R extends string = string> {
  /** The resource (router prefix) the row belongs to. */
  resource: R;
  /** The row's primary key: a UUID string, or a number for integer keys. */
  id: string | number;
  title: string;
  subtitle: string | null;
  /** Higher is better, the model's weight included. */
  score: number;
}

/** Experimental. The hits of one resource, best first. */
export interface GlobalSearchGroup<R extends string = string> {
  resource: R;
  /** The model's plural name, for a heading. */
  label: string;
  hits: Array<GlobalSearchHit<R>>;
}

/** Experimental. The answer of `GET /search/`: groups ordered by their best hit. */
export interface GlobalSearchResult<R extends string = string> {
  query: string;
  groups: Array<GlobalSearchGroup<R>>;
}

/** Experimental. TanStack Query options, plus the shortest query that sends a request. */
export interface UseGlobalSearchOptions<R extends string = string> extends Omit<
  UseQueryOptions<GlobalSearchResult<R>>,
  "queryKey" | "queryFn"
> {
  /** The shortest query that is sent (default 2). */
  minLength?: number;
}

/** Experimental. The search path, relative to the client's base URL. */
export const GLOBAL_SEARCH_PATH = "/search/";

/** Experimental. The query string `GET /search/` is sent. */
export function globalSearchQuery<R extends string>(
  params: GlobalSearchParams<R>,
): Record<string, string> {
  const query: Record<string, string> = { q: params.q.trim() };
  if (params.models !== undefined && params.models.length > 0) {
    query.models = params.models.join(",");
  }
  if (params.limit !== undefined) query.limit = String(params.limit);
  return query;
}

/** Experimental. Searches every model that opts in (`GET /search/?q=`), grouped per resource. */
export function useGlobalSearch<R extends string = string>(
  params: GlobalSearchParams<R>,
  options?: UseGlobalSearchOptions<R>,
): UseQueryResult<GlobalSearchResult<R>> {
  const client = useKarniClient();
  const { minLength = 2, enabled, ...rest } = options ?? {};
  const query = globalSearchQuery(params);
  const long = (query.q ?? "").length >= minLength;
  return useQuery<GlobalSearchResult<R>>({
    placeholderData: keepPreviousData,
    ...rest,
    queryKey: karniKeys.search(query),
    queryFn: ({ signal }) =>
      client.request<GlobalSearchResult<R>>(GLOBAL_SEARCH_PATH, { query, signal }),
    enabled: long && (enabled ?? true),
  });
}
