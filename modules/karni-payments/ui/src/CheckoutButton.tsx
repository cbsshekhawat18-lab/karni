/**
 * <CheckoutButton> — starts a provider checkout for the signed-in user
 * (contract "@karni/payments-ui" + G9).
 *
 * Flow: click → `POST /payments/checkout/` via `useKarniClient().request`
 * (resource-relative; the client's baseUrl carries `/api`) → on success
 * invalidate every `["karni", "payments"]`-rooted cache entry (so
 * <PaymentStatus> and payment tables refresh after the user returns) → hand
 * `session.url` to `navigate`, which defaults to `window.location.assign`.
 *
 * The amount sent here is NEVER authoritative — the backend re-validates via
 * KARNI_PAYMENTS_CHECKOUT_VALIDATOR (G2). See the package README.
 *
 * Escape hatches: every @karni/ui Button prop (variant, size, className, ...)
 * passes through; `navigate` is injectable for tests and client-side routers;
 * `onError` receives the thrown error (a KarniApiError for API failures).
 */
import { Button, karniKeys, useKarniClient, type ButtonProps } from "@karni/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ReactElement } from "react";
import type { CheckoutSession } from "./types";

/** Body of the checkout action (snake_case, as the DRF action expects). */
interface CheckoutRequestBody {
  amount: string | number;
  currency?: string;
  metadata?: Record<string, unknown>;
  success_url: string;
  cancel_url: string;
}

export interface CheckoutButtonProps extends Omit<ButtonProps, "onError" | "onClick"> {
  /** Amount to charge, e.g. "49.00". Display-level only — the server decides (G2). */
  amount: string | number;
  /** Lowercase ISO 4217 code; the backend default (KARNI_PAYMENTS_CURRENCY) applies when omitted. */
  currency?: string;
  /** Stored on the Payment's metadata JSONField. */
  metadata?: Record<string, unknown>;
  /** Where the provider sends the user after a completed checkout. */
  successUrl: string;
  /** Where the provider sends the user after an abandoned checkout. */
  cancelUrl: string;
  /** Called with the thrown error (KarniApiError for non-2xx responses). */
  onError?: (error: unknown) => void;
  /** Redirect strategy; defaults to `window.location.assign`. Inject for tests/routers. */
  navigate?: (url: string) => void;
}

function defaultNavigate(url: string): void {
  window.location.assign(url);
}

export function CheckoutButton(props: CheckoutButtonProps): ReactElement {
  const {
    amount,
    currency,
    metadata,
    successUrl,
    cancelUrl,
    onError,
    navigate,
    children,
    disabled,
    ...buttonProps
  } = props;
  const client = useKarniClient();
  const queryClient = useQueryClient();

  const checkout = useMutation({
    mutationFn: () => {
      const body: CheckoutRequestBody = {
        amount,
        success_url: successUrl,
        cancel_url: cancelUrl,
      };
      if (currency !== undefined) body.currency = currency;
      if (metadata !== undefined) body.metadata = metadata;
      return client.request<CheckoutSession>("/payments/checkout/", {
        method: "POST",
        body,
      });
    },
    onSuccess: async (session) => {
      // Refresh every ["karni", "payments"] cache entry (G9) — never the bare
      // ["karni"] root, which would also nuke the cached OpenAPI schema (D4).
      await queryClient.invalidateQueries({ queryKey: karniKeys.resource("payments") });
      (navigate ?? defaultNavigate)(session.url);
    },
    onError: (error) => {
      onError?.(error);
    },
  });

  return (
    <Button
      data-karni-role="checkout-button"
      {...buttonProps}
      disabled={disabled === true || checkout.isPending}
      onClick={() => {
        checkout.mutate();
      }}
    >
      {children ?? "Checkout"}
    </Button>
  );
}
