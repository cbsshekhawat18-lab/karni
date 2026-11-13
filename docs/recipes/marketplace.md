---
description: "The marketplace recipe: sellers a user owns, listings, orders buyers pay for and payouts after a fee from a setting, with seller, buyer and staff roles. What it builds and changes."
---

# Recipe: marketplace

!!! warning "Experimental"
    Recipes are [experimental](../stability.md#experimental-names). See
    [recipes](index.md).

Sellers list items, buyers order and pay for them, and each paid order owes
its seller a payout: the order's amount less the marketplace's fee.

```sh
karni new "Craft Market" --recipe marketplace
```

## Entities and roles

The app `market`:

| Entity | Fields | Owner | Who reads, who writes |
|---|---|---|---|
| Seller | user, name, slug (the import key), about | user | anyone reads, the user and staff write, anyone signed in creates |
| Listing | seller, title, slug (the import key), description, price (`money:USD`), active | seller's user | anyone reads an active one, the seller and staff read all, the seller and staff write |
| Order | listing, buyer, quantity, amount (`money:USD`), status (`state`), payment | buyer | the buyer, the listing's seller and staff read, the buyer and staff write, staff delete |
| Payout | seller, order (`o2o`), amount, fee, status (`state:pending>paid\|pending>void`), paid_at | seller's user | the seller and staff read, staff write |

An order's status moves `pending > paid > shipped > delivered`, and also
`pending > cancelled` and `paid > refunded`.

| Role | Grants |
|---|---|
| `staff` | a system role: everything |
| `seller` | `own` on sellers and listings. A seller sees the orders of their listings and their payouts through the entities' access |
| `buyer` | the role every account that signs up gets: `own` on orders |

## Rules

Declared in `karni.yaml` ([rules](../rules.md)), so a rebuild keeps them:

- One shop per person (`E991`), a listing only in your own shop (`E134`),
  prices above zero (`E990`), a shop with listings is not deleted. A paused
  listing is seen by its seller and staff only.
- An order is of an active listing and never of your own (`E993`), for at
  least one item (`E990`), and its listing and quantity never change
  (`E994`). Staff delete pending or cancelled orders only (`E995`).
- Row actions: the buyer pays a pending order (once: a second call returns
  the open payment) or cancels it; the seller ships a paid order; the buyer
  or staff confirm delivery; staff refund a paid order, which voids its
  payout and refunds the payment; staff mark a payout paid, which stamps
  `paid_at`. In another state they answer 409 (`E997`).

## Modules and settings

- `payments` (karni-payments) with `provider: stripe` and `currency: usd`.
- `two_factor`: sellers can protect their sign-in with an authenticator app.
- `terms` with `version: "2026-01"`, `url: /terms/` and `required: true`.

The fee is `MARKETPLACE_FEE_PERCENT` in `config/settings.py`, 10 when it is
not set.

Pages: the staff dashboard, listings and sellers (list, detail, form),
orders (list, detail) and payouts (list). Demo data: 5 sellers, 30 listings
and 40 orders. Payouts come from paid orders, so none is seeded. The
sellers are makers (pottery, leather, candles, woodwork, textiles), each
with six listings of their own at a fitting price, and an order costs its
listing's price times its quantity (`market/seeds.py`, `SELLERS`).

## Domain code

- `market/models.py`: a new order costs the listing's price times the
  quantity, never what the buyer sends (`amount`, `status` and `payment`
  are read-only in the API). `Order.fee()` is the fee to the cent and
  `payout_amount()` the amount less it. When an order turns paid, a
  listener creates its seller's payout, and another marks the pending order
  paid when its payment succeeds.
- `market/viewsets.py`: `POST /api/orders/<id>/pay/` opens the payment.
- `market/tests/test_payouts.py`: the amount, the fee and the payout.

## What people usually change

| Change | In karni.yaml or the settings |
|---|---|
| the listing fields | `apps.market.entities.Listing.fields`, for example `condition: "choice:new\|used"` |
| the fee | `MARKETPLACE_FEE_PERCENT = 7.5` in `config/settings.py`, below the `karni:spec` block |
| the order states | `apps.market.entities.Order.fields.status` (keep `paid`: the payout is made on it) |
| the payment provider and the currency | `modules.payments: {provider: razorpay, currency: inr}`, and `money:INR` on the prices and amounts |

Then run `karni build`.
