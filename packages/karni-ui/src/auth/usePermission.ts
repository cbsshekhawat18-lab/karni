/**
 * Role helpers over the authenticated user (contract "Hooks + auth",
 * accounts A15: the me endpoint returns `roles: string[]`).
 */
import { useMemo } from "react";
import { useAuth } from "./provider";

export interface PermissionHelpers {
  /** True when the user has at least one of the given role names. */
  hasRole(...names: string[]): boolean;
  isAuthenticated: boolean;
}

export function usePermission(): PermissionHelpers {
  const { roles, status } = useAuth();
  return useMemo<PermissionHelpers>(
    () => ({
      isAuthenticated: status === "authenticated",
      hasRole: (...names: string[]) =>
        status === "authenticated" && names.some((name) => roles.includes(name)),
    }),
    [roles, status],
  );
}
