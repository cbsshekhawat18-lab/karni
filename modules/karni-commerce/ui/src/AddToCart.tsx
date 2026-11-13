/**
 * "Add to cart" for any kind of thing for sale: a quantity and a button. The
 * server checks the line (what is left, whether it may be bought) and the
 * person sees its answer. `available` caps the quantity input.
 */
import { Button, Input, PendingButton, cn, useToast } from "@karni/ui";
import { useId, useState } from "react";
import { problemOf, useSetLine } from "./cart";
import { useCommerce } from "./routes";

export interface AddToCartProps {
  /** The kind of thing (a registered sellable on the server: "product", "seat"). */
  kind: string;
  /** Its key (the row's id). */
  item: string;
  /** The name the confirmation names. */
  name?: string;
  options?: Record<string, unknown>;
  /** How many a person can still buy (null: no limit). 0 shows the button off. */
  available?: number | null;
  /** The button's words. */
  label?: string;
  /** Show the quantity input (default true). */
  quantity?: boolean;
  className?: string;
  /** Called once the line is in the cart. */
  onAdded?: () => void;
}

export function AddToCart({
  kind,
  item,
  name,
  options,
  available = null,
  label = "Add to cart",
  quantity: showQuantity = true,
  className,
  onAdded,
}: AddToCartProps) {
  const set = useSetLine({ quiet: true });
  const { success } = useToast();
  const { paths, navigate } = useCommerce();
  const [quantity, setQuantity] = useState(1);
  const id = useId();
  const soldOut = available !== null && available <= 0;
  const add = () =>
    set.mutate(
      { kind, item, quantity, options, add: true },
      {
        onSuccess: () => {
          success(name ? `${name} is in your cart` : "Added to your cart", {
            action: (
              <Button variant="outline" size="sm" onClick={() => navigate(paths.cart)}>
                View the cart
              </Button>
            ),
          });
          onAdded?.();
        },
      },
    );
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap items-end gap-2">
        {showQuantity ? (
          <div className="flex flex-col gap-1">
            <label htmlFor={id} className="text-sm font-medium">
              Quantity
            </label>
            <Input
              id={id}
              type="number"
              min={1}
              max={available ?? undefined}
              className="w-20"
              value={quantity}
              disabled={soldOut}
              onChange={(event) =>
                setQuantity(Math.max(1, Math.floor(Number(event.target.value) || 1)))
              }
            />
          </div>
        ) : null}
        <PendingButton pending={set.isPending} disabled={soldOut} onClick={add}>
          {soldOut ? "Sold out" : label}
          {name ? <span className="sr-only"> {name}</span> : null}
        </PendingButton>
      </div>
      {set.isError ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {problemOf(set.error)}
        </p>
      ) : null}
    </div>
  );
}
