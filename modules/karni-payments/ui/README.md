# @karni/payments-ui

Payments components for Karni backends, composing [`@karni/ui`](https://www.npmjs.com/package/@karni/ui).
Ships two components for the `karni_payments` Django app (`karni add payments`):

- **`CheckoutButton`** — starts a provider checkout (`POST /api/payments/checkout/`) and
  redirects the user to the provider's hosted page.
- **`PaymentStatus`** — live, token-styled status badge + amount for one payment, with
  optional polling while a webhook-driven status settles.

## Install

```bash
npm install @karni/payments-ui @karni/ui @tanstack/react-query
```

Peer dependencies: `react` / `react-dom` (`^18 || ^19`), `@karni/ui` (`^0.1.0`),
`@tanstack/react-query` (`^5`). Note that `@karni/ui` is pre-1.0: 0.x minors may break,
so keep the two packages' versions moving together.

## Setup

Both components read the Karni client from context — wrap your app in
`<KarniProvider>` exactly as described in the
[`@karni/ui` README](https://www.npmjs.com/package/@karni/ui) ("Provider setup"):

```tsx
import { KarniProvider, createKarniClient } from "@karni/ui";

const client = createKarniClient({ baseUrl: "/api" });

export function App() {
  return <KarniProvider client={client}>{/* ... */}</KarniProvider>;
}
```

The components call resource-relative paths (`/payments/checkout/`,
`/payments/<id>/`); the client's `baseUrl` carries the `/api` prefix.

## Never trust client amounts

The `amount` you pass to `CheckoutButton` is a **display-level convenience, not an
authorization**. Anyone can open the dev tools and send a different amount. The
`karni_payments` backend is the authority: set `KARNI_PAYMENTS_CHECKOUT_VALIDATOR`
(or override the checkout action) so the server derives or verifies the amount for
the signed-in user before a `Payment` is created. Ship nothing to production that
charges whatever the browser asked for.

## CheckoutButton

```tsx
import { CheckoutButton } from "@karni/payments-ui";

<CheckoutButton
  amount="49.00"
  currency="usd"
  metadata={{ sku: "pro-plan" }}
  successUrl="https://app.example.com/billing/done"
  cancelUrl="https://app.example.com/billing/cancel"
  onError={(error) => toast({ title: "Checkout failed" })}
>
  Upgrade — $49
</CheckoutButton>;
```

| Prop                       | Type                       | Notes                                                                                             |
| -------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------- |
| `amount`                   | `string \| number`         | Sent to the checkout action. Server-validated (see above).                                        |
| `currency?`                | `string`                   | Falls back to the backend's `KARNI_PAYMENTS_CURRENCY`.                                            |
| `metadata?`                | `Record<string, unknown>`  | Stored on `Payment.metadata`.                                                                     |
| `successUrl` / `cancelUrl` | `string`                   | Validated server-side against allowed origins (G2).                                               |
| `onError?`                 | `(error: unknown) => void` | Receives a `KarniApiError` for non-2xx responses.                                                 |
| `navigate?`                | `(url: string) => void`    | Redirect strategy; defaults to `window.location.assign`. Inject for tests or client-side routers. |
| ...`ButtonProps`           |                            | Every `@karni/ui` `Button` prop (`variant`, `size`, `className`, `disabled`, ...) passes through. |

On success the button invalidates every `["karni", "payments"]`-rooted query
(`karniKeys.resource("payments")`), so `PaymentStatus` badges and payment tables
refresh, then redirects to `session.url`.

## PaymentStatus

```tsx
import { PaymentStatus } from "@karni/payments-ui";

<PaymentStatus paymentId={payment.id} poll={3000} />;
```

| Prop                                  | Type                                        | Notes                                                                                      |
| ------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `paymentId`                           | `string \| number`                          | Fetched via `useResourceItem("payments", id)`.                                             |
| `poll?`                               | `false \| number`                           | `false` (default) fetches once; a number maps to TanStack Query's `refetchInterval` in ms. |
| `className?`                          | `string`                                    | Merged onto the wrapper.                                                                   |
| `statusLabels?` / `statusClassNames?` | per-status overrides                        | i18n / theming hatches.                                                                    |
| `formatAmount?`                       | `(payment) => string`                       | Replaces the default `Intl.NumberFormat` currency rendering.                               |
| `loadingFallback?` / `errorFallback?` | `ReactNode` (error also accepts a function) | Replace the skeleton / error message.                                                      |
| `children?`                           | `(payment) => ReactNode`                    | Full render override.                                                                      |

Styling is design-token-only (`bg-muted`, `bg-primary`, `bg-destructive`,
`bg-secondary`, ...), so the badge follows any `--karni-*` theme override and dark
mode automatically.

## Component roles

On import the package feature-detects `registerComponentRole` on `@karni/ui` and
registers the `"checkout-button"` and `"payment-status"` roles when the registry
exists; on older `@karni/ui` versions it silently skips (G8). `registerPaymentRoles`
and `PAYMENT_COMPONENT_ROLES` are exported for manual registration.

## Local development (monorepo)

`@karni/ui` is resolved via `file:../../../packages/karni-ui` for local installs.
Because a fresh checkout has no built `dist/` in `packages/karni-ui`, the tsconfig
and vitest config alias `@karni/ui` straight to its source — `npm install` followed
by `npm test` works without building `@karni/ui` first.

```bash
npm install
npm run typecheck
npm test
npm run lint
```
