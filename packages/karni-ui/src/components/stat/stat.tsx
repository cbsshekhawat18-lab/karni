import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";

registerComponentRole("stat", "Stat");

type ArrowProps = React.SVGAttributes<SVGSVGElement>;

function ArrowUpIcon(props: ArrowProps): React.ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
      {...props}
    >
      <line x1="12" y1="19" x2="12" y2="5" />
      <polyline points="5 12 12 5 19 12" />
    </svg>
  );
}

function ArrowDownIcon(props: ArrowProps): React.ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable={false}
      {...props}
    >
      <line x1="12" y1="5" x2="12" y2="19" />
      <polyline points="19 12 12 19 5 12" />
    </svg>
  );
}

export interface StatProps extends React.HTMLAttributes<HTMLDivElement> {
  /** What the number measures ("Active users"). */
  label: React.ReactNode;
  /** The headline value — preformatted string or any node. */
  value: React.ReactNode;
  /**
   * Change indicator. A number renders a signed figure with an up/down arrow
   * (negative numbers use the destructive token) plus screen-reader context;
   * any other node renders verbatim in the delta slot.
   */
  delta?: number | React.ReactNode;
  /** Formats a numeric `delta` (default: signed, locale formatted). */
  formatDelta?: (delta: number) => string;
  /** Optional icon slot, top-right. */
  icon?: React.ReactNode;
}

function defaultFormatDelta(delta: number): string {
  const formatted = Math.abs(delta).toLocaleString();
  return delta >= 0 ? `+${formatted}` : `-${formatted}`;
}

/**
 * KPI tile: label, value, optional delta and icon.
 *
 * Escape hatches: `value`/`delta`/`icon` accept arbitrary nodes,
 * `formatDelta` overrides numeric formatting, `className` merges via cn().
 */
export const Stat = React.forwardRef<HTMLDivElement, StatProps>(
  ({ label, value, delta, formatDelta = defaultFormatDelta, icon, className, ...props }, ref) => {
    let deltaNode: React.ReactNode = null;
    if (typeof delta === "number" && Number.isFinite(delta)) {
      const down = delta < 0;
      deltaNode = (
        <p
          className={cn(
            "flex items-center gap-1 text-sm font-medium",
            down ? "text-destructive" : "text-muted-foreground",
          )}
        >
          {down ? (
            <ArrowDownIcon className="h-3.5 w-3.5" />
          ) : (
            <ArrowUpIcon className="h-3.5 w-3.5" />
          )}
          <span className="sr-only">{down ? "Decreased by" : "Increased by"} </span>
          {formatDelta(delta)}
        </p>
      );
    } else if (delta != null) {
      deltaNode = <div className="text-sm text-muted-foreground">{delta}</div>;
    }

    return (
      <div
        ref={ref}
        className={cn(
          "flex flex-col gap-1 rounded-lg border border-border bg-card p-4 text-card-foreground",
          className,
        )}
        {...props}
      >
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          {icon != null && (
            <span aria-hidden="true" className="text-muted-foreground [&>svg]:h-4 [&>svg]:w-4">
              {icon}
            </span>
          )}
        </div>
        <p className="text-2xl font-semibold tracking-tight">{value}</p>
        {deltaNode}
      </div>
    );
  },
);
Stat.displayName = "Stat";
