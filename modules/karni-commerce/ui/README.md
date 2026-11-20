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
- **`StaffOrders`**, **`StaffOrderPage`**, **`NewOrderPage`**, **`CustomersPage`** and
  **`CustomerPage`**: the staff's orders, one order with refunds, notes and history, an
  order placed by hand of any kind, and the customers. `registerOrderPanel` adds a
  selling part's panel (a parcel to ship) to the staff's order page and
  `registerBuyerOrderPanel` to the buyer's, each for the kinds of line it names.
- **`PayChoice`**: pay in full, or a deposit now and the balance later.
- **`useCart`**, **`useSetLine`**, **`useMergeOnSignIn`**, **`useCurrency`**, **`Money`**,
  **`PriceTag`**.

- **`ReportsPage`**: the reports a person may run. A dated report takes From, To and
  By (day, week or month), shows its table with a totals row and downloads a CSV file. The
  chosen report stays in the `report` search value.
- **`AbandonedCartsPage`**: carts with items that nobody touched for a while, with a search
  box and paging, so the shop can write to the people it has an email for.
- **`OrderDocumentPage`**: an order's invoice or packing slip (`kind="invoice"` or
  `"packing_slip"`) in a frame, with Print and a way back to the order. Mount it at
  `paths.invoice(number, key)` and `paths.packingSlip(number)`.
- **`useBusiness`**: what the business says about itself (`/preferences/public/`), read once.
  `Money` follows its `currency_display` (a symbol, a code or a name).

`CheckoutPage` follows the shop's checkout settings: when guest checkout is off, a visitor is
asked to sign in, and when the terms of sale must be accepted, a checkbox is required.

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

## In a project of parts

A project built from recipes gets these pages without a file of its own:
`karni build` writes `/cart`, `/checkout`, `/orders`, `/orders/<number>` and
the invoice and packing slip pages, and calls `register()` at startup. Each
is one component here:

- `FamilyOrdersPage` (`/orders`): every order for staff (`StaffOrders`), a
  customer's own (`OrdersPage`). `FamilyOrderPage` (`/orders/<number>`): the
  order to run for staff, the order for its buyer or a guest with the key.
- `register()` adds "Your orders" to the account page, the Orders tab of the
  person page (`PersonOrders`, `GET /orders/?person=<id>`) and the link from
  any row or search hit of an order to its page.
- `registerLineRenderer(kind, Component)` draws one kind's lines on the cart,
  the checkout, the buyer's order page and the staff's order page. Component
  gets `{ line, place }`, `place` being `cart`, `checkout`, `order` or
  `staff`. Without one, a line shows its name (linked to the item's page where
  the buyer may follow it), its options in words and, for staff, its SKU.
  `LineDescription` draws a line the same way on a page of your own.
- `registerCommercePaths({ browse: "/shop/catalogue" })` sets a path once at
  startup, under the provider's `paths`. The staff's order page links the
  buyer to their person page (`paths.person(id)`, `/people/<id>`).
- `useBusiness` is @karni/ui's, so both packages read the business's details
  once.

## License

Apache-2.0.
