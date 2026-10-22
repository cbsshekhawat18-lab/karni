import * as React from "react";
import { cn } from "../lib/cn";
import { Button, type ButtonProps } from "../components/primitives/button";
import { SpinnerIcon } from "../components/primitives/icons";
import { useDelayedFlag } from "./hooks";

export interface PendingButtonProps extends ButtonProps {
  /** True while the action runs: the button is disabled and, after ~500ms, shows progress. */
  pending?: boolean;
  /** Announced to screen readers while pending ("Saving…"). */
  pendingLabel?: string;
}

/**
 * A button for work that takes time. While `pending` it is disabled and
 * `aria-busy`. Once the work is slow (500ms), a spinner covers the label,
 * which stays in the layout, so the button never changes width or freezes
 * silently. Renders the registered `button` primitive, so it follows the
 * project's design system.
 */
export const PendingButton = React.forwardRef<HTMLButtonElement, PendingButtonProps>(
  (
    { pending = false, pendingLabel = "Working…", disabled, className, children, ...props },
    ref,
  ) => {
    const slow = useDelayedFlag(pending);
    return (
      <>
        <Button
          ref={ref}
          disabled={disabled === true || pending}
          aria-busy={pending || undefined}
          className={cn("relative", className)}
          {...props}
        >
          <span className={cn("inline-flex items-center gap-2", slow && "text-transparent")}>
            {children}
          </span>
          {slow && (
            <span className="absolute inset-0 flex items-center justify-center" aria-hidden="true">
              <SpinnerIcon className="h-4 w-4 animate-spin" />
            </span>
          )}
        </Button>
        <span className="sr-only" role="status" aria-live="polite">
          {pending ? pendingLabel : ""}
        </span>
      </>
    );
  },
);
PendingButton.displayName = "PendingButton";
