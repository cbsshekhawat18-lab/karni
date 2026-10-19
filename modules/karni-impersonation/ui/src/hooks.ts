/**
 * Hooks over the impersonation API, on @karni/ui's client, auth and query keys.
 *
 * - `useImpersonation()` — `GET /impersonation-sessions/current/`: the session
 *   this user is in, or null;
 * - `useStartImpersonation()` — `POST …/start/`; in JWT mode the tokens the
 *   backend returns are adopted through `useAuth().adoptTokens`, in session
 *   mode `/me/` is re-synced; every resource query is invalidated either way;
 * - `useStopImpersonation()` — `POST …/stop/`, the mirror image.
 */
import { karniKeys, useAuth, useKarniClient } from "@karni/ui";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import type { CurrentResponse, SessionResponse } from "./types";

export const RESOURCE = "impersonation-sessions";

export function impersonationKey(): readonly unknown[] {
  return [...karniKeys.resource(RESOURCE), "current"] as const;
}

export interface UseImpersonationOptions {
  /** `false` (default) = fetch once; a number = refetch every N milliseconds (watch the clock). */
  poll?: false | number;
}

export function useImpersonation(
  options?: UseImpersonationOptions,
): UseQueryResult<CurrentResponse> {
  const client = useKarniClient();
  const poll = options?.poll ?? false;
  return useQuery<CurrentResponse>({
    queryKey: impersonationKey(),
    queryFn: ({ signal }) => client.request<CurrentResponse>(`/${RESOURCE}/current/`, { signal }),
    refetchInterval: poll === false ? false : poll,
  });
}

export interface StartInput {
  /** The user to act as: id or email. */
  user: string;
  reason?: string;
}

function useAdoption(): (response: SessionResponse) => Promise<void> {
  const auth = useAuth();
  const queryClient = useQueryClient();
  return async (response) => {
    await auth.adoptTokens(response.access ?? null, response.refresh ?? null);
    queryClient.removeQueries({
      queryKey: ["karni"],
      predicate: (query) => query.queryKey[1] !== "$schema",
    });
    await queryClient.invalidateQueries({ queryKey: impersonationKey() });
  };
}

export function useStartImpersonation(): UseMutationResult<SessionResponse, unknown, StartInput> {
  const client = useKarniClient();
  const adopt = useAdoption();
  return useMutation<SessionResponse, unknown, StartInput>({
    mutationFn: ({ user, reason }) =>
      client.request<SessionResponse>(`/${RESOURCE}/start/`, {
        method: "POST",
        body: { user, reason: reason ?? "" },
      }),
    onSuccess: (response) => adopt(response),
  });
}

export function useStopImpersonation(): UseMutationResult<SessionResponse, unknown, undefined> {
  const client = useKarniClient();
  const adopt = useAdoption();
  return useMutation<SessionResponse, unknown, undefined>({
    mutationFn: () =>
      client.request<SessionResponse>(`/${RESOURCE}/stop/`, { method: "POST", body: {} }),
    onSuccess: (response) => adopt(response),
  });
}
