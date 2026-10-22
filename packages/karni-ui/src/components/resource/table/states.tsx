/**
 * ResourceTable's state screens, each the default of one slot: the loading
 * skeleton, the two empty screens (nothing yet / nothing matches), the error
 * panels, the permission screen and the offline notice. A project replaces
 * any of them with `slots={{ NoRecords: OurEmpty }}`, and each receives the
 * props documented here.
 */
import * as React from "react";
import { cn } from "../../../lib/cn";
import { ErrorState, PermissionDenied, type ErrorSlotProps } from "../../../states/ErrorState";
import { EmptyState } from "../../empty-state/empty-state";
import { Button } from "../../primitives/button";
import { OfflineIcon } from "../../primitives/icons";
import { Skeleton } from "../../primitives/skeleton";
import {
  BODY_CELL,
  DENSITY_CLASSES,
  FROZEN_AFTER_SELECT,
  FROZEN_AT_START,
  FROZEN_CELL,
  HEAD_CELL,
  LAST_ROW,
  SCROLL_BOX,
  SELECT_CELL,
  TABLE,
  THEAD,
} from "./layout";
import type { ResourceTableDensity } from "./preferences";
import { FilterOffIcon, InboxIcon, PlusIcon } from "./table-icons";

// loading

/** What the Loading slot receives: enough to draw the real layout's outline. */
export interface ResourceTableLoadingProps {
  /** Columns of the real table, the checkbox and actions columns included (a guess until the schema loads). */
  columnCount: number;
  /** Rows of a full page: the page size. */
  rowCount: number;
  density: ResourceTableDensity;
  /** Draw the toolbar's outline too (until the schema says what the toolbar holds). */
  toolbar: boolean;
  /** "cards" below the container breakpoint, else "table". */
  layout: "table" | "cards";
  /** A checkbox column leads (the table has bulk actions). */
  selectable: boolean;
  /** An actions column ends each row (edit, delete, `rowActions`). */
  actions: boolean;
}

/** Bars of uneven width read as text. The pattern repeats so rows differ. */
const BAR_WIDTHS = ["w-3/4", "w-1/2", "w-2/3", "w-5/6", "w-1/3"] as const;

function barWidth(...offsets: number[]): string {
  const index = offsets.reduce((sum, offset) => sum + offset, 0);
  return BAR_WIDTHS[index % BAR_WIDTHS.length] ?? "w-1/2";
}

function TableOutline(props: ResourceTableLoadingProps): React.ReactElement {
  const { columnCount, rowCount, density, selectable } = props;
  const sizes = DENSITY_CLASSES[density];
  const columns = Array.from({ length: Math.max(1, columnCount) }, (_, index) => index);
  const frozen = (index: number): string | false => {
    if (selectable && index === 0) return SELECT_CELL;
    if (index === (selectable ? 1 : 0)) {
      return cn(FROZEN_CELL, selectable ? FROZEN_AFTER_SELECT : FROZEN_AT_START);
    }
    return false;
  };
  return (
    <div className={cn(SCROLL_BOX, "overflow-hidden")}>
      <table className={TABLE}>
        <thead className={THEAD}>
          <tr>
            {columns.map((index) => (
              <th key={index} scope="col" className={cn(HEAD_CELL, sizes.head, frozen(index))}>
                {selectable && index === 0 ? (
                  <Skeleton className="h-4 w-4 rounded-sm bg-background" />
                ) : (
                  <Skeleton className="h-3 w-16 bg-background" />
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className={LAST_ROW}>
          {Array.from({ length: rowCount }, (_, row) => (
            <tr key={row} className="group/row">
              {columns.map((index) => (
                <td key={index} className={cn(BODY_CELL, sizes.cell, frozen(index))}>
                  {selectable && index === 0 ? (
                    <Skeleton className="h-4 w-4 rounded-sm" />
                  ) : (
                    <Skeleton className={cn("h-4 min-w-12", barWidth(row, index))} />
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CardsOutline(props: ResourceTableLoadingProps): React.ReactElement {
  const { density, selectable, actions } = props;
  const sizes = DENSITY_CLASSES[density];
  // The card's fields: the data columns after the title, as RowCard shows them (8 at most).
  const structural = (selectable ? 1 : 0) + (actions ? 1 : 0);
  const pairs = Math.min(8, Math.max(1, props.columnCount - structural - 1));
  return (
    <ul className="flex flex-col gap-3">
      {Array.from({ length: props.rowCount }, (_, row) => (
        <li
          key={row}
          className={cn("flex flex-col rounded-lg border border-border bg-card", sizes.card)}
        >
          <div className="flex h-6 items-center gap-3">
            {selectable && <Skeleton className="h-4 w-4 rounded-sm" />}
            <Skeleton className={cn("h-4", barWidth(row, 0))} />
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1">
            {Array.from({ length: pairs * 2 }, (_, index) => (
              <div key={index} className="flex h-5 items-center">
                <Skeleton className={cn("h-3.5", barWidth(row, index, 1))} />
              </div>
            ))}
          </div>
          {actions && (
            <div className="flex justify-end border-t border-border pt-2">
              <Skeleton className={cn("w-16", sizes.action)} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * The default Loading slot: the real layout in outline (toolbar, header row
 * with the real column count, a full page of rows at the current density,
 * the pagination row), so nothing moves when the data arrives. Hidden from
 * screen readers: the table's live region says "Loading…" instead.
 */
export function TableSkeleton(props: ResourceTableLoadingProps): React.ReactElement {
  return (
    <div aria-hidden="true" data-testid="resource-table-skeleton" className="flex flex-col gap-3">
      {props.toolbar && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Skeleton className="h-9 w-full max-w-80" />
          <Skeleton className="h-9 w-40" />
        </div>
      )}
      {props.layout === "cards" ? <CardsOutline {...props} /> : <TableOutline {...props} />}
      <div className="flex min-h-9 flex-wrap items-center justify-between gap-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-9 w-64" />
      </div>
    </div>
  );
}

// empty: nothing yet

/** What the NoRecords slot receives: the resource has no rows at all yet. */
export interface ResourceTableNoRecordsProps {
  /** The resource as a sentence names it, plural ("events"). */
  resourceLabel: string;
  /** One of them ("event"). */
  itemLabel: string;
  /** Set when the table knows how to create one and the role may: offer it. */
  onCreate?: () => void;
  createLabel: string;
}

/** "No events yet": explains, and offers the create action when there is one. */
export function NoRecords(props: ResourceTableNoRecordsProps): React.ReactElement {
  const { resourceLabel, itemLabel, onCreate, createLabel } = props;
  return (
    <EmptyState
      data-empty-reason="no-records"
      icon={<InboxIcon />}
      title={`No ${resourceLabel} yet`}
      description={
        onCreate !== undefined
          ? `Create the first ${itemLabel} and it will appear here.`
          : `When ${resourceLabel} are added, they will appear here.`
      }
      action={
        onCreate !== undefined ? (
          <Button size="sm" onClick={onCreate}>
            <PlusIcon className="h-4 w-4" />
            {createLabel}
          </Button>
        ) : undefined
      }
    />
  );
}

// empty: nothing matches

/** One active filter, in words ("Status: Draft"). */
export interface ResourceTableActiveFilter {
  field: string;
  label: string;
  value: string;
}

/** What the NoResults slot receives: rows exist, but none match the search or filters. */
export interface ResourceTableNoResultsProps {
  resourceLabel: string;
  /** The search term, or "" when the search box is empty. */
  search: string;
  /** The filters narrowing the list, in words. */
  filters: readonly ResourceTableActiveFilter[];
  /** Resets the search and every filter (pinned `params` stay). */
  onClearFilters: () => void;
}

/** "No events match": says what is narrowing the list and offers to clear it. */
export function NoResults(props: ResourceTableNoResultsProps): React.ReactElement {
  const { resourceLabel, search, filters, onClearFilters } = props;
  const narrowing = [
    ...(search !== "" ? [`the search “${search}”`] : []),
    ...filters.map((filter) => `${filter.label}: ${filter.value}`),
  ];
  return (
    <EmptyState
      data-empty-reason="no-results"
      icon={<FilterOffIcon />}
      title={`No ${resourceLabel} match`}
      description={`Nothing matches ${narrowing.join(" and ")}. Try a different search, or clear the filters.`}
      action={
        <Button variant="outline" size="sm" onClick={onClearFilters}>
          Clear filters
        </Button>
      }
    >
      {narrowing.length > 0 && (
        <ul aria-label="Active filters" className="mt-3 flex flex-wrap justify-center gap-2">
          {search !== "" && (
            <li className="rounded-md border border-border bg-muted px-2 py-0.5 text-xs text-foreground">
              Search: {search}
            </li>
          )}
          {filters.map((filter) => (
            <li
              key={filter.field}
              className="rounded-md border border-border bg-muted px-2 py-0.5 text-xs text-foreground"
            >
              {filter.label}: {filter.value}
            </li>
          ))}
        </ul>
      )}
    </EmptyState>
  );
}

// errors

/** The default Error slot: what failed, in plain words, with "Try again" when it can help. */
export function TableError(props: ErrorSlotProps): React.ReactElement {
  return <ErrorState {...props} />;
}

/**
 * The default RefetchError slot: a failed refresh over rows already shown.
 * The rows stay, and this one line says the list may be out of date.
 */
export function RefetchError(props: ErrorSlotProps): React.ReactElement {
  return (
    <ErrorState
      {...props}
      variant="inline"
      className="rounded-md border border-destructive-border bg-destructive-subtle px-3 py-2"
    />
  );
}

/** What the Forbidden slot receives: the list itself answered 403. */
export interface ResourceTableForbiddenProps {
  resourceLabel: string;
  /** The server's refusal (its own explanation, when it gave one, is in `data.detail`). */
  error: unknown;
}

/** "You can't view events": no retry, since asking again changes nothing. */
export function Forbidden(props: ResourceTableForbiddenProps): React.ReactElement {
  return <PermissionDenied action="view" resource={props.resourceLabel} />;
}

/** What the Offline slot receives while the browser has no connection. */
export interface ResourceTableOfflineProps {
  resourceLabel: string;
  /** Rows loaded before the connection dropped are still on screen. */
  hasRows: boolean;
  onRetry: () => void;
}

/**
 * The default Offline slot. With rows on screen it is one line above them.
 * Without rows it is the offline error panel. The table reloads by itself
 * once the connection is back.
 */
export function OfflineNotice(props: ResourceTableOfflineProps): React.ReactElement {
  if (!props.hasRows) {
    return (
      <ErrorState
        error={new TypeError("offline")}
        onRetry={props.onRetry}
        actions={
          <span className="text-sm text-muted-foreground">
            The list loads by itself when you are back online.
          </span>
        }
      />
    );
  }
  return (
    <div
      role="status"
      className={cn(
        "flex items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground",
      )}
    >
      <OfflineIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span>
        You&apos;re offline. These {props.resourceLabel} may be out of date. The list refreshes by
        itself when you&apos;re back online.
      </span>
    </div>
  );
}
