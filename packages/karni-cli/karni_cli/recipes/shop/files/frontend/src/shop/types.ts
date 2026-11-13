// What the storefront reads from the shop's API (GET /api/products/ and /api/categories/).
// The cart and the orders are karni-commerce's (@karni/commerce-ui has their types).

export interface ProductImage {
  image: string;
  alt: string;
}

/** One way a product is sold (a size, a colour), with its own price and stock. */
export interface Variation {
  id: string;
  sku: string;
  /** Its values in words: "M, Sage". */
  label: string;
  /** Option name to value: { Size: "M" }. */
  values: Record<string, string>;
  price: string;
  current_price: string;
  on_sale: boolean;
  /** What is left (null: it takes backorders). */
  available: number | null;
  image: string | null;
}

/** An option of a product (Size) with the values its variations use, in order. */
export interface ProductOption {
  name: string;
  values: string[];
}

/** A product as GET /api/products/ answers it, with the price today and what is left. */
export interface Product {
  id: string;
  name: string;
  slug: string;
  sku: string;
  short_description: string;
  description: string;
  /** The description less what the short description already says (blank: nothing more). */
  more_description: string;
  image: string | null;
  price: string;
  sale_price: string | null;
  current_price: string;
  on_sale: boolean;
  available: number;
  featured: boolean;
  categories: string[];
  gallery: ProductImage[];
  /** Its variations for sale (empty: sold as it is). */
  variations: Variation[];
  options: ProductOption[];
  /** The lowest and highest price today (the same for a product sold as it is). */
  price_from: string;
  price_to: string;
  /** What is left to buy, of the product or of all its variations (null: backorders). */
  stock_left: number | null;
  /** The average of the approved reviews (null: none yet), and how many. */
  rating_average: string | null;
  rating_count: number;
}

/** A review as GET /api/reviews/ answers it. */
export interface Review {
  id: string;
  product: string;
  rating: number;
  title: string;
  body: string;
  status: "pending" | "approved" | "rejected";
  verified: boolean;
  author_name: string;
  created_at: string;
}

export interface Category {
  id: string;
  name: string;
  slug: string;
  description: string;
  image: string | null;
  parent: string | null;
}
