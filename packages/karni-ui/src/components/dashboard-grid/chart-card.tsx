/**
 * <ChartCard>: a DashboardCard around a DataChart.
 *
 * Experimental. The card's title names the chart too (its SVG title, label
 * and the caption of its hidden data table), so a screen reader hears the
 * same name a sighted user reads. While `loading`, a placeholder of the
 * chart's proportions stands in. With no plottable value the card says so
 * (`emptyLabel`), and a failure shows the error with "Try again".
 *
 * Escape hatches: every DataChart prop passes through (`kind`, `series`,
 * `valueFormatter`, `slots` for the tooltip and legend, ...), `cardSlots`
 * replaces the card's Loading, Empty or Error, and a page can put a
 * DataChart in a DashboardCard itself.
 */
import * as React from "react";
import { registerComponentRole } from "../../lib/roles";
import { aggregateSeries, DataChart, type DataChartProps } from "../chart/data-chart";
import {
  DashboardCard,
  type DashboardCardLoadingProps,
  type DashboardCardProps,
  type DashboardCardSlots,
} from "./dashboard-grid";

registerComponentRole("chart-card", "ChartCard");

export interface ChartCardProps
  extends
    Omit<
      DataChartProps,
      "title" | "description" | "loading" | "className" | "slots" | "emptyLabel"
    >,
    Pick<
      DashboardCardProps,
      | "description"
      | "actions"
      | "span"
      | "headingLevel"
      | "emptyLabel"
      | "error"
      | "onRetry"
      | "retrying"
      | "loading"
    > {
  /** The card's heading and the chart's name for assistive technology. */
  title: string;
  /** DataChart's slots: Tooltip, Legend, Empty, Loading. */
  slots?: DataChartProps["slots"];
  /** The card's slots: Loading, Empty, Error. */
  cardSlots?: Partial<DashboardCardSlots>;
  /** Merged onto the card. */
  className?: string;
  /** Merged onto the chart. */
  chartClassName?: string;
}

function hasValues(props: Pick<DataChartProps, "data" | "series" | "aggregate">): boolean {
  // DataChart reads `aggregate` first, so the empty test does too.
  const series =
    props.aggregate !== undefined
      ? aggregateSeries(props.aggregate)
      : (props.series ?? (props.data !== undefined ? [{ data: props.data }] : []));
  return series.some((entry) => entry.data.some((point) => Number.isFinite(point.value)));
}

function ChartLoading({ title }: DashboardCardLoadingProps): React.ReactElement {
  return <DataChart kind="bar" title={title} loading />;
}

/** Experimental. A dashboard card holding one DataChart, with loading, empty and error states. */
export function ChartCard(props: ChartCardProps): React.ReactElement {
  const {
    title,
    description,
    actions,
    span,
    headingLevel,
    emptyLabel = "No data to chart yet.",
    error,
    onRetry,
    retrying,
    loading = false,
    cardSlots,
    className,
    chartClassName,
    ...chart
  } = props;
  const descriptionText = typeof description === "string" ? description : undefined;
  return (
    <DashboardCard
      title={title}
      description={description}
      actions={actions}
      span={span}
      headingLevel={headingLevel}
      loading={loading}
      empty={!hasValues(chart)}
      emptyLabel={emptyLabel}
      error={error}
      onRetry={onRetry}
      retrying={retrying}
      slots={{ Loading: ChartLoading, ...cardSlots }}
      className={className}
    >
      <DataChart
        {...chart}
        title={title}
        description={descriptionText}
        className={chartClassName}
      />
    </DashboardCard>
  );
}
