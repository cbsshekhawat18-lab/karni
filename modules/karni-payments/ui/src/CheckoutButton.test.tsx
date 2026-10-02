import { KarniApiError } from "@karni/ui";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { API_BASE, checkoutCalls, checkoutSessionFixture, server } from "../tests/msw/server";
import { makeQueryClient, renderWithKarni } from "../tests/test-utils";
import { CheckoutButton } from "./CheckoutButton";

describe("CheckoutButton", () => {
  it("POSTs the checkout action and redirects to the session url", async () => {
    const navigate = vi.fn();
    const user = userEvent.setup();
    renderWithKarni(
      <CheckoutButton
        amount="49.00"
        currency="usd"
        metadata={{ sku: "pro-plan" }}
        successUrl="https://app.example.test/billing/done"
        cancelUrl="https://app.example.test/billing/cancel"
        navigate={navigate}
      >
        Pay now
      </CheckoutButton>,
    );

    await user.click(screen.getByRole("button", { name: "Pay now" }));

    await waitFor(() => expect(navigate).toHaveBeenCalledWith(checkoutSessionFixture.url));
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(checkoutCalls).toHaveLength(1);
    expect(checkoutCalls[0]).toEqual({
      amount: "49.00",
      currency: "usd",
      metadata: { sku: "pro-plan" },
      success_url: "https://app.example.test/billing/done",
      cancel_url: "https://app.example.test/billing/cancel",
    });
  });

  it("calls onError with the KarniApiError and does not redirect on server error", async () => {
    server.use(
      http.post(`${API_BASE}/payments/checkout/`, () =>
        HttpResponse.json({ detail: "Amount rejected" }, { status: 400 }),
      ),
    );
    const navigate = vi.fn();
    const onError = vi.fn();
    const user = userEvent.setup();
    renderWithKarni(
      <CheckoutButton
        amount="49.00"
        successUrl="https://app.example.test/done"
        cancelUrl="https://app.example.test/cancel"
        navigate={navigate}
        onError={onError}
      >
        Pay now
      </CheckoutButton>,
    );

    await user.click(screen.getByRole("button", { name: "Pay now" }));

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    const error = onError.mock.calls[0]?.[0] as KarniApiError;
    expect(error).toBeInstanceOf(KarniApiError);
    expect(error.status).toBe(400);
    expect(error.data).toEqual({ detail: "Amount rejected" });
    expect(navigate).not.toHaveBeenCalled();
  });

  it('invalidates the ["karni", "payments"] invalidation root on success', async () => {
    const queryClient = makeQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const navigate = vi.fn();
    const user = userEvent.setup();
    renderWithKarni(
      <CheckoutButton
        amount="10.00"
        successUrl="https://app.example.test/done"
        cancelUrl="https://app.example.test/cancel"
        navigate={navigate}
      >
        Pay
      </CheckoutButton>,
      { queryClient },
    );

    await user.click(screen.getByRole("button", { name: "Pay" }));

    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ["karni", "payments"] }),
    );
    // Invalidation completes BEFORE the redirect (G9: tables/status refresh).
    const invalidationOrder = invalidateSpy.mock.invocationCallOrder[0];
    const navigateOrder = navigate.mock.invocationCallOrder[0];
    expect(invalidationOrder).toBeLessThan(navigateOrder ?? 0);
  });

  it("composes the @karni/ui Button and forwards button props", async () => {
    const navigate = vi.fn();
    renderWithKarni(
      <CheckoutButton
        amount="10.00"
        successUrl="https://app.example.test/done"
        cancelUrl="https://app.example.test/cancel"
        navigate={navigate}
        variant="outline"
        disabled
      />,
    );

    const button = screen.getByRole("button", { name: "Checkout" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("data-karni-role", "checkout-button");
    expect(button).toHaveAttribute("type", "button");
  });
});
