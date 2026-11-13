// Who the signed-in person is to the shop: staff hold a role beyond the family's
// customer role (admin, shop-manager, shop-staff, or another part's role when the project
// holds several parts). The server decides what each may do. This only picks the back
// office's frame and its links.
import { useAuth } from "@karni/ui";

/** The family's role for the people who buy: it alone keeps someone a customer. */
export const CUSTOMER_ROLES = ["customer"];

export type Person = "loading" | "visitor" | "customer" | "staff";

export function usePerson(): Person {
  const { status, roles } = useAuth();
  if (status === "loading") return "loading";
  if (status !== "authenticated") return "visitor";
  return roles.some((role) => !CUSTOMER_ROLES.includes(role)) ? "staff" : "customer";
}

export function useIsStaff(): boolean {
  return usePerson() === "staff";
}
