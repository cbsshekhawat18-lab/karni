/**
 * ResourceTable — the schema-driven data table (contract "ResourceTable" + D5).
 *
 * `<Page title="Events"><ResourceTable resource="events" /></Page>` is a
 * complete screen: columns derive from the parsed OpenAPI schema, sorting maps
 * to DRF `ordering`, the search box renders only when the list operation
 * declares `search`, the filter bar derives from the declared query params,
 * and pagination speaks `page` / `page_size`.
 *
 * Audit fields (AUDIT_FIELDS — id, created_at, updated_at, created_by,
 * updated_by, carried by every BaseModel resource) are hidden by default so
 * domain fields lead; rows stay keyed by `id` regardless (getRowId, row
 * actions, onRowClick, bulk selection). Show one with a `columns` entry
 * (`{ field: "created_at" }`), or all of them with `showAuditFields`.
 *
 * Escape hatches: `columns` (per-field overrides), `extraColumns` (ColumnDef
 * passthrough), `columnsOverride` (applied last over the derived + merged
 * domain columns; the selection and actions columns are structural and follow
 * `bulkActions` / `rowActions` / `onEdit` / `enableDelete`), `rowActions`,
 * `bulkActions`, `filters`, `toolbar` / `empty` / `footer` slots,
 * `getRowLabel`, and `className`.
 */
import { keepPreviousData, useQueryClient } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
  type Updater,
} from "@tanstack/react-table";
import * as React from "react";
import { karniKeys } from "../../../hooks/keys";
import type { FilterValue, ResourceListParams } from "../../../hooks/types";
import { useResourceList } from "../../../hooks/useResourceList";
import type { KarniQueryValue } from "../../../schema/client";
import { useResourceMutations } from "../../../hooks/useResourceMutations";
import { cn } from "../../../lib/cn";
import type { FieldDef } from "../../../schema/types";
import { useSchema } from "../../../schema/useSchema";
import { EmptyState } from "../../empty-state/empty-state";
import { Button } from "../../primitives/button";
import { Checkbox } from "../../primitives/checkbox";
import { ChevronDownIcon, ChevronUpIcon } from "../../primitives/icons";
import { Skeleton } from "../../primitives/skeleton";
import { isAuditField, partitionAuditFields } from "../audit-fields";
import { displayLabel } from "../displayLabel";
import { BulkActionsBar, type BulkAction } from "./BulkActionsBar";
import { deriveColumns, type ResourceColumn } from "./derive-columns";
import { FilterBar } from "./FilterBar";
import { PaginationControls } from "./PaginationControls";
import {
  asRecord,
  errorMessage,
  isNotFoundError,
  pageCountFor,
  sortingToOrdering,
} from "./table-utils";
import { useDebouncedValue } from "./use-debounced-value";
import { registerComponentRole } from "../../../lib/roles";

registerComponentRole("data-table", "ResourceTable");

export type { BulkAction, ResourceColumn };

export const DEFAULT_PAGE_SIZE = 25;
const SEARCH_DEBOUNCE_MS = 300;
const MAX_DERIVED_FILTERS = 4;

export interface ResourceTableProps<T = Record<string, unknown>> {
  resource: string;
  /**
   * Per-field overrides. Naming a default-hidden field (an audit field such
   * as `created_at`, or a json/file field) shows it; `hidden: true` hides one.
   */
  columns?: ReadonlyArray<ResourceColumn<T>>;
  /**
   * Show the audit columns (AUDIT_FIELDS: id, created_at, updated_at,
   * created_by, updated_by) after the domain columns, and let audit fields
   * into the derived filter bar. Default false: they are hidden.
   */
  showAuditFields?: boolean;
  /** TanStack ColumnDef pass-through, appended after derived columns. */
  extraColumns?: ReadonlyArray<ColumnDef<T>>;
  /** Full escape hatch, applied last over the derived + merged columns. */
  columnsOverride?: (derived: Array<ColumnDef<T>>) => Array<ColumnDef<T>>;
  rowActions?: (row: T) => React.ReactNode;
  /** Passing this enables the default edit row action. */
  onEdit?: (row: T) => void;
  /** Enables the default delete row action (uses useResourceMutations). */
  enableDelete?: boolean;
  bulkActions?: ReadonlyArray<BulkAction>;
  onRowClick?: (row: T) => void;
  /**
   * `expand` query values. Default: single-relation field names ∩ the list
   * operation's expand enum — never guessed beyond the schema (D5).
   */
  expand?: readonly string[];
  initialSorting?: SortingState;
  /** Sent as `page_size`. Default 25. */
  pageSize?: number;
  /**
   * Field names to build the filter bar from; `false` disables it. Default:
   * (enum/boolean/relation fields) ∩ declared list query params, domain
   * fields first, audit fields only with `showAuditFields`, cap 4 (D5).
   * Only enum, boolean and relation fields get controls.
   */
  filters?: readonly string[] | false;
  /**
   * Fixed filters sent with every request and hidden from the filter bar —
   * e.g. `{ event: eventId }` for "the bookings of this event". A user filter
   * on the same field never overrides them.
   */
  params?: Readonly<Record<string, KarniQueryValue>>;
  /** Extra toolbar content, rendered to the right of the search/filter row. */
  toolbar?: React.ReactNode;
  /** Replaces the default EmptyState when the list has no results. */
  empty?: React.ReactNode;
  /** Rendered under the pagination row. */
  footer?: React.ReactNode;
  /** Overrides displayLabel() for relation cells (and the delete confirm). */
  getRowLabel?: (row: Record<string, unknown>) => string;
  className?: string;
}

// structural columns

function selectionColumn<T>(): ColumnDef<T> {
  return {
    id: "__select__",
    enableSorting: false,
    header: ({ table }) => (
      <Checkbox
        aria-label="Select all rows"
        checked={
          table.getIsAllPageRowsSelected()
            ? true
            : table.getIsSomePageRowsSelected()
              ? "indeterminate"
              : false
        }
        onCheckedChange={(checked) => table.toggleAllPageRowsSelected(checked === true)}
      />
    ),
    cell: ({ row }) => (
      <div className="flex items-center" onClick={(event) => event.stopPropagation()}>
        <Checkbox
          aria-label="Select row"
          checked={row.getIsSelected()}
          onCheckedChange={(checked) => row.toggleSelected(checked === true)}
        />
      </div>
    ),
  };
}

function DeleteRowButton(props: {
  resource: string;
  row: Record<string, unknown>;
  getRowLabel?: (row: Record<string, unknown>) => string;
}): React.ReactElement {
  const mutations = useResourceMutations(props.resource);
  const label = (props.getRowLabel ?? displayLabel)(props.row);
  return (
    <Button
      variant="ghost"
      size="sm"
      className="text-destructive hover:text-destructive"
      disabled={mutations.remove.isPending}
      onClick={() => {
        const id = props.row["id"];
        if (id === null || id === undefined) return;
        const confirmed =
          typeof window === "undefined" ||
          typeof window.confirm !== "function" ||
          window.confirm(`Delete "${label}"? This cannot be undone.`);
        if (confirmed) mutations.remove.mutate(id as string | number);
      }}
    >
      Delete
    </Button>
  );
}

function actionsColumn<T>(options: {
  resource: string;
  rowActions?: (row: T) => React.ReactNode;
  onEdit?: (row: T) => void;
  enableDelete?: boolean;
  getRowLabel?: (row: Record<string, unknown>) => string;
}): ColumnDef<T> {
  const { resource, rowActions, onEdit, enableDelete, getRowLabel } = options;
  return {
    id: "__actions__",
    enableSorting: false,
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <div
        className="flex items-center justify-end gap-1"
        onClick={(event) => event.stopPropagation()}
      >
        {onEdit !== undefined && (
          <Button variant="ghost" size="sm" onClick={() => onEdit(row.original)}>
            Edit
          </Button>
        )}
        {rowActions?.(row.original)}
        {enableDelete === true && (
          <DeleteRowButton
            resource={resource}
            row={asRecord(row.original)}
            getRowLabel={getRowLabel}
          />
        )}
      </div>
    ),
  };
}

// states

function TableSkeleton({ rows = 8 }: { rows?: number }): React.ReactElement {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex w-full flex-col gap-3 rounded-md border border-border p-4"
    >
      <span className="sr-only">Loading…</span>
      <Skeleton className="h-6 w-1/3" />
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-8 w-full" />
      ))}
    </div>
  );
}

function ErrorPanel(props: { error: unknown; onRetry?: () => void }): React.ReactElement {
  return (
    <div
      role="alert"
      className="flex w-full flex-col items-center gap-3 rounded-md border border-destructive/50 bg-destructive/10 px-6 py-8 text-center"
    >
      <p className="text-sm font-medium text-destructive">{errorMessage(props.error)}</p>
      {props.onRetry !== undefined && (
        <Button variant="outline" size="sm" onClick={props.onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

/** Mounted only on schema errors, so the hook never runs otherwise. */
function SchemaErrorPanel(props: { error: unknown }): React.ReactElement {
  const queryClient = useQueryClient();
  return (
    <ErrorPanel
      error={props.error}
      onRetry={() => {
        void queryClient.invalidateQueries({ queryKey: karniKeys.schema() });
      }}
    />
  );
}

// the table

export function ResourceTable<T = Record<string, unknown>>(
  props: ResourceTableProps<T>,
): React.ReactElement {
  const {
    resource,
    columns,
    showAuditFields,
    extraColumns,
    columnsOverride,
    rowActions,
    onEdit,
    enableDelete,
    bulkActions,
    onRowClick,
    expand,
    initialSorting,
    pageSize,
    filters,
    params,
    toolbar,
    empty,
    footer,
    getRowLabel,
    className,
  } = props;

  const schemaResult = useSchema(resource);
  const schema = schemaResult.data;

  // server-mode state (TanStack manual)
  const [sorting, setSorting] = React.useState<SortingState>(initialSorting ?? []);
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});
  const [page, setPage] = React.useState(1);
  const [searchInput, setSearchInput] = React.useState("");
  const [filterValues, setFilterValues] = React.useState<Record<string, FilterValue>>({});

  const effectivePageSize = pageSize ?? DEFAULT_PAGE_SIZE;
  const debouncedSearch = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS);

  // A settled search change starts over from page 1 (skip the initial value).
  const lastSearch = React.useRef(debouncedSearch);
  React.useEffect(() => {
    if (lastSearch.current !== debouncedSearch) {
      lastSearch.current = debouncedSearch;
      setPage(1);
    }
  }, [debouncedSearch]);

  const handleSortingChange = React.useCallback((updater: Updater<SortingState>) => {
    setSorting((old) => (typeof updater === "function" ? updater(old) : updater));
    setPage(1);
  }, []);

  const handleFilterChange = React.useCallback((field: FieldDef, value: FilterValue) => {
    setFilterValues((old) => {
      const cleared =
        value === null ||
        value === undefined ||
        value === "" ||
        (Array.isArray(value) && value.length === 0);
      if (cleared) {
        return Object.fromEntries(Object.entries(old).filter(([key]) => key !== field.name));
      }
      return { ...old, [field.name]: value };
    });
    setPage(1);
  }, []);

  // schema-derived behaviour (D5)
  const expandList = React.useMemo<readonly string[]>(() => {
    if (expand !== undefined) return expand;
    const allowed = schema?.operations.list?.expandEnum;
    if (schema === undefined || allowed === undefined) return [];
    return schema.fields
      .filter(
        (field) =>
          field.kind === "relation" &&
          field.relation !== undefined &&
          !field.relation.many &&
          allowed.includes(field.name),
      )
      .map((field) => field.name);
  }, [expand, schema]);

  const pinned = React.useMemo(() => new Set(Object.keys(params ?? {})), [params]);
  const filterFields = React.useMemo<readonly FieldDef[]>(() => {
    if (filters === false || schema === undefined) return [];
    if (filters !== undefined) {
      const byName = new Map(schema.fields.map((field) => [field.name, field]));
      return filters
        .filter((name) => !pinned.has(name))
        .map((name) => byName.get(name))
        .filter((field): field is FieldDef => field !== undefined);
    }
    const declared = new Set(schema.operations.list?.queryParams ?? []);
    const { domain, audit } = partitionAuditFields(schema.fields);
    return [...domain, ...audit]
      .filter(
        (field) =>
          !field.writeOnly &&
          !pinned.has(field.name) &&
          (showAuditFields === true || !isAuditField(field)) &&
          declared.has(field.name) &&
          (field.kind === "enum" ||
            field.kind === "boolean" ||
            (field.kind === "relation" && field.relation !== undefined)),
      )
      .slice(0, MAX_DERIVED_FILTERS);
  }, [filters, pinned, schema, showAuditFields]);

  const searchEnabled = schema?.operations.list?.hasSearch === true;

  // the list query
  const trimmedSearch = debouncedSearch.trim();
  const listParams = React.useMemo<ResourceListParams>(
    () => ({
      page,
      pageSize: effectivePageSize,
      ordering: sortingToOrdering(sorting),
      search: searchEnabled && trimmedSearch.length > 0 ? trimmedSearch : undefined,
      filters:
        Object.keys(filterValues).length > 0 || params !== undefined
          ? { ...filterValues, ...params }
          : undefined,
      expand: expandList.length > 0 ? expandList : undefined,
    }),
    [
      page,
      effectivePageSize,
      sorting,
      searchEnabled,
      trimmedSearch,
      filterValues,
      params,
      expandList,
    ],
  );

  const list = useResourceList<T>(resource, listParams, {
    enabled: schema !== undefined,
    placeholderData: keepPreviousData,
    // A 404 is the page-clamp signal (D5) — retrying it only delays the clamp.
    retry: (failureCount, error) => !isNotFoundError(error) && failureCount < 3,
  });

  // D5 page-clamp: list 404 with page > 1 → decrement + refetch as loading.
  const clamping = isNotFoundError(list.error) && page > 1;
  React.useEffect(() => {
    if (clamping) setPage((current) => Math.max(1, current - 1));
  }, [clamping, page]);

  // columns
  const hasBulkSelect = bulkActions !== undefined && bulkActions.length > 0;
  const hasActions = rowActions !== undefined || onEdit !== undefined || enableDelete === true;

  const columnDefs = React.useMemo<Array<ColumnDef<T>>>(() => {
    if (schema === undefined) return [];
    let defs = deriveColumns<T>({ fields: schema.fields, columns, getRowLabel, showAuditFields });
    if (extraColumns !== undefined) defs = [...defs, ...extraColumns];
    if (columnsOverride !== undefined) defs = columnsOverride(defs);
    const leading: Array<ColumnDef<T>> = hasBulkSelect ? [selectionColumn<T>()] : [];
    const trailing: Array<ColumnDef<T>> = hasActions
      ? [actionsColumn<T>({ resource, rowActions, onEdit, enableDelete, getRowLabel })]
      : [];
    return [...leading, ...defs, ...trailing];
  }, [
    schema,
    columns,
    getRowLabel,
    showAuditFields,
    extraColumns,
    columnsOverride,
    hasBulkSelect,
    hasActions,
    resource,
    rowActions,
    onEdit,
    enableDelete,
  ]);

  const rows = React.useMemo<T[]>(() => list.data?.results ?? [], [list.data]);
  const count = list.data?.count;
  const pageCount = pageCountFor(count, effectivePageSize);

  const table = useReactTable<T>({
    data: rows,
    columns: columnDefs,
    state: { sorting, rowSelection },
    manualSorting: true,
    manualPagination: true,
    manualFiltering: true,
    pageCount,
    enableRowSelection: hasBulkSelect,
    onSortingChange: handleSortingChange,
    onRowSelectionChange: setRowSelection,
    // D5: selection is keyed by String(row.id) and persists across pages —
    // rows always carry `id`, even while its column is hidden.
    getRowId: (row) => String(asRecord(row).id),
    getCoreRowModel: getCoreRowModel(),
  });

  const selectedIds = React.useMemo(
    () => Object.keys(rowSelection).filter((id) => rowSelection[id]),
    [rowSelection],
  );

  const hasActiveNarrowing = trimmedSearch.length > 0 || Object.keys(filterValues).length > 0;

  // render
  let body: React.ReactNode;
  if (schemaResult.error !== null && schemaResult.error !== undefined) {
    body = <SchemaErrorPanel error={schemaResult.error} />;
  } else if (schemaResult.isLoading || schema === undefined || list.isPending || clamping) {
    body = <TableSkeleton />;
  } else if (list.error !== null && list.error !== undefined) {
    body = (
      <ErrorPanel
        error={list.error}
        onRetry={() => {
          void list.refetch();
        }}
      />
    );
  } else if (rows.length === 0) {
    body =
      empty ??
      (hasActiveNarrowing ? (
        <EmptyState title="No results" description="Try adjusting your search or filters." />
      ) : (
        <EmptyState title="Nothing here yet" description="Records will appear here once created." />
      ));
  } else {
    body = (
      <>
        <div
          className={cn(
            "w-full overflow-x-auto rounded-md border border-border",
            list.isFetching && "opacity-60",
          )}
        >
          <table className="w-full caption-bottom text-sm" aria-busy={list.isFetching}>
            <thead className="border-b border-border bg-muted">
              <tr>
                {table.getFlatHeaders().map((header) => {
                  const canSort = header.column.getCanSort();
                  const direction = header.column.getIsSorted();
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
                      className="h-10 px-3 text-left align-middle text-xs font-medium uppercase tracking-wide text-muted-foreground"
                    >
                      {header.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 rounded-sm hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={(event) => header.column.getToggleSortingHandler()?.(event)}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {direction === "asc" ? (
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
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  data-state={row.getIsSelected() ? "selected" : undefined}
                  onClick={onRowClick !== undefined ? () => onRowClick(row.original) : undefined}
                  className={cn(
                    "border-b border-border transition-colors last:border-0 hover:bg-muted data-[state=selected]:bg-muted",
                    onRowClick !== undefined && "cursor-pointer",
                  )}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-3 py-2 align-middle">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {count !== undefined && count > 0 && (
          <PaginationControls
            page={page}
            pageCount={pageCount}
            totalCount={count}
            hasPrevious={list.data?.previous !== null && list.data?.previous !== undefined}
            hasNext={list.data?.next !== null && list.data?.next !== undefined}
            onPageChange={setPage}
          />
        )}
      </>
    );
  }

  const showFilterRow =
    schema !== undefined && (searchEnabled || filterFields.length > 0 || toolbar !== undefined);

  return (
    <div className={cn("flex w-full flex-col gap-3", className)}>
      {showFilterRow && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <FilterBar
            searchEnabled={searchEnabled}
            searchValue={searchInput}
            onSearchChange={setSearchInput}
            filterFields={filterFields}
            values={filterValues}
            onFilterChange={handleFilterChange}
            className="min-w-0 flex-1"
          />
          {toolbar !== undefined && (
            <div className="flex shrink-0 items-center gap-2">{toolbar}</div>
          )}
        </div>
      )}
      {hasBulkSelect && selectedIds.length > 0 && (
        <BulkActionsBar
          selectedIds={selectedIds}
          bulkActions={bulkActions}
          onClear={() => setRowSelection({})}
        />
      )}
      {body}
      {footer}
    </div>
  );
}
