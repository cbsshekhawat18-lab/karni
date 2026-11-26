/**
 * Who the signed-in person is to a project of parts, and what
 * the business says about itself.
 *
 * The family has two roles of its own: `admin` and `customer`, the one
 * default role of a sign-up ([the family](https://cbsshekhawat18-lab.github.io/karni/family/)).
 * Every other role belongs to a part (`shop-staff`, `crm-rep`). So a person
 * who holds a role beyond `customer` works for the business (`staff`), and
 * everyone else who is signed in buys from it (`customer`). The server
 * decides what each may do. This only picks a frame and a home.
 *
 * Escape hatch: `useAudience(["customer", "member"])` names the roles that
 * keep someone a customer, and every family component takes the audience
 * from its own props where it matters.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useContext } from "react";
import { AuthContext } from "../../auth/provider";
import { useKarniClient } from "../../schema/provider";

/** Who is looking: not known yet, not signed in, a buyer, or the business. */
export type Audience = "loading" | "visitor" | "customer" | "staff";

/** The roles that keep a signed-in person a customer: the family's `customer`. */
export const CUSTOMER_ROLES: readonly string[] = ["customer"];

/** The audience of a session: `staff` once a role beyond `customerRoles` is held. */
export function audienceOf(
  status: "loading" | "authenticated" | "anonymous" | undefined,
  roles: readonly string[],
  customerRoles: readonly string[] = CUSTOMER_ROLES,
): Audience {
  if (status === undefined || status === "loading") return "loading";
  if (status !== "authenticated") return "visitor";
  return roles.some((role) => !customerRoles.includes(role)) ? "staff" : "customer";
}

/** The audience of the signed-in person (`visitor` outside `AuthProvider`). */
export function useAudience(customerRoles: readonly string[] = CUSTOMER_ROLES): Audience {
  const auth = useContext(AuthContext);
  if (auth === null) return "visitor";
  return audienceOf(auth.status, auth.roles, customerRoles);
}

/** What `GET /preferences/public/` says about the business, open to visitors. */
export interface BusinessDetails {
  name: string;
  legal_name: string;
  address: string;
  phone: string;
  email: string;
  time_zone: string;
  language: string;
  currency: string;
  currency_display: "symbol" | "narrowSymbol" | "code" | "name";
  /** The logo's address, or blank. */
  logo?: string;
  tax_number?: string;
}

/** The cache key of the business's public details. */
export const BUSINESS_QUERY_KEY = ["karni", "$business"] as const;

/**
 * The business's public details (karni.preferences), read once
 * and kept for 5 minutes. A failure is not retried: a project without the
 * preferences contract answers 404, and the screens keep their defaults.
 */
export function useBusiness(): UseQueryResult<BusinessDetails> {
  const client = useKarniClient();
  return useQuery<BusinessDetails>({
    queryKey: BUSINESS_QUERY_KEY,
    staleTime: 5 * 60 * 1000,
    retry: false,
    queryFn: ({ signal }) => client.request<BusinessDetails>("/preferences/public/", { signal }),
  });
}

/** index.html's title when the app started: the project's name, which `karni new` writes. */
const STARTING_TITLE = typeof document === "undefined" ? "" : document.title;

/**
 * The business's name as Settings, Details has it, else
 * `fallback`, else the page's title when the app started (the project's
 * name, which `karni new` writes into index.html).
 */
export function useSiteName(fallback?: string): string {
  const business = useBusiness();
  return business.data?.name || fallback || STARTING_TITLE;
}
