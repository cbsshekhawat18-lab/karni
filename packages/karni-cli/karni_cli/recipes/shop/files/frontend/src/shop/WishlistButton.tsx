// Keep a product for later, or take it off the wishlist. A visitor is asked to sign in.
import { Button, cn } from "@karni/ui";
import { useWishlist } from "./wishlist";

export function WishlistButton({
  product,
  name,
  className,
}: {
  product: string;
  name: string;
  className?: string;
}) {
  const wishlist = useWishlist();
  if (!wishlist.signedIn) {
    return (
      <a
        href={`/signin?next=${encodeURIComponent(window.location.pathname)}`}
        className={cn(
          "text-sm text-muted-foreground hover:underline",
          className,
        )}
      >
        Sign in to keep it for later
      </a>
    );
  }
  const kept = wishlist.has(product);
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={className}
      aria-pressed={kept}
      disabled={!wishlist.ready || wishlist.pending}
      onClick={() => wishlist.toggle(product)}
    >
      <span aria-hidden="true">{kept ? "♥" : "♡"}</span>
      {kept ? "On your wishlist" : "Add to wishlist"}
      <span className="sr-only"> {name}</span>
    </Button>
  );
}
