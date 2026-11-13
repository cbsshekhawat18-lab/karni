// The options of a product sold in several ways (Size, Colour): a button per value. Once
// every option has a value, the variation they make sets the price, the stock, the
// picture and what goes in the cart. A value no variation for sale has is off.
import { AddToCart, PriceTag } from "@karni/commerce-ui";
import { Button } from "@karni/ui";
import { useId, useState } from "react";
import { StockState } from "./ProductCard";
import type { Product, Variation } from "./types";

function matches(
  variation: Variation,
  chosen: Record<string, string>,
): boolean {
  return Object.entries(chosen).every(
    ([name, value]) => variation.values[name] === value,
  );
}

export function VariationPicker({
  product,
  onPicture,
}: {
  product: Product;
  /** Called with the picture of the variation chosen (null: the product's). */
  onPicture?: (image: string | null) => void;
}) {
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const base = useId();
  const complete = product.options.every(
    (option) => chosen[option.name] !== undefined,
  );
  const variation = complete
    ? product.variations.find((row) => matches(row, chosen))
    : undefined;
  const pick = (name: string, value: string) => {
    const next = { ...chosen };
    if (next[name] === value) delete next[name];
    else next[name] = value;
    setChosen(next);
    const done = product.options.every(
      (option) => next[option.name] !== undefined,
    );
    const found = done
      ? product.variations.find((row) => matches(row, next))
      : undefined;
    onPicture?.(found?.image ?? null);
  };
  return (
    <div className="space-y-4">
      {product.options.map((option) => {
        const labelId = `${base}-${option.name}`;
        return (
          <div key={option.name} className="space-y-2">
            <p id={labelId} className="text-sm font-medium">
              {option.name}
              {chosen[option.name] ? (
                <span className="font-normal text-muted-foreground">
                  : {chosen[option.name]}
                </span>
              ) : null}
            </p>
            <div
              role="group"
              aria-labelledby={labelId}
              className="flex flex-wrap gap-2"
            >
              {option.values.map((value) => {
                const others = { ...chosen, [option.name]: value };
                const possible = product.variations.some(
                  (row) =>
                    matches(row, others) &&
                    (row.available === null || row.available > 0),
                );
                return (
                  <Button
                    key={value}
                    type="button"
                    size="sm"
                    variant={
                      chosen[option.name] === value ? "default" : "outline"
                    }
                    aria-pressed={chosen[option.name] === value}
                    disabled={!possible && chosen[option.name] !== value}
                    onClick={() => pick(option.name, value)}
                  >
                    {value}
                    {!possible ? (
                      <span className="sr-only"> (sold out)</span>
                    ) : null}
                  </Button>
                );
              })}
            </div>
          </div>
        );
      })}
      {variation ? (
        <div className="space-y-2">
          <PriceTag
            price={variation.current_price}
            compareAt={variation.on_sale ? variation.price : null}
            className="text-xl"
          />
          <p>
            {variation.available === null ? (
              <span className="text-sm text-muted-foreground">In stock</span>
            ) : (
              <StockState available={variation.available} />
            )}
          </p>
          <p className="text-sm text-muted-foreground">SKU {variation.sku}</p>
          <AddToCart
            kind="product"
            item={product.id}
            name={`${product.name}, ${variation.label}`}
            options={{ variation: variation.id }}
            available={variation.available}
          />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground" role="status">
          {complete
            ? "That combination is not for sale."
            : `Choose ${product.options.map((option) => option.name.toLowerCase()).join(" and ")} to add it to the cart.`}
        </p>
      )}
    </div>
  );
}
