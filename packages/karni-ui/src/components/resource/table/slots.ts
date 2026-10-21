/**
 * ResourceTable's slots: every state screen and structural part a project
 * can replace with its own component, `slots={{ NoRecords: OurEmpty }}`.
 * Each slot receives the props type exported next to it; the defaults are
 * exported as `defaultResourceTableSlots`, so a replacement can wrap one
 * (`(props) => <defaultResourceTableSlots.Error {...props} />`).
 */
import type * as React from "react";
import type { ErrorSlotProps } from "../../../states/ErrorState";
import { BulkActionsBar, type BulkActionsBarProps } from "./BulkActionsBar";
import { PaginationControls, type PaginationControlsProps } from "./PaginationControls";
import { RowCard, type ResourceTableRowCardProps } from "./RowCard";
import {
  Forbidden,
  NoRecords,
  NoResults,
  OfflineNotice,
  RefetchError,
  TableError,
  TableSkeleton,
  type ResourceTableForbiddenProps,
  type ResourceTableLoadingProps,
  type ResourceTableNoRecordsProps,
  type ResourceTableNoResultsProps,
  type ResourceTableOfflineProps,
} from "./states";

/** The pagination row's props (the `Pagination` slot). */
export type ResourceTablePaginationProps = PaginationControlsProps;

/** The bulk actions bar's props (the `BulkActions` slot). */
export type ResourceTableBulkActionsProps = BulkActionsBarProps;

export interface ResourceTableSlots {
  /** The first load: the layout in outline. */
  Loading: React.ComponentType<ResourceTableLoadingProps>;
  /** The resource has no rows at all yet. */
  NoRecords: React.ComponentType<ResourceTableNoRecordsProps>;
  /** Rows exist, but none match the search and filters. */
  NoResults: React.ComponentType<ResourceTableNoResultsProps>;
  /** The list (or the schema) failed to load and there is nothing to show. */
  Error: React.ComponentType<ErrorSlotProps>;
  /** A refresh failed while rows were already on screen: the rows stay. */
  RefetchError: React.ComponentType<ErrorSlotProps>;
  /** The role may not view this resource (the list answered 403). */
  Forbidden: React.ComponentType<ResourceTableForbiddenProps>;
  /** The browser is offline. */
  Offline: React.ComponentType<ResourceTableOfflineProps>;
  /** The pagination row. */
  Pagination: React.ComponentType<ResourceTablePaginationProps>;
  /** The selected-rows bar. */
  BulkActions: React.ComponentType<ResourceTableBulkActionsProps>;
  /** One row as a card, below `cardBreakpoint`. */
  RowCard: React.ComponentType<ResourceTableRowCardProps<unknown>>;
}

export const defaultResourceTableSlots: ResourceTableSlots = {
  Loading: TableSkeleton,
  NoRecords,
  NoResults,
  Error: TableError,
  RefetchError,
  Forbidden,
  Offline: OfflineNotice,
  Pagination: PaginationControls,
  BulkActions: BulkActionsBar,
  RowCard,
};

export type {
  ResourceTableForbiddenProps,
  ResourceTableLoadingProps,
  ResourceTableNoRecordsProps,
  ResourceTableNoResultsProps,
  ResourceTableOfflineProps,
  ResourceTableRowCardProps,
};
