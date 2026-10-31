/**
 * <DataTable>: a table of rows the page computed, not a resource.
 *
 * Experimental. ResourceTable lists a resource through the API (paging,
 * filters, permissions). DataTable shows rows a page already has: a summary,
 * a breakdown, a report's result. It sorts on a click of a header (ascending,
 * descending, then as given), keeps its header and its first column in view
 * while the box scrolls, exports CSV and XLSX (every row, in the order shown,
 * with each column's raw value), and renders only the rows in view once
 * there are more than `virtualizeAfter` (default 100), so 10,000 rows scroll
 * smoothly. The table keeps `aria-rowcount` and `aria-rowindex`, so a screen
 * reader knows the whole size while only a window of rows is in the page.
 *
 * Escape hatches: per column `value` (what sorts and exports), `render`
 * (what the cell shows), `format`, `compare`, `align` and `exportValue`.
 * `sort` and `onSortChange` control sorting, `exportFormats={false}` drops
 * the export buttons and `toolbar` adds controls, and `virtualize={false}`
 * renders every row. The `--karni-data-table-max-height` and
 * `--karni-data-table-row-height` tokens size it, `slots` replaces the
 * loading and empty states, and `className` merges on the root.
 */
import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { ErrorState, type ErrorSlotProps } from "../../states/ErrorState";
import { Button } from "../primitives/button";
import { ChevronDownIcon, ChevronUpIcon } from "../primitives/icons";
import { Skeleton } from "../primitives/skeleton";
import { EmptyValue } from "../resource/empty-value";
import {
  FROZEN_AT_START,
  FROZEN_CELL,
  HEAD_CELL,
  LAST_ROW,
  TABLE,
  THEAD,
} from "../resource/table/layout";
import { downloadTable, exportCell, type DataTableExportFormat } from "./export";

registerComponentRole("computed-table", "DataTable");

/** A value a column sorts and exports by. */
export type DataTableValue = string | number | boolean | Date | null | undefined;

export type DataTableSortDirection = "asc" | "desc";

export interface DataTableSort {
  /** The column's `key`. */
  key: string;
  direction: DataTableSortDirection;
}

export interface DataTableColumn<T> {
  /** Unique within the table. The default value is `row[key]`. */
  key: string;
  /** The column header. */
  header: string;
  /** The raw value: what sorts and what the exports write. Default `row[key]`. */
  value?: (row: T) => DataTableValue;
  /** The cell's text (default: numbers grouped for the locale, dates as local dates, Yes or No). */
  format?: (value: DataTableValue, row: T) => string;
  /** The cell's content, when it is more than text (a link, a badge). Sorting still uses `value`. */
  render?: (row: T) => React.ReactNode;
  /** `"end"` for numbers (the default when the first value is a number), else `"start"`. */
  align?: "start" | "end";
  /** Default true. */
  sortable?: boolean;
  /** A custom order for this column (ascending). */
  compare?: (a: T, b: T) => number;
  /** What the exports write for this column (default: `value`). */
  exportValue?: (row: T) => DataTableValue;
}

/** What the `Loading` slot receives. */
export interface DataTableLoadingProps {
  columns: number;
}

/** What the `Empty` slot receives. */
export interface DataTableEmptyProps {
  /** The `emptyLabel` prop. */
  label: React.ReactNode;
}

export interface DataTableSlots {
  Loading: React.ComponentType<DataTableLoadingProps>;
  Empty: React.ComponentType<DataTableEmptyProps>;
  Error: React.ComponentType<ErrorSlotProps>;
}

export interface DataTableProps<T> {
  /** Names the table for assistive technology, and the exported file and sheet. */
  caption: string;
  columns: ReadonlyArray<DataTableColumn<T>>;
  rows: readonly T[];
  /** A stable key per row (default: its index). */
  getRowKey?: (row: T, index: number) => string | number;
  /** The first column becomes a button that calls this, and a click on the row too. */
  onRowClick?: (row: T) => void;
  /** The sort at first (uncontrolled). */
  initialSort?: DataTableSort | null;
  /** The sort now (controlled, with `onSortChange`). `null`: rows as given. */
  sort?: DataTableSort | null;
  onSortChange?: (sort: DataTableSort | null) => void;
  /** Keep the first column in view while the table scrolls sideways (default true). */
  stickyFirstColumn?: boolean;
  /** Export buttons (default `["csv", "xlsx"]`). `false` hides them. */
  exportFormats?: readonly DataTableExportFormat[] | false;
  /** The exported file's name, without extension (default: from `caption`). */
  exportName?: string;
  /** Extra controls next to the export buttons. */
  toolbar?: React.ReactNode;
  /** Render only the rows in view past this many rows (default 100). `false`: every row. */
  virtualize?: boolean | number;
  /** True while the rows load: placeholder rows stand in. */
  loading?: boolean;
  /** A failure to load the rows: the `Error` slot replaces the table. */
  error?: unknown;
  onRetry?: () => void;
  retrying?: boolean;
  /** What the table says with no rows (default "No rows to show."). */
  emptyLabel?: React.ReactNode;
  slots?: Partial<DataTableSlots>;
  className?: string;
}

/** The scrolling box: both directions scroll inside it, so the header and first column can stick. */
const SCROLL_BOX =
  "group/scroll relative w-full max-h-[var(--karni-data-table-max-height)] overflow-auto rounded-md border border-border bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const ROW_CELL =
  "h-[var(--karni-data-table-row-height)] whitespace-nowrap border-b border-border bg-background px-3 align-middle group-hover/row:bg-muted";
const HEAD = cn(HEAD_CELL, "h-10 px-3");

/** Before the first row is measured (jsdom never measures): 2.5rem at 16px. */
const DEFAULT_ROW_HEIGHT = 40;
/** Before the box is measured: enough rows to fill a tall screen. */
const DEFAULT_VIEWPORT = 720;
const OVERSCAN = 10;

function rawValue<T>(column: DataTableColumn<T>, row: T): DataTableValue {
  if (column.value !== undefined) return column.value(row);
  const value = (row as Record<string, unknown>)[column.key];
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
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? "" : value.toLocaleDateString();
  }
  return value;
}

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** Ascending order of two values: empty values last, numbers and dates by size, text naturally. */
export function compareValues(a: DataTableValue, b: DataTableValue): number {
  const emptyA = a === null || a === undefined || a === "";
  const emptyB = b === null || b === undefined || b === "";
  if (emptyA || emptyB) return emptyA === emptyB ? 0 : emptyA ? 1 : -1;
  if (a instanceof Date && b instanceof Date) return a.getTime() - b.getTime();
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return Number(a) - Number(b);
  return collator.compare(String(a), String(b));
}

/** The rows in `sort`'s order (a stable sort: equal rows keep their order). */
export function sortRows<T>(
  rows: readonly T[],
  columns: ReadonlyArray<DataTableColumn<T>>,
  sort: DataTableSort | null,
): readonly T[] {
  if (sort === null) return rows;
  const column = columns.find((candidate) => candidate.key === sort.key);
  if (column === undefined) return rows;
  const sign = sort.direction === "asc" ? 1 : -1;
  const keyed = rows.map((row, index) => ({ row, index, value: rawValue(column, row) }));
  keyed.sort((a, b) => {
    let order: number;
    if (column.compare !== undefined) {
      order = column.compare(a.row, b.row) * sign;
    } else {
      const emptyA = a.value === null || a.value === undefined || a.value === "";
      const emptyB = b.value === null || b.value === undefined || b.value === "";
      // Empty values stay last in both directions.
      order =
        emptyA || emptyB ? compareValues(a.value, b.value) : compareValues(a.value, b.value) * sign;
    }
    return order !== 0 ? order : a.index - b.index;
  });
  return keyed.map((entry) => entry.row);
}

function nextSort(current: DataTableSort | null, key: string): DataTableSort | null {
  if (current === null || current.key !== key) return { key, direction: "asc" };
  if (current.direction === "asc") return { key, direction: "desc" };
  return null;
}

function DefaultLoading({ columns }: DataTableLoadingProps): React.ReactElement {
  return (
    <div className="space-y-2 p-3" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((row) => (
        <div key={row} className="flex gap-3">
          {Array.from({ length: Math.max(1, columns) }, (_, column) => (
            <Skeleton key={column} className="h-6 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

function DefaultEmpty({ label }: DataTableEmptyProps): React.ReactElement {
  return <p className="py-8 text-center text-sm text-muted-foreground">{label}</p>;
}

/** DataTable's default states, exported so a project can wrap one. */
export const defaultDataTableSlots: DataTableSlots = {
  Loading: DefaultLoading,
  Empty: DefaultEmpty,
  Error: ErrorState,
};

const EXPORT_LABEL: Record<DataTableExportFormat, string> = { csv: "CSV", xlsx: "XLSX" };

/**
 * Experimental. A sortable, exportable table of rows the page computed, with
 * a sticky header and first column, virtualized past `virtualizeAfter` rows.
 */
export function DataTable<T>(props: DataTableProps<T>): React.ReactElement {
  const {
    caption,
    columns,
    rows,
    getRowKey,
    onRowClick,
    initialSort = null,
    sort: controlledSort,
    onSortChange,
    stickyFirstColumn = true,
    exportFormats = ["csv", "xlsx"],
    exportName,
    toolbar,
    virtualize = 100,
    loading = false,
    error,
    onRetry,
    retrying = false,
    emptyLabel = "No rows to show.",
    slots,
    className,
  } = props;
  const Slots: DataTableSlots = { ...defaultDataTableSlots, ...slots };
  const captionId = React.useId();
  const boxRef = React.useRef<HTMLDivElement>(null);
  const [ownSort, setOwnSort] = React.useState<DataTableSort | null>(initialSort);
  const sort = controlledSort !== undefined ? controlledSort : ownSort;
  const sorted = React.useMemo(() => sortRows(rows, columns, sort), [rows, columns, sort]);

  const threshold = virtualize === false ? Infinity : virtualize === true ? 0 : virtualize;
  const virtual = sorted.length > threshold;
  const [rowHeight, setRowHeight] = React.useState(DEFAULT_ROW_HEIGHT);
  const [viewport, setViewport] = React.useState(0);
  const [first, setFirst] = React.useState(0);
  const [headWidths, setHeadWidths] = React.useState<readonly number[]>([]);
  const [exporting, setExporting] = React.useState<DataTableExportFormat | null>(null);
  const [exportError, setExportError] = React.useState<unknown>(null);

  const aligns = React.useMemo(
    () =>
      columns.map((column) => {
        if (column.align !== undefined) return column.align;
        const sample = rows.find((row) => {
          const value = rawValue(column, row);
          return value !== null && value !== undefined;
        });
        return sample !== undefined && typeof rawValue(column, sample) === "number"
          ? "end"
          : "start";
      }),
    [columns, rows],
  );

  // Measure the box and one row: the window of rows follows them.
  React.useLayoutEffect(() => {
    const box = boxRef.current;
    if (!virtual || box === null) return undefined;
    const measure = (): void => {
      setViewport(box.clientHeight);
      const row = box.querySelector("tbody tr[data-row]");
      const height = row?.getBoundingClientRect().height ?? 0;
      if (height > 0)
        setRowHeight((current) => (Math.abs(current - height) > 0.5 ? height : current));
      // Columns never narrow while rows scroll in and out of the window.
      const heads = Array.from(
        box.querySelectorAll("thead th"),
        (th) => th.getBoundingClientRect().width,
      );
      if (heads.some((width) => width > 0)) {
        setHeadWidths((current) =>
          heads.map((width, index) => Math.max(width, current[index] ?? 0)),
        );
      }
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, [virtual, sorted]);

  const onScroll = React.useCallback(
    (event: React.UIEvent<HTMLDivElement>) => {
      const box = event.currentTarget;
      const scrolled = box.scrollLeft > 0;
      if ((box.dataset["scrolled"] === "true") !== scrolled)
        box.dataset["scrolled"] = String(scrolled);
      if (!virtual) return;
      const next = Math.floor(box.scrollTop / rowHeight);
      setFirst((current) => (current === next ? current : next));
    },
    [virtual, rowHeight],
  );

  const span = Math.ceil((viewport > 0 ? viewport : DEFAULT_VIEWPORT) / rowHeight);
  const start = virtual ? Math.max(0, Math.min(first, sorted.length - 1) - OVERSCAN) : 0;
  const end = virtual ? Math.min(sorted.length, start + span + OVERSCAN * 2) : sorted.length;
  const shown = virtual ? sorted.slice(start, end) : sorted;
  const above = start * rowHeight;
  const below = (sorted.length - end) * rowHeight;

  const changeSort = (key: string): void => {
    const next = nextSort(sort, key);
    if (controlledSort === undefined) setOwnSort(next);
    onSortChange?.(next);
  };

  const runExport = (format: DataTableExportFormat): void => {
    setExporting(format);
    setExportError(null);
    const headers = columns.map((column) => column.header);
    const cells = sorted.map((row) =>
      columns.map((column) =>
        exportCell((column.exportValue ?? ((r: T) => rawValue(column, r)))(row)),
      ),
    );
    downloadTable(format, exportName ?? caption, headers, cells)
      .catch((failure: unknown) => setExportError(failure))
      .finally(() => setExporting(null));
  };

  const failed = error !== undefined && error !== null;
  const formats = exportFormats === false ? [] : exportFormats;
  const showToolbar = toolbar != null || (formats.length > 0 && !loading && !failed);

  return (
    <div className={cn("space-y-2", className)}>
      {showToolbar ? (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {toolbar}
          {!loading && !failed
            ? formats.map((format) => (
                <Button
                  key={format}
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={exporting !== null || sorted.length === 0}
                  aria-label={`Export ${caption} as ${EXPORT_LABEL[format]}`}
                  onClick={() => runExport(format)}
                >
                  {EXPORT_LABEL[format]}
                </Button>
              ))
            : null}
        </div>
      ) : null}
      {exportError !== null ? (
        <ErrorState
          variant="inline"
          error={exportError}
          context={{ action: "export", resource: caption.toLowerCase() }}
        />
      ) : null}
      {failed ? (
        <Slots.Error
          error={error}
          context={{ action: "load", resource: caption.toLowerCase() }}
          onRetry={onRetry}
          retrying={retrying}
        />
      ) : (
        <div
          ref={boxRef}
          role="region"
          aria-labelledby={captionId}
          aria-busy={loading || undefined}
          tabIndex={0}
          onScroll={onScroll}
          className={SCROLL_BOX}
        >
          <table
            className={TABLE}
            aria-rowcount={virtual ? sorted.length + 1 : undefined}
            data-virtual={virtual ? "true" : undefined}
          >
            <caption id={captionId} className="sr-only">
              {caption}
            </caption>
            <thead className={THEAD}>
              <tr aria-rowindex={virtual ? 1 : undefined}>
                {columns.map((column, index) => {
                  const sortable = column.sortable !== false;
                  const direction = sort?.key === column.key ? sort.direction : undefined;
                  const width = headWidths[index];
                  return (
                    <th
                      key={column.key}
                      scope="col"
                      aria-sort={
                        direction === "asc"
                          ? "ascending"
                          : direction === "desc"
                            ? "descending"
                            : undefined
                      }
                      style={virtual && width !== undefined ? { minWidth: width } : undefined}
                      className={cn(
                        HEAD,
                        aligns[index] === "end" && "text-right",
                        index === 0 && stickyFirstColumn && cn(FROZEN_CELL, FROZEN_AT_START),
                      )}
                    >
                      {sortable ? (
                        <button
                          type="button"
                          onClick={() => changeSort(column.key)}
                          className={cn(
                            "inline-flex items-center gap-1 rounded-sm hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                            aligns[index] === "end" && "flex-row-reverse",
                          )}
                        >
                          {column.header}
                          {direction === "asc" ? (
                            <ChevronUpIcon className="h-3.5 w-3.5" />
                          ) : direction === "desc" ? (
                            <ChevronDownIcon className="h-3.5 w-3.5" />
                          ) : null}
                        </button>
                      ) : (
                        column.header
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className={LAST_ROW}>
              {loading || sorted.length === 0 ? (
                <tr>
                  <td colSpan={Math.max(1, columns.length)} className="p-0">
                    {loading ? (
                      <>
                        <Slots.Loading columns={columns.length} />
                        <span className="sr-only">Loading {caption}</span>
                      </>
                    ) : (
                      <Slots.Empty label={emptyLabel} />
                    )}
                  </td>
                </tr>
              ) : (
                <>
                  {above > 0 ? <tr aria-hidden="true" style={{ height: above }} /> : null}
                  {shown.map((row, offset) => {
                    const index = start + offset;
                    return (
                      <tr
                        key={getRowKey ? getRowKey(row, index) : index}
                        data-row=""
                        aria-rowindex={virtual ? index + 2 : undefined}
                        onClick={onRowClick !== undefined ? () => onRowClick(row) : undefined}
                        className={cn("group/row", onRowClick !== undefined && "cursor-pointer")}
                      >
                        {columns.map((column, columnIndex) => {
                          const value = rawValue(column, row);
                          const content =
                            column.render !== undefined ? (
                              column.render(row)
                            ) : value === null || value === undefined || value === "" ? (
                              <EmptyValue />
                            ) : (
                              (column.format ?? defaultFormat)(value, row)
                            );
                          const isFirst = columnIndex === 0;
                          return (
                            <td
                              key={column.key}
                              className={cn(
                                ROW_CELL,
                                aligns[columnIndex] === "end" && "text-right tabular-nums",
                                isFirst && stickyFirstColumn && cn(FROZEN_CELL, FROZEN_AT_START),
                              )}
                            >
                              {isFirst && onRowClick !== undefined ? (
                                <button
                                  type="button"
                                  className="max-w-72 truncate rounded-sm text-left font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    onRowClick(row);
                                  }}
                                >
                                  {content}
                                </button>
                              ) : isFirst ? (
                                <div className="max-w-72 truncate">{content}</div>
                              ) : (
                                content
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                  {below > 0 ? <tr aria-hidden="true" style={{ height: below }} /> : null}
                </>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
