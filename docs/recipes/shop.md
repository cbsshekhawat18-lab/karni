---
description: "The shop recipe: categories, products, a cart, orders with a state field and checkout through karni-payments. Its entities, roles, modules and what people usually change in karni.yaml."
---

# Recipe: online shop

!!! warning "Experimental"
    Recipes are [experimental](../stability.md#experimental-names). See
    [recipes](index.md).

Products in categories, a cart per customer, and orders that customers pay
for online. Checkout turns the cart into an order and opens its payment at
the provider, and the provider's webhook marks the order paid.

```sh
karni new "Corner Shop" --recipe shop
```

## Entities and roles

The app `shop`:

| Entity | Fields | Owner | Who reads, who writes |
|---|---|---|---|
| Category | name, slug (the import key) | | anyone reads, staff write |
| Product | category, name, slug (the import key), description, price (`money:USD`), stock, active | | anyone reads, staff write |
| Cart | customer | customer | the customer |
| CartItem | cart, product, quantity | cart's customer | the customer |
| Order | customer, status (`state`), total (`money:USD`), payment | customer | the customer and staff read, staff write |
| OrderItem | order, product, quantity, unit_price | order's customer | the customer and staff read, staff write |

An order's status moves `pending > paid > shipped > delivered`, and also
`pending > cancelled`, `paid > refunded` and `delivered > refunded`. Every
move is in the order's change history (`audit: [status]`).

Roles: `staff` (a system role, everything) and `customer`, the role every
account that signs up gets, with `own` grants on carts, cart items, orders
and order items.

## Modules and settings

- `payments` (karni-payments) with `provider: stripe` and `currency: usd`.
  The Stripe keys go in `.env`.
- `email_code_login`: customers sign in with a code sent by email.
- `terms` with `version: "2026-01"`, `url: /terms/` and `required: true`:
  the API refuses until a customer accepts the current terms.

Pages: the staff dashboard, products (list, detail, form), categories (list,
form), orders (list, detail) and a cart's detail. Demo data: 5 categories,
40 products, 10 carts, 30 cart items, 30 orders and 80 order items.

## Domain code

- `shop/models.py`: `Cart.checkout()` makes an order with an item per cart
  item at the current price and empties the cart. `Order.items_total()` and
  `update_total()` keep the total the sum of its items, through listeners
  on every item added, changed or removed. A listener marks the pending
  order paid when its payment succeeds.
- `shop/viewsets.py`: `POST /api/carts/<id>/checkout/` checks the cart out
  and opens the payment (`karni_payments.services.create_checkout`). It
  answers the order, the payment and the provider's checkout URL.
- `shop/seeds.py`: products on sale, and order items at their product's
  price, so every demo order's total is right.
- `shop/tests/test_checkout.py`: the total, checkout and the paid order.

## What people usually change

| Change | In karni.yaml |
|---|---|
| the product fields | `apps.shop.entities.Product.fields`, for example `weight: "decimal:6:2?"` or `image: "image?"` |
| the payment provider and the currency | `modules.payments: {provider: razorpay, currency: inr}`, and `money:INR` on the prices and totals |
| the order states | `apps.shop.entities.Order.fields.status`, for example `"state:pending>paid\|paid>packed\|packed>shipped\|..."` |
| the terms version and url | `features.terms: {version: "2026-06", url: /legal/terms/, required: true}` |
| who may see orders | `apps.shop.entities.Order.access` |

Then run `karni build`.
