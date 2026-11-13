---
description: "karni-commerce (experimental): one cart, checkout and order path for anything a project sells, through a sellable adapter per kind, with options per line, coupons, shipping zones and methods, tax rates, orders in money states, several payments per order, refunds by line or amount, emails by kind and @karni/commerce-ui."
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
   line's name, SKU, options in words and price are copied to an order line,
   each line is held (`hold`), the totals are worked out once (the coupon,
   the shipping method chosen and the tax, [below](#what-an-order-costs)),
   and the order waits for its payment for `KARNI_COMMERCE_HOLD_MINUTES`
   (30). The answer says where to pay. A total of zero is paid at once, with
   no payment.
3. karni-payments reports the payment. Commerce counts the money, and once
   it covers the total the order is `paid` and each line is taken
   (`on_paid`). A declined payment makes the order `failed` and lets its
   lines go (`release`). The buyer can try again (`POST /api/orders/pay/`):
   the lines are held again first. A second Pay while a payment is still
   open at the provider answers that payment's address (kept in its
   `metadata["url"]`) instead of starting another.
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
| `refund_limit(line, now)` | what is left of the line (what the buyer paid for it, discount off and tax in) | how much may still go back |
| `clean_options(item, options)` | keeps the options not starting with `_` | a line goes in the cart and at checkout: refuse options that do not fit (a size it does not come in) |
| `option_key(item, options)` | a short hash of the options | what tells two lines of one item apart (two sizes are two lines) |
| `details(item, options)` | none | the options in words, `[{"label": "Size", "value": "M"}]`, shown on the cart and copied to the order line |
| `choices(item)` | one choice with no options | every set of options the item is sold with, for staff placing an order by hand |
| `coupon_keys(item)` | none | what a coupon may be limited to: `{"categories": ["3", "7"]}` |
| `get_many`, `queryset`, `key` | by primary key | how items are found, one query per kind |

Every hook runs inside commerce's transaction: a hook that raises undoes the
whole step, so a checkout holds every line or none. Hold stock and seats with
[`karni.capacity`](lifecycle-and-capacity.md), so two buyers of the last item
never both get it.

`KARNI_COMMERCE_SELLABLES = {"seat": "myapp.sellables.MySeats"}` replaces the
adapter of a kind without touching the app that registered it.

## What an order costs

`karni_commerce.pricing.quote` works out the price of a cart or an order
once, and the cart page, the checkout page and checkout itself all call it,
so what the buyer sees is what the order stores:

1. Each line is priced by its adapter (`price`).
2. A coupon takes money off the lines it applies to.
3. Shipping, when a line is sent somewhere: the methods of the zone that
   covers the address.
4. Tax: each line at the rate of its tax class for the address, and the
   shipping at the standard rate.

The order keeps each part: `subtotal`, `discount_total`, `shipping_total`,
`tax_total` and `total`, the `coupon_code`, the `shipping_method`'s name and
the `tax_lines` (`[{"name", "rate", "amount"}]`). Each order line keeps its
`discount`, `tax_rate`, `tax` and `total` (what the buyer pays for the line),
so a refund by lines gives back what the line cost.

### Options

An item may be sold in several ways (a size and a colour, a date). The
cart line and the order line keep the options the buyer picked, and the
adapter decides what they mean: `clean_options` refuses options that do not
fit, `option_key` tells two lines of one item apart, `details` says them in
words, and `name`, `sku`, `price` and the stock hooks read them. The shop
recipe keeps its variations in its own table and names one in the options
(`{"variation": "<id>"}`). Another kind can do the same with its own table.

### Coupons

A coupon (`Coupon`, staff edit them at `/api/coupons/`) is a code a buyer
types at the cart or at checkout (`POST /api/carts/current/coupon/
{code}`, a blank code takes it off):

| Field | What |
|---|---|
| `kind` | `percent` (of each line it applies to), `fixed` (shared between those lines by their price, never more than they cost) or `free_shipping` |
| `amount` | the percent or the amount |
| `minimum_spend` | what the items must come to first |
| `starts_at`, `ends_at` | when it works |
| `usage_limit`, `usage_limit_per_person` | its uses in all, and per buyer (by account, else by email) |
| `kinds` | the kinds it works on, with commas (`product, seat`) |
| `items` | some items: `["product:12"]` or `[{"key": "product:12", "name": "Lamp"}]` |
| `limits` | the coupon keys the adapters give: `{"categories": ["3"]}` |

A line it applies to is one of `items`, or shares a value with a key of
`limits`, and with neither every line of its kinds. Each use is a
`CouponUse` of its order. A cancelled order gives its use back. Checkout
locks the coupon, so two buyers at once never pass its limits. A coupon the
cart holds that stopped working (it expired, it was used up) is refused at
checkout with the reason.

### Shipping

Staff set up zones (`ShippingZone`: a name, country codes with commas,
regions or postcode starts such as `75*`, and an order) and each zone's
methods (`ShippingMethod`):

| `kind` | Costs |
|---|---|
| `flat` | `cost`, and nothing once the items (less the discount) reach `free_above` when it is set |
| `free` | nothing, and it shows only once the items reach `free_above` |
| `pickup` | `cost` (often nothing): the buyer collects it |

Checkout offers the methods of the first zone, by its order, that covers the
address (`POST /api/carts/current/quote/ {address, shipping_method, email}`
answers them with the totals), and takes the one chosen
(`shipping_method` in the checkout body; blank takes the first). A zone with
no countries covers everywhere else. An address no zone covers cannot check
out ("We do not send orders to US yet."). With no zone at all, shipping is
not charged. A free-shipping coupon makes every method free.

### Tax

Staff set up rates (`TaxRate`: a name, a country or blank for anywhere, a
region or blank for the whole country, the rate in percent, a tax class and
whether it applies to shipping). The rate of an address is the most specific
one: the country and region, then the country, then the rate with neither.
A sellable's `Price.tax_class` picks the class (blank: the standard one).
The address is where the order goes, or where it is billed when nothing
ships.

Prices are entered without their tax by default, and the tax is added on
top. With `KARNI_COMMERCE_PRICES_INCLUDE_TAX` on, prices include it: the tax
is the part of each price that is tax, the total is the prices, and the
order and the emails say the tax is included.

`KARNI_COMMERCE_SHIPPING` and `KARNI_COMMERCE_TAX` name the classes that
give the methods and the rates (`karni_commerce.pricing.ZoneShipping` and
`RateTax`): subclass one to price shipping by weight, or read rates from a
tax service.

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
| `commerce.order_note` | the buyer | staff wrote them a note on the order |
| `commerce.payment_request` | the buyer | staff placed an order for them: the link to pay |

An order that waits for its payment sends no email: most orders that are
never paid are a person who changed their mind, and a "we got your order"
message for them reads like a charge that did not happen. The buyer's
confirmation and the staff's new-order email go out once the order is paid.
`order_placed` is still sent for every order, so a project that wants a
placed email sends one from its own receiver.

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

## The staff's side

Staff read the orders their grants give (`karni_commerce.order:view`):

- `GET /api/orders/?status=&created_at__gte=&email__iexact=&search=`: the
  list, by money state, date and buyer.
- `GET /api/orders/{id}/staff/`: one order with every note, its payments
  and refunds, the buyer (with how many orders and what they spent) and what
  may be done with it now (`can_cancel`, `can_refund`, `refundable`).
- `GET /api/orders/{id}/history/`: every move of its money (the order's
  `status`, `amount_paid` and `amount_refunded` are audited).
- `POST /api/orders/{id}/notes/` (`order:change`): `{body, kind}`. An
  `internal` note stays with the staff. A `customer` note shows on the
  buyer's order page and goes to them by email (`commerce.order_note`).
- `POST /api/orders/manual/` (`order:add`): an order placed by hand for a
  buyer who called. The server prices and holds the lines as checkout does,
  for `KARNI_COMMERCE_MANUAL_HOLD_MINUTES`, the order is the account's whose
  verified email it names, and the buyer gets the link to pay
  (`commerce.payment_request`) unless `send_link` is false.
  `GET /api/orders/items/?kind=&search=` finds what may go on it: an adapter
  offers its items by its `search_fields`.
- `GET /api/orders/customers/?search=&ordering=`: the buyers, one row per
  email, with their orders, what they spent (paid less refunded) and their
  first and last order, and `GET /api/orders/customer/?email=`: one buyer's
  orders, addresses and account.

The customers come from `KARNI_COMMERCE_CUSTOMERS`
(`karni_commerce.customers.OrderCustomers`, which groups the orders by
email). It is a seam: the family's people contract replaces it with the
project's people and keeps the two calls.

## Settings

| Setting | Default | What |
|---|---|---|
| `KARNI_COMMERCE_CURRENCY` | blank: the payments currency | the project's currency |
| `KARNI_COMMERCE_HOLD_MINUTES` | `30` | how long checkout holds an order's items |
| `KARNI_COMMERCE_MANUAL_HOLD_MINUTES` | `2880` | how long an order staff place by hand holds its items |
| `KARNI_COMMERCE_CUSTOMERS` | `karni_commerce.customers.OrderCustomers` | the class behind the customers list and page |
| `KARNI_COMMERCE_MAX_QUANTITY` | `99` | the most of one item a cart line takes |
| `KARNI_COMMERCE_FIRST_NUMBER` | `1001` | the first order's number |
| `KARNI_COMMERCE_NUMBER` | blank | a dotted path `number(order) -> int` that replaces the numbering |
| `KARNI_COMMERCE_ORDER_PATH` | `/orders/{number}?key={key}` | the order's page in the app, after `KARNI_FRONTEND_URL` |
| `KARNI_COMMERCE_STAFF_EMAILS` | `[]` | who gets the new-order email |
| `KARNI_COMMERCE_OTHER_CHECKOUT_VALIDATOR` | payments' default | the validator for payments that are not an order's |
| `KARNI_COMMERCE_SELLABLES` | `{}` | adapters by kind, over the registered ones |
| `KARNI_COMMERCE_PRICES_INCLUDE_TAX` | `False` | whether the prices the adapters give include their tax |
| `KARNI_COMMERCE_SHIPPING` | `karni_commerce.pricing.ZoneShipping` | the class that gives an address's shipping methods |
| `KARNI_COMMERCE_TAX` | `karni_commerce.pricing.RateTax` | the class that gives a tax class's rate at an address |

## The React package

`@karni/commerce-ui` has `CartPage`, `MiniCart`, `AddToCart`, `CheckoutPage`,
`OrderPage`, `MyOrders` and `OrdersPage`, the hooks `useCart`, `useSetLine`,
`useMergeOnSignIn` and `useCurrency`, and `Money` and `PriceTag`. Wrap the app
once in `<CommerceProvider navigate={(to) => router.history.push(to)}>` and
mount each page from a thin route file. `CheckoutPage`'s `addressPicker` slot
offers a person's saved addresses.

For staff it has `StaffOrders` (the orders list with search, filters by
state, date and buyer, and a CSV export), `StaffOrderPage` (one order: the
buyer, lines, payments, refunds, notes and history, with Cancel and Refund
following the order's declared row actions when the schema has them),
`NewOrderPage` (an order placed by hand), `CustomersPage` and
`CustomerPage`. A selling app adds its own panel to the order page once at
startup:

```tsx
import { registerOrderPanel } from "@karni/commerce-ui";

registerOrderPanel({ key: "parcel", title: "Parcel", component: Parcel,
                     when: (order) => order.needs_shipping });
```

The panel gets the order and `refresh()`. `CommercePaths` gains
`customers`, `customer(email)` and `newOrder`.

The cart page and checkout take a coupon (`CouponBox`, `useApplyCoupon`),
checkout offers the shipping methods for the address and shows the tax
(`useQuote`, `Totals`), and `CheckoutPage`'s `defaultCountry` starts the
address in the business's own country. A line shows its options in words
(`LineDetails`), and an order its stored totals (`OrderTotals`). For staff,
`CouponsPage`, `ShippingPage` (the zones, and a zone's methods) and
`TaxRatesPage` edit what checkout charges. A coupon's form picks the items
it applies to by name, and a selling app adds its own coupon keys to it once
at startup:

```tsx
import { registerCouponLimit } from "@karni/commerce-ui";

registerCouponLimit({ key: "categories", label: "Categories", resource: "categories" });
```

## What it does not do yet

Invoices, deposits with a balance link, bundles, abandoned-cart reports and
reports of coupons used are planned in this module. Shipping is priced by
zone and method, not by weight or a carrier's live rates (subclass
`ZoneShipping` for that). One rate applies per tax class and address: no
compound taxes.
