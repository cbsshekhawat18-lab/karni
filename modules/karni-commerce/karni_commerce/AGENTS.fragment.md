## Commerce (karni-commerce)
- One cart, checkout and order path for every kind of thing the project sells.
  Never write a cart, order, order line or order number model of your own.
- Make a model sellable with an adapter in `<app>/sellables.py`: subclass
  `karni_commerce.sellables.Sellable`, set `kind` and `model`, implement
  `price`, and the hooks your item needs (`validate`, `hold`, `release`,
  `on_paid`, `on_cancelled`, `on_refunded`, `needs_shipping`), then
  `@register` it. Hold stock with `karni.capacity.reserve`/`release`.
- Every order change goes through `karni_commerce.services` (`checkout`,
  `place_order`, `open_payment`, `cancel`, `refund`). Prices and totals come
  from the adapters, never from the client.
- An order's `status` is money only (pending, paid, part_paid, failed,
  cancelled, refunded, part_refunded). Keep fulfilment (shipped, delivered,
  confirmed) in your own model that points at `karni_commerce.Order`, and
  report it with `karni_commerce.fulfilment.register_reporter`.
- React to orders with the signals in `karni_commerce.events` in your
  `listeners.py`. Never import another app's code from yours.
- Set `KARNI_PAYMENTS_CHECKOUT_VALIDATOR =
  "karni_commerce.payments.checkout_validator"` (karni.yaml:
  `modules: {payments: {checkout_validator: ...}}`).
- UI: `@karni/commerce-ui` has the cart, mini cart, checkout and order pages.
