/**
 * @karni/payments-ui public barrel.
 *
 * Explicit exports only, mirroring @karni/ui's barrel conventions.
 * Importing the package also feature-detects @karni/ui's component-role
 * registry and registers the payments roles when it exists (G8).
 */
import { registerPaymentRoles } from "./roles";

export { CheckoutButton } from "./CheckoutButton";
export type { CheckoutButtonProps } from "./CheckoutButton";

export { PaymentStatus } from "./PaymentStatus";
export type { PaymentStatusProps } from "./PaymentStatus";

export { PAYMENT_STATUSES } from "./types";
export type { Payment, PaymentStatusValue, CheckoutSession } from "./types";

export { PAYMENT_COMPONENT_ROLES, registerPaymentRoles } from "./roles";
export type { ComponentRoleDefinition } from "./roles";

// G8: silently a no-op until @karni/ui ships registerComponentRole.
registerPaymentRoles();
