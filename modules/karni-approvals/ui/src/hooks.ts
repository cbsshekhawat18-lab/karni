/**
 * Hooks over the pending-changes API, on @karni/ui's client and query keys.
 *
 * - `usePendingChanges(params)` — the queue (`GET /pending-changes/`), pending by default;
 * - `usePendingCount(options)` — `GET /pending-changes/count/`, optionally polling;
 * - `useDecidePendingChange()` — the approve/reject mutation; it invalidates the
 *   resource's queries and the count so queues and badges refresh.
 */
import { karniKeys, useKarniClient, useResourceList } from "@karni/ui";
import type { Paginated, ResourceListParams } from "@karni/ui";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import type { PendingChange, PendingCount } from "./types";

export const RESOURCE = "pending-changes";

export function pendingCountKey(): readonly unknown[] {
  return [...karniKeys.resource(RESOURCE), "count"] as const;
}

export function usePendingChanges(
  params?: ResourceListParams,
): UseQueryResult<Paginated<PendingChange>> {
  const effective: ResourceListParams = {
    pageSize: 25,
    ...params,
    filters: { status: "pending", ...params?.filters },
  };
  return useResourceList<PendingChange>(RESOURCE, effective);
}

export interface UsePendingCountOptions {
  /** `false` (default) = fetch once; a number = refetch every N milliseconds. */
  poll?: false | number;
}

export function usePendingCount(options?: UsePendingCountOptions): UseQueryResult<PendingCount> {
  const client = useKarniClient();
  const poll = options?.poll ?? false;
  return useQuery<PendingCount>({
    queryKey: pendingCountKey(),
    queryFn: ({ signal }) => client.request<PendingCount>(`/${RESOURCE}/count/`, { signal }),
    refetchInterval: poll === false ? false : poll,
  });
}

export interface DecideInput {
  id: string;
  verdict: "approve" | "reject";
  reason?: string;
}

export function useDecidePendingChange(): UseMutationResult<PendingChange, unknown, DecideInput> {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  return useMutation<PendingChange, unknown, DecideInput>({
    mutationFn: ({ id, verdict, reason }) =>
      client.request<PendingChange>(`/${RESOURCE}/${encodeURIComponent(id)}/${verdict}/`, {
        method: "POST",
        body: { reason: reason ?? "" },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: karniKeys.resource(RESOURCE) });
    },
  });
}
