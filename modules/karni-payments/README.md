# karni-payments

Payments module for [Karni](https://github.com/cbsshekhawat18-lab/karni): hosted checkout, refunds and
webhook-driven payment state for **Stripe** (Checkout Sessions) and
**Razorpay** (Payment Links), plus an in-memory **test provider**.

```bash
karni add payments        # wires dependency + INSTALLED_APPS + agent guidance
pip install "karni-payments[stripe]"    # or [razorpay]
```

One line of project wiring (the viewsets ride Karni's auto-router):

```python
# config/urls.py
(path("payments/", include("karni_payments.urls")),)  # the webhook endpoint
```

then `make migrate`. Register `https://<host>/payments/webhook/stripe/` (or
`.../razorpay/`) at the provider.

## What you get

- **Models** (all on `karni.models.BaseModel`): `Payment`, `Refund`,
  `WebhookEvent` (the `(provider, event_id)` dedupe record). The admin is
  derived through `AdminMeta`, with no `admin.py`.
- **API** (auto-routed, authenticated only):
  - `GET /api/payments/`: owner-scoped. The `payments-admin` role sees all.
  - `POST /api/payments/checkout/`: create a pending payment + provider
    session, then redirect the customer to the returned `url`.
  - `POST /api/payments/{id}/refund/`: requires the `payments-admin` role.
    Omit `amount` to refund the full unrefunded remainder.
  - `GET /api/refunds/`: `payments-admin` only.
  - Writes to the resources themselves answer 405: state belongs to webhooks.
- **Webhooks**: `POST /payments/webhook/<provider>/` verifies the signature
  (400 + warning log on failure, nothing persisted), dedupes on
  `(provider, event_id)` and hands processing to a Celery task
  (`process_webhook_event`: row lock + monotonic state machine +
  `processed_at` stamp in one transaction, and 3 retries with backoff). Nothing
  state-changing runs in the request cycle.
- **Services** (`karni_payments.services`): the only module project code
  should call. It holds `create_checkout`, `create_refund` (lock-validated
  against the unrefunded remainder, so over-refunds are impossible) and
  `apply_event`.

## Settings (via the `karni.settings` fragment, all overridable)

| Setting (env var of the same name)  | Default | Meaning |
| --- | --- | --- |
| `KARNI_PAYMENTS_PROVIDER` | `"stripe"` | `"stripe"`, `"razorpay"`, `"test"` or a dotted path to your own `PaymentProvider` subclass |
| `KARNI_PAYMENTS_CURRENCY` | `"usd"` | default checkout currency |
| `KARNI_PAYMENTS_CHECKOUT_VALIDATOR` | pass-through | dotted path called with `(user=, amount=, currency=, metadata=)` **before** a Payment exists. Set it, and never trust client amounts |
| `KARNI_PAYMENTS_EVENT_HANDLER` | `karni_payments.services.apply_event` | dotted path the webhook task calls (the state-machine escape hatch) |
| `KARNI_PAYMENTS_ALLOWED_REDIRECTS` | `[]` | extra origins allowed for checkout redirect URLs (on top of `KARNI_FRONTEND_URL`) |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | `""` | validated lazily at provider use |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` / `RAZORPAY_WEBHOOK_SECRET` | `""` | validated lazily at provider use |

## Semantics worth knowing

- **Monotonic state**: `pending → processing → succeeded →
  partially_refunded → refunded`. `failed`/`canceled` are terminal. Events
  that would regress a status are recorded as a `no-op:` note on the
  `WebhookEvent` and count as processed. Expired checkout sessions map to
  `canceled`.
- **Zero-decimal currencies** (JPY, KRW, …) are handled by
  `providers.base.to_minor_units` / `from_minor_units`. Currencies with 3
  decimals (BHD, KWD, …) are unsupported in v0.1 and raise.
- A provider failure during checkout marks the Payment `failed` before
  re-raising. Abandoned pending payments are not reaped in v0.1, so expire
  them yourself if you need to (sessions that expire at the provider arrive
  as webhook events and cancel the payment).
- Razorpay webhooks take their event id from the `X-Razorpay-Event-Id`
  header. Payment Links have a single `callback_url`, so `cancel_url` is
  unused there.

## Testing your project

Set `KARNI_PAYMENTS_PROVIDER = "test"` in test settings:
`TestProvider` is in-memory and deterministic (`test_cs_1`, `test_re_1`, …),
and `TestProvider.build_webhook({...})` returns a correctly signed
`(body, headers)` pair for driving the full webhook pipeline. Call
`TestProvider.reset()` between tests.

## Development

```bash
pip install -e . --group dev
python -m pytest        # standalone suite (sqlite + eager Celery + TestProvider)
ruff check . && ruff format --check .
```

This module is also the reference implementation of the Karni module
contract. See `docs/modules.md` in the Karni repo.
