## Payments (karni-payments)
- Checkout, refunds and webhook-driven state ship ready-made. Never call
  provider SDKs (stripe/razorpay) directly — go through `karni_payments.services`.
- NEVER trust client amounts: set `KARNI_PAYMENTS_CHECKOUT_VALIDATOR` (dotted
  path) to enforce server-side pricing, or override the checkout action.
- Wire URLs once in config/urls.py:
  `path("payments/", include("karni_payments.urls"))`
- API rides the auto-router: `/api/payments/` + `checkout/` (POST) +
  `{id}/refund/` (POST, role `payments-admin`), `/api/refunds/` (same role).
- Settings arrive via the module's settings fragment; env vars:
  KARNI_PAYMENTS_PROVIDER (stripe|razorpay|test|dotted path),
  KARNI_PAYMENTS_CURRENCY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
  RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET.
- Webhook state changes run in Celery — keep the worker service running.
