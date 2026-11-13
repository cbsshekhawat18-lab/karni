/**
 * What the business says about itself (`GET /preferences/public/`, open to
 * visitors): its name, contact details, time zone and how money is shown.
 * Read once and kept for 5 minutes. A failure is ignored: the screens fall
 * back to their defaults.
 */
import { useKarniClient } from "@karni/ui";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { BusinessDetails } from "./types";

export type { BusinessDetails } from "./types";

export const BUSINESS_QUERY_KEY = ["karni-commerce", "business"] as const;

export function useBusiness(): UseQueryResult<BusinessDetails> {
  const client = useKarniClient();
  return useQuery<BusinessDetails>({
    queryKey: BUSINESS_QUERY_KEY,
    staleTime: 5 * 60 * 1000,
    retry: false,
    queryFn: ({ signal }) => client.request<BusinessDetails>("/preferences/public/", { signal }),
  });
}
