// The signed-in customer's wishlist: which products they keep, and a way to add or
// take one off. Each row is theirs alone (GET/POST/DELETE /api/wishlist-items/).
import { useAuth, useResourceList, useResourceMutations } from "@karni/ui";

export interface WishlistRow {
  id: string;
  product: string;
}

export function useWishlist() {
  const { status } = useAuth();
  const signedIn = status === "authenticated";
  const rows = useResourceList<WishlistRow>(
    "wishlist-items",
    { pageSize: 100 },
    { enabled: signedIn },
  );
  const { create, remove } = useResourceMutations("wishlist-items");
  const found = rows.data?.results ?? [];
  const rowOf = (product: string) =>
    found.find((row) => row.product === product);
  return {
    signedIn,
    ready: !signedIn || rows.isSuccess,
    products: found.map((row) => row.product),
    has: (product: string) => rowOf(product) !== undefined,
    pending: create.isPending || remove.isPending,
    toggle: (product: string) => {
      const row = rowOf(product);
      if (row) remove.mutate(row.id);
      else create.mutate({ product });
    },
  };
}
