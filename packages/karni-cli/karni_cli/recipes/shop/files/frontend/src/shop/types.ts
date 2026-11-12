// What the storefront reads from the shop's API (GET /api/products/ and /api/categories/).
// The cart and the orders are karni-commerce's (@karni/commerce-ui has their types).

export interface ProductImage {
  image: string;
  alt: string;
}

/** A product as GET /api/products/ answers it, with the price today and what is left. */
export interface Product {
  id: string;
  name: string;
  slug: string;
  sku: string;
  short_description: string;
  description: string;
  image: string | null;
  price: string;
  sale_price: string | null;
  current_price: string;
  on_sale: boolean;
  available: number;
  featured: boolean;
  categories: string[];
  gallery: ProductImage[];
}

export interface Category {
  id: string;
  name: string;
  slug: string;
  description: string;
  image: string | null;
  parent: string | null;
}
