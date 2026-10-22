/**
 * ResourceTable's table layout: one scrolling box (both axes), a header that
 * sticks on vertical scroll, a frozen first column (after the checkboxes)
 * that shows an edge once the table scrolls sideways, and rows a keyboard
 * can open (the first cell holds a button when `onRowClick` is set).
 *
 * With `keyboardNavigation="grid"` (the default) the table is a WAI-ARIA
 * grid: one Tab stop for the whole table, arrows between rows and cells
 * (./grid-navigation), Enter opens the row and Space selects it.
 * Internal to @karni/ui.
 */
import { flexRender, type Header, type Row, type Table } from "@tanstack/react-table";
import * as React from "react";
import { cn } from "../../../lib/cn";
import { AlertIcon, ChevronDownIcon, ChevronUpIcon, SpinnerIcon } from "../../primitives/icons";
import {
  BODY_CELL,
  DENSITY_CLASSES,
  FROZEN_AFTER_SELECT,
  FROZEN_AT_START,
  FROZEN_CELL,
  FROZEN_CONTENT,
  GRID_CELL,
  GRID_SCROLL_BOX,
  HEAD_CELL,
  LAST_ROW,
  SCROLL_BOX,
  SELECT_CELL,
  TABLE,
  THEAD,
} from "./layout";
import { useGridNavigation } from "./grid-navigation";
import type { ResourceTableDensity } from "./preferences";
import { ACTIONS_COLUMN, SELECT_COLUMN } from "./structural-columns";

/** How the keyboard moves through the table's rows (ResourceTable's `keyboardNavigation`). */
export type ResourceTableKeyboardNavigation = "grid" | "native";

export interface TableViewProps<T> {
  table: Table<T>;
  /** Names the table for assistive technology ("Events"). */
  caption: string;
  density: ResourceTableDensity;
  /** A sort or page change is loading: sort buttons ignore clicks. */
  busy: boolean;
  /** The column whose header was clicked last, for its progress spinner. */
  sortTarget: string | null;
  /** Work has run for 500ms: show progress. */
  slow: boolean;
  onSort: (header: Header<T, unknown>, event: React.MouseEvent) => void;
  onRowClick?: (row: T) => void;
  /** Why the last bulk action failed, by row id. */
  failures: Readonly<Record<string, string>>;
  /** 1-based position of the first row in the whole list, for aria-rowindex. */
  firstRowIndex: number;
  totalCount?: number;
  /** The rows are stale (a later request failed or is slow): dim them. */
  dimmed: boolean;
  scrollRef: React.RefObject<HTMLDivElement>;
  keyboardNavigation: ResourceTableKeyboardNavigation;
}

function isCheckbox(element: HTMLElement): boolean {
  return (
    element.getAttribute("role") === "checkbox" ||
    (element instanceof HTMLInputElement && element.type === "checkbox")
  );
}

/**
 * Enter and Space on a row of the grid. Controls keep their own keys: a
 * button activates, a link follows, and Ctrl or Cmd+Enter opens it in a new
 * tab. On a cell, Enter opens the row and Space selects it. A checkbox does
 * not use Enter, so there Enter opens the row too.
 */
function rowKeyDown<T>(
  event: React.KeyboardEvent<HTMLTableRowElement>,
  row: Row<T>,
  onRowClick: ((row: T) => void) | undefined,
): void {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (event.key !== "Enter" && event.key !== " ") return;
  const element = event.target;
  if (!(element instanceof HTMLElement)) return;
  const cell = element.closest("td");
  if (cell === null || cell.parentElement !== event.currentTarget) return;
  const onCell = element === cell;
  if (event.key === "Enter") {
    // A checkbox cancels Enter itself (it must not submit a form), so that is not checked here.
    if ((onCell || isCheckbox(element)) && onRowClick !== undefined) {
      event.preventDefault();
      onRowClick(row.original);
    }
    return;
  }
  // Space: links do not use it, buttons and checkboxes do.
  if (event.defaultPrevented || !(onCell || element instanceof HTMLAnchorElement)) return;
  if (row.getCanSelect()) {
    event.preventDefault();
    row.toggleSelected();
  }
}

function frozenClasses(
  columnId: string,
  firstDataColumn: string | undefined,
  selectable: boolean,
): string | false {
  if (columnId === SELECT_COLUMN) return SELECT_CELL;
  if (columnId === firstDataColumn) {
    return cn(FROZEN_CELL, selectable ? FROZEN_AFTER_SELECT : FROZEN_AT_START);
  }
  return false;
}

export function TableView<T>(props: TableViewProps<T>): React.ReactElement {
  const {
    table,
    caption,
    density,
    busy,
    sortTarget,
    slow,
    onSort,
    onRowClick,
    failures,
    firstRowIndex,
    totalCount,
    dimmed,
    scrollRef,
    keyboardNavigation,
  } = props;
  const sizes = DENSITY_CLASSES[density];
  const captionId = React.useId();
  const grid = keyboardNavigation === "grid";
  const tableRef = React.useRef<HTMLTableElement>(null);
  const navigation = useGridNavigation(tableRef, grid);
  const columns = table.getVisibleLeafColumns();
  const selectable = columns.some((column) => column.id === SELECT_COLUMN);
  const firstDataColumn = columns.find(
    (column) => column.id !== SELECT_COLUMN && column.id !== ACTIONS_COLUMN,
  )?.id;

  // Mark the box once it scrolls sideways, so the frozen column shows its edge.
  const onScroll = React.useCallback((event: React.UIEvent<HTMLDivElement>) => {
    const box = event.currentTarget;
    const scrolled = box.scrollLeft > 0;
    if ((box.dataset["scrolled"] === "true") !== scrolled) {
      box.dataset["scrolled"] = String(scrolled);
    }
  }, []);

  return (
    <div className="relative">
      {slow && (
        <div
          aria-hidden="true"
          data-testid="resource-table-progress"
          className="absolute inset-x-0 top-0 z-drawer h-1 animate-pulse rounded-t-md bg-primary"
        />
      )}
      <div
        ref={scrollRef}
        role="region"
        aria-labelledby={captionId}
        // A grid is the Tab stop and scrolls each cell it focuses into view. The
        // box still takes focus by script (where focus lands after a delete).
        tabIndex={grid ? -1 : 0}
        onScroll={onScroll}
        className={cn(SCROLL_BOX, grid && GRID_SCROLL_BOX, dimmed && "cursor-progress")}
      >
        <table
          ref={tableRef}
          role={grid ? "grid" : undefined}
          aria-labelledby={grid ? captionId : undefined}
          aria-multiselectable={grid && selectable ? true : undefined}
          className={TABLE}
          aria-busy={busy || undefined}
          aria-rowcount={totalCount !== undefined ? totalCount + 1 : undefined}
          onKeyDown={grid ? navigation.onKeyDown : undefined}
          onFocus={grid ? navigation.onFocus : undefined}
        >
          <caption id={captionId} className="sr-only">
            {caption}
          </caption>
          <thead className={THEAD}>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id} aria-rowindex={1}>
                {group.headers.map((header) => {
                  const canSort = header.column.getCanSort();
                  const direction = header.column.getIsSorted();
                  const spinning = slow && busy && sortTarget === header.column.id;
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={
                        direction === "asc"
                          ? "ascending"
                          : direction === "desc"
                            ? "descending"
                            : undefined
                      }
                      className={cn(
                        HEAD_CELL,
                        grid && GRID_CELL,
                        sizes.head,
                        frozenClasses(header.column.id, firstDataColumn, selectable),
                        header.column.id === ACTIONS_COLUMN && "text-right",
                      )}
                    >
                      {header.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          aria-disabled={busy || undefined}
                          aria-busy={spinning || undefined}
                          className="inline-flex items-center gap-1 rounded-sm hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-disabled:cursor-wait"
                          onClick={(event) => onSort(header, event)}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {spinning ? (
                            <SpinnerIcon className="h-3.5 w-3.5 animate-spin" />
                          ) : direction === "asc" ? (
                            <ChevronUpIcon className="h-3.5 w-3.5" />
                          ) : direction === "desc" ? (
                            <ChevronDownIcon className="h-3.5 w-3.5" />
                          ) : null}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className={LAST_ROW}>
            {table.getRowModel().rows.map((row, index) => {
              const failure = failures[row.id];
              return (
                <tr
                  key={row.id}
                  data-row-id={row.id}
                  aria-rowindex={firstRowIndex + index + 1}
                  aria-selected={grid && selectable ? row.getIsSelected() : undefined}
                  data-state={row.getIsSelected() ? "selected" : undefined}
                  data-failed={failure !== undefined ? "true" : undefined}
                  onClick={onRowClick !== undefined ? () => onRowClick(row.original) : undefined}
                  onKeyDown={grid ? (event) => rowKeyDown(event, row, onRowClick) : undefined}
                  className={cn("group/row", onRowClick !== undefined && "cursor-pointer")}
                >
                  {row.getVisibleCells().map((cell) => {
                    const first = cell.column.id === firstDataColumn;
                    const content = flexRender(cell.column.columnDef.cell, cell.getContext());
                    return (
                      <td
                        key={cell.id}
                        className={cn(
                          BODY_CELL,
                          grid && GRID_CELL,
                          sizes.cell,
                          frozenClasses(cell.column.id, firstDataColumn, selectable),
                        )}
                      >
                        {first ? (
                          <div className="flex flex-col">
                            {onRowClick !== undefined ? (
                              <button
                                type="button"
                                className={cn(
                                  FROZEN_CONTENT,
                                  "rounded-sm text-left font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                )}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  onRowClick(row.original);
                                }}
                              >
                                {content}
                              </button>
                            ) : (
                              <div className={FROZEN_CONTENT}>{content}</div>
                            )}
                            {failure !== undefined && (
                              <span className="flex items-center gap-1 text-xs text-destructive">
                                <AlertIcon className="h-3.5 w-3.5 shrink-0" />
                                {failure}
                              </span>
                            )}
                          </div>
                        ) : (
                          content
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
