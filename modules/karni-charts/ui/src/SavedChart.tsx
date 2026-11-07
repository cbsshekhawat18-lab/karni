/**
 * SavedChart: a chart defined in the admin, drawn by @karni/ui's DataChart
 * (karni-charts, experimental).
 *
 * `<SavedChart chart="launches-per-year" />` fetches the chart's definition and
 * data in one request (`GET /charts/<slug>/data/`) and draws them: the saved
 * name is the title, the description the chart's description, the kind a bar
 * or line chart, and a chart whose z axis stacks gets stacked bars. The data is
 * the source resource's aggregate under its own access, so two people may see
 * different numbers on the same chart.
 *
 * Escape hatches: every DataChart prop but the data (formatters, size, legend,
 * tooltip, `className`, its `slots`), `title` and `kind` to replace the saved
 * ones, an `Error` slot, `queryOptions` for the query, and `useSavedChart` for
 * a layout of your own.
 */
import {
  DataChart,
  ErrorState,
  registerComponentRole,
  type DataChartKind,
  type DataChartProps,
  type DataChartSlots,
  type FilterValue,
} from "@karni/ui";
import type { UseQueryOptions } from "@tanstack/react-query";
import type * as React from "react";
import { useSavedChart } from "./hooks";
import type { SavedChartData } from "./types";

registerComponentRole("saved-chart", "SavedChart");

/** Experimental. What the `Error` slot receives: the failure and a retry. */
export interface SavedChartErrorProps {
  error: unknown;
  onRetry: () => void;
  retrying: boolean;
}

/** Experimental. DataChart's slots plus the error state. */
export interface SavedChartSlots extends DataChartSlots {
  Error: React.ComponentType<SavedChartErrorProps>;
}

/** Experimental. The props of `SavedChart`. */
export interface SavedChartProps extends Omit<
  DataChartProps,
  "kind" | "title" | "data" | "series" | "aggregate" | "loading" | "slots"
> {
  /** The chart's slug, as the admin saved it. */
  chart: string;
  /** Filters the chart allows (its `allowed_filters`), as `useResourceList` takes them. */
  filters?: Record<string, FilterValue>;
  /** Replaces the saved name as the title. */
  title?: string;
  /** Replaces the saved kind. */
  kind?: DataChartKind;
  /** Replaces DataChart's pieces, or the error state. */
  slots?: Partial<SavedChartSlots>;
  /** Any TanStack Query option but `queryKey` and `queryFn`. */
  queryOptions?: Omit<UseQueryOptions<SavedChartData>, "queryKey" | "queryFn">;
}

function DefaultError({ error, onRetry, retrying }: SavedChartErrorProps): React.ReactElement {
  return <ErrorState error={error} onRetry={onRetry} retrying={retrying} />;
}

/** Experimental. Draws a chart saved in the admin, with the viewer's data. */
export function SavedChart({
  chart,
  filters,
  title,
  kind,
  slots,
  queryOptions,
  description,
  categoryHeader,
  ...chartProps
}: SavedChartProps): React.ReactElement {
  const { Error = DefaultError, ...chartSlots } = slots ?? {};
  const query = useSavedChart(chart, filters, queryOptions);
  if (query.isError) {
    return (
      <Error error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} />
    );
  }
  const saved = query.data?.chart;
  const resolvedTitle = title ?? saved?.name ?? chart;
  return (
    <DataChart
      {...chartProps}
      kind={kind ?? saved?.kind ?? "bar"}
      title={resolvedTitle}
      description={description ?? (saved?.description || undefined)}
      categoryHeader={categoryHeader ?? (saved?.x_label || undefined)}
      aggregate={query.data?.data}
      loading={query.isPending}
      slots={chartSlots}
    />
  );
}
