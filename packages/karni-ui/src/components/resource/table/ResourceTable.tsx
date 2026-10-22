/**
 * ResourceTable: the schema-driven data table (contract "ResourceTable" + D5).
 *
 * `<Page title="Events"><ResourceTable resource="events" /></Page>` is a
 * complete screen: columns derive from the parsed OpenAPI schema, sorting maps
 * to DRF `ordering`, the search box renders only when the list operation
 * declares `search`, the filter bar derives from the declared query params,
 * and pagination speaks `page` / `page_size` (one page is fetched, never
 * everything).
 *
 * Every state is its own screen, each a replaceable slot: the loading outline
 * (the real layout, so nothing moves when data arrives), "no records yet"
 * (with the create action when there is one) apart from "nothing matches"
 * (with "Clear filters"), errors in plain words with a retry, a failed
 * refresh that keeps the rows, "You can't view events" for a 403, offline,
 * and progress once work runs for 500ms.
 *
 * Page, page size, ordering, search and filters live in the URL (namespaced,
 * Back works). `syncUrl={false}` opts out and `stateStore` plugs in a router.
 * Below `cardBreakpoint` (its container's width, not the viewport's) rows
 * render as cards. Wide tables scroll inside their box with a sticky header
 * and a frozen first column. Density and hidden columns are remembered per
 * user. In the table layout the rows are a WAI-ARIA grid: the whole table
 * is one Tab stop and the arrow keys move between rows and cells
 * (`keyboardNavigation="native"` makes every control a Tab stop again).
 *
 * Audit fields (AUDIT_FIELDS: id, created_at, updated_at, created_by,
 * updated_by, carried by every BaseModel resource) are hidden by default so
 * domain fields lead. Rows stay keyed by `id` regardless (getRowId, row
 * actions, onRowClick, bulk selection). Show one with a `columns` entry
 * (`{ field: "created_at" }`), or all of them with `showAuditFields`.
 *
 * Escape hatches: `columns` (per-field overrides), `extraColumns` (ColumnDef
 * passthrough), `columnsOverride` (applied last over the derived + merged
 * domain columns, but the selection and actions columns are structural and
 * follow `bulkActions` / `rowActions` / `onEdit` / `enableDelete`),
 * `rowActions`, `bulkActions`, `filters`, `slots` (every state screen and
 * part), `toolbar` / `empty` / `footer`, `canCreate` / `canEdit` /
 * `canDelete` (over the schema's access rules), `stateStore`, `getRowLabel`,
 * and `className`.
 */
import { keepPreviousData, useQueryClient } from "@tanstack/react-query";
import {
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type Header,
  type RowSelectionState,
  type SortingState,
  type Updater,
  type VisibilityState,
} from "@tanstack/react-table";
import * as React from "react";
import { AuthContext } from "../../../auth/provider";
import { karniKeys } from "../../../hooks/keys";
import type { FilterValue, Paginated, ResourceListParams } from "../../../hooks/types";
import type { ExportFormat } from "../../../hooks/useResourceImport";
import { useResourceList } from "../../../hooks/useResourceList";
import { useResourceMutations } from "../../../hooks/useResourceMutations";
import { cn } from "../../../lib/cn";
import { registerComponentRole } from "../../../lib/roles";
import type { KarniQueryValue } from "../../../schema/client";
import { humanize } from "../../../schema/parse";
import type { FieldDef } from "../../../schema/types";
import { useSchema } from "../../../schema/useSchema";
import { useDelayedFlag, useOnlineStatus } from "../../../states/hooks";
import { Button } from "../../primitives/button";
import { isAuditField, partitionAuditFields } from "../audit-fields";
import { displayLabel } from "../displayLabel";
import { evaluateAccess, type AccessIdentity } from "./access";
import type { BulkAction, BulkOutcome, BulkResult } from "./BulkActionsBar";
import { CardList } from "./CardList";
import { ConfirmDialog } from "./ConfirmDialog";
import { deriveColumns, type ResourceColumn } from "./derive-columns";
import { ExportButtons } from "./ExportButtons";
import { FilterBar } from "./FilterBar";
import { DENSITY_CLASSES } from "./layout";
import {
  asString,
  densityKey,
  hiddenColumnsKey,
  parseColumnList,
  parseDensity,
  serializeColumnList,
  useStoredPreference,
  type ResourceTableDensity,
} from "./preferences";
import { defaultResourceTableSlots, type ResourceTableSlots } from "./slots";
import type { ResourceTableActiveFilter } from "./states";
import { actionsColumn, isStructural, selectionColumn } from "./structural-columns";
import { PlusIcon } from "./table-icons";
import {
  asRecord,
  capitalised,
  enumLabel,
  isNotFoundError,
  orderingToSorting,
  pageCountFor,
  resourceWords,
  listRetry,
  singular,
  sortingToOrdering,
  statusOf,
} from "./table-utils";
import { TableView, type ResourceTableKeyboardNavigation } from "./TableView";
import { useContainerWidth } from "./use-container-width";
import { useDebouncedValue } from "./use-debounced-value";
import { useTableView, type ResourceTableStateStore } from "./url-state";
import { ViewOptions as ViewOptionsMenu } from "./ViewOptions";

registerComponentRole("data-table", "ResourceTable");

export type {
  BulkAction,
  BulkResult,
  ResourceColumn,
  ResourceTableDensity,
  ResourceTableKeyboardNavigation,
};

export const DEFAULT_PAGE_SIZE = 25;
/** The page sizes offered by default (`pageSizeOptions`). */
export const DEFAULT_PAGE_SIZE_OPTIONS: readonly number[] = [10, 25, 50, 100];
/** Below this container width (px) rows render as cards (`cardBreakpoint`). */
export const DEFAULT_CARD_BREAKPOINT = 640;
const SEARCH_DEBOUNCE_MS = 300;
const MAX_DERIVED_FILTERS = 4;
/** Columns the loading outline draws before the schema says how many there are. */
const SKELETON_COLUMNS = 5;
const NO_COLUMNS: readonly string[] = [];

export interface ResourceTableProps<T = Record<string, unknown>> {
  resource: string;
  /**
   * Per-field overrides. Naming a default-hidden field (an audit field such
   * as `created_at`, or a json/file field) shows it. `hidden: true` hides one.
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
  /** Enables the default delete row action (confirms in a dialog, uses useResourceMutations). */
  enableDelete?: boolean;
  bulkActions?: ReadonlyArray<BulkAction>;
  /**
   * Opens a row. The whole row is clickable, and its first cell is a button,
   * so the row opens from the keyboard too (Enter on any cell of the grid).
   */
  onRowClick?: (row: T) => void;
  /**
   * `expand` query values. Default: single-relation field names ∩ the list
   * operation's expand enum, never guessed beyond the schema (D5).
   */
  expand?: readonly string[];
  /** The ordering when the URL names none. */
  initialSorting?: SortingState;
  /** Sent as `page_size`. Default 25. */
  pageSize?: number;
  /** The page sizes a user can choose. Default `[10, 25, 50, 100]`. `pageSize` is always offered. */
  pageSizeOptions?: readonly number[];
  /**
   * Field names to build the filter bar from. `false` disables it. Default:
   * (enum/boolean/relation fields) ∩ declared list query params, domain
   * fields first, audit fields only with `showAuditFields`, cap 4 (D5).
   * Only enum, boolean and relation fields get controls.
   */
  filters?: readonly string[] | false;
  /**
   * Fixed filters sent with every request and hidden from the filter bar,
   * e.g. `{ event: eventId }` for "the bookings of this event". A user filter
   * on the same field never overrides them. Never written to the URL.
   */
  params?: Readonly<Record<string, KarniQueryValue>>;
  /**
   * Export buttons (one per format) when the resource serves
   * `GET /<resource>/export/`, as every Karni BaseViewSet does. The file
   * carries the table's current filters, search and ordering. The backend
   * applies the row scope and field visibility. Default `["csv", "xlsx"]`.
   * `false` hides them.
   */
  exportFormats?: readonly ExportFormat[] | false;
  /** Extra toolbar content, rendered to the right of the search/filter row. */
  toolbar?: React.ReactNode;
  /**
   * Replaces both empty screens. Prefer `slots.NoRecords` and
   * `slots.NoResults`, which tell "nothing yet" from "nothing matches".
   */
  empty?: React.ReactNode;
  /** Rendered under the pagination row. */
  footer?: React.ReactNode;
  /** Overrides displayLabel() for relation cells, row names (checkboxes, cards, the delete question). */
  getRowLabel?: (row: Record<string, unknown>) => string;
  /** Replace any state screen or part (see ResourceTableSlots). */
  slots?: Partial<ResourceTableSlots>;
  /** The resource in sentences, plural ("events"). Default: from the resource name. */
  resourceLabel?: string;
  /** One of them ("event"). Default: a singular of `resourceLabel`. */
  itemLabel?: string;
  /** Names the table for assistive technology. Default: `resourceLabel`, capitalised. */
  caption?: string;
  /** Offers a create button (toolbar and the "no records yet" screen). */
  onCreate?: () => void;
  /** Default "New <itemLabel>". */
  createLabel?: string;
  /**
   * Whether the role may create. Default: the schema documents a create
   * operation and its access rule does not refuse this user.
   */
  canCreate?: boolean;
  /** Whether a row's edit action shows. Default: the update operation's access rule for this user and row. */
  canEdit?: boolean | ((row: T) => boolean);
  /** Whether a row's delete action shows. Default: the delete operation's access rule for this user and row. */
  canDelete?: boolean | ((row: T) => boolean);
  /** Keep page, page size, sort, search and filters in the URL. Default true. */
  syncUrl?: boolean;
  /** Prefix of this table's URL keys (`events.page=2`). Default: the resource name, `""` for none. */
  urlNamespace?: string;
  /** Where URL state lives. Default `window.history`. Plug a router in here. */
  stateStore?: ResourceTableStateStore;
  /** Row density, controlled. Uncontrolled, the user's choice is remembered per user. */
  density?: ResourceTableDensity;
  /** The density before the user chooses. Default "comfortable". */
  defaultDensity?: ResourceTableDensity;
  onDensityChange?: (density: ResourceTableDensity) => void;
  /** The "View" menu (density, column visibility). Default true. */
  viewOptions?: boolean;
  /** Below this container width (px) rows render as cards. Default 640, and 0 means never. */
  cardBreakpoint?: number;
  /**
   * How the keyboard moves through the table layout. Default `"grid"`, the
   * WAI-ARIA grid pattern: the whole table is one Tab stop, the arrow keys
   * move between rows and cells (each control of a cell is a stop of its
   * own), Home and End go to the ends of a row, Ctrl+Home and Ctrl+End to
   * the first and last cell, Enter on a cell opens the row (`onRowClick`) and
   * Space on a cell selects it (`bulkActions`). `"native"` is a plain table
   * where every checkbox, button and link is its own Tab stop, as before.
   */
  keyboardNavigation?: ResourceTableKeyboardNavigation;
  className?: string;
}

interface DeleteTarget<T> {
  row: T;
  trigger: HTMLButtonElement;
}

interface ConfirmTarget {
  index: number;
  trigger: HTMLButtonElement | null;
}

function isPromiseLike(value: unknown): value is PromiseLike<unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { then?: unknown }).then === "function"
  );
}

function textOf(node: React.ReactNode): string | undefined {
  return typeof node === "string" || typeof node === "number" ? String(node) : undefined;
}

function filterWords(field: FieldDef, value: FilterValue): string {
  if (field.kind === "boolean") return value === true ? "Yes" : "No";
  if (field.kind === "enum" && (typeof value === "string" || typeof value === "number")) {
    return enumLabel(value, field.enumLabels);
  }
  if (Array.isArray(value)) return `${value.length} chosen`;
  if (field.kind === "relation") return "1 chosen";
  return String(value);
}

/** The delete question for one row. Its mutation lives here so tables without deletes never create it. */
function RowDeleteDialog<T>(props: {
  resource: string;
  target: DeleteTarget<T> | null;
  rowLabel: (row: T) => string;
  onClose: () => void;
  onDeleted: (label: string) => void;
  fallbackFocus: () => HTMLElement | null;
}): React.ReactElement {
  const { resource, target, rowLabel, onClose, onDeleted, fallbackFocus } = props;
  const mutations = useResourceMutations(resource);
  const [error, setError] = React.useState<unknown>(null);
  const deleted = React.useRef(false);
  // The dialog closes after `target` is cleared: keep wording and focus on the last one.
  const last = React.useRef(target);
  if (target !== null) last.current = target;
  React.useEffect(() => {
    setError(null);
    if (target !== null) deleted.current = false;
  }, [target]);
  const label = last.current === null ? "" : rowLabel(last.current.row);
  const quoted = `“${label}”`;
  return (
    <ConfirmDialog
      open={target !== null}
      title={`Delete ${quoted}?`}
      description="This can't be undone."
      confirmLabel="Delete"
      pendingLabel="Deleting…"
      destructive
      pending={mutations.remove.isPending}
      error={error}
      errorContext={{ action: "delete", resource: quoted }}
      onCancel={onClose}
      onConfirm={() => {
        const id = target === null ? undefined : asRecord(target.row)["id"];
        if (typeof id !== "string" && typeof id !== "number") return;
        setError(null);
        mutations.remove.mutate(id, {
          onSuccess: () => {
            deleted.current = true;
            onDeleted(label);
          },
          onError: (failure) => setError(failure),
        });
      }}
      returnFocus={() => {
        const trigger = last.current?.trigger;
        return !deleted.current && trigger !== undefined && trigger.isConnected
          ? trigger
          : fallbackFocus();
      }}
    />
  );
}

/** Schema-driven data table for one resource: columns, sorting, filters, search, pagination, row actions and bulk select, all derived from the OpenAPI schema. */
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
    pageSizeOptions,
    filters,
    params,
    exportFormats,
    toolbar,
    empty,
    footer,
    getRowLabel,
    slots: slotOverrides,
    resourceLabel,
    itemLabel,
    caption,
    onCreate,
    createLabel,
    canCreate,
    canEdit,
    canDelete,
    syncUrl = true,
    urlNamespace,
    stateStore,
    density: densityProp,
    defaultDensity = "comfortable",
    onDensityChange,
    viewOptions = true,
    cardBreakpoint = DEFAULT_CARD_BREAKPOINT,
    keyboardNavigation = "grid",
    className,
  } = props;

  const Slots = React.useMemo<ResourceTableSlots>(
    () => ({ ...defaultResourceTableSlots, ...slotOverrides }),
    [slotOverrides],
  );
  const queryClient = useQueryClient();
  const auth = React.useContext(AuthContext);
  const authStatus = auth?.status;
  const authUser = auth?.user ?? null;
  const identity = React.useMemo<AccessIdentity | null>(
    () => (authStatus === undefined ? null : { status: authStatus, user: authUser }),
    [authStatus, authUser],
  );
  const userId = authStatus === "authenticated" ? authUser?.id : undefined;

  const schemaResult = useSchema(resource);
  const schema = schemaResult.data;

  const plural = resourceLabel ?? resourceWords(resource);
  const one = itemLabel ?? singular(plural);
  const tableName = caption ?? capitalised(plural);
  const namespace = urlNamespace ?? resource;

  // filters the bar offers (D5)
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

  // view state: the URL (or component state with syncUrl={false})
  const defaultPageSize = pageSize ?? DEFAULT_PAGE_SIZE;
  const sizesKey = (pageSizeOptions ?? DEFAULT_PAGE_SIZE_OPTIONS).join(",");
  const defaultOrdering = sortingToOrdering(initialSorting ?? []) ?? "";
  const defaults = React.useMemo(
    () => ({
      pageSize: defaultPageSize,
      ordering: defaultOrdering,
      pageSizes: [
        ...new Set([...sizesKey.split(",").map(Number).filter(Number.isFinite), defaultPageSize]),
      ].sort((a, b) => a - b),
    }),
    [defaultPageSize, defaultOrdering, sizesKey],
  );
  const [view, setView] = useTableView({
    syncUrl,
    store: stateStore,
    namespace,
    defaults,
    filterFields,
  });
  const viewRef = React.useRef(view);
  viewRef.current = view;
  const sorting = React.useMemo(() => orderingToSorting(view.ordering), [view.ordering]);

  // announcements for screen readers
  const [announcement, setAnnouncement] = React.useState("");
  const intent = React.useRef<"page" | "results" | null>(null);

  // search: the box is local while typing, the settled term is URL state
  const [searchInput, setSearchInput] = React.useState(view.search);
  const debouncedSearch = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS);
  const shownSearch = React.useRef(view.search);
  React.useEffect(() => {
    // Back, Forward, a shared link or "Clear filters" changed the search.
    if (view.search !== shownSearch.current) {
      shownSearch.current = view.search;
      setSearchInput(view.search);
    }
  }, [view.search]);
  const settledSearch = React.useRef(debouncedSearch);
  React.useEffect(() => {
    if (debouncedSearch === settledSearch.current) return;
    settledSearch.current = debouncedSearch;
    const term = debouncedSearch.trim();
    const current = viewRef.current;
    if (term === current.search) return;
    shownSearch.current = term;
    intent.current = "results";
    // The first keystrokes add a history entry; refining the term replaces it.
    setView({ search: term, page: 1 }, { push: current.search === "" });
  }, [debouncedSearch, setView]);

  const handleFilterChange = React.useCallback(
    (field: FieldDef, value: FilterValue) => {
      intent.current = "results";
      setView(
        { filters: { ...viewRef.current.filters, [field.name]: value }, page: 1 },
        { push: true },
      );
    },
    [setView],
  );

  const clearFilters = React.useCallback(() => {
    intent.current = "results";
    setSearchInput("");
    setView({ search: "", filters: {}, page: 1 }, { push: true });
  }, [setView]);

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

  const searchEnabled = schema?.operations.list?.hasSearch === true;
  const activeSearch = searchEnabled ? view.search : "";

  // the list query: one page, never everything
  const listParams = React.useMemo<ResourceListParams>(
    () => ({
      page: view.page,
      pageSize: view.pageSize,
      ordering: view.ordering === "" ? undefined : view.ordering,
      search: activeSearch.length > 0 ? activeSearch : undefined,
      filters:
        Object.keys(view.filters).length > 0 || params !== undefined
          ? { ...view.filters, ...params }
          : undefined,
      expand: expandList.length > 0 ? expandList : undefined,
    }),
    [view, activeSearch, params, expandList],
  );

  const appRetry = queryClient.getDefaultOptions().queries?.retry;
  const retry = React.useMemo(() => listRetry(appRetry), [appRetry]);
  const list = useResourceList<T>(resource, listParams, {
    enabled: schema !== undefined,
    placeholderData: keepPreviousData,
    // A 4xx answers the same way again (a 404 is the page-clamp signal, D5);
    // the rest follows the app's QueryClient.
    retry,
  });

  // The last page that loaded, kept so a failed refresh never wipes the table.
  const lastLoaded = React.useRef<{ resource: string; data: Paginated<T> } | null>(null);
  if (list.data !== undefined) lastLoaded.current = { resource, data: list.data };
  const lastData = lastLoaded.current?.resource === resource ? lastLoaded.current.data : undefined;

  const status = statusOf(list.error);
  const hasError = list.error !== null && list.error !== undefined;
  // D5 page clamp: a 404 past page 1 means the page is gone (fewer rows now).
  const clamping = isNotFoundError(list.error) && view.page > 1;
  React.useEffect(() => {
    if (!clamping) return;
    const known = lastData !== undefined ? pageCountFor(lastData.count, view.pageSize) : 1;
    const target = view.page > known ? known : view.page - 1;
    setView({ page: Math.max(1, target) }, { push: false });
  }, [clamping, lastData, view.page, view.pageSize, setView]);

  const blocking = status === 401 || status === 403;
  const shownData = list.data ?? (hasError && !blocking && !clamping ? lastData : undefined);
  const stale = list.data === undefined && shownData !== undefined;

  // connection
  const online = useOnlineStatus();
  const paused = list.fetchStatus === "paused";
  const wasOnline = React.useRef(online);
  const refetch = list.refetch;
  React.useEffect(() => {
    // Back online: reload what failed (TanStack resumes paused queries itself).
    if (online && !wasOnline.current && hasError) void refetch();
    wasOnline.current = online;
  }, [online, hasError, refetch]);

  const transitioning = list.isFetching && list.isPlaceholderData === true;
  const slow = useDelayedFlag(list.isFetching);

  // preferences, per user
  const [storedDensity, setStoredDensity] = useStoredPreference(
    densityKey(userId),
    defaultDensity,
    parseDensity,
    asString,
  );
  const density = densityProp ?? storedDensity;
  const changeDensity = React.useCallback(
    (next: ResourceTableDensity) => {
      if (densityProp === undefined) setStoredDensity(next);
      onDensityChange?.(next);
    },
    [densityProp, setStoredDensity, onDensityChange],
  );
  const [hiddenColumns, setHiddenColumns] = useStoredPreference<readonly string[]>(
    hiddenColumnsKey(namespace, userId),
    NO_COLUMNS,
    parseColumnList,
    serializeColumnList,
  );

  // permissions: explicit props win over the schema's access rules
  const rowLabel = React.useCallback(
    (row: T) => (getRowLabel ?? displayLabel)(asRecord(row)),
    [getRowLabel],
  );
  const updateRule = schema?.operations.update?.access;
  const removeRule = schema?.operations.remove?.access;
  const createRule = schema?.operations.create?.access;
  // The item path is documented but has no DELETE: nobody can delete.
  const deleteMissing =
    schema !== undefined &&
    schema.operations.detail !== undefined &&
    schema.operations.remove === undefined;
  const allowEdit = React.useCallback(
    (row: T): boolean => {
      if (typeof canEdit === "function") return canEdit(row);
      if (canEdit !== undefined) return canEdit;
      return evaluateAccess(updateRule, identity, row) !== false;
    },
    [canEdit, updateRule, identity],
  );
  const allowDelete = React.useCallback(
    (row: T): boolean => {
      if (typeof canDelete === "function") return canDelete(row);
      if (canDelete !== undefined) return canDelete;
      return !deleteMissing && evaluateAccess(removeRule, identity, row) !== false;
    },
    [canDelete, deleteMissing, removeRule, identity],
  );
  const createAllowed =
    onCreate !== undefined &&
    (canCreate ??
      (schema?.operations.create !== undefined && evaluateAccess(createRule, identity) !== false));
  const createText = createLabel ?? `New ${one}`;

  // row delete
  const [deleteTarget, setDeleteTarget] = React.useState<DeleteTarget<T> | null>(null);
  const requestDelete = React.useCallback((row: T, trigger: HTMLButtonElement) => {
    setDeleteTarget({ row, trigger });
  }, []);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const cardListRef = React.useRef<HTMLUListElement>(null);
  const rootRef = React.useRef<HTMLDivElement>(null);
  // Where focus lands when the control that had it is gone (a deleted row, the
  // bulk toolbar once its action ran): the table's scroll region, or the card
  // list below the card breakpoint. Both take focus by script.
  const fallbackFocus = React.useCallback(
    (): HTMLElement | null => scrollRef.current ?? cardListRef.current ?? rootRef.current,
    [],
  );

  // columns
  const hasBulkSelect = bulkActions !== undefined && bulkActions.length > 0;
  const hasActions = rowActions !== undefined || onEdit !== undefined || enableDelete === true;
  const actionButtons = DENSITY_CLASSES[density].action;

  const columnDefs = React.useMemo<Array<ColumnDef<T>>>(() => {
    if (schema === undefined) return [];
    let defs = deriveColumns<T>({ fields: schema.fields, columns, getRowLabel, showAuditFields });
    if (extraColumns !== undefined) defs = [...defs, ...extraColumns];
    if (columnsOverride !== undefined) defs = columnsOverride(defs);
    const leading: Array<ColumnDef<T>> = hasBulkSelect
      ? [selectionColumn<T>({ rowLabel, resourceLabel: plural })]
      : [];
    const trailing: Array<ColumnDef<T>> = hasActions
      ? [
          actionsColumn<T>({
            rowActions,
            onEdit,
            canEdit: allowEdit,
            onDelete: enableDelete === true ? requestDelete : undefined,
            canDelete: allowDelete,
            buttonClassName: actionButtons,
          }),
        ]
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
    rowLabel,
    plural,
    rowActions,
    onEdit,
    allowEdit,
    enableDelete,
    requestDelete,
    allowDelete,
    actionButtons,
  ]);

  const columnLabel = React.useCallback(
    (id: string): string => {
      const def = columnDefs.find((candidate) => candidate.id === id);
      if (typeof def?.header === "string") return def.header;
      return schema?.fields.find((field) => field.name === id)?.label ?? humanize(id);
    },
    [columnDefs, schema],
  );

  const columnVisibility = React.useMemo<VisibilityState>(
    () => Object.fromEntries(hiddenColumns.map((id) => [id, false])),
    [hiddenColumns],
  );

  const rows = React.useMemo<T[]>(() => shownData?.results ?? [], [shownData]);
  const count = shownData?.count;
  const pageCount = pageCountFor(count, view.pageSize);

  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});
  const [sortTarget, setSortTarget] = React.useState<string | null>(null);

  const handleSortingChange = React.useCallback(
    (updater: Updater<SortingState>) => {
      const current = orderingToSorting(viewRef.current.ordering);
      const next = typeof updater === "function" ? updater(current) : updater;
      const first = next[0];
      setAnnouncement(
        first === undefined
          ? "Sorting cleared."
          : `Sorted by ${columnLabel(first.id)}, ${first.desc ? "descending" : "ascending"}.`,
      );
      setView({ ordering: sortingToOrdering(next) ?? "", page: 1 }, { push: true });
    },
    [columnLabel, setView],
  );

  const table = useReactTable<T>({
    data: rows,
    columns: columnDefs,
    state: { sorting, rowSelection, columnVisibility },
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
  const selectedRef = React.useRef(selectedIds);
  selectedRef.current = selectedIds;

  // Say what changed once the new rows are in.
  React.useEffect(() => {
    if (intent.current === null || list.isFetching || list.data === undefined) return;
    const kind = intent.current;
    intent.current = null;
    const total = list.data.count;
    if (kind === "page") {
      setAnnouncement(
        `Showing page ${view.page.toLocaleString()} of ${pageCountFor(total, view.pageSize).toLocaleString()}.`,
      );
    } else {
      setAnnouncement(
        total === 0
          ? `No ${plural} match.`
          : `${total.toLocaleString()} ${total === 1 ? one : plural} match.`,
      );
    }
  }, [list.isFetching, list.data, view.page, view.pageSize, plural, one]);

  const firstSelection = React.useRef(true);
  // A finished bulk action says what it did; its deselection needs no second word.
  const quietSelection = React.useRef(false);
  React.useEffect(() => {
    if (firstSelection.current || quietSelection.current) {
      firstSelection.current = false;
      quietSelection.current = false;
      return;
    }
    setAnnouncement(
      selectedIds.length === 0 ? "Selection cleared." : `${selectedIds.length} selected.`,
    );
  }, [selectedIds.length]);

  // bulk actions
  const [runningIndex, setRunningIndex] = React.useState<number | null>(null);
  const [outcome, setOutcome] = React.useState<BulkOutcome | null>(null);
  const [failures, setFailures] = React.useState<Record<string, string>>({});
  const [confirmTarget, setConfirmTarget] = React.useState<ConfirmTarget | null>(null);
  const [confirmError, setConfirmError] = React.useState<unknown>(null);

  const runBulk = React.useCallback(
    async (index: number, confirmed: boolean): Promise<void> => {
      const action = bulkActions?.[index];
      if (action === undefined) return;
      const ids = [...selectedRef.current];
      const actionLabel = textOf(action.label) ?? "The action";
      setOutcome(null);
      setFailures({});
      setConfirmError(null);
      let returned: unknown;
      try {
        returned = action.onClick(ids);
      } catch (error) {
        if (confirmed) setConfirmError(error);
        else setOutcome({ kind: "failed", actionLabel, error, count: ids.length });
        return;
      }
      if (!isPromiseLike(returned)) {
        // A plain `void` action: the selection stays, as it always has.
        setConfirmTarget(null);
        return;
      }
      setRunningIndex(index);
      try {
        const result = (await returned) as BulkResult | undefined;
        const failed = result?.failed ?? [];
        setConfirmTarget(null);
        if (failed.length > 0) {
          setFailures(Object.fromEntries(failed.map((entry) => [entry.id, entry.reason])));
          setRowSelection(Object.fromEntries(failed.map((entry) => [entry.id, true])));
          setOutcome({ kind: "partial", actionLabel, failed: failed.length, total: ids.length });
        } else {
          quietSelection.current = true;
          setRowSelection({});
          setAnnouncement(
            `${actionLabel}: done for ${ids.length} ${ids.length === 1 ? one : plural}.`,
          );
        }
        void queryClient.invalidateQueries({ queryKey: karniKeys.resource(resource) });
      } catch (error) {
        if (confirmed) setConfirmError(error);
        else setOutcome({ kind: "failed", actionLabel, error, count: ids.length });
      } finally {
        setRunningIndex(null);
      }
    },
    [bulkActions, queryClient, resource, one, plural],
  );

  const onBulkAction = React.useCallback(
    (index: number, trigger: HTMLButtonElement | null) => {
      const action = bulkActions?.[index];
      if (action === undefined) return;
      const confirm = action.confirm ?? action.destructive === true;
      if (confirm === false) {
        void runBulk(index, false);
        return;
      }
      setConfirmError(null);
      setConfirmTarget({ index, trigger });
    },
    [bulkActions, runBulk],
  );

  const clearSelection = React.useCallback(() => {
    setRowSelection({});
    setFailures({});
    setOutcome(null);
  }, []);

  // layout from the container's own width
  const width = useContainerWidth(rootRef);
  const layout =
    cardBreakpoint > 0 && width !== undefined && width < cardBreakpoint ? "cards" : "table";

  const changePage = React.useCallback(
    (page: number) => {
      intent.current = "page";
      setView({ page }, { push: true });
    },
    [setView],
  );
  const changePageSize = React.useCallback(
    (size: number) => {
      intent.current = "page";
      setView({ pageSize: size, page: 1 }, { push: true });
    },
    [setView],
  );
  const onSort = React.useCallback(
    (header: Header<T, unknown>, event: React.MouseEvent) => {
      if (transitioning) return;
      setSortTarget(header.column.id);
      header.column.getToggleSortingHandler()?.(event);
    },
    [transitioning],
  );

  const retryList = React.useCallback(() => {
    void refetch();
  }, [refetch]);
  const retrySchema = React.useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: karniKeys.schema() });
  }, [queryClient]);

  const activeFilters = React.useMemo<ResourceTableActiveFilter[]>(
    () =>
      Object.entries(view.filters).flatMap(([name, value]) => {
        const field = filterFields.find((candidate) => candidate.name === name);
        return field === undefined
          ? []
          : [{ field: name, label: field.label, value: filterWords(field, value) }];
      }),
    [view.filters, filterFields],
  );

  // render
  const loadingNode = (
    <Slots.Loading
      columnCount={
        schema === undefined
          ? SKELETON_COLUMNS + (hasBulkSelect ? 1 : 0) + (hasActions ? 1 : 0)
          : table.getVisibleLeafColumns().length
      }
      rowCount={view.pageSize}
      density={density}
      toolbar={schema === undefined}
      layout={layout}
      selectable={hasBulkSelect}
      actions={hasActions}
    />
  );

  let body: React.ReactNode;
  if (schemaResult.error !== null && schemaResult.error !== undefined) {
    body = (
      <Slots.Error
        error={schemaResult.error}
        context={{ action: "load", resource: plural }}
        onRetry={retrySchema}
      />
    );
  } else if (blocking) {
    body =
      status === 403 ? (
        <Slots.Forbidden resourceLabel={plural} error={list.error} />
      ) : (
        <Slots.Error error={list.error} context={{ action: "view", resource: plural }} />
      );
  } else if (shownData === undefined && (paused || (!online && hasError))) {
    body = <Slots.Offline resourceLabel={plural} hasRows={false} onRetry={retryList} />;
  } else if (schema === undefined || clamping || shownData === undefined) {
    body =
      hasError && !clamping && schema !== undefined ? (
        <Slots.Error
          error={list.error}
          context={{ action: "load", resource: plural }}
          onRetry={retryList}
          retrying={list.isFetching}
        />
      ) : (
        loadingNode
      );
  } else if (rows.length === 0 && !stale) {
    body =
      empty ??
      (activeSearch !== "" || activeFilters.length > 0 ? (
        <Slots.NoResults
          resourceLabel={plural}
          search={activeSearch}
          filters={activeFilters}
          onClearFilters={clearFilters}
        />
      ) : (
        <Slots.NoRecords
          resourceLabel={plural}
          itemLabel={one}
          onCreate={createAllowed ? onCreate : undefined}
          createLabel={createText}
        />
      ));
  } else {
    const dimmed = stale || (slow && transitioning);
    body = (
      <>
        {layout === "cards" ? (
          <CardList
            table={table}
            caption={tableName}
            resourceLabel={plural}
            density={density}
            Card={Slots.RowCard}
            rowLabel={rowLabel}
            useRowLabelAsTitle={getRowLabel !== undefined}
            onRowClick={onRowClick}
            failures={failures}
            columnLabel={columnLabel}
            ordering={view.ordering}
            onOrderingChange={(ordering) => handleSortingChange(orderingToSorting(ordering))}
            busy={transitioning}
            dimmed={dimmed}
            listRef={cardListRef}
          />
        ) : (
          <TableView
            table={table}
            caption={tableName}
            density={density}
            busy={transitioning}
            sortTarget={sortTarget}
            slow={slow}
            onSort={onSort}
            onRowClick={onRowClick}
            failures={failures}
            firstRowIndex={(view.page - 1) * view.pageSize + 1}
            totalCount={count}
            dimmed={dimmed}
            scrollRef={scrollRef}
            keyboardNavigation={keyboardNavigation}
          />
        )}
        {count !== undefined && count > 0 && (
          <Slots.Pagination
            page={view.page}
            pageCount={pageCount}
            totalCount={count}
            hasPrevious={
              transitioning
                ? view.page > 1
                : shownData.previous !== null && shownData.previous !== undefined
            }
            hasNext={
              transitioning
                ? view.page < pageCount
                : shownData.next !== null && shownData.next !== undefined
            }
            onPageChange={changePage}
            pageSize={view.pageSize}
            pageSizeOptions={defaults.pageSizes}
            onPageSizeChange={changePageSize}
            busy={transitioning}
          />
        )}
      </>
    );
  }

  const exportList: readonly ExportFormat[] =
    exportFormats === undefined ? ["csv", "xlsx"] : exportFormats === false ? [] : exportFormats;
  const exportEnabled = exportList.length > 0 && schema?.operations.export !== undefined;
  const dataColumns = table
    .getAllLeafColumns()
    .filter((column) => !isStructural(column.id))
    .map((column) => ({
      id: column.id,
      label: columnLabel(column.id),
      visible: column.getIsVisible(),
    }));

  const showFilterRow =
    schema !== undefined &&
    !blocking &&
    (searchEnabled ||
      filterFields.length > 0 ||
      toolbar !== undefined ||
      exportEnabled ||
      viewOptions ||
      createAllowed);

  const liveText = slow ? `Loading ${plural}…` : announcement;

  return (
    <div ref={rootRef} className={cn("flex w-full min-w-0 flex-col gap-3", className)}>
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {liveText}
      </div>
      {showFilterRow && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <FilterBar
            searchEnabled={searchEnabled}
            searchValue={searchInput}
            onSearchChange={setSearchInput}
            filterFields={filterFields}
            values={view.filters}
            onFilterChange={handleFilterChange}
            className="min-w-64 flex-1"
          />
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {viewOptions && (
              <ViewOptionsMenu
                density={density}
                onDensityChange={changeDensity}
                columns={dataColumns}
                onColumnVisibilityChange={(id, visible) =>
                  setHiddenColumns(
                    visible
                      ? hiddenColumns.filter((hidden) => hidden !== id)
                      : [...hiddenColumns.filter((hidden) => hidden !== id), id],
                  )
                }
              />
            )}
            {exportEnabled && (
              <ExportButtons resource={resource} params={listParams} formats={exportList} />
            )}
            {toolbar}
            {createAllowed && (
              <Button size="sm" onClick={onCreate}>
                <PlusIcon className="h-4 w-4" />
                {createText}
              </Button>
            )}
          </div>
        </div>
      )}
      {!online && shownData !== undefined && (
        <Slots.Offline resourceLabel={plural} hasRows onRetry={retryList} />
      )}
      {hasError && !blocking && !clamping && shownData !== undefined && online && (
        <Slots.RefetchError
          error={list.error}
          context={{ action: "load", resource: plural }}
          onRetry={retryList}
          retrying={list.isFetching}
        />
      )}
      {hasBulkSelect && selectedIds.length > 0 && (
        <Slots.BulkActions
          selectedIds={selectedIds}
          bulkActions={bulkActions}
          onClear={clearSelection}
          onAction={onBulkAction}
          runningIndex={runningIndex}
          outcome={outcome}
          pageRowCount={rows.length}
          allPageRowsSelected={rows.length > 0 && table.getIsAllPageRowsSelected()}
          totalCount={count}
          resourceLabel={plural}
        />
      )}
      {body}
      {footer}
      {hasBulkSelect && (
        <BulkConfirm
          target={confirmTarget}
          actions={bulkActions}
          count={selectedIds.length}
          one={one}
          plural={plural}
          pending={confirmTarget !== null && runningIndex === confirmTarget.index}
          error={confirmError}
          onConfirm={(index) => void runBulk(index, true)}
          onCancel={() => {
            setConfirmTarget(null);
            setConfirmError(null);
          }}
          fallbackFocus={fallbackFocus}
        />
      )}
      {enableDelete === true && (
        <RowDeleteDialog
          resource={resource}
          target={deleteTarget}
          rowLabel={rowLabel}
          onClose={() => setDeleteTarget(null)}
          onDeleted={(label) => {
            setAnnouncement(`Deleted “${label}”.`);
            setDeleteTarget(null);
          }}
          fallbackFocus={fallbackFocus}
        />
      )}
    </div>
  );
}

/** The confirm question for a bulk action, worded from its label and the count. */
function BulkConfirm(props: {
  target: ConfirmTarget | null;
  actions: ReadonlyArray<BulkAction>;
  count: number;
  one: string;
  plural: string;
  pending: boolean;
  error: unknown;
  onConfirm: (index: number) => void;
  onCancel: () => void;
  fallbackFocus: () => HTMLElement | null;
}): React.ReactElement {
  const { target, actions, one, plural, pending, error, onConfirm, onCancel } = props;
  // The dialog closes after `target` is cleared (and the selection with it):
  // keep the wording and the focus target of the last question.
  const last = React.useRef({ target, count: props.count });
  if (target !== null) last.current = { target, count: props.count };
  const shown = last.current.target;
  const count = last.current.count;
  const action = shown === null ? undefined : actions[shown.index];
  const label = action === undefined ? undefined : textOf(action.label);
  const custom = typeof action?.confirm === "object" ? action.confirm : undefined;
  const what = `${count} ${count === 1 ? one : plural}`;
  return (
    <ConfirmDialog
      open={target !== null}
      title={custom?.title ?? (label !== undefined ? `${label} ${what}?` : `Apply to ${what}?`)}
      description={
        custom?.description ??
        (action?.destructive === true
          ? `This applies to all ${what} you selected, and can't be undone.`
          : `This applies to all ${what} you selected.`)
      }
      confirmLabel={custom?.confirmLabel ?? (label !== undefined ? `${label} ${what}` : "Continue")}
      pendingLabel={action?.pendingLabel}
      destructive={action?.destructive === true}
      pending={pending}
      error={error === null ? undefined : error}
      errorContext={{ action: (label ?? "change").toLowerCase(), resource: what }}
      onConfirm={() => {
        if (target !== null) onConfirm(target.index);
      }}
      onCancel={onCancel}
      returnFocus={() => {
        const trigger = last.current.target?.trigger;
        return trigger !== null && trigger !== undefined && trigger.isConnected
          ? trigger
          : props.fallbackFocus();
      }}
    />
  );
}
