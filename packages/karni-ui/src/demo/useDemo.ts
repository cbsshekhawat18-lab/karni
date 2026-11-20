/**
 * Experimental. What a demo-mode server says about itself: `GET /demo/`
 * (Django's `karni.demo`, mounted at `api/demo/`). The demo accounts with what
 * each can do, how often the data resets, and when the next reset is due.
 *
 * A server that is not a demo answers 404 (`E954`) or has no such route. That
 * is an answer, not a hiccup: the hook does not retry a 4xx, and `data` stays
 * undefined, so `DemoNotice` renders nothing.
 *
 * Escape hatch: `options` forwards every TanStack Query option except
 * `queryKey`/`queryFn` (e.g. `enabled`, `staleTime`, `retry`).
 */
import {
  useQuery,
  useQueryClient,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { KarniApiError } from "../schema/client";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "../hooks/keys";

/** Experimental. One demo account, as the server lists it. */
export interface DemoAccount {
  /** The login (an email) to sign in with. */
  login: string;
  /** The password: demo passwords are public on purpose. */
  password: string;
  /** A short name for the account, for example "Customer". */
  label: string;
  /** What the account can do, in a sentence. Empty when the project gave none. */
  can: string;
  /** The role names the account holds. */
  roles: string[];
}

/** Experimental. The body of `GET /demo/`. */
export interface DemoInfo {
  enabled: true;
  accounts: DemoAccount[];
  /** Hours between two resets of the data. */
  reset_hours: number;
  /** When the next reset is due (ISO 8601), or null before the first one is recorded. */
  next_reset: string | null;
  /** The admin's address, or null when the project has no admin. */
  admin_url: string | null;
}

/** Experimental. Where the demo's description comes from, relative to the client's `baseUrl`. */
export const DEMO_PATH = "/demo/";

/** Experimental. The demo accounts of the server (`GET /demo/`), cached for five minutes. */
export function useDemo(
  options?: Omit<UseQueryOptions<DemoInfo>, "queryKey" | "queryFn">,
): UseQueryResult<DemoInfo> {
  const client = useKarniClient();
  const fallback = useQueryClient().getDefaultOptions().queries?.retry ?? 3;
  return useQuery<DemoInfo>({
    staleTime: 5 * 60 * 1000,
    // A 4xx (a server that is not a demo: 404 E954) is an answer, not a hiccup: no retries.
    retry: (failures, error) => {
      if (error instanceof KarniApiError && error.status < 500) return false;
      if (typeof fallback === "function") return fallback(failures, error);
      if (typeof fallback === "boolean") return fallback;
      return failures < fallback;
    },
    ...options,
    queryKey: karniKeys.demo(),
    queryFn: ({ signal }) => client.request<DemoInfo>(DEMO_PATH, { signal }),
  });
}
