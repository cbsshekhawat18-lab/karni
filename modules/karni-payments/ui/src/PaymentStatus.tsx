/**
 * <PaymentStatus>: live status badge + amount for one payment (contract
 * "@karni/payments-ui").
 *
 * Fetches via `useResourceItem<Payment>("payments", paymentId)`, so it shares
 * the `["karni", "payments", "detail", id]` cache entry with every other
 * @karni/ui consumer and is refreshed by <CheckoutButton>'s invalidation.
 * `poll` (a number of milliseconds) maps to TanStack Query's
 * `refetchInterval`, which helps while a webhook-driven status is settling.
 *
 * Styling uses @karni/ui design tokens only (bg-muted, bg-primary,
 * bg-destructive, bg-secondary, ...), so it inherits any theme override.
 *
 * Escape hatches: `children` render-prop replaces the whole rendering,
 * `statusLabels`/`statusClassNames` override one status each, `formatAmount`
 * replaces the Intl currency formatting, `loadingFallback`/`errorFallback`
 * replace the non-success states, `className` merges onto the wrapper.
 */
import { Skeleton, cn, useResourceItem } from "@karni/ui";
import type { ReactElement, ReactNode } from "react";
import type { Payment, PaymentStatusValue } from "./types";

/** Token-only badge classes per status. Unknown statuses fall back to muted. */
const STATUS_CLASSES: Record<PaymentStatusValue, string> = {
  pending: "bg-muted text-muted-foreground",
  processing: "bg-muted text-muted-foreground",
  succeeded: "bg-primary text-primary-foreground",
  failed: "bg-destructive text-destructive-foreground",
  canceled: "bg-secondary text-secondary-foreground",
  refunded: "bg-secondary text-secondary-foreground",
  partially_refunded: "bg-secondary text-secondary-foreground",
};

const FALLBACK_STATUS_CLASS = "bg-muted text-muted-foreground";

export interface PaymentStatusProps {
  paymentId: string | number;
  /** `false` (default) fetches once. A number refetches every N milliseconds. */
  poll?: false | number;
  /** Merged onto the wrapper element. */
  className?: string;
  /** Per-status label overrides (i18n hatch). Default: the status with spaces. */
  statusLabels?: Partial<Record<PaymentStatusValue, string>>;
  /** Per-status badge class overrides. Replaces the default classes for that status. */
  statusClassNames?: Partial<Record<PaymentStatusValue, string>>;
  /** Replaces the default Intl currency formatting of amount/currency. */
  formatAmount?: (payment: Payment) => string;
  /** Shown while loading. Defaults to a token-styled skeleton. */
  loadingFallback?: ReactNode;
  /** Shown when the fetch fails. Defaults to a destructive-toned message. */
  errorFallback?: ReactNode | ((error: unknown) => ReactNode);
  /** Full render override. It receives the fetched payment. */
  children?: (payment: Payment) => ReactNode;
}

function defaultLabel(status: string): string {
  return status.replace(/_/g, " ");
}

function defaultFormatAmount(payment: Payment): string {
  const numeric = Number(payment.amount);
  const code = payment.currency.toUpperCase();
  if (Number.isFinite(numeric)) {
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency: code }).format(
        numeric,
      );
    } catch {
      // Unknown currency code — fall through to the plain rendering.
    }
  }
  return `${payment.amount} ${code}`;
}

export function PaymentStatus(props: PaymentStatusProps): ReactElement {
  const {
    paymentId,
    poll,
    className,
    statusLabels,
    statusClassNames,
    formatAmount,
    loadingFallback,
    errorFallback,
    children,
  } = props;

  const query = useResourceItem<Payment>(
    "payments",
    paymentId,
    undefined,
    typeof poll === "number" && poll > 0 ? { refetchInterval: poll } : undefined,
  );

  if (query.isPending) {
    return (
      <span data-karni-role="payment-status" className={cn("inline-flex", className)}>
        {loadingFallback ?? <Skeleton className="h-6 w-32" data-testid="payment-status-loading" />}
      </span>
    );
  }

  if (query.isError) {
    const fallback =
      typeof errorFallback === "function" ? errorFallback(query.error) : errorFallback;
    return (
      <span
        data-karni-role="payment-status"
        role="alert"
        className={cn("inline-flex items-center text-sm text-destructive", className)}
      >
        {fallback ?? "Payment could not be loaded."}
      </span>
    );
  }

  const payment = query.data;

  if (children !== undefined) {
    return (
      <span data-karni-role="payment-status" className={cn("inline-flex", className)}>
        {children(payment)}
      </span>
    );
  }

  const status = payment.status;
  const badgeClass = statusClassNames?.[status] ?? STATUS_CLASSES[status] ?? FALLBACK_STATUS_CLASS;
  const label = statusLabels?.[status] ?? defaultLabel(status);

  return (
    <span
      data-karni-role="payment-status"
      data-status={status}
      className={cn("inline-flex items-center gap-2 text-sm", className)}
    >
      <span
        className={cn(
          "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
          badgeClass,
        )}
      >
        {label}
      </span>
      <span className="font-medium text-foreground">
        {(formatAmount ?? defaultFormatAmount)(payment)}
      </span>
    </span>
  );
}
