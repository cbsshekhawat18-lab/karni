import * as karniUi from "@karni/ui";
import { describe, expect, it, vi } from "vitest";
import { PAYMENT_COMPONENT_ROLES, registerPaymentRoles } from "./roles";

describe("registerPaymentRoles (G8 feature detection)", () => {
  it("registers checkout-button and payment-status on a registry that supports roles", () => {
    const registerComponentRole = vi.fn();
    const registered = registerPaymentRoles({ registerComponentRole });

    expect(registered).toBe(true);
    expect(registerComponentRole).toHaveBeenCalledTimes(2);
    expect(registerComponentRole).toHaveBeenCalledWith(
      "checkout-button",
      expect.objectContaining({ role: "checkout-button", component: "CheckoutButton" }),
    );
    expect(registerComponentRole).toHaveBeenCalledWith(
      "payment-status",
      expect.objectContaining({ role: "payment-status", component: "PaymentStatus" }),
    );
  });

  it("skips silently when the registry lacks registerComponentRole", () => {
    expect(registerPaymentRoles({})).toBe(false);
    expect(registerPaymentRoles(null)).toBe(false);
    expect(registerPaymentRoles("nope")).toBe(false);
  });

  it("does not throw against the installed @karni/ui (with or without the registry)", () => {
    const hasRegistry =
      typeof (karniUi as Record<string, unknown>)["registerComponentRole"] === "function";
    // Phase 9's registerComponentRole has not landed in @karni/ui yet; when it
    // does, the default registration flips to true with no code change here.
    expect(registerPaymentRoles()).toBe(hasRegistry);
  });

  it("describes both roles for manifest consumers", () => {
    expect(PAYMENT_COMPONENT_ROLES.map((definition) => definition.role)).toEqual([
      "checkout-button",
      "payment-status",
    ]);
  });
});
