/**
 * Shared payment types for @karni/payments-ui.
 *
 * Shapes mirror the karni_payments Django app: Payment is what
 * `GET /api/payments/<id>/` returns (DRF serializes DecimalField as string),
 * CheckoutSession is the body of `POST /api/payments/checkout/`.
 */

/** Payment.status choices of the karni_payments app (closed set, G4). */
export const PAYMENT_STATUSES = [
  "pending",
  "processing",
  "succeeded",
  "failed",
  "canceled",
  "refunded",
  "partially_refunded",
] as const;

export type PaymentStatusValue = (typeof PAYMENT_STATUSES)[number];

/** One payment as serialized by the karni_payments API. */
export interface Payment {
  id: string | number;
  /** DRF DecimalField(12, 2), serialized as a string, e.g. "49.00". */
  amount: string;
  /** Lowercase ISO 4217 code, e.g. "usd". */
  currency: string;
  status: PaymentStatusValue;
  provider?: string;
  provider_payment_id?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

/** Response of the checkout action: the provider session to redirect to. */
export interface CheckoutSession {
  id: string;
  url: string;
}
