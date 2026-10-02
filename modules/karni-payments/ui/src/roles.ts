/**
 * Component-role registration (contract G8).
 *
 * The role registry (`registerComponentRole`) ships with a later @karni/ui
 * phase. Per G8 the registration is feature-detected: when the installed
 * @karni/ui exports `registerComponentRole`, both roles are registered at
 * import time; when it does not (older/current @karni/ui), registration is
 * skipped silently. `registerPaymentRoles` is exported as the escape hatch —
 * call it with your own registry object to register the roles elsewhere.
 */
import * as karniUi from "@karni/ui";

export interface ComponentRoleDefinition {
  role: string;
  component: string;
  package: string;
  description: string;
}

export const PAYMENT_COMPONENT_ROLES: readonly ComponentRoleDefinition[] = [
  {
    role: "checkout-button",
    component: "CheckoutButton",
    package: "@karni/payments-ui",
    description: "Starts a provider checkout via POST /payments/checkout/ and redirects.",
  },
  {
    role: "payment-status",
    component: "PaymentStatus",
    package: "@karni/payments-ui",
    description: "Token-styled live status badge for one payment (optionally polling).",
  },
];

type RegisterComponentRole = (role: string, definition: ComponentRoleDefinition) => void;

/**
 * Registers both roles on `registry.registerComponentRole` when present.
 * Returns true when registration happened, false when it was skipped (G8).
 */
export function registerPaymentRoles(registry: unknown = karniUi): boolean {
  if (typeof registry !== "object" || registry === null) return false;
  const candidate = (registry as Record<string, unknown>)["registerComponentRole"];
  if (typeof candidate !== "function") return false;
  for (const definition of PAYMENT_COMPONENT_ROLES) {
    (candidate as RegisterComponentRole)(definition.role, definition);
  }
  return true;
}
