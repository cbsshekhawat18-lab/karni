/**
 * How the buyer pays, when the order allows a deposit: the whole
 * total now, or the deposit now and the rest later by the order's link. It shows
 * only when the quote offers a deposit (every line allows one, a booking's).
 * Checkout and an order staff place by hand use it, and send `pay` with the choice.
 */
import { useId, type ReactNode } from "react";
import { Money } from "./Money";
import type { PayWay, Quote } from "./types";

export interface PayChoiceProps {
  quote: Quote | undefined;
  chosen: PayWay;
  onChoose: (way: PayWay) => void;
  /** Who pays, for the words: "you" at checkout, "the customer" for staff. */
  payer?: "you" | "the customer";
}

/** The way to pay `quote` that is open now: a deposit only while the quote offers one. */
export function payWayFor(quote: Quote | undefined, chosen: PayWay): PayWay {
  return chosen === "deposit" && quote?.deposit ? "deposit" : "full";
}

export function PayChoice({ quote, chosen, onChoose, payer = "you" }: PayChoiceProps) {
  const name = useId();
  if (!quote?.deposit) return null;
  const rest = (Number(quote.total) - Number(quote.deposit)).toFixed(2);
  const ways: Array<{ way: PayWay; label: string; hint: ReactNode }> = [
    {
      way: "full",
      label: "Pay in full",
      hint: <Money value={quote.total} currency={quote.currency} />,
    },
    {
      way: "deposit",
      label: "Pay a deposit",
      hint: (
        <>
          <Money value={quote.deposit} currency={quote.currency} /> now,{" "}
          <Money value={rest} currency={quote.currency} /> later by the link{" "}
          {payer === "you" ? "we email you" : "we email the customer"}
        </>
      ),
    },
  ];
  return (
    <fieldset className="space-y-2">
      <legend className="text-lg font-semibold">Payment</legend>
      <ul className="space-y-2">
        {ways.map(({ way, label, hint }) => {
          const id = `${name}-${way}`;
          return (
            <li key={way}>
              <label
                htmlFor={id}
                className="flex cursor-pointer items-center gap-3 rounded-md border border-border p-3 has-[:checked]:border-primary"
              >
                <input
                  id={id}
                  type="radio"
                  name={name}
                  value={way}
                  checked={payWayFor(quote, chosen) === way}
                  onChange={() => onChoose(way)}
                  className="h-4 w-4 accent-primary"
                />
                <span className="flex-1">
                  {label}
                  <span className="block text-sm text-muted-foreground">{hint}</span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}
