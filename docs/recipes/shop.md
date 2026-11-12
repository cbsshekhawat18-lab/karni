---
description: "The shop recipe: a storefront with categories, products on sale, a cart for visitors and customers, guest checkout through karni-commerce and karni-payments, order emails, parcels with tracking, and a staff home. What each role does, how to change it, and what it does not do yet."
---

# Recipe: online shop

!!! warning "Experimental"
    Recipes are [experimental](../stability.md#experimental-names). See
    [recipes](index.md).

An online shop that a small business can open with: a storefront anyone can
browse, a cart that a visitor keeps and that joins their account when they
sign in, checkout as a guest or signed in, payment at the provider, an order
page and emails for the buyer, and parcels that staff send with a tracking
number.

```sh
karni new "Corner Shop" --recipe shop
```

The cart, checkout, orders, payments and refunds come from
[karni-commerce](../commerce.md), the same order path a booking or a course
would use in the same project. The shop adds its catalogue, its stock rules
and its parcels.

## What each person does

### A visitor

- Browses the storefront at `/shop`: the categories, featured products and
  new arrivals. `/shop/products` is the catalogue, with search, a category
  (and its sub-categories), a price range, the sort order (name, newest,
  price) and pages, all kept in the address so a link finds them again.
- Opens a product at `/shop/products/<slug>`: its pictures, the price (the
  sale price next to the regular one while a sale runs), how many are left,
  and the description. Every page has a title and a description for search
  engines.
- Adds products to the cart from a card or a product page. The mini cart in
  the header shows the count and the first lines. `/cart` changes quantities
  and takes lines out, and says when a line cannot be bought (sold out, fewer
  left, no longer for sale).
- Checks out at `/checkout` as a guest: an email, the billing address, a
  different shipping address if they want, and a note. The order holds the
  products for 30 minutes while they pay at the provider. Back from the
  provider, the order page confirms the payment, and the confirmation email
  arrives with a link to the order.

### A customer

- Signs in at `/signin` with a code sent by email (a new address gets an
  account that way) or with a password. The cart they filled as a visitor
  joins their account's cart, and orders they placed as a guest with the
  same, verified email become theirs.
- Checks out without typing their email, after accepting the shop's terms of
  sale (`features.terms`).
- Sees their orders at `/orders` and each one at `/orders/<number>`: where
  the money stands, where the parcel is (being prepared, shipped with its
  tracking number, delivered), the lines, the totals and the addresses.
  `/account` shows their orders and their name.

### Staff (`shop-staff`)

- Their home `/` is the dashboard: orders by state and the newest ones,
  parcels to send, and products sold out or running low.
- `/shipments` lists the parcels. A parcel is created when an order is paid.
  Staff mark it shipped with a tracking number (it cannot be shipped without
  one) and then delivered. The buyer gets an email at each step.
- Manage the catalogue: products (with the price, the sale price and its
  dates, the stock, the pictures, active and featured), categories in a tree,
  and tags.
- Cancel an order. A cancelled order that was paid puts its products back on
  the shelf and its money goes back through the provider.

### A manager (`shop-manager`) and an admin (`admin`)

- Everything staff do, and refunds: an amount, or lines with the items back
  in stock. `admin` holds every permission of the project.

The demo logins (password `karni-password`) are `demo@example.com` (admin),
`manager@example.com`, `staff@example.com` and `customer@example.com`.

## The rules

- Stock is held at checkout, taken when the order is paid, and given back
  when the payment fails, the order is cancelled, or the 30 minutes pass
  without a payment. A refund with "back in stock" puts the items back too.
  The database refuses stock below zero, and two buyers of the last item
  never both get it (`karni.capacity`).
- A product's `available` is the stock no order holds. Changing `stock` in
  the back office moves `available` by the same amount.
- The price, name and SKU of each line are copied to the order at checkout,
  and every total is worked out on the server. Checkout never takes a price
  from the browser.
- An order's status is its money only: waiting for payment, paid, payment
  failed, cancelled, part refunded, refunded. The parcel has its own:
  processing, shipped, delivered or cancelled. A payment that arrives after
  the order stopped waiting goes back at once.
- Order numbers count up from 1001.
- Every move of an order and a parcel is in its change history.

## Emails

| Email | To | When |
|---|---|---|
| `commerce.order_paid` | the buyer | the order is paid |
| `commerce.new_order` | `KARNI_COMMERCE_STAFF_EMAILS` | an order is paid |
| `commerce.order_cancelled` | the buyer | the order is cancelled |
| `commerce.order_refunded` | the buyer | a refund went through |
| `shop.shipment_shipped` | the buyer | the parcel left, with its tracking number |
| `shop.shipment_delivered` | the buyer | the parcel arrived |
| `shop.low_stock` | `SHOP_STAFF_EMAILS` (else the commerce staff emails) | an order leaves 3 or fewer of a product (`SHOP_LOW_STOCK`) |

In development every email prints in the console. Change one by putting a
template of the same path under your project's templates
(`karni_commerce/email/order_paid_body.txt`,
`shop/email/shipment_shipped_body.txt`), and switch one off with
`KARNI_MAIL_DISABLED_KINDS = ["commerce.new_order"]`.

## Trying it without a payment account

`modules.payments.provider` is `stripe`, with the keys in `.env`. To try the
whole journey on your machine without an account, set it to `test` in
karni.yaml and run `karni build`: while `DEBUG` is on, checkout sends the
buyer to a test page with Pay and Decline, which settles the payment the way
the provider's webhook would. Set the real provider before the shop opens.

The API answers a visitor 100 times a minute by default (`THROTTLE_ANON`).
A busy storefront raises it.

## Where the code is

- `shop/models.py`: a product's price today (`current_price`, the sale
  window) and the parcel's rules.
- `shop/sellables.py`: how the shop sells through karni-commerce. The
  product adapter prices a line, refuses a product that is not for sale or
  sold out, and holds, takes and returns the stock. Change a rule here and
  every cart and checkout follows.
- `shop/services.py`, `shop/listeners.py`, `shop/events.py` and
  `shop/messages.py`: parcels (one per paid order, cancelled with its order),
  the signals `shipment_shipped`, `shipment_delivered` and
  `product_low_stock`, and the shop's emails.
- `shop/viewsets.py`: the price filters of the catalogue
  (`?min_price=`, `?max_price=`, `?ordering=effective_price`), what a shopper
  reads of a product, and `POST /api/shipments/<id>/ship/` and `deliver/`.
- `shop/seeds.py`: the demo shop. Five categories with their children, 40
  products (some on sale, some sold out, one not for sale), and 20 orders
  placed through karni-commerce in every money and parcel state, with their
  payments and refunds. Seeding sends no email.
- `frontend/src/shop/`: the storefront (home, catalogue, product page,
  header and footer). `frontend/src/pages/` holds a thin file per page:
  `cart.tsx`, `checkout.tsx`, `orders.tsx`, `order.tsx` mount
  `@karni/commerce-ui`, and `account.tsx` and `signin.tsx` mount `@karni/ui`.
- `shop/tests/`: the stock, price, parcel and email rules, the API for each
  role (a visitor, a customer, another customer, staff and a manager), query
  counts on the catalogue, and the demo data.

## What people usually change

| Change | In karni.yaml or the code |
|---|---|
| the product fields | `apps.shop.entities.Product.fields`, for example `weight: "decimal:6:2?"`, then `karni build`: the storefront keeps working |
| the payment provider and the currency | `modules.payments: {provider: razorpay, currency: inr}`, and `money:INR` on the product prices. Orders take the currency of the payments module |
| the parcel states | `apps.shop.entities.Shipment.fields.status` and the words in `frontend/src/` and `shop/sellables.py` |
| the terms version and url | `features.terms: {version: "2026-06", url: /terms, required: true}`, and the text in `frontend/src/shop/Terms.tsx` |
| how long checkout holds the stock | `modules.commerce: {hold_minutes: 60}` |
| who may do what | `roles` in karni.yaml |

## What it does not do yet

Not yet built: the staff order page with its actions and notes, refunds from
the screen, bulk product edits and CSV import of products, the customers
list, saved addresses, product variations, coupons, shipping zones and
rates, tax, reviews, wishlists, reports, invoices, a settings screen and
digital products. They are planned in later steps.

Out of scope for this recipe: a plugin or theme system, subscriptions,
several currencies at once, live carrier rates, several warehouses and a
point of sale.
