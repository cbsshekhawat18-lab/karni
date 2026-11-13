/** The header's cart button: the count, and a menu with the first lines, the subtotal and checkout. */
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@karni/ui";
import { useCart } from "./cart";
import { Money } from "./Money";
import { useCommerce } from "./routes";

export interface MiniCartProps {
  /** How many lines the menu lists before "View the cart". */
  lines?: number;
}

export function MiniCart({ lines = 5 }: MiniCartProps) {
  const { paths, navigate } = useCommerce();
  const cart = useCart().data;
  const count = cart?.count ?? 0;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" aria-label={`Cart, ${count} ${count === 1 ? "item" : "items"}`}>
          Cart{" "}
          <span className="ml-1 rounded-full bg-primary px-2 text-xs text-primary-foreground">
            {count}
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel>{count === 0 ? "Your cart is empty" : "In your cart"}</DropdownMenuLabel>
        {(cart?.lines ?? []).slice(0, lines).map((line) => (
          <DropdownMenuItem key={line.id} onSelect={() => navigate(line.url || paths.cart)}>
            <span className="flex w-full justify-between gap-2">
              <span className="truncate">
                {line.quantity} x {line.name}
              </span>
              <Money value={line.line_total} />
            </span>
          </DropdownMenuItem>
        ))}
        {count > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="flex justify-between">
              Subtotal <Money value={cart?.subtotal ?? "0"} />
            </DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => navigate(paths.cart)}>View the cart</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => navigate(paths.checkout)}>Check out</DropdownMenuItem>
          </>
        ) : (
          <DropdownMenuItem onSelect={() => navigate(paths.browse)}>
            Start shopping
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
