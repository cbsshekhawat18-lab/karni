/**
 * <AuthGuard> — renders children only for authenticated users (optionally
 * holding one of the given roles); otherwise the `fallback` slot (contract
 * "Hooks + auth").
 *
 * While the initial auth state resolves, the `loading` slot renders
 * (default: nothing) so protected content never flashes a login screen
 * during session restore.
 */
import type { ReactElement, ReactNode } from "react";
import { useAuth } from "./provider";
import { registerComponentRole } from "../lib/roles";

registerComponentRole("auth-guard", "AuthGuard");

export interface AuthGuardProps {
  /** Grant access when the user holds AT LEAST ONE of these role names. */
  roles?: string[];
  /** Rendered for anonymous users and role mismatches; default nothing. */
  fallback?: ReactNode;
  /** Rendered while the auth status is still "loading"; default nothing. */
  loading?: ReactNode;
  children?: ReactNode;
}

/** Renders its children only for a signed-in user, optionally with one of the given roles; otherwise its `fallback`. */
export function AuthGuard({
  roles,
  fallback = null,
  loading = null,
  children,
}: AuthGuardProps): ReactElement | null {
  const { status, user } = useAuth();
  if (status === "loading") return <>{loading}</>;
  if (status !== "authenticated" || user === null) return <>{fallback}</>;
  if (roles !== undefined && roles.length > 0 && !roles.some((role) => user.roles.includes(role))) {
    return <>{fallback}</>;
  }
  return <>{children}</>;
}
