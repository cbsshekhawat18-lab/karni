/**
 * A coupon code on the cart: type it and apply it, see what it takes off, or
 * take it off again. The server says why a code does not work.
 */
import { Button, Input, Label, PendingButton } from "@karni/ui";
import { useId, useState } from "react";
import { problemOf, useApplyCoupon } from "./cart";
import { Money } from "./Money";
import type { Cart } from "./types";

export function CouponBox({ cart }: { cart: Cart }) {
  const apply = useApplyCoupon();
  const [code, setCode] = useState("");
  const id = useId();
  if (cart.coupon) {
    return (
      <div className="space-y-1 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span>
            Coupon <strong>{cart.coupon}</strong>
            {cart.coupon_description ? ` (${cart.coupon_description})` : ""}
            {Number(cart.discount) > 0 ? (
              <>
                {": "}
                <Money value={cart.discount} currency={cart.currency} /> off
              </>
            ) : null}
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={apply.isPending}
            onClick={() => apply.mutate("")}
          >
            Remove<span className="sr-only"> the coupon</span>
          </Button>
        </div>
        {cart.coupon_problem ? (
          <p role="alert" className="font-medium text-destructive">
            {cart.coupon_problem}
          </p>
        ) : null}
      </div>
    );
  }
  return (
    <form
      className="space-y-1"
      onSubmit={(event) => {
        event.preventDefault();
        if (code.trim()) apply.mutate(code.trim(), { onSuccess: () => setCode("") });
      }}
    >
      <Label htmlFor={id}>Coupon code</Label>
      <div className="flex gap-2">
        <Input
          id={id}
          value={code}
          autoComplete="off"
          onChange={(event) => setCode(event.target.value)}
          aria-invalid={apply.isError || undefined}
          aria-describedby={apply.isError ? `${id}-error` : undefined}
        />
        <PendingButton type="submit" variant="outline" pending={apply.isPending}>
          Apply
        </PendingButton>
      </div>
      {apply.isError ? (
        <p id={`${id}-error`} role="alert" className="text-sm font-medium text-destructive">
          {problemOf(apply.error)}
        </p>
      ) : null}
    </form>
  );
}
