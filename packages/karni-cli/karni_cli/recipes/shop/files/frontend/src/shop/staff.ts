// Who the signed-in person is to the shop: the roles of karni.yaml that run it. The server
// decides what each may do. This only picks the back office's frame and its links.
import { useAuth } from "@karni/ui";

/** The roles that open the back office (karni.yaml roles). */
export const STAFF_ROLES = ["admin", "shop-manager", "shop-staff"];

export type Person = "loading" | "visitor" | "customer" | "staff";

export function usePerson(): Person {
  const { status, roles } = useAuth();
  if (status === "loading") return "loading";
  if (status !== "authenticated") return "visitor";
  return roles.some((role) => STAFF_ROLES.includes(role)) ? "staff" : "customer";
}

export function useIsStaff(): boolean {
  return usePerson() === "staff";
}
