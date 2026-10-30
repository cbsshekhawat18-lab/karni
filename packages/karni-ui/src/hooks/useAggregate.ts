/**
 * useAggregate: grouped counts and sums of one resource (karni.aggregation).
 *
 * `useAggregate("products", { groupBy: "region", metric: "sum", value: "price" })`
 * fetches `GET /products/aggregate/?group_by=region&metric=sum&value=price`, the
 * action a `BaseViewSet` serves for a model that declares
 * `class Karni: aggregate`. The backend applies the list's access and filters
 * and refuses anything the declaration does not list (400 with a code), so the
 * hook only builds the query. The result feeds `<DataChart aggregate={data} />`.
 *
 * The cache entry lives under `karniKeys.resource(resource)`, so every mutation
 * of the resource refreshes its aggregates too.
 *
 * Escape hatch: `options` forwards every TanStack Query option except
 * `queryKey`/`queryFn`.
 */
import { useQuery, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";
import { buildListQuery, listPath, normalizeParams } from "./params";
import type { FilterValue } from "./types";

/** Experimental. What an aggregate computes per group. */
export type AggregateMetric = "count" | "sum" | "avg" | "min" | "max" | "distinct_count";

/** Experimental. The query of `useAggregate`: the action's parameters plus the list's filters. */
export interface AggregateParams {
  /** A declared field, relation path or expression. A date takes `:year`, `:quarter` or `:month`. */
  groupBy: string;
  /** Default `count`. */
  metric?: AggregateMetric;
  /** The declared field the metric reads (every metric but `count` needs one). */
  value?: string;
  /** Keep the N largest groups and put the rest in one "Other" group. */
  top?: number;
  /** A second dimension, stacked (bars on top of each other). */
  stack?: string;
  /** A second dimension, as separate series. */
  series?: string;
  /** The list's filters, as `useResourceList` takes them. */
  filters?: Record<string, FilterValue>;
  /** The list's full-text search. */
  search?: string;
}

/** Experimental. A JSON key: a value, a related row's key, or a date bucket (`2024-Q1`). */
export type AggregateKey = string | number | boolean | null;

/** Experimental. One group of the first dimension. */
export interface AggregateCategory {
  key: AggregateKey;
  label: string;
  /** True for the "Other" group `top` adds. */
  other: boolean;
}

/** Experimental. One series: a value per category, in the categories' order. */
export interface AggregateSeries {
  key: AggregateKey;
  label: string;
  values: ReadonlyArray<number | null>;
}

/** Experimental. The response of `GET <resource>/aggregate/`. */
export interface AggregateResult {
  group_by: string;
  metric: AggregateMetric;
  value: string | null;
  /** The second dimension, or null. */
  split: string | null;
  /** True when the second dimension came as `stack`. */
  stacked: boolean;
  top: number | null;
  categories: readonly AggregateCategory[];
  series: readonly AggregateSeries[];
}

/** Experimental. `params` as the query string the aggregate action reads. */
export function buildAggregateQuery(
  params: AggregateParams,
): Record<string, string | readonly string[]> {
  const query = buildListQuery({ filters: params.filters, search: params.search });
  query.group_by = params.groupBy;
  if (params.metric !== undefined) query.metric = params.metric;
  if (params.value !== undefined && params.value !== "") query.value = params.value;
  if (params.top !== undefined) query.top = String(params.top);
  if (params.stack !== undefined && params.stack !== "") query.stack = params.stack;
  if (params.series !== undefined && params.series !== "") query.series = params.series;
  return query;
}

/** Experimental. The query key of one aggregate (under the resource's invalidation root). */
export function aggregateKey(resource: string, params: AggregateParams): readonly unknown[] {
  return [
    ...karniKeys.resource(resource),
    "aggregate",
    normalizeParams(buildAggregateQuery(params)),
  ] as const;
}

/** Experimental. Fetches grouped counts and sums of a resource (`GET /<resource>/aggregate/`). */
export function useAggregate(
  resource: string,
  params: AggregateParams,
  options?: Omit<UseQueryOptions<AggregateResult>, "queryKey" | "queryFn">,
): UseQueryResult<AggregateResult> {
  const client = useKarniClient();
  return useQuery<AggregateResult>({
    ...options,
    queryKey: aggregateKey(resource, params),
    queryFn: ({ signal }) =>
      client.request<AggregateResult>(`${listPath(resource)}aggregate/`, {
        query: buildAggregateQuery(params),
        signal,
      }),
  });
}
