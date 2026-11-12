---
description: "karni-commerce (experimental): one cart, checkout and order path for anything a project sells, through a sellable adapter per kind, with orders in money states, several payments per order, refunds by line or amount, emails by kind and @karni/commerce-ui."
---

# Commerce (karni-commerce)

!!! warning "Experimental"
    The karni-commerce module and `@karni/commerce-ui` are
    [experimental](stability.md#experimental-names): their names may change in
    a minor release, with a CHANGELOG entry.

A project can sell more than one kind of thing: a product, a seat at a
class, a booking, a course. Each needs the same path: a cart, a checkout that
holds what was bought, a payment, an order the buyer can find again, and
refunds. karni-commerce is that path, once. Each app that sells registers an
adapter for its kind, and commerce calls the adapter. Commerce never imports
the app, so the shop recipe and a booking app can sell through the same cart
in one project.

```bash
pip install karni-commerce
karni add payments
karni add commerce
```

In karni.yaml:

```yaml
modules:
  payments:
    provider: stripe
    currency: eur
    checkout_validator: karni_commerce.payments.checkout_validator
  commerce: {}
```

The currency is the project's: `KARNI_COMMERCE_CURRENCY`, or else the
payments currency. Every order and line stores the currency it was placed in.

## The path

1. A page adds a line: `POST /api/carts/current/lines/` with `{kind, item,
   quantity, options, add}`. The kind's adapter checks it (`validate`) and
   prices it (`price`). A visitor's cart is found by a token the browser
   keeps (`X-Cart-Token`), and joins the person's cart when they sign in
   (`POST /api/carts/current/merge/`).
2. Checkout, `POST /api/carts/current/checkout/`, in one transaction: each
   line's name, SKU and price are copied to an order line, each line is held
   (`hold`), the totals are the sum of the lines, and the order waits for its
   payment for `KARNI_COMMERCE_HOLD_MINUTES` (30). The answer says where to
   pay. A total of zero is paid at once, with no payment.
3. karni-payments reports the payment. Commerce counts the money, and once
   it covers the total the order is `paid` and each line is taken
   (`on_paid`). A declined payment makes the order `failed` and lets its
   lines go (`release`). The buyer can try again (`POST /api/orders/pay/`):
   the lines are held again first.
4. An order not paid in time is cancelled by `release_expired` (checkout runs
   it, and so can a beat task, `karni_commerce.tasks.release_expired`).
   Money that arrives for an order that is no longer waiting goes back at
   once.
5. Staff cancel an order (`POST /api/orders/{id}/cancel/`): a waiting order
   lets its lines go, a paid order undoes them (`on_cancelled`) and its money
   goes back. Staff refund by amount or by lines (`POST
   /api/orders/{id}/refund/`, `{amount}` or `{lines: {line id: quantity},
   restock}`). The refund is asked of the provider, and when the provider
   confirms it the lines are refunded (`on_refunded`, with the items back on
   the shelf when `restock`) and the order is `part_refunded` or `refunded`.

An order's `status` holds the money only: `pending`, `paid`, `part_paid`,
`failed`, `cancelled`, `refunded`, `part_refunded`. What happens to the goods
(a parcel shipped, a seat confirmed) is the selling app's own record, which
points at `karni_commerce.Order`. The app tells the order's page about it
with a reporter (below).

## Selling something

An app registers one adapter per kind in its own `sellables.py`, which
commerce imports at startup:

```python
# workshops/sellables.py
from django.db.models import F
from karni.capacity import release, reserve
from karni_commerce.sellables import Price, Sellable, refuse, register

from workshops.models import Workshop


@register
class SeatSellable(Sellable):
    kind = "seat"
    model = Workshop

    def name(self, item, options):
        return f"Seat at {item.title}"

    def price(self, item, options, buyer):
        return Price(unit=item.price)

    def available(self, item, options):
        return item.free_seats

    def validate(self, item, quantity, options, buyer):
        if item.has_started():
            raise refuse(f"{item.title} has started.")
        super().validate(item, quantity, options, buyer)

    def hold(self, line):
        reserve(Workshop.objects.get(pk=line.item), line.quantity, field="free_seats")

    def release(self, line):
        release(Workshop.objects.get(pk=line.item), line.quantity, field="free_seats")

    def on_paid(self, line):
        Workshop.objects.filter(pk=line.item).update(enrolled=F("enrolled") + line.quantity)
```

| Hook | Default | When |
|---|---|---|
| `kind`, `model` | required | the kind's name and its rows |
| `name`, `sku`, `url`, `image` | `str(item)`, blank, blank, none | what a cart and an order line show (name and SKU are copied to the line) |
| `price(item, options, buyer)` | required | a `Price(unit, compare_at, tax_class)` |
| `needs_shipping` | `False` | checkout asks for a shipping address when a line needs one |
| `available` | `None` (no limit) | the default `validate` refuses more |
| `validate(item, quantity, options, buyer)` | refuses past `available` | adding a line and checkout |
| `hold`, `release` | nothing | checkout, and a failed, cancelled or expired order |
| `on_paid`, `on_cancelled` | nothing | the order is paid, a paid order is cancelled |
| `on_refunded(line, quantity, restock)` | nothing | a refund of the line went through |
| `refund_limit(line, now)` | what is left of the line | how much may still go back |
| `get_many`, `queryset`, `key` | by primary key | how items are found, one query per kind |

Every hook runs inside commerce's transaction: a hook that raises undoes the
whole step, so a checkout holds every line or none. Hold stock and seats with
[`karni.capacity`](lifecycle-and-capacity.md), so two buyers of the last item
never both get it.

`KARNI_COMMERCE_SELLABLES = {"seat": "myapp.sellables.MySeats"}` replaces the
adapter of a kind without touching the app that registered it.

## What the goods are doing

```python
from karni_commerce.fulfilment import register_reporter


@register_reporter
def shipments(order):
    for shipment in Shipment.objects.filter(order=order):
        yield {"title": "Parcel", "status": shipment.status, "label": "Shipped",
               "detail": f"Tracking {shipment.tracking_number}", "at": shipment.shipped_at}
```

The buyer's order page lists every reporter's entries under the order.

## Signals and emails

`karni_commerce.events` sends `order_placed`, `order_paid`,
`order_part_paid`, `order_failed`, `order_cancelled`, `order_refunded`,
`cart_merged` and `orders_claimed`, inside the transaction that made the
change. `EVENTS` maps the family event names (`commerce.order.paid`) to them.

Emails go through [`karni.mail`](#karnimail), each under a kind:

| Kind | To | When |
|---|---|---|
| `commerce.order_paid` | the buyer | the order is paid (the confirmation) |
| `commerce.new_order` | `KARNI_COMMERCE_STAFF_EMAILS` | an order is paid and waits to be fulfilled |
| `commerce.order_cancelled` | the buyer | the order was cancelled |
| `commerce.order_refunded` | the buyer | a refund went through |

The templates are `karni_commerce/email/<name>_subject.txt`, `_body.txt` and
`_body.html`. Put a file at the same path in your project's templates to
change one, and list a kind in `KARNI_MAIL_DISABLED_KINDS` to stop it.

### karni.mail

`karni.mail.send_templated(template, to=[...], context={...}, kind="...")`
renders `<template>_subject.txt`, `_body.txt` and, when it exists,
`_body.html`, and sends them with Django's mail backend (the console in
development). The subject is one line. The kind goes out in the
`X-Karni-Kind` header, and a kind listed in `KARNI_MAIL_DISABLED_KINDS` is not
sent. Send from `transaction.on_commit` so a rolled-back change sends nothing.

## Who sees what

The API reads the roles' grants (`karni_commerce.order:view` and so on), and
a person always reads their own orders and lines. A guest reads their order
with the key checkout gave them (`GET /api/orders/lookup/?number=&key=`, the
link in the emails). Orders change only through the actions: the standard
writes answer 405. Cancelling needs `karni_commerce.order:change`. Refunding
needs that and `karni_commerce.orderrefund:add` too, so a role can handle
orders without giving money back.

## Settings

| Setting | Default | What |
|---|---|---|
| `KARNI_COMMERCE_CURRENCY` | blank: the payments currency | the project's currency |
| `KARNI_COMMERCE_HOLD_MINUTES` | `30` | how long checkout holds an order's items |
| `KARNI_COMMERCE_MAX_QUANTITY` | `99` | the most of one item a cart line takes |
| `KARNI_COMMERCE_FIRST_NUMBER` | `1001` | the first order's number |
| `KARNI_COMMERCE_NUMBER` | blank | a dotted path `number(order) -> int` that replaces the numbering |
| `KARNI_COMMERCE_ORDER_PATH` | `/orders/{number}?key={key}` | the order's page in the app, after `KARNI_FRONTEND_URL` |
| `KARNI_COMMERCE_STAFF_EMAILS` | `[]` | who gets the new-order email |
| `KARNI_COMMERCE_OTHER_CHECKOUT_VALIDATOR` | payments' default | the validator for payments that are not an order's |
| `KARNI_COMMERCE_SELLABLES` | `{}` | adapters by kind, over the registered ones |

## The React package

`@karni/commerce-ui` has `CartPage`, `MiniCart`, `AddToCart`, `CheckoutPage`,
`OrderPage`, `MyOrders` and `OrdersPage`, the hooks `useCart`, `useSetLine`,
`useMergeOnSignIn` and `useCurrency`, and `Money` and `PriceTag`. Wrap the app
once in `<CommerceProvider navigate={(to) => router.history.push(to)}>` and
mount each page from a thin route file. `CheckoutPage`'s `addressPicker` slot
offers a person's saved addresses.

## What it does not do yet

Coupons, tax, shipping zones and methods, invoices, deposits with a balance
link, bundles and abandoned-cart reports are planned in this module. Until
then an order's total is the sum of its lines, and a project adds its own
charges in its adapters' prices.
