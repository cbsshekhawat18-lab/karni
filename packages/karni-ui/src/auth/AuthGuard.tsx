/**
 * <AuthGuard> — renders children only for authenticated users (optionally
 * holding one of the given roles); otherwise it says why, in plain words
 * (contract "Hooks + auth").
 *
 * Two different refusals: a visitor who is not signed in sees a sign-in
 * prompt (the `Anonymous` slot: a LoginForm, so signing in reveals the
 * content in place); a signed-in user whose role lacks access sees
 * PermissionDenied (the `Denied` slot). `anonymous` / `denied` replace one
 * of them with your own node, and `fallback` (one node for both) keeps
 * working; `fallback={null}` renders nothing, for hiding a piece of UI.
 *
 * While the initial auth state resolves, the `loading` slot renders
 * (default: nothing) so protected content never flashes a login screen
 * during session restore.
 */
import * as React from "react";
import type { ReactElement, ReactNode } from "react";
import { LockIcon } from "../components/primitives/icons";
import { cn } from "../lib/cn";
import { registerComponentRole } from "../lib/roles";
import { PermissionDenied } from "../states/ErrorState";
import { LoginForm } from "./LoginForm";
import { useAuth } from "./provider";
import type { KarniUser } from "./types";

registerComponentRole("auth-guard", "AuthGuard");

/** What the `Anonymous` slot receives: nobody is signed in. */
export interface AuthGuardAnonymousProps {
  /** The roles the content needs, when the guard names some. */
  roles: readonly string[];
  className?: string;
}

/** What the `Denied` slot receives: someone is signed in, and no role of theirs is in `roles`. */
export interface AuthGuardDeniedProps {
  user: KarniUser;
  /** The roles the content needs. */
  roles: readonly string[];
  className?: string;
}

/**
 * The replaceable refusals of AuthGuard. Pass any subset as `slots`;
 * `defaultAuthGuardSlots` holds Karni's own, to wrap them.
 */
export interface AuthGuardSlots {
  /** Not signed in: a sign-in prompt. */
  Anonymous: React.ComponentType<AuthGuardAnonymousProps>;
  /** Signed in without the role: PermissionDenied. */
  Denied: React.ComponentType<AuthGuardDeniedProps>;
}

export interface AuthGuardProps {
  /** Grant access when the user holds AT LEAST ONE of these role names. */
  roles?: string[];
  /**
   * Rendered for anonymous users and role mismatches alike. `anonymous` and
   * `denied` (or `slots`) are preferred: they say which of the two it is.
   * `null` renders nothing.
   */
  fallback?: ReactNode;
  /** Rendered for a visitor who is not signed in (wins over `fallback`). */
  anonymous?: ReactNode;
  /** Rendered for a signed-in user whose role lacks access (wins over `fallback`). */
  denied?: ReactNode;
  /** Rendered while the auth status is still "loading"; default nothing. */
  loading?: ReactNode;
  /** Replace the default refusals: Anonymous (sign-in prompt), Denied (PermissionDenied). */
  slots?: Partial<AuthGuardSlots>;
  /** Merged onto the default refusal's root. */
  className?: string;
  children?: ReactNode;
}

/** The default `Anonymous` slot: says the content needs a signed-in user, with the form to do it. */
function SignInPrompt({ className }: AuthGuardAnonymousProps): ReactElement {
  const headingId = React.useId();
  return (
    <section
      aria-labelledby={headingId}
      className={cn(
        "mx-auto w-full max-w-96 space-y-4 rounded-lg border border-border bg-card p-6 text-card-foreground",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <LockIcon className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
        <div className="space-y-1">
          <h2 id={headingId} className="text-lg font-semibold">
            Sign in to continue
          </h2>
          <p className="text-sm text-muted-foreground">You need to be signed in to see this.</p>
        </div>
      </div>
      <LoginForm title={null} />
    </section>
  );
}

/** The default `Denied` slot: who is signed in, and that their role does not reach this. */
function AccessDenied({ user, className }: AuthGuardDeniedProps): ReactElement {
  return (
    <PermissionDenied
      className={className}
      description={
        <>
          You&apos;re signed in as <span className="font-medium text-foreground">{user.email}</span>
          , and your role doesn&apos;t include this. Ask an administrator if you need access.
        </>
      }
    />
  );
}

/** Karni's own slots, exported so a project can wrap one instead of rewriting it. */
export const defaultAuthGuardSlots: AuthGuardSlots = {
  Anonymous: SignInPrompt,
  Denied: AccessDenied,
};

const NO_ROLES: readonly string[] = [];

/** Renders its children only for a signed-in user, optionally with one of the given roles; otherwise says why. */
export function AuthGuard(props: AuthGuardProps): ReactElement | null {
  const { roles, fallback, anonymous, denied, loading = null, slots, className, children } = props;
  const Slots: AuthGuardSlots = { ...defaultAuthGuardSlots, ...slots };
  const { status, user } = useAuth();
  const required = roles ?? NO_ROLES;
  // `fallback={null}` is a choice (render nothing); only an absent fallback means the defaults.
  const hasFallback = fallback !== undefined;
  if (status === "loading") return <>{loading}</>;
  if (status !== "authenticated" || user === null) {
    if (anonymous !== undefined) return <>{anonymous}</>;
    if (hasFallback) return <>{fallback}</>;
    return <Slots.Anonymous roles={required} className={className} />;
  }
  if (required.length > 0 && !required.some((role) => user.roles.includes(role))) {
    if (denied !== undefined) return <>{denied}</>;
    if (hasFallback) return <>{fallback}</>;
    return <Slots.Denied user={user} roles={required} className={className} />;
  }
  return <>{children}</>;
}
