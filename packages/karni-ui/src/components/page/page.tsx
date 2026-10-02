import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";

registerComponentRole("page-shell", "Page");

export interface PageProps extends Omit<React.HTMLAttributes<HTMLElement>, "title"> {
  /** Page heading, rendered as an <h1>. */
  title: React.ReactNode;
  /** Optional sub-heading under the title. */
  description?: React.ReactNode;
  /** Slot rendered to the right of the title (buttons, menus, …). */
  actions?: React.ReactNode;
  /**
   * Escape hatch: replaces the entire derived header (title/description/
   * actions are ignored when given).
   */
  header?: React.ReactNode;
  /** Extra classes for the derived header row. */
  headerClassName?: string;
  /** Extra classes for the content area under the header. */
  contentClassName?: string;
  children?: React.ReactNode;
}

/**
 * Standard page chrome: an <h1> title row with an actions slot, then the
 * content. The target usage `<Page title="Events"><ResourceTable … /></Page>`
 * is a complete screen.
 *
 * Escape hatches: `header` replaces the whole derived header; `className`,
 * `headerClassName` and `contentClassName` merge through cn(); every other
 * prop passes through to the root <section>.
 */
export const Page = React.forwardRef<HTMLElement, PageProps>(
  (
    {
      title,
      description,
      actions,
      header,
      headerClassName,
      contentClassName,
      className,
      children,
      ...props
    },
    ref,
  ) => (
    <section ref={ref} className={cn("flex w-full flex-col gap-6", className)} {...props}>
      {header ?? (
        <header className={cn("flex flex-wrap items-start justify-between gap-4", headerClassName)}>
          <div className="grid gap-1">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
            {description != null && <p className="text-sm text-muted-foreground">{description}</p>}
          </div>
          {actions != null && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("flex flex-col gap-4", contentClassName)}>{children}</div>
    </section>
  ),
);
Page.displayName = "Page";
