# @karni/commerce-ui

React components for the Karni commerce module: the cart, the mini cart, add to cart, checkout, an order's page and a person's orders. Experimental.

[![npm](https://img.shields.io/npm/v/@karni/commerce-ui)](https://www.npmjs.com/package/@karni/commerce-ui) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/commerce/)

It composes [`@karni/ui`](https://www.npmjs.com/package/@karni/ui) for the
[karni-commerce](https://pypi.org/project/karni-commerce/) module (`karni add commerce`).
Every component works for every kind of thing a project sells (a product, a
seat, a booking): the server prices each line through its kind's adapter.

- **`CartPage`**: the lines, their quantities and prices, what stops a line, the subtotal.
- **`MiniCart`**: the header's cart button with the first lines and checkout.
- **`AddToCart`**: a quantity and a button for one item of any kind.
- **`CheckoutPage`**: contact, billing and (when a line is sent) shipping address, a note,
  and the payment at the provider. An `addressPicker` slot lets a project offer saved
  addresses.
- **`OrderPage`**: one order for its buyer, or for a guest with the key from checkout.
- **`MyOrders`** and **`OrdersPage`**: the signed-in person's orders.
- **`useCart`**, **`useSetLine`**, **`useMergeOnSignIn`**, **`useCurrency`**, **`Money`**,
  **`PriceTag`**.

## Install

```bash
npm install @karni/commerce-ui @karni/ui @tanstack/react-query@5
```

## Setup

The components read the Karni client and the signed-in person from
`<KarniProvider>` and `<AuthProvider>` (see the `@karni/ui` README). Wrap the
app once in `<CommerceProvider>` with your router's navigation, and mount the
pages from thin route files:

```tsx
import { CommerceProvider, useMergeOnSignIn } from "@karni/commerce-ui";

<CommerceProvider navigate={(to) => router.history.push(to)} paths={{ browse: "/shop" }}>
  <Outlet />
</CommerceProvider>;
```

```tsx
// src/pages/cart.tsx
import { CartPage } from "@karni/commerce-ui";

export default function Cart() {
  return <CartPage />;
}
```

Call `useMergeOnSignIn()` once in the layout, so a visitor's cart joins the
person's cart when they sign in. A visitor's cart is found by a token this
browser keeps in `localStorage` (`karni.cart-token`).

## License

Apache-2.0.
