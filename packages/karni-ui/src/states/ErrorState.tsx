import * as React from "react";
import { cn } from "../lib/cn";
import { registerComponentRole } from "../lib/roles";
import { AlertIcon, LockIcon, OfflineIcon, SearchIcon } from "../components/primitives/icons";
import { describeError, type KarniErrorContext, type KarniErrorKind } from "./describe-error";
import { PendingButton } from "./PendingButton";

registerComponentRole("error-state", "ErrorState");
registerComponentRole("permission-denied", "PermissionDenied");

const ICONS: Partial<Record<KarniErrorKind, React.ComponentType<{ className?: string }>>> = {
  forbidden: LockIcon,
  unauthenticated: LockIcon,
  offline: OfflineIcon,
  network: OfflineIcon,
  "not-found": SearchIcon,
};

export interface ErrorStateProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  /** What failed: a KarniApiError, a fetch failure, anything. */
  error: unknown;
  /** What the user was doing, so the message names it ("You can't delete events"). */
  context?: KarniErrorContext;
  /** Offered when trying again can succeed. */
  onRetry?: () => void;
  /** True while the retry runs: the button shows progress after ~500ms. */
  retrying?: boolean;
  /** More actions next to Retry (a sign-in link, "Back to the list"). */
  actions?: React.ReactNode;
  /** "panel" (a bordered block, the default) or "inline" (one compact row). */
  variant?: "panel" | "inline";
}

/**
 * What a component's `Error` slot receives: every Karni component that loads
 * data takes `slots={{ Error: YourPanel }}` with these props.
 */
export type ErrorSlotProps = Pick<ErrorStateProps, "error" | "context" | "onRetry" | "retrying">;

/**
 * What failed and what to do, in plain words (see describeError). Never shows
 * a raw status code; shows the server's own explanation when it gave one.
 * Announced to screen readers when it appears.
 */
export const ErrorState = React.forwardRef<HTMLDivElement, ErrorStateProps>(
  (
    { error, context, onRetry, retrying = false, actions, variant = "panel", className, ...props },
    ref,
  ) => {
    const described = describeError(error, context);
    const Icon = ICONS[described.kind] ?? AlertIcon;
    const retry =
      described.retryable && onRetry !== undefined ? (
        <PendingButton
          variant="outline"
          size="sm"
          onClick={onRetry}
          pending={retrying}
          pendingLabel="Trying again…"
        >
          Try again
        </PendingButton>
      ) : null;
    const inline = variant === "inline";
    return (
      <div
        ref={ref}
        role="alert"
        data-error-kind={described.kind}
        className={cn(
          inline
            ? "flex flex-wrap items-center gap-2 text-sm"
            : "flex w-full flex-col items-center gap-2 rounded-lg border border-destructive-border bg-destructive-subtle px-6 py-8 text-center",
          className,
        )}
        {...props}
      >
        <Icon className={cn("shrink-0 text-destructive", inline ? "h-4 w-4" : "mb-1 h-8 w-8")} />
        <p className={cn("font-semibold text-foreground", inline ? "text-sm" : "text-base")}>
          {described.title}
        </p>
        <p className="max-w-128 text-sm text-muted-foreground">{described.description}</p>
        {described.detail !== undefined && (
          <p className="max-w-128 text-xs text-muted-foreground">{described.detail}</p>
        )}
        {(retry !== null || actions !== undefined) && (
          <div className={cn("flex flex-wrap items-center gap-2", !inline && "mt-2")}>
            {retry}
            {actions}
          </div>
        )}
      </div>
    );
  },
);
ErrorState.displayName = "ErrorState";

export interface PermissionDeniedProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  /** The action that is not allowed: "create", "delete", "export". */
  action?: string;
  /** What it applies to: "events", "this booking". */
  resource?: string;
  /** Replaces the default "Ask an administrator" sentence. */
  description?: React.ReactNode;
  /** A way forward ("Back to the list"). */
  actions?: React.ReactNode;
}

/**
 * Says, in plain words, which action the user's role does not allow — for
 * screens that know before asking the server (a role check) as well as
 * after a 403.
 */
export const PermissionDenied = React.forwardRef<HTMLDivElement, PermissionDeniedProps>(
  ({ action, resource, description, actions, className, ...props }, ref) => {
    const what = [action, resource].filter(Boolean).join(" ");
    return (
      <div
        ref={ref}
        data-error-kind="forbidden"
        className={cn(
          "flex w-full flex-col items-center gap-2 rounded-lg border border-border bg-muted-subtle px-6 py-8 text-center",
          className,
        )}
        {...props}
      >
        <LockIcon className="mb-1 h-8 w-8 text-muted-foreground" />
        <p className="text-base font-semibold text-foreground">
          {what ? `You can't ${what}` : "You don't have access to this"}
        </p>
        <p className="max-w-128 text-sm text-muted-foreground">
          {description ?? "Your role doesn't allow it. Ask an administrator if you need access."}
        </p>
        {actions !== undefined && <div className="mt-2 flex items-center gap-2">{actions}</div>}
      </div>
    );
  },
);
PermissionDenied.displayName = "PermissionDenied";
