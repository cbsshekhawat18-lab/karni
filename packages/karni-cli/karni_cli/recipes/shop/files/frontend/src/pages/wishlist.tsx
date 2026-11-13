// /wishlist: what the customer keeps for later, as cards they can buy from.
import { EmptyState, Skeleton, useResourceList, usePageMeta } from "@karni/ui";
import { Link } from "@tanstack/react-router";
import { ProductCard } from "../shop/ProductCard";
import { useShopName } from "../shop/StoreLayout";
import type { Product } from "../shop/types";
import { WishlistButton } from "../shop/WishlistButton";
import { useWishlist } from "../shop/wishlist";

export default function WishlistPage() {
  const shopName = useShopName();
  usePageMeta({ title: "Your wishlist", siteName: shopName });
  const wishlist = useWishlist();
  const ids = wishlist.products;
  const products = useResourceList<Product>(
    "products",
    { filters: { ids: ids.join(",") }, pageSize: 50 },
    { enabled: ids.length > 0 },
  );
  let body;
  if (!wishlist.ready || (ids.length > 0 && products.isPending)) {
    body = <Skeleton className="h-64 w-full" />;
  } else if (ids.length === 0) {
    body = (
      <EmptyState
        title="Your wishlist is empty"
        description="Keep a product for later from its page."
        action={<Link to="/shop/products">Browse the products</Link>}
      />
    );
  } else {
    body = (
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {(products.data?.results ?? []).map((product) => (
          <li key={product.id} className="flex flex-col gap-2">
            <ProductCard product={product} />
            <WishlistButton product={product.id} name={product.name} />
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Your wishlist</h1>
      {body}
    </div>
  );
}
