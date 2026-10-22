import * as React from "react";
import { cn } from "../../lib/cn";
import { registerComponentRole } from "../../lib/roles";
import { Skeleton } from "../primitives/skeleton";

registerComponentRole("stat", "Stat");

type ArrowProps = React.SVGAttributes<SVGSVGElement>;

function iconProps(props: ArrowProps): ArrowProps {
  return {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
    focusable: false,
    ...props,
  };
}

function ArrowUpIcon(props: ArrowProps): React.ReactElement {
  return (
    <svg {...iconProps(props)}>
      <line x1="12" y1="19" x2="12" y2="5" />
      <polyline points="5 12 12 5 19 12" />
    </svg>
  );
}

function ArrowDownIcon(props: ArrowProps): React.ReactElement {
  return (
    <svg {...iconProps(props)}>
      <line x1="12" y1="5" x2="12" y2="19" />
      <polyline points="19 12 12 19 5 12" />
    </svg>
  );
}

function FlatIcon(props: ArrowProps): React.ReactElement {
  return (
    <svg {...iconProps(props)}>
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

/** What the `Label`, `Value` and `Icon` slots receive. */
export interface StatSlotProps {
  children: React.ReactNode;
}

/** What the `Delta` slot receives. */
export interface StatDeltaProps {
  /** The `delta` prop: a number, or any node. */
  delta: number | React.ReactNode;
  /** The `formatDelta` prop (or the default signed format). */
  formatDelta: (delta: number) => string;
}

/** The parts of the tile a project can replace (`slots={{ Delta: GoodWhenDown }}`). */
export interface StatSlots {
  /** What the number measures. */
  Label: React.ComponentType<StatSlotProps>;
  /** The headline value. */
  Value: React.ComponentType<StatSlotProps>;
  /** The change indicator; the default treats a rise as neutral and a fall as destructive. */
  Delta: React.ComponentType<StatDeltaProps>;
  /** Wraps `icon`; decorative, hidden from assistive tech. */
  Icon: React.ComponentType<StatSlotProps>;
}

export interface StatProps extends React.HTMLAttributes<HTMLDivElement> {
  /** What the number measures ("Active users"). */
  label: React.ReactNode;
  /** The headline value — preformatted string or any node. */
  value: React.ReactNode;
  /**
   * Change indicator. A number renders a signed figure with an up, down or
   * flat marker (negative numbers use the destructive token) plus
   * screen-reader context; any other node renders verbatim in the delta slot.
   */
  delta?: number | React.ReactNode;
  /** Formats a numeric `delta` (default: signed, locale formatted). */
  formatDelta?: (delta: number) => string;
  /** Optional icon slot, top-right. */
  icon?: React.ReactNode;
  /** True while the value loads: a placeholder replaces the value and the delta. */
  loading?: boolean;
  /** Replaces the Label, Value, Delta or Icon; see StatSlots. */
  slots?: Partial<StatSlots>;
}

function defaultFormatDelta(delta: number): string {
  const formatted = Math.abs(delta).toLocaleString();
  if (delta === 0) return formatted;
  return delta > 0 ? `+${formatted}` : `-${formatted}`;
}

function DefaultLabel({ children }: StatSlotProps): React.ReactElement {
  return <p className="text-sm font-medium text-muted-foreground">{children}</p>;
}

function DefaultValue({ children }: StatSlotProps): React.ReactElement {
  return <p className="text-2xl font-semibold tracking-tight">{children}</p>;
}

function DefaultIcon({ children }: StatSlotProps): React.ReactElement {
  return (
    <span aria-hidden="true" className="text-muted-foreground [&>svg]:h-4 [&>svg]:w-4">
      {children}
    </span>
  );
}

function DefaultDelta({ delta, formatDelta }: StatDeltaProps): React.ReactElement | null {
  if (typeof delta === "number") {
    if (!Number.isFinite(delta)) return null;
    const direction = delta < 0 ? "down" : delta > 0 ? "up" : "flat";
    const Icon = direction === "down" ? ArrowDownIcon : direction === "up" ? ArrowUpIcon : FlatIcon;
    const spoken =
      direction === "down" ? "Decreased by" : direction === "up" ? "Increased by" : "Unchanged:";
    return (
      <p
        data-trend={direction}
        className={cn(
          "flex items-center gap-1 text-sm font-medium",
          direction === "down" ? "text-destructive" : "text-muted-foreground",
        )}
      >
        <Icon className="h-3.5 w-3.5" />
        <span className="sr-only">{spoken} </span>
        {formatDelta(delta)}
      </p>
    );
  }
  if (delta == null) return null;
  return <div className="text-sm text-muted-foreground">{delta}</div>;
}

/** The default pieces of the tile, for wrapping one. */
export const defaultStatSlots: StatSlots = {
  Label: DefaultLabel,
  Value: DefaultValue,
  Delta: DefaultDelta,
  Icon: DefaultIcon,
};

/**
 * KPI tile: label, value, optional delta and icon.
 *
 * Escape hatches: `slots` replaces the Label, Value, Delta or Icon (a Delta
 * for metrics where down is good, say); `value`/`delta`/`icon` accept
 * arbitrary nodes, `formatDelta` overrides numeric formatting, `className`
 * merges via cn().
 */
export const Stat = React.forwardRef<HTMLDivElement, StatProps>(
  (
    {
      label,
      value,
      delta,
      formatDelta = defaultFormatDelta,
      icon,
      loading = false,
      slots,
      className,
      ...props
    },
    ref,
  ) => {
    const { Label, Value, Delta, Icon } = { ...defaultStatSlots, ...slots };
    return (
      <div
        ref={ref}
        aria-busy={loading || undefined}
        className={cn(
          "flex flex-col gap-1 rounded-lg border border-border bg-card p-4 text-card-foreground",
          className,
        )}
        {...props}
      >
        <div className="flex items-start justify-between gap-2">
          <Label>{label}</Label>
          {icon != null && <Icon>{icon}</Icon>}
        </div>
        {loading ? (
          <>
            <Skeleton className="h-8 w-24" />
            <span className="sr-only">Loading</span>
          </>
        ) : (
          <>
            <Value>{value}</Value>
            {delta != null && <Delta delta={delta} formatDelta={formatDelta} />}
          </>
        )}
      </div>
    );
  },
);
Stat.displayName = "Stat";
