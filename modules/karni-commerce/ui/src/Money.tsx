/** An amount as people read it, in the cart's currency unless `currency` says otherwise. */
import { cn, formatMoney } from "@karni/ui";
import { useBusiness } from "./business";
import { useCurrency } from "./cart";

export interface MoneyProps {
  value: string | number;
  /** An ISO 4217 code. Default: the project's, as the cart reports it. */
  currency?: string;
  className?: string;
}

export function Money({ value, currency, className }: MoneyProps) {
  const fallback = useCurrency();
  const display = useBusiness().data?.currency_display;
  const code = currency || fallback;
  return (
    <span className={className}>
      {code
        ? formatMoney(value, code, undefined, display ? { currencyDisplay: display } : undefined)
        : String(value)}
    </span>
  );
}

export interface PriceTagProps {
  price: string;
  /** The regular price a sale is shown against. */
  compareAt?: string | null;
  currency?: string;
  className?: string;
}

/** A price, with the regular one struck through beside it while it is on sale. */
export function PriceTag({ price, compareAt, currency, className }: PriceTagProps) {
  const onSale = compareAt != null && Number(compareAt) > Number(price);
  return (
    <span className={cn("inline-flex flex-wrap items-baseline gap-2", className)}>
      <Money
        value={price}
        currency={currency}
        className={cn("font-semibold", onSale && "text-destructive")}
      />
      {onSale ? (
        <span className="text-sm text-muted-foreground line-through">
          <span className="sr-only">was </span>
          <Money value={compareAt} currency={currency} />
        </span>
      ) : null}
    </span>
  );
}
