/**
 * The cart page: each line with its picture, price, quantity and a way to
 * take it out, then the subtotal and the way to checkout. Lines that cannot
 * be bought say why, and checkout waits until they are changed.
 */
import { Button, EmptyState, ErrorState, Input, Skeleton, usePageMeta } from "@karni/ui";
import { useCart, useSetLine } from "./cart";
import { ItemImage } from "./ItemImage";
import { Money, PriceTag } from "./Money";
import { CommerceLink, useCommerce } from "./routes";
import type { CartLine } from "./types";

export interface CartPageProps {
  /** The page's heading and title. */
  title?: string;
  /** The site's name, after the title in the browser tab. */
  siteName?: string;
}

function Line({ line }: { line: CartLine }) {
  const set = useSetLine();
  const change = (value: string) => {
    const quantity = Math.max(0, Math.floor(Number(value) || 0));
    if (quantity !== line.quantity) set.mutate({ kind: line.kind, item: line.item, quantity });
  };
  return (
    <li className="flex flex-wrap items-center gap-4 border-b border-border py-4">
      <div className="w-20">
        <ItemImage src={line.image} />
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        {line.url ? (
          <CommerceLink to={line.url} className="font-medium hover:underline">
            {line.name}
          </CommerceLink>
        ) : (
          <span className="font-medium">{line.name}</span>
        )}
        <p className="text-sm text-muted-foreground">
          <PriceTag price={line.unit_price} compareAt={line.compare_at_price} /> each
        </p>
        {line.problem ? (
          <p className="text-sm font-medium text-destructive">{line.problem}</p>
        ) : null}
      </div>
      <Input
        aria-label={`Quantity of ${line.name}`}
        type="number"
        min={0}
        className="w-20"
        defaultValue={line.quantity}
        key={line.quantity}
        onBlur={(event) => change(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") change(event.currentTarget.value);
        }}
      />
      <Money value={line.line_total} className="w-24 text-right font-medium" />
      <Button
        variant="ghost"
        onClick={() => set.mutate({ kind: line.kind, item: line.item, quantity: 0 })}
      >
        Remove<span className="sr-only"> {line.name}</span>
      </Button>
    </li>
  );
}

export function CartPage({ title = "Your cart", siteName }: CartPageProps) {
  const { paths, navigate } = useCommerce();
  const cart = useCart();
  usePageMeta({ title, siteName });
  let body;
  if (cart.isPending) body = <Skeleton className="h-64 w-full" />;
  else if (cart.isError)
    body = <ErrorState error={cart.error} onRetry={() => void cart.refetch()} />;
  else if (cart.data.lines.length === 0)
    body = (
      <EmptyState
        title="Your cart is empty"
        description="Find something you like."
        action={<Button onClick={() => navigate(paths.browse)}>Start shopping</Button>}
      />
    );
  else
    body = (
      <div className="space-y-6">
        <ul aria-label="Cart">
          {cart.data.lines.map((line) => (
            <Line key={line.id} line={line} />
          ))}
        </ul>
        <div className="ml-auto max-w-sm space-y-3">
          <p className="flex justify-between text-lg font-semibold">
            Subtotal <Money value={cart.data.subtotal} />
          </p>
          <p className="text-sm text-muted-foreground">
            The total is worked out again when you check out.
          </p>
          <Button
            className="w-full"
            disabled={!cart.data.ready}
            onClick={() => navigate(paths.checkout)}
          >
            Check out
          </Button>
          {!cart.data.ready ? (
            <p className="text-sm text-destructive">Change the lines marked above to check out.</p>
          ) : null}
        </div>
      </div>
    );
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {body}
    </div>
  );
}
