/**
 * useResourceCounts: how many rows of each resource the signed-in user can
 * read, as chart points (`{ label, value }`) for a ChartCard.
 *
 * Experimental. Each count is one list request with `page_size=1` (the API's
 * `count`), under the list's own row scope, access rules and filters, the
 * way Dashboard counts. A resource the user may not list (403) is left out,
 * and any other failure is returned as `error` with a `refetch`. The
 * requests share the cache of `useResourceList`.
 *
 * It is the data seam of the dashboard pages `karni build` writes: until the
 * aggregation endpoint (large-apps item 8) counts grouped rows in one
 * request, a count per resource is what a page can ask for.
 */
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { listRetry } from "../components/resource/table/table-utils";
import { KarniApiError } from "../schema/client";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";
import { buildListQuery, listPath } from "./params";
import type { FilterValue, Paginated, ResourceListParams } from "./types";

/** One count: a resource, its label on the chart, and the list filters it counts with. */
export interface ResourceCountTarget {
  resource: string;
  /** The chart label (default: the resource, humanized: "deal-stages" → "Deal stages"). */
  label?: string;
  /** List filters, as `useResourceList`'s `filters`. */
  filters?: Readonly<Record<string, FilterValue>>;
}

/** One counted resource. */
export interface ResourceCountPoint {
  resource: string;
  label: string;
  value: number;
}

export interface ResourceCounts {
  /** One point per resource counted so far, in the order asked (left out: forbidden ones). */
  data: ResourceCountPoint[];
  /** True until every count has answered. */
  loading: boolean;
  /** The first failure that is not a 403, or null. */
  error: unknown;
  /** Asks again for the counts that failed. */
  refetch: () => void;
}

function humanize(resource: string): string {
  const spaced = resource.replace(/[-_]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function forbidden(error: unknown): boolean {
  return error instanceof KarniApiError && error.status === 403;
}

/** Experimental. The row count of each resource (`page_size=1` list requests), as chart points. */
export function useResourceCounts(
  targets: ReadonlyArray<string | ResourceCountTarget>,
): ResourceCounts {
  const client = useKarniClient();
  // A 4xx never succeeds on a retry; anything else follows the app's own rule.
  const appRetry = useQueryClient().getDefaultOptions().queries?.retry;
  const retry = listRetry(appRetry);
  const normalized = targets.map((target) =>
    typeof target === "string" ? { resource: target } : target,
  );
  const results = useQueries({
    queries: normalized.map((target) => {
      const params: ResourceListParams = { pageSize: 1, filters: target.filters };
      return {
        queryKey: karniKeys.list(target.resource, params),
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          client.request<Paginated<unknown>>(listPath(target.resource), {
            query: buildListQuery(params),
            signal,
          }),
        retry,
      };
    }),
  });
  const data: ResourceCountPoint[] = [];
  let error: unknown = null;
  results.forEach((result, index) => {
    const target = normalized[index];
    if (target === undefined) return;
    if (result.data !== undefined) {
      data.push({
        resource: target.resource,
        label: target.label ?? humanize(target.resource),
        value: result.data.count,
      });
    } else if (result.error !== null && !forbidden(result.error) && error === null) {
      error = result.error;
    }
  });
  return {
    data,
    loading: results.some((result) => result.isPending && result.error === null),
    error,
    refetch: () => {
      for (const result of results) if (result.error !== null) void result.refetch();
    },
  };
}
