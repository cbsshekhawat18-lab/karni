/**
 * Public entry for ResourceTable (owner: resource table builder).
 *
 * The implementation lives in ./table/ (ResourceTable + filter bar +
 * pagination controls + bulk select, contract "ResourceTable" + D5). This
 * module keeps the barrel's import path and exported names stable.
 */
export { ResourceTable } from "./table/ResourceTable";
export type {
  BulkResult,
  ResourceTableDensity,
  ResourceTableKeyboardNavigation,
  ResourceTableProps,
} from "./table/ResourceTable";
export type { ResourceColumn } from "./table/derive-columns";
export type { BulkAction, BulkActionReturn, BulkOutcome } from "./table/BulkActionsBar";
export { defaultResourceTableSlots } from "./table/slots";
export type {
  ResourceTableBulkActionsProps,
  ResourceTableForbiddenProps,
  ResourceTableLoadingProps,
  ResourceTableNoRecordsProps,
  ResourceTableNoResultsProps,
  ResourceTableOfflineProps,
  ResourceTablePaginationProps,
  ResourceTableRowCardProps,
  ResourceTableSlots,
} from "./table/slots";
export type { ResourceTableActiveFilter } from "./table/states";
export type { ResourceTableCardField } from "./table/RowCard";
export { createHistoryStateStore } from "./table/url-state";
export type { ResourceTableStateStore } from "./table/url-state";
