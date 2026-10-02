/**
 * Public entry for ResourceTable (owner: resource table builder).
 *
 * The implementation lives in ./table/ (ResourceTable + filter bar +
 * pagination controls + bulk select, contract "ResourceTable" + D5); this
 * module keeps the barrel's import path and exported names stable.
 */
export { ResourceTable } from "./table/ResourceTable";
export type { ResourceTableProps } from "./table/ResourceTable";
export type { ResourceColumn } from "./table/derive-columns";
export type { BulkAction } from "./table/BulkActionsBar";
