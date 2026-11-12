// What the storefront reads from the shop's API (shop/serializers.py and the products list).

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

export interface CartProduct {
  id: string;
  name: string;
  slug: string;
  sku: string;
  image: string | null;
  price: string;
  current_price: string;
  available: number;
}

export interface CartLine {
  id: string;
  product: CartProduct;
  quantity: number;
  unit_price: string;
  line_total: string;
  problem: string | null;
}

export interface Cart {
  token: string | null;
  lines: CartLine[];
  count: number;
  subtotal: string;
  currency: string;
  ready: boolean;
}

export interface Address {
  name: string;
  company?: string;
  line1: string;
  line2?: string;
  city: string;
  region?: string;
  postcode: string;
  country: string;
  phone?: string;
}

export interface OrderLine {
  id: string;
  name: string;
  sku: string | null;
  quantity: number;
  unit_price: string;
  line_total: string;
  slug: string | null;
  image: string | null;
}

/** An order as its customer, or the guest with its key, sees it (GET /api/orders/lookup/). */
export interface Order {
  id: string;
  number: number;
  status: string;
  email: string;
  subtotal: string;
  total: string;
  currency: string;
  billing: Address;
  shipping: Address;
  note: string;
  created_at: string;
  paid_at: string | null;
  reserved_until: string | null;
  payable: boolean;
  lines: OrderLine[];
}

/** An order as the orders list answers it (the customer's own). */
export interface OrderRow {
  id: string;
  number: number;
  status: string;
  total: string;
  created_at: string;
}
