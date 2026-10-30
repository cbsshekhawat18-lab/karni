/**
 * useSavedChart: one saved chart's definition and data (karni-charts, experimental).
 *
 * `useSavedChart("launches-per-year", { channel: "online" })` fetches
 * `GET /charts/launches-per-year/data/?channel=online`. The filters must be ones
 * the chart allows (the backend answers 400 `CHART002` otherwise). The data is
 * the source resource's aggregate, under its access, so the hook never filters.
 *
 * The cache entry lives under `karniKeys.resource("charts")`, so invalidating
 * the charts refreshes it. Pass `options` (any TanStack Query option but
 * `queryKey` and `queryFn`) to poll, or to keep the previous data while the
 * filters change.
 */
import { karniKeys, useKarniClient } from "@karni/ui";
import type { FilterValue } from "@karni/ui";
import { useQuery, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";
import type { SavedChartData } from "./types";

export const RESOURCE = "charts";

/** Experimental. The query string a chart's filters make: lists repeat, empty values drop. */
export function savedChartQuery(
  filters?: Record<string, FilterValue>,
): Record<string, string | readonly string[]> {
  const query: Record<string, string | readonly string[]> = {};
  for (const [name, value] of Object.entries(filters ?? {})) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      if (value.length > 0) query[name] = value.map(String);
    } else {
      query[name] = String(value);
    }
  }
  return query;
}

/** Experimental. The query key of one chart's data. */
export function savedChartKey(
  slug: string,
  filters?: Record<string, FilterValue>,
): readonly unknown[] {
  const query = savedChartQuery(filters);
  const sorted = Object.keys(query)
    .sort()
    .map((name) => [name, query[name]]);
  return [...karniKeys.resource(RESOURCE), "data", slug, sorted] as const;
}

/** Experimental. Fetches a saved chart's definition and data (`GET /charts/<slug>/data/`). */
export function useSavedChart(
  slug: string,
  filters?: Record<string, FilterValue>,
  options?: Omit<UseQueryOptions<SavedChartData>, "queryKey" | "queryFn">,
): UseQueryResult<SavedChartData> {
  const client = useKarniClient();
  return useQuery<SavedChartData>({
    ...options,
    queryKey: savedChartKey(slug, filters),
    queryFn: ({ signal }) =>
      client.request<SavedChartData>(`/${RESOURCE}/${encodeURIComponent(slug)}/data/`, {
        query: savedChartQuery(filters),
        signal,
      }),
  });
}
