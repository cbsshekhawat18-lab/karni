/**
 * Experimental. The menu the signed-in user gets from the server:
 * `GET /navigation/` (Django's `KARNI_NAVIGATION`, the settings list or the
 * `NavItem` rows edited in the admin), filtered by the same grants as the
 * API. A group has `route: null`, an item `children: []`.
 *
 * The cache key holds the user's id (`karniKeys.navigation(user)`), read from
 * `AuthProvider` when there is one, so signing in or out reads the menu
 * again. Outside `AuthProvider` the key holds no user.
 *
 * Escape hatch: `options` forwards every TanStack Query option except
 * `queryKey`/`queryFn` (e.g. `enabled`, `staleTime`).
 */
import { useQuery, type UseQueryOptions, type UseQueryResult } from "@tanstack/react-query";
import { useContext } from "react";
import { AuthContext } from "../auth/provider";
import { useKarniClient } from "../schema/provider";
import { karniKeys } from "./keys";

/** Experimental. One entry of the server's menu: an item (with a route) or a group (without). */
export interface NavigationItem {
  label: string;
  /** An icon name the app maps to a picture (Layout's `icons`), or null. */
  icon: string | null;
  /** The app path the item opens. null for a group. */
  route: string | null;
  /** A group's entries, in order. Empty for an item. */
  children: NavigationItem[];
}

/** Experimental. The body of `GET /navigation/`. */
export interface NavigationMenu {
  items: NavigationItem[];
}

/** Experimental. Where the menu comes from, relative to the client's `baseUrl`. */
export const NAVIGATION_PATH = "/navigation/";

/** Experimental. The menu for the signed-in user (`GET /navigation/`), cached per user. */
export function useNavigation(
  options?: Omit<UseQueryOptions<NavigationMenu>, "queryKey" | "queryFn">,
): UseQueryResult<NavigationMenu> {
  const client = useKarniClient();
  const auth = useContext(AuthContext);
  const user = auth?.status === "authenticated" ? (auth.user?.id ?? null) : null;
  return useQuery<NavigationMenu>({
    staleTime: 5 * 60 * 1000,
    ...options,
    enabled: (options?.enabled ?? true) && auth?.status !== "loading",
    queryKey: karniKeys.navigation(user),
    queryFn: ({ signal }) => client.request<NavigationMenu>(NAVIGATION_PATH, { signal }),
  });
}
