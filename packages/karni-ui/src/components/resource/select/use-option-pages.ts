/**
 * ResourceSelect's data: option pages and the rows behind preselected ids.
 *
 * Options come a page at a time from the related resource's list endpoint,
 * following the API's own `next` link (page-number and cursor pagination
 * alike; only its query string is used, so a proxy-rewritten host never
 * matters). Nothing ever fetches every row.
 *
 * Preselected ids resolve in ONE list request when the list documents an
 * id-list filter (`?id__in=1,2,3`, django-filter's `in` lookup; a project
 * adds it with `filterset_fields = {"id": ["exact", "in"]}`), otherwise
 * through each id's detail endpoint, in parallel.
 *
 * Internal to @karni/ui.
 */
import {
  keepPreviousData,
  useInfiniteQuery,
  useQueries,
  type UseInfiniteQueryResult,
  type InfiniteData,
} from "@tanstack/react-query";
import { karniKeys } from "../../../hooks/keys";
import { buildListQuery, detailPath, listPath } from "../../../hooks/params";
import type { Paginated, ResourceListParams } from "../../../hooks/types";
import { useResourceList } from "../../../hooks/useResourceList";
import { useKarniClient } from "../../../schema/provider";

export type OptionRow = Record<string, unknown>;

/** The query string of one page request. */
type PageQuery = Record<string, string | readonly string[]>;

export interface OptionPage {
  /** Undefined when the API does not count (cursor pagination). */
  count?: number;
  next: string | null;
  results: OptionRow[];
}

/** `next` → its query string (`?page=2&search=x`, `?cursor=...`). */
export function pageQueryOf(next: string): PageQuery {
  const url = new URL(next, "http://karni.invalid");
  const query: Record<string, string | string[]> = {};
  for (const key of new Set(url.searchParams.keys())) {
    const values = url.searchParams.getAll(key);
    query[key] = values.length === 1 ? (values[0] ?? "") : values;
  }
  return query;
}

/** A DRF page, or a plain list (an `Unpaginated` viewset), as one page. */
function asPage(body: unknown): OptionPage {
  if (Array.isArray(body)) return { count: body.length, next: null, results: body as OptionRow[] };
  const page = (body ?? {}) as Partial<Paginated<OptionRow>> & { count?: unknown };
  return {
    count: typeof page.count === "number" ? page.count : undefined,
    next: typeof page.next === "string" && page.next !== "" ? page.next : null,
    results: Array.isArray(page.results) ? page.results : [],
  };
}

export interface OptionPagesInput {
  resource: string;
  /** The (debounced) search term; "" for none. */
  search: string;
  filter?: Record<string, string | number | boolean>;
  pageSize?: number;
  enabled: boolean;
}

export type OptionPagesResult = UseInfiniteQueryResult<InfiniteData<OptionPage, PageQuery | null>>;

/** Pages of options, each fetched on demand; the previous term's rows stay while a new search loads. */
export function useOptionPages({
  resource,
  search,
  filter,
  pageSize,
  enabled,
}: OptionPagesInput): OptionPagesResult {
  const client = useKarniClient();
  const params: ResourceListParams = { page: 1 };
  if (pageSize !== undefined) params.pageSize = pageSize;
  if (search !== "") params.search = search;
  if (filter !== undefined) params.filters = filter;
  return useInfiniteQuery({
    queryKey: [...karniKeys.list(resource, params), "options"],
    queryFn: async ({ pageParam, signal }) =>
      asPage(
        await client.request<unknown>(listPath(resource), {
          query: pageParam ?? buildListQuery(params),
          signal,
        }),
      ),
    initialPageParam: null as PageQuery | null,
    getNextPageParam: (last) => (last.next !== null ? pageQueryOf(last.next) : undefined),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export interface SelectedRows {
  /** Rows found for the requested ids, by String(id). */
  rows: Record<string, OptionRow>;
  /** Ids that could not be loaded (deleted, hidden from the role, or the request failed). */
  failed: ReadonlySet<string>;
  /** Ids still loading. */
  loading: ReadonlySet<string>;
}

const NOTHING: ReadonlySet<string> = new Set();

/** Loads the rows behind ids the options have not shown yet. */
export function useSelectedRows(
  resource: string,
  ids: ReadonlyArray<string | number>,
  options: { idsFilter?: string; enabled: boolean },
): SelectedRows {
  const client = useKarniClient();
  const { idsFilter, enabled } = options;
  const keys = ids.map(String);
  const batched = idsFilter !== undefined;

  const batch = useResourceList<OptionRow>(
    resource,
    {
      filters: { [idsFilter ?? "id__in"]: keys.join(",") },
      pageSize: Math.max(keys.length, 1),
    },
    { enabled: enabled && batched && keys.length > 0, retry: false },
  );

  const singles = useQueries({
    queries: (batched ? [] : keys).map((key) => ({
      queryKey: karniKeys.detail(resource, key),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        client.request<OptionRow>(detailPath(resource, key), { signal }),
      enabled,
      retry: false,
    })),
  });

  const rows: Record<string, OptionRow> = {};
  if (keys.length === 0) return { rows, failed: NOTHING, loading: NOTHING };
  const failed = new Set<string>();
  const loading = new Set<string>();
  if (batched) {
    const results = batch.data?.results;
    if (results !== undefined) {
      for (const row of results) rows[String(row["id"])] = row;
      for (const key of keys) if (!(key in rows)) failed.add(key);
    } else if (batch.error != null) {
      for (const key of keys) failed.add(key);
    } else {
      for (const key of keys) loading.add(key);
    }
  } else {
    keys.forEach((key, index) => {
      const query = singles[index];
      if (query?.data !== undefined) rows[key] = query.data;
      else if (query?.error != null) failed.add(key);
      else loading.add(key);
    });
  }
  return { rows, failed, loading };
}
