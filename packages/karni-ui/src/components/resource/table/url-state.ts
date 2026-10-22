/**
 * ResourceTable's view state (page, page size, ordering, search, filters) in
 * the URL, so a view can be shared and Back returns to the previous one.
 *
 * The table reads and writes its own query keys through a
 * `ResourceTableStateStore`. The default store uses `window.history` and
 * listens to `popstate`, so it needs no router. A project on a router plugs
 * its search params in with its own store (see the README). Keys are
 * namespaced (`events.page=2`), and the reserved names are DRF's own
 * (`page`, `page_size`, `ordering`, `search`), so a filter field can never
 * collide with them. A value equal to the table's default is left out of the
 * URL. Pinned `params` are never URL state.
 */
import * as React from "react";
import type { FilterValue } from "../../../hooks/types";
import type { FieldDef } from "../../../schema/types";

/**
 * Where a table keeps its view state. The table only touches its own
 * (namespaced) keys.
 *
 * An adapter for a router reads the router's current search params in
 * `read`, navigates in `write`, and either calls the `subscribe` listener
 * when the params change or simply passes a new store object on each change
 * (the table re-reads whenever the store changes).
 */
export interface ResourceTableStateStore {
  /** Every current query value by key. */
  read(): Readonly<Record<string, string>>;
  /**
   * Merge `changes` into the URL (`null` removes a key). `push` adds a
   * history entry (page, sort, filter changes). Otherwise the current entry
   * is replaced (a search refined while typing, a page clamped).
   */
  write(changes: Readonly<Record<string, string | null>>, options: { push: boolean }): void;
  /** Call `onChange` when the values change outside the table. Returns an unsubscribe. */
  subscribe(onChange: () => void): () => void;
}

const historyListeners = new Set<() => void>();

/**
 * The default store: the browser's URL through `window.history`
 * (`pushState` / `replaceState`, `popstate` for Back and Forward). Other
 * query parameters and the hash are kept.
 */
export function createHistoryStateStore(): ResourceTableStateStore {
  return {
    read() {
      if (typeof window === "undefined") return {};
      return Object.fromEntries(new URLSearchParams(window.location.search));
    },
    write(changes, { push }) {
      if (typeof window === "undefined") return;
      const url = new URL(window.location.href);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null) url.searchParams.delete(key);
        else url.searchParams.set(key, value);
      }
      if (url.href === window.location.href) return;
      if (push) window.history.pushState(window.history.state, "", url);
      else window.history.replaceState(window.history.state, "", url);
      // Other tables on the page re-read their own keys (pushState fires no event).
      for (const listener of [...historyListeners]) listener();
    },
    subscribe(onChange) {
      historyListeners.add(onChange);
      window.addEventListener("popstate", onChange);
      return () => {
        historyListeners.delete(onChange);
        window.removeEventListener("popstate", onChange);
      };
    },
  };
}

const defaultStore = createHistoryStateStore();

/** The view a table shows: what the URL holds for it. */
export interface TableView {
  page: number;
  pageSize: number;
  /** DRF ordering ("-starts_at,title"), where "" is "no ordering". */
  ordering: string;
  search: string;
  filters: Readonly<Record<string, FilterValue>>;
}

export interface TableViewDefaults {
  pageSize: number;
  ordering: string;
  /** Page sizes a URL may ask for. Anything else falls back to the default. */
  pageSizes: readonly number[];
}

const RESERVED = new Set(["page", "page_size", "ordering", "search"]);

function prefixed(namespace: string, key: string): string {
  return namespace === "" ? key : `${namespace}.${key}`;
}

/** Encodes one filter value for the URL (arrays comma-joined). */
export function encodeFilter(value: FilterValue): string | null {
  if (value === null || value === undefined) return null;
  if (Array.isArray(value)) return value.length === 0 ? null : value.map(String).join(",");
  return String(value);
}

function relationId(raw: string, field: FieldDef): string | number {
  return field.relationValueType === "integer" && /^-?\d+$/.test(raw) ? Number(raw) : raw;
}

/** Decodes a URL value back to the type the filter control and the API expect. */
export function decodeFilter(raw: string, field: FieldDef): FilterValue {
  if (field.kind === "boolean") return raw === "true" ? true : raw === "false" ? false : undefined;
  if (field.kind === "enum") {
    return (field.enumValues ?? []).find((member) => String(member) === raw);
  }
  if (field.kind === "relation" && field.relation !== undefined) {
    if (field.relation.many) {
      const ids = raw
        .split(",")
        .filter((part) => part.length > 0)
        .map((part) => relationId(part, field));
      return ids.length > 0 ? ids : undefined;
    }
    return relationId(raw, field);
  }
  return raw;
}

function positiveInt(raw: string | undefined): number | undefined {
  if (raw === undefined || !/^\d+$/.test(raw)) return undefined;
  const value = Number(raw);
  return value >= 1 ? value : undefined;
}

/** The table's own entries of the store, as a stable string (a snapshot). */
function snapshotOf(store: ResourceTableStateStore, namespace: string): string {
  const prefix = namespace === "" ? "" : `${namespace}.`;
  const own = Object.entries(store.read())
    .filter(([key]) => (prefix === "" ? true : key.startsWith(prefix)))
    .map(([key, value]) => [key.slice(prefix.length), value] as const)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return JSON.stringify(own);
}

function viewFromSnapshot(
  snapshot: string,
  defaults: TableViewDefaults,
  filterFields: readonly FieldDef[],
): TableView {
  const entries = new Map(JSON.parse(snapshot) as Array<[string, string]>);
  const size = positiveInt(entries.get("page_size"));
  const filters: Record<string, FilterValue> = {};
  for (const field of filterFields) {
    const raw = entries.get(field.name);
    if (raw === undefined || RESERVED.has(field.name)) continue;
    const value = decodeFilter(raw, field);
    if (value !== undefined) filters[field.name] = value;
  }
  return {
    page: positiveInt(entries.get("page")) ?? 1,
    pageSize: size !== undefined && defaults.pageSizes.includes(size) ? size : defaults.pageSize,
    ordering: entries.get("ordering") ?? defaults.ordering,
    search: entries.get("search") ?? "",
    filters,
  };
}

function isCleared(value: FilterValue): boolean {
  return (
    value === null ||
    value === undefined ||
    value === "" ||
    (Array.isArray(value) && value.length === 0)
  );
}

/** Drops cleared filters so "no filter" has one representation. */
export function compactFilters(
  filters: Readonly<Record<string, FilterValue>>,
): Record<string, FilterValue> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => !isCleared(value)));
}

export type SetTableView = (patch: Partial<TableView>, options: { push: boolean }) => void;

export interface UseTableViewOptions {
  /** False keeps the view in component state only (the URL is untouched). */
  syncUrl: boolean;
  /** Where the URL state lives. Default: `window.history`. */
  store?: ResourceTableStateStore;
  namespace: string;
  defaults: TableViewDefaults;
  /** The fields the filter bar offers: only these are read from the URL. */
  filterFields: readonly FieldDef[];
}

const noSubscription = (): (() => void) => () => undefined;

/** The table's view state, from the URL (or component state) with a setter. */
export function useTableView(options: UseTableViewOptions): [TableView, SetTableView] {
  const { syncUrl, namespace, defaults, filterFields } = options;
  const store = options.store ?? defaultStore;

  const subscribe = React.useCallback(
    (onChange: () => void) => (syncUrl ? store.subscribe(onChange) : noSubscription()),
    [store, syncUrl],
  );
  const getSnapshot = React.useCallback(
    () => (syncUrl ? snapshotOf(store, namespace) : "[]"),
    [store, namespace, syncUrl],
  );
  const snapshot = React.useSyncExternalStore(subscribe, getSnapshot, () => "[]");

  const [local, setLocal] = React.useState<TableView>(() => ({
    page: 1,
    pageSize: defaults.pageSize,
    ordering: defaults.ordering,
    search: "",
    filters: {},
  }));

  const fromUrl = React.useMemo(
    () => viewFromSnapshot(snapshot, defaults, filterFields),
    [snapshot, defaults, filterFields],
  );
  const view = syncUrl ? fromUrl : local;

  const viewRef = React.useRef(view);
  viewRef.current = view;

  const setView = React.useCallback<SetTableView>(
    (patch, { push }) => {
      const next: TableView = {
        ...viewRef.current,
        ...patch,
        filters: compactFilters(patch.filters ?? viewRef.current.filters),
      };
      // Two updates in one event (search settles while a filter changes) compose.
      viewRef.current = next;
      if (!syncUrl) {
        setLocal(next);
        return;
      }
      const changes: Record<string, string | null> = {
        [prefixed(namespace, "page")]: next.page === 1 ? null : String(next.page),
        [prefixed(namespace, "page_size")]:
          next.pageSize === defaults.pageSize ? null : String(next.pageSize),
        [prefixed(namespace, "ordering")]:
          next.ordering === defaults.ordering ? null : next.ordering,
        [prefixed(namespace, "search")]: next.search === "" ? null : next.search,
      };
      for (const field of filterFields) {
        if (RESERVED.has(field.name)) continue;
        changes[prefixed(namespace, field.name)] = encodeFilter(next.filters[field.name]);
      }
      store.write(changes, { push });
    },
    [store, syncUrl, namespace, defaults, filterFields],
  );

  return [view, setView];
}
