/**
 * <ComparisonTable>: entities side by side, one column each, one row per metric.
 *
 * Experimental. For "compare these three plans, regions or products": the
 * metric names head the rows (and stay in view while the table scrolls
 * sideways), the entity names head the columns (and stay in view while it
 * scrolls down). A metric that declares `better: "higher"` or `"lower"`
 * marks its best value: bold, and "best" for a screen reader.
 *
 * Escape hatches: per metric `value`, `format`, `render` and `better`.
 * `entityKey` and `entityLabel` read any shape of entity, `slots` replaces
 * the loading and empty states, and `className` merges on the root.
 */
import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { ErrorState, type ErrorSlotProps } from "../../states/ErrorState";
import { Skeleton } from "../primitives/skeleton";
import type { DataTableValue } from "../data-table/data-table";
import { displayLabel } from "../resource/displayLabel";
import { EmptyValue } from "../resource/empty-value";
import {
  FROZEN_AT_START,
  FROZEN_CELL,
  HEAD_CELL,
  LAST_ROW,
  TABLE,
  THEAD,
} from "../resource/table/layout";

registerComponentRole("comparison-table", "ComparisonTable");

export interface ComparisonMetric<T> {
  /** Unique within the table. The default value is `entity[key]`. */
  key: string;
  /** The row header. */
  label: string;
  /** One line under the label. */
  description?: string;
  /** The raw value (default `entity[key]`): what `better` compares. */
  value?: (entity: T) => DataTableValue;
  /** The cell's text (default: numbers grouped for the locale, Yes or No). */
  format?: (value: DataTableValue, entity: T) => string;
  /** The cell's content, when it is more than text. */
  render?: (entity: T) => React.ReactNode;
  /** Marks the best value of the row: the highest or the lowest number. */
  better?: "higher" | "lower";
}

/** What the `Empty` slot receives. */
export interface ComparisonTableEmptyProps {
  label: React.ReactNode;
}

export interface ComparisonTableSlots {
  Loading: React.ComponentType<Record<string, never>>;
  Empty: React.ComponentType<ComparisonTableEmptyProps>;
  Error: React.ComponentType<ErrorSlotProps>;
}

export interface ComparisonTableProps<T> {
  /** Names the table for assistive technology. */
  caption: string;
  /** The entities compared, one column each, in this order. */
  entities: readonly T[];
  metrics: ReadonlyArray<ComparisonMetric<T>>;
  /** A stable key per entity (default: its `id`, else its position). */
  entityKey?: (entity: T, index: number) => string | number;
  /** The column header (default: its name, title or label, as ResourceTable labels a row). */
  entityLabel?: (entity: T) => string;
  /** The header of the metric column (default "Metric"). */
  metricHeader?: string;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  retrying?: boolean;
  /** What the table says with no entity (default "Nothing to compare yet."). */
  emptyLabel?: React.ReactNode;
  slots?: Partial<ComparisonTableSlots>;
  className?: string;
}

const SCROLL_BOX =
  "group/scroll relative w-full max-h-[var(--karni-data-table-max-height)] overflow-auto rounded-md border border-border bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const CELL = "whitespace-nowrap border-b border-border bg-background px-3 py-2 align-middle";

function rawValue<T>(metric: ComparisonMetric<T>, entity: T): DataTableValue {
  if (metric.value !== undefined) return metric.value(entity);
  const value = (entity as Record<string, unknown>)[metric.key];
  if (
    value === null ||
    value === undefined ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    value instanceof Date
  ) {
    return value;
  }
  return String(value);
}

function defaultFormat(value: DataTableValue): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value instanceof Date) return value.toLocaleDateString();
  return value;
}

/** The positions of the best values of one metric (ties all count), or none. */
export function bestOf<T>(metric: ComparisonMetric<T>, entities: readonly T[]): Set<number> {
  const best = new Set<number>();
  if (metric.better === undefined) return best;
  let top: number | undefined;
  entities.forEach((entity, index) => {
    const value = rawValue(metric, entity);
    if (typeof value !== "number" || !Number.isFinite(value)) return;
    const wins = top === undefined || (metric.better === "higher" ? value > top : value < top);
    if (wins) {
      top = value;
      best.clear();
    }
    if (value === top) best.add(index);
  });
  // A metric where every entity ties marks nothing.
  return best.size === entities.length && entities.length > 1 ? new Set() : best;
}

function DefaultLoading(): React.ReactElement {
  return (
    <div className="space-y-2" aria-hidden="true">
      {[0, 1, 2, 3].map((row) => (
        <Skeleton key={row} className="h-8 w-full" />
      ))}
    </div>
  );
}

function DefaultEmpty({ label }: ComparisonTableEmptyProps): React.ReactElement {
  return <p className="py-8 text-center text-sm text-muted-foreground">{label}</p>;
}

/** ComparisonTable's default states, exported so a project can wrap one. */
export const defaultComparisonTableSlots: ComparisonTableSlots = {
  Loading: DefaultLoading,
  Empty: DefaultEmpty,
  Error: ErrorState,
};

/** Experimental. Entities side by side: metrics as rows, entities as columns, the best value marked. */
export function ComparisonTable<T>(props: ComparisonTableProps<T>): React.ReactElement {
  const {
    caption,
    entities,
    metrics,
    entityKey,
    entityLabel,
    metricHeader = "Metric",
    loading = false,
    error,
    onRetry,
    retrying = false,
    emptyLabel = "Nothing to compare yet.",
    slots,
    className,
  } = props;
  const Slots: ComparisonTableSlots = { ...defaultComparisonTableSlots, ...slots };
  const captionId = React.useId();
  const best = React.useMemo(
    () => metrics.map((metric) => bestOf(metric, entities)),
    [metrics, entities],
  );

  if (error !== undefined && error !== null) {
    return (
      <div className={className}>
        <Slots.Error
          error={error}
          context={{ action: "load", resource: caption.toLowerCase() }}
          onRetry={onRetry}
          retrying={retrying}
        />
      </div>
    );
  }
  if (loading) {
    return (
      <div className={className} aria-busy="true">
        <Slots.Loading />
        <span className="sr-only">Loading {caption}</span>
      </div>
    );
  }
  if (entities.length === 0) {
    return (
      <div className={className}>
        <Slots.Empty label={emptyLabel} />
      </div>
    );
  }

  const label = (entity: T): string =>
    entityLabel !== undefined
      ? entityLabel(entity)
      : displayLabel(entity as Record<string, unknown>);
  const key = (entity: T, index: number): string | number => {
    if (entityKey !== undefined) return entityKey(entity, index);
    const id = (entity as Record<string, unknown>)["id"];
    return typeof id === "string" || typeof id === "number" ? id : index;
  };

  return (
    <div
      role="region"
      aria-labelledby={captionId}
      tabIndex={0}
      className={cn(SCROLL_BOX, className)}
      onScroll={(event) => {
        const box = event.currentTarget;
        const scrolled = box.scrollLeft > 0;
        if ((box.dataset["scrolled"] === "true") !== scrolled)
          box.dataset["scrolled"] = String(scrolled);
      }}
    >
      <table className={TABLE}>
        <caption id={captionId} className="sr-only">
          {caption}
        </caption>
        <thead className={THEAD}>
          <tr>
            <th scope="col" className={cn(HEAD_CELL, "h-10 px-3", FROZEN_CELL, FROZEN_AT_START)}>
              {metricHeader}
            </th>
            {entities.map((entity, index) => (
              <th
                key={key(entity, index)}
                scope="col"
                className={cn(HEAD_CELL, "h-10 px-3 text-right")}
              >
                {label(entity)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className={LAST_ROW}>
          {metrics.map((metric, row) => (
            <tr key={metric.key}>
              <th
                scope="row"
                className={cn(CELL, "text-left font-medium", FROZEN_CELL, FROZEN_AT_START)}
              >
                <div className="max-w-72 truncate">{metric.label}</div>
                {metric.description !== undefined ? (
                  <div className="max-w-72 truncate text-xs font-normal text-muted-foreground">
                    {metric.description}
                  </div>
                ) : null}
              </th>
              {entities.map((entity, index) => {
                const value = rawValue(metric, entity);
                const isBest = best[row]?.has(index) ?? false;
                const content =
                  metric.render !== undefined ? (
                    metric.render(entity)
                  ) : value === null || value === undefined || value === "" ? (
                    <EmptyValue />
                  ) : (
                    (metric.format ?? defaultFormat)(value, entity)
                  );
                return (
                  <td
                    key={key(entity, index)}
                    data-best={isBest ? "true" : undefined}
                    className={cn(CELL, "text-right tabular-nums", isBest && "font-semibold")}
                  >
                    {content}
                    {isBest ? <span className="sr-only"> (best)</span> : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
