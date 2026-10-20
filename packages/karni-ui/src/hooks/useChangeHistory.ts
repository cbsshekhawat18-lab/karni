/**
 * useChangeHistory — one row's field-level change history (karni.audit, ADR 0002 P4).
 *
 * `useChangeHistory("prices", id)` fetches `GET /<resource>/<id>/history/`,
 * the paginated list a `BaseViewSet` serves for models that opt in with
 * `class Karni: audit = True`. The backend answers 404 for the rest, and
 * hides from each entry's `diff` the fields the requesting role may not see,
 * so the hook renders whatever it is given without filtering.
 */
import { useQuery, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";
import { detailPath } from "./params";

export type ChangeAction = "create" | "update" | "delete" | "restore";

export interface ChangeLogEntry {
  id: number;
  timestamp: string;
  actor: { id: string | number; email?: string } | null;
  action: ChangeAction;
  /** `{ field: [old, new] }`; a redacted field carries `"[redacted]"` on both sides. */
  diff: Record<string, [unknown, unknown]>;
  fields_changed: string[];
}

export interface ChangeHistoryPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: ChangeLogEntry[];
}

export interface ChangeHistoryParams {
  /** Entries per page (the backend caps it). Default: the API's page size. */
  pageSize?: number;
  page?: number;
}

/** The query key of one row's change history. */
export function changeHistoryKey(
  resource: string,
  id: string | number,
  params?: ChangeHistoryParams,
): readonly unknown[] {
  return [...karniKeys.resource(resource), "history", String(id), params ?? {}] as const;
}

/** Fetches one row's field-level change history (`GET /<resource>/<id>/history/`) for models with `audit = True`. */
export function useChangeHistory(
  resource: string,
  id: string | number,
  params?: ChangeHistoryParams,
  options?: Omit<UseQueryOptions<ChangeHistoryPage>, "queryKey" | "queryFn">,
): UseQueryResult<ChangeHistoryPage> {
  const client = useKarniClient();
  return useQuery<ChangeHistoryPage>({
    ...options,
    queryKey: changeHistoryKey(resource, id, params),
    queryFn: ({ signal }) =>
      client.request<ChangeHistoryPage>(`${detailPath(resource, id)}history/`, {
        query: { page_size: params?.pageSize, page: params?.page },
        signal,
      }),
  });
}
