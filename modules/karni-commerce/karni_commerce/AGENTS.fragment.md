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
  `listeners.py`, or from another part with `@subscribe("commerce.order.paid",
  version=1)` (the family events). Never import another app's code from yours.
- The buyer is `Order.person` (karni.people). Read what they bought through
  the person facts (`orders`, `total_spent`, `last_order`), never by grouping
  orders by email.
- A deposit is the adapter's (`allows_deposit`, `deposit`): the order is
  `part_paid` and the balance is paid by its link. A short hold (a booking
  slot) is `hold_minutes`. A free order is paid when placed: never skip
  checkout for it.
- Test your adapter with `karni_commerce.testing.assert_sellable(kind, item)`.
- Set `KARNI_PAYMENTS_CHECKOUT_VALIDATOR =
  "karni_commerce.payments.checkout_validator"` (karni.yaml:
  `modules: {payments: {checkout_validator: ...}}`).
- Options (a size, a colour, a date) go in the line's `options`. The adapter
  checks them (`clean_options`), tells lines apart (`option_key`) and says
  them in words (`details`). Never add a variant column to commerce's tables.
- Coupons, shipping zones and methods and tax rates are commerce's
  (`Coupon`, `ShippingZone`, `ShippingMethod`, `TaxRate`), priced by
  `karni_commerce.pricing.quote`. Never compute a discount, shipping or tax
  in your app: give `Price.tax_class` and `coupon_keys`, or replace
  `KARNI_COMMERCE_SHIPPING` / `KARNI_COMMERCE_TAX`.
- UI: `@karni/commerce-ui` has the cart, mini cart, checkout and order pages,
  and `CouponsPage`, `ShippingPage` and `TaxRatesPage` for staff.
