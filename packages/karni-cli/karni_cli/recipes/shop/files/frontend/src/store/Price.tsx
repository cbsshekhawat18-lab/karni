// A price as a shopper reads it: the sale price next to the regular one, struck through.
import { cn, formatMoney } from "@karni/ui";
import { useCart } from "./cart";

/** The shop's currency, as the cart reports it (karni.yaml: money:USD, payments: currency). */
export function useCurrency(): string {
  return useCart().data?.currency ?? "USD";
}

export function Money({
  value,
  className,
}: {
  value: string | number;
  className?: string;
}) {
  const currency = useCurrency();
  return <span className={className}>{formatMoney(value, currency)}</span>;
}

export function Price({
  price,
  current,
  onSale,
  className,
}: {
  price: string;
  current: string;
  onSale: boolean;
  className?: string;
}) {
  return (
    <span className={cn("flex flex-wrap items-baseline gap-2", className)}>
      <Money
        value={current}
        className={cn("font-semibold", onSale && "text-destructive")}
      />
      {onSale ? (
        <span className="text-sm text-muted-foreground line-through">
          <span className="sr-only">was </span>
          <Money value={price} />
        </span>
      ) : null}
    </span>
  );
}

/** In stock, a few left, or sold out, in words. */
export function StockState({ available }: { available: number }) {
  if (available <= 0) {
    return (
      <span className="text-sm font-medium text-destructive">Sold out</span>
    );
  }
  if (available <= 3) {
    return (
      <span className="text-sm text-muted-foreground">
        Only {available} left
      </span>
    );
  }
  return <span className="text-sm text-muted-foreground">In stock</span>;
}
