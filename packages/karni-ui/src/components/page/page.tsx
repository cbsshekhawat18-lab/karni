import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";

registerComponentRole("page-shell", "Page");

/** What the `Header` slot receives: the title row's pieces, already rendered by their slots. */
export interface PageHeaderProps {
  /** The Title slot holding `title`. */
  title: React.ReactNode;
  /** The Description slot holding `description`, or null. */
  description: React.ReactNode;
  /** The Actions slot holding `actions`, or null. */
  actions: React.ReactNode;
  /** `headerClassName`. */
  className?: string;
}

/** What the `Title`, `Description` and `Actions` slots receive. */
export interface PageSlotContentProps {
  children: React.ReactNode;
}

/** The parts of the page chrome a project can replace (`slots={{ Title: MyHeading }}`). */
export interface PageSlots {
  /** The row holding the title, description and actions. */
  Header: React.ComponentType<PageHeaderProps>;
  /** The page heading; the default is the page's <h1>. */
  Title: React.ComponentType<PageSlotContentProps>;
  /** The line under the title. */
  Description: React.ComponentType<PageSlotContentProps>;
  /** The container of the actions, right of the title. */
  Actions: React.ComponentType<PageSlotContentProps>;
}

export interface PageProps extends Omit<React.HTMLAttributes<HTMLElement>, "title"> {
  /** Page heading, rendered as an <h1>. */
  title: React.ReactNode;
  /** Optional sub-heading under the title. */
  description?: React.ReactNode;
  /** Slot rendered to the right of the title (buttons, menus, …). */
  actions?: React.ReactNode;
  /**
   * Replaces the entire derived header (title/description/actions are
   * ignored when given). Prefer the `Header` slot, which still receives them.
   */
  header?: React.ReactNode;
  /** Replaces pieces of the chrome; see PageSlots. */
  slots?: Partial<PageSlots>;
  /** Extra classes for the derived header row. */
  headerClassName?: string;
  /** Extra classes for the content area under the header. */
  contentClassName?: string;
  children?: React.ReactNode;
}

function DefaultHeader({
  title,
  description,
  actions,
  className,
}: PageHeaderProps): React.ReactElement {
  return (
    <header className={cn("flex flex-wrap items-start justify-between gap-4", className)}>
      <div className="grid gap-1">
        {title}
        {description}
      </div>
      {actions}
    </header>
  );
}

function DefaultTitle({ children }: PageSlotContentProps): React.ReactElement {
  return <h1 className="text-2xl font-semibold tracking-tight text-foreground">{children}</h1>;
}

function DefaultDescription({ children }: PageSlotContentProps): React.ReactElement {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function DefaultActions({ children }: PageSlotContentProps): React.ReactElement {
  return <div className="flex shrink-0 items-center gap-2">{children}</div>;
}

/** The default pieces of the page chrome, for wrapping one. */
export const defaultPageSlots: PageSlots = {
  Header: DefaultHeader,
  Title: DefaultTitle,
  Description: DefaultDescription,
  Actions: DefaultActions,
};

/**
 * Standard page chrome: an <h1> title row with an actions slot, then the
 * content. The target usage `<Page title="Events"><ResourceTable … /></Page>`
 * is a complete screen.
 *
 * Escape hatches: `slots` replaces the Header, Title, Description or
 * Actions; `header` replaces the whole derived header; `className`,
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
      slots,
      headerClassName,
      contentClassName,
      className,
      children,
      ...props
    },
    ref,
  ) => {
    const { Header, Title, Description, Actions } = { ...defaultPageSlots, ...slots };
    return (
      <section ref={ref} className={cn("flex w-full flex-col gap-6", className)} {...props}>
        {header ?? (
          <Header
            className={headerClassName}
            title={<Title>{title}</Title>}
            description={description != null ? <Description>{description}</Description> : null}
            actions={actions != null ? <Actions>{actions}</Actions> : null}
          />
        )}
        <div className={cn("flex flex-col gap-4", contentClassName)}>{children}</div>
      </section>
    );
  },
);
Page.displayName = "Page";
