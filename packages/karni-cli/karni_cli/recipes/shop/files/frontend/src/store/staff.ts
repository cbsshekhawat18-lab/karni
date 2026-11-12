// Who the signed-in person is to the shop. The server's menu (KARNI_NAVIGATION, from
// karni.yaml's navigation) opens the back office only to roles that may change orders, so
// the frontend asks the menu instead of guessing from role names.
import { useAuth, useNavigation } from "@karni/ui";

export const BACK_OFFICE = "/backoffice";

export type Person = "loading" | "visitor" | "customer" | "staff";

export function usePerson(): Person {
  const { status } = useAuth();
  const menu = useNavigation({ enabled: status === "authenticated" });
  if (status === "loading") return "loading";
  if (status !== "authenticated") return "visitor";
  if (menu.isPending) return "loading";
  const items = menu.data?.items ?? [];
  const opens = items.some(
    (item) =>
      item.route === BACK_OFFICE ||
      item.children.some((child) => child.route === BACK_OFFICE),
  );
  return opens ? "staff" : "customer";
}

export function useIsStaff(): boolean {
  return usePerson() === "staff";
}
