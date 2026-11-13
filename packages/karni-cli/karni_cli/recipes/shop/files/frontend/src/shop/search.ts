// The storefront keeps its filters in the address, so a link or the back button finds them again.
import { useRouter, useRouterState } from "@tanstack/react-router";

export type SearchValues = Record<string, string>;

export function useSearchValues(): SearchValues {
  const search = useRouterState({ select: (state) => state.location.search });
  const found: SearchValues = {};
  for (const [key, value] of Object.entries(
    search as Record<string, unknown>,
  )) {
    if (value !== undefined && value !== null && value !== "")
      found[key] = String(value);
  }
  return found;
}

/** Replace some search values of the current page (an empty value removes it). */
export function useSetSearch(): (changes: SearchValues) => void {
  const router = useRouter();
  return (changes) => {
    const location = router.state.location;
    const query = new URLSearchParams();
    const merged = {
      ...(location.search as Record<string, unknown>),
      ...changes,
    };
    for (const [key, value] of Object.entries(merged)) {
      if (value !== undefined && value !== null && value !== "")
        query.set(key, String(value));
    }
    const text = query.toString();
    router.history.replace(`${location.pathname}${text ? `?${text}` : ""}`);
  };
}
