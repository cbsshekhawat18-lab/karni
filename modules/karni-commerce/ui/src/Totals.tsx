/**
 * The totals of a cart, a quote or an order: the items, the coupon's discount,
 * the shipping, each tax and the total. With prices that include their tax the
 * tax lines say "included" and do not add to the total.
 */
import { cn } from "@karni/ui";
import { Money } from "./Money";
import type { LineDetail, Order, TaxLine } from "./types";

export interface TotalsProps {
  currency?: string;
  subtotal: string;
  discount?: string;
  coupon?: string | null;
  /** The shipping: null when it is not known yet (no address), undefined when nothing ships. */
  shipping?: string | null;
  shippingMethod?: string;
  taxLines?: readonly TaxLine[];
  pricesIncludeTax?: boolean;
  total: string;
  className?: string;
}

function rateText(rate: string): string {
  const value = Number(rate);
  return Number.isFinite(value) ? `${String(value)}%` : rate;
}

export function Totals({
  currency,
  subtotal,
  discount,
  coupon,
  shipping,
  shippingMethod,
  taxLines = [],
  pricesIncludeTax = false,
  total,
  className,
}: TotalsProps) {
  return (
    <dl className={cn("space-y-1", className)}>
      <div className="flex justify-between gap-4">
        <dt>Items</dt>
        <dd className="tabular-nums">
          <Money value={subtotal} currency={currency} />
        </dd>
      </div>
      {discount !== undefined && Number(discount) > 0 ? (
        <div className="flex justify-between gap-4">
          <dt>Discount{coupon ? ` (${coupon})` : ""}</dt>
          <dd className="tabular-nums">
            -<Money value={discount} currency={currency} />
          </dd>
        </div>
      ) : null}
      {shipping !== undefined ? (
        <div className="flex justify-between gap-4">
          <dt>Shipping{shippingMethod ? ` (${shippingMethod})` : ""}</dt>
          <dd className="tabular-nums">
            {shipping === null ? (
              <span className="text-muted-foreground">With the address</span>
            ) : Number(shipping) === 0 ? (
              "Free"
            ) : (
              <Money value={shipping} currency={currency} />
            )}
          </dd>
        </div>
      ) : null}
      {taxLines.map((tax) => (
        <div
          key={`${tax.name}-${tax.rate}`}
          className={cn("flex justify-between gap-4", pricesIncludeTax && "text-muted-foreground")}
        >
          <dt>
            {tax.name} {rateText(tax.rate)}
            {pricesIncludeTax ? " (included)" : ""}
          </dt>
          <dd className="tabular-nums">
            <Money value={tax.amount} currency={currency} />
          </dd>
        </div>
      ))}
      <div className="flex justify-between gap-4 border-t border-border pt-2 text-lg font-semibold">
        <dt>Total</dt>
        <dd className="tabular-nums">
          <Money value={total} currency={currency} />
        </dd>
      </div>
    </dl>
  );
}

/** A line's options in words: "Size: M, Colour: Blue". */
export function LineDetails({
  details,
  className,
}: {
  details: readonly LineDetail[] | undefined;
  className?: string;
}) {
  if (!details || details.length === 0) return null;
  return (
    <span className={cn("block text-sm text-muted-foreground", className)}>
      {details.map((detail) => `${detail.label}: ${detail.value}`).join(", ")}
    </span>
  );
}

/** An order's totals as it stored them: items, discount, shipping, taxes and the total. */
export function OrderTotals({ order, className }: { order: Order; className?: string }) {
  return (
    <Totals
      className={className}
      currency={order.currency}
      subtotal={order.subtotal}
      discount={order.discount_total}
      coupon={order.coupon_code || null}
      shipping={order.shipping_method ? order.shipping_total : undefined}
      shippingMethod={order.shipping_method}
      taxLines={order.tax_lines}
      pricesIncludeTax={order.prices_include_tax}
      total={order.total}
    />
  );
}
