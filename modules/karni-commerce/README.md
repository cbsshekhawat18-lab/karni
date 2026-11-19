# karni-commerce

One cart, checkout and order path for anything a Karni project sells. Experimental.

[![PyPI](https://img.shields.io/pypi/v/karni-commerce)](https://pypi.org/project/karni-commerce/) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/commerce/)

A project's apps sell different things: a product, a booking, a course seat.
They share one path. A cart line names a *kind* and an item. Checkout turns
the cart into an order with its lines copied and every line held.
[karni-payments](https://pypi.org/project/karni-payments/) takes the money, and the
settlement and refunds move the order. Each kind is an adapter the selling
app registers in its own `sellables.py`. Commerce calls the adapter and
never imports the app.

```bash
pip install karni-commerce
karni add payments
karni add commerce
```

Or in karni.yaml:

```yaml
modules:
  payments:
    provider: stripe
    currency: eur
    checkout_validator: karni_commerce.payments.checkout_validator
  commerce: {}
```

## What it gives

- `Cart` and `CartLine`: a signed-in person's cart, or a visitor's, found by
  a token and merged at sign-in.
- `Order`, `OrderLine`, `OrderPayment` and `OrderRefund`: an order with a
  readable number, the buyer's person (karni.people), user (or none), email
  and name, the addresses, lines with the name, SKU and price copied at
  checkout, several payments (a deposit and its balance, a retry) and refunds
  by line or by amount.
- `karni_commerce.services`: `set_line`, `merge`, `checkout`, `place_order`,
  `open_payment`, `settle`, `cancel`, `refund`, `settle_refund` and
  `release_expired`, each in one transaction.
- The API: `/api/carts/current/` (and `lines/`, `merge/`, `checkout/`),
  `/api/orders/` (and `lookup/`, `pay/`, `{id}/cancel/`, `{id}/refund/`),
  `/api/order-lines/`, `/api/order-payments/`, `/api/order-refunds/`.
- Signals in `karni_commerce.events`: `order_placed`, `order_paid`,
  `order_part_paid`, `order_failed`, `order_cancelled`, `order_refunded`,
  `cart_merged` and `orders_claimed`, and the family events
  `commerce.order.*` on the buyer's timeline.
- The person facts `orders`, `total_spent`, `last_order` and `first_order`,
  and `karni_commerce.testing.assert_sellable` for a selling part's tests.
- Emails through `karni.mail`, each with a kind: `commerce.order_paid`,
  `commerce.new_order`, `commerce.order_cancelled` and
  `commerce.order_refunded`.
- [`@karni/commerce-ui`](https://www.npmjs.com/package/@karni/commerce-ui):
  the cart page, the mini cart, checkout, an order's page and the person's
  orders.

## Selling something

```python
# shop/sellables.py
from karni.capacity import release, reserve
from karni_commerce.sellables import Price, Sellable, register

from shop.models import Product


@register
class ProductSellable(Sellable):
    kind = "product"
    model = Product

    def price(self, item, options, buyer):
        return Price(unit=item.current_price(), compare_at=item.price)

    def needs_shipping(self, item, options):
        return True

    def available(self, item, options):
        return item.available

    def hold(self, line):
        reserve(Product.objects.get(pk=line.item), line.quantity)

    def release(self, line):
        release(Product.objects.get(pk=line.item), line.quantity)
```

An order's `status` holds the money only: `pending`, `paid`, `part_paid`,
`failed`, `cancelled`, `refunded` and `part_refunded`. What happens to the
goods (shipped, delivered, a seat confirmed) stays in the selling app's own
records, which point at `karni_commerce.Order`.

The full guide is [docs/commerce.md](https://cbsshekhawat18-lab.github.io/karni/commerce/).

## License

Apache-2.0.
