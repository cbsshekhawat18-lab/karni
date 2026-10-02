/**
 * Simulated karni_payments backend for the test suite (mirrors
 * packages/karni-ui/tests/msw/ conventions).
 *
 * Default behavior: checkout succeeds with a deterministic session, payment
 * detail returns `paymentFixture` under the requested id. Suites override
 * per-test with `server.use(...)`; `resetMswData()` runs after every test.
 */
import { HttpResponse, http } from "msw";
import type { CheckoutSession, Payment } from "../../src/types";

export const API_BASE = "http://localhost/api";

export const checkoutSessionFixture: CheckoutSession = {
  id: "cs_test_1",
  url: "https://pay.example.test/session/cs_test_1",
};

export const paymentFixture: Payment = {
  id: "pay_1",
  amount: "49.00",
  currency: "usd",
  status: "succeeded",
  provider: "test",
  provider_payment_id: "pi_test_1",
  metadata: {},
};

/** Bodies of every checkout POST received since the last reset. */
export const checkoutCalls: unknown[] = [];

export function resetMswData(): void {
  checkoutCalls.length = 0;
}

export const handlers = [
  http.post(`${API_BASE}/payments/checkout/`, async ({ request }) => {
    checkoutCalls.push(await request.json());
    return HttpResponse.json(checkoutSessionFixture);
  }),
  http.get(`${API_BASE}/payments/:id/`, ({ params }) =>
    HttpResponse.json({ ...paymentFixture, id: String(params.id) }),
  ),
];
