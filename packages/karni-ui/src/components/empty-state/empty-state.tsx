import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";

registerComponentRole("empty-state", "EmptyState");

export interface EmptyStateProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  /** Optional illustration/icon slot, rendered above the title. */
  icon?: React.ReactNode;
  /** Short headline ("No events yet"). */
  title: React.ReactNode;
  /** Optional supporting copy under the title. */
  description?: React.ReactNode;
  /** Slot for a call to action (e.g. a "Create" button). */
  action?: React.ReactNode;
  children?: React.ReactNode;
}

/**
 * Centered placeholder for empty collections: icon, title, description and
 * an action slot. Used by ResourceTable's `empty` slot and reusable anywhere.
 *
 * Escape hatches: every visual part is a slot; `className` merges via cn();
 * extra children render under the action.
 */
export const EmptyState = React.forwardRef<HTMLDivElement, EmptyStateProps>(
  ({ icon, title, description, action, className, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "flex w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-background px-6 py-12 text-center",
        className,
      )}
      {...props}
    >
      {icon != null && (
        <div aria-hidden="true" className="mb-2 text-muted-foreground [&>svg]:h-10 [&>svg]:w-10">
          {icon}
        </div>
      )}
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      {description != null && (
        <p className="max-w-96 text-sm text-muted-foreground">{description}</p>
      )}
      {action != null && <div className="mt-3 flex items-center gap-2">{action}</div>}
      {children}
    </div>
  ),
);
EmptyState.displayName = "EmptyState";
