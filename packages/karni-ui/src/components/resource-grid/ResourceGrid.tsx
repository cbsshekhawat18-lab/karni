/**
 * Experimental. ResourceGrid: a resource's rows as cards, with search, sort and paging.
 *
 * A catalogue is cards, not a table: products, listings, courses, rooms or
 * datasets, each with a picture, a title and what it costs or holds. The grid
 * reads one page of `GET /<resource>/` (`useResourceList`) and renders each
 * row with `renderCard`. It owns the plumbing every catalogue repeats: a
 * search box, a sort menu, filters the page passes in, paging, and the
 * loading, empty and error states.
 *
 *   <ResourceGrid<Product>
 *     resource="products"
 *     filters={{ categories: categoryId }}
 *     sortOptions={[{ value: "name", label: "Name" }, { value: "-created_at", label: "Newest" }]}
 *     renderCard={(product) => <ProductCard product={product} />}
 *   />
 *
 * Each of `search`, `ordering` and `page` is controlled when its value is
 * passed (keep it in the URL with your router) and kept inside the grid when
 * it is not. A change of search, sort or filters goes back to page 1.
 *
 * Override / escape hatch: `slots` replaces the Loading, Empty and Error
 * states and the Pagination; `toolbar` adds controls next to search and sort;
 * `query` passes TanStack Query options (`placeholderData`, `staleTime`).
 */
import * as React from "react";
import { keepPreviousData } from "@tanstack/react-query";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";
import { Select, type SelectOption } from "../primitives/select";
import { Skeleton } from "../primitives/skeleton";
import { EmptyState } from "../empty-state/empty-state";
import { ErrorState, type ErrorSlotProps } from "../../states/ErrorState";
import { useResourceList } from "../../hooks/useResourceList";
import type { FilterValue } from "../../hooks/types";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";

registerComponentRole("resource-grid", "ResourceGrid");

/** Experimental. One choice of the sort menu: an `ordering` value and its label. */
export interface ResourceGridSortOption {
  /** What the list endpoint takes as `?ordering=` (`-created_at`, `name`). */
  value: string;
  label: string;
}

/** Experimental. What the `Pagination` slot receives. */
export interface ResourceGridPaginationProps {
  page: number;
  pages: number;
  count: number;
  onPageChange: (page: number) => void;
  /** True while the next page loads. */
  busy: boolean;
}

/** Experimental. What the `Empty` slot receives. */
export interface ResourceGridEmptyProps {
  /** True when a search or a filter is on: nothing matches, not nothing at all. */
  filtered: boolean;
  onClear?: () => void;
}

/** Experimental. What the `Loading` slot receives. */
export interface ResourceGridLoadingProps {
  /** How many cards a page holds: draw as many placeholders. */
  count: number;
}

/** Experimental. The replaceable parts of ResourceGrid. */
export interface ResourceGridSlots {
  Loading: React.ComponentType<ResourceGridLoadingProps>;
  Empty: React.ComponentType<ResourceGridEmptyProps>;
  Error: React.ComponentType<ErrorSlotProps>;
  Pagination: React.ComponentType<ResourceGridPaginationProps>;
}

/** Experimental. Props of ResourceGrid. */
export interface ResourceGridProps<T> {
  /** The router prefix of the resource (`products`). */
  resource: string;
  /** One card per row. */
  renderCard: (row: T) => React.ReactNode;
  /** A row's key. Default: its `id`. */
  getRowKey?: (row: T) => string;
  /** Fixed list parameters the page decides: a category, a price range, `featured`. */
  filters?: Record<string, FilterValue>;
  /** Relation paths to expand. */
  expand?: readonly string[];
  /** Cards per page. Default 12. */
  pageSize?: number;
  /** Show the search box. Default true. */
  searchable?: boolean;
  /** The search box's label. Default "Search". */
  searchLabel?: string;
  /** The sort menu's choices. None: no menu, the endpoint's own order. */
  sortOptions?: readonly ResourceGridSortOption[];
  /** The search text (controlled). */
  search?: string;
  onSearchChange?: (search: string) => void;
  /** The `ordering` value (controlled). Default: the first sort option. */
  ordering?: string;
  onOrderingChange?: (ordering: string) => void;
  /** The 1-based page (controlled). */
  page?: number;
  onPageChange?: (page: number) => void;
  /** More controls in the toolbar, after search and sort. */
  toolbar?: React.ReactNode;
  /** The grid's name for assistive technology, and the noun of the count line. */
  label?: string;
  /** Classes of the card list (the grid's columns). */
  gridClassName?: string;
  className?: string;
  slots?: Partial<ResourceGridSlots>;
}

const SEARCH_DELAY_MS = 300;

function DefaultLoading({ count }: ResourceGridLoadingProps): React.ReactElement {
  return (
    <ul aria-hidden="true" className={GRID_CLASSES}>
      {Array.from({ length: count }, (_unused, index) => (
        <li key={index} className="space-y-3 rounded-lg border border-border p-3">
          <Skeleton className="aspect-square w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/3" />
        </li>
      ))}
    </ul>
  );
}

function DefaultEmpty({ filtered, onClear }: ResourceGridEmptyProps): React.ReactElement {
  return (
    <EmptyState
      title={filtered ? "Nothing matches" : "Nothing here yet"}
      description={
        filtered
          ? "Try another search, or clear the filters."
          : "Come back soon: new things arrive."
      }
      action={
        filtered && onClear ? (
          <Button variant="outline" onClick={onClear}>
            Clear the search
          </Button>
        ) : undefined
      }
    />
  );
}

function DefaultError(props: ErrorSlotProps): React.ReactElement {
  return <ErrorState {...props} />;
}

function DefaultPagination({
  page,
  pages,
  onPageChange,
  busy,
}: ResourceGridPaginationProps): React.ReactElement | null {
  if (pages <= 1) return null;
  return (
    <nav aria-label="Pages" className="flex items-center justify-between gap-2">
      <Button variant="outline" disabled={page <= 1 || busy} onClick={() => onPageChange(page - 1)}>
        Previous
      </Button>
      <span className="text-sm text-muted-foreground">
        Page {page} of {pages}
      </span>
      <Button
        variant="outline"
        disabled={page >= pages || busy}
        onClick={() => onPageChange(page + 1)}
      >
        Next
      </Button>
    </nav>
  );
}

/** Experimental. Karni's own slots, to wrap one instead of rewriting it. */
export const defaultResourceGridSlots: ResourceGridSlots = {
  Loading: DefaultLoading,
  Empty: DefaultEmpty,
  Error: DefaultError,
  Pagination: DefaultPagination,
};

const GRID_CLASSES = "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

/** A value that is controlled when `given` is not undefined, else kept here. */
function useMaybeControlled<V>(
  given: V | undefined,
  initial: V,
  onChange?: (value: V) => void,
): [V, (value: V) => void] {
  const [own, setOwn] = React.useState<V>(given ?? initial);
  const value = given ?? own;
  const set = React.useCallback(
    (next: V) => {
      setOwn(next);
      onChange?.(next);
    },
    [onChange],
  );
  return [value, set];
}

function rowKey(row: unknown): string {
  if (row && typeof row === "object" && "id" in row) return String((row as { id: unknown }).id);
  return JSON.stringify(row);
}

/** Experimental. A resource's rows as cards, with search, sort, filters and paging. */
export function ResourceGrid<T>(props: ResourceGridProps<T>): React.ReactElement {
  const {
    resource,
    renderCard,
    getRowKey = rowKey,
    filters,
    expand,
    pageSize = 12,
    searchable = true,
    searchLabel = "Search",
    sortOptions = [],
    toolbar,
    label = "Results",
    gridClassName,
    className,
  } = props;
  const Slots: ResourceGridSlots = { ...defaultResourceGridSlots, ...props.slots };
  const [search, setSearch] = useMaybeControlled(props.search, "", props.onSearchChange);
  const [ordering, setOrdering] = useMaybeControlled(
    props.ordering,
    sortOptions[0]?.value ?? "",
    props.onOrderingChange,
  );
  const [page, setPage] = useMaybeControlled(props.page, 1, props.onPageChange);
  const [draft, setDraft] = React.useState(search);
  const searchId = React.useId();
  const sortId = React.useId();

  React.useEffect(() => setDraft(search), [search]);
  React.useEffect(() => {
    if (draft === search) return undefined;
    const timer = window.setTimeout(() => {
      setSearch(draft);
      setPage(1);
    }, SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [draft, search, setSearch, setPage]);

  const filterKey = JSON.stringify(filters ?? {});
  const firstFilters = React.useRef(filterKey);
  React.useEffect(() => {
    if (firstFilters.current === filterKey) return;
    firstFilters.current = filterKey;
    setPage(1);
  }, [filterKey, setPage]);

  const list = useResourceList<T>(
    resource,
    {
      page,
      pageSize,
      search: search || undefined,
      ordering: ordering || undefined,
      filters,
      expand,
    },
    { placeholderData: keepPreviousData },
  );
  const count = list.data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(count / pageSize));
  const rows = list.data?.results ?? [];
  const filtered = search !== "";
  const sortChoices: SelectOption[] = sortOptions.map((option) => ({
    value: option.value,
    label: option.label,
  }));

  let body: React.ReactNode;
  if (list.isPending) {
    body = <Slots.Loading count={pageSize} />;
  } else if (list.isError && !list.data) {
    body = (
      <Slots.Error
        error={list.error}
        context={{ action: "view", resource }}
        onRetry={() => void list.refetch()}
        retrying={list.isFetching}
      />
    );
  } else if (rows.length === 0) {
    body = (
      <Slots.Empty
        filtered={filtered}
        onClear={
          filtered
            ? () => {
                setDraft("");
                setSearch("");
                setPage(1);
              }
            : undefined
        }
      />
    );
  } else {
    body = (
      <ul aria-label={label} className={cn(GRID_CLASSES, gridClassName)}>
        {rows.map((row) => (
          <li key={getRowKey(row)} className="flex">
            {renderCard(row)}
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div className={cn("space-y-4", className)} aria-busy={list.isFetching}>
      {searchable || sortChoices.length > 0 || toolbar ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
          {searchable ? (
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <Label htmlFor={searchId}>{searchLabel}</Label>
              <Input
                id={searchId}
                type="search"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    setSearch(draft);
                    setPage(1);
                  }
                }}
              />
            </div>
          ) : null}
          {sortChoices.length > 0 ? (
            <div className="flex flex-col gap-1 sm:w-56">
              <Label id={sortId}>Sort by</Label>
              <Select
                aria-labelledby={sortId}
                value={ordering}
                options={sortChoices}
                onValueChange={(value) => {
                  setOrdering(value ?? sortChoices[0]?.value ?? "");
                  setPage(1);
                }}
              />
            </div>
          ) : null}
          {toolbar}
        </div>
      ) : null}
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {list.data ? `${count} ${count === 1 ? "result" : "results"}` : ""}
      </p>
      {body}
      {list.data && rows.length > 0 ? (
        <Slots.Pagination
          page={page}
          pages={pages}
          count={count}
          onPageChange={setPage}
          busy={list.isFetching}
        />
      ) : null}
    </div>
  );
}
