import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";

registerComponentRole("empty-state", "EmptyState");

/** What each EmptyState slot receives: the matching prop. */
export interface EmptyStateSlotProps {
  children: React.ReactNode;
}

/** The parts of the placeholder a project can replace (`slots={{ Title: MyHeading }}`). */
export interface EmptyStateSlots {
  /** Wraps `icon`. It is decorative and hidden from assistive tech. */
  Icon: React.ComponentType<EmptyStateSlotProps>;
  /** The headline. The default is an <h3>. */
  Title: React.ComponentType<EmptyStateSlotProps>;
  /** The supporting copy. */
  Description: React.ComponentType<EmptyStateSlotProps>;
  /** Wraps `action`. */
  Actions: React.ComponentType<EmptyStateSlotProps>;
}

export interface EmptyStateProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  /** Optional illustration/icon slot, rendered above the title. */
  icon?: React.ReactNode;
  /** Short headline ("No events yet"). */
  title: React.ReactNode;
  /** Optional supporting copy under the title. */
  description?: React.ReactNode;
  /** Slot for a call to action (e.g. a "Create" button). */
  action?: React.ReactNode;
  /** Replaces the Icon, Title, Description or Actions. See EmptyStateSlots. */
  slots?: Partial<EmptyStateSlots>;
  children?: React.ReactNode;
}

function DefaultIcon({ children }: EmptyStateSlotProps): React.ReactElement {
  return (
    <div aria-hidden="true" className="mb-2 text-muted-foreground [&>svg]:h-10 [&>svg]:w-10">
      {children}
    </div>
  );
}

function DefaultTitle({ children }: EmptyStateSlotProps): React.ReactElement {
  return <h3 className="text-base font-semibold text-foreground">{children}</h3>;
}

function DefaultDescription({ children }: EmptyStateSlotProps): React.ReactElement {
  return <p className="max-w-96 text-sm text-muted-foreground">{children}</p>;
}

function DefaultActions({ children }: EmptyStateSlotProps): React.ReactElement {
  return <div className="mt-3 flex items-center gap-2">{children}</div>;
}

/** The default pieces of the placeholder, for wrapping one. */
export const defaultEmptyStateSlots: EmptyStateSlots = {
  Icon: DefaultIcon,
  Title: DefaultTitle,
  Description: DefaultDescription,
  Actions: DefaultActions,
};

/**
 * Centered placeholder for empty collections: icon, title, description and
 * an action slot. Used by ResourceTable's `empty` slot and reusable anywhere.
 *
 * Escape hatches: `slots` replaces the Icon, Title (an <h3> by default: swap
 * it for the heading level your page needs), Description or Actions.
 * `className` merges via cn(), and extra children render under the action.
 */
export const EmptyState = React.forwardRef<HTMLDivElement, EmptyStateProps>(
  ({ icon, title, description, action, slots, className, children, ...props }, ref) => {
    const { Icon, Title, Description, Actions } = { ...defaultEmptyStateSlots, ...slots };
    return (
      <div
        ref={ref}
        className={cn(
          "flex w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-background px-6 py-12 text-center",
          className,
        )}
        {...props}
      >
        {icon != null && <Icon>{icon}</Icon>}
        <Title>{title}</Title>
        {description != null && <Description>{description}</Description>}
        {action != null && <Actions>{action}</Actions>}
        {children}
      </div>
    );
  },
);
EmptyState.displayName = "EmptyState";
