/**
 * <DashboardGrid> and <DashboardCard>: a responsive grid of titled cards.
 *
 * Experimental. The grid lays its cards out one per row on phones, two from
 * the `md` breakpoint and `columns` (2, 3 or 4) from `xl`. A card spans one
 * column, or `span` of them (clamped to the grid's columns), or the whole row
 * (`"full"`). Each card is a labelled region with a heading, an optional
 * description and actions, and the three states every data card needs:
 * loading, empty and error.
 *
 * Escape hatches: `slots` replaces a card's Loading, Empty or Error, the
 * `--karni-dashboard-gap` token sets the space between cards, `className`
 * merges on both, and a page can put any element in the grid (a card is only
 * a convention).
 */
import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { ErrorState, type ErrorSlotProps } from "../../states/ErrorState";
import { Skeleton } from "../primitives/skeleton";

registerComponentRole("dashboard-grid", "DashboardGrid");

/** How many columns a grid has on wide screens. */
export type DashboardGridColumns = 2 | 3 | 4;

/** How many columns a card takes: 1 to 4, or the whole row. */
export type DashboardCardSpan = 1 | 2 | 3 | 4 | "full";

export interface DashboardGridProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Columns from the `xl` breakpoint (default 3). Phones get one, `md` screens two. */
  columns?: DashboardGridColumns;
}

const GridColumns = React.createContext<DashboardGridColumns>(3);

const COLUMN_CLASSES: Record<DashboardGridColumns, string> = {
  2: "md:grid-cols-2",
  3: "md:grid-cols-2 xl:grid-cols-3",
  4: "md:grid-cols-2 xl:grid-cols-4",
};

const SPAN_CLASSES: Record<Exclude<DashboardCardSpan, "full">, string> = {
  1: "",
  2: "md:col-span-2",
  3: "md:col-span-2 xl:col-span-3",
  4: "md:col-span-2 xl:col-span-4",
};

/**
 * Experimental. A responsive grid of cards (`DashboardCard`, `ChartCard`, or
 * any element). One column on phones, two on `md` screens, `columns` on `xl`.
 */
export const DashboardGrid = React.forwardRef<HTMLDivElement, DashboardGridProps>(
  ({ columns = 3, className, children, ...props }, ref) => (
    <GridColumns.Provider value={columns}>
      <div
        ref={ref}
        className={cn(
          "grid grid-cols-1 gap-[var(--karni-dashboard-gap)]",
          COLUMN_CLASSES[columns],
          className,
        )}
        {...props}
      >
        {children}
      </div>
    </GridColumns.Provider>
  ),
);
DashboardGrid.displayName = "DashboardGrid";

/** What a card's `Loading` slot receives. */
export interface DashboardCardLoadingProps {
  /** The card's title, for the screen-reader text. */
  title: string;
}

/** What a card's `Empty` slot receives. */
export interface DashboardCardEmptyProps {
  title: string;
  /** The `emptyLabel` prop. */
  label: React.ReactNode;
}

/** The parts of a card a project can replace. */
export interface DashboardCardSlots {
  /** Shown instead of the content while `loading`. */
  Loading: React.ComponentType<DashboardCardLoadingProps>;
  /** Shown instead of the content when `empty`. */
  Empty: React.ComponentType<DashboardCardEmptyProps>;
  /** Shown instead of the content when `error` is set. */
  Error: React.ComponentType<ErrorSlotProps>;
}

export interface DashboardCardProps extends Omit<
  React.HTMLAttributes<HTMLElement>,
  "title" | "children"
> {
  /** The card's heading, and its name for assistive technology. */
  title: string;
  /** One line under the heading. */
  description?: React.ReactNode;
  /** Buttons or links next to the heading (an export, a link to the full list). */
  actions?: React.ReactNode;
  /** Columns the card takes (default 1), clamped to the grid's. `"full"` takes the row. */
  span?: DashboardCardSpan;
  /** The heading level (default 2: a card sits under the page title). */
  headingLevel?: 2 | 3 | 4;
  /** True while the content loads: the `Loading` slot replaces it. */
  loading?: boolean;
  /** True when there is nothing to show: the `Empty` slot replaces the content. */
  empty?: boolean;
  /** What the empty card says (default "Nothing to show yet."). */
  emptyLabel?: React.ReactNode;
  /** A failure to load the content: the `Error` slot replaces it. `null` or `undefined`: none. */
  error?: unknown;
  /** Offered on the error when trying again can help. */
  onRetry?: () => void;
  /** True while the retry runs. */
  retrying?: boolean;
  /** Replaces the Loading, Empty or Error state. See DashboardCardSlots. */
  slots?: Partial<DashboardCardSlots>;
  children?: React.ReactNode;
}

function DefaultLoading({ title }: DashboardCardLoadingProps): React.ReactElement {
  return (
    <>
      <Skeleton className="h-32 w-full" />
      <span className="sr-only">Loading {title}</span>
    </>
  );
}

function DefaultEmpty({ label }: DashboardCardEmptyProps): React.ReactElement {
  return <p className="py-8 text-center text-sm text-muted-foreground">{label}</p>;
}

function DefaultError(props: ErrorSlotProps): React.ReactElement {
  return <ErrorState {...props} variant="inline" />;
}

/** The card's default states, exported so a project can wrap one. */
export const defaultDashboardCardSlots: DashboardCardSlots = {
  Loading: DefaultLoading,
  Empty: DefaultEmpty,
  Error: DefaultError,
};

function spanClass(span: DashboardCardSpan, columns: DashboardGridColumns): string {
  if (span === "full") return "col-span-full";
  return SPAN_CLASSES[Math.min(span, columns) as Exclude<DashboardCardSpan, "full">];
}

const HEADINGS = { 2: "h2", 3: "h3", 4: "h4" } as const;

/**
 * Experimental. One card of a DashboardGrid: a labelled region with a heading,
 * optional description and actions, and loading, empty and error states.
 */
export const DashboardCard = React.forwardRef<HTMLElement, DashboardCardProps>(
  (
    {
      title,
      description,
      actions,
      span = 1,
      headingLevel = 2,
      loading = false,
      empty = false,
      emptyLabel = "Nothing to show yet.",
      error,
      onRetry,
      retrying = false,
      slots,
      className,
      children,
      ...props
    },
    ref,
  ) => {
    const Slots: DashboardCardSlots = { ...defaultDashboardCardSlots, ...slots };
    const columns = React.useContext(GridColumns);
    const headingId = React.useId();
    const Heading = HEADINGS[headingLevel];
    const failed = error !== undefined && error !== null;
    let body: React.ReactNode;
    if (failed) {
      body = (
        <Slots.Error
          error={error}
          context={{ action: "load", resource: title.toLowerCase() }}
          onRetry={onRetry}
          retrying={retrying}
        />
      );
    } else if (loading) {
      body = <Slots.Loading title={title} />;
    } else if (empty) {
      body = <Slots.Empty title={title} label={emptyLabel} />;
    } else {
      body = children;
    }
    return (
      <section
        ref={ref}
        aria-labelledby={headingId}
        aria-busy={loading && !failed ? true : undefined}
        className={cn(
          "flex min-w-0 flex-col gap-4 rounded-lg border border-border bg-card p-4 text-card-foreground",
          spanClass(span, columns),
          className,
        )}
        {...props}
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 space-y-1">
            <Heading id={headingId} className="text-base font-semibold tracking-tight">
              {title}
            </Heading>
            {description != null ? (
              <p className="text-sm text-muted-foreground">{description}</p>
            ) : null}
          </div>
          {actions != null ? (
            <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
          ) : null}
        </div>
        <div className="min-w-0 flex-1">{body}</div>
      </section>
    );
  },
);
DashboardCard.displayName = "DashboardCard";
